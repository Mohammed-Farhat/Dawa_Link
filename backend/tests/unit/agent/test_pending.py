"""The worker's turns run a few at a time (A#30; docs/07 §8, R-AG2).

The turns themselves are stubbed: what is checked here is how they are handed out.
"""

import threading
import time
import uuid
from typing import Any, cast

import pytest
from sqlalchemy.pool import QueuePool

from dawalink.agent import pending as pending_module
from dawalink.agent.pending import PendingTurns
from dawalink.agent.turn import Agent, Status, TurnResult
from dawalink.db.session import make_engine
from dawalink.domain.numbers import AGENT_TURNS_AT_ONCE
from dawalink.domain.vocabulary import RunOutcome
from tests.conftest import logged

DONE = TurnResult(Status.DONE)


class Turns:
    """A stand-in for `run_turn` that records how many ran together."""

    def __init__(
        self,
        result: TurnResult = DONE,
        seconds: float = 0.05,
        meet: threading.Barrier | None = None,
    ) -> None:
        self.result = result
        self.seconds = seconds
        # The first turns wait for each other here: they can only all arrive if they run
        # at the same time (a broken barrier fails the test, however slow the machine).
        self.meet = meet
        self.ran: list[uuid.UUID] = []
        self.threads: list[threading.Thread] = []
        self.running = 0
        self.most_at_once = 0
        self._lock = threading.Lock()

    def __call__(self, _: Any, conversation_id: uuid.UUID, **__: Any) -> TurnResult:
        with self._lock:
            self.ran.append(conversation_id)
            self.threads.append(threading.current_thread())
            self.running += 1
            self.most_at_once = max(self.most_at_once, self.running)
            first = len(self.ran) <= (self.meet.parties if self.meet else 0)
        if first and self.meet is not None:
            self.meet.wait(timeout=10)
        time.sleep(self.seconds)
        with self._lock:
            self.running -= 1
        return self.result


def worker_pass(
    monkeypatch: pytest.MonkeyPatch, turns: Any, *, due: int, at_once: int = 4
) -> tuple[PendingTurns, list[tuple[uuid.UUID, bool]]]:
    pending = PendingTurns(cast(Agent, object()), at_once=at_once)
    waiting = [(uuid.uuid4(), False) for _ in range(due)]
    monkeypatch.setattr(pending, "due", lambda: waiting)
    monkeypatch.setattr(pending_module, "run_turn", turns)
    return pending, waiting


def test_several_turns_run_at_once_never_more_than_the_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turns = Turns(meet=threading.Barrier(AGENT_TURNS_AT_ONCE))
    pending, waiting = worker_pass(monkeypatch, turns, due=10, at_once=AGENT_TURNS_AT_ONCE)

    assert pending.run_pending_turns() == 10
    assert sorted(turns.ran) == sorted(conversation for conversation, _ in waiting)
    assert turns.most_at_once == AGENT_TURNS_AT_ONCE
    # Daemon threads: a turn still running when the worker exits never keeps it alive.
    assert all(thread.daemon for thread in turns.threads)


def test_each_conversation_gets_one_turn_per_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-AG2: never two turns of one conversation (its lease guards the rest)."""
    turns = Turns()
    pending, _ = worker_pass(monkeypatch, turns, due=7)

    pending.run_pending_turns()

    assert len(turns.ran) == len(set(turns.ran)) == 7


def test_by_default_turns_run_one_after_another_on_the_callers_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The simulation, the evaluation and the tests keep their known order."""
    turns = Turns(seconds=0)
    pending = PendingTurns(cast(Agent, object()))
    waiting = [(uuid.uuid4(), False) for _ in range(3)]
    monkeypatch.setattr(pending, "due", lambda: waiting)
    monkeypatch.setattr(pending_module, "run_turn", turns)

    pending.run_pending_turns()

    assert turns.ran == [conversation for conversation, _ in waiting]
    assert set(turns.threads) == {threading.current_thread()}


def test_once_told_to_stop_no_further_turn_is_handed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A#21: the turns already running finish; the others keep their mark."""
    stop = threading.Event()

    class Stopping(Turns):
        def __call__(self, *args: Any, **kwargs: Any) -> TurnResult:
            stop.set()
            return super().__call__(*args, **kwargs)

    turns = Stopping()
    pending, _ = worker_pass(monkeypatch, turns, due=10)

    pending.run_pending_turns(stop)

    assert 1 <= len(turns.ran) <= 4


def test_once_the_assistant_is_unavailable_no_further_turn_is_handed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Degraded mode: the rest would be refused too, and are tried again next pass."""
    turns = Turns(TurnResult(Status.UNAVAILABLE))
    pending, _ = worker_pass(monkeypatch, turns, due=10)

    assert pending.run_pending_turns() == 0
    assert 1 <= len(turns.ran) <= 4


def test_a_model_failure_of_one_turn_does_not_stop_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn that fell back is that turn's business (its retry is counted on its row)."""
    turns = Turns(TurnResult(Status.UNAVAILABLE, RunOutcome.FALLBACK), seconds=0)
    pending, _ = worker_pass(monkeypatch, turns, due=6)

    pending.run_pending_turns()

    assert len(turns.ran) == 6


def test_a_turn_that_raises_does_not_take_the_others_with_it(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[uuid.UUID] = []

    def turns(_: Any, conversation_id: uuid.UUID, **__: Any) -> TurnResult:
        calls.append(conversation_id)
        if len(calls) == 1:
            raise RuntimeError("a bug outside the turn's own guard")
        return TurnResult(Status.DONE)

    pending, _ = worker_pass(monkeypatch, turns, due=5, at_once=1)

    assert pending.run_pending_turns() == 4
    assert len(calls) == 5
    assert logged(caplog, "agent_turn_not_run")[0]["error"] == "RuntimeError"


def test_the_workers_database_pool_has_room_for_its_turns() -> None:
    """Each turn holds one connection at a time; the clock check holds one more, and the
    demo clock reads one for a moment. A pool too small would fail turns after 2 s."""
    pool = make_engine("postgresql+psycopg://u@h/d").pool
    assert isinstance(pool, QueuePool)

    room = pool.size() + pool._max_overflow  # the pool has no public reader for it

    assert room >= AGENT_TURNS_AT_ONCE + 2
