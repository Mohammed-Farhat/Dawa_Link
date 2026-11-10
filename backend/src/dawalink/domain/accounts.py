"""Pharmacy and client accounts: states and what each state may do (docs/04 SM-1, SM-2)."""

from enum import StrEnum

from dawalink.domain.state_machine import Actor, StateMachine, by


class PharmacyStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class ClientStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"


PHARMACY_MACHINE = StateMachine(
    "pharmacy account (SM-1)",
    {
        (PharmacyStatus.PENDING, PharmacyStatus.APPROVED): by(Actor.ADMIN),
        (PharmacyStatus.PENDING, PharmacyStatus.REJECTED): by(Actor.ADMIN),
        (PharmacyStatus.REJECTED, PharmacyStatus.PENDING): by(Actor.PHARMACY),
        (PharmacyStatus.APPROVED, PharmacyStatus.SUSPENDED): by(Actor.ADMIN),
        (PharmacyStatus.SUSPENDED, PharmacyStatus.APPROVED): by(Actor.ADMIN),
    },
)

CLIENT_MACHINE = StateMachine(
    "client account (SM-2)",
    {
        (ClientStatus.UNVERIFIED, ClientStatus.ACTIVE): by(Actor.CLIENT),
        (ClientStatus.ACTIVE, ClientStatus.PAUSED): by(Actor.SYSTEM),
        (ClientStatus.PAUSED, ClientStatus.ACTIVE): by(Actor.SYSTEM, Actor.ADMIN),
        (ClientStatus.ACTIVE, ClientStatus.SUSPENDED): by(Actor.ADMIN),
        (ClientStatus.PAUSED, ClientStatus.SUSPENDED): by(Actor.ADMIN),
        (ClientStatus.SUSPENDED, ClientStatus.ACTIVE): by(Actor.ADMIN),
    },
)


def pharmacy_can_manage_inventory(status: PharmacyStatus) -> bool:
    """Upload or edit inventory, manage listings, receive reservations and early-release asks."""
    return status is PharmacyStatus.APPROVED


def pharmacy_can_update_reservations(status: PharmacyStatus) -> bool:
    """Mark existing reservations picked up or not available: still allowed when suspended."""
    return status in (PharmacyStatus.APPROVED, PharmacyStatus.SUSPENDED)


def client_can_search(status: ClientStatus) -> bool:
    return status is not ClientStatus.SUSPENDED


def client_can_use_assistant(status: ClientStatus) -> bool:
    return status in (ClientStatus.ACTIVE, ClientStatus.PAUSED)


def client_can_reserve(status: ClientStatus) -> bool:
    """Reserve, accept offers, create requests or watches, and be included in matching."""
    return status is ClientStatus.ACTIVE


def client_can_cancel(status: ClientStatus) -> bool:
    return status in (ClientStatus.ACTIVE, ClientStatus.PAUSED)
