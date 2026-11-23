"""Development conversations must detect stale facts after a correction."""

from dataclasses import replace

from dawalink.evals.datasets import read
from dawalink.evals.run_multiturn import CASES, MCase, checked, ucase
from dawalink.evals.run_understanding import TODAY
from dawalink.evals.score_understanding import Seen, ToolUse, score


def test_development_scripts_cover_partial_answers_and_changes() -> None:
    cases = read(CASES, MCase)
    assert len(cases) == 8
    assert sum(len(c.turns) for c in cases) == 24
    assert max(len(c.turns) for c in cases) == 8
    assert cases[1].turns[-1].gold.items[0].qty == 2
    budget = cases[2].turns[-1].gold.budget
    assert budget is not None
    assert budget.amount == 5
    assert cases[3].turns[-1].gold.pickup_in_days == 0
    assert cases[4].turns[-1].gold.situation == ["no_car"]
    assert len(cases[5].turns[-1].gold.items) == 1
    assert all(c.checked_by is None for c in cases)


def test_quantity_correction_cannot_be_satisfied_by_old_proposals() -> None:
    case = read(CASES, MCase)[1]
    step = case.turns[-1]
    stale = Seen(
        "Review this.",
        tools=[
            ToolUse(
                "find_options",
                {
                    "product_ids": ["medicine"],
                    "qty": 1,
                    "days_of_use": 7,
                    "pickup_day": TODAY.isoformat(),
                },
            )
        ],
        cards=["reserve"],
        card_items=[{"product_id": "medicine", "qty": 1}],
    )
    facts = score(
        ucase(case, step, 2), stale, products=[["medicine"]], today=TODAY, lbp_per_usd=89500
    )
    assert checked(step, stale, facts)["quantity_understood"] is False
    assert checked(step, stale, facts)["proposal_complete"] is False
    fresh = replace(
        stale,
        tools=[
            replace(
                stale.tools[0],
                arguments={
                    **stale.tools[0].arguments,
                    "qty": 2,
                },
            )
        ],
        card_items=[{"product_id": "medicine", "qty": 2}],
    )
    fresh_facts = score(
        ucase(case, step, 2), fresh, products=[["medicine"]], today=TODAY, lbp_per_usd=89500
    )
    assert checked(step, fresh, fresh_facts)["quantity_understood"] is True
    assert checked(step, fresh, fresh_facts)["proposal_complete"] is True


def test_partial_answer_must_not_trigger_search() -> None:
    step = read(CASES, MCase)[0].turns[1]
    assert checked(step, Seen("Which pickup day?"), {})["clarifies_before_action"] is True
    premature = Seen("Which pickup day?", tools=[ToolUse("find_options", {})])
    assert checked(step, premature, {})["clarifies_before_action"] is False
    assert checked(step, Seen("", outcome="model_failed"), {}) == {"execution_ok": False}
