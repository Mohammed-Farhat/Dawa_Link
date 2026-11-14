"""A client's message, on its way into a conversation (docs/06 §6.6, docs/07 §7.1).

The message is stored **after** its personal details are removed, and only then can a
turn read it: nothing unredacted ever sits in the conversation or reaches the model
(INV-10). In a chat the caller then runs the turn at once; in a request's thread the
worker runs it.
"""

import uuid
from dataclasses import dataclass

from dawalink.agent.context import identity_of
from dawalink.agent.guards.redact import redact
from dawalink.db.models import SourcingRequest
from dawalink.domain.numbers import MAX_MESSAGE_CHARS
from dawalink.services import clients, conversations
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError


@dataclass(frozen=True)
class Posted:
    seq: int
    # The same message sent twice by the website: it was stored the first time.
    seen_before: bool
    # A request's thread: the worker will run the turn. A chat: the caller runs it now.
    worker_runs_the_turn: bool


def post_client_message(
    tx: Tx,
    *,
    client_id: uuid.UUID,
    conversation_id: uuid.UUID,
    text: str,
    client_message_id: uuid.UUID,
) -> Posted:
    """Stores a client's message, redacted. The same `client_message_id` is stored once."""
    clients.require_search(clients.profile(tx, client_id))
    text = text.strip()
    if not text:
        raise ServiceError(Code.VALIDATION_ERROR, "A message can't be empty.")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ServiceError(
            Code.MESSAGE_TOO_LONG, "A message has 1,000 characters at most.", max=MAX_MESSAGE_CHARS
        )
    conversations.own(tx, client_id, conversation_id)
    conversation = conversations.locked(tx, conversation_id)
    in_thread = conversation.kind == "request"
    if conversation.status != "ACTIVE":
        raise ServiceError(Code.NOT_FOUND, "This conversation is closed.")
    if in_thread:
        request = tx.session.get_one(SourcingRequest, conversation.request_id)
        if request.state != "OPEN":
            raise ServiceError(Code.REQUEST_CLOSED, "This request is closed.")
    before = conversations.sent_before(tx, conversation_id, client_message_id)
    if before is not None:
        return Posted(before.seq, seen_before=True, worker_runs_the_turn=in_thread)
    message = conversations.append(
        tx,
        conversation,
        author="client",
        kind="text",
        text=redact(text, identity_of(tx, client_id)).text,
        client_message_id=client_message_id,
    )
    if in_thread and conversation.pending_turn_at is None:
        conversation.pending_turn_at = tx.now
        conversation.turn_attempts = 0
    return Posted(message.seq, seen_before=False, worker_runs_the_turn=in_thread)
