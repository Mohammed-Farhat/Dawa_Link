import json

import pytest

from dawalink.agent.guards.grounding import claims_completed, comparison_errors
from dawalink.agent.guards.language import language_of
from dawalink.agent.guards.output import POINTS_AT_A_CARD


def options() -> list[str]:
    return [
        json.dumps(
            {
                "options": [
                    {
                        "product_id": "same",
                        "pharmacy": {"name": "Pharmacy One"},
                        "price": "500,000 LBP",
                        "travel": {"car_min": 4, "walk_min": 8},
                        "expiry_date": "2026-12-31",
                    },
                    {
                        "product_id": "same",
                        "pharmacy": {"name": "Pharmacy Two"},
                        "price": "333,000 LBP",
                        "travel": {"car_min": 3, "walk_min": 12},
                        "expiry_date": "2027-03-16",
                    },
                ]
            }
        )
    ]


@pytest.mark.parametrize(
    "text",
    [
        "I've reserved it.",
        "I cancelled your order.",
        "Reserved for you.",
        "تم الحجز",
    ],
)
def test_proposals_do_not_prove_completed_actions(text: str) -> None:
    assert claims_completed(text)


@pytest.mark.parametrize(
    "text",
    [
        "I have not reserved it.",
        "Tap to reserve it.",
        "I can't cancel that order.",
        "The pharmacy where you reserved it.",
        "A cancellation card is ready for your approval.",
    ],
)
def test_proposals_and_refusals_are_valid(text: str) -> None:
    assert not claims_completed(text)


@pytest.mark.parametrize(
    "text",
    [
        "Here is the cancellation card.",
        "Here's the reservation card.",
        "The card is below.",
    ],
)
def test_nonexistent_cards_are_recognized(text: str) -> None:
    assert POINTS_AT_A_CARD.search(text)


@pytest.mark.parametrize(
    ("text", "wrong"),
    [
        ("Pharmacy One is closest.", True),
        ("Pharmacy Two is closest.", False),
        ("Pharmacy One is cheaper than Pharmacy Two.", True),
        ("Pharmacy Two is cheaper than Pharmacy One.", False),
        ("Pharmacy One has the latest expiry, 31 December 2026.", True),
        ("Pharmacy Two has the latest expiry, 16 March 2027.", False),
        ("Pharmacy One: 4 minutes by car, 500,000 LBP.", False),
    ],
)
def test_comparisons_use_associated_facts(text: str, wrong: bool) -> None:
    assert bool(comparison_errors(text, options())) is wrong


def test_walking_rank_differs_from_driving_and_latest_search_supersedes() -> None:
    assert not comparison_errors("Pharmacy One is closest.", options(), on_foot=True)
    assert comparison_errors("Pharmacy Two is closest.", options(), on_foot=True)
    assert not comparison_errors("Pharmacy One is closest.", [*options(), '{"options": []}'])


@pytest.mark.parametrize(
    ("text", "noted", "wanted"),
    [
        ("baddi concor w ana 3ande siyyara", None, "arabizi"),
        ("yes, 2 boxes", "arabizi", "arabizi"),
        ("I would like two boxes tomorrow", "arabizi", "english"),
        ("بدي علبتين من الدواء", "english", "arabic"),
    ],
)
def test_language_corrections_preserve_or_switch_explicitly(
    text: str, noted: str | None, wanted: str
) -> None:
    assert language_of(text, noted) == wanted


def test_decimal_prices_do_not_break_comparison_subject_associations() -> None:
    # Candidate1's live development failure: the reply named the pharmacy before
    # a parenthesized dollar decimal; the guard lost the subject at that decimal.
    good = "Pharmacy Two: 333,000 LBP (about $3.72), the lowest price."
    bad = "Pharmacy One: 500,000 LBP (about $5.59), the lowest price."
    assert not comparison_errors(good, options())
    assert comparison_errors(bad, options())


def test_spoken_closing_half_hour_must_use_exact_numeric_tool_hours() -> None:
    assert comparison_errors("Pharmacy One btsakker 5 w noss (17:00).", options())
    assert not comparison_errors("Pharmacy One closes at 17:00.", options())
