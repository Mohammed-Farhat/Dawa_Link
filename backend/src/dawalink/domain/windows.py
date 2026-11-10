"""Request hours, search windows and offer times (docs/04 R-T3, R-T6, R-T8)."""

from datetime import datetime, timedelta

from dawalink.domain.clock import at_beirut, beirut
from dawalink.domain.numbers import (
    EARLY_RELEASE_ANSWER_TIME,
    OFFER_VALIDITY,
    REQUEST_HOURS_END,
    REQUEST_HOURS_START,
    SEARCH_WINDOW,
    WINDOW_CHECK_BEFORE_END,
)


def in_request_hours(now: datetime) -> bool:
    """Requests and watches can only be started during request hours (R-T3, INV-22)."""
    return REQUEST_HOURS_START <= beirut(now).time() < REQUEST_HOURS_END


def request_hours_open_at(now: datetime) -> datetime:
    """When request hours next open: later today, or tomorrow."""
    local = beirut(now)
    day = local.date() if local.time() < REQUEST_HOURS_START else local.date() + timedelta(days=1)
    return at_beirut(day, REQUEST_HOURS_START)


def search_window_end(created_at: datetime) -> datetime:
    return created_at + SEARCH_WINDOW


def window_check_at(ends_at: datetime) -> datetime:
    """When the agent gets its last chance to re-plan before the window ends (N-24)."""
    return ends_at - WINDOW_CHECK_BEFORE_END


def offer_expires_at(now: datetime) -> datetime:
    return now + OFFER_VALIDITY


def early_release_respond_by(now: datetime) -> datetime:
    return now + EARLY_RELEASE_ANSWER_TIME
