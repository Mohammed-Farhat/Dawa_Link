"""The clock check loop and its heartbeat (docs/04 R-T10; FX-13)."""

import threading
import time
import uuid
from pathlib import Path
from typing import Any, cast

import pytest

from dawalink.agent import pending as pending_module
from dawalink.agent.pending import PendingTurns
from dawalink.agent.turn import Agent, Status, TurnResult
from dawalink.domain.numbers import (
    CLOCK_CHECK_LATE_AFTER_S,
    TURN_TIME_LIMIT_WORKER_S,
    WORKER_STOP_WAIT_S,
)
from dawalink.worker import alive
from dawalink.worker.__main__ import run_until_stopped
from dawalink.worker.heartbeat import beat, is_alive
from dawalink.worker.loop import ClockCheck
from tests.conftest import logged


def test_the_stop_wait_outlasts_a_worker_turn_and_fits_in_two_minutes() -> None:
    """docs/12 §6: a turn that started may finish; ECS gives at most 120 s."""
    assert TURN_TIME_LIMIT_WORKER_S < WORKER_STOP_WAIT_S < 120


def test_a_fresh_heartbeat_means_alive(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat"

    beat(heartbeat)

    assert is_alive(heartbeat)


def test_no_heartbeat_means_not_alive(tmp_path: Path) -> None:
    assert not is_alive(tmp_path / "never-written")


def test_a_stale_heartbeat_means_not_alive(tmp_path: Path) -> None:
    heartbeat = tmp_path / "heartbeat"
    beat(heartbeat)
    written_at = heartbeat.stat().st_mtime

    assert is_alive(heartbeat, now=written_at + CLOCK_CHECK_LATE_AFTER_S)
    assert not is_alive(heartbeat, now=written_at + CLOCK_CHECK_LATE_AFTER_S + 1)


def test_a_pass_runs_every_task_in_order_then_beats(tmp_path: Path) -> None:
    calls: list[str] = []
    heartbeat = tmp_path / "heartbeat"
    check = ClockCheck([lambda: calls.append("first"), lambda: calls.append("second")], heartbeat)

    check.run_pass()

    assert calls == ["first", "second"]
    assert is_alive(heartbeat)


def test_a_failing_task_does_not_stop_the_others(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[str] = []
    heartbeat = tmp_path / "heartbeat"

    def expire_offers() -> None:
        raise RuntimeError("database went away")

    check = ClockCheck([expire_offers, lambda: calls.append("still ran")], heartbeat)

    check.run_pass()

    assert calls == ["still ran"]
    assert is_alive(heartbeat)
    assert [entry["task"] for entry in logged(caplog, "clock_task_failed")] == ["expire_offers"]


def test_the_loop_stops_when_asked_and_finishes_its_pass(tmp_path: Path) -> None:
    stop = threading.Event()
    passes: list[float] = []

    def count_then_stop() -> None:
        passes.append(time.monotonic())
        if len(passes) == 3:
            stop.set()

    ClockCheck([count_then_stop], tmp_path / "heartbeat", interval_s=0.01).run_until(stop)

    assert len(passes) == 3
    assert is_alive(tmp_path / "heartbeat")


def test_once_told_to_stop_no_further_task_starts(tmp_path: Path) -> None:
    """A#21: SIGTERM stops the worker taking new work at once; the pass doesn't finish."""
    stop = threading.Event()
    calls: list[str] = []

    def first() -> None:
        calls.append("first")
        stop.set()  # the signal arrives during the first task

    check = ClockCheck([first, lambda: calls.append("second")], tmp_path / "b")

    check.run_pass(stop)

    assert calls == ["first"]
    assert is_alive(tmp_path / "b")


class TestStoppingTheWorker:
    """A#21: on SIGTERM the worker waits a bounded time for what runs, then exits."""

    def test_work_that_finishes_in_time_is_waited_for(self, tmp_path: Path) -> None:
        stop = threading.Event()
        finished: list[str] = []

        def a_turn() -> None:
            stop.set()  # the signal arrives while a turn runs
            time.sleep(0.2)
            finished.append("turn")

        loops = {"agent-turns": ClockCheck([a_turn], tmp_path / "b", interval_s=0.01)}

        assert run_until_stopped(loops, stop, wait_s=5, look_every_s=0.01) is True
        assert finished == ["turn"]

    def test_work_that_runs_too_long_is_left_and_the_worker_exits(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        stop = threading.Event()
        release = threading.Event()

        def a_stuck_turn() -> None:
            stop.set()
            release.wait(30)

        loops = {"agent-turns": ClockCheck([a_stuck_turn], tmp_path / "b", interval_s=0.01)}
        started = time.monotonic()
        try:
            finished = run_until_stopped(loops, stop, wait_s=0.2, look_every_s=0.01)
            took = time.monotonic() - started
        finally:
            release.set()

        assert finished is False
        assert took < 5
        assert logged(caplog, "worker_stopped_with_work_running")[0]["loops"] == ["agent-turns"]
        # A daemon thread: it never keeps the process alive after main() returns.
        assert all(t.daemon for t in threading.enumerate() if t.name == "agent-turns")

    def test_a_loop_that_dies_stops_the_worker(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        stop = threading.Event()

        def dies() -> None:
            raise SystemExit("a bug no task catches")

        loops = {
            "agent-turns": ClockCheck([dies], tmp_path / "a"),
            "clock-check": ClockCheck([lambda: None], tmp_path / "b", interval_s=0.01),
        }

        assert run_until_stopped(loops, stop, wait_s=5, look_every_s=0.01) is False
        assert stop.is_set()
        assert logged(caplog, "worker_loop_died")[0]["loops"] == ["agent-turns"]

    def test_no_further_agent_turn_starts_once_told_to_stop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stop = threading.Event()
        ran: list[uuid.UUID] = []

        def a_turn(_: Any, conversation_id: uuid.UUID, **__: Any) -> TurnResult:
            ran.append(conversation_id)
            stop.set()
            return TurnResult(Status.DONE)

        pending = PendingTurns(cast(Agent, object()))
        waiting = [(uuid.uuid4(), False), (uuid.uuid4(), False)]
        monkeypatch.setattr(pending, "due", lambda: waiting)
        monkeypatch.setattr(pending_module, "run_turn", a_turn)

        assert pending.run_pending_turns(stop) == 1
        assert ran == [waiting[0][0]]


@pytest.mark.parametrize(("beats", "exit_code"), [(True, 0), (False, 1)])
def test_the_health_check_command_reports_through_its_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, beats: bool, exit_code: int
) -> None:
    heartbeat = tmp_path / "heartbeat"
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u@h/d")
    monkeypatch.setenv("WEBSITE_URL", "http://localhost:5173")
    monkeypatch.setenv("WORKER_HEARTBEAT_FILE", str(heartbeat))
    if beats:
        beat(heartbeat)

    with pytest.raises(SystemExit) as finished:
        alive.main()

    assert finished.value.code == exit_code
