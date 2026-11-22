"""Suite E7, conversations with a played client (docs/08 E7):
python -m dawalink.evals.run_conversations --model claude-haiku-5-5 --max-usd 1.50

A second model plays the client (`played_client.py`): one persona per case of the U-set
that the agent can serve, in four ways of telling (everything at once, half, only the
medicine, one answer at a time). The agent answers in the frozen world of suite E1. A
conversation ends when the agent shows something to reserve, when the client leaves, or
after `MAX_CLIENT_MESSAGES`.

It costs money twice: the agent's turns and the playing model's messages. `--max-usd` is
a hard stop for both together. The conversations, the traces and the scores are saved in
`eval/results/` (decision log BLD-D19).
"""

import argparse
import json
import sys
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session, sessionmaker

from dawalink.agent.llm import ChatModel
from dawalink.agent.llm.base import LLMError, cost_usd, has_price
from dawalink.agent.prompts import PROMPT_VERSION
from dawalink.agent.tracing import Tracer
from dawalink.agent.turn import Agent
from dawalink.config import ConfigError, load_settings
from dawalink.db.models import InventoryItem
from dawalink.db.session import make_engine
from dawalink.domain.clock import Clock, ManualClock, at_beirut
from dawalink.domain.numbers import DAILY_SPEND_CAP_SHARE
from dawalink.evals.budget import EvaluationModel
from dawalink.evals.catalog_match import CatalogNames
from dawalink.evals.checkpoint import save_case, stop_requested
from dawalink.evals.datasets import DATASETS, UCase, read
from dawalink.evals.played_client import STYLES, Line, Persona, next_message, personas
from dawalink.evals.review import review_flags
from dawalink.evals.run_understanding import (
    AT,
    SEED,
    TODAY,
    _spread,
    _turns_by_chat,
    ask,
    observed,
    shelves_for,
    write,
)
from dawalink.evals.score_conversations import CHECKS, Exchange, has_cards, score
from dawalink.evals.score_understanding import rates
from dawalink.observability.logging import configure_logging
from dawalink.services.context import unit_of_work
from dawalink.services.travel import shared_location
from dawalink.sim import database, save, travel_table, world

DATABASE = f"{database.PREFIX}_conversations_{uuid.uuid4().hex[:12]}"
MAX_CLIENT_MESSAGES = 6
# The share of `--max-usd` the playing model may spend; the rest is the agent's.
CLIENT_SHARE = Decimal("0.25")


def converse(
    agent: Agent,
    client_model: ChatModel,
    persona: Persona,
    who: world.SimClient,
    folder: Path,
) -> tuple[list[Exchange], str, Decimal]:
    """One conversation. Returns its exchanges, how it ended, and what the playing model
    cost. Ends: `cards`, `client_left`, `too_long`, or the agent's status when a turn
    didn't run (the spend cap, the model down)."""
    exchanges: list[Exchange] = []
    lines: list[Line] = []
    spent = Decimal(0)
    chat_id = None
    for _ in range(MAX_CLIENT_MESSAGES):
        try:
            said = next_message(client_model, persona, lines)
        except LLMError:
            # Preserve preceding exchanges and the failed conversation. Provider
            # request/failure details and any unknown charge remain in the ledger.
            return exchanges, "client_provider_failure", spent
        spent += cost_usd(client_model.name, said.usage)
        if said.left:
            return exchanges, "client_left", spent
        if chat_id is None:
            chat_id, result, kinds = ask(
                agent, who.id, shared_location(who.lat, who.lon), said.text
            )
        else:
            result, kinds = write(agent, who.id, chat_id, said.text)
        traced = _turns_by_chat(folder).get(str(chat_id), [])
        if len(traced) <= len(exchanges):
            return exchanges, result.status.value, spent
        seen = observed(agent, traced[-1], kinds, result)
        exchanges.append(Exchange(said.text, said.says, seen))
        lines += [
            Line("you", said.text),
            Line("assistant", seen.reply, cards=len(seen.cards)),
        ]
        if has_cards(seen):
            return exchanges, "cards", spent
    return exchanges, "too_long", spent


def _row(
    persona: Persona,
    exchanges: Sequence[Exchange],
    ended: str,
    client_cost: Decimal,
    catalog: CatalogNames,
) -> dict[str, Any]:
    gold = persona.case.gold
    return {
        "id": persona.id,
        "case": persona.case.id,
        "lang": persona.case.lang,
        "style": persona.style,
        "opens_with": list(persona.opens_with),
        "truth": {
            "on_foot": persona.truth.on_foot,
            "pickup_in_days": persona.truth.pickup_in_days,
            "days_of_use": persona.truth.days_of_use,
        },
        "ended": ended,
        "client_messages": len(exchanges),
        "exchanges": [
            {
                "client": exchange.said,
                "says": list(exchange.says),
                "agent": exchange.seen.reply,
                "cards": list(exchange.seen.cards),
                "card_items": list(exchange.seen.card_items),
                "card_groups": list(exchange.seen.card_groups),
                "outcome": exchange.seen.outcome,
                "review": review_flags(exchange.seen.reply, persona.case.lang),
                "tools": [tool.name for tool in exchange.seen.tools],
                "seconds": exchange.seen.seconds,
            }
            for exchange in exchanges
        ],
        "checks": score(
            persona,
            exchanges,
            products=[[str(p) for p in catalog.products_for(i.match)] for i in gold.items],
            today=TODAY,
        ),
        "agent_cost_usd": round(sum(e.seen.cost_usd for e in exchanges), 6),
        "client_cost_usd": float(client_cost),
    }


def run(
    people: Sequence[Persona],
    *,
    sessions: sessionmaker[Session],
    clock: Clock,
    model: ChatModel,
    client_model: ChatModel,
    tracer: Tracer,
    folder: Path,
    clients: Sequence[world.SimClient],
    max_usd: Decimal,
) -> list[dict[str, Any]]:
    """Every persona's conversation, scored: one row each, in the personas' order."""
    agent = Agent(
        sessions,
        clock,
        model,
        tracer=tracer,
        monthly_budget_usd=max_usd * (1 - CLIENT_SHARE) * 100 / DAILY_SPEND_CAP_SHARE,
    )
    with unit_of_work(sessions, clock) as tx:
        catalog = CatalogNames.load(tx.session)
    if len(people) > len(clients):
        # One chat per client: a second persona in the same chat would read the first's.
        raise ValueError(f"{len(people)} personas need as many clients; there are {len(clients)}")
    rows: list[dict[str, Any]] = []
    client_spent = Decimal(0)
    for position, persona in enumerate(people):
        if stop_requested():
            print("Stopped before the next played conversation", flush=True)
            break
        try:
            exchanges, ended, cost = converse(
                agent, client_model, persona, clients[position % len(clients)], folder
            )
        except LLMError as error:
            print(f"stopped at {persona.id}: the playing model failed ({error})", flush=True)
            break
        client_spent += cost
        rows.append(_row(persona, exchanges, ended, cost, catalog))
        save_case(folder, rows[-1])
        if ended not in ("cards", "client_left", "too_long"):
            print(f"stopped at {persona.id}: {ended}", flush=True)
            break
        if client_spent > max_usd * CLIENT_SHARE:
            print(f"stopped at {persona.id}: the playing model's share is spent", flush=True)
            break
    return rows


def summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    turns = [exchange for row in rows for exchange in row["exchanges"]]
    by_style = {}
    for style in STYLES:
        mine = [row for row in rows if row["style"] == style]
        with_cards = [row["client_messages"] for row in mine if row["ended"] == "cards"]
        by_style[style] = {
            "conversations": len(mine),
            "ended_with_cards": len(with_cards),
            "client_messages_to_cards": round(sum(with_cards) / max(1, len(with_cards)), 2),
        }
    return {
        "prompt_version": PROMPT_VERSION,
        "conversations": len(rows),
        "ended": dict(Counter(row["ended"] for row in rows)),
        "by_style": by_style,
        "turns_that_only_answer": _spread([t["seconds"] for t in turns if not t["cards"]]),
        "turns_with_cards": _spread([t["seconds"] for t in turns if t["cards"]]),
        "agent_cost_usd": round(sum(row["agent_cost_usd"] for row in rows), 6),
        "client_cost_usd": round(sum(row["client_cost_usd"] for row in rows), 6),
        "checks": rates([row["checks"] for row in rows], CHECKS),
    }


def _write(folder: Path, rows: Sequence[dict[str, Any]], about: dict[str, Any]) -> dict[str, Any]:
    result = about | summary(rows)
    result["cost_usd"] = round(result["agent_cost_usd"] + result["client_cost_usd"], 6)
    save.write_artifacts(
        folder,
        {
            "conversations.jsonl": "".join(
                json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in rows
            ),
            "summary.json": json.dumps(result, indent=2) + "\n",
        },
    )
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(
        f"{result['conversations']} conversations, ${result['cost_usd']} "
        f"(agent ${result['agent_cost_usd']}, client ${result['client_cost_usd']}), "
        f"saved in {folder}"
    )
    print(f"  ended: {result['ended']}")
    for check, good in CHECKS.items():
        line = result["checks"][check]
        if line["cases"]:
            want = "" if good else "  (lower is better)"
            print(
                f"  {check:24s} {line['yes']:3d} of {line['cases']:3d}  {line['share']:.0%}{want}"
            )
    for style, line in result["by_style"].items():
        print(
            f"  {style:14s} {line['ended_with_cards']:3d} of {line['conversations']:3d} got "
            f"cards, after {line['client_messages_to_cards']} client messages on average"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--model", required=True, help="the agent's Claude model (paid)")
    parser.add_argument("--client-model", help="the model that plays the client (paid)")
    parser.add_argument("--effort", default="medium", choices=("low", "medium", "high"))
    parser.add_argument("--max-usd", type=Decimal, required=True, help="the most it may cost")
    parser.add_argument("--limit", type=int, help="only the first N personas")
    parser.add_argument("--cases", help="only these cases' personas: 'U-0004,U-0039'")
    parser.add_argument("--lang", help="only the personas of this language")
    parser.add_argument("--keep", action="store_true", help="keep the run's database")
    arguments = parser.parse_args()
    playing = arguments.client_model or arguments.model

    settings = load_settings()
    configure_logging("WARNING")
    if settings.app_env == "test" or settings.anthropic_api_key is None:
        raise ConfigError("This run needs ANTHROPIC_API_KEY, outside the tests.")
    for name in {arguments.model, playing}:
        if not has_price(name):
            raise ConfigError(f"{name} has no price in dawalink/agent/llm/base.py.")
    cases = read(DATASETS / "understanding.jsonl", UCase)
    people = personas(cases)
    only = set((arguments.cases or "").split(",")) - {""}
    if only or arguments.lang:
        people = [
            p
            for p in people
            if (not only or p.case.id in only) and arguments.lang in (None, p.case.lang)
        ]
    people = people[: arguments.limit]
    served = [persona.case for persona in people]
    name = f"{date.today().isoformat()}_conversations_dev_{arguments.model}"
    part = "_part" if only or arguments.lang or arguments.limit else ""
    folder = save.RESULTS / f"{name}_prompt-{PROMPT_VERSION}{part}"

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
            connection.execute(insert(InventoryItem), shelves_for(served, known, lands, TODAY))
    finally:
        migrator.dispose()
    key = settings.anthropic_api_key.get_secret_value()
    app = make_engine(where.app)
    try:
        rows = run(
            people,
            sessions=sessionmaker(app, expire_on_commit=False),
            clock=ManualClock(now),
            model=EvaluationModel(api_key=key, model=arguments.model, effort=arguments.effort),
            client_model=EvaluationModel(api_key=key, model=playing, effort="low"),
            tracer=save.FileTracer(folder),
            folder=folder,
            clients=lands.clients,
            max_usd=arguments.max_usd,
        )
    finally:
        app.dispose()
        if not arguments.keep:
            database.drop(settings, DATABASE)

    _write(folder, rows, {"model": arguments.model, "client_model": playing, "part": "dev"})


if __name__ == "__main__":
    main()
