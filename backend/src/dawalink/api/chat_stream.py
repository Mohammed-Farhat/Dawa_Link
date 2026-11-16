"""A chat message's answer, as a short stream of events (docs/06 §6.6.1).

The agent's turn runs **on its own thread, not inside the response**. If the client's
connection drops, the turn carries on, its reply is saved, and the next poll returns it.
The stream only reports what that thread does: progress lines, then the complete reply
once it has passed every check. Nothing is sent word by word (API-D6).
"""

import json
import queue
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from dawalink.agent.turn import Agent, Status, TurnResult, run_turn
from dawalink.api import present
from dawalink.api.errors import error_body, service_status
from dawalink.db.models import ChatMessage
from dawalink.domain.numbers import SSE_HEARTBEAT_S
from dawalink.services.context import unit_of_work
from dawalink.services.errors import Code

log = structlog.get_logger(__name__)

# What a turn that didn't answer becomes for the website (docs/06 §3.2).
REFUSALS: dict[Status, tuple[Code, str]] = {
    Status.BUSY: (Code.CONVERSATION_BUSY, "One moment…"),
    Status.UNAVAILABLE: (
        Code.ASSISTANT_UNAVAILABLE,
        "The assistant isn't available right now. Search still works.",
    ),
    Status.BUDGET: (
        Code.TOKEN_BUDGET_EXCEEDED,
        "You've reached today's limit for the assistant. Search still works.",
    ),
}
BUSY_RETRY_MS = 2_000


def event(name: str, data: Any) -> bytes:
    return f"event: {name}\ndata: {json.dumps(jsonable_encoder(data))}\n\n".encode()


def refusal(result: TurnResult, request_id: str) -> dict[str, Any]:
    code, message = REFUSALS[result.status]
    details: dict[str, Any] = {}
    if result.status is Status.BUSY:
        details["retry_after_ms"] = BUSY_RETRY_MS
    if result.status is Status.UNAVAILABLE:
        details["fallback"] = "search"
    if result.status is Status.BUDGET:
        details["until"] = result.until
    return {**error_body(code.value, message, request_id, details), "status": service_status(code)}


def answer(
    pool: ThreadPoolExecutor,
    agent: Agent,
    conversation_id: uuid.UUID,
    *,
    client_message_seq: int,
    request_id: str,
    heartbeat_s: float = SSE_HEARTBEAT_S,
) -> Iterator[bytes]:
    """Starts the turn now, and returns the stream that follows it."""
    events: queue.Queue[tuple[str, Any]] = queue.Queue()

    def turn() -> None:
        try:
            result = run_turn(
                agent,
                conversation_id,
                runs_in="chat",
                on_progress=lambda label: events.put(("progress", {"label": label})),
            )
            events.put(("result", result))
        except Exception:
            log.exception("chat_turn_failed", conversation_id=str(conversation_id))
            events.put(("result", TurnResult(Status.UNAVAILABLE)))

    # Started here, before anything is read from the stream: the turn doesn't depend on
    # anyone listening.
    pool.submit(turn)

    def stream() -> Iterator[bytes]:
        yield event("turn_started", {"client_message_seq": client_message_seq})
        while True:
            try:
                name, data = events.get(timeout=heartbeat_s)
            except queue.Empty:
                yield b": heartbeat\n\n"
                continue
            if name != "result":
                yield event(name, data)
                continue
            result: TurnResult = data
            if result.status in REFUSALS:
                yield event("error", refusal(result, request_id))
                return
            if result.message_seq is not None:
                with unit_of_work(agent.sessions, agent.clock) as tx:
                    row = tx.session.execute(
                        select(ChatMessage).where(
                            ChatMessage.conversation_id == conversation_id,
                            ChatMessage.seq == result.message_seq,
                        )
                    ).scalar_one()
                    shown = present.messages(tx, [row])
                for message in shown:
                    yield event("message", message)
            yield event(
                "turn_completed",
                {
                    "agent_message_seq": result.message_seq,
                    "outcome": result.outcome.value if result.outcome else result.status.value,
                },
            )
            return

    return stream()
