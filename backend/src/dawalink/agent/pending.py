"""The turns nobody is waiting for at a screen (docs/04 SM-12, R-AG4; docs/07 §2).

A decision event, a message in a request's thread, the window check and a follow-up all
leave a mark on the conversation row: `pending_turn_at` or `followup_at`. The worker
looks for those marks and runs one turn per conversation. Many events on one
conversation are one mark, so they become one turn that reads them all (FA-20).

These turns run in their own loop, beside the clock check: a slow model must never delay
an offer's expiry or a no-show.
"""

import threading
import uuid

import structlog
from sqlalchemy import func, or_, select

from dawalink.agent.turn import Agent, Status, TurnResult, run_turn
from dawalink.db.models import Conversation

log = structlog.get_logger(__name__)
BATCH = 10


class PendingTurns:
    """`at_once`: how many turns may run together. The worker runs `AGENT_TURNS_AT_ONCE`
    (A#30); everything else runs them one after another."""

    def __init__(self, agent: Agent, *, batch: int = BATCH, at_once: int = 1) -> None:
        self._agent = agent
        self._batch = batch
        self._at_once = at_once

    def due(self) -> list[tuple[uuid.UUID, bool]]:
        """Conversations waiting for a turn, oldest mark first: `(id, only a follow-up?)`."""
        now = self._agent.clock.now()
        pending = (Conversation.pending_turn_at.is_not(None)) & (
            Conversation.pending_turn_at <= now
        )
        followup = (Conversation.followup_at.is_not(None)) & (Conversation.followup_at <= now)
        with self._agent.sessions() as session:
            rows = session.execute(
                select(Conversation.id, Conversation.pending_turn_at)
                .where(
                    or_(pending, followup),
                    Conversation.status == "ACTIVE",
                    or_(
                        Conversation.turn_lease_until.is_(None),
                        Conversation.turn_lease_until <= now,
                    ),
                )
                .order_by(
                    func.least(
                        func.coalesce(Conversation.pending_turn_at, Conversation.followup_at),
                        func.coalesce(Conversation.followup_at, Conversation.pending_turn_at),
                    )
                )
                .limit(self._batch)
            ).all()
        return [(row[0], row[1] is None or row[1] > now) for row in rows]

    def run_pending_turns(self, stop: threading.Event | None = None) -> int:
        """Runs each waiting turn, up to `at_once` at a time. Returns how many ended with a
        saved reply.

        Each due conversation appears once in the list, and its lease keeps any other turn
        off it, so two turns never run on one conversation (R-AG2). A turn is handed out
        only when a slot is free, and none is handed out once `stop` is set (the worker is
        being stopped: the ones left keep their mark and run after the restart, A#21) or
        once the assistant is found unavailable (degraded mode: the rest would be refused
        too, and are tried again next pass). The turns already running finish.
        """
        handing = _Handing(self.due(), stop)

        def take_turns() -> None:
            while (next_turn := handing.next()) is not None:
                conversation_id, only_followup = next_turn
                try:
                    result = run_turn(
                        self._agent, conversation_id, runs_in="worker", followup=only_followup
                    )
                except Exception as error:
                    # `run_turn` closes its own failures; this is a last guard, so that one
                    # turn can't take the rest of the pass with it.
                    log.error("agent_turn_not_run", error=type(error).__name__)
                    continue
                handing.ended(result)

        slots = min(self._at_once, handing.waiting())
        if slots <= 1:
            # One at a time, on this thread: what the tests, the simulation and the
            # evaluation use, so that their turns run in a known order.
            take_turns()
        else:
            threads = [
                threading.Thread(target=take_turns, name=f"agent-turn-{n}", daemon=True)
                for n in range(slots)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        if handing.done:
            log.info("agent_turns_run", turns=handing.done)
        return handing.done


class _Handing:
    """The turns of one pass, handed out one by one to whichever slot is free."""

    def __init__(self, due: list[tuple[uuid.UUID, bool]], stop: threading.Event | None) -> None:
        self._waiting = list(due)
        self._stop = stop
        self._lock = threading.Lock()
        self._degraded = False
        self.done = 0

    def waiting(self) -> int:
        return len(self._waiting)

    def next(self) -> tuple[uuid.UUID, bool] | None:
        with self._lock:
            stopping = self._stop is not None and self._stop.is_set()
            if stopping or self._degraded or not self._waiting:
                return None
            return self._waiting.pop(0)

    def ended(self, result: TurnResult) -> None:
        with self._lock:
            if result.status is Status.DONE:
                self.done += 1
            elif result.status is Status.UNAVAILABLE and result.outcome is None:
                self._degraded = True
