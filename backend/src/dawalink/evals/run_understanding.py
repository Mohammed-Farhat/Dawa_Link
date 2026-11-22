"""Suite E1, understanding (docs/08 E1): python -m dawalink.evals.run_understanding \\
    --model claude-haiku-5-5 --max-usd 1.00

Each case of the U-set is sent as the first message of a new chat, by a client of its own,
in a frozen world: the simulated world of seed 1, on Monday 2026-11-16 at 10:00 in Beirut.
What the agent did is read from the turn's trace and scored (`score_understanding.py`).

It costs money: one turn of the agent per case. `--max-usd` is a hard stop, through the
app's own daily spend cap (docs/04 N-46). The answers, the traces and the scores are saved
in `eval/results/` (decision log BLD-D19).

It reads `eval/datasets/understanding.jsonl`. The held-out file is read only when
`--heldout` is given, which only the final run's session does.
"""

import argparse
import json
import math
import statistics
import sys
import uuid
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import date, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import Session, sessionmaker

from dawalink.agent.chat import post_client_message
from dawalink.agent.llm import ChatModel
from dawalink.agent.llm.base import has_price
from dawalink.agent.prompts import PROMPT_VERSION
from dawalink.agent.tools.base import rate
from dawalink.agent.tracing import Tracer
from dawalink.agent.turn import Agent, TurnResult, run_turn
from dawalink.config import ConfigError, load_settings
from dawalink.db.models import InventoryItem, Proposal
from dawalink.db.session import make_engine
from dawalink.domain.clock import Clock, ManualClock, at_beirut
from dawalink.domain.numbers import DAILY_SPEND_CAP_SHARE
from dawalink.evals.budget import EvaluationModel
from dawalink.evals.catalog_match import CatalogNames
from dawalink.evals.dataset_selection import fixed_cases
from dawalink.evals.datasets import DATASETS, HELDOUT, UCase, read
from dawalink.evals.review import review_flags
from dawalink.evals.score_understanding import (
    CHECKS,
    Answer,
    Seen,
    answer_of,
    asked_a_question,
    left_out_first,
    rates,
    score,
    seen_in,
    together,
    wants_an_answer,
)
from dawalink.observability.logging import configure_logging
from dawalink.services import conversations
from dawalink.services.context import unit_of_work
from dawalink.services.travel import Location, shared_location
from dawalink.sim import database, save, travel_table, world

TODAY = date(2026, 11, 16)  # the Monday every case is written for (LABELING_GUIDE.md)
AT = time(10, 0)
SEED = 1
DATABASE = f"{database.PREFIX}_understanding_{uuid.uuid4().hex[:12]}"


# Days until expiry of the boxes put on shelves for a case's medicine: most last a
# month's treatment, one doesn't, so the expiry fit has something to refuse.
SHELF_DAYS = (45, 120, 160, 25)


def shelves_for(
    cases: Sequence[UCase], catalog: CatalogNames, lands: world.World, today: date
) -> list[dict[str, Any]]:
    """Every case's medicines on four shelves: two in its client's district, two elsewhere.

    The seed's world stocks what simulated clients ask for, which isn't what the cases
    name. Without these boxes every answer would be "not listed", and proposing a pharmacy
    would never be exercised.
    """
    items: dict[tuple[int, uuid.UUID], dict[str, Any]] = {}
    for position, case in enumerate(cases):
        client = lands.clients[position % len(lands.clients)]
        near = [p for p in lands.pharmacies if p.district == client.district]
        far = [p for p in lands.pharmacies if p.district != client.district]
        places = [*near[:2], *far[position % len(far) :][:2]]
        for item in case.gold.items:
            for product in sorted(catalog.products_for(item.match), key=str)[:1]:
                for pharmacy, days in zip(places, SHELF_DAYS, strict=False):
                    items.setdefault(
                        (pharmacy.n, product),
                        {
                            "id": uuid.uuid5(world.NAMESPACE, f"u-{pharmacy.n}-{product}"),
                            "pharmacy_id": pharmacy.id,
                            "product_id": product,
                            "batch": f"U-{pharmacy.n}-{len(items)}",
                            "expiry_date": today + timedelta(days=days),
                            "qty_on_hand": 3,
                            "last_edited_at": at_beirut(today, AT),
                        },
                    )
    return list(items.values())


# The client's answer to the agent's question, in the case's language: how they get
# there, the day, the days of use. The facts come from the case's labels (`answer_of`).
ANSWERS: dict[str, dict[str, Any]] = {
    "english": {
        "car": "I have a car.",
        "foot": "I don't have a car, I'll go on foot.",
        "day": ("I'll come today.", "I'll come tomorrow.", "I'll come the day after tomorrow."),
        "days": "I'll take it for {n} days.",
    },
    "arabizi": {
        "car": "3ande siyyara.",
        "foot": "ma 3ande siyyara, bade rou7 mashi.",
        "day": ("bade eje lyom.", "bade eje bukra.", "bade eje ba3d bukra."),
        "days": "bade ekhdo la {n} ayyam.",
    },
    "arabic": {
        "car": "عندي سيارة.",
        "foot": "ما عندي سيارة، بروح مشي.",
        "day": ("بجي اليوم.", "بجي بكرا.", "بجي بعد بكرا."),
        "days": "باخد الدوا {n} أيام.",
    },
}


def words_of(
    answer: Answer, lang: str, *, only: str | None = None, without: str | None = None
) -> str:
    """One message that answers everything the agent may have asked: the transport, the
    day, the days of use. `without` leaves one of the three out; `only` says just that one."""
    words = ANSWERS.get(lang, ANSWERS["arabizi"])  # "mixed" is mostly Arabizi
    parts = {
        "transport": words["foot"] if answer.on_foot else words["car"],
        "day": words["day"][answer.pickup_in_days],
        "days": words["days"].format(n=answer.days_of_use),
    }
    return " ".join(
        said for what, said in parts.items() if what != without and only in (None, what)
    )


def write(
    agent: Agent, client_id: uuid.UUID, chat_id: uuid.UUID, text: str
) -> tuple[TurnResult, list[str]]:
    """The client writes one message in their chat and the agent answers it. Returns what
    the turn did and the kinds of the cards under the reply."""
    with unit_of_work(agent.sessions, agent.clock) as tx:
        post_client_message(
            tx,
            client_id=client_id,
            conversation_id=chat_id,
            text=text,
            client_message_id=uuid.uuid4(),
        )
    result = run_turn(agent, chat_id, runs_in="chat")
    with agent.sessions() as session:
        kinds = dict(
            session.execute(
                select(Proposal.id, Proposal.kind).where(Proposal.id.in_(result.proposal_ids))
            ).all()
        )
    return result, [kinds[card] for card in result.proposal_ids if card in kinds]


def observed(agent: Agent, traced: dict[str, Any], kinds: list[str], result: TurnResult) -> Seen:
    """Attach the actual displayed proposal contents, not merely their card kinds."""
    with agent.sessions() as session:
        cards = session.execute(
            select(Proposal).where(Proposal.id.in_(result.proposal_ids))
        ).scalars()
        items = []
        by_id = {}
        for card in cards:
            if card.kind == "reserve":
                items.append(card.payload)
                by_id[str(card.id)] = [card.payload]
            elif card.kind == "reserve_group":
                items.extend(card.payload.get("items", []))
                by_id[str(card.id)] = card.payload.get("items", [])
    seen = seen_in(traced, kinds)
    groups = []
    assigned = set()
    for tool in seen.tools:
        if tool.name != "propose_plan" or not tool.ok:
            continue
        data = json.loads(tool.answer)
        ids = [str(p["proposal_id"]) for p in data.get("proposals", [])]
        group = [item for key in ids if key in by_id for item in by_id[key]]
        if group:
            groups.append(group)
            assigned.update(ids)
    groups.extend(value for key, value in by_id.items() if key not in assigned)
    return replace(seen, card_items=items, card_groups=groups)


def ask(
    agent: Agent, client_id: uuid.UUID, location: Location, text: str
) -> tuple[uuid.UUID, TurnResult, list[str]]:
    """One client opens the assistant, shares their location and writes one message.
    Returns the chat, what the turn did, and the kinds of the cards under the reply."""
    with unit_of_work(agent.sessions, agent.clock) as tx:
        chat = conversations.active_chat(tx, client_id)
        chat.loc_lat, chat.loc_lon = location.point.lat, location.point.lon
        chat.loc_source, chat.loc_set_at = "shared", tx.now
        chat_id = chat.id
    result, kinds = write(agent, client_id, chat_id, text)
    return chat_id, result, kinds


def _turns_by_chat(folder: Path) -> dict[str, list[dict[str, Any]]]:
    """A run's traced turns, by chat, in the order they ran."""
    found: dict[str, list[dict[str, Any]]] = {}
    for line in (folder / "turns.jsonl").read_text(encoding="utf-8").splitlines():
        turn = json.loads(line)
        found.setdefault(str(turn["metadata"].get("conversation_id")), []).append(turn)
    return found


def _row(
    case: UCase,
    turns: Sequence[Seen],
    *,
    said: str | None,
    chat: str | None,
    status: str,
    catalog: CatalogNames,
    lbp_per_usd: int,
    left_out: str | None = None,
) -> dict[str, Any]:
    """One case's line of `answers.jsonl`: what was written, turn by turn, and the checks.
    `left_out` is what the client's first answer didn't say, when it was partial."""
    whole = together(turns)
    checks = score(
        case,
        whole,
        products=[[str(p) for p in catalog.products_for(i.match)] for i in case.gold.items],
        today=TODAY,
        lbp_per_usd=lbp_per_usd,
        first=turns[0] if len(turns) > 1 else None,
        after_partial=turns[1] if left_out and len(turns) > 1 else None,
    )
    return {
        "id": case.id,
        "lang": case.lang,
        "category": case.category,
        "text": case.text,
        "expected": case.gold.expected,
        "status": status,
        "chat": chat,
        "client_answer": said,
        "left_out": left_out,
        "turns": [
            {
                "reply": turn.reply,
                "cards": list(turn.cards),
                "seconds": turn.seconds,
                "outcome": turn.outcome,
            }
            for turn in turns
        ],
        "checks": checks,
        "review": review_flags(whole.reply, case.lang),
        **asdict(whole),
    }


def run(
    cases: Sequence[UCase],
    *,
    sessions: sessionmaker[Session],
    clock: Clock,
    model: ChatModel,
    tracer: Tracer,
    folder: Path,
    clients: Sequence[world.SimClient],
    max_usd: Decimal,
) -> list[dict[str, Any]]:
    """Every case answered and scored: one row per case, in the cases' order. When the
    agent asks before it searches, the case's client answers and the agent goes on. One
    client in four answers all but one thing first (`left_out_first`), and says the rest
    when the agent asks for it."""
    agent = Agent(
        sessions,
        clock,
        model,
        tracer=tracer,
        monthly_budget_usd=max_usd * 100 / DAILY_SPEND_CAP_SHARE,
    )
    with unit_of_work(sessions, clock) as tx:
        catalog = CatalogNames.load(tx.session)
        lbp_per_usd = int(rate(tx) or 0)
    rows: list[dict[str, Any]] = []
    for position, case in enumerate(cases):
        client = clients[position % len(clients)]
        chat_id, result, kinds = ask(
            agent, client.id, shared_location(client.lat, client.lon), case.text
        )
        traced = _turns_by_chat(folder).get(str(chat_id), [])
        turns = [observed(agent, traced[-1], kinds, result)] if traced else []
        said = left_out = None
        expected = 1
        if turns and wants_an_answer(case, turns[0]):
            answer, left_out = answer_of(case.gold), left_out_first(case)
            said = words_of(answer, case.lang, without=left_out)
            messages = [said]
            while messages:
                result, kinds = write(agent, client.id, chat_id, messages.pop())
                expected += 1
                traced = _turns_by_chat(folder).get(str(chat_id), [])
                if len(traced) < expected:
                    break
                turns.append(observed(agent, traced[-1], kinds, result))
                if left_out and expected == 2 and asked_a_question(turns[-1]):
                    # Asked for what the first answer left out: now the client says it.
                    messages.append(words_of(answer, case.lang, only=left_out))
        ran = len(turns) == expected
        rows.append(
            _row(
                case,
                turns or [Seen(reply="", outcome=result.status.value)],
                said=said,
                chat=str(chat_id),
                status=result.status.value,
                catalog=catalog,
                lbp_per_usd=lbp_per_usd,
                left_out=left_out,
            )
        )
        if not ran:
            # A turn didn't run: the spend cap, or the model is down. What is done is kept.
            print(f"stopped at {case.id}: {result.status.value}", flush=True)
            break
    return rows


def rescore(folder: Path, cases: Sequence[UCase], catalog: CatalogNames, lbp_per_usd: int) -> None:
    """Scores a saved run again, from its traces: after a scorer changed, nothing is paid
    twice. A run saved before the second turn existed has one turn per case, in order."""
    by_id = {case.id: case for case in cases}
    lines = (folder / "answers.jsonl").read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    by_chat = _turns_by_chat(folder)
    in_order = [
        json.loads(line)
        for line in (folder / "turns.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for position, row in enumerate(rows):
        if row.get("chat"):
            cards = [turn["cards"] for turn in row["turns"]]
            traced = by_chat.get(row["chat"], [])[: len(cards)]
            turns = [seen_in(turn, kinds) for turn, kinds in zip(traced, cards, strict=False)]
        elif position < len(in_order):
            turns = [seen_in(in_order[position], row.get("cards") or [])]
        else:
            turns = []
        if not turns:
            continue
        turns[-1] = replace(
            turns[-1], card_items=row.get("card_items", []), card_groups=row.get("card_groups", [])
        )
        rows[position] = _row(
            by_id[row["id"]],
            turns,
            said=row.get("client_answer"),
            chat=row.get("chat"),
            status=row["status"],
            catalog=catalog,
            lbp_per_usd=lbp_per_usd,
            left_out=row.get("left_out"),
        )
    destination = folder.with_name(folder.name + "_rescore_" + uuid.uuid4().hex[:12])
    destination.mkdir(exist_ok=False)
    _write(destination, rows, json.loads((folder / "summary.json").read_text(encoding="utf-8")))


def _write(folder: Path, rows: Sequence[dict[str, Any]], about: dict[str, Any]) -> dict[str, Any]:
    """The answers and the summary of a run, written and printed."""
    result = about | summary(rows, model=about["model"])
    if "prompt_version" in about:
        # Scoring a saved run again: it keeps the prompt it ran on, not today's.
        result["prompt_version"] = about["prompt_version"]
    save.write_artifacts(
        folder,
        {
            "answers.jsonl": "".join(
                json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows
            ),
            "summary.json": json.dumps(result, indent=2) + "\n",
        },
    )
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(f"{result['cases']} cases, ${result['cost_usd']}, saved in {folder}")
    for check, good in CHECKS.items():
        line = result["checks"][check]
        if line["cases"]:
            want = "" if good else "  (lower is better)"
            share = f"{line['share']:.0%}"
            print(f"  {check:20s} {line['yes']:3d} of {line['cases']:3d}  {share}{want}")
    return result


def _spread(seconds: Sequence[float]) -> dict[str, float | int]:
    """How long turns took: how many, the middle one, and the 95th of 100."""
    ordered = sorted(seconds) or [0.0]
    return {
        "turns": len(seconds),
        "seconds_p50": statistics.median(ordered),
        "seconds_p95": ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)],
    }


def summary(rows: Sequence[dict[str, Any]], *, model: str) -> dict[str, Any]:
    # A row saved before the second turn existed is one turn.
    turns = [
        turn
        for row in rows
        for turn in row.get("turns") or [{"seconds": row["seconds"], "cards": row["cards"]}]
    ]
    every = _spread([turn["seconds"] for turn in turns])
    return {
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "cases": len(rows),
        "turns": every["turns"],
        "cost_usd": round(sum(row["cost_usd"] for row in rows), 6),
        "seconds_p50": every["seconds_p50"],
        "seconds_p95": every["seconds_p95"],
        # The speed target is per kind of turn (docs/08 E1): one that only answers or asks,
        # and one that shows cards.
        "turns_that_only_answer": _spread([t["seconds"] for t in turns if not t["cards"]]),
        "turns_with_cards": _spread([t["seconds"] for t in turns if t["cards"]]),
        "model_calls_per_turn": round(
            sum(row["model_calls"] for row in rows) / max(1, len(turns)), 2
        ),
        "not_ok": sum(1 for row in rows if row["outcome"] != "ok"),
        "checks": rates([row["checks"] for row in rows]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--model", help="the Claude model (paid)")
    parser.add_argument("--rescore", type=Path, help="score a saved run again (free)")
    parser.add_argument("--effort", default="medium", choices=("low", "medium", "high"))
    parser.add_argument("--max-usd", type=Decimal, help="the most the run may cost")
    parser.add_argument("--cases", default="", help="comma-separated fixed case IDs")
    parser.add_argument("--limit", type=int, help="only the first N cases")
    parser.add_argument(
        "--heldout", action="store_true", help="the held-out file (final runs only)"
    )
    parser.add_argument("--keep", action="store_true", help="keep the run's database")
    arguments = parser.parse_args()

    settings = load_settings()
    configure_logging("WARNING")
    if arguments.rescore is not None:
        cases = read((HELDOUT if arguments.heldout else DATASETS) / "understanding.jsonl", UCase)
        # A database of its own, only to read the catalog's names: a run in progress keeps its own.
        names = f"{DATABASE}_names"
        where = database.fresh(settings, names)
        engine = make_engine(where.app)
        try:
            with unit_of_work(sessionmaker(engine), ManualClock(at_beirut(TODAY, AT))) as tx:
                catalog, money = CatalogNames.load(tx.session), int(rate(tx) or 0)
        finally:
            engine.dispose()
            database.drop(settings, names)
        rescore(arguments.rescore, cases, catalog, money)
        return
    if arguments.model is None or arguments.max_usd is None:
        parser.error("a run needs --model and --max-usd: it spends the API credit")
    if settings.app_env == "test" or settings.anthropic_api_key is None:
        raise ConfigError("This run needs ANTHROPIC_API_KEY, outside the tests.")
    if not has_price(arguments.model):
        raise ConfigError(f"{arguments.model} has no price in dawalink/agent/llm/base.py.")
    source = (HELDOUT if arguments.heldout else DATASETS) / "understanding.jsonl"
    cases = fixed_cases(read(source, UCase), arguments.cases)[: arguments.limit]
    part = "heldout" if arguments.heldout else "dev"
    name = f"{date.today().isoformat()}_understanding_{part}_{arguments.model}"
    effort = "" if arguments.effort == "medium" else f"_effort-{arguments.effort}"
    folder = save.RESULTS / f"{name}_prompt-{PROMPT_VERSION}{effort}"

    folder = folder.with_name(folder.name + "_" + uuid.uuid4().hex[:12])
    now = at_beirut(TODAY, AT)
    where = database.fresh(settings, DATABASE)
    lands = world.load()
    table = travel_table.read()
    migrator = create_engine(where.migrator)
    try:
        with migrator.begin() as connection:
            world.populate(
                connection,
                lands,
                seed=SEED,
                now=now,
                road_times=travel_table.cache_rows(table, lands, now=now) if table else (),
            )
            known = CatalogNames.load(Session(bind=connection))
            connection.execute(insert(InventoryItem), shelves_for(cases, known, lands, TODAY))
    finally:
        migrator.dispose()
    app = make_engine(where.app)
    try:
        rows = run(
            cases,
            sessions=sessionmaker(app, expire_on_commit=False),
            clock=ManualClock(now),
            model=EvaluationModel(
                api_key=settings.anthropic_api_key.get_secret_value(),
                model=arguments.model,
                effort=arguments.effort,
            ),
            tracer=save.FileTracer(folder),
            folder=folder,
            clients=lands.clients,
            max_usd=arguments.max_usd,
        )
    finally:
        app.dispose()
        if not arguments.keep:
            database.drop(settings, DATABASE)

    _write(folder, rows, {"model": arguments.model, "file": source.name, "part": part})


if __name__ == "__main__":
    main()
