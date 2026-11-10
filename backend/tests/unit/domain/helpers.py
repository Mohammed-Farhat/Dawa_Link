"""Small builders shared by the domain tests."""

from datetime import date, datetime, time

from dawalink.domain.clock import at_beirut
from dawalink.domain.opening_hours import WeeklyHours

# The date the examples in docs/04 use: a Tuesday.
TODAY = date(2026, 10, 20)


def beirut_at(day: date, clock_time: str) -> datetime:
    """The moment a Beirut wall clock shows `clock_time` ("21:00") on `day`."""
    hours, minutes = clock_time.split(":")
    return at_beirut(day, time(int(hours), int(minutes)))


def every_day(opens: str, closes: str) -> WeeklyHours:
    return WeeklyHours.of({weekday: [(opens, closes)] for weekday in range(7)})
