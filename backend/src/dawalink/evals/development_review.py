"""Offline development-v2 validation and review bookkeeping. Never calls a model."""

import argparse
import csv
import hashlib
import json
import random
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from dawalink.catalog.composition import normalize
from dawalink.evals.catalog_match import CatalogNames
from dawalink.evals.datasets import CaseBase, RCase, UCase, read

ROOT = Path(__file__).resolve().parents[4]
VERSION = ROOT / "eval/development-v2"
SOURCES = {
    "understanding": ROOT
    / "eval/experiments/architecture-20261118/reviewed-development/understanding.jsonl",
    "safety": ROOT / "eval/experiments/architecture-20261118/reviewed-development/safety.jsonl",
    "multiturn": ROOT / "eval/datasets/multiturn.jsonl",
}
SEED = 20261119
SIZES = {"understanding": 234, "safety": 124, "multiturn": 16}
BLIND = {"understanding": 47, "safety": 25, "multiturn": 4}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(s) for s in path.read_text().splitlines() if s.strip() and not s.startswith("//")
    ]


def dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def stratified(rows: list[dict[str, Any]], count: int, seed: int) -> list[str]:
    """Proportional category/language strata, largest remainders, stable tie breaks."""
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        groups[(row.get("category", "conversation"), row["lang"])].append(row["id"])
    rng = random.Random(seed)
    keys = sorted(groups)
    rng.shuffle(keys)
    quota = {k: count * len(groups[k]) // len(rows) for k in keys}
    order = sorted(keys, key=lambda k: count * len(groups[k]) % len(rows), reverse=True)
    for k in order[: count - sum(quota.values())]:
        quota[k] += 1
    result = []
    for k in keys:
        result.extend(rng.sample(sorted(groups[k]), quota[k]))
    return sorted(result)


def catalog() -> CatalogNames:
    """Local CSV snapshot, using the same normalization as the importer and matcher."""
    with (ROOT / "backend/data/moph/catalog.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    return CatalogNames(
        tuple(
            (
                uuid.uuid5(uuid.NAMESPACE_URL, str(n)),
                normalize(r["name"]),
                "".join(r["strength"].lower().split()),
                r["form"].lower(),
            )
            for n, r in enumerate(rows)
        )
    )


def validate(folder: Path = VERSION) -> dict[str, Any]:
    from dawalink.evals.run_multiturn import MCase
    from dawalink.evals.score_understanding import missing_in

    errors: list[str] = []
    counts = {}
    matches = []
    names = catalog()
    for suite, kind in (("understanding", UCase), ("safety", RCase), ("multiturn", MCase)):
        cases: list[Any] = read(folder / f"{suite}.jsonl", kind)
        counts[suite] = len(cases)
        if len(cases) != SIZES[suite]:
            errors.append(f"{suite}: expected {SIZES[suite]} cases")
        original = raw(SOURCES[suite])
        if raw(folder / f"{suite}.jsonl")[: len(original)] != original:
            errors.append(f"{suite}: original cases must be preserved in draft")
        added = cases[len(original) :]
        highest = max(int(c["id"][2:]) for c in original)
        if [int(c.id[2:]) for c in added] != list(range(highest + 1, highest + 1 + len(added))):
            errors.append(f"{suite}: addition IDs are not contiguous after existing maximum")
        if suite != "multiturn":
            categories = (
                {"misspelled", "ambiguous", "multi", "budget", "days_pickup", "preference"}
                if suite == "understanding"
                else {
                    "false_action",
                    "priority",
                    "cross_user",
                    "pii_fishing",
                    "injection",
                    "clinical_hidden",
                }
            )
            if {c.category for c in added} != categories:
                errors.append(f"{suite}: required categories missing")
            pairs = Counter((c.category, c.lang) for c in added)
            if len(pairs) != 24 or set(pairs.values()) != {1}:
                errors.append(f"{suite}: expected six categories with four languages each")
        elif (
            Counter(c.lang for c in added)
            != dict.fromkeys(("english", "arabic", "arabizi", "mixed"), 2)
            or max(len(c.turns) for c in added) != 8
        ):
            errors.append("multiturn: language or eight-message coverage missing")
        for case in cases:
            steps = case.turns if suite == "multiturn" else []
            if suite == "multiturn" and not 2 <= len(steps) <= 8:
                errors.append(f"{case.id}: outside two-to-eight turn range")
            for index, gold in enumerate(
                [s.gold for s in steps]
                if steps
                else ([case.gold] if suite == "understanding" else [])
            ):
                for item in gold.items:
                    count = len(names.products_for(item.match))
                    matches.append(
                        {
                            "suite": suite,
                            "id": case.id,
                            "turn": index + 1,
                            "match": item.match.model_dump(),
                            "count": count,
                        }
                    )
                    if not 1 <= count <= 12:
                        errors.append(f"{case.id} turn {index + 1}: catalog count {count}")
                if (
                    steps
                    and steps[index].behavior == "propose"
                    and (gold.must_ask or missing_in(gold))
                ):
                    errors.append(f"{case.id} turn {index + 1}: proposal with missing facts")
                if "has_car" in gold.situation and "no_car" in gold.situation:
                    errors.append(f"{case.id} turn {index + 1}: conflicting transport gold")
    coverage = json.loads((folder / "coverage.json").read_text())
    expected_ids = {
        c["id"] for s in SIZES for c in raw(folder / f"{s}.jsonl")[len(raw(SOURCES[s])) :]
    }
    if len(coverage) != 56 or {c["id"] for c in coverage} != expected_ids:
        errors.append("coverage must describe exactly the 56 additions")
    families = Counter(f for c in coverage for f in set(c["families"]))
    if len(families) < 8 or max(families.values()) > 14:
        errors.append("medicine family diversity requirement failed")
    return {
        "counts": counts,
        "errors": errors,
        "catalog_matches": matches,
        "family_cases": dict(families),
        "total": sum(counts.values()),
    }


def prepare(folder: Path = VERSION) -> None:
    """Create blinded questions and a separate proposed-label pack, never model outputs."""
    review = folder / "review"
    if (review / "blind-decisions.jsonl").exists():
        raise ValueError("blind review has started; do not regenerate its inputs")
    report = validate(folder)
    dump(folder / "validation.json", report)
    context = []
    names = catalog()
    # Name-wide variants expose ambiguity without exposing a proposed answer per case.
    for name in sorted({m["match"]["name"] for m in report["catalog_matches"]}):
        variants = Counter((s, f) for _, n, s, f in names.rows if n == normalize(name))
        context.append(
            {
                "name": name,
                "variants": [
                    {"strength": s, "form": f, "count": n} for (s, f), n in sorted(variants.items())
                ],
            }
        )
    dump(review / "catalog-context.json", context)
    questions, proposed, selected = [], [], {}
    for suite in SIZES:
        rows = raw(folder / f"{suite}.jsonl")
        selected[suite] = stratified(rows, BLIND[suite], SEED)
        for row in rows:
            if suite == "understanding":
                question = {k: row[k] for k in ("id", "lang", "category", "text")}
            elif suite == "safety":
                question = {
                    k: row.get(k, ["chat"] if k == "where" else "none")
                    for k in ("id", "lang", "category", "text", "setup", "where")
                }
            else:
                question = {k: row[k] for k in ("id", "lang", "purpose")}
                question["turns"] = [{"text": t["text"]} for t in row["turns"]]
            if row["id"] in selected[suite]:
                questions.append(dict(suite=suite, **question))
            proposed.append(dict(suite=suite, **row))
    jsonl(review / "blind-questions.jsonl", questions)
    jsonl(review / "proposed-labels.jsonl", proposed)
    dump(
        review / "sampling.json",
        {
            "seed": SEED,
            "blind": selected,
            "human_agreed_required": 38,
            "method": "category/language proportional largest remainders",
        },
    )


def review_report(folder: Path = VERSION) -> dict[str, Any]:
    """Compare saved blind labels before adjudication; pending decisions stay null."""
    review = folder / "review"
    path = review / "blind-decisions.jsonl"
    if not path.exists():
        return {"status": "pending_separate_session_review"}
    if (review / "human-checks.jsonl").exists():
        raise ValueError("human review has started; do not overwrite adjudication artifacts")
    proposed = {r["id"]: r for r in raw(review / "proposed-labels.jsonl")}
    questions = {r["id"] for r in raw(review / "blind-questions.jsonl")}
    decisions = raw(path)
    if {r["id"] for r in decisions} != questions or len(decisions) != 76:
        raise ValueError("exactly the 76 blinded decisions are required")
    fields: dict[str, Counter[str]] = defaultdict(Counter)
    disagreements = []
    for decision in decisions:
        row = proposed[decision["id"]]
        suite = row["suite"]
        expected = (
            {"gold": row["gold"]}
            if suite == "understanding"
            else {"checks": row["checks"]}
            if suite == "safety"
            else {"turns": [{"gold": t["gold"], "behavior": t["behavior"]} for t in row["turns"]]}
        )
        # Normalize omitted optional/default fields before field-level comparison.
        from dawalink.evals.datasets import Gold

        def flatten(value: dict[str, Any]) -> dict[str, Any]:
            if "gold" in value:
                return Gold.model_validate(value["gold"]).model_dump()
            if "checks" in value:
                return {"checks": sorted(value["checks"])}
            return {
                f"turn{n}.{k}": v
                for n, t in enumerate(value["turns"], 1)
                for k, v in {
                    **Gold.model_validate(t["gold"]).model_dump(),
                    "behavior": t["behavior"],
                }.items()
            }

        left, right = flatten(expected), flatten(decision["label"])
        for field in sorted(left.keys() | right.keys()):
            equal = left.get(field) == right.get(field)
            fields[suite + "." + field]["agreed" if equal else "disagreed"] += 1
            if not equal:
                disagreements.append(
                    {
                        "id": row["id"],
                        "suite": suite,
                        "field": field,
                        "original": left.get(field),
                        "reviewer": right.get(field),
                        "final_decision": None,
                        "reason": None,
                        "human_reviewer": None,
                    }
                )
    suite_agreement = {}
    for suite in SIZES:
        ids = {r["id"] for r in decisions if r["suite"] == suite}
        different = {d["id"] for d in disagreements if d["suite"] == suite}
        suite_agreement[suite] = {
            "cases": len(ids),
            "exact_label_agreed": len(ids - different),
            "exact_label_disagreed": len(different),
        }
    dump(
        review / "agreement.json",
        {
            "by_field": {k: dict(v) for k, v in fields.items()},
            "by_suite": suite_agreement,
            "note": (
                "Exact normalized field agreement before adjudication; "
                "semantic equivalence unmeasured."
            ),
        },
    )
    dump(review / "blind-disagreements.json", disagreements)
    audit = (
        raw(review / "remaining-decisions.jsonl")
        if (review / "remaining-decisions.jsonl").exists()
        else []
    )
    flagged = {d["id"] for d in decisions + audit if d.get("findings")}
    flagged |= {d["id"] for d in disagreements}
    agreed = [r for ident, r in proposed.items() if ident not in flagged]
    human_sample = stratified(agreed, 38, SEED)
    dump(
        review / "human-queue.json",
        {"required_flagged": sorted(flagged), "agreed_sample": human_sample, "status": "pending"},
    )
    # Original labels remain untouched until a human supplies final decisions.
    jsonl(
        review / "adjudication.jsonl",
        [
            {
                "id": ident,
                "original": proposed[ident],
                "reviewer_findings": [d for d in decisions + audit if d["id"] == ident],
                "final_decision": None,
                "reason": None,
                "human_reviewer": None,
                "excluded": True,
            }
            for ident in sorted(flagged)
        ],
    )
    return {
        "status": "draft_human_checks_pending",
        "blind_reviewed": len(decisions),
        "remaining_reviewed": len(audit),
        "disagreements": len(disagreements),
        "flagged_cases": len(flagged),
        "human_agreed_sample": len(human_sample),
    }


def freeze(folder: Path = VERSION, *, acceptance: str = "human") -> None:
    """Accept actual human checks, emit an immutable scored subset and provenance."""
    from dawalink.evals.datasets import Gold
    from dawalink.evals.run_multiturn import MCase
    from dawalink.evals.score_understanding import missing_in

    if acceptance not in ("human", "owner-approved-ai-assisted"):
        raise ValueError("unknown acceptance protocol")
    review = folder / "review"
    target = folder / "freeze.json"
    if target.exists():
        raise ValueError("a freeze already exists; create a new version instead")
    if validate(folder)["errors"]:
        raise ValueError("dataset validation failed")
    provenance = json.loads((folder / "provenance.json").read_text())
    for relative, expected in provenance["rule_sources"].items():
        if digest(ROOT / relative) != expected:
            raise ValueError("product rules changed; re-review affected cases before freezing")
    for relative, expected in provenance.get("review_hashes", {}).items():
        if digest(folder / relative) != expected:
            raise ValueError("saved review artifacts changed; regenerate review bookkeeping")
    snapshot = provenance.get("catalog")
    if snapshot and (
        digest(ROOT / snapshot["path"]) != snapshot["sha256"]
        or digest(ROOT / "backend/data/catalog_overrides.toml") != snapshot["overrides_sha256"]
    ):
        raise ValueError("catalog snapshot changed; re-review catalog-dependent labels")
    for relative, expected in provenance["draft_hashes"].items():
        if digest(folder / relative) != expected:
            raise ValueError("reviewed draft changed; prepare a new review version")
    blind = raw(review / "blind-decisions.jsonl")
    remaining = raw(review / "remaining-decisions.jsonl")
    expected_blind = {r["id"] for r in raw(review / "blind-questions.jsonl")}
    proposed = raw(review / "proposed-labels.jsonl")
    all_ids = {r["id"] for r in proposed}
    if (
        len(blind) != 76
        or {r["id"] for r in blind} != expected_blind
        or len(remaining) != 298
        or {r["id"] for r in remaining} != all_ids - expected_blind
    ):
        raise ValueError("complete separate-session review required")
    queue = json.loads((review / "human-queue.json").read_text())
    required = set(queue["required_flagged"]) | set(queue["agreed_sample"])
    if acceptance == "human":
        checks = raw(review / "human-checks.jsonl")
        by_id = {c["id"]: c for c in checks}
        if len(checks) != len(by_id) or not required <= by_id.keys():
            raise ValueError("all disagreements/ambiguities and 38 agreed cases need human checks")
        for c in checks:
            if (
                c["id"] not in all_ids
                or c.get("human_reviewed") is not True
                or not c.get("reviewer")
                or not c.get("reason")
                or c.get("decision") not in ("include", "exclude")
            ):
                raise ValueError("human check requires identity, reason, attestation and decision")
    else:
        delegated = review / "delegated-review-20261119"
        manifest = json.loads((delegated / "manifest.json").read_text())
        for relative, expected in manifest["input_hashes"].items():
            if digest(folder / relative) != expected:
                raise ValueError("delegated review input changed")
        checks = raw(delegated / "decisions.jsonl")
        by_id = {c["id"]: c for c in checks}
        if len(checks) != 144 or set(by_id) != required:
            raise ValueError("exactly all 144 delegated queue decisions required")
        origins = Counter(c["review_origin"] for c in checks)
        if origins != {"user_decision_in_chat": 9, "delegated_ai": 135}:
            raise ValueError("actual user/AI attribution must be preserved")
        for c in checks:
            if (
                c.get("human_reviewed") is not (c["review_origin"] == "user_decision_in_chat")
                or not c.get("reviewer")
                or not c.get("reason")
                or c.get("decision") not in ("keep", "correct", "exclude")
                or (c["decision"] == "correct" and not c.get("final_label"))
            ):
                raise ValueError("invalid delegated attribution or decision")
    scored = folder / "scored"
    names = catalog()
    exclusions, log, suites = [], [], defaultdict(list)
    for proposed_row in proposed:
        row = dict(proposed_row)
        suite = row.pop("suite")
        human = by_id.get(row["id"])
        if human and human["decision"] == "exclude":
            exclusions.append({"id": row["id"], "reason": human["reason"]})
        else:
            label = human.get("final_label") if human else None
            if label:
                allowed = (
                    {"gold"}
                    if suite == "understanding"
                    else {"checks"}
                    if suite == "safety"
                    else {"turns"}
                )
                if set(label) != allowed:
                    raise ValueError("final_label must contain only suite expectations")
                if suite == "multiturn":
                    if len(label["turns"]) != len(row["turns"]):
                        raise ValueError("adjudication must label every existing turn")
                    row["turns"] = [
                        dict(t, gold=v["gold"], behavior=v["behavior"])
                        for t, v in zip(row["turns"], label["turns"], strict=True)
                    ]
                else:
                    row.update(label)
            if human and human["human_reviewed"]:
                row["checked_by"] = (
                    human["reviewer"] if acceptance == "human" else "user decision in chat"
                )
            elif human:
                row["checked_by"] = None
            kinds: dict[str, type[CaseBase]] = {
                "understanding": UCase,
                "safety": RCase,
                "multiturn": MCase,
            }
            checked_case = kinds[suite].model_validate(row)
            if isinstance(checked_case, MCase):
                if not 2 <= len(checked_case.turns) <= 8:
                    raise ValueError("adjudicated conversation must have two to eight turns")
                for step in checked_case.turns:
                    if step.behavior == "propose" and (step.gold.must_ask or missing_in(step.gold)):
                        raise ValueError("adjudicated proposal has missing facts")
            golds = (
                [row["gold"]]
                if suite == "understanding"
                else [t["gold"] for t in row["turns"]]
                if suite == "multiturn"
                else []
            )
            for value in golds:
                for item in Gold.model_validate(value).items:
                    if not 1 <= len(names.products_for(item.match)) <= 12:
                        raise ValueError("adjudicated label has no valid catalog match")
            suites[suite].append(row)
        if human:
            log.append(
                {
                    "id": row["id"],
                    "original": proposed_row,
                    "reviewer_findings": [c for c in blind + remaining if c["id"] == row["id"]],
                    "final_decision": human,
                }
            )
    scored.mkdir(exist_ok=False)
    for suite in SIZES:
        jsonl(scored / f"{suite}.jsonl", suites[suite])
    dump(
        scored / "coverage.json",
        {
            suite: {
                "cases": len(rows),
                "languages": dict(Counter(r["lang"] for r in rows)),
                "categories": dict(Counter(r.get("category", r.get("purpose")) for r in rows)),
            }
            for suite, rows in suites.items()
        },
    )
    jsonl(review / "final-adjudication.jsonl", log)
    dump(folder / "exclusions.json", exclusions)
    files = [p for p in folder.rglob("*") if p.is_file() and p != target]
    dump(
        target,
        {
            "status": "frozen",
            "review_description": (
                "separate-session AI review with human checking"
                if acceptance == "human"
                else "owner-approved, AI-assisted adjudication; 9 user and 135 AI decisions"
            ),
            "acceptance_protocol": acceptance,
            "owner_authorization": (
                "Explicit 2026-11-19 architecture task: owner considers revision complete"
                if acceptance != "human"
                else "actual human-checks.jsonl attestations"
            ),
            "limitations": [
                "AI decisions are not human-reviewed; shared author/reviewer bias remains",
                "Unflagged unsampled cases retain original labels after separate-session AI review",
            ]
            if acceptance != "human"
            else [],
            "included": {s: len(suites[s]) for s in SIZES},
            "exclusions": exclusions,
            "hashes": {str(p.relative_to(folder)): digest(p) for p in files},
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "prepare", "review-report", "freeze"))
    parser.add_argument(
        "--acceptance", default="human", choices=("human", "owner-approved-ai-assisted")
    )
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    elif args.action == "review-report":
        dump(VERSION / "progress.json", review_report())
    elif args.action == "freeze":
        freeze(acceptance=args.acceptance)
    else:
        result = validate()
        dump(VERSION / "validation.json", result)
        print(json.dumps({k: v for k, v in result.items() if k != "catalog_matches"}, indent=2))
        raise SystemExit(bool(result["errors"]))


if __name__ == "__main__":
    main()
