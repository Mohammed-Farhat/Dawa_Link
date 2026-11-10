"""Expiry dates, zones and the expiry fit (docs/04 R-T7, R-T9, SM-3, R-F1).

Zones are never stored: they're computed from the expiry date and today, every time.
"""

import calendar
import re
from datetime import date, timedelta
from enum import StrEnum

from dawalink.domain.numbers import EARLY_RELEASE_MAX_DAYS, NEAR_EXPIRY_MAX_DAYS

_MONTH = re.compile(r"(\d{4})-(\d{2})")
_DAY = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


class Zone(StrEnum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    EXPIRED = "EXPIRED"
    NEAR_EXPIRY = "NEAR_EXPIRY"
    EARLY_RELEASE = "EARLY_RELEASE"
    PRIVATE = "PRIVATE"


def parse_expiry(text: str) -> date:
    """`YYYY-MM-DD`, or `YYYY-MM` meaning the last day of that month (R-T7)."""
    text = text.strip()
    if match := _DAY.fullmatch(text):
        return date(int(match[1]), int(match[2]), int(match[3]))
    if match := _MONTH.fullmatch(text):
        year, month = int(match[1]), int(match[2])
        if not 1 <= month <= 12:
            raise ValueError(f"Not a month: {text!r}")
        return date(year, month, calendar.monthrange(year, month)[1])
    raise ValueError(f"Expected YYYY-MM or YYYY-MM-DD, got {text!r}")


def days_left(expiry_date: date, today: date) -> int:
    """Whole days until expiry: 0 on the expiry day itself, negative after it."""
    return (expiry_date - today).days


def zone_of(days: int, *, eligible: bool = True) -> Zone:
    """The zone for this many days left.

    `eligible` is false for controlled products and for stock that matches no product.
    """
    if not eligible:
        return Zone.NOT_ELIGIBLE
    if days < 0:
        return Zone.EXPIRED
    if days <= NEAR_EXPIRY_MAX_DAYS:
        return Zone.NEAR_EXPIRY
    if days <= EARLY_RELEASE_MAX_DAYS:
        return Zone.EARLY_RELEASE
    return Zone.PRIVATE


def last_day_of_use(pickup_day: date, days_of_use: int) -> date:
    if days_of_use < 1:
        raise ValueError("Days of use start at 1.")
    return pickup_day + timedelta(days=days_of_use - 1)


def fits(expiry_date: date, pickup_day: date, days_of_use: int) -> bool:
    """The box is still valid on the client's last day of use (R-F1)."""
    return expiry_date >= last_day_of_use(pickup_day, days_of_use)
