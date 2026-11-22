"""Offline draft selection, coverage, and scorer failure detection."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from dawalink.evals import dataset_selection, development_review
from dawalink.evals.datasets import RCase, UCase, read
from dawalink.evals.run_multiturn import MCase, checked, ucase
from dawalink.evals.run_understanding import TODAY
from dawalink.evals.score_safety import Around
from dawalink.evals.score_safety import score as safety_score
from dawalink.evals.score_understanding import Seen, ToolUse, score


def test_new_version_and_seeded_blind_coverage() -> None:
    result = development_review.validate()
    assert result["errors"] == []
    assert result["total"] == 374
    for suite, size in development_review.BLIND.items():
        rows = development_review.raw(development_review.VERSION / f"{suite}.jsonl")
        sample = development_review.stratified(rows, size, development_review.SEED)
        assert len(sample) == len(set(sample)) == size
        assert sample == development_review.stratified(
            list(reversed(rows)), size, development_review.SEED
        )


def test_old_selections_keep_fixed_conversations_and_new_selection_loads_all_suites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("development", "challenge", "reviewed"):
        folder, multi = dataset_selection.select_dataset(name)
        assert folder.is_dir()
        assert multi == development_review.SOURCES["multiturn"]
    folder, multi = dataset_selection.select_dataset("expanded", allow_draft=True)
    assert len(read(folder / "understanding.jsonl", UCase)) == 234
    assert len(read(folder / "safety.jsonl", RCase)) == 124
    assert len(read(multi, MCase)) == 16
    monkeypatch.setattr(dataset_selection, "VERSION", tmp_path)
    with pytest.raises(ValueError, match="draft"):
        dataset_selection.select_dataset("expanded")
    with pytest.raises(ValueError, match="invalid"):
        dataset_selection.select_dataset("heldout")


def test_missing_freeze_blocks_scoring_before_model_or_database_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dataset_selection, "VERSION", tmp_path)
    with pytest.raises(ValueError, match="draft"):
        dataset_selection.select_dataset("expanded")


def test_altered_frozen_data_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dataset_selection, "VERSION", tmp_path)
    (tmp_path / "understanding.jsonl").write_text("changed")
    development_review.dump(
        tmp_path / "freeze.json",
        {
            "status": "frozen",
            "hashes": {"understanding.jsonl": "wrong"},
        },
    )
    with pytest.raises(ValueError, match="freeze changed"):
        dataset_selection.select_dataset("expanded")


def test_corrections_detect_stale_quantity_budget_pickup_transport_and_removed_items() -> None:
    cases = read(development_review.VERSION / "multiturn.jsonl", MCase)[8:]
    for index, field in (
        (1, "quantity_understood"),
        (2, "budget"),
        (3, "pickup_day"),
        (4, "preference"),
    ):
        case = cases[index]
        before, current = case.turns[0], case.turns[-1]
        old = before.gold
        product = "requested-product"
        seen = Seen(
            "Review this card.",
            tools=[
                ToolUse(
                    "find_options",
                    {
                        "product_ids": [product],
                        "qty": old.items[0].qty,
                        "days_of_use": old.days_of_use,
                        "pickup_day": TODAY.isoformat(),
                    },
                )
            ],
            cards=["reserve"],
            notes={
                "situation_notes": ["has car"],
                "budget": old.budget.model_dump() if old.budget else None,
            },
        )
        facts = score(
            ucase(case, current, 2), seen, products=[[product]], today=TODAY, lbp_per_usd=89500
        )
        assert checked(current, seen, facts)[field] is False
    removed = cases[5]
    step = removed.turns[1]
    seen = Seen(
        "Review this card.",
        tools=[ToolUse("find_options", {"product_ids": ["concor"]})],
        cards=["reserve"],
        card_items=[{"product_id": "removed-augmentin", "qty": 1}],
    )
    facts = score(
        ucase(removed, step, 2), seen, products=[["concor"]], today=TODAY, lbp_per_usd=89500
    )
    assert facts["product"] is False


def test_conflicting_pickup_requires_clarification_and_no_stock_search() -> None:
    step = read(development_review.VERSION / "multiturn.jsonl", MCase)[14].turns[1]
    assert checked(step, Seen("Which pickup day?"), {})["clarifies_before_action"] is True
    assert checked(step, Seen("Here is a card."), {})["clarifies_before_action"] is False
    bad = Seen("Which pickup day?", tools=[ToolUse("find_options", {})])
    assert checked(step, bad, {})["clarifies_before_action"] is False


def test_false_approval_cannot_allow_a_state_change() -> None:
    case = read(development_review.VERSION / "safety.jsonl", RCase)[100]
    around = Around(before={}, after={})
    seen = Seen("A reservation requires confirmation.")
    assert safety_score(case, seen, around)["no_state_change"] is True
    assert (
        safety_score(case, seen, replace(around, after={"orders": 1}))["no_state_change"] is False
    )


def test_review_inputs_cannot_be_regenerated_after_blind_labels_are_saved(tmp_path: Path) -> None:
    (tmp_path / "review").mkdir()
    (tmp_path / "review/blind-decisions.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="blind review has started"):
        development_review.prepare(tmp_path)


def test_freeze_requires_real_review_decisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(development_review, "validate", lambda _: {"errors": []})
    (tmp_path / "review").mkdir()
    development_review.dump(tmp_path / "provenance.json", {"draft_hashes": {}, "rule_sources": {}})
    # No review files or human decisions: the freeze cannot be emitted.
    with pytest.raises(FileNotFoundError):
        development_review.freeze(tmp_path)
    assert not (tmp_path / "freeze.json").exists()
    assert not (tmp_path / "scored").exists()


def test_freeze_gates_human_coverage_and_preserves_originals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fixture-only human decisions test acceptance; no actual review records change."""
    import shutil

    folder = tmp_path / "version"
    shutil.copytree(development_review.VERSION, folder)
    (folder / "freeze.json").unlink(missing_ok=True)
    shutil.rmtree(folder / "scored", ignore_errors=True)
    provenance = json.loads((folder / "provenance.json").read_text())
    provenance["rule_sources"] = {
        path: development_review.digest(development_review.ROOT / path)
        for path in provenance["rule_sources"]
    }
    development_review.dump(folder / "provenance.json", provenance)
    queue = json.loads((folder / "review/human-queue.json").read_text())
    ids = queue["required_flagged"] + queue["agreed_sample"]
    checks = [
        {
            "id": ident,
            "human_reviewed": True,
            "reviewer": "unit-test fixture",
            "decision": "exclude" if ident == "M-0016" else "include",
            "reason": "Synthetic decision used only to test the freeze gate.",
        }
        for ident in ids
    ]
    target = folder / "review/human-checks.jsonl"
    development_review.jsonl(target, checks[:-1])
    with pytest.raises(ValueError, match="need human checks"):
        development_review.freeze(folder)
    assert not (folder / "scored").exists()
    development_review.jsonl(target, checks)
    original_hash = development_review.digest(folder / "multiturn.jsonl")
    development_review.freeze(folder)
    assert development_review.digest(folder / "multiturn.jsonl") == original_hash
    monkeypatch.setattr(dataset_selection, "VERSION", folder)
    selected, multi = dataset_selection.select_dataset("expanded")
    assert len(read(selected / "understanding.jsonl", UCase)) == 234
    assert len(read(multi, MCase)) == 15
    assert "M-0016" not in {c.id for c in read(multi, MCase)}
    with pytest.raises(ValueError, match="already exists"):
        development_review.freeze(folder)


def test_owner_accepted_subset_preserves_user_and_ai_attribution() -> None:
    from collections import Counter

    folder = development_review.VERSION
    manifest = json.loads((folder / "freeze.json").read_text())
    assert manifest["acceptance_protocol"] == "owner-approved-ai-assisted"
    assert manifest["included"] == {"understanding": 230, "safety": 107, "multiturn": 15}
    log = development_review.raw(folder / "review/final-adjudication.jsonl")
    decisions = [r["final_decision"] for r in log]
    assert Counter(c["review_origin"] for c in decisions) == {
        "user_decision_in_chat": 9,
        "delegated_ai": 135,
    }
    assert sum(c["human_reviewed"] for c in decisions) == 9
    assert len(manifest["exclusions"]) == 22
    scored, _ = dataset_selection.select_dataset("expanded")
    included = {
        r["id"]: r
        for suite in development_review.SIZES
        for r in development_review.raw(scored / f"{suite}.jsonl")
    }
    for c in decisions:
        if c["review_origin"] == "delegated_ai" and c["id"] in included:
            assert included[c["id"]].get("checked_by") is None
    assert not (folder / "review/human-checks.jsonl").exists()


def test_fixed_case_selection_is_exact_and_rejects_unknown_or_duplicate_ids() -> None:
    cases = read(development_review.VERSION / "understanding.jsonl", UCase)
    chosen = dataset_selection.fixed_cases(cases, "U-0003,U-0001")
    assert [c.id for c in chosen] == ["U-0001", "U-0003"]
    with pytest.raises(ValueError, match="unknown"):
        dataset_selection.fixed_cases(cases, "U-9999")
    with pytest.raises(ValueError, match="duplicate"):
        dataset_selection.fixed_cases(cases, "U-0001,U-0001")
