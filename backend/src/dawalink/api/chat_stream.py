"""A chat message's answer, as a short stream of events (docs/06 §6.6.1).

The agent's turn runs **on its own thread, not inside the response**. If the client's
connection drops, the turn carries on, its reply is saved, and the next poll returns it.
The stream only reports what that thread does: progress lines, then the complete reply
once it has passed every check. Nothing is sent word by word (API-D6).

**An open stream holds no thread while it waits** (A#6). The stream is read on the event
loop, and the turn's thread wakes it when it has something to say. A stream that held a
thread would take one of the threads every other endpoint shares: about 40 chats at once
would leave none for the load balancer's health check, and the API task would be replaced.
"""

import asyncio
import contextlib
import json
import threading
import uuid
from collections.abc import AsyncIterator, Callable
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


class TurnPool:
    """The threads that run chat turns, and how many of them are taken.

    A turn never waits in a queue for a free thread: while its stream waited, the client
    would see nothing at all. When every thread is taken, a new message is refused as
    busy before it is stored (A#6), and the page sends it again after `BUSY_RETRY_MS`.
    """

    def __init__(self, size: int) -> None:
        self._size = size
        self._taken = 0
        self._lock = threading.Lock()
        self._threads = ThreadPoolExecutor(max_workers=size, thread_name_prefix="chat-turn")

    def try_take(self) -> bool:
        """Takes a thread for a turn about to start, or says that none is free."""
        with self._lock:
            if self._taken >= self._size:
                return False
            self._taken += 1
            return True

    def give_back(self) -> None:
        with self._lock:
            self._taken = max(0, self._taken - 1)

    def run(self, work: Callable[[], None], *, taken: bool) -> None:
        """Runs `work` on a thread. `taken` says whether `try_take` already took one;
        if not, it is counted now, even if it has to wait for a thread."""
        if not taken:
            with self._lock:
                self._taken += 1

        def then_give_back() -> None:
            try:
                work()
            finally:
                self.give_back()

        try:
            self._threads.submit(then_give_back)
        except BaseException:
            self.give_back()
            raise

    def shutdown(self, wait: bool = True) -> None:
        self._threads.shutdown(wait=wait)


class TurnSlot:
    """A thread of the pool, taken for a chat message before it is stored.

    Used as `with TurnSlot(pool) as slot, work.tx() as tx:`. If anything fails before the
    turn starts (a later refusal, the commit itself), the thread is given back: the page
    is told nothing was stored, so nothing may stay taken either.
    """

    def __init__(self, pool: TurnPool) -> None:
        self._pool = pool
        self.taken = False

    def take(self) -> bool:
        self.taken = self._pool.try_take()
        return self.taken

    def __enter__(self) -> "TurnSlot":
        return self

    def __exit__(self, kind: object, error: object, traceback: object) -> None:
        if kind is not None and self.taken:
            self._pool.give_back()
            self.taken = False


class _Mailbox:
    """What the turn's thread hands to the stream, which waits for it on the event loop.

    The thread may put before the stream has started (the turn starts first, and the
    stream may never be read at all), so what is put is kept until it is taken, and the
    loop is only known once the stream waits for the first time.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, Any]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready: asyncio.Event | None = None

    def put(self, name: str, data: Any) -> None:
        """From the turn's thread. It never raises into the turn."""
        with self._lock:
            self._items.append((name, data))
            loop, ready = self._loop, self._ready
        if loop is None or ready is None:
            return
        # A closed loop: nobody listens any more, and the turn goes on.
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(ready.set)

    async def get(self, timeout_s: float) -> tuple[str, Any] | None:
        """The next item, or None when `timeout_s` passed without one."""
        if self._ready is None:
            ready = asyncio.Event()
            with self._lock:
                self._loop = asyncio.get_running_loop()
                self._ready = ready
        ready = self._ready
        while True:
            with self._lock:
                if self._items:
                    return self._items.pop(0)
                # Cleared under the lock: a put after this point sets it again.
                ready.clear()
            try:
                await asyncio.wait_for(ready.wait(), timeout_s)
            except TimeoutError:
                return None


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


def _shown(agent: Agent, conversation_id: uuid.UUID, result: TurnResult) -> list[Any] | None:
    """The reply as the page shows it. Read on the turn's thread, never on the event loop:
    a database call there would hold up every request of the process."""
    if result.status in REFUSALS or result.message_seq is None:
        return []
    with unit_of_work(agent.sessions, agent.clock) as tx:
        row = tx.session.execute(
            select(ChatMessage).where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.seq == result.message_seq,
            )
        ).scalar_one()
        return list(present.messages(tx, [row]))


def answer(
    pool: TurnPool,
    agent: Agent,
    conversation_id: uuid.UUID,
    *,
    client_message_seq: int,
    request_id: str,
    heartbeat_s: float = SSE_HEARTBEAT_S,
    taken: bool = False,
) -> AsyncIterator[bytes]:
    """Starts the turn now, and returns the stream that follows it.

    `taken`: the route already took a thread of `pool` for this turn (`try_take`).
    """
    mailbox = _Mailbox()

    def turn() -> None:
        try:
            result = run_turn(
                agent,
                conversation_id,
                runs_in="chat",
                on_progress=lambda label: mailbox.put("progress", {"label": label}),
            )
        except Exception:
            log.exception("chat_turn_failed", conversation_id=str(conversation_id))
            result = TurnResult(Status.UNAVAILABLE)
        try:
            shown = _shown(agent, conversation_id, result)
        except Exception:
            # The reply is saved: the stream ends without its last event, and the page
            # reads the reply by polling, as after a dropped connection.
            log.exception("chat_reply_not_read", conversation_id=str(conversation_id))
            shown = None
        mailbox.put("result", (result, shown))

    # Started here, before anything is read from the stream: the turn doesn't depend on
    # anyone listening.
    pool.run(turn, taken=taken)

    async def stream() -> AsyncIterator[bytes]:
        yield event("turn_started", {"client_message_seq": client_message_seq})
        while True:
            got = await mailbox.get(heartbeat_s)
            if got is None:
                yield b": heartbeat\n\n"
                continue
            name, data = got
            if name != "result":
                yield event(name, data)
                continue
            result, shown = data
            if result.status in REFUSALS:
                yield event("error", refusal(result, request_id))
                return
            if shown is None:
                return
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
