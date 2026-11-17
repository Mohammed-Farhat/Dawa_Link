"""Every state change writes exactly one audit event naming its actor (docs/04 INV-13).

`before` and `after` hold states, quantities and IDs only: never a name, an email, a phone
number or a location.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from dawalink.db.models import AuditEvent
from dawalink.domain.state_machine import Actor
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

MAX_REASON = 300


def required_reason(text: str | None) -> str:
    """The few words an admin gives for an action: every admin change has them (SM-1,
    SM-2). They are kept in the audit log, so they name no person."""
    reason = (text or "").strip()
    if not reason:
        raise ServiceError(Code.REASON_REQUIRED, "Say why, in a few words.")
    if len(reason) > MAX_REASON:
        raise ServiceError(
            Code.VALIDATION_ERROR, "A reason has 300 characters at most.", field="reason"
        )
    return reason


def record(
    tx: Tx,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    *,
    actor_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> None:
    tx.session.add(
        AuditEvent(
            occurred_at=tx.now,
            actor_type=actor.value,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            before=before,
            after=after,
            reason=reason,
        )
    )


def listed(
    tx: Tx,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    action: str | None = None,
    actor_type: Actor | None = None,
    before_id: int | None = None,
    limit: int = 50,
) -> Sequence[AuditEvent]:
    """The audit log, newest first (AS-11). `action` matches a whole action
    ("pharmacy.approve") or everything of one kind ("pharmacy.")."""
    statement = select(AuditEvent)
    if entity_type:
        statement = statement.where(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        statement = statement.where(AuditEvent.entity_id == entity_id)
    if action:
        statement = statement.where(
            AuditEvent.action.startswith(action, autoescape=True)
            if action.endswith(".")
            else AuditEvent.action == action
        )
    if actor_type is not None:
        statement = statement.where(AuditEvent.actor_type == actor_type.value)
    if before_id is not None:
        statement = statement.where(AuditEvent.id < before_id)
    return tx.session.execute(statement.order_by(AuditEvent.id.desc()).limit(limit)).scalars().all()
