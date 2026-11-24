"""Judges saved scenario runs a second time, to know how far the judge can be trusted:
python -m dawalink.evals.scenarios.rejudge <result folders> --judge-model claude-sonnet-5-5
    --max-usd 1 [--every 9] [--only ids] [--lang arabizi] [--suffix again]

The course's chapter 9 names an LLM judge's weaknesses: it is inconsistent, it depends on
its rubric, and it prefers answers of its own kind. This measures the first, and with
another judge model the second opinion: the same transcripts, the same rubric, a new
verdict. Nothing is played again; only the judge is paid.

Printed and saved: how often the two verdicts agree on "accepted", and for each criterion
how often the two scores are equal, within one point, and their mean difference.
"""

import argparse
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any

from dawalink.agent.llm.base import has_price
from dawalink.agent.llm.claude import ClaudeModel
from dawalink.config import load_settings
from dawalink.evals.scenarios.judge import CRITERIA, judge
from dawalink.evals.scenarios.spend import Metered, Spend

Row = dict[str, Any]


def sample(folders: list[Path], *, every: int, only: set[str], lang: str | None) -> list[Row]:
    """The judged rows to judge again: every `every`-th by scenario and language, so the
    choice is fixed and anyone can repeat it."""
    rows: list[Row] = []
    for folder in folders:
        for line in (folder / "scenarios.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            first = row.get("judge") or {}
            if not first.get("scores") or first.get("error"):
                continue
            if (only and row["id"] not in only) or (lang and row["lang"] != lang):
                continue
            rows.append(row | {"folder": folder.name})
    rows.sort(key=lambda row: (row["lang"], row["id"]))
    return rows if only else rows[::every]


def agreement(pairs: list[tuple[Row, Row]]) -> dict[str, Any]:
    """`pairs`: the first verdict and the second, as saved rows."""
    done = [(first, second) for first, second in pairs if second.get("scores")]
    if not done:
        return {"n": 0}
    same = sum(1 for first, second in done if first["passed"] == second["passed"])
    found: dict[str, Any] = {
        "n": len(done),
        "no_verdict": len(pairs) - len(done),
        "accepted_first": sum(1 for first, _ in done if first["passed"]),
        "accepted_second": sum(1 for _, second in done if second["passed"]),
        "same_accepted": same,
        "same_accepted_share": round(same / len(done), 3),
        "criteria": {},
    }
    for name in CRITERIA:
        gaps = [second["scores"][name] - first["scores"][name] for first, second in done]
        found["criteria"][name] = {
            "equal": round(sum(1 for gap in gaps if gap == 0) / len(gaps), 3),
            "within_one": round(sum(1 for gap in gaps if abs(gap) <= 1) / len(gaps), 3),
            "mean_first": round(statistics.mean(first["scores"][name] for first, _ in done), 2),
            "mean_second": round(statistics.mean(second["scores"][name] for _, second in done), 2),
            "mean_gap": round(statistics.mean(gaps), 2),
        }
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    parser.add_argument("folders", nargs="+", type=Path)
    parser.add_argument("--judge-model", required=True, help="the model that judges again (paid)")
    parser.add_argument("--effort", default="low", choices=("low", "medium", "high"))
    parser.add_argument("--max-usd", type=Decimal, required=True, help="the most it may cost")
    parser.add_argument("--every", type=int, default=9, help="every N-th judged row")
    parser.add_argument("--only", help="only these scenarios (then every row of them)")
    parser.add_argument("--lang", help="only this language")
    parser.add_argument("--suffix", default="again", help="names the output file")
    parser.add_argument("--workers", type=int, default=4)
    arguments = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    settings = load_settings()
    if settings.anthropic_api_key is None:
        raise SystemExit("ANTHROPIC_API_KEY is not set.")
    if not has_price(arguments.judge_model):
        raise SystemExit(f"No price is known for {arguments.judge_model}: add it first.")
    only = set((arguments.only or "").split(",")) - {""}
    rows = sample(arguments.folders, every=arguments.every, only=only, lang=arguments.lang)
    spend = Spend(arguments.max_usd)
    key = settings.anthropic_api_key.get_secret_value()

    def again(row: Row) -> Row:
        model = Metered(
            ClaudeModel(api_key=key, model=arguments.judge_model, effort=arguments.effort),
            spend,
            "judge",
        )
        verdict = judge(
            model,
            title=row["title"],
            kind=row["kind"],
            expected=row["expected"],
            lang=row["lang"],
            transcript=row["transcript"],
        )
        return {
            "id": row["id"],
            "lang": row["lang"],
            "rep": row["rep"],
            "folder": row["folder"],
            "checks_passed": row.get("passed"),
            "first": row["judge"],
            "second": verdict.as_row(),
            "second_model": arguments.judge_model,
        }

    print(
        f"{len(rows)} judged runs judged again by {arguments.judge_model}, "
        f"at most ${arguments.max_usd}"
    )
    with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
        judged = list(pool.map(again, rows))
    out = arguments.folders[0].parent / (
        f"{arguments.folders[0].name.split('_scenarios_')[0]}_scenarios_judge-agreement_"
        f"{arguments.judge_model}_{arguments.suffix}"
    )
    out.mkdir(parents=True, exist_ok=True)
    (out / "rejudged.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in judged), encoding="utf-8"
    )
    summary: dict[str, Any] = {
        "second_judge": arguments.judge_model,
        "effort": arguments.effort,
        "from": [folder.name for folder in arguments.folders],
        "cost_usd": float(spend.total),
        "all": agreement([(row["first"], row["second"]) for row in judged]),
    }
    for lang in sorted({row["lang"] for row in judged}):
        summary[lang] = agreement(
            [(row["first"], row["second"]) for row in judged if row["lang"] == lang]
        )
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"spent ${float(spend.total):.3f}, saved in {out}")


if __name__ == "__main__":
    main()
