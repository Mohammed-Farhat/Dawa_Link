"""Suite E8's numbers, from the saved rows:
python -m dawalink.evals.scenarios.report <result folder> [<result folder> ...] --out <file.md>

It reads the `scenarios.jsonl` of each folder (one folder per language) and writes the
tables of the course's chapter 9: results by kind of case, by level and by metric
family, the automatic checks, the judge's scores and how often it agrees with the
checks, efficiency, and (when scenarios were played several times) reliability. Then
every scenario that failed, with what failed.

It computes; it explains nothing. Why something failed is read from the traces by a
person, and written in the evaluation's report.
"""

import argparse
import json
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from dawalink.evals.scenarios.client_model import LANGS
from dawalink.evals.scenarios.judge import CRITERIA
from dawalink.evals.scenarios.scenario import KINDS

Row = dict[str, Any]
LEVELS = ("component", "step", "trajectory", "end_to_end")
FAMILIES = (
    "task_success",
    "output_quality",
    "tool_use",
    "planning",
    "memory",
    "efficiency",
    "reliability",
    "safety",
)


def read(folders: Iterable[Path]) -> list[Row]:
    """Every row of the folders, in the order given. A scenario played in several folders
    (the main run, then the repeats) is numbered across them: run 1 is the first folder's."""
    rows: list[Row] = []
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for folder in folders:
        for line in (folder / "scenarios.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                seen[(row["id"], row["lang"])] += 1
                row["rep"] = seen[(row["id"], row["lang"])]
                row["folder"] = folder.name
                rows.append(row)
    return rows


def played(rows: Sequence[Row]) -> list[Row]:
    return [row for row in rows if row.get("error") is None and "checks" in row]


def _share(ok: int, total: int) -> str:
    return f"{ok}/{total} ({ok / total:.0%})" if total else "-"


def _table(head: Sequence[str], lines: Iterable[Sequence[object]]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(cell) for cell in line) + " |" for line in lines]
    return "\n".join(out)


def _by_lang(rows: Sequence[Row]) -> dict[str, list[Row]]:
    found: dict[str, list[Row]] = {lang: [] for lang in LANGS}
    for row in rows:
        found.setdefault(row["lang"], []).append(row)
    return {lang: mine for lang, mine in found.items() if mine}


def passed_by(rows: Sequence[Row], field: str, order: Sequence[str] | None = None) -> str:
    """Scenarios passed out of scenarios played, by `field`, a column per language."""
    langs = _by_lang(rows)
    names = list(order or sorted({row[field] for row in rows}))
    names = [name for name in names if any(row[field] == name for row in rows)]
    lines = []
    for name in [*names, "all"]:
        cells: list[object] = [name]
        for mine in [*langs.values(), list(rows)]:
            of = [row for row in mine if name == "all" or row[field] == name]
            cells.append(_share(sum(1 for row in of if row["passed"]), len(of)))
        lines.append(cells)
    return _table([field, *langs, "all"], lines)


def checks_by(rows: Sequence[Row], where: str, field: str, order: Sequence[str]) -> str:
    """Checks passed out of checks made, by level or by metric family."""
    langs = _by_lang(rows)
    lines = []
    for name in order:
        cells: list[object] = [name]
        any_made = False
        for mine in [*langs.values(), list(rows)]:
            made = [c for row in mine for c in row.get(where) or [] if c[field] == name]
            any_made = any_made or bool(made)
            cells.append(_share(sum(1 for c in made if c["ok"]), len(made)))
        if any_made:
            lines.append(cells)
    return _table([field, *langs, "all"], lines)


def checks_by_id(rows: Sequence[Row], where: str) -> str:
    langs = _by_lang(rows)
    ids = sorted({c["id"] for row in rows for c in row.get(where) or []})
    lines = []
    for one in ids:
        cells: list[object] = [one]
        for mine in [*langs.values(), list(rows)]:
            made = [c for row in mine for c in row.get(where) or [] if c["id"] == one]
            cells.append(_share(sum(1 for c in made if c["ok"]), len(made)))
        lines.append(cells)
    return _table(["check", *langs, "all"], lines)


def judge_scores(rows: Sequence[Row]) -> str:
    langs = _by_lang(rows)
    lines = []
    for name in CRITERIA:
        cells: list[object] = [name]
        for mine in [*langs.values(), list(rows)]:
            scores = [
                row["judge"]["scores"][name]
                for row in mine
                if row.get("judge") and row["judge"]["scores"]
            ]
            cells.append(f"{statistics.mean(scores):.2f}" if scores else "-")
        lines.append(cells)
    accepted: list[object] = ["accepted by the judge"]
    for mine in [*langs.values(), list(rows)]:
        judged = [row for row in mine if row.get("judge") and row["judge"]["scores"]]
        accepted.append(_share(sum(1 for row in judged if row["judge"]["passed"]), len(judged)))
    lines.append(accepted)
    return _table(["criterion (1 to 5)", *langs, "all"], lines)


def judge_agreement(rows: Sequence[Row]) -> str:
    """The judge's "accepted" against the checks' "passed": where they disagree, one of
    the two is wrong, and a person reads those scenarios."""
    judged = [row for row in rows if row.get("judge") and row["judge"]["scores"]]
    cells: dict[tuple[bool, bool], int] = defaultdict(int)
    for row in judged:
        cells[(bool(row["passed"]), bool(row["judge"]["passed"]))] += 1
    agree = cells[(True, True)] + cells[(False, False)]
    table = _table(
        ["", "judge accepts", "judge rejects"],
        [
            ["checks pass", cells[(True, True)], cells[(True, False)]],
            ["a check fails", cells[(False, True)], cells[(False, False)]],
        ],
    )
    return f"{table}\n\nThey agree on {_share(agree, len(judged))} of the judged scenarios."


def problem_layers(rows: Sequence[Row]) -> str:
    """Where the judge thinks each problem comes from. Its guess, to be checked by trace."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        for problem in (row.get("judge") or {}).get("problems") or []:
            counts[str(problem.get("layer"))][str(problem.get("severity"))] += 1
    lines = [
        [layer, by.get("high", 0), by.get("medium", 0), by.get("low", 0), sum(by.values())]
        for layer, by in sorted(counts.items(), key=lambda item: -sum(item[1].values()))
    ]
    return _table(["layer (the judge's guess)", "high", "medium", "low", "all"], lines)


def _spread(values: Sequence[float]) -> str:
    if not values:
        return "-"
    ordered = sorted(values)
    p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
    return f"{statistics.median(ordered):.1f} / {p95:.1f} / {ordered[-1]:.1f}"


def efficiency(rows: Sequence[Row]) -> str:
    langs = _by_lang(rows)
    groups = [*langs.values(), list(rows)]

    def line(name: str, value: Callable[[Sequence[Row]], object]) -> list[object]:
        return [name, *(value(mine) for mine in groups)]

    def cost(mine: Sequence[Row], *parts: str) -> float:
        return sum(float(row.get(part) or 0) for row in mine for part in parts)

    lines = [
        line("agent turns", lambda m: sum(row["agent_turns"] for row in m)),
        line(
            "seconds per agent turn: median / p95 / max",
            lambda m: _spread([s for row in m for s in row["turn_seconds"]]),
        ),
        line(
            "model calls per agent turn",
            lambda m: (
                f"{sum(r['model_calls'] for r in m) / max(1, sum(r['agent_turns'] for r in m)):.2f}"
            ),
        ),
        line(
            "tool calls per agent turn",
            lambda m: (
                f"{sum(r['tool_calls'] for r in m) / max(1, sum(r['agent_turns'] for r in m)):.2f}"
            ),
        ),
        line(
            "tool calls that succeeded",
            lambda m: _share(
                sum(r["tool_calls"] - r["tool_errors"] for r in m), sum(r["tool_calls"] for r in m)
            ),
        ),
        line(
            "agent cost per scenario (USD)",
            lambda m: f"{cost(m, 'agent_cost_usd') / max(1, len(m)):.4f}",
        ),
        line(
            "agent cost per passed scenario (USD)",
            lambda m: f"{cost(m, 'agent_cost_usd') / max(1, sum(1 for r in m if r['passed'])):.4f}",
        ),
        line(
            "whole run: agent + client + judge (USD)",
            lambda m: f"{cost(m, 'agent_cost_usd', 'client_cost_usd', 'judge_cost_usd'):.2f}",
        ),
    ]
    return _table(["", *langs, "all"], lines)


def reliability(rows: Sequence[Row]) -> str | None:
    """For scenarios played several times: pass@1, pass@k, and how often every run agrees."""
    runs: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: r["rep"]):
        runs[(row["id"], row["lang"])].append(bool(row["passed"]))
    several = {key: results for key, results in runs.items() if len(results) > 1}
    if not several:
        return None
    k = max(len(results) for results in several.values())
    langs = sorted({lang for _, lang in several}, key=LANGS.index)
    lines = []
    for lang in [*langs, "all"]:
        mine = [r for (_, one), r in several.items() if lang in ("all", one)]
        variance = statistics.mean(statistics.pvariance([float(x) for x in r]) for r in mine)
        lines.append(
            [
                lang,
                len(mine),
                _share(sum(1 for r in mine if r[0]), len(mine)),
                _share(sum(1 for r in mine if any(r)), len(mine)),
                _share(sum(1 for r in mine if all(r)), len(mine)),
                _share(sum(1 for r in mine if len(set(r)) > 1), len(mine)),
                f"{variance:.3f}",
            ]
        )
    table = _table(
        [
            "language",
            "scenarios",
            "pass@1",
            f"pass@{k} (at least one run passes)",
            "every run passes",
            "runs disagree",
            "mean variance of success",
        ],
        lines,
    )
    flaky = sorted(
        f"{one} [{lang}]: {''.join('P' if x else 'F' for x in r)}"
        for (one, lang), r in several.items()
        if len(set(r)) > 1
    )
    return table + (
        "\n\nRuns that disagree:\n" + "\n".join(f"- {f}" for f in flaky) if flaky else ""
    )


def failures(rows: Sequence[Row]) -> str:
    """Every scenario with a failed check, a language per column."""
    by_id: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    kinds: dict[str, str] = {}
    for row in rows:
        kinds[row["id"]] = row["kind"]
        failed = [c["id"] for c in row.get("checks") or [] if not c["ok"]]
        if failed:
            by_id[row["id"]][row["lang"]] += [
                f for f in failed if f not in by_id[row["id"]][row["lang"]]
            ]
    langs = list(_by_lang(rows))
    lines = [
        [one, kinds[one], *(", ".join(by_lang.get(lang, [])) or "pass" for lang in langs)]
        for one, by_lang in sorted(by_id.items())
    ]
    return _table(["scenario", "kind", *langs], lines)


def markdown(rows: Sequence[Row], about: str) -> str:
    done = played(rows)
    first = [row for row in done if row["rep"] == 1]
    broken = sorted({f"{row['id']} [{row['lang']}]" for row in rows if row.get("error")})
    parts = [
        f"# Scenario evaluation: the numbers\n\n{about}",
        f"Scenarios played: {len(done)} runs of {len({row['id'] for row in done})} scenarios. "
        + (f"Broken by the harness, not counted: {', '.join(broken)}." if broken else ""),
        "## Scenarios passed, by kind of case\n\nA scenario passes when every check it "
        "states is true.\n\n" + passed_by(first, "kind", KINDS),
        "## By family\n\n" + passed_by(first, "family"),
        "## By prescription notice\n\n" + passed_by(first, "prescription"),
        "## Checks passed, by level\n\n" + checks_by(first, "checks", "level", LEVELS),
        "## Checks passed, by metric family\n\n" + checks_by(first, "checks", "family", FAMILIES),
        "## Automatic checks (every scenario)\n\n" + checks_by_id(first, "auto_checks"),
        "## The judge's scores\n\n" + judge_scores(first),
        "## The judge against the checks\n\n" + judge_agreement(first),
        "## Where the judge places the problems\n\n" + problem_layers(first),
        "## Efficiency\n\n" + efficiency(first),
    ]
    again = reliability(done)
    if again:
        parts.append("## Reliability (scenarios played several times)\n\n" + again)
    parts.append("## Scenarios with a failed check\n\n" + failures(first))
    return "\n\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    rows = read(arguments.folders)
    about = "From: " + ", ".join(folder.name for folder in arguments.folders) + "."
    arguments.out.write_text(markdown(rows, about), encoding="utf-8")
    print(f"{len(rows)} rows, written to {arguments.out}")


if __name__ == "__main__":
    main()
