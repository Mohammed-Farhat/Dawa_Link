"""Runs the worker: python -m dawalink.worker"""

import signal
import sys
import threading
import time
from collections.abc import Mapping
from email.utils import parseaddr
from types import FrameType

import structlog
from sqlalchemy.orm import Session, sessionmaker

from dawalink.agent.pending import PendingTurns
from dawalink.agent.setup import build_agent
from dawalink.config import ConfigError, Settings, load_settings
from dawalink.db.session import make_engine
from dawalink.domain.clock import Clock
from dawalink.domain.numbers import AGENT_TURNS_AT_ONCE, WORKER_STOP_WAIT_S
from dawalink.observability.logging import configure_logging
from dawalink.services.clock import AppClock
from dawalink.services.clock_check import ClockTasks
from dawalink.services.email import EmailSender, LogSender, SmtpSender
from dawalink.worker.loop import ClockCheck, ClockTask

log = structlog.get_logger(__name__)


def clock_tasks(
    settings: Settings, sessions: sessionmaker[Session], clock: Clock
) -> tuple[ClockTask, ...]:
    """Everything the worker does each pass, in order (docs/04 R-T10)."""
    retention = None
    if settings.database_retention_url:
        retention = sessionmaker(
            make_engine(settings.database_retention_url), expire_on_commit=False
        )
    return ClockTasks(
        sessions,
        clock,
        mailer=mailer(settings),
        retention_sessions=retention,
        website_url=settings.website_url,
    ).tasks()


def mailer(settings: Settings) -> EmailSender:
    """The worker's way of sending email, from the settings (docs/12 §9).

    In AWS a missing or half-set mail server is refused at start: an email only written
    to the log would be recorded as sent, and a client would never get their link.
    """
    if settings.app_env == "aws":
        _check_aws_mail(settings)
    if settings.smtp_host:
        # A login means a real server (SES): TLS first, unless SMTP_STARTTLS says no.
        starttls = settings.smtp_starttls
        if starttls is None:
            starttls = settings.smtp_user is not None
        password = settings.smtp_password
        return SmtpSender(
            settings.smtp_host,
            settings.smtp_port,
            settings.email_from,
            user=settings.smtp_user,
            password=password.get_secret_value() if password else None,
            starttls=starttls,
        )
    # In-app notifications still work; locally the log is enough.
    log.warning("email_not_configured", effect="emails are only written to the log")
    return LogSender()


def _check_aws_mail(settings: Settings) -> None:
    """Names what is wrong with the mail settings in AWS, never a value (FX-17)."""
    problems = []
    if not settings.smtp_host:
        problems.append("SMTP_HOST")
    # 1025 is the local catcher's default, left unset; 465 and 2465 want TLS from the
    # first byte, which this sender doesn't speak. SES takes STARTTLS on 587 or 2587.
    if settings.smtp_port in (1025, 465, 2465):
        problems.append("SMTP_PORT (587 or 2587, with STARTTLS)")
    if not settings.smtp_user or settings.smtp_password is None:
        problems.append("SMTP_USER and SMTP_PASSWORD")
    elif settings.smtp_starttls is False:
        problems.append("SMTP_STARTTLS (a login is never sent in clear)")
    sender = parseaddr(settings.email_from)[1]
    domain = sender.rpartition("@")[2].lower()
    if "@" not in sender or not domain or domain.endswith(".invalid"):
        problems.append("EMAIL_FROM (an address SES has verified)")
    if problems:
        raise ConfigError("Email can't be sent in AWS. Set: " + ", ".join(problems))


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    stop = threading.Event()

    def request_stop(signal_number: int, _: FrameType | None) -> None:
        log.info("worker_stopping", signal=signal_number)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    engine = make_engine(settings.database_url)
    sessions = sessionmaker(engine, expire_on_commit=False)
    clock = AppClock(engine, demo_mode=settings.demo_mode)
    tasks = clock_tasks(settings, sessions, clock)
    agent = build_agent(settings, sessions, clock)
    log.info(
        "worker_started",
        version=settings.app_version,
        tasks=len(tasks),
        agent_turns=agent is not None,
    )
    loops = {"clock-check": ClockCheck(tasks, settings.worker_heartbeat_file)}
    if agent is not None:
        # The agent's turns run in their own loop: a model that takes a minute to
        # answer must never delay an offer's expiry or a no-show (docs/04 SM-12). Several
        # at a time, each on another conversation, so that one slow turn doesn't keep the
        # other clients waiting (A#30). Each ends within its time limit (N-37), inside
        # the wait for a clean stop.
        pending = PendingTurns(agent, at_once=AGENT_TURNS_AT_ONCE)

        def run_agent_turns() -> None:
            pending.run_pending_turns(stop)

        loops["agent-turns"] = ClockCheck(
            (run_agent_turns,),
            settings.worker_heartbeat_file.with_name(
                settings.worker_heartbeat_file.name + "-agent"
            ),
        )
    clean = run_until_stopped(loops, stop)
    log.info("worker_stopped", clean=clean)
    if not clean:
        sys.exit(1)


def run_until_stopped(
    loops: Mapping[str, ClockCheck],
    stop: threading.Event,
    *,
    wait_s: float = WORKER_STOP_WAIT_S,
    look_every_s: float = 1.0,
) -> bool:
    """Runs each loop on its own thread until `stop` is set, then waits up to `wait_s` for
    the work in progress (A#21). Returns whether it all ended cleanly: no loop died, and
    nothing was still running when the wait was over.

    The loops run on daemon threads so that one still busy when the wait is over (a turn
    stuck on the model) doesn't keep the process alive: ECS would kill it anyway, and a
    turn that never finished runs again once its lease is over (FX-13).
    The main thread only waits; it is the one Python gives the stop signal to. A loop that
    died on its own stops the worker too, so that ECS starts a new one.
    """
    threads = [
        threading.Thread(target=loop.run_until, args=(stop,), name=name, daemon=True)
        for name, loop in loops.items()
    ]
    for thread in threads:
        thread.start()
    died = False
    while not stop.wait(look_every_s):
        dead = [thread.name for thread in threads if not thread.is_alive()]
        if dead:
            log.error("worker_loop_died", loops=dead)
            died = True
            stop.set()
    deadline = time.monotonic() + wait_s
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    still_running = [thread.name for thread in threads if thread.is_alive()]
    if still_running:
        log.warning("worker_stopped_with_work_running", loops=still_running, waited_s=wait_s)
    return not died and not still_running


if __name__ == "__main__":
    main()
