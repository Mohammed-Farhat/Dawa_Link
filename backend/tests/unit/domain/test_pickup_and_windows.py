"""Pickup days and deadlines, request hours and windows (docs/04 R-T3, R-T4, R-T8, R-F3)."""

from datetime import date, timedelta

import pytest

from dawalink.domain.opening_hours import WeeklyHours
from dawalink.domain.pickup import pickup_days_allowed, pickup_deadline
from dawalink.domain.windows import (
    early_release_respond_by,
    in_request_hours,
    offer_expires_at,
    request_hours_open_at,
    search_window_end,
    window_check_at,
)
from tests.unit.domain.helpers import TODAY, beirut_at, every_day

MONDAY = date(2026, 10, 19)
TUESDAY = date(2026, 10, 20)
WEDNESDAY = date(2026, 10, 21)
THURSDAY = date(2026, 10, 22)
FRIDAY = date(2026, 10, 23)
SATURDAY = date(2026, 10, 24)
SUNDAY = date(2026, 10, 25)
NEXT_MONDAY = date(2026, 10, 26)
FAR_EXPIRY = date(2027, 3, 31)

DAILY = every_day("08:00", "21:00")
CLOSED_ON_SUNDAY = WeeklyHours.of({weekday: [("08:00", "21:00")] for weekday in range(6)})


class TestPickupDays:
    def test_the_example_of_r_t4(self) -> None:
        """Reserved Monday 10:00, the client chooses tomorrow, open Tuesday 08:00-21:00."""
        days = pickup_days_allowed(
            DAILY, 1, beirut_at(MONDAY, "10:00"), expiry_date=FAR_EXPIRY, days_of_use=1
        )

        assert days == [MONDAY, TUESDAY]
        assert pickup_deadline(DAILY, TUESDAY, FAR_EXPIRY) == beirut_at(TUESDAY, "21:00")

    @pytest.mark.parametrize(("clock_time", "today_offered"), [("20:00", True), ("20:01", False)])
    def test_today_needs_an_hour_of_opening_time_left(
        self, clock_time: str, today_offered: bool
    ) -> None:
        days = pickup_days_allowed(
            DAILY, 1, beirut_at(TODAY, clock_time), expiry_date=FAR_EXPIRY, days_of_use=1
        )

        assert (TODAY in days) is today_offered
        assert TODAY + timedelta(days=1) in days

    def test_today_counts_before_opening_time(self) -> None:
        days = pickup_days_allowed(
            DAILY, 1, beirut_at(TODAY, "06:00"), expiry_date=FAR_EXPIRY, days_of_use=1
        )

        assert days[0] == TODAY

    def test_the_pickup_time_setting_counts_open_days_and_skips_closed_ones(self) -> None:
        now = beirut_at(SATURDAY, "10:00")

        one = pickup_days_allowed(CLOSED_ON_SUNDAY, 1, now, expiry_date=FAR_EXPIRY, days_of_use=1)
        three = pickup_days_allowed(CLOSED_ON_SUNDAY, 3, now, expiry_date=FAR_EXPIRY, days_of_use=1)

        assert one == [SATURDAY, NEXT_MONDAY]
        assert three == [SATURDAY, NEXT_MONDAY, date(2026, 10, 27), date(2026, 10, 28)]

    def test_on_a_closed_day_only_later_days_are_offered(self) -> None:
        days = pickup_days_allowed(
            CLOSED_ON_SUNDAY, 1, beirut_at(SUNDAY, "10:00"), expiry_date=FAR_EXPIRY, days_of_use=1
        )

        assert days == [NEXT_MONDAY]

    def test_only_days_on_which_the_box_still_lasts_are_offered(self) -> None:
        # The box expires Thursday. Three days of use fit from Tuesday (used Tue-Thu) only.
        days = pickup_days_allowed(
            DAILY, 3, beirut_at(TUESDAY, "10:00"), expiry_date=THURSDAY, days_of_use=3
        )

        assert days == [TUESDAY]

    def test_no_day_is_offered_when_the_box_never_lasts(self) -> None:
        days = pickup_days_allowed(
            DAILY, 3, beirut_at(TUESDAY, "10:00"), expiry_date=WEDNESDAY, days_of_use=12
        )

        assert days == []

    def test_a_pharmacy_that_never_opens_offers_no_day(self) -> None:
        never = WeeklyHours.of({})

        assert (
            pickup_days_allowed(
                never, 3, beirut_at(TODAY, "10:00"), expiry_date=FAR_EXPIRY, days_of_use=1
            )
            == []
        )

    @pytest.mark.parametrize("setting", [0, 4])
    def test_the_setting_must_be_one_to_three_days(self, setting: int) -> None:
        with pytest.raises(ValueError, match="1 to 3"):
            pickup_days_allowed(
                DAILY, setting, beirut_at(TODAY, "10:00"), expiry_date=FAR_EXPIRY, days_of_use=1
            )


class TestPickupDeadline:
    def test_it_is_the_closing_time_on_the_pickup_day(self) -> None:
        assert pickup_deadline(CLOSED_ON_SUNDAY, FRIDAY, FAR_EXPIRY) == beirut_at(FRIDAY, "21:00")

    def test_it_is_never_after_the_expiry_date(self) -> None:
        open_until_midnight = every_day("08:00", "24:00")

        deadline = pickup_deadline(open_until_midnight, TUESDAY, TUESDAY)

        assert deadline == beirut_at(WEDNESDAY, "00:00")
        assert deadline <= beirut_at(WEDNESDAY, "00:00")

    def test_a_closed_day_is_not_a_pickup_day(self) -> None:
        with pytest.raises(ValueError, match="closed"):
            pickup_deadline(CLOSED_ON_SUNDAY, SUNDAY, FAR_EXPIRY)


class TestRequestHours:
    @pytest.mark.parametrize(
        ("clock_time", "expected"),
        [("07:59", False), ("08:00", True), ("19:59", True), ("20:00", False), ("23:30", False)],
    )
    def test_boundaries(self, clock_time: str, expected: bool) -> None:
        assert in_request_hours(beirut_at(TODAY, clock_time)) is expected

    def test_they_follow_beirut_time_in_winter_too(self) -> None:
        winter_day = date(2026, 12, 1)

        assert in_request_hours(beirut_at(winter_day, "08:00"))
        assert not in_request_hours(beirut_at(winter_day, "07:59"))

    def test_before_opening_they_open_later_today(self) -> None:
        assert request_hours_open_at(beirut_at(TODAY, "06:30")) == beirut_at(TODAY, "08:00")

    def test_at_night_they_open_tomorrow(self) -> None:
        tomorrow = TODAY + timedelta(days=1)

        assert request_hours_open_at(beirut_at(TODAY, "22:00")) == beirut_at(tomorrow, "08:00")


def test_windows_and_offer_times() -> None:
    created = beirut_at(TODAY, "10:00")

    assert search_window_end(created) == beirut_at(TODAY, "16:00")
    assert window_check_at(search_window_end(created)) == beirut_at(TODAY, "15:00")
    assert offer_expires_at(created) == beirut_at(TODAY, "12:00")
    assert early_release_respond_by(created) == beirut_at(TODAY, "12:00")
