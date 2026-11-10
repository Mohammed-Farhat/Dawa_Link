"""A pharmacy's weekly opening hours (docs/04 R-T2).

Up to two ranges per day, each `[opens, closes)` in minutes after midnight, Beirut time.
`closes` may be 24:00. A pharmacy open past midnight enters the rest on the next day.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import pairwise

from dawalink.domain.clock import at_beirut, beirut

MINUTES_PER_DAY = 24 * 60
MAX_RANGES_PER_DAY = 2


def _minutes(text: str) -> int:
    """ "08:30" -> 510. "24:00" is allowed as a closing time."""
    hours, _, minutes = text.partition(":")
    value = int(hours) * 60 + int(minutes)
    if not (0 <= int(minutes) < 60 and 0 <= value <= MINUTES_PER_DAY):
        raise ValueError(f"Not a time of day: {text!r}")
    return value


@dataclass(frozen=True, order=True)
class OpenRange:
    opens: int
    closes: int

    def __post_init__(self) -> None:
        if not 0 <= self.opens < self.closes <= MINUTES_PER_DAY:
            raise ValueError("A range must open before it closes, within one day.")

    @classmethod
    def parse(cls, opens: str, closes: str) -> "OpenRange":
        return cls(_minutes(opens), _minutes(closes))


@dataclass(frozen=True)
class WeeklyHours:
    """Seven days, Monday first. A day with no range is a closed day."""

    by_weekday: tuple[tuple[OpenRange, ...], ...]

    def __post_init__(self) -> None:
        if len(self.by_weekday) != 7:
            raise ValueError("Opening hours cover exactly seven days.")
        for ranges in self.by_weekday:
            if len(ranges) > MAX_RANGES_PER_DAY:
                raise ValueError("A day has at most two opening ranges.")
            if any(later.opens < earlier.closes for earlier, later in pairwise(ranges)):
                raise ValueError("Opening ranges must be in order and not overlap.")

    @classmethod
    def of(cls, ranges: Mapping[int, Sequence[tuple[str, str]]]) -> "WeeklyHours":
        """From `{weekday: [("08:00", "13:00"), ("16:00", "21:00")]}`, Monday = 0."""
        if any(not 0 <= weekday <= 6 for weekday in ranges):
            raise ValueError("Weekdays run from 0 (Monday) to 6 (Sunday).")
        return cls(
            tuple(
                tuple(sorted(OpenRange.parse(*pair) for pair in ranges.get(weekday, ())))
                for weekday in range(7)
            )
        )

    def on(self, day: date) -> tuple[OpenRange, ...]:
        return self.by_weekday[day.weekday()]

    def is_open_day(self, day: date) -> bool:
        return bool(self.on(day))


def _at_minute(day: date, minute: int) -> datetime:
    if minute == MINUTES_PER_DAY:
        return at_beirut(day + timedelta(days=1), time.min)
    return at_beirut(day, time(minute // 60, minute % 60))


def _second_of_day(local: datetime) -> int:
    return local.hour * 3600 + local.minute * 60 + local.second


def is_open(hours: WeeklyHours, moment: datetime) -> bool:
    local = beirut(moment)
    second = _second_of_day(local)
    return any(r.opens * 60 <= second < r.closes * 60 for r in hours.on(local.date()))


def closes_at(hours: WeeklyHours, moment: datetime) -> datetime | None:
    """When the range that is open right now ends, or None if the pharmacy is closed."""
    local = beirut(moment)
    second = _second_of_day(local)
    for open_range in hours.on(local.date()):
        if open_range.opens * 60 <= second < open_range.closes * 60:
            return _at_minute(local.date(), open_range.closes)
    return None


def last_closing(hours: WeeklyHours, day: date) -> datetime | None:
    """The closing time at the end of this day, or None on a closed day."""
    ranges = hours.on(day)
    return _at_minute(day, ranges[-1].closes) if ranges else None


def open_time_left(hours: WeeklyHours, moment: datetime) -> timedelta:
    """How much opening time is left today, counting a range that starts later today."""
    local = beirut(moment)
    second = _second_of_day(local)
    seconds = sum(max(0, r.closes * 60 - max(r.opens * 60, second)) for r in hours.on(local.date()))
    return timedelta(seconds=seconds)
