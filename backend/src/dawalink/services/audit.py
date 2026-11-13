"""Every state change writes exactly one audit event naming its actor (docs/04 INV-13).

`before` and `after` hold states, quantities and IDs only: never a name, an email, a phone
number or a location.
"""

import uuid
from typing import Any

from dawalink.db.models import AuditEvent
from dawalink.domain.state_machine import Actor
from dawalink.services.context import Tx


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
