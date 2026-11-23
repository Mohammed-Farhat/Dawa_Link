"""The free checks to run before committing a change (docs/08 §7):
python -m dawalink.evals.before_commit

No paid model is called. Four things, each of which stops a kind of mistake the tests
alone don't:
1. **the planner on the P-set:** every one of the 200 rankings exact;
2. **the written datasets:** every case well formed, every medicine a label names in the
   local catalog;
3. **the saved results:** no email address, phone number or coordinates in any file of
   `eval/results/`, which is public (`python -m dawalink.evals.scan_results`);
4. **one simulated day of the policy with no AI** (seed 1, about 3 minutes): the units it
   secures must not be below the recorded number (`eval/baseline.json`). It drops when a
   change breaks matching, early release, the expiry fit or the planner.

When a change is meant to move that number (a rule changed, the simulation was corrected),
run it with `--accept` and say why in the build plan.
"""

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from dawalink.config import load_settings
from dawalink.db.session import make_engine
from dawalink.evals import catalog_match, plan_set, scan_results
from dawalink.evals.catalog_match import CatalogNames
from dawalink.evals.datasets import DATASETS, RCase, UCase, read
from dawalink.evals.run_multiturn import CASES, MCase, ucase
from dawalink.observability.logging import configure_logging
from dawalink.sim import run
from dawalink.sim.params import Params

BASELINE = Path("../eval/baseline.json")
SEED = 1


def planner() -> list[str]:
    return [line for case in plan_set.read_cases() for line in plan_set.check(case)]


def datasets() -> list[str]:
    understanding = read(DATASETS / "understanding.jsonl", UCase)
    read(DATASETS / "safety.jsonl", RCase)
    multi = read(CASES, MCase)
    understanding += [ucase(c, s, n) for c in multi for n, s in enumerate(c.turns, 1)]
    engine = make_engine(load_settings().database_url)
    try:
        with Session(engine) as session:
            return catalog_match.problems(CatalogNames.load(session), understanding)
    finally:
        engine.dispose()


def simulated_day() -> dict[str, int]:
    played = run.one(load_settings(), "rules", SEED, Params())
    return {
        "units_secured": int(played.summary["units_secured"]),
        "units_wanted": int(played.summary["units_wanted"]),
        "no_shows": int(played.summary["no_shows"]),
        "boxes_that_dont_last": int(played.summary["boxes_that_dont_last"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--accept", action="store_true", help="record this day as the new number")
    parser.add_argument("--skip-day", action="store_true", help="only the two quick checks")
    arguments = parser.parse_args()
    configure_logging("WARNING")
    failed = False

    differences = planner()
    print(f"planner on the P-set: {'exact' if not differences else differences[:5]}")
    failed |= bool(differences)

    problems = datasets()
    print(f"datasets: {'valid' if not problems else problems[:5]}")
    failed |= bool(problems)

    read, personal = scan_results.scan(scan_results.RESULTS)
    said = "nothing personal" if not personal else [f"{p.what} in {p.file}" for p in personal[:5]]
    print(f"the saved results ({read} files): {said}")
    failed |= bool(personal)

    if not arguments.skip_day:
        day = simulated_day()
        recorded = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else None
        print(f"the no-AI policy, seed {SEED}: {day} (recorded: {recorded})")
        if day["no_shows"] or day["boxes_that_dont_last"]:
            print("  a no-show or a box that doesn't last: these must stay at zero")
            failed = True
        if arguments.accept or recorded is None:
            BASELINE.write_text(json.dumps(day, indent=2) + "\n", encoding="utf-8")
            print(f"  recorded in {BASELINE}")
        elif day["units_secured"] < recorded["units_secured"]:
            print("  fewer units than recorded: a regression, or a change to explain (--accept)")
            failed = True
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
