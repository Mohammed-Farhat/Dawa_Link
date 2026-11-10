"""Pickup days and deadlines (docs/04 R-T4, R-F3, R-F6, N-6, N-42, N-49).

There is one set of pickup days, and every part of the app uses it: the search page, the
reserve screen and the agent's tools (decision log BLD-D1).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from dawalink.domain.clock import beirut_date, end_of_day
from dawalink.domain.expiry import fits
from dawalink.domain.numbers import (
    PICKUP_TIME_MAX_DAYS,
    PICKUP_TIME_MIN_DAYS,
    SAME_DAY_PICKUP_MIN_OPEN,
    UPCOMING_DAYS_NAMED,
)
from dawalink.domain.opening_hours import WeeklyHours, last_closing, open_time_left


@dataclass(frozen=True)
class PickupChoice:
    """The days a client may collect one box, for their days of use (R-F3, R-F6)."""

    days: tuple[date, ...]
    """The days the client may choose, earliest first. Empty when the box never lasts."""

    expiry_limits_pickup: bool
    """The pharmacy accepts a later day, but the box wouldn't last from it."""


def pharmacy_pickup_days(hours: WeeklyHours, pickup_time_days: int, now: datetime) -> list[date]:
    """The days this pharmacy accepts a pickup for a reservation made now, earliest first.

    Today counts only if the pharmacy stays open long enough (N-42). After today come the
    pharmacy's next open days, as many as its pickup time setting: 3 at most (N-6).
    """
    if not PICKUP_TIME_MIN_DAYS <= pickup_time_days <= PICKUP_TIME_MAX_DAYS:
        raise ValueError("The pickup time setting is 1 to 3 days.")
    today = beirut_date(now)
    next_open_days: list[date] = []
    # A weekly schedule with any open day has one within the next 7 days.
    for ahead in range(1, 7 * pickup_time_days + 1):
        if len(next_open_days) == pickup_time_days:
            break
        day = today + timedelta(days=ahead)
        if hours.is_open_day(day):
            next_open_days.append(day)
    open_long_enough_today = open_time_left(hours, now) >= SAME_DAY_PICKUP_MIN_OPEN
    return ([today] if open_long_enough_today else []) + next_open_days


def pickup_choice(
    hours: WeeklyHours,
    pickup_time_days: int,
    now: datetime,
    *,
    expiry_date: date,
    days_of_use: int,
) -> PickupChoice:
    """The pharmacy's pickup days on which the box still lasts the client's days of use.

    A later pickup leaves fewer days before the box expires, so the days that fit are
    always the earliest ones (R-F6).
    """
    pharmacy_days = pharmacy_pickup_days(hours, pickup_time_days, now)
    days = tuple(day for day in pharmacy_days if fits(expiry_date, day, days_of_use))
    return PickupChoice(days, expiry_limits_pickup=len(days) < len(pharmacy_days))


def pickup_days_allowed(
    hours: WeeklyHours,
    pickup_time_days: int,
    now: datetime,
    *,
    expiry_date: date,
    days_of_use: int,
) -> list[date]:
    """The days a client may choose to collect this box, earliest first (R-F3)."""
    choice = pickup_choice(
        hours, pickup_time_days, now, expiry_date=expiry_date, days_of_use=days_of_use
    )
    return list(choice.days)


def upcoming_days(now: datetime) -> list[date]:
    """Today and the next days in Beirut, one of each weekday (N-49).

    The agent is given this list with dates and weekday names, so that it never works out
    a date itself.
    """
    today = beirut_date(now)
    return [today + timedelta(days=ahead) for ahead in range(UPCOMING_DAYS_NAMED)]


def pickup_deadline(hours: WeeklyHours, pickup_day: date, expiry_date: date) -> datetime:
    """Closing time on the pickup day, and never after the box's expiry date (R-T4)."""
    closing = last_closing(hours, pickup_day)
    if closing is None:
        raise ValueError("The pharmacy is closed on that day.")
    return min(closing, end_of_day(expiry_date))
