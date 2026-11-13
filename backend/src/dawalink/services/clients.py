"""What a client may do in their current status (docs/04 SM-2)."""

import uuid

from sqlalchemy import select

from dawalink.db.models import ClientProfile
from dawalink.domain.accounts import ClientStatus, client_can_reserve, client_can_search
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError


def profile(tx: Tx, client_id: uuid.UUID, *, lock: bool = False) -> ClientProfile:
    """The client's profile. With `lock`, the row is locked until the transaction ends.

    The lock is what serializes one client's reservations, so two taps at once can't both
    pass a limit (docs/05 §6). It is always the first lock a transaction takes.
    """
    statement = select(ClientProfile).where(ClientProfile.user_id == client_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    found = tx.session.execute(statement).scalar()
    if found is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown client.")
    return found


def require_search(client: ClientProfile) -> None:
    if not client_can_search(ClientStatus(client.status)):
        raise ServiceError(Code.ACCOUNT_SUSPENDED, "This account is suspended.")


def require_reserve(tx: Tx, client: ClientProfile) -> None:
    """Reserving, accepting an offer, starting a request or a watch need an ACTIVE client."""
    status = ClientStatus(client.status)
    if client_can_reserve(status):
        return
    if status is ClientStatus.UNVERIFIED:
        raise ServiceError(Code.EMAIL_NOT_VERIFIED, "Please confirm your email first.")
    if status is ClientStatus.PAUSED:
        raise ServiceError(
            Code.CLIENT_PAUSED,
            "Reservations are paused after missed pickups.",
            paused_until=client.paused_until,
        )
    raise ServiceError(Code.ACCOUNT_SUSPENDED, "This account is suspended.")
