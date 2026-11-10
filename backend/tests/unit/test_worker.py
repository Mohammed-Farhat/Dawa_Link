"""The clock check loop and its heartbeat (docs/04 R-T10; FX-13)."""

import threading
import time
from pathlib import Path

import pytest

from dawalink.domain.numbers import CLOCK_CHECK_LATE_AFTER_S
from dawalink.worker import alive
from dawalink.worker.heartbeat import beat, is_alive
from dawalink.worker.loop import ClockCheck
from tests.conftest import logged


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
