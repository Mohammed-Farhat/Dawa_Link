"""Runs the worker: python -m dawalink.worker"""

import signal
import threading
from types import FrameType

import structlog
from sqlalchemy.orm import sessionmaker

from dawalink.config import Settings, load_settings
from dawalink.db.session import make_engine
from dawalink.observability.logging import configure_logging
from dawalink.services.clock import AppClock
from dawalink.services.clock_check import ClockTasks
from dawalink.services.email import EmailSender, LogSender, SmtpSender
from dawalink.worker.loop import ClockCheck, ClockTask

log = structlog.get_logger(__name__)


def clock_tasks(settings: Settings) -> tuple[ClockTask, ...]:
    """Everything the worker does each pass, in order (docs/04 R-T10)."""
    engine = make_engine(settings.database_url)
    sessions = sessionmaker(engine, expire_on_commit=False)
    clock = AppClock(engine, demo_mode=settings.demo_mode)
    retention = None
    if settings.database_retention_url:
        retention = sessionmaker(
            make_engine(settings.database_retention_url), expire_on_commit=False
        )
    return ClockTasks(
        sessions, clock, mailer=mailer(settings), retention_sessions=retention
    ).tasks()


def mailer(settings: Settings) -> EmailSender:
    if settings.smtp_host:
        return SmtpSender(settings.smtp_host, settings.smtp_port, settings.email_from)
    # In-app notifications still work. In AWS this is a mistake, so it is an error there.
    report = log.error if settings.app_env == "aws" else log.warning
    report("email_not_configured", effect="emails are only written to the log")
    return LogSender()


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    stop = threading.Event()

    def request_stop(signal_number: int, _: FrameType | None) -> None:
        log.info("worker_stopping", signal=signal_number)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    tasks = clock_tasks(settings)
    log.info("worker_started", version=settings.app_version, tasks=len(tasks))
    ClockCheck(tasks, settings.worker_heartbeat_file).run_until(stop)
    log.info("worker_stopped")


if __name__ == "__main__":
    main()
