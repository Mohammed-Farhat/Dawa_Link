"""The chat and a request's thread: reading, writing, and tapping a card (docs/06 §6.6, §6.7)."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select

from dawalink.agent import limits as agent_limits
from dawalink.agent.chat import post_client_message
from dawalink.agent.context import identity_of
from dawalink.agent.guards.redact import redact
from dawalink.agent.turn import Agent
from dawalink.api import chat_stream, present
from dawalink.api.deps import AsClient, DoWork, IdempotencyKey, get_agent
from dawalink.api.errors import ApiError, ErrorCode, request_id_of
from dawalink.api.limits import Limiter
from dawalink.api.schemas.admin import AnswerReported, ReportAnswer
from dawalink.api.schemas.chat import (
    ConversationRef,
    ExecuteProposal,
    ExecuteResult,
    MessageAccepted,
    MessagesPage,
    SendMessage,
)
from dawalink.api.schemas.common import MAX_SEQ, LocationIn
from dawalink.db.models import ChatMessage, Conversation
from dawalink.domain.accounts import ClientStatus, client_can_use_assistant
from dawalink.domain.clock import BEIRUT
from dawalink.domain.numbers import CHAT_MESSAGES_PER_DAY, MAX_PAGE_SIZE
from dawalink.domain.vocabulary import ReportReason
from dawalink.services import answer_reports, clients, conversations, proposals, travel
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

router = APIRouter(tags=["conversations"])


def _may_use_the_assistant(tx: Tx, client_id: uuid.UUID) -> None:
    """The assistant needs a confirmed email (R-AU5). A paused client may still chat."""
    status = ClientStatus(clients.profile(tx, client_id).status)
    if client_can_use_assistant(status):
        return
    if status is ClientStatus.UNVERIFIED:
        raise ServiceError(Code.EMAIL_NOT_VERIFIED, "Please confirm your email first.")
    raise ServiceError(Code.ACCOUNT_SUSPENDED, "This account is suspended.")


@router.get("/conversations/active-chat")
def active_chat(caller: AsClient, work: DoWork) -> ConversationRef:
    """The client's one chat, created the first time they open the assistant (D9)."""
    with work.tx() as tx:
        _may_use_the_assistant(tx, caller.user_id)
        chat = conversations.active_chat(tx, caller.user_id)
        return ConversationRef(conversation_id=chat.id, kind="chat")


@router.post("/conversations/new-chat")
def new_chat(caller: AsClient, work: DoWork) -> ConversationRef:
    """Starts a fresh chat. The old one is archived, and kept 30 days (R-RET)."""
    with work.tx() as tx:
        _may_use_the_assistant(tx, caller.user_id)
        conversations.archive_chats(tx, caller.user_id)
        chat = conversations.active_chat(tx, caller.user_id)
        return ConversationRef(conversation_id=chat.id, kind="chat")


@router.put("/conversations/{conversation_id}/location", status_code=204)
def set_location(
    conversation_id: uuid.UUID, body: LocationIn, caller: AsClient, work: DoWork, request: Request
) -> Response:
    """Where the agent's tools count travel times from in this chat. The point is rounded
    before it is stored, and it is never part of what the AI reads (INV-24)."""
    with work.tx() as tx:
        conversations.own(tx, caller.user_id, conversation_id)
        if body.lat is not None and body.lon is not None:
            location = travel.shared_location(body.lat, body.lon)
            # A shared point can start a paid routing call; a district can't (N-47).
            wait_s = cast(Limiter, request.app.state.locations_per_client).wait_s(caller.user_id)
            if wait_s:
                raise ApiError(ErrorCode.RATE_LIMITED, details={"retry_after_s": wait_s})
        elif body.district_id is not None:
            location = travel.district_location(tx, body.district_id)
        else:
            raise ServiceError(Code.VALIDATION_ERROR, "Send a point (lat and lon) or a district.")
        chat = conversations.locked(tx, conversation_id)
        if chat.kind != "chat":
            # A request's location is fixed when it starts (R-RQ4).
            raise ServiceError(Code.VALIDATION_ERROR, "A request's location can't be changed.")
        conversations.set_location(tx, chat, location)
    return Response(status_code=204)


@router.get("/conversations/{conversation_id}/messages")
def read_messages(
    conversation_id: uuid.UUID,
    caller: AsClient,
    work: DoWork,
    after_seq: Annotated[int, Query(ge=0, le=MAX_SEQ)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = MAX_PAGE_SIZE,
) -> MessagesPage:
    """The messages after `after_seq`, oldest first. With `after_seq=0`, the newest ones.

    This is what an open chat or request page asks for every few seconds (API-D7).
    """
    with work.tx() as tx:
        conversation = conversations.own(tx, caller.user_id, conversation_id)
        statement = select(ChatMessage).where(
            ChatMessage.conversation_id == conversation_id, ChatMessage.kind != "event"
        )
        if after_seq:
            rows = (
                tx.session.execute(
                    statement.where(ChatMessage.seq > after_seq)
                    .order_by(ChatMessage.seq)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
        else:
            newest_first = (
                tx.session.execute(statement.order_by(ChatMessage.seq.desc()).limit(limit))
                .scalars()
                .all()
            )
            rows = list(reversed(newest_first))
        return MessagesPage(
            conversation_id=conversation.id,
            kind=conversation.kind,
            request_id=conversation.request_id,
            messages=present.messages(tx, rows),
            last_seq=conversations.last_seq(tx, conversation_id),
            busy=conversations.is_busy(tx, conversation),
            location=present.location_summary(tx, conversation),
            server_now=tx.now,
        )


@router.post("/conversations/{conversation_id}/messages/{seq}/report", status_code=201)
def report_answer(
    conversation_id: uuid.UUID,
    seq: Annotated[int, Path(ge=1)],
    body: ReportAnswer,
    caller: AsClient,
    work: DoWork,
) -> AnswerReported:
    """The thumbs-down under a reply of the assistant, once per reply (SM-10). A copy of
    the reply and of the messages before it is kept for DawaLink's team; the client's
    comment is stored without personal details, like a message."""
    with work.tx() as tx:
        identity = identity_of(tx, caller.user_id)

        def clean(text: str) -> str:
            return redact(text, identity).text

        created = answer_reports.report(
            tx,
            caller.user_id,
            conversation_id,
            seq,
            reason=ReportReason(body.reason),
            clean=clean,
            comment=clean(body.comment) if body.comment else None,
        )
        return AnswerReported(id=created.id)


def _sent_today(tx: Tx, client_id: uuid.UUID) -> int:
    """How many messages this client wrote since midnight in Beirut (R-AS)."""
    midnight = datetime.combine(tx.real_now.astimezone(BEIRUT).date(), time.min, BEIRUT)
    return tx.session.execute(
        select(func.count())
        .select_from(ChatMessage)
        .join(Conversation, Conversation.id == ChatMessage.conversation_id)
        .where(
            Conversation.client_id == client_id,
            ChatMessage.author == "client",
            ChatMessage.created_at >= midnight,
        )
    ).scalar_one()


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=MessageAccepted,
    status_code=202,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "In a chat: the answer, as a stream of events.",
        }
    },
)
def send_message(
    conversation_id: uuid.UUID,
    body: SendMessage,
    caller: AsClient,
    work: DoWork,
    request: Request,
    agent: Annotated[Agent | None, Depends(get_agent)],
) -> Response:
    """A client's message.

    - **In the chat** the answer comes back at once as a stream of events (`200`,
      `text/event-stream`): progress lines, then the complete, checked reply.
    - **In a request's thread** the answer is `202`: the worker runs the agent's turn,
      and the page sees the reply by polling.
    """
    wait_s = cast(Limiter, request.app.state.chat_per_client).wait_s(caller.user_id)
    if wait_s:
        raise ApiError(ErrorCode.RATE_LIMITED, details={"retry_after_s": wait_s})
    with work.tx() as tx:
        _may_use_the_assistant(tx, caller.user_id)
        conversation = conversations.own(tx, caller.user_id, conversation_id)
        in_chat = conversation.kind == "chat"
        if in_chat:
            if (
                agent is None
                or agent_limits.breaker_open(tx)
                or agent_limits.spend_cap_reached(tx, agent.monthly_budget_usd)
            ):
                raise ServiceError(
                    Code.ASSISTANT_UNAVAILABLE,
                    "The assistant isn't available right now. Search still works.",
                    fallback="search",
                )
            if agent_limits.over_daily_budget(tx, caller.user_id):
                raise ServiceError(
                    Code.TOKEN_BUDGET_EXCEEDED,
                    "You've reached today's limit for the assistant. Search still works.",
                    until=agent_limits.midnight(tx),
                )
            if conversations.is_busy(tx, conversation):
                raise ServiceError(
                    Code.CONVERSATION_BUSY,
                    "One moment…",
                    retry_after_ms=chat_stream.BUSY_RETRY_MS,
                )
        if _sent_today(tx, caller.user_id) >= CHAT_MESSAGES_PER_DAY:
            raise ApiError(
                ErrorCode.RATE_LIMITED,
                "You've reached today's number of messages. Search still works.",
                details={"retry_after_s": 3600},
            )
        posted = post_client_message(
            tx,
            client_id=caller.user_id,
            conversation_id=conversation_id,
            text=body.text,
            client_message_id=body.client_message_id,
        )
    if posted.worker_runs_the_turn:
        return JSONResponse({"message_seq": posted.seq}, status_code=202)
    assert agent is not None
    stream = chat_stream.answer(
        cast(ThreadPoolExecutor, request.app.state.turn_pool),
        agent,
        conversation_id,
        client_message_seq=posted.seq,
        request_id=request_id_of(request),
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        # Told to every proxy on the way: pass each event on as it comes.
        headers={"X-Accel-Buffering": "no"},
    )


@router.post("/proposals/{proposal_id}/execute")
def execute_proposal(
    proposal_id: uuid.UUID,
    body: ExecuteProposal,
    caller: AsClient,
    work: DoWork,
    _key: IdempotencyKey,
) -> ExecuteResult:
    """The client tapped an agent card. Everything is checked again as if it were new
    (R-AG7): the card holds no authority, only what to try.

    A card works once, so a second tap of the same card answers `PROPOSAL_USED`.
    """
    try:
        with work.tx() as tx:
            done = proposals.execute(
                tx,
                client_id=caller.user_id,
                proposal_id=proposal_id,
                selected_item_keys=body.selected_item_keys,
            )
            made = present.reservations(tx, done.orders)
            request_made = done.request
            if done.orders:
                refs = ", ".join(order.ref for order in done.orders)
                message = f"Reserved: {refs}. Show this number at the counter."
            elif request_made is not None:
                message = f"Request {request_made.ref}: DawaLink is on it."
            else:
                message = "Done."
            if done.kind.value == "cancel":
                message = "Cancelled. Nothing is owed."
            return ExecuteResult(
                proposal_id=proposal_id,
                kind=done.kind.value,
                reservations=made,
                request_id=request_made.id if request_made else None,
                request_ref=request_made.ref if request_made else None,
                message=message,
            )
    except ServiceError as refused:
        # Nothing was reserved. When it was a plan's card, the agent is told, so that it
        # says which medicine failed and offers the rest (R-RQ6).
        with work.tx() as tx:
            proposals.report_failed_group(
                tx, client_id=caller.user_id, proposal_id=proposal_id, error=refused
            )
        raise
