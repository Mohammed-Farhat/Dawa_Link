"""The clock check: run every task, record a heartbeat, wait, repeat (docs/04 R-T10, N-26)."""

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

import structlog

from dawalink.domain.numbers import CLOCK_CHECK_INTERVAL_S
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

    def run_pass(self) -> None:
        """Run every task once. One failing task never stops the others."""
        for task in self._tasks:
            try:
                task()
            except Exception:
                log.exception("clock_task_failed", task=getattr(task, "__name__", repr(task)))
        beat(self._heartbeat_file)

    def run_until(self, stop: threading.Event) -> None:
        """Loop until `stop` is set. The pass in progress always finishes first."""
        while not stop.is_set():
            self.run_pass()
            stop.wait(self._interval_s)
