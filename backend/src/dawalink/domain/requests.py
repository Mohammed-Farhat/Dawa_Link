"""Sourcing requests and their items (docs/04 SM-8).

The agent works a request, but only a client's tap creates or cancels one (INV-11).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from dawalink.domain.state_machine import Actor, StateMachine, by


class RequestState(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RequestOutcome(StrEnum):
    FULFILLED = "FULFILLED"
    PARTIAL = "PARTIAL"
    UNFULFILLED = "UNFULFILLED"
    CANCELLED = "CANCELLED"


class ItemState(StrEnum):
    SEARCHING = "SEARCHING"
    PROPOSED = "PROPOSED"
    WAITING = "WAITING"
    SECURED = "SECURED"
    UNAVAILABLE = "UNAVAILABLE"
    CANCELLED = "CANCELLED"


FINAL_ITEM_STATES = frozenset({ItemState.SECURED, ItemState.UNAVAILABLE, ItemState.CANCELLED})

REQUEST_MACHINE = StateMachine(
    "sourcing request (SM-8)",
    {
        # The window ended or every item is final (system), or the client cancelled.
        (RequestState.OPEN, RequestState.CLOSED): by(Actor.SYSTEM, Actor.CLIENT),
    },
)

_NOT_FINAL = (ItemState.SEARCHING, ItemState.PROPOSED, ItemState.WAITING)

ITEM_MACHINE = StateMachine(
    "request item (SM-8)",
    {
        # The agent proposes a plan card, or opens a claim to wait for stock.
        (ItemState.SEARCHING, ItemState.PROPOSED): by(Actor.AGENT),
        (ItemState.SEARCHING, ItemState.WAITING): by(Actor.AGENT),
        (ItemState.WAITING, ItemState.PROPOSED): by(Actor.AGENT),
        (ItemState.WAITING, ItemState.SEARCHING): by(Actor.AGENT, Actor.SYSTEM),
        # Only the client's tap secures an item: a plan card, or an accepted offer.
        (ItemState.PROPOSED, ItemState.SECURED): by(Actor.CLIENT),
        (ItemState.WAITING, ItemState.SECURED): by(Actor.CLIENT),
        # Unticked on the card, reserved only in part, or the card failed or expired (R-RQ6).
        (ItemState.PROPOSED, ItemState.SEARCHING): by(Actor.CLIENT, Actor.SYSTEM),
        # A reservation was marked not available, or cancelled by the system: the item waits
        # again if a claim is open for it, and is searched for again otherwise.
        (ItemState.SECURED, ItemState.WAITING): by(Actor.PHARMACY, Actor.SYSTEM),
        (ItemState.SECURED, ItemState.SEARCHING): by(Actor.PHARMACY, Actor.SYSTEM),
        # The client cancelled the item's reservation while the request is open (O5), or
        # didn't come for it (O4): DawaLink doesn't look for that medicine again.
        (ItemState.SECURED, ItemState.CANCELLED): by(Actor.CLIENT, Actor.SYSTEM),
        **{(state, ItemState.CANCELLED): by(Actor.CLIENT) for state in _NOT_FINAL},
        **{(state, ItemState.UNAVAILABLE): by(Actor.SYSTEM) for state in _NOT_FINAL},
    },
)


@dataclass(frozen=True)
class ItemProgress:
    qty: int
    qty_secured: int

    @property
    def is_secured(self) -> bool:
        """Secured if and only if its reserved or picked-up units cover its quantity (INV-18)."""
        return self.qty_secured >= self.qty


def should_close(
    item_states: Sequence[ItemState], *, now: datetime, ends_at: datetime, offers_pending: int
) -> bool:
    """Close when every item is final, or when the window ended and no offer is pending (R-RQ9).

    An offer made before the end stays valid for its 2 hours, so it keeps the request open.
    """
    if all(state in FINAL_ITEM_STATES for state in item_states):
        return True
    return now >= ends_at and offers_pending == 0


def closing_outcome(items: Sequence[ItemProgress]) -> RequestOutcome:
    """The outcome when a window ends. After closing it never changes (R-RQ9)."""
    if all(item.is_secured for item in items):
        return RequestOutcome.FULFILLED
    if any(item.qty_secured > 0 for item in items):
        return RequestOutcome.PARTIAL
    return RequestOutcome.UNFULFILLED
