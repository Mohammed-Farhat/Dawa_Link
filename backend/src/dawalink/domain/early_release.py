"""Early release: asking open pharmacies to release privately held stock (docs/04 SM-6)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from dawalink.domain.numbers import (
    AUTOMATIC_REACH_CAR_MIN,
    EARLY_RELEASE_DECLINE_MEMORY,
    EARLY_RELEASE_MAX_ASKS_PER_PHARMACY_PER_DAY,
    EARLY_RELEASE_MAX_PHARMACIES,
)
from dawalink.domain.state_machine import Actor, StateMachine, by


class EarlyReleaseState(StrEnum):
    OPEN = "OPEN"
    FULFILLED = "FULFILLED"
    UNFULFILLED = "UNFULFILLED"
    CANCELLED = "CANCELLED"


class AskState(StrEnum):
    ASKED = "ASKED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


EARLY_RELEASE_MACHINE = StateMachine(
    "early-release request (SM-6)",
    {
        (EarlyReleaseState.OPEN, EarlyReleaseState.FULFILLED): by(Actor.CLIENT),
        (EarlyReleaseState.OPEN, EarlyReleaseState.UNFULFILLED): by(Actor.SYSTEM),
        (EarlyReleaseState.OPEN, EarlyReleaseState.CANCELLED): by(Actor.CLIENT, Actor.SYSTEM),
    },
)

ASK_MACHINE = StateMachine(
    "early-release ask (SM-6)",
    {
        (AskState.ASKED, AskState.ACCEPTED): by(Actor.PHARMACY),
        (AskState.ASKED, AskState.DECLINED): by(Actor.PHARMACY),
        (AskState.ASKED, AskState.EXPIRED): by(Actor.SYSTEM),
        (AskState.ASKED, AskState.WITHDRAWN): by(Actor.SYSTEM),
    },
)


@dataclass(frozen=True)
class AskCandidate:
    """A pharmacy holding the medicine privately. The service fills this in from its tables."""

    pharmacy_id: str
    car_min: int
    expiry_date: date
    not_available_marks_30d: int
    open_now: bool
    asks_today: int
    declined_this_product_at: datetime | None = None


def pharmacies_to_ask(candidates: Sequence[AskCandidate], now: datetime) -> list[AskCandidate]:
    """Which pharmacies get the ask: at most 3, all at once (R-E2 to R-E4).

    Only pharmacies that are open now and within reach. Skipped: those that already got
    their daily share of asks, or declined this medicine recently. Then the shortest trip
    first, the soonest expiry (less waste), and the fewest [Not available] marks.
    """
    eligible = [
        candidate
        for candidate in candidates
        if candidate.open_now
        and candidate.car_min <= AUTOMATIC_REACH_CAR_MIN
        and candidate.asks_today < EARLY_RELEASE_MAX_ASKS_PER_PHARMACY_PER_DAY
        and not _declined_recently(candidate, now)
    ]
    eligible.sort(
        key=lambda c: (c.car_min, c.expiry_date, c.not_available_marks_30d, c.pharmacy_id)
    )
    chosen: list[AskCandidate] = []
    for candidate in eligible:
        # One ask per pharmacy, for its best box.
        if all(candidate.pharmacy_id != other.pharmacy_id for other in chosen):
            chosen.append(candidate)
        if len(chosen) == EARLY_RELEASE_MAX_PHARMACIES:
            break
    return chosen


def _declined_recently(candidate: AskCandidate, now: datetime) -> bool:
    declined_at = candidate.declined_this_product_at
    return declined_at is not None and now - declined_at < EARLY_RELEASE_DECLINE_MEMORY


def is_valid_acceptance(
    *, qty: int, price_lbp: int, qty_missing: int, private_available: int, public_price_lbp: int
) -> bool:
    """What a pharmacy may offer when it accepts an ask (R-E6)."""
    return 1 <= qty <= min(qty_missing, private_available) and 0 <= price_lbp <= public_price_lbp
