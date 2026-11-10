"""Opening hours (docs/04 R-T2)."""

from datetime import date, timedelta

import pytest

from dawalink.domain.opening_hours import (
    OpenRange,
    WeeklyHours,
    closes_at,
    is_open,
    last_closing,
    open_time_left,
)
from tests.unit.domain.helpers import TODAY, beirut_at, every_day

# Open in two parts on weekdays, mornings only on Saturday, closed on Sunday.
SPLIT = WeeklyHours.of(
    {
        **{weekday: [("08:00", "13:00"), ("16:00", "21:00")] for weekday in range(5)},
        5: [("09:00", "14:00")],
    }
)
SATURDAY = date(2026, 10, 24)
SUNDAY = date(2026, 10, 25)


@pytest.mark.parametrize(
    ("clock_time", "expected"),
    [
        ("07:59", False),
        ("08:00", True),
        ("12:59", True),
        ("13:00", False),  # a range is [opens, closes)
        ("15:59", False),
        ("16:00", True),
        ("20:59", True),
        ("21:00", False),
    ],
)
def test_open_now_follows_the_ranges(clock_time: str, expected: bool) -> None:
    assert is_open(SPLIT, beirut_at(TODAY, clock_time)) is expected


def test_a_closed_day_is_never_open() -> None:
    assert not is_open(SPLIT, beirut_at(SUNDAY, "10:00"))
    assert not SPLIT.is_open_day(SUNDAY)
    assert last_closing(SPLIT, SUNDAY) is None


def test_the_current_range_says_when_it_closes() -> None:
    assert closes_at(SPLIT, beirut_at(TODAY, "09:00")) == beirut_at(TODAY, "13:00")
    assert closes_at(SPLIT, beirut_at(TODAY, "17:00")) == beirut_at(TODAY, "21:00")
    assert closes_at(SPLIT, beirut_at(TODAY, "14:00")) is None


def test_the_last_closing_is_the_end_of_the_last_range() -> None:
    assert last_closing(SPLIT, TODAY) == beirut_at(TODAY, "21:00")
    assert last_closing(SPLIT, SATURDAY) == beirut_at(SATURDAY, "14:00")


def test_closing_at_24_00_means_the_next_midnight() -> None:
    late = every_day("10:00", "24:00")

    assert is_open(late, beirut_at(TODAY, "23:59"))
    assert last_closing(late, TODAY) == beirut_at(TODAY + timedelta(days=1), "00:00")


def test_opening_time_left_counts_a_range_that_starts_later_today() -> None:
    assert open_time_left(SPLIT, beirut_at(TODAY, "07:00")) == timedelta(hours=10)
    assert open_time_left(SPLIT, beirut_at(TODAY, "12:30")) == timedelta(hours=5, minutes=30)
    assert open_time_left(SPLIT, beirut_at(TODAY, "14:00")) == timedelta(hours=5)
    assert open_time_left(SPLIT, beirut_at(TODAY, "20:15")) == timedelta(minutes=45)
    assert open_time_left(SPLIT, beirut_at(TODAY, "21:00")) == timedelta(0)


def test_ranges_are_put_in_order() -> None:
    hours = WeeklyHours.of({0: [("16:00", "21:00"), ("08:00", "13:00")]})

    assert hours.by_weekday[0] == (OpenRange(480, 780), OpenRange(960, 1260))


@pytest.mark.parametrize(
    "ranges",
    [
        {0: [("08:00", "13:00"), ("12:00", "21:00")]},  # overlapping
        {0: [("08:00", "10:00"), ("11:00", "12:00"), ("13:00", "14:00")]},  # three ranges
        {0: [("13:00", "08:00")]},  # closes before it opens
        {0: [("08:00", "25:00")]},
        {0: [("08:60", "09:00")]},
        {7: [("08:00", "13:00")]},  # no such weekday
    ],
)
def test_invalid_hours_are_refused(ranges: dict[int, list[tuple[str, str]]]) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - any refusal is right here
        WeeklyHours.of(ranges)


def test_hours_must_cover_seven_days() -> None:
    with pytest.raises(ValueError, match="seven"):
        WeeklyHours(((),) * 6)
