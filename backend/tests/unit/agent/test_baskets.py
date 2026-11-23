from typing import Any

import pytest

from dawalink.agent.guards.baskets import incomplete_plan_cards


def group(plan: str, index: int, count: int = 2) -> dict[str, Any]:
    return {"plan_id": plan, "plan_group_index": index, "plan_group_count": count}


@pytest.mark.parametrize(
    ("text", "cards", "incomplete"),
    [
        ("Complete basket", [group("a", 0), group("a", 1)], False),
        ("Complete basket", [group("a", 0)], True),
        ("Complete basket", [group("a", 0), group("a", 0)], True),
        ("Two complete options", [group("a", 0, 1), group("b", 0)], True),
        ("Partial plan: the second pharmacy group is missing.", [group("a", 0)], False),
        ("خطة جزئية: المجموعة الثانية ناقصة", [group("a", 0)], False),
        ("No plans were made", [], False),
        ("Older card", [{"listing_id": "old"}], False),
    ],
)
def test_each_plan_needs_every_group_or_partial_explanation(
    text: str, cards: list[dict[str, Any]], incomplete: bool
) -> None:
    assert incomplete_plan_cards(text, cards) is incomplete
