"""Runs the worker: python -m dawalink.worker"""

import signal
import threading
from types import FrameType

import structlog

from dawalink.config import load_settings
from dawalink.observability.logging import configure_logging
from dawalink.worker.loop import ClockCheck, ClockTask

log = structlog.get_logger(__name__)

# Each feature adds its task here: expiries, matching, agent turns, emails, retention.
TASKS: tuple[ClockTask, ...] = ()


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    stop = threading.Event()

    def request_stop(signal_number: int, _: FrameType | None) -> None:
        log.info("worker_stopping", signal=signal_number)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    log.info("worker_started", version=settings.app_version, tasks=len(TASKS))
    ClockCheck(TASKS, settings.worker_heartbeat_file).run_until(stop)
    log.info("worker_stopped")


if __name__ == "__main__":
    main()
