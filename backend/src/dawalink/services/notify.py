"""In-app notifications and the email outbox (docs/04 R-NT; docs/03 CN- and PN- lists).

One notification per event per recipient: sending the same one twice does nothing.
The email address is never stored here; it is looked up when the email is sent.
A payload holds display values and IDs only. A pharmacy's payload never says who the
client is (INV-9).
"""

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from dawalink.db.models import EmailOutbox, Notification
from dawalink.services.context import Tx


class Template(StrEnum):
    # To clients
    RESERVED = "CN-3"
    NOT_AVAILABLE = "CN-5"
    PICKUP_REMINDER = "CN-6"
    EXPIRED_NO_SHOW = "CN-7"
    PAUSED = "CN-8"
    EARLY_RELEASE_OFFER = "CN-9"
    MATCHING_OFFER = "CN-10"
    WATCH_ENDED = "CN-11"
    CANCELLED_BY_SYSTEM = "CN-12"
    PLAN_READY = "CN-15"
    WINDOW_ENDING = "CN-16"
    REQUEST_CLOSED = "CN-17"
    # To pharmacies
    NEW_RESERVATION = "PN-4"
    EARLY_RELEASE_ASK = "PN-7"
    CLIENT_CANCELLED = "PN-8"
    STALE_INVENTORY = "PN-10"


def notify(
    tx: Tx,
    user_id: uuid.UUID,
    template: Template,
    payload: dict[str, Any],
    *,
    event: str,
    email: bool = True,
) -> bool:
    """Tell one user about one event, in the app and by email. True if it was new.

    `event` identifies the event for this recipient ("order:<id>", or
    "order:<id>:not-available:2" for something that can happen more than once).
    """
    key = f"{template.value}:{user_id}:{event}"
    added = tx.session.execute(
        insert(Notification)
        .values(user_id=user_id, type=template.value, payload=payload, dedupe_key=key)
        .on_conflict_do_nothing(index_elements=[Notification.dedupe_key])
        .returning(Notification.id)
    ).scalar()
    if added is None:
        return False
    if email:
        tx.session.execute(
            insert(EmailOutbox)
            .values(
                user_id=user_id,
                template=template.value,
                params=payload,
                dedupe_key=key,
                next_attempt_at=tx.now,
            )
            .on_conflict_do_nothing(index_elements=[EmailOutbox.dedupe_key])
        )
    return True
