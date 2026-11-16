"""Expiry dates, zones and the expiry fit (docs/04 R-T7, SM-3, R-F1)."""

from datetime import date, timedelta

import pytest

from dawalink.domain.expiry import (
    AmbiguousDate,
    DayMonthOrder,
    Zone,
    day_month_order,
    days_left,
    fits,
    last_day_of_use,
    last_pickup_day_that_fits,
    parse_expiry,
    parse_expiry_cell,
    zone_of,
)
from tests.unit.domain.helpers import TODAY


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-11", date(2026, 11, 30)),
        ("2026-12", date(2026, 12, 31)),
        ("2027-02", date(2027, 2, 28)),
        ("2028-02", date(2028, 2, 29)),  # a leap year
        ("2026-11-05", date(2026, 11, 5)),
        (" 2026-11 ", date(2026, 11, 30)),
    ],
)
def test_a_month_means_its_last_day(text: str, expected: date) -> None:
    assert parse_expiry(text) == expected


@pytest.mark.parametrize("text", ["11/26", "2026-13", "2026-00", "2026-11-31", "soon", ""])
def test_other_formats_are_refused(text: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - any refusal is right here
        parse_expiry(text)


def test_days_left_counts_whole_days() -> None:
    assert days_left(TODAY, TODAY) == 0
    assert days_left(TODAY + timedelta(days=1), TODAY) == 1
    assert days_left(TODAY - timedelta(days=1), TODAY) == -1


@pytest.mark.parametrize(
    ("days", "zone"),
    [
        (-1, Zone.EXPIRED),
        (0, Zone.NEAR_EXPIRY),  # no fixed minimum: the expiry fit decides who it suits
        (180, Zone.NEAR_EXPIRY),
        (181, Zone.EARLY_RELEASE),
        (270, Zone.EARLY_RELEASE),
        (271, Zone.PRIVATE),
    ],
)
def test_zone_boundaries(days: int, zone: Zone) -> None:
    assert zone_of(days) is zone


def test_a_controlled_or_unmatched_product_is_never_eligible() -> None:
    assert zone_of(30, eligible=False) is Zone.NOT_ELIGIBLE
    assert zone_of(-5, eligible=False) is Zone.NOT_ELIGIBLE


class TestExpiryFit:
    """The examples of R-F1: today is Oct 20 and the box expires on Oct 21."""

    box = date(2026, 10, 21)
    tomorrow = TODAY + timedelta(days=1)

    def test_one_day_of_use_picked_up_today_fits(self) -> None:
        assert fits(self.box, TODAY, 1)

    def test_one_day_of_use_picked_up_tomorrow_fits_on_the_expiry_day(self) -> None:
        assert fits(self.box, self.tomorrow, 1)

    def test_three_days_of_use_does_not_fit(self) -> None:
        assert not fits(self.box, TODAY, 3)

    def test_the_professors_example_of_twelve_days(self) -> None:
        assert not fits(TODAY + timedelta(days=2), TODAY, 12)
        assert fits(TODAY + timedelta(days=15), TODAY, 12)

    def test_the_boundary_is_the_last_day_of_use(self) -> None:
        last_day = last_day_of_use(TODAY, 12)

        assert last_day == date(2026, 10, 31)
        assert fits(last_day, TODAY, 12)
        assert not fits(last_day - timedelta(days=1), TODAY, 12)

    @pytest.mark.parametrize("days_of_use", [0, -3])
    def test_days_of_use_start_at_one(self, days_of_use: int) -> None:
        with pytest.raises(ValueError, match="start at 1"):
            fits(self.box, TODAY, days_of_use)
        with pytest.raises(ValueError, match="start at 1"):
            last_pickup_day_that_fits(self.box, days_of_use)

    def test_the_last_pickup_day_that_fits_is_the_same_rule_turned_around(self) -> None:
        """R-F6: a box fits from a pickup day exactly when that day isn't too late."""
        for left in range(15):
            expiry = TODAY + timedelta(days=left)
            for days_of_use in range(1, 15):
                last = last_pickup_day_that_fits(expiry, days_of_use)
                for ahead in range(-2, 15):
                    pickup_day = TODAY + timedelta(days=ahead)
                    assert fits(expiry, pickup_day, days_of_use) == (pickup_day <= last)

    def test_one_day_of_use_can_be_picked_up_until_the_expiry_day(self) -> None:
        assert last_pickup_day_that_fits(self.box, 1) == self.box


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-11", date(2026, 11, 30)),
        ("2026-11-05", date(2026, 11, 5)),
        ("2026/11/05", date(2026, 11, 5)),
        ("2026/11", date(2026, 11, 30)),
        ("11/2026", date(2026, 11, 30)),
        ("3/2027", date(2027, 3, 31)),
        ("Nov-26", date(2026, 11, 30)),
        ("nov 2026", date(2026, 11, 30)),
        ("November-2026", date(2026, 11, 30)),
    ],
)
def test_a_cell_of_a_stock_file_is_read_when_it_means_one_thing(text: str, expected: date) -> None:
    assert parse_expiry_cell(text) == expected


@pytest.mark.parametrize("text", ["03/04/2027", "3-4-27", "31.12.2026", "12/31/2026"])
def test_a_day_and_a_month_as_numbers_are_ambiguous(text: str) -> None:
    """Even "31.12.2026", which a person reads at once: one rule, no surprises."""
    with pytest.raises(AmbiguousDate):
        parse_expiry_cell(text)


@pytest.mark.parametrize("text", ["11/26", "2026-13", "13/2026", "Foo-26", "soon", ""])
def test_a_cell_that_is_no_date_is_refused(text: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - any refusal is right here
        parse_expiry_cell(text)


def test_a_file_shows_how_it_writes_its_dates_or_shows_nothing() -> None:
    """One date that can only be read one way settles it for the whole file. Tried with
    Excel on a computer set to US dates: a typed 2027-03-31 was saved as 3/31/2027."""
    assert day_month_order(["3/31/2027", "3/4/2027", "2027-03"]) is DayMonthOrder.MONTH_FIRST
    assert day_month_order(["31/03/2027", "03/04/2027"]) is DayMonthOrder.DAY_FIRST
    assert day_month_order(["30.06.27", "Mar-27"]) is DayMonthOrder.DAY_FIRST
    # No date says which, or two dates disagree: nothing is shown, and nothing is guessed.
    assert day_month_order(["3/4/2027", "5/6/2027", "2027-03"]) is None
    assert day_month_order(["31/03/2027", "3/31/2027"]) is None
    assert day_month_order([]) is None


def test_two_numbers_are_read_with_the_order_the_file_showed() -> None:
    assert parse_expiry_cell("3/4/2027", DayMonthOrder.MONTH_FIRST) == date(2027, 3, 4)
    assert parse_expiry_cell("3/4/2027", DayMonthOrder.DAY_FIRST) == date(2027, 4, 3)
    assert parse_expiry_cell("30.06.27", DayMonthOrder.DAY_FIRST) == date(2027, 6, 30)
    # The other forms don't depend on it.
    assert parse_expiry_cell("Mar-27", DayMonthOrder.DAY_FIRST) == date(2027, 3, 31)
    with pytest.raises(ValueError):  # noqa: PT011 - a 31 June doesn't exist
        parse_expiry_cell("31/06/2027", DayMonthOrder.DAY_FIRST)
