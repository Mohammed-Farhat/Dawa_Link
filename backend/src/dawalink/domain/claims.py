"""Claims: one need for one medicine, waiting for stock (docs/04 SM-7).

A claim is a client's watch or a waiting request item. Matching and early release both work
for it; the first offer the client accepts wins (R-W3).
"""

from enum import StrEnum

from dawalink.domain.state_machine import Actor, StateMachine, by


class ClaimState(StrEnum):
    ACTIVE = "ACTIVE"
    OFFER_PENDING = "OFFER_PENDING"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ClaimPath(StrEnum):
    """The two ways stock reaches a claim. Each holds at most one offer at a time (INV-20)."""

    MATCHING = "matching"
    EARLY_RELEASE = "early_release"


LIVE_STATES = frozenset({ClaimState.ACTIVE, ClaimState.OFFER_PENDING})

CLAIM_MACHINE = StateMachine(
    "claim (SM-7)",
    {
        # An offer is made: by matching, or by a pharmacy accepting an early-release ask.
        (ClaimState.ACTIVE, ClaimState.OFFER_PENDING): by(Actor.SYSTEM, Actor.PHARMACY),
        # The offer ended, or covered only part of the need.
        (ClaimState.OFFER_PENDING, ClaimState.ACTIVE): by(Actor.SYSTEM, Actor.CLIENT),
        # The client reserved the last missing unit: an offer, or a card for listed stock.
        (ClaimState.OFFER_PENDING, ClaimState.FULFILLED): by(Actor.CLIENT),
        (ClaimState.ACTIVE, ClaimState.FULFILLED): by(Actor.CLIENT),
        # A reservation for it was marked not available, or cancelled by the system.
        (ClaimState.FULFILLED, ClaimState.ACTIVE): by(Actor.PHARMACY, Actor.SYSTEM),
        (ClaimState.ACTIVE, ClaimState.EXPIRED): by(Actor.SYSTEM),
        (ClaimState.OFFER_PENDING, ClaimState.EXPIRED): by(Actor.SYSTEM),
        (ClaimState.ACTIVE, ClaimState.CANCELLED): by(Actor.CLIENT),
        (ClaimState.OFFER_PENDING, ClaimState.CANCELLED): by(Actor.CLIENT),
    },
)


def missing_after_reserving(qty_missing: int, units_reserved: int) -> int:
    """Units still missing after a reservation; 0 means the need is covered (R-W4)."""
    if not 1 <= units_reserved <= qty_missing:
        raise ValueError("A reservation covers between 1 unit and the missing units.")
    return qty_missing - units_reserved


def missing_after_losing(qty: int, qty_missing: int, units_lost: int) -> int:
    """Units missing again after reserved units were marked not available (O3)."""
    if not 1 <= units_lost <= qty - qty_missing:
        raise ValueError("Only reserved units can be lost.")
    return qty_missing + units_lost
