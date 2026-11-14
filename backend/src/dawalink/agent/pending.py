"""The turns nobody is waiting for at a screen (docs/04 SM-12, R-AG4; docs/07 §2).

A decision event, a message in a request's thread, the window check and a follow-up all
leave a mark on the conversation row: `pending_turn_at` or `followup_at`. The worker
looks for those marks and runs one turn per conversation. Many events on one
conversation are one mark, so they become one turn that reads them all (FA-20).

These turns run in their own loop, beside the clock check: a slow model must never delay
an offer's expiry or a no-show.
"""

import uuid

import structlog
from sqlalchemy import func, or_, select

from dawalink.agent.turn import Agent, Status, run_turn
from dawalink.db.models import Conversation

log = structlog.get_logger(__name__)
BATCH = 10


class PendingTurns:
    def __init__(self, agent: Agent, *, batch: int = BATCH) -> None:
        self._agent = agent
        self._batch = batch

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

    def run_pending_turns(self) -> int:
        """Runs each waiting turn. Returns how many ended with a saved reply."""
        done = 0
        for conversation_id, only_followup in self.due():
            result = run_turn(
                self._agent, conversation_id, runs_in="worker", followup=only_followup
            )
            if result.status is Status.DONE:
                done += 1
            elif result.status is Status.UNAVAILABLE and result.outcome is None:
                # Degraded mode: the rest would be refused too. Try again next pass.
                break
        if done:
            log.info("agent_turns_run", turns=done)
        return done
