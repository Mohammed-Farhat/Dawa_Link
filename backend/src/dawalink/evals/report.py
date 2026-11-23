"""The evaluation's tables, from the saved runs: python -m dawalink.evals.report

Reads every folder of `eval/results/` and prints, as Markdown:
- **the simulation** (docs/08 E2): for each contender, the units secured within the window
  with a 95% interval, and each contender against plain search and against the policy with
  no AI on the same clients (a paired difference);
- **the ablations** (E3): the agent minus one ability, against the whole agent on the same
  clients, model and prompt;
- **understanding** (E1) and **safety** (E4): the latest run of each prompt version;
- **conversations with a played client** (E7): every saved run.

It costs nothing and calls nothing: the numbers are the ones the runs saved. With `--write`
the same text goes to `eval/results/REPORT.md`.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from dawalink.evals import charts, stats
from dawalink.evals.played_client import STYLES
from dawalink.evals.score_conversations import CHECKS as CONVERSATION_CHECKS
from dawalink.evals.score_understanding import CHECKS
from dawalink.sim import save
from dawalink.sim.params import Params
from dawalink.sim.sweep import RANGES

Day = dict[tuple[int, int], dict[str, Any]]  # (seed, need) -> that need's result
ABLATION = "agent_without_"  # a day of the agent minus one ability (`sim/run.py --without`)


def _base_day(config: dict[str, Any]) -> bool:
    """A full day on the base assumptions: not a pilot, not a sweep."""
    base, params = Params(), config["params"]
    if params.get("requests") != base.requests:
        return False
    return all(params.get(name, getattr(base, name)) == getattr(base, name) for name in RANGES)


SLOW_ANSWERS = " [the client answered after 5 to 30 min]"


def _answered_slowly(config: dict[str, Any]) -> bool:
    """A day saved before 2026-11-15's change (build plan Q35), by a contender that asks:
    its client took 5 to 30 minutes to answer a question, where it now takes 1 to 3. Such
    a day is never mixed with the newer ones. Before prompt v1.9 the client didn't answer
    at all, and those days keep their name."""
    if "answers_after_min" in config["params"]:
        return False
    if config["contender"] == "rules_asking":
        return True
    version = str(config.get("prompt_version") or "")
    return version.startswith("v1.") and int(version.removeprefix("v1.")) >= 9


def simulation(results: Path) -> dict[str, Day]:
    """Every contender's full days on the base assumptions, by contender and prompt."""
    days: dict[str, Day] = defaultdict(dict)
    for folder in sorted(results.iterdir()):
        if not (folder / "needs.jsonl").exists():
            continue
        config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
        if not _base_day(config):
            continue
        name = config["contender"]
        if config.get("model"):
            name = f"{name} ({config['model']}, prompt {config['prompt_version']})"
        if _answered_slowly(config):
            name += SLOW_ANSWERS
        for line in (folder / "needs.jsonl").read_text(encoding="utf-8").splitlines():
            need = json.loads(line)
            key = (config["seed"], need["n"])
            if key in days[name]:
                raise ValueError(
                    "Repeated contender/seed/need; select one immutable run explicitly"
                )
            days[name][key] = need
    return days


def _numbers(day: Day, keys: list[tuple[int, int]], field: str) -> list[float]:
    return [float(day[key][field]) for key in keys]


def simulation_table(days: dict[str, Day]) -> list[str]:
    lines = [
        "| Contender | Seeds | Requests | Units secured within the window | Fully served | "
        "Against search, same clients | Against the no-AI policy, same clients | "
        "Against the no-AI policy that asks first, same clients |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, day in sorted(days.items()):
        if name.startswith(ABLATION):
            continue  # in its own table, against the whole agent
        keys = sorted(day)
        wanted = _numbers(day, keys, "units_wanted")
        secured = _numbers(day, keys, "units_secured")
        served = [float(day[key]["fulfilled"]) for key in keys]
        cells = [
            name,
            ", ".join(str(seed) for seed in sorted({seed for seed, _ in keys})),
            str(len(keys)),
            f"{int(sum(secured))} of {int(sum(wanted))}: {stats.share(secured, wanted)}",
            str(stats.share(served, [1.0] * len(keys))),
        ]
        # A day played with the slower answers is compared with the asking policy's days
        # played the same way.
        asking = "rules_asking" + (SLOW_ANSWERS if name.endswith(SLOW_ANSWERS) else "")
        for other in ("search", "rules", asking):
            both = sorted(set(day) & set(days.get(other, {})))
            if name == other or not both:
                cells.append("-")
                continue
            gap = stats.clustered_difference(
                _numbers(day, both, "units_secured"),
                _numbers(days[other], both, "units_secured"),
                _numbers(day, both, "units_wanted"),
                [seed for seed, _ in both],
            )
            verdict = "" if gap.excludes_zero else " *(not a clear difference)*"
            cells.append(f"{gap.value:+.1%} ({gap.low:+.1%} to {gap.high:+.1%}){verdict}")
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def ablation_table(days: dict[str, Day]) -> list[str]:
    """The agent minus one ability, against the whole agent: same clients, model, prompt."""
    lines = [
        "| The agent without | Seeds | Units secured within the window | The whole agent, "
        "same clients | What the ability adds |",
        "|---|---|---|---|---|",
    ]
    for name, day in sorted(days.items()):
        if not name.startswith(ABLATION):
            continue
        ability, _, setup = name.removeprefix(ABLATION).partition(" ")
        whole = days.get(f"agent {setup}", {})
        both = sorted(set(day) & set(whole))
        if not both:
            continue
        wanted = _numbers(day, both, "units_wanted")
        less = _numbers(day, both, "units_secured")
        full = _numbers(whole, both, "units_secured")
        gap = stats.difference(full, less, wanted)
        verdict = "" if gap.excludes_zero else " *(not a clear difference)*"
        lines.append(
            f"| {ability.replace('_', ' ')} {setup} | "
            f"{', '.join(str(seed) for seed in sorted({seed for seed, _ in both}))} | "
            f"{int(sum(less))} of {int(sum(wanted))}: {stats.share(less, wanted)} | "
            f"{int(sum(full))} of {int(sum(wanted))}: {stats.share(full, wanted)} | "
            f"{gap.value:+.1%} ({gap.low:+.1%} to {gap.high:+.1%}){verdict} |"
        )
    return lines if len(lines) > 2 else ["No ablation day is saved."]


def simulation_chart(days: dict[str, Day]) -> str:
    """Units secured within the window, one bar per contender, as SVG."""
    rows = []
    for name, day in sorted(days.items()):
        if name.startswith(ABLATION):
            continue
        keys = sorted(day)
        estimate = stats.share(
            _numbers(day, keys, "units_secured"), _numbers(day, keys, "units_wanted")
        )
        rows.append((name, estimate))
    return charts.bars("Units secured within the 6-hour window", rows)


def _latest(results: Path, kind: str) -> list[tuple[str, dict[str, Any]]]:
    found = []
    for folder in sorted(results.iterdir()):
        if f"_{kind}_" in folder.name and (folder / "summary.json").exists():
            summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
            found.append((folder.name, summary))
    return found


def understanding_table(results: Path) -> list[str]:
    runs = _latest(results, "understanding")
    if not runs:
        return ["No run of suite E1 is saved."]
    lines = ["| Check | " + " | ".join(name.split("_understanding_")[1] for name, _ in runs) + " |"]
    lines.append("|---" * (len(runs) + 1) + "|")
    for check, good in CHECKS.items():
        cells = []
        for _, summary in runs:
            line = summary["checks"].get(check)
            cells.append(
                f"{line['yes']} of {line['cases']} ({line['share']:.0%})"
                if line and line["cases"]
                else "-"
            )
        lines.append(
            f"| {check}{'' if good else ' (lower is better)'} | " + " | ".join(cells) + " |"
        )
    # The speed target is per kind of turn (docs/08 E1). Runs saved before the two kinds
    # were told apart have one number for every turn.
    for label, kind in (
        ("95% of the turns that only answer, within (s)", "turns_that_only_answer"),
        ("95% of the turns with cards, within (s)", "turns_with_cards"),
    ):
        cells = [
            f"{s[kind]['seconds_p95']:.1f} ({s[kind]['turns']} turns)"
            if kind in s and s[kind]["turns"]
            else "-"
            for _, s in runs
        ]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines.append(
        "| 95% of all turns, within (s) | "
        + " | ".join(f"{s['seconds_p95']:.1f}" for _, s in runs)
        + " |"
    )
    lines.append(
        "| cases · cost | "
        + " | ".join(f"{s['cases']} · ${s['cost_usd']:.3f}" for _, s in runs)
        + " |"
    )
    return lines


def conversations_table(results: Path) -> list[str]:
    """Suite E7: one column per run, the checks first, then each way of telling."""
    runs = _latest(results, "conversations")
    if not runs:
        return ["No run of suite E7 is saved."]
    lines = ["| Check | " + " | ".join(name.split("_conversations_")[1] for name, _ in runs) + " |"]
    lines.append("|---" * (len(runs) + 1) + "|")
    for check, good in CONVERSATION_CHECKS.items():
        cells = []
        for _, summary in runs:
            line = summary["checks"].get(check)
            cells.append(
                f"{line['yes']} of {line['cases']} ({line['share']:.0%})"
                if line and line["cases"]
                else "-"
            )
        lines.append(
            f"| {check}{'' if good else ' (lower is better)'} | " + " | ".join(cells) + " |"
        )
    for style in STYLES:
        cells = []
        for _, summary in runs:
            line = summary["by_style"].get(style)
            cells.append(
                f"{line['ended_with_cards']} of {line['conversations']} got cards, after "
                f"{line['client_messages_to_cards']} client messages"
                if line and line["conversations"]
                else "-"
            )
        lines.append(f"| {style.replace('_', ' ')} | " + " | ".join(cells) + " |")
    lines.append(
        "| conversations · cost (agent + playing model) | "
        + " | ".join(
            f"{s['conversations']} · ${s['agent_cost_usd']:.3f} + ${s['client_cost_usd']:.3f}"
            for _, s in runs
        )
        + " |"
    )
    return lines


def safety_table(results: Path) -> list[str]:
    runs = _latest(results, "safety")
    if not runs:
        return ["No run of suite E4 is saved."]
    lines = ["| Run | Answers | With a violation | Which checks | Cost |", "|---|---|---|---|---|"]
    for name, summary in runs:
        broken = ", ".join(f"{check} x{n}" for check, n in summary["by_check"].items()) or "none"
        lines.append(
            f"| {name.split('_safety_')[1]} | {summary['answers']} | "
            f"{summary['answers_with_a_violation']} | {broken} | ${summary['cost_usd']:.3f} |"
        )
    return lines


def report(results: Path) -> str:
    parts = [
        "# DawaLink: evaluation results",
        "",
        "Generated by `python -m dawalink.evals.report` from the runs saved in this folder. "
        "Intervals are 95% bootstrap intervals; a comparison is made on the same simulated "
        "clients (docs/08 §4).",
        "",
        "## The simulation (E2)",
        "",
        "![Units secured within the window, by contender](simulation.svg)",
        "",
        *simulation_table(simulation(results)),
        "",
        "## The ablations (E3)",
        "",
        *ablation_table(simulation(results)),
        "",
        "## Understanding (E1)",
        "",
        *understanding_table(results),
        "",
        "## Safety (E4)",
        "",
        *safety_table(results),
        "",
        "## Conversations with a played client (E7)",
        "",
        *conversations_table(results),
        "",
    ]
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="also write eval/results/REPORT.md")
    arguments = parser.parse_args()
    text = report(save.RESULTS)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(text)
    if arguments.write:
        (save.RESULTS / "REPORT.md").write_text(text, encoding="utf-8", newline="\n")
        chart = simulation_chart(simulation(save.RESULTS))
        (save.RESULTS / "simulation.svg").write_text(chart, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
