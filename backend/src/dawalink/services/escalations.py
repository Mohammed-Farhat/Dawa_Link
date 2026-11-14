"""Handing a client's case to a person (docs/04 SM-9).

An escalation gives nobody any power over who gets stock: a person can reply and help,
and that is all (R-PRI4). A client has one open escalation at a time; a second one is
added to it.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from dawalink.db.models import Escalation
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import EscalationReason
from dawalink.services import audit
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

MAX_SUMMARY = 300


@dataclass(frozen=True)
class Escalated:
    escalation_id: uuid.UUID
    # True when the client already had an open escalation and this one joined it.
    appended: bool


def escalate(
    tx: Tx,
    *,
    client_id: uuid.UUID,
    reason: EscalationReason,
    summary: str,
    conversation_id: uuid.UUID | None = None,
    request_id: uuid.UUID | None = None,
    actor: Actor = Actor.AGENT,
) -> Escalated:
    """Opens an escalation, or adds to the client's open one.

    `summary` holds no personal details: the caller removes them first. Asking again with
    the same reason and summary changes nothing, so a turn that is retried doesn't write
    its escalation twice (R-AG6).
    """
    summary = summary.strip()
    if not summary or len(summary) > MAX_SUMMARY:
        raise ServiceError(Code.VALIDATION_ERROR, "A summary has 1 to 300 characters.")
    current = tx.session.execute(
        select(Escalation)
        .where(Escalation.client_id == client_id, Escalation.state != "RESOLVED")
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    if current is None:
        created = Escalation(
            id=uuid.uuid4(),
            client_id=client_id,
            conversation_id=conversation_id,
            request_id=request_id,
            reason=reason.value,
            summary=summary,
            created_at=tx.now,
        )
        tx.session.add(created)
        tx.session.flush()
        audit.record(
            tx,
            actor,
            "escalation.open",
            "escalation",
            created.id,
            after={"state": "OPEN", "reason": reason.value},
        )
        return Escalated(created.id, appended=False)

    said = [(current.reason, current.summary)]
    said += [(note.get("reason"), note.get("summary")) for note in current.notes]
    if (reason.value, summary) not in said:
        current.notes = [
            *current.notes,
            {
                "reason": reason.value,
                "summary": summary,
                "at": tx.now.isoformat(),
                "conversation_id": str(conversation_id) if conversation_id else None,
                "request_id": str(request_id) if request_id else None,
            },
        ]
        audit.record(
            tx,
            actor,
            "escalation.append",
            "escalation",
            current.id,
            after={"reason": reason.value, "notes": len(current.notes)},
        )
    return Escalated(current.id, appended=True)
