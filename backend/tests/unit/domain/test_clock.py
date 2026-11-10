"""The app clock and Beirut time, including daylight saving (docs/04 R-T1, R-T11; FR-21)."""

from datetime import UTC, date, datetime, time, timedelta

import pytest

from dawalink.domain.clock import (
    ManualClock,
    SystemClock,
    at_beirut,
    beirut,
    beirut_date,
    end_of_day,
)
from dawalink.domain.opening_hours import WeeklyHours
from dawalink.domain.pickup import pickup_deadline
from dawalink.domain.windows import in_request_hours, search_window_end


def test_the_system_clock_gives_an_aware_utc_moment() -> None:
    assert SystemClock().now().tzinfo is UTC


def test_a_manual_clock_moves_only_when_told() -> None:
    clock = ManualClock(datetime(2026, 10, 20, 7, 0, tzinfo=UTC))

    assert clock.now() == clock.now()
    clock.advance(timedelta(hours=2))
    assert clock.now() == datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    clock.set(datetime(2026, 11, 1, tzinfo=UTC))
    assert clock.now() == datetime(2026, 11, 1, tzinfo=UTC)


def test_a_manual_clock_cannot_go_backwards_by_advancing() -> None:
    clock = ManualClock(datetime(2026, 10, 20, tzinfo=UTC))

    with pytest.raises(ValueError, match="backwards"):
        clock.advance(timedelta(seconds=-1))


def test_moments_without_a_time_zone_are_refused() -> None:
    with pytest.raises(ValueError, match="time zone"):
        beirut(datetime(2026, 10, 20, 12, 0))
    with pytest.raises(ValueError, match="time zone"):
        ManualClock(datetime(2026, 10, 20, 12, 0))


def test_today_is_the_beirut_date_not_the_utc_date() -> None:
    # 22:30 UTC on the 20th is already 01:30 on the 21st in Beirut (summer time, UTC+3).
    assert beirut_date(datetime(2026, 10, 20, 22, 30, tzinfo=UTC)) == date(2026, 10, 21)
    assert beirut_date(datetime(2026, 10, 20, 20, 30, tzinfo=UTC)) == date(2026, 10, 20)


def test_beirut_wall_time_follows_summer_and_winter_time() -> None:
    assert at_beirut(date(2026, 7, 1), time(8, 0)) == datetime(2026, 7, 1, 5, 0, tzinfo=UTC)
    assert at_beirut(date(2026, 12, 1), time(8, 0)) == datetime(2026, 12, 1, 6, 0, tzinfo=UTC)


def test_the_end_of_a_day_is_the_next_midnight_in_beirut() -> None:
    assert end_of_day(date(2026, 12, 1)) == datetime(2026, 12, 1, 22, 0, tzinfo=UTC)
    assert beirut_date(end_of_day(date(2026, 12, 1)) - timedelta(seconds=1)) == date(2026, 12, 1)


class TestDaylightSaving:
    """FR-21: in 2026 Beirut moves its clocks on 29 March and on 25 October."""

    spring = date(2026, 3, 29)
    autumn = date(2026, 10, 25)

    def test_the_offset_changes_on_the_two_dates(self) -> None:
        noon = time(12, 0)
        day = timedelta(days=1)

        assert at_beirut(self.spring - day, noon).hour == 10  # UTC+2
        assert at_beirut(self.spring, noon).hour == 9  # UTC+3
        assert at_beirut(self.autumn - day, noon).hour == 9
        assert at_beirut(self.autumn, noon).hour == 10

    @pytest.mark.parametrize("change", [spring, autumn])
    def test_request_hours_follow_the_wall_clock_around_a_change(self, change: date) -> None:
        for offset in (-1, 0, 1):
            day = change + timedelta(days=offset)
            assert in_request_hours(at_beirut(day, time(8, 0)))
            assert not in_request_hours(at_beirut(day, time(7, 59)))
            assert not in_request_hours(at_beirut(day, time(20, 0)))

    def test_a_search_window_is_six_real_hours_across_a_change(self) -> None:
        # Saturday 24 October, 19:30 summer time. Clocks go back one hour at midnight.
        started = at_beirut(self.autumn - timedelta(days=1), time(19, 30))

        ends = search_window_end(started)

        assert ends - started == timedelta(hours=6)
        assert (beirut(ends).date(), beirut(ends).time()) == (self.autumn, time(0, 30))

    def test_a_pickup_deadline_is_the_closing_time_on_the_wall_clock(self) -> None:
        hours = WeeklyHours.of({weekday: [("08:00", "21:00")] for weekday in range(7)})
        far_expiry = date(2027, 6, 30)

        before = pickup_deadline(hours, self.autumn - timedelta(days=1), far_expiry)
        after = pickup_deadline(hours, self.autumn, far_expiry)

        assert (before.hour, after.hour) == (18, 19)  # 21:00 in Beirut, in UTC
        assert beirut(before).time() == beirut(after).time() == time(21, 0)

    def test_the_days_of_a_change_are_23_and_25_hours_long(self) -> None:
        def length(day: date) -> timedelta:
            return end_of_day(day) - at_beirut(day, time.min)

        assert length(self.spring) == timedelta(hours=23)
        assert length(self.autumn - timedelta(days=1)) == timedelta(hours=25)
        assert length(date(2026, 7, 1)) == timedelta(hours=24)
