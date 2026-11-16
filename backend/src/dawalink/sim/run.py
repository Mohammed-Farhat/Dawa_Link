"""Runs simulated days: python -m dawalink.sim.run --contender search --seeds 1-5

One run is one contender on one seed: a fresh database, the seed's world, the day played
through the real services, and the results (docs/08 §6). The search baseline and the no-AI
policy cost nothing.

The agent is the only contender that costs money, and only when asked for by name:
`--contender agent --model claude-haiku-5-5 --max-usd 0.50`. `--max-usd` is a hard stop: it
becomes the app's own daily spend cap (docs/04 N-46), so when the day has cost that much
the agent stops taking turns, as it would in the app. A run with `--save`, and every run of
the agent, leaves its evidence in `eval/results/` (`sim/save.py`).
"""

import argparse
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from datetime import time as clock_time
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dawalink.agent.llm import ChatModel
from dawalink.agent.llm.base import has_price
from dawalink.agent.llm.claude import ClaudeModel
from dawalink.config import ConfigError, Settings, load_settings
from dawalink.db.models import Product
from dawalink.db.session import make_engine
from dawalink.domain.clock import ManualClock, at_beirut
from dawalink.domain.numbers import DAILY_SPEND_CAP_SHARE
from dawalink.observability.logging import configure_logging
from dawalink.sim import database, engine, measure, save, scenario, travel_table, world
from dawalink.sim.contenders.ablations import VARIANTS, Without
from dawalink.sim.contenders.rules import RulesModel
from dawalink.sim.contenders.search_baseline import SearchBaseline
from dawalink.sim.contenders.with_requests import WithRequests
from dawalink.sim.engine import Contender, Sim
from dawalink.sim.measure import NeedResult
from dawalink.sim.params import Params

CONTENDERS: dict[str, Callable[[], Contender]] = {
    "search": SearchBaseline,
    "rules": lambda: WithRequests("rules", RulesModel()),
    # The same rules behind one question, as the product now asks first (BLD-D28).
    "rules_asking": lambda: WithRequests("rules_asking", RulesModel(asks_first=True)),
}
AGENT = "agent"


def the_agent(
    settings: Settings,
    model: str,
    effort: str,
    max_usd: Decimal,
    folder: Path,
    without: str | None = None,
) -> Contender:
    """The agent of `07` on a Claude model, with a hard stop on what the day may cost.
    `without` takes one ability away (docs/08 E3, `contenders/ablations.py`)."""
    if settings.app_env == "test":
        raise ConfigError("A test must not build a real model. Use a scripted one.")
    if settings.anthropic_api_key is None:
        raise ConfigError("ANTHROPIC_API_KEY is not set.")
    if not has_price(model):
        raise ConfigError(f"{model} has no price in dawalink/agent/llm/base.py.")
    if effort not in ("low", "medium", "high"):
        raise ConfigError("--effort is low, medium or high.")
    claude: ChatModel = ClaudeModel(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=model,
        effort=effort,  # type: ignore[arg-type]
    )
    return WithRequests(
        AGENT,
        Without(claude, without) if without else claude,
        # The whole simulated day is one day: its cap is this share of the month's budget.
        monthly_budget_usd=max_usd * 100 / DAILY_SPEND_CAP_SHARE,
        tracer=save.FileTracer(folder),
    )


STARTS_AT = clock_time(7, 0)  # the day's clock starts before the first request


@dataclass(frozen=True)
class Run:
    contender: str
    seed: int
    needs: list[NeedResult]
    summary: dict[str, float | int]
    refusals: dict[str, int]
    turns: dict[str, float | int]
    room: dict[str, int]
    seconds: float


def _products(migrator_url: str) -> tuple[dict[Any, int], dict[Any, str], dict[Any, int]]:
    """Public prices, medicines (groups of brands) and Ministry codes of the whole catalog."""
    migrator = create_engine(migrator_url)
    try:
        with migrator.connect() as connection:
            rows = connection.execute(select(Product)).all()
    finally:
        migrator.dispose()
    prices = {row.id: row.public_price_lbp for row in rows}
    medicine_of = {row.id: row.equivalence_key or f"product:{row.id}" for row in rows}
    return prices, medicine_of, {row.id: row.moph_code for row in rows}


def one(
    settings: Settings,
    contender_name: str,
    seed: int,
    params: Params,
    *,
    keep: bool = False,
    contender: Contender | None = None,
    folder: Path | None = None,
    model: str | None = None,
) -> Run:
    """One contender on one seed, on a database of its own. `keep` leaves that database
    in place when the day is over, to look at what happened. With a `folder`, the run's
    evidence is written there before the database goes."""
    started = time.perf_counter()
    name = f"{database.PREFIX}_{contender_name}_{seed}"
    where = database.fresh(settings, name)
    now = at_beirut(params.day, STARTS_AT)
    lands = world.load()
    table = travel_table.read()
    migrator = create_engine(where.migrator)
    try:
        with migrator.begin() as connection:
            populated = world.populate(
                connection,
                lands,
                seed=seed,
                now=now,
                road_times=travel_table.cache_rows(table, lands, now=now) if table else (),
                early_release_share=params.early_release_share,
            )
    finally:
        migrator.dispose()
    prices, medicine_of, code_of = _products(where.migrator)
    app = make_engine(where.app)
    try:
        sim = Sim(
            seed=seed,
            params=params,
            world=lands,
            scenario=scenario.build(seed, lands, populated.demand, medicine_of, params),
            sessions=sessionmaker(app, expire_on_commit=False),
            clock=ManualClock(now),
            prices=prices,
            medicine_of=medicine_of,
            code_of=code_of,
        )
        engine.play(sim, contender or CONTENDERS[contender_name]())
        needs = measure.results(sim)
        turns = measure.turns(sim)
        room = measure.room_for_early_release(sim)
        if folder is not None:
            save.write(
                folder,
                contender=contender_name,
                model=model,
                seed=seed,
                params=params,
                summary=measure.summary(needs),
                needs=measure.as_rows(needs),
                said=save.threads(sim),
                more={"refused": dict(sim.refusals), "turns": turns, "room": room},
            )
    finally:
        app.dispose()
    if not keep:
        database.drop(settings, name)
    return Run(
        contender_name,
        seed,
        needs,
        measure.summary(needs),
        dict(sim.refusals),
        turns,
        room,
        round(time.perf_counter() - started, 1),
    )


def _seeds(text: str) -> list[int]:
    if "-" in text:
        first, last = text.split("-")
        return list(range(int(first), int(last) + 1))
    return [int(part) for part in text.split(",")]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contender", choices=sorted([*CONTENDERS, AGENT]), required=True)
    parser.add_argument("--model", help="the Claude model the agent runs on (paid)")
    parser.add_argument("--effort", default="medium")
    parser.add_argument("--without", choices=VARIANTS, help="the agent minus one ability")
    parser.add_argument("--max-usd", type=Decimal, help="the most a day of the agent may cost")
    parser.add_argument("--save", action="store_true", help="keep the evidence in eval/results/")
    parser.add_argument("--seeds", default="1", help="'1', '1-5' or '1,3,4'")
    parser.add_argument("--requests", type=int, default=Params().requests)
    parser.add_argument("--not-available", type=float, default=Params().not_available)
    parser.add_argument("--keep", action="store_true", help="keep the run's database")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="ASSUMPTION=VALUE",
        help="another value for an assumption of sim/params.py, e.g. answers_ask=0.2",
    )
    arguments = parser.parse_args()
    configure_logging("WARNING")
    logging.getLogger("alembic").setLevel(logging.WARNING)
    params = Params().but(requests=arguments.requests, not_available=arguments.not_available)
    changed = dict(change.split("=", 1) for change in arguments.set)
    params = params.but(**{name: float(value) for name, value in changed.items()})
    label = "_".join(f"{name}-{value}" for name, value in sorted(changed.items()))
    settings = load_settings()
    paid = arguments.contender == AGENT
    if paid and (arguments.model is None or arguments.max_usd is None):
        parser.error("the agent needs --model and --max-usd: it spends the API credit")
    if not paid and (arguments.model is not None or arguments.without is not None):
        parser.error("--model and --without are for --contender agent")
    # An ablation is a contender of its own: its own database, folder and name.
    name = f"{AGENT}_without_{arguments.without}" if arguments.without else arguments.contender
    for seed in _seeds(arguments.seeds):
        model = arguments.model if paid else None
        folder = (
            save.folder_for(name, model, seed, params, on=date.today())
            if paid or arguments.save
            else None
        )
        if folder is not None and label:
            folder = folder.with_name(f"{folder.name}_{label}")
        run = one(
            settings,
            name,
            seed,
            params,
            keep=arguments.keep,
            contender=the_agent(
                settings, model, arguments.effort, arguments.max_usd, folder, arguments.without
            )
            if paid and model and folder
            else None,
            folder=folder,
            model=model,
        )
        if folder is not None:
            print("saved in", folder)
        print(
            json.dumps(
                {"contender": run.contender, "seed": seed, "seconds": run.seconds} | run.summary
            )
        )
        if run.refusals:
            print("  refused:", json.dumps(run.refusals))
        if run.turns:
            print("  turns:", json.dumps(run.turns))
        # Flushed, so each seed shows as soon as its day is over, also into a file.
        print("  room:", json.dumps(run.room), flush=True)


if __name__ == "__main__":
    main()
