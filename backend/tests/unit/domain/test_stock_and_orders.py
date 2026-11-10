"""Stock quantities, visibility and order rules (docs/04 SM-3, SM-5, INV-1, INV-7, INV-16)."""

from datetime import timedelta

import pytest

from dawalink.domain.accounts import PharmacyStatus
from dawalink.domain.expiry import Zone
from dawalink.domain.inventory import ListingControl, NotEnoughStock, Stock, is_visible
from dawalink.domain.orders import (
    OrderState,
    is_no_show,
    is_offer_over,
    is_reserved_in_time,
    mark_not_available,
)
from tests.unit.domain.helpers import TODAY, beirut_at

DEADLINE = beirut_at(TODAY, "21:00")
SECOND = timedelta(seconds=1)


class TestStock:
    def test_reserving_holds_units_without_removing_them(self) -> None:
        stock = Stock(on_hand=5).reserve(2)

        assert (stock.on_hand, stock.reserved, stock.available) == (5, 2, 3)

    def test_the_last_unit_can_be_reserved_once(self) -> None:
        stock = Stock(on_hand=1).reserve(1)

        with pytest.raises(NotEnoughStock) as refused:
            stock.reserve(1)
        assert (refused.value.asked, refused.value.available) == (1, 0)

    def test_a_pickup_removes_the_held_units_from_the_shelf(self) -> None:
        """O2: on hand and reserved both go down."""
        assert Stock(5, 2).remove_reserved(2) == Stock(3, 0)

    def test_units_marked_not_available_leave_the_shelf_too(self) -> None:
        """O3, for some of the units."""
        assert Stock(5, 2).remove_reserved(1) == Stock(4, 1)

    def test_a_cancel_or_a_no_show_puts_units_back(self) -> None:
        assert Stock(5, 2).release(2) == Stock(5, 0)

    def test_an_edit_below_the_reserved_units_is_raised_to_protect_them(self) -> None:
        """R-U3."""
        assert Stock(5, 2).set_on_hand(1) == (Stock(2, 2), True)
        assert Stock(5, 2).set_on_hand(0) == (Stock(2, 2), True)
        assert Stock(5, 2).set_on_hand(8) == (Stock(8, 2), False)
        assert Stock(5, 2).set_on_hand(2) == (Stock(2, 2), False)

    @pytest.mark.parametrize(("on_hand", "reserved"), [(1, 2), (-1, 0), (3, -1)])
    def test_reserved_never_leaves_its_bounds(self, on_hand: int, reserved: int) -> None:
        """INV-1."""
        with pytest.raises(ValueError, match="reserved"):
            Stock(on_hand, reserved)

    def test_more_than_is_held_cannot_be_released_or_removed(self) -> None:
        with pytest.raises(ValueError, match="reserved"):
            Stock(5, 1).release(2)
        with pytest.raises(ValueError, match="reserved"):
            Stock(5, 1).remove_reserved(2)

    @pytest.mark.parametrize("units", [0, -1])
    def test_units_start_at_one(self, units: int) -> None:
        with pytest.raises(ValueError, match="start at 1"):
            Stock(5).reserve(units)

    def test_a_negative_quantity_is_refused(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            Stock(5).set_on_hand(-1)


VISIBLE = {
    "zone": Zone.NEAR_EXPIRY,
    "control": ListingControl.LIVE,
    "pharmacy_status": PharmacyStatus.APPROVED,
    "qty_available": 1,
    "controlled": False,
}


def test_a_listing_is_visible_when_every_condition_holds() -> None:
    assert is_visible(**VISIBLE)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "change",
    [
        {"zone": Zone.EARLY_RELEASE},
        {"zone": Zone.PRIVATE},
        {"zone": Zone.EXPIRED},
        {"zone": Zone.NOT_ELIGIBLE},
        {"control": ListingControl.PAUSED},
        {"pharmacy_status": PharmacyStatus.SUSPENDED},
        {"pharmacy_status": PharmacyStatus.PENDING},
        {"qty_available": 0},
        {"controlled": True},
    ],
)
def test_breaking_any_one_condition_hides_it(change: dict[str, object]) -> None:
    """INV-16: visible if and only if the whole SM-3 condition holds."""
    assert not is_visible(**{**VISIBLE, **change})  # type: ignore[arg-type]


class TestOrderTiming:
    def test_pickup_and_cancel_are_possible_until_the_deadline(self) -> None:
        assert is_reserved_in_time(OrderState.RESERVED, DEADLINE - SECOND, DEADLINE)
        assert not is_reserved_in_time(OrderState.RESERVED, DEADLINE, DEADLINE)

    def test_there_is_no_late_pickup(self) -> None:
        """INV-7."""
        assert not is_reserved_in_time(OrderState.RESERVED, DEADLINE + SECOND, DEADLINE)
        assert not is_reserved_in_time(OrderState.PICKED_UP, DEADLINE - SECOND, DEADLINE)
        assert not is_reserved_in_time(OrderState.OFFERED, DEADLINE - SECOND, DEADLINE)

    def test_a_no_show_begins_exactly_at_the_deadline(self) -> None:
        assert not is_no_show(OrderState.RESERVED, DEADLINE - SECOND, DEADLINE)
        assert is_no_show(OrderState.RESERVED, DEADLINE, DEADLINE)

    def test_only_a_reservation_can_become_a_no_show(self) -> None:
        """A stale deadline does nothing once the order has moved on."""
        for state in (OrderState.PICKED_UP, OrderState.CANCELLED_BY_CLIENT, OrderState.OFFERED):
            assert not is_no_show(state, DEADLINE + SECOND, DEADLINE)

    def test_an_offer_ends_when_its_time_is_up(self) -> None:
        assert not is_offer_over(OrderState.OFFERED, DEADLINE - SECOND, DEADLINE)
        assert is_offer_over(OrderState.OFFERED, DEADLINE, DEADLINE)
        assert not is_offer_over(OrderState.RESERVED, DEADLINE, DEADLINE)


class TestNotAvailable:
    def test_some_units_keep_the_order_reserved_for_the_rest(self) -> None:
        after = mark_not_available(qty_locked=2, units=1)

        assert (after.state, after.qty_locked) == (OrderState.RESERVED, 1)

    def test_all_units_end_the_order(self) -> None:
        after = mark_not_available(qty_locked=2, units=2)

        assert (after.state, after.qty_locked) == (OrderState.NOT_AVAILABLE, 0)

    @pytest.mark.parametrize("units", [0, 3])
    def test_units_must_be_between_one_and_the_units_held(self, units: int) -> None:
        with pytest.raises(ValueError, match="between 1"):
            mark_not_available(qty_locked=2, units=units)
