"""Expiry dates, zones and the expiry fit (docs/04 R-T7, R-T9, SM-3, R-F1, R-F6).

Zones are never stored: they're computed from the expiry date and today, every time.
"""

import calendar
import re
from collections.abc import Iterable
from datetime import date, timedelta
from enum import StrEnum

from dawalink.domain.numbers import EARLY_RELEASE_MAX_DAYS, NEAR_EXPIRY_MAX_DAYS

_MONTH = re.compile(r"(\d{4})-(\d{2})")
_DAY = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# What a spreadsheet makes of a month typed in a cell: "03/2027", "Mar-27", "Mar 2027".
_MONTH_FIRST = re.compile(r"(\d{1,2})[/.-](\d{4})")
_MONTH_NAME = re.compile(r"([A-Za-z]{3,9})[ ./-](\d{2}|\d{4})")
_YEAR_FIRST = re.compile(r"(\d{4})[/.](\d{1,2})(?:[/.](\d{1,2}))?")
_DAY_AND_MONTH = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2}|\d{4})")
_MONTH_NAMES = {
    name[:3].lower(): number for number, name in enumerate(calendar.month_name) if number
}


class AmbiguousDate(ValueError):
    """ "03/04/2027": 3 April in Beirut, 4 March on a computer set to US dates."""


class DayMonthOrder(StrEnum):
    """Which of two numbers is the day, when a date is written with numbers only."""

    DAY_FIRST = "DAY_FIRST"
    MONTH_FIRST = "MONTH_FIRST"


def day_month_order(cells: Iterable[str]) -> DayMonthOrder | None:
    """How one file writes its dates, **if the file itself shows it**.

    "31/03/2027" can only be day first; "3/31/2027" only month first. One such date
    settles it for the whole file: a spreadsheet writes every date of a sheet the same
    way. A file with no such date, or with both kinds, shows nothing: None, and its
    two-number dates stay refused. Nothing is ever guessed from where we are.
    """
    day_first = month_first = False
    for cell in cells:
        if match := _DAY_AND_MONTH.fullmatch(cell.strip()):
            first, second = int(match[1]), int(match[2])
            day_first = day_first or (first > 12 and second <= 12)
            month_first = month_first or (second > 12 and first <= 12)
    if day_first == month_first:
        return None
    return DayMonthOrder.DAY_FIRST if day_first else DayMonthOrder.MONTH_FIRST


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


def parse_expiry_cell(text: str, order: DayMonthOrder | None = None) -> date:
    """An expiry as it arrives in a stock file, after a spreadsheet had its way with it.

    Besides the two forms of `parse_expiry`, it reads the ones that can mean only one
    thing: `2027/03/31`, `03/2027`, `Mar-27`, `Mar 2027`. **A day and a month written as
    two numbers are read only with the `order` the file showed** (`day_month_order`);
    without it they are refused (`AmbiguousDate`): reading them the wrong way round would
    show a box as valid for months longer than it is.
    """
    text = text.strip()
    try:
        return parse_expiry(text)
    except ValueError:
        pass
    if match := _YEAR_FIRST.fullmatch(text):
        day = f"-{int(match[3]):02d}" if match[3] else ""
        return parse_expiry(f"{match[1]}-{int(match[2]):02d}{day}")
    if match := _MONTH_FIRST.fullmatch(text):
        return parse_expiry(f"{match[2]}-{int(match[1]):02d}")
    if match := _MONTH_NAME.fullmatch(text):
        month = _MONTH_NAMES.get(match[1][:3].lower())
        if month is None:
            raise ValueError(f"Not a month: {text!r}")
        year = int(match[2]) if len(match[2]) == 4 else 2000 + int(match[2])
        return parse_expiry(f"{year}-{month:02d}")
    if match := _DAY_AND_MONTH.fullmatch(text):
        if order is None:
            raise AmbiguousDate(text)
        first, second = int(match[1]), int(match[2])
        of_month, month = (first, second) if order is DayMonthOrder.DAY_FIRST else (second, first)
        year = int(match[3]) if len(match[3]) == 4 else 2000 + int(match[3])
        return date(year, month, of_month)  # ValueError for a 31 June or a month 13
    raise ValueError(f"Not an expiry date: {text!r}")


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


def last_pickup_day_that_fits(expiry_date: date, days_of_use: int) -> date:
    """The latest pickup day from which the box still lasts the days of use (R-F6).

    A later pickup leaves fewer days before the box expires: a box that fits today may
    not fit on the last day the pharmacy allows.
    """
    if days_of_use < 1:
        raise ValueError("Days of use start at 1.")
    return expiry_date - timedelta(days=days_of_use - 1)
