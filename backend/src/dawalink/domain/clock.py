"""The app clock, and Beirut time (docs/04 R-T1, R-T11).

Every rule receives `now` or `today` from a Clock, never from the system directly, so tests,
the simulation and the demo clock control time. Moments are always timezone-aware.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

BEIRUT = ZoneInfo("Asia/Beirut")


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    """A clock that only moves when told to: for tests and the simulation."""

    def __init__(self, start: datetime) -> None:
        self._now = _aware(start)

    def now(self) -> datetime:
        return self._now

    def set(self, moment: datetime) -> None:
        self._now = _aware(moment)

    def advance(self, by: timedelta) -> None:
        if by < timedelta(0):
            raise ValueError("A clock can't be advanced backwards.")
        self._now += by


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("A moment needs a time zone.")
    return moment


def beirut(moment: datetime) -> datetime:
    """The same moment on a Beirut wall clock."""
    return _aware(moment).astimezone(BEIRUT)


def beirut_date(moment: datetime) -> date:
    """`today` for every business rule."""
    return beirut(moment).date()


def at_beirut(day: date, time_of_day: time) -> datetime:
    """The moment a Beirut wall clock shows this day and time, in UTC."""
    return datetime.combine(day, time_of_day, tzinfo=BEIRUT).astimezone(UTC)


def end_of_day(day: date) -> datetime:
    """Midnight at the end of this Beirut day."""
    return at_beirut(day + timedelta(days=1), time.min)
