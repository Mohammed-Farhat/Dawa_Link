"""Pickup days and deadlines (docs/04 R-T4, R-F3, N-6, N-42)."""

from datetime import date, datetime, timedelta

from dawalink.domain.clock import beirut_date, end_of_day
from dawalink.domain.expiry import fits
from dawalink.domain.numbers import (
    PICKUP_TIME_MAX_DAYS,
    PICKUP_TIME_MIN_DAYS,
    SAME_DAY_PICKUP_MIN_OPEN,
)
from dawalink.domain.opening_hours import WeeklyHours, last_closing, open_time_left


def pickup_days_allowed(
    hours: WeeklyHours,
    pickup_time_days: int,
    now: datetime,
    *,
    expiry_date: date,
    days_of_use: int,
) -> list[date]:
    """The days a client may choose to collect this box, earliest first.

    Today counts only if the pharmacy stays open long enough (N-42). After today come the
    pharmacy's next open days, as many as its pickup time setting (N-6). A day is offered
    only if the box still lasts the client's days of use from that day (R-F3).
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
    days = ([today] if open_long_enough_today else []) + next_open_days
    return [day for day in days if fits(expiry_date, day, days_of_use)]


def pickup_deadline(hours: WeeklyHours, pickup_day: date, expiry_date: date) -> datetime:
    """Closing time on the pickup day, and never after the box's expiry date (R-T4)."""
    closing = last_closing(hours, pickup_day)
    if closing is None:
        raise ValueError("The pharmacy is closed on that day.")
    return min(closing, end_of_day(expiry_date))
