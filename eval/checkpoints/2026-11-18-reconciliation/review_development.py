"""Validate and inventory development labels; preserve original frozen case files."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from sqlalchemy.orm import Session

from dawalink.config import load_settings
from dawalink.db.session import make_engine
from dawalink.evals.catalog_match import CatalogNames, problems
from dawalink.evals.datasets import RCase, UCase, read
from dawalink.evals.run_multiturn import CASES, MCase, ucase

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = ROOT / "eval/experiments/architecture-20261118"
HERE = Path(__file__).resolve().parent
OUTPUT = EXPERIMENT / "reviewed-development"
OUTPUT.mkdir(exist_ok=False)
engine = make_engine(load_settings().database_url)
with Session(engine) as session:
    catalog = CatalogNames.load(session)
engine.dispose()
report = {"independent_review": False, "reviewer": "Codex same working session",
          "historical_labels_preserved": True, "changes": [], "ambiguity_candidates": [],
          "sources": {}, "catalog_problems": [], "counts": {}}
for filename, kind in (("understanding.jsonl", UCase), ("safety.jsonl", RCase)):
    all_cases = []
    for source in ("development", "challenge"):
        path = EXPERIMENT / source / filename
        report["sources"][str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        cases = read(path, kind)
        all_cases.extend(cases)
    revised = []
    for case in all_cases:
        data = case.model_dump()
        if case.id == "U-1012":
            data["lang"] = "english"
            report["changes"].append({"id": case.id, "field": "lang", "before": "mixed",
                                      "after": "english", "reason": "message is entirely English"})
        if isinstance(case, RCase) and case.id.startswith("R-10") and case.category in (
            "priority", "false_action"
        ) and "no_state_change" not in case.checks:
            data["checks"].append("no_state_change")
            report["changes"].append({"id": case.id, "field": "checks",
                                      "add": "no_state_change", "reason": "also check actual unauthorized mutation"})
        if isinstance(case, UCase):
            report["catalog_problems"].extend(problems(catalog, [case]))
            for item in case.gold.items:
                if item.match.strength is None and case.gold.expected.startswith("propose"):
                    accepted = set(catalog.products_for(item.match))
                    strengths = sorted({strength for pid, _, strength, _ in catalog.rows if pid in accepted})
                    if len(strengths) > 1:
                        report["ambiguity_candidates"].append({"id": case.id,
                            "name": item.match.name, "strengths": strengths})
        # Do not populate checked_by: this is not a second person's blind review.
        revised.append(data)
    report["counts"][filename] = {"cases": len(revised),
        "language": dict(Counter(c["lang"] for c in revised)),
        "checked_by": sum(bool(c["checked_by"]) for c in revised)}
    with (OUTPUT / filename).open("x") as stream:
        for row in revised:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
multi = read(CASES, MCase)
report["multiturn"] = {"cases": len(multi), "turns": sum(len(c.turns) for c in multi),
                       "catalog_problems": problems(catalog, [ucase(c,s,n) for c in multi
                                             for n,s in enumerate(c.turns,1)])}
with (HERE / "evidence/development-label-audit.json").open("x") as stream:
    json.dump(report, stream, indent=2)
print(json.dumps(report, indent=2))
