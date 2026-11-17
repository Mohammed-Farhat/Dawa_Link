"""Handing a client's case to a person (docs/04 SM-9).

An escalation gives nobody any power over who gets stock: a person can reply and help,
and that is all (R-PRI4). A client has one open escalation at a time; a second one is
added to it.

The admin's side is here too: take it, reply, resolve. **A reply is a message in the
client's conversation**, signed "DawaLink team", stored as the admin typed it. It never
starts an agent turn: the agent reads it, cleaned of personal details, as part of the
conversation the next time the client writes.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, func, select

from dawalink.db.models import ChatMessage, Conversation, Escalation, SourcingRequest
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import (
    EscalationReason,
    EscalationState,
    MessageAuthor,
    MessageKind,
)
from dawalink.services import audit, conversations, notify
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

MAX_SUMMARY = 300
MAX_REPLY = 500  # SM-9
MAX_NOTE = 500
# How much of the conversation an admin reads with an escalation (A-D4: redacted).
THREAD_MESSAGES = 60
# A note of another kind than "said later": where a reply went (see `reply`).
ANSWERED_IN = "answered_in"


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
    said += [(str(note.get("reason")), str(note.get("summary"))) for note in said_later(current)]
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


# --- The admin's side (docs/03 AS-6) ------------------------------------------------------


def listed(
    tx: Tx, *, state: EscalationState | None = None, offset: int = 0, limit: int = 50
) -> Sequence[Escalation]:
    """Escalations to work on: emergency claims first, then the one that waits longest.
    Without `state`, the ones that are not resolved."""
    statement = select(Escalation)
    if state is None:
        statement = statement.where(Escalation.state != EscalationState.RESOLVED.value)
    else:
        statement = statement.where(Escalation.state == state.value)
    emergency_first = case(
        (Escalation.reason == EscalationReason.EMERGENCY_CLAIM.value, 0), else_=1
    )
    return (
        tx.session.execute(
            statement.order_by(emergency_first, Escalation.created_at, Escalation.id)
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )


def open_counts(tx: Tx) -> tuple[int, int]:
    """How many escalations are not resolved, and how many of them are emergency claims."""
    row = tx.session.execute(
        select(
            func.count(),
            func.count().filter(Escalation.reason == EscalationReason.EMERGENCY_CLAIM.value),
        ).where(Escalation.state != EscalationState.RESOLVED.value)
    ).one()
    return int(row[0]), int(row[1])


def one(tx: Tx, escalation_id: uuid.UUID) -> Escalation:
    found = tx.session.get(Escalation, escalation_id)
    if found is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown escalation.")
    return found


def request_ref(tx: Tx, escalation: Escalation) -> str | None:
    if escalation.request_id is None:
        return None
    return tx.session.execute(
        select(SourcingRequest.ref).where(SourcingRequest.id == escalation.request_id)
    ).scalar()


def _answered_in(escalation: Escalation) -> dict[uuid.UUID, int]:
    """Other conversations a reply of this escalation went to, with the reply's number:
    the client had left the chat the escalation came from (`reply`)."""
    found: dict[uuid.UUID, int] = {}
    for note in escalation.notes:
        if isinstance(note, dict) and note.get("kind") == ANSWERED_IN:
            found.setdefault(uuid.UUID(str(note["conversation_id"])), int(note["from_seq"]))
    return found


def said_later(escalation: Escalation) -> list[dict[str, Any]]:
    """The later escalations of the same client that joined this one (SM-9)."""
    return [
        note
        for note in escalation.notes
        if isinstance(note, dict) and note.get("kind") != ANSWERED_IN
    ]


def thread(tx: Tx, escalation: Escalation) -> Sequence[ChatMessage]:
    """The conversation the escalation came from, as it is stored: the client's and the
    agent's messages without personal details (INV-10), the team's own replies as they
    were typed. Internal events are left out. If a
    reply went to the chat the client opened afterwards, that chat follows from the
    reply on, so the admin sees what they wrote and what the client answered.

    **This is the only way an admin reads a chat** (A-D4), with the report of an answer:
    there is no list of conversations for admins.
    """

    def messages(conversation_id: uuid.UUID, from_seq: int) -> list[ChatMessage]:
        newest_first = (
            tx.session.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == conversation_id,
                    ChatMessage.seq >= from_seq,
                    ChatMessage.kind != MessageKind.EVENT.value,
                )
                .order_by(ChatMessage.seq.desc())
                .limit(THREAD_MESSAGES)
            )
            .scalars()
            .all()
        )
        return list(reversed(newest_first))

    shown: list[ChatMessage] = []
    if escalation.conversation_id is not None:  # None: purged after 30 days
        shown += messages(escalation.conversation_id, 0)
    for conversation_id, from_seq in _answered_in(escalation).items():
        shown += messages(conversation_id, from_seq)
    return shown


def _locked(tx: Tx, escalation_id: uuid.UUID) -> Escalation:
    found = tx.session.execute(
        select(Escalation)
        .where(Escalation.id == escalation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    if found is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown escalation.")
    return found


def _still_open(escalation: Escalation) -> None:
    if escalation.state == EscalationState.RESOLVED.value:
        raise ServiceError(Code.CHANGED_SINCE, "This escalation is already resolved.")


def take(tx: Tx, admin_id: uuid.UUID, escalation_id: uuid.UUID) -> Escalation:
    """OPEN → IN_PROGRESS: an admin is on it. Taking it twice changes nothing."""
    escalation = _locked(tx, escalation_id)
    _still_open(escalation)
    if escalation.state == EscalationState.OPEN.value:
        escalation.state = EscalationState.IN_PROGRESS.value
        audit.record(
            tx,
            Actor.ADMIN,
            "escalation.take",
            "escalation",
            escalation.id,
            actor_id=admin_id,
            before={"state": EscalationState.OPEN.value},
            after={"state": escalation.state},
        )
    return escalation


def _where_to_answer(tx: Tx, escalation: Escalation) -> Conversation:
    """The conversation the client will read the reply in, locked.

    A request's thread stays on the request's page after the request closes. A chat the
    client has left for a new one is no longer on their screen: the reply then goes to
    the chat they have now.
    """
    if escalation.conversation_id is not None:
        came_from = tx.session.get(Conversation, escalation.conversation_id)
        if came_from is not None and (came_from.kind == "request" or came_from.status == "ACTIVE"):
            return conversations.locked(tx, came_from.id)
    return conversations.locked(tx, conversations.active_chat(tx, escalation.client_id).id)


def reply(tx: Tx, admin_id: uuid.UUID, escalation_id: uuid.UUID, *, text: str) -> ChatMessage:
    """An admin answers the client: a "DawaLink team" message, and CN-14 (SM-9).

    **The text is stored as the admin typed it** (the owner, 2026-11-16, Q46: a person may
    have to give a phone number). It is the one message kind stored that way: whatever
    reads it for the model, a trace or an export cleans it first. The reply changes
    nothing else: **no order, no offer, no priority** (R-PRI4), and no agent turn.
    """
    text = text.strip()
    if not text or len(text) > MAX_REPLY:
        raise ServiceError(Code.VALIDATION_ERROR, "A reply has 1 to 500 characters.", field="text")
    # The escalation first, the conversation last: the global lock order (docs/05 §6).
    escalation = _locked(tx, escalation_id)
    _still_open(escalation)
    conversation = _where_to_answer(tx, escalation)
    message = conversations.append(
        tx,
        conversation,
        author=MessageAuthor.ADMIN.value,
        kind=MessageKind.TEXT.value,
        text=text,
    )
    if conversation.id != escalation.conversation_id and conversation.id not in _answered_in(
        escalation
    ):
        # Remembered, so that the admin's page shows the reply and what follows it.
        escalation.notes = [
            *escalation.notes,
            {
                "kind": ANSWERED_IN,
                "conversation_id": str(conversation.id),
                "from_seq": message.seq,
            },
        ]
    before = escalation.state
    escalation.state = EscalationState.IN_PROGRESS.value
    audit.record(
        tx,
        Actor.ADMIN,
        "escalation.reply",
        "escalation",
        escalation.id,
        actor_id=admin_id,
        before={"state": before},
        after={"state": escalation.state, "message_seq": message.seq},
    )
    notify.notify(
        tx,
        escalation.client_id,
        notify.Template.TEAM_REPLIED,
        {
            "conversation_id": str(conversation.id),
            "request_id": str(conversation.request_id) if conversation.request_id else None,
        },
        event=f"escalation:{escalation.id}:reply:{message.seq}",
    )
    return message


def resolve(tx: Tx, admin_id: uuid.UUID, escalation_id: uuid.UUID, *, note: str) -> Escalation:
    """→ RESOLVED, with the admin's note of what was done. The client may be escalated
    again afterwards: that opens a new one."""
    note = note.strip()
    if not note:
        raise ServiceError(Code.REASON_REQUIRED, "Say what was done, in a few words.")
    if len(note) > MAX_NOTE:
        raise ServiceError(
            Code.VALIDATION_ERROR, "A note has 500 characters at most.", field="note"
        )
    escalation = _locked(tx, escalation_id)
    _still_open(escalation)
    before = escalation.state
    escalation.state = EscalationState.RESOLVED.value
    escalation.resolution_note = note
    escalation.resolved_by, escalation.resolved_at = admin_id, tx.now
    audit.record(
        tx,
        Actor.ADMIN,
        "escalation.resolve",
        "escalation",
        escalation.id,
        actor_id=admin_id,
        before={"state": before},
        after={"state": escalation.state},
    )
    return escalation
