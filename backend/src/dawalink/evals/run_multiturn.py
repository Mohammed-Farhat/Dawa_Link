"""Fixed development conversations: corrections and partial answers, without a paid client.

Uses the unchanged agent and shared spending ledger. This is separate from E7's
model-played client; predetermined messages do not adapt to the assistant's replies.
"""

import argparse
import json
import uuid
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field
from sqlalchemy import create_engine, insert
from sqlalchemy.orm import Session, sessionmaker

from dawalink.agent.turn import Agent
from dawalink.config import ConfigError, load_settings
from dawalink.db.models import InventoryItem
from dawalink.db.session import make_engine
from dawalink.domain.clock import ManualClock, at_beirut
from dawalink.domain.numbers import DAILY_SPEND_CAP_SHARE
from dawalink.evals.budget import EvaluationModel
from dawalink.evals.catalog_match import CatalogNames
from dawalink.evals.datasets import CaseBase, Gold, Strict, UCase, read
from dawalink.evals.review import review_flags
from dawalink.evals.run_understanding import (
    AT,
    SEED,
    TODAY,
    _turns_by_chat,
    ask,
    observed,
    shelves_for,
    write,
)
from dawalink.evals.score_understanding import (
    RESERVE_CARDS,
    Seen,
    acted,
    asked_a_question,
    score,
)
from dawalink.services.travel import shared_location
from dawalink.sim import database, save, travel_table, world

CASES = Path("../eval/datasets/multiturn.jsonl")


class Step(Strict):
    text: str = Field(min_length=1, max_length=1000)
    gold: Gold  # cumulative facts after this message; corrections replace old values
    behavior: Literal["clarify", "propose", "reply"]


class MCase(CaseBase):
    id: str = Field(pattern=r"^M-\d{4}$")
    lang: Literal["english", "arabic", "arabizi", "mixed"]
    purpose: str
    turns: list[Step] = Field(min_length=2, max_length=20)
    author: str
    checked_by: str | None = None


class Client(Protocol):
    @property
    def id(self) -> uuid.UUID: ...

    @property
    def lat(self) -> float: ...

    @property
    def lon(self) -> float: ...


def ucase(case: MCase, step: Step, index: int) -> UCase:
    return UCase(
        id=f"U-{index:04d}",
        lang=case.lang,
        category="clear",
        text=step.text,
        gold=step.gold,
        author=case.author,
    )


def checked(step: Step, seen: Seen, facts: dict[str, bool | None]) -> dict[str, bool | None]:
    result: dict[str, bool | None] = {"execution_ok": seen.outcome == "ok" and bool(seen.reply)}
    if not result["execution_ok"]:
        return result
    if step.behavior == "clarify":
        result["clarifies_before_action"] = asked_a_question(seen) and not acted(seen)
    elif step.behavior == "propose":
        result["gives_proposal"] = bool(set(seen.cards) & RESERVE_CARDS)
        result.update(facts)
    return result


def converse(
    agent: Agent,
    case: MCase,
    who: Client,
    folder: Path,
    catalog: CatalogNames,
    lbp_per_usd: int,
) -> dict[str, Any]:
    exchanges: list[dict[str, Any]] = []
    chat = None
    for n, step in enumerate(case.turns, 1):
        if chat is None:
            chat, result, kinds = ask(agent, who.id, shared_location(who.lat, who.lon), step.text)
        else:
            result, kinds = write(agent, who.id, chat, step.text)
        traces = _turns_by_chat(folder).get(str(chat), [])
        seen = (
            observed(agent, traces[-1], kinds, result)
            if len(traces) == n
            else Seen("", outcome=result.status.value)
        )
        # Only this turn's actions/cards are judged against the current cumulative
        # truth. Earlier correct actions must not satisfy a later correction.
        facts = score(
            ucase(case, step, n),
            seen,
            products=[[str(p) for p in catalog.products_for(i.match)] for i in step.gold.items],
            today=TODAY,
            lbp_per_usd=lbp_per_usd,
        )
        exchanges.append(
            {
                "client": step.text,
                "gold": step.gold.model_dump(),
                "behavior": step.behavior,
                **asdict(seen),
                "checks": checked(step, seen, facts),
                "review": review_flags(seen.reply, case.lang),
            }
        )
        if seen.outcome != "ok":
            break
    return {
        "id": case.id,
        "lang": case.lang,
        "purpose": case.purpose,
        "expected_turns": len(case.turns),
        "exchanges": exchanges,
        "outcome": "ok"
        if len(exchanges) == len(case.turns) and all(e["outcome"] == "ok" for e in exchanges)
        else "incomplete",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="medium", choices=("low", "medium", "high"))
    parser.add_argument("--max-usd", type=Decimal, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    settings = load_settings()
    if settings.app_env == "test" or settings.anthropic_api_key is None:
        raise ConfigError("Paid evaluation requires an explicit key outside tests")
    cases = read(CASES, MCase)[: args.limit]
    lands = world.load()
    if len(cases) > len(lands.clients):
        raise ValueError("Each conversation requires a separate synthetic client")
    name = f"{database.PREFIX}_multiturn_{uuid.uuid4().hex[:12]}"
    where = database.fresh(settings, name)
    clock = ManualClock(at_beirut(TODAY, AT))
    folder = save.RESULTS / f"multiturn_{uuid.uuid4().hex[:12]}"
    migrator = create_engine(where.migrator)
    try:
        with migrator.begin() as connection:
            table = travel_table.read()
            world.populate(
                connection,
                lands,
                seed=SEED,
                now=clock.now(),
                road_times=travel_table.cache_rows(table, lands, now=clock.now()) if table else (),
            )
            catalog = CatalogNames.load(Session(bind=connection))
            labels = [ucase(c, s, n) for c in cases for n, s in enumerate(c.turns, 1)]
            connection.execute(insert(InventoryItem), shelves_for(labels, catalog, lands, TODAY))
    finally:
        migrator.dispose()
    app = make_engine(where.app)
    try:
        from dawalink.agent.tools.base import rate
        from dawalink.services.context import unit_of_work

        sessions = sessionmaker(app, expire_on_commit=False)
        with unit_of_work(sessions, clock) as tx:
            lbp_per_usd = int(rate(tx) or 0)
        model = EvaluationModel(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=args.model,
            effort=args.effort,
        )
        agent = Agent(
            sessions,
            clock,
            model,
            tracer=save.FileTracer(folder),
            monthly_budget_usd=args.max_usd * 100 / DAILY_SPEND_CAP_SHARE,
        )
        rows = []
        for case, who in zip(cases, lands.clients, strict=False):
            row = converse(agent, case, who, folder, catalog, lbp_per_usd)
            rows.append(row)
            if row["outcome"] != "ok":
                break
        save.write_artifacts(
            folder,
            {
                "conversations.jsonl": "".join(save._line(row) for row in rows),
                "summary.json": json.dumps(
                    {"conversations": len(rows), "not_ok": sum(r["outcome"] != "ok" for r in rows)}
                )
                + "\n",
            },
        )
        print("saved in", folder)
    finally:
        app.dispose()
        database.drop(settings, name)


if __name__ == "__main__":
    main()
