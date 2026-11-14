"""Conversations: their messages and the turn lease (ADR-001; docs/04 R-AG1, R-AG2).

Our tables are the only memory a conversation has. One agent turn runs at a time per
conversation: whoever holds the **lease** on the conversation row runs the turn. No
database connection is held while the model thinks, so the lease is a deadline on the
row, not a lock: a turn that crashes simply lets it run out.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, or_, select, update

from dawalink.db.models import ChatMessage, Conversation
from dawalink.domain.numbers import AGENT_HISTORY_MESSAGES, TURN_LEASE
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError


def locked(tx: Tx, conversation_id: uuid.UUID) -> Conversation:
    """The conversation row, locked. It is the last lock in the global order (docs/05 §6)."""
    found = tx.session.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    if found is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown conversation.")
    return found


def own(tx: Tx, client_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
    """The client's own conversation; someone else's doesn't exist for them."""
    found = tx.session.get(Conversation, conversation_id)
    if found is None or found.client_id != client_id:
        raise ServiceError(Code.NOT_FOUND, "Unknown conversation.")
    return found


def active_chat(tx: Tx, client_id: uuid.UUID) -> Conversation:
    """The client's one active chat, created when they open the assistant (D9)."""
    found = tx.session.execute(
        select(Conversation).where(
            Conversation.client_id == client_id,
            Conversation.kind == "chat",
            Conversation.status == "ACTIVE",
        )
    ).scalar()
    if found is None:
        found = Conversation(
            id=uuid.uuid4(), client_id=client_id, kind="chat", last_activity_at=tx.now
        )
        tx.session.add(found)
        tx.session.flush()
    return found


def last_seq(tx: Tx, conversation_id: uuid.UUID) -> int:
    return tx.session.execute(
        select(func.coalesce(func.max(ChatMessage.seq), 0)).where(
            ChatMessage.conversation_id == conversation_id
        )
    ).scalar_one()


def append(
    tx: Tx,
    conversation: Conversation,
    *,
    author: str,
    kind: str,
    text: str | None,
    cards: list[Any] | None = None,
    quick_replies: list[str] | None = None,
    agent_run_id: uuid.UUID | None = None,
    client_message_id: uuid.UUID | None = None,
) -> ChatMessage:
    """Adds a message. The caller holds the conversation's lock: it makes the number safe.

    `text` is already free of personal details (INV-10): the callers redact first.
    """
    message = ChatMessage(
        conversation_id=conversation.id,
        seq=last_seq(tx, conversation.id) + 1,
        author=author,
        kind=kind,
        text_redacted=text,
        cards=cards,
        quick_replies=quick_replies,
        agent_run_id=agent_run_id,
        client_message_id=client_message_id,
    )
    tx.session.add(message)
    conversation.last_activity_at = tx.now
    tx.session.flush()
    return message


def sent_before(
    tx: Tx, conversation_id: uuid.UUID, client_message_id: uuid.UUID
) -> ChatMessage | None:
    """The message with this website-chosen ID, if it was already stored (docs/06 §6.6)."""
    return tx.session.execute(
        select(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.client_message_id == client_message_id,
        )
    ).scalar()


def history(
    tx: Tx, conversation_id: uuid.UUID, *, limit: int = AGENT_HISTORY_MESSAGES
) -> Sequence[ChatMessage]:
    """The last messages, oldest first: what a turn reads (N-32)."""
    newest_first = (
        tx.session.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.seq.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return list(reversed(newest_first))


# --- The turn lease -------------------------------------------------------------------


def take_lease(tx: Tx, conversation_id: uuid.UUID, owner: str) -> bool:
    """Takes the lease if nobody holds it. One statement, so two takers can't both win."""
    taken = tx.session.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            or_(Conversation.turn_lease_until.is_(None), Conversation.turn_lease_until <= tx.now),
        )
        .values(turn_lease_until=tx.now + TURN_LEASE, turn_owner=owner)
        .returning(Conversation.id)
    ).scalar()
    return taken is not None


def renew_lease(tx: Tx, conversation_id: uuid.UUID, owner: str) -> bool:
    """Pushes the lease's end forward during a long turn. False: the lease was lost."""
    kept = tx.session.execute(
        update(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.turn_owner == owner,
            Conversation.turn_lease_until > tx.now,
        )
        .values(turn_lease_until=tx.now + TURN_LEASE)
        .returning(Conversation.id)
    ).scalar()
    return kept is not None


def holds_lease(tx: Tx, conversation: Conversation, owner: str) -> bool:
    return (
        conversation.turn_owner == owner
        and conversation.turn_lease_until is not None
        and conversation.turn_lease_until > tx.now
    )


def release_lease(conversation: Conversation, owner: str) -> None:
    """Gives the lease back, if it is still this owner's."""
    if conversation.turn_owner == owner:
        conversation.turn_lease_until = None
        conversation.turn_owner = None


def is_busy(tx: Tx, conversation: Conversation) -> bool:
    """An agent turn is running: the website shows "one moment" (docs/06 `MessagesPage.busy`)."""
    return conversation.turn_lease_until is not None and conversation.turn_lease_until > tx.now
