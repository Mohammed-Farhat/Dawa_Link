"""Orders: one quantity from one pharmacy, from offer or reservation to its end (docs/04 SM-5).

No agent tool appears here: only client taps, pharmacy actions and system rules move an order
(INV-11).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dawalink.domain.state_machine import Actor, StateMachine, by


class OrderState(StrEnum):
    OFFERED = "OFFERED"
    RESERVED = "RESERVED"
    PICKED_UP = "PICKED_UP"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    EXPIRED_NO_SHOW = "EXPIRED_NO_SHOW"
    CANCELLED_BY_CLIENT = "CANCELLED_BY_CLIENT"
    CANCELLED_BY_SYSTEM = "CANCELLED_BY_SYSTEM"
    OFFER_DECLINED = "OFFER_DECLINED"
    OFFER_EXPIRED = "OFFER_EXPIRED"
    OFFER_WITHDRAWN = "OFFER_WITHDRAWN"


class OrderSource(StrEnum):
    SEARCH = "search"
    ASSISTANT = "assistant"
    REQUEST = "request"
    WATCH = "watch"
    EARLY_RELEASE = "early_release"


OPEN_STATES = frozenset({OrderState.OFFERED, OrderState.RESERVED})

# How an order starts: a client's tap reserves at once (O1); matching or an accepted
# early-release ask creates an offer (O7, O8).
INITIAL_STATES: dict[OrderState, frozenset[Actor]] = {
    OrderState.RESERVED: by(Actor.CLIENT),
    OrderState.OFFERED: by(Actor.SYSTEM, Actor.PHARMACY),
}

ORDER_MACHINE = StateMachine(
    "order (SM-5)",
    {
        (OrderState.OFFERED, OrderState.RESERVED): by(Actor.CLIENT),  # O9
        (OrderState.OFFERED, OrderState.OFFER_DECLINED): by(Actor.CLIENT),  # O10
        (OrderState.OFFERED, OrderState.OFFER_EXPIRED): by(Actor.SYSTEM),  # O10
        (OrderState.OFFERED, OrderState.OFFER_WITHDRAWN): by(Actor.SYSTEM),  # O11
        (OrderState.OFFERED, OrderState.CANCELLED_BY_SYSTEM): by(Actor.SYSTEM),  # O6
        (OrderState.RESERVED, OrderState.PICKED_UP): by(Actor.PHARMACY),  # O2
        (OrderState.RESERVED, OrderState.NOT_AVAILABLE): by(Actor.PHARMACY),  # O3
        (OrderState.RESERVED, OrderState.EXPIRED_NO_SHOW): by(Actor.SYSTEM),  # O4
        (OrderState.RESERVED, OrderState.CANCELLED_BY_CLIENT): by(Actor.CLIENT),  # O5
        (OrderState.RESERVED, OrderState.CANCELLED_BY_SYSTEM): by(Actor.SYSTEM),  # O6
    },
)


def is_reserved_in_time(state: OrderState, now: datetime, deadline: datetime) -> bool:
    """Reserved, and the deadline hasn't passed.

    The pharmacy may mark it picked up (there is no late pickup: O2, INV-7), and the client
    may cancel it (O5).
    """
    return state is OrderState.RESERVED and now < deadline


def is_no_show(state: OrderState, now: datetime, deadline: datetime) -> bool:
    """The deadline passed and the box wasn't collected (O4)."""
    return state is OrderState.RESERVED and now >= deadline


def is_offer_over(state: OrderState, now: datetime, offer_expires_at: datetime) -> bool:
    """The offer's 2 hours passed without an answer (O10)."""
    return state is OrderState.OFFERED and now >= offer_expires_at


@dataclass(frozen=True)
class AfterNotAvailable:
    state: OrderState
    qty_locked: int


def mark_not_available(qty_locked: int, units: int) -> AfterNotAvailable:
    """The pharmacy says `units` of a reservation aren't there (O3).

    The order stays reserved for the rest, and ends only when no unit is left.
    """
    if not 1 <= units <= qty_locked:
        raise ValueError("Units not available must be between 1 and the units held.")
    left = qty_locked - units
    return AfterNotAvailable(OrderState.RESERVED if left else OrderState.NOT_AVAILABLE, left)
