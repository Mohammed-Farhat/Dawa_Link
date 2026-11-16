"""Checks the development datasets: python -m dawalink.evals.validate

For each file: every line is a well-formed case, no ID is used twice, the mix by language
and by category is printed next to the plan's (docs/08 §2), and, with a catalog in the
local database, every medicine a label names exists there.

It reads `eval/datasets/` only. The held-out files are never opened by this command
unless `--heldout` is given, which only the final run's session does.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy.orm import Session

from dawalink.config import load_settings
from dawalink.db.session import make_engine
from dawalink.evals import catalog_match
from dawalink.evals.catalog_match import CatalogNames
from dawalink.evals.datasets import DATASETS, HELDOUT, DatasetError, RCase, UCase, read

# The whole sets of the plan (docs/08 §2.1, §2.2). A file holds its split's share of them.
U_PLAN = {
    "clear": 40,
    "days_pickup": 20,
    "ambiguous": 40,
    "misspelled": 40,
    "multi": 40,
    "budget": 30,
    "preference": 20,
    "clinical": 30,
    "status": 20,
    "offtopic": 10,
    "injection": 10,
}
R_PLAN = {
    "clinical": 30,
    "clinical_hidden": 15,
    "injection": 20,
    "cross_user": 15,
    "priority": 15,
    "controlled": 10,
    "pii_fishing": 10,
    "false_action": 5,
}
U_LANGUAGES = {"arabizi": 0.40, "arabic": 0.25, "english": 0.25, "mixed": 0.10}


def _mix(title: str, counted: Counter[str], plan: dict[str, int] | None = None) -> None:
    print(f"  {title}:")
    for name in sorted(set(counted) | set(plan or {})):
        of_plan = f" of {plan[name]} in the whole set" if plan and name in plan else ""
        print(f"    {name:<18} {counted[name]:>4}{of_plan}")


def check(folder: Path, *, with_catalog: bool) -> list[str]:
    """Prints what each file holds and returns everything that is wrong."""
    wrong: list[str] = []
    understanding, safety = folder / "understanding.jsonl", folder / "safety.jsonl"
    u_cases: list[UCase] = []
    try:
        if understanding.is_file():
            u_cases = read(understanding, UCase)
            print(f"{understanding}: {len(u_cases)} cases")
            _mix("by category", Counter(case.category for case in u_cases), U_PLAN)
            languages: Counter[str] = Counter(case.lang for case in u_cases)
            _mix("by language", languages)
            for language, share in U_LANGUAGES.items():
                got = languages[language] / max(len(u_cases), 1)
                if abs(got - share) > 0.10:
                    # A note, not a mistake: a file is written in batches.
                    print(
                        f"  note: {language} is {got:.0%} of the messages, "
                        f"the plan says {share:.0%}"
                    )
        if safety.is_file():
            r_cases = read(safety, RCase)
            print(f"{safety}: {len(r_cases)} cases")
            _mix("by category", Counter(case.category for case in r_cases), R_PLAN)
            _mix("by language", Counter(case.lang for case in r_cases))
    except DatasetError as error:
        return [str(error)]

    if with_catalog and u_cases:
        engine = make_engine(load_settings().database_url)
        with Session(engine) as session:
            catalog = CatalogNames.load(session)
        if not catalog.rows:
            wrong.append("the local catalog is empty: import it, or run with --no-catalog")
        else:
            wrong += catalog_match.problems(catalog, u_cases)
    return wrong


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-catalog", action="store_true", help="skip the medicine names")
    parser.add_argument("--heldout", action="store_true", help="the final run's session only")
    arguments = parser.parse_args()
    if isinstance(sys.stdout, __import__("io").TextIOWrapper):
        sys.stdout.reconfigure(errors="replace")
    wrong = check(HELDOUT if arguments.heldout else DATASETS, with_catalog=not arguments.no_catalog)
    for line in wrong:
        print("WRONG:", line)
    print("ok" if not wrong else f"{len(wrong)} problems")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    main()
