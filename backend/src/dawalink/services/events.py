"""What appears in a conversation without the client typing (docs/04 R-AG3 to R-AG5, ADR-001).

- An **informational event** posts a template card: no LLM call.
- A **decision event** writes a system message and asks for an agent turn. The clock
  check runs the turn later; nothing here calls the agent.

Routing (R-AG5): orders from the search page never reach a conversation, so the search
baseline stays agent-free. Assistant orders and watches go to the client's active chat,
and everything that belongs to a request goes to the request's own thread.
"""

import json
import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import func, select

from dawalink.db.models import ChatMessage, Conversation, RequestItem
from dawalink.services.context import Tx


class Decision(StrEnum):
    """The decision events of docs/06 §8."""

    REQUEST_SUBMITTED = "request_submitted"
    NOT_AVAILABLE = "not_available"
    SYSTEM_CANCELLED = "system_cancelled"
    EARLY_RELEASE_UNFULFILLED = "early_release_unfulfilled"
    WINDOW_CHECK = "window_check"
    GROUP_ITEM_FAILED = "group_item_failed"
    ITEMS_UNTICKED = "items_unticked"


def chat_of(tx: Tx, client_id: uuid.UUID) -> uuid.UUID | None:
    """The client's active chat, if they have one."""
    return tx.session.execute(
        select(Conversation.id).where(
            Conversation.client_id == client_id,
            Conversation.kind == "chat",
            Conversation.status == "ACTIVE",
        )
    ).scalar()


def thread_of_request(tx: Tx, request_id: uuid.UUID) -> uuid.UUID | None:
    return tx.session.execute(
        select(Conversation.id).where(Conversation.request_id == request_id)
    ).scalar()


def conversation_for(
    tx: Tx, *, source: str, client_id: uuid.UUID, request_item_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Where an order's or a claim's events go, or None for "notifications only" (R-AG5)."""
    if request_item_id is not None:
        request_id = tx.session.execute(
            select(RequestItem.request_id).where(RequestItem.id == request_item_id)
        ).scalar_one()
        return thread_of_request(tx, request_id)
    if source == "search":
        return None
    return chat_of(tx, client_id)


def _append(
    tx: Tx, conversation_id: uuid.UUID, *, kind: str, text: str | None, cards: list[Any] | None
) -> Conversation:
    # The conversation row is locked last in the global lock order (docs/05 §6), and its
    # lock is what makes the next message number safe.
    conversation = tx.session.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    last = tx.session.execute(
        select(func.coalesce(func.max(ChatMessage.seq), 0)).where(
            ChatMessage.conversation_id == conversation_id
        )
    ).scalar_one()
    tx.session.add(
        ChatMessage(
            conversation_id=conversation_id,
            seq=last + 1,
            author="system",
            kind=kind,
            text_redacted=text,
            cards=cards,
        )
    )
    conversation.last_activity_at = tx.now
    tx.session.flush()
    return conversation


def post_card(tx: Tx, conversation_id: uuid.UUID | None, template: str, **data: Any) -> None:
    """An informational card, rendered by the website from `template` and `data`."""
    if conversation_id is not None:
        _append(tx, conversation_id, kind="card", text=None, cards=[{"template": template, **data}])


def post_decision(
    tx: Tx, conversation_id: uuid.UUID | None, decision: Decision, **ids: Any
) -> None:
    """Something the agent must react to: a system message, and a turn asked for."""
    if conversation_id is None:
        return
    body = json.dumps({"type": decision.value, **ids}, default=str, sort_keys=True)
    conversation = _append(tx, conversation_id, kind="event", text=body, cards=None)
    if conversation.pending_turn_at is None:
        conversation.pending_turn_at = tx.now
        conversation.turn_attempts = 0
