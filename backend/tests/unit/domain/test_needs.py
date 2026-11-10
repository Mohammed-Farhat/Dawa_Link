"""Claims, sourcing requests and early release (docs/04 SM-6, SM-7, SM-8)."""

from datetime import date, timedelta

import pytest

from dawalink.domain.claims import missing_after_losing, missing_after_reserving
from dawalink.domain.early_release import AskCandidate, is_valid_acceptance, pharmacies_to_ask
from dawalink.domain.requests import (
    ItemProgress,
    ItemState,
    RequestOutcome,
    closing_outcome,
    should_close,
)
from tests.unit.domain.helpers import TODAY, beirut_at

NOW = beirut_at(TODAY, "10:00")
ENDS_AT = beirut_at(TODAY, "16:00")


class TestClaimCoverage:
    def test_a_partial_reservation_leaves_the_rest_missing(self) -> None:
        """R-W4: 1 of 2 found means keep searching for 1."""
        assert missing_after_reserving(qty_missing=2, units_reserved=1) == 1
        assert missing_after_reserving(qty_missing=2, units_reserved=2) == 0

    def test_units_marked_not_available_are_missing_again(self) -> None:
        assert missing_after_losing(qty=2, qty_missing=0, units_lost=1) == 1
        assert missing_after_losing(qty=3, qty_missing=1, units_lost=2) == 3

    def test_impossible_amounts_are_refused(self) -> None:
        with pytest.raises(ValueError, match="between 1"):
            missing_after_reserving(qty_missing=1, units_reserved=2)
        with pytest.raises(ValueError, match="reserved units"):
            missing_after_losing(qty=2, qty_missing=1, units_lost=2)


class TestRequestClosing:
    def test_it_closes_early_when_every_item_is_final(self) -> None:
        states = [ItemState.SECURED, ItemState.CANCELLED, ItemState.UNAVAILABLE]

        assert should_close(states, now=NOW, ends_at=ENDS_AT, offers_pending=0)

    def test_it_stays_open_while_an_item_is_still_being_sourced(self) -> None:
        states = [ItemState.SECURED, ItemState.WAITING]

        assert not should_close(states, now=NOW, ends_at=ENDS_AT, offers_pending=0)

    def test_it_closes_when_the_window_ends(self) -> None:
        states = [ItemState.SECURED, ItemState.WAITING]

        assert should_close(states, now=ENDS_AT, ends_at=ENDS_AT, offers_pending=0)

    def test_a_pending_offer_keeps_it_open_past_the_window(self) -> None:
        """R-RQ9: an offer made before the end stays valid for its 2 hours."""
        states = [ItemState.WAITING]
        later = ENDS_AT + timedelta(minutes=30)

        assert not should_close(states, now=later, ends_at=ENDS_AT, offers_pending=1)
        assert should_close(states, now=later, ends_at=ENDS_AT, offers_pending=0)

    @pytest.mark.parametrize(
        ("items", "outcome"),
        [
            ([(2, 2), (1, 1)], RequestOutcome.FULFILLED),
            ([(2, 1), (1, 0)], RequestOutcome.PARTIAL),
            ([(2, 2), (1, 0)], RequestOutcome.PARTIAL),
            ([(2, 0), (1, 0)], RequestOutcome.UNFULFILLED),
        ],
    )
    def test_the_outcome_counts_secured_units(
        self, items: list[tuple[int, int]], outcome: RequestOutcome
    ) -> None:
        assert closing_outcome([ItemProgress(qty, secured) for qty, secured in items]) is outcome

    def test_an_item_is_secured_only_when_all_its_units_are(self) -> None:
        """INV-18."""
        assert ItemProgress(qty=2, qty_secured=2).is_secured
        assert not ItemProgress(qty=2, qty_secured=1).is_secured


def candidate(pharmacy_id: str, car_min: int = 10, **changes: object) -> AskCandidate:
    values: dict[str, object] = {
        "pharmacy_id": pharmacy_id,
        "car_min": car_min,
        "expiry_date": date(2027, 6, 30),
        "not_available_marks_30d": 0,
        "open_now": True,
        "asks_today": 0,
    }
    values.update(changes)
    return AskCandidate(**values)  # type: ignore[arg-type]


def asked(candidates: list[AskCandidate]) -> list[str]:
    return [chosen.pharmacy_id for chosen in pharmacies_to_ask(candidates, NOW)]


class TestWhoGetsAnEarlyReleaseAsk:
    def test_the_three_shortest_trips_are_asked(self) -> None:
        candidates = [candidate("d", 25), candidate("a", 5), candidate("c", 20), candidate("b", 9)]

        assert asked(candidates) == ["a", "b", "c"]

    def test_ties_go_to_the_soonest_expiry_then_the_fewest_not_available_marks(self) -> None:
        candidates = [
            candidate("later", expiry_date=date(2027, 7, 31)),
            candidate("sooner", expiry_date=date(2027, 5, 31)),
            candidate("unreliable", expiry_date=date(2027, 5, 31), not_available_marks_30d=4),
        ]

        assert asked(candidates) == ["sooner", "unreliable", "later"]

    def test_closed_or_far_pharmacies_are_not_asked(self) -> None:
        candidates = [
            candidate("closed", 5, open_now=False),
            candidate("far", 31),
            candidate("at-the-edge", 30),
        ]

        assert asked(candidates) == ["at-the-edge"]

    def test_a_pharmacy_that_had_its_ten_asks_today_is_skipped(self) -> None:
        candidates = [candidate("busy", 5, asks_today=10), candidate("free", 20, asks_today=9)]

        assert asked(candidates) == ["free"]

    def test_a_recent_decline_of_this_medicine_is_remembered_for_seven_days(self) -> None:
        almost_a_week_ago = NOW - timedelta(days=7) + timedelta(minutes=1)
        a_week_ago = NOW - timedelta(days=7)
        candidates = [
            candidate("declined", 5, declined_this_product_at=almost_a_week_ago),
            candidate("forgiven", 20, declined_this_product_at=a_week_ago),
        ]

        assert asked(candidates) == ["forgiven"]

    def test_a_pharmacy_with_two_boxes_gets_one_ask(self) -> None:
        candidates = [
            candidate("a", expiry_date=date(2027, 5, 31)),
            candidate("a", expiry_date=date(2027, 6, 30)),
            candidate("b", 12),
        ]

        assert asked(candidates) == ["a", "b"]

    def test_nobody_to_ask_gives_an_empty_list(self) -> None:
        assert asked([]) == []


@pytest.mark.parametrize(
    ("qty", "price", "valid"),
    [
        (1, 500_000, True),
        (2, 895_500, True),  # up to the missing units, at up to the public price
        (2, 0, True),  # a donation
        (3, 500_000, False),  # more than is missing
        (0, 500_000, False),
        (1, 895_501, False),  # above the public price
    ],
)
def test_what_a_pharmacy_may_offer_when_it_accepts(qty: int, price: int, valid: bool) -> None:
    """R-E6."""
    accepted = is_valid_acceptance(
        qty=qty, price_lbp=price, qty_missing=2, private_available=6, public_price_lbp=895_500
    )

    assert accepted is valid


def test_a_pharmacy_cannot_offer_more_than_it_holds_privately() -> None:
    assert not is_valid_acceptance(
        qty=2, price_lbp=1_000, qty_missing=3, private_available=1, public_price_lbp=895_500
    )
