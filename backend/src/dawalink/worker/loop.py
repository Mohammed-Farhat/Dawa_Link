"""The clock check: run every task, record a heartbeat, wait, repeat (docs/04 R-T10, N-26)."""

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

import structlog

from dawalink.domain.numbers import CLOCK_CHECK_INTERVAL_S
from dawalink.services.clock_check import database_lost
from dawalink.worker.heartbeat import beat

log = structlog.get_logger(__name__)

ClockTask = Callable[[], None]


class ClockCheck:
    def __init__(
        self,
        tasks: Sequence[ClockTask],
        heartbeat_file: Path,
        interval_s: float = CLOCK_CHECK_INTERVAL_S,
    ) -> None:
        self._tasks = tasks
        self._heartbeat_file = heartbeat_file
        self._interval_s = interval_s

    def run_pass(self, stop: threading.Event | None = None) -> None:
        """Run every task once. One failing task never stops the others.

        If the database can't be reached, the rest of the pass is skipped: the next pass
        tries again, and nothing is lost because the deadlines live on the rows (FX-10).
        A statement that timed out, or a deadlock, is one task's failure, not that.
        When `stop` is set, no further task starts: the worker is being stopped (A#21).
        The heartbeat is still written: the worker itself is alive.
        """
        for task in self._tasks:
            if stop is not None and stop.is_set():
                break
            try:
                task()
            except Exception as error:
                if database_lost(error):
                    log.warning("clock_check_paused", reason="the database can't be reached")
                    break
                log.exception("clock_task_failed", task=getattr(task, "__name__", repr(task)))
        beat(self._heartbeat_file)

    def run_until(self, stop: threading.Event) -> None:
        """Loop until `stop` is set. The task in progress finishes; no new one starts."""
        while not stop.is_set():
            self.run_pass(stop)
            stop.wait(self._interval_s)
