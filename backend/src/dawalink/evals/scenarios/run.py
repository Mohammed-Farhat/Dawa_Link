"""Suite E8, scenarios (docs/08): python -m dawalink.evals.scenarios.run \\
    --lang all --model claude-haiku-5-5 --judge-model claude-sonnet-5-5 --max-usd 5

Every scenario of `cases/` is played once per language (English, Arabizi, Arabic), each
in a database of its own: a copy of the simulation's template with the simulated
pharmacies and clients, empty shelves, and the Ministry's no-prescription marks. The
scenario fills the shelves it needs.

It costs money three times: the agent's turns, the played client's messages and the
judge. `--max-usd` is one hard limit for all three (`spend.py`). The rows, the traces
and a summary are saved in `eval/results/`, one folder per language.
"""

import argparse
import json
import os
import queue
import statistics
import sys
import threading
import time
import traceback
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from dawalink.agent.llm.base import has_price
from dawalink.agent.llm.claude import ClaudeModel
from dawalink.agent.prompts import PROMPT_VERSION
from dawalink.agent.turn import Agent
from dawalink.api.main import create_app
from dawalink.config import ConfigError, Settings, load_settings
from dawalink.db.session import make_engine
from dawalink.domain.clock import ManualClock
from dawalink.domain.numbers import DAILY_SPEND_CAP_SHARE
from dawalink.evals.scenarios import cases, checks, faults
from dawalink.evals.scenarios.client_model import LANGS, Brief, Lang
from dawalink.evals.scenarios.judge import judge
from dawalink.evals.scenarios.scenario import Scenario
from dawalink.evals.scenarios.spend import Metered, Spend
from dawalink.evals.scenarios.stage import Stage, StageError, start_of
from dawalink.observability.logging import configure_logging
from dawalink.ops.import_catalog import refresh_marks_from_folder
from dawalink.sim import database, save, travel_table, world

# The most one scenario's agent may spend: the app's own daily cap, per database.
USD_PER_SCENARIO = Decimal("0.75")
SEED = 1
TEMPLATE_TRIES = 12
# The simulated clients are called "Sim Client 001". The app removes a client's own name
# from what they write and from the agent's notes, each part as a whole word: with that
# name the ordinary word "client" became "[name]" in the notes the model reads back. In a
# scenario's own database they get a name no sentence contains.
RENAME_CLIENTS = (
    "UPDATE users SET full_name = 'Zqsim Xvcl' || right(full_name, 3) WHERE role = 'client'"
)
# Automatic checks a story of this kind breaks on purpose.
NOT_AUTOMATIC = {"tool_failure": ("tool_calls_succeed", "turn_ended_normally")}
_database_lock = threading.Lock()
_file_lock = threading.Lock()


@dataclass(frozen=True)
class Models:
    key: str
    agent: str
    effort: str
    client: str
    judge: str | None


@dataclass(frozen=True)
class Job:
    scenario: Scenario
    lang: Lang
    rep: int

    @property
    def key(self) -> str:
        return f"{self.scenario.id}__{self.lang}__r{self.rep}"


def folder_for(lang: Lang, model: str, suffix: str) -> Path:
    name = f"{date.today().isoformat()}_scenarios_{lang}_{model}_prompt-{PROMPT_VERSION}{suffix}"
    return save.RESULTS / name


def _fresh(settings: Settings, name: str) -> database.Addresses:
    """A new database for one scenario. Another run on this computer may be copying the
    template at the same moment, which PostgreSQL refuses: then it is tried again."""
    for attempt in range(1, TEMPLATE_TRIES + 1):
        try:
            with _database_lock:
                return database.fresh(settings, name)
        except DBAPIError:
            if attempt == TEMPLATE_TRIES:
                raise
            time.sleep(1.5 * attempt)
    raise AssertionError("unreachable")


def _template(settings: Settings) -> None:
    """The template database, made once. Two runs that start together on one computer
    both try to prepare it, and PostgreSQL refuses one of them: then it is tried again."""
    for attempt in range(1, TEMPLATE_TRIES + 1):
        try:
            database.ensure_template(settings)
            return
        except DBAPIError:
            if attempt == TEMPLATE_TRIES:
                raise
            time.sleep(2.0 * attempt)


def play(
    job: Job,
    slot: int,
    *,
    settings: Settings,
    lands: world.World,
    table: Any,
    models: Models,
    spend: Spend,
    folder: Path,
) -> dict[str, Any]:
    """One scenario, in one language, from an empty database to its scored row."""
    scenario, started = job.scenario, time.monotonic()
    # The process's number is in the name: two runs at once never share a database.
    name = f"{database.PREFIX}_scn_{os.getpid()}_{slot}"
    now = start_of(scenario.day, scenario.at)
    where = _fresh(settings, name)
    migrator = create_engine(where.migrator)
    app_engine = make_engine(where.app)
    row: dict[str, Any] = {
        "id": scenario.id,
        "family": scenario.family,
        "kind": scenario.kind,
        "lang": job.lang,
        "rep": job.rep,
        "prescription": scenario.prescription,
        "title": scenario.title,
        "expected": scenario.expected,
        "rules": list(scenario.rules),
        "error": None,
    }
    try:
        with migrator.begin() as connection:
            world.populate(
                connection,
                lands,
                seed=SEED,
                now=now,
                road_times=travel_table.cache_rows(table, lands, now=now) if table else (),
                stock=False,
            )
            refresh_marks_from_folder(connection)
            connection.execute(text(RENAME_CLIENTS))
        sessions = sessionmaker(app_engine, expire_on_commit=False)
        clock = ManualClock(now)
        traces = folder / "traces" / job.key
        agent_model = Metered(
            ClaudeModel(api_key=models.key, model=models.agent, effort=models.effort),  # type: ignore[arg-type]
            spend,
            "agent",
        )
        flaky = faults.FlakyModel(agent_model)
        client_model = Metered(
            ClaudeModel(api_key=models.key, model=models.client, effort="low"), spend, "client"
        )
        agent = Agent(
            sessions,
            clock,
            flaky,
            routing=faults.DownRouting() if scenario.routing == "down" else None,
            tracer=save.FileTracer(traces),
            monthly_budget_usd=USD_PER_SCENARIO * 100 / DAILY_SPEND_CAP_SHARE,
        )
        app = create_app(
            settings.model_copy(update={"database_url": where.app, "log_level": "ERROR"}),
            agent=agent,
            clock=clock,
            sessions=sessions,
        )
        stage: Stage | None = None
        with TestClient(app, headers={"Origin": settings.website_url}) as http:
            try:
                stage = Stage(
                    lang=job.lang,
                    http=http,
                    sessions=sessions,
                    setup_sessions=sessionmaker(migrator, expire_on_commit=False),
                    clock=clock,
                    agent=agent,
                    lands=lands,
                    client_model=client_model,
                    flaky=flaky,
                    traces=traces,
                    brief=Brief(scenario.facts, scenario.manner),
                    client_district=scenario.client_district,
                )
                scenario.play(stage)
            except StageError as error:
                row["error"] = f"harness: {error}"
            except Exception:
                row["error"] = "crash: " + traceback.format_exc(limit=6)
            finally:
                faults.mend_play(sessions)
        if stage is not None:
            authored = [asdict(check) for check in stage.checks]
            skipped = {*scenario.not_automatic, *NOT_AUTOMATIC.get(scenario.kind, ())}
            automatic = [
                asdict(check)
                for check in checks.for_turns(job.lang, stage.turns)
                if check.id not in skipped
            ]
            replies = [turn for turn in stage.turns if turn.agent_turns]
            row |= {
                "checks": authored,
                "auto_checks": automatic,
                "passed": row["error"] is None
                and bool(authored)
                and all(check["ok"] for check in authored),
                "transcript": stage.transcript,
                "agent_turns": sum(turn.agent_turns for turn in replies),
                "model_calls": sum(turn.model_calls for turn in replies),
                "tool_calls": sum(len(turn.tools) for turn in replies),
                "tool_errors": sum(1 for turn in replies for tool in turn.tools if not tool.ok),
                "turn_seconds": [
                    round(turn.seconds / max(1, turn.agent_turns), 2) for turn in replies
                ],
                "client_left": stage.client.left,
            }
            if models.judge and row["error"] is None and replies:
                judge_model = Metered(
                    ClaudeModel(api_key=models.key, model=models.judge, effort="low"),
                    spend,
                    "judge",
                )
                verdict = judge(
                    judge_model,
                    title=scenario.title,
                    kind=scenario.kind,
                    expected=scenario.expected,
                    lang=job.lang,
                    transcript=stage.transcript,
                )
                row["judge"] = verdict.as_row()
                row["judge_cost_usd"] = float(judge_model.usd)
        row["agent_cost_usd"] = float(agent_model.usd)
        row["client_cost_usd"] = float(client_model.usd)
    except Exception:
        row["error"] = "harness: " + traceback.format_exc(limit=6)
    finally:
        migrator.dispose()
        app_engine.dispose()
        with _database_lock:
            database.drop(settings, name)
    row["seconds"] = round(time.monotonic() - started, 1)
    row["budget_ran_out"] = spend.spent
    return row


def _spread(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "median": round(statistics.median(ordered), 2),
        "p95": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 2),
        "max": round(ordered[-1], 2),
    }


def _rate(rows: Sequence[dict[str, Any]], where: str) -> dict[str, dict[str, Any]]:
    """Checks passed out of checks made, by level and by family."""
    counts: dict[str, dict[str, list[int]]] = {"level": {}, "family": {}}
    for row in rows:
        for check in row.get(where) or []:
            for by in ("level", "family"):
                cell = counts[by].setdefault(check[by], [0, 0])
                cell[0] += int(check["ok"])
                cell[1] += 1
    return {
        by: {
            name: {"ok": ok, "of": total, "share": round(ok / total, 3)}
            for name, (ok, total) in sorted(cells.items())
        }
        for by, cells in counts.items()
    }


def summary(rows: Sequence[dict[str, Any]], about: dict[str, Any]) -> dict[str, Any]:
    played = [row for row in rows if row.get("error") is None and "checks" in row]
    passed = [row for row in played if row["passed"]]

    def by(field: str) -> dict[str, str]:
        names = sorted({row[field] for row in played})
        return {
            name: f"{sum(1 for r in passed if r[field] == name)} of "
            f"{sum(1 for r in played if r[field] == name)}"
            for name in names
        }

    judged = [row["judge"] for row in played if row.get("judge") and row["judge"]["scores"]]
    cost = sum(
        row.get(part, 0)
        for row in rows
        for part in ("agent_cost_usd", "client_cost_usd", "judge_cost_usd")
    )
    return about | {
        "prompt_version": PROMPT_VERSION,
        "scenarios": len(rows),
        "played": len(played),
        "harness_errors": [row["id"] for row in rows if row.get("error")],
        "passed": len(passed),
        "passed_by_kind": by("kind"),
        "passed_by_family": by("family"),
        "passed_by_prescription": by("prescription"),
        "checks": _rate(played, "checks"),
        "auto_checks": _rate(played, "auto_checks"),
        "judge": {
            "scenarios": len(judged),
            "accepted": sum(1 for verdict in judged if verdict["passed"]),
            "mean_scores": {
                name: round(statistics.mean(v["scores"][name] for v in judged), 2)
                for name in (judged[0]["scores"] if judged else {})
            },
        },
        "agent_turn_seconds": _spread([s for row in played for s in row["turn_seconds"]]),
        "model_calls_per_turn": round(
            sum(row["model_calls"] for row in played)
            / max(1, sum(row["agent_turns"] for row in played)),
            2,
        ),
        "tool_calls": sum(row["tool_calls"] for row in played),
        "tool_errors": sum(row["tool_errors"] for row in played),
        "cost_usd": round(cost, 4),
        "agent_cost_usd": round(sum(row.get("agent_cost_usd", 0) for row in rows), 4),
        "cost_per_passed_scenario_usd": round(cost / len(passed), 4) if passed else None,
    }


def _done(folder: Path) -> dict[str, dict[str, Any]]:
    path = folder / "scenarios.jsonl"
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {f"{row['id']}__{row['lang']}__r{row['rep']}": row for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--model", required=True, help="the agent's Claude model (paid)")
    parser.add_argument("--effort", default="medium", choices=("low", "medium", "high"))
    parser.add_argument("--client-model", help="the model that plays the client (paid)")
    parser.add_argument("--judge-model", help="the model that judges; none: no judge")
    parser.add_argument("--max-usd", type=Decimal, required=True, help="the most it may cost")
    parser.add_argument("--lang", default="all", choices=("all", *LANGS))
    parser.add_argument("--only", help="only these scenarios: 'find.rx_clear,team.reply'")
    parser.add_argument("--family", help="only these families: 'find,team'")
    parser.add_argument("--repeat", type=int, default=1, help="play each scenario N times")
    parser.add_argument("--workers", type=int, default=4, help="scenarios played at once")
    parser.add_argument("--suffix", default="", help="added to the result folders' names")
    parser.add_argument("--resume", action="store_true", help="keep the rows already saved")
    arguments = parser.parse_args()

    settings = load_settings()
    configure_logging("ERROR")
    if settings.app_env == "test" or settings.anthropic_api_key is None:
        raise ConfigError("This run needs ANTHROPIC_API_KEY, outside the tests.")
    models = Models(
        key=settings.anthropic_api_key.get_secret_value(),
        agent=arguments.model,
        effort=arguments.effort,
        client=arguments.client_model or arguments.model,
        judge=arguments.judge_model,
    )
    for name in {models.agent, models.client, models.judge} - {None}:
        if not has_price(str(name)):
            raise ConfigError(f"{name} has no price in dawalink/agent/llm/base.py.")
    only = set((arguments.only or "").split(",")) - {""}
    families = set((arguments.family or "").split(",")) - {""}
    chosen = [
        scenario
        for scenario in cases.all_scenarios()
        if (not only or scenario.id in only) and (not families or scenario.family in families)
    ]
    langs: tuple[Lang, ...] = LANGS if arguments.lang == "all" else (arguments.lang,)
    suffix = f"_{arguments.suffix}" if arguments.suffix else ""
    folders = {lang: folder_for(lang, models.agent, suffix) for lang in langs}
    rows: dict[Lang, dict[str, dict[str, Any]]] = {}
    for lang, folder in folders.items():
        folder.mkdir(parents=True, exist_ok=True)
        rows[lang] = _done(folder) if arguments.resume else {}
        if not arguments.resume:
            (folder / "scenarios.jsonl").write_text("", encoding="utf-8")
    jobs = [
        Job(scenario, lang, rep)
        for rep in range(1, arguments.repeat + 1)
        for scenario in chosen
        for lang in langs
        if Job(scenario, lang, rep).key not in rows[lang]
    ]
    spend = Spend(arguments.max_usd)
    faults.install()
    lands = world.load()
    table = travel_table.read()
    _template(settings)
    slots: queue.Queue[int] = queue.Queue()
    for slot in range(arguments.workers):
        slots.put(slot)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(f"{len(jobs)} runs of {len(chosen)} scenarios, at most ${arguments.max_usd}", flush=True)

    def work(job: Job) -> None:
        if spend.spent:
            return
        slot = slots.get()
        try:
            row = play(
                job,
                slot,
                settings=settings,
                lands=lands,
                table=table,
                models=models,
                spend=spend,
                folder=folders[job.lang],
            )
        finally:
            slots.put(slot)
        with _file_lock:
            rows[job.lang][job.key] = row
            with (folders[job.lang] / "scenarios.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            mark = "ERROR" if row["error"] else ("pass" if row.get("passed") else "FAIL")
            failed = [c["id"] for c in row.get("checks") or [] if not c["ok"]]
            print(
                f"{mark:5s} {job.key:60s} ${float(spend.total):6.3f}  {row['seconds']:5.1f}s  "
                + (row["error"].splitlines()[-1][:120] if row["error"] else ", ".join(failed)),
                flush=True,
            )

    with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
        list(pool.map(work, jobs))

    for lang, folder in folders.items():
        result = summary(
            list(rows[lang].values()),
            {
                "lang": lang,
                "model": models.agent,
                "effort": models.effort,
                "client_model": models.client,
                "judge_model": models.judge,
                "part": "dev",
            },
        )
        (folder / "summary.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(
            f"{lang}: {result['passed']} of {result['played']} scenarios passed, "
            f"${result['cost_usd']}, saved in {folder}"
        )
    print(f"spent ${float(spend.total):.3f}: {spend.by_part()}")
    if spend.spent:
        print("STOPPED: the run's budget was reached; the rows after it are missing or cut short.")


if __name__ == "__main__":
    main()
