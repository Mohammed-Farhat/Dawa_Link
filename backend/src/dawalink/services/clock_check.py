"""The clock check's tasks: what happens because time passed (docs/04 R-T10, SM-12).

There is no jobs table. Each task asks the database for rows whose deadline has passed,
then handles each row **in its own transaction**, re-checking it under its locks. So a
row is never handled twice, two workers can run at once, and a worker that stops in the
middle simply leaves the rest for the next pass (FX-13).

A row that fails is logged with its task and its id, and the task goes on to the next
row. Only a lost connection ends the task: then every row would fail the same way.
"""

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import date
from typing import Any

import structlog
from sqlalchemy import Select, or_, select
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as NoConnectionFree
from sqlalchemy.orm import Session, sessionmaker

from dawalink.db.models import (
    Claim,
    ClientProfile,
    EarlyReleaseAsk,
    EarlyReleaseRequest,
    EmailOutbox,
    Order,
    RequestItem,
    SourcingRequest,
)
from dawalink.domain.clock import Clock
from dawalink.domain.numbers import WINDOW_CHECK_BEFORE_END
from dawalink.domain.requests import FINAL_ITEM_STATES
from dawalink.services import (
    claims,
    daily,
    early_release,
    email,
    matching,
    orders,
    requests,
)
from dawalink.services.context import Tx, unit_of_work

log = structlog.get_logger(__name__)
BATCH = 50

# The SQLSTATEs that mean the server is going away or won't take us: class 08 (connection
# exception), the server shutting down or starting, too many connections.
_SERVER_GONE = ("57P01", "57P02", "57P03", "53300")


def database_lost(error: BaseException) -> bool:
    """Whether `error` means the database can't be reached, rather than one statement failing.

    psycopg calls a statement time-out, a deadlock and a lock that isn't free an
    OperationalError too, but those are one row's failure: the next row may well work. A
    lost connection has no SQLSTATE (libpq reports it itself), or one of class 08.
    """
    if isinstance(error, NoConnectionFree):
        return True  # no connection came free in the pool's wait (FX-12)
    if not isinstance(error, DBAPIError):
        return False
    if error.connection_invalidated:
        return True
    if not isinstance(error, OperationalError):
        return False
    sqlstate = getattr(error.orig, "sqlstate", None)
    return sqlstate is None or sqlstate.startswith("08") or sqlstate in _SERVER_GONE


class ClockTasks:
    """Every task returns how many rows it acted on."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        clock: Clock,
        *,
        mailer: email.EmailSender | None = None,
        website_url: str = "",
        retention_sessions: sessionmaker[Session] | None = None,
        batch: int = BATCH,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._mailer = mailer or email.LogSender()
        # Where the links of the account emails lead.
        self._website_url = website_url
        # The login that may delete old rows. Without it, the purge is skipped.
        self._retention_sessions = retention_sessions
        self._batch = batch
        # Per task, the rows that failed in its last run. They are tried again every pass,
        # but after the others: a batch that starts with rows that always fail would
        # otherwise hold back every row behind them (A#26).
        self._failing: dict[str, list[Any]] = {}

    def _due(self, task: str, statement: Select[Any]) -> list[Any]:
        """The IDs of the rows a task must look at, oldest deadline first, then the rows
        that failed last time."""
        failing = self._failing.get(task, [])
        if failing:
            statement = statement.where(statement.selected_columns[0].not_in(failing))
        with self._sessions() as session:
            fresh = list(session.execute(statement.limit(self._batch)).scalars())
        return fresh + failing

    @contextmanager
    def _one_row(self, task: str, row: Any, failed: list[Any]) -> Iterator[None]:
        """One row's failure is logged and noted; a lost connection ends the task."""
        try:
            yield
        except Exception as error:
            if database_lost(error):
                raise
            log.exception("clock_row_failed", task=task, row=str(row))
            failed.append(row)

    def _each(self, task: str, ids: Sequence[Any], action: Callable[[Tx, Any], Any]) -> int:
        """Handles each row in its own transaction. A row that needed nothing isn't counted."""
        done = 0
        failed: list[Any] = []
        for row_id in ids:
            with (
                self._one_row(task, row_id, failed),
                unit_of_work(self._sessions, self._clock) as tx,
            ):
                if action(tx, row_id):
                    done += 1
        self._failing[task] = failed[: self._batch]
        return done

    # 1. Offers whose two hours passed (O10).
    def expire_offers(self) -> int:
        now = self._clock.now()
        due = self._due(
            "expire_offers",
            select(Order.id)
            .where(Order.state == "OFFERED", Order.offer_expires_at <= now)
            .order_by(Order.offer_expires_at),
        )
        return self._each("expire_offers", due, lambda tx, order_id: orders.end_offer(tx, order_id))

    # 2. Reservations nobody came for (O4), and the pause that may follow (R-N1).
    def expire_reservations(self) -> int:
        now = self._clock.now()
        due = self._due(
            "expire_reservations",
            select(Order.id)
            .where(Order.state == "RESERVED", Order.deadline <= now)
            .order_by(Order.deadline),
        )
        return self._each(
            "expire_reservations", due, lambda tx, order_id: orders.expire_no_show(tx, order_id)
        )

    def send_pickup_reminders(self) -> int:
        now = self._clock.now()
        due = self._due(
            "send_pickup_reminders",
            select(Order.id)
            .where(Order.state == "RESERVED", Order.next_reminder_at <= now)
            .order_by(Order.next_reminder_at),
        )
        return self._each(
            "send_pickup_reminders",
            due,
            lambda tx, order_id: orders.send_pickup_reminder(tx, order_id),
        )

    def lift_pauses(self) -> int:
        now = self._clock.now()
        due = self._due(
            "lift_pauses",
            select(ClientProfile.user_id).where(
                ClientProfile.status == "PAUSED", ClientProfile.paused_until <= now
            ),
        )
        return self._each(
            "lift_pauses", due, lambda tx, client_id: orders.lift_pause(tx, client_id)
        )

    # 3. Early-release asks a pharmacy didn't answer in time (R-E6).
    def expire_asks(self) -> int:
        now = self._clock.now()
        due = self._due(
            "expire_asks",
            select(EarlyReleaseAsk.id)
            .where(EarlyReleaseAsk.state == "ASKED", EarlyReleaseAsk.respond_by <= now)
            .order_by(EarlyReleaseAsk.respond_by),
        )
        return self._each(
            "expire_asks", due, lambda tx, ask_id: early_release.expire_ask(tx, ask_id)
        )

    # 3b. Early-release requests with no ask left to wait for (R-E7). They normally end
    # with their last ask; this catches the case where that follow-up failed.
    def resolve_early_release(self) -> int:
        waiting = (
            select(EarlyReleaseAsk.id)
            .where(
                EarlyReleaseAsk.er_request_id == EarlyReleaseRequest.id,
                EarlyReleaseAsk.state == "ASKED",
            )
            .exists()
        )
        due = self._due(
            "resolve_early_release",
            select(EarlyReleaseRequest.id)
            .where(EarlyReleaseRequest.state == "OPEN", ~waiting)
            .order_by(EarlyReleaseRequest.created_at),
        )
        return self._each(
            "resolve_early_release",
            due,
            lambda tx, request_id: early_release.resolve(tx, request_id),
        )

    # 4. The window check, one hour before a request's window ends (N-24).
    def run_window_checks(self) -> int:
        now = self._clock.now()
        due = self._due(
            "run_window_checks",
            select(SourcingRequest.id)
            .where(
                SourcingRequest.state == "OPEN",
                SourcingRequest.window_checked_at.is_(None),
                SourcingRequest.ends_at <= now + WINDOW_CHECK_BEFORE_END,
            )
            .order_by(SourcingRequest.ends_at),
        )
        return self._each(
            "run_window_checks",
            due,
            lambda tx, request_id: requests.run_window_check(tx, request_id),
        )

    # 5. Requests whose window ended (R-RQ9). One with an offer pending waits for it.
    # Also a request whose medicines are all settled: it normally closes right after the
    # action that settled the last one, and this catches the case where that failed.
    def end_windows(self) -> int:
        now = self._clock.now()
        unsettled = (
            select(RequestItem.id)
            .where(
                RequestItem.request_id == SourcingRequest.id,
                RequestItem.state.not_in([state.value for state in FINAL_ITEM_STATES]),
            )
            .exists()
        )
        due = self._due(
            "end_windows",
            select(SourcingRequest.id)
            .where(
                SourcingRequest.state == "OPEN",
                or_(SourcingRequest.ends_at <= now, ~unsettled),
            )
            .order_by(SourcingRequest.ends_at),
        )
        return self._each(
            "end_windows", due, lambda tx, request_id: requests.close_if_done(tx, request_id)
        )

    # 5b. Watches whose window ended (SM-7). Request items end with their request.
    def expire_watches(self) -> int:
        now = self._clock.now()
        due = self._due(
            "expire_watches",
            select(Claim.id)
            .where(
                Claim.kind == "WATCH",
                Claim.state.in_(("ACTIVE", "OFFER_PENDING")),
                Claim.ends_at <= now,
            )
            .order_by(Claim.ends_at),
        )
        return self._each(
            "expire_watches", due, lambda tx, claim_id: claims.expire_watch(tx, claim_id)
        )

    # 6. The sweep: visible stock that a waiting claim hasn't been offered yet (R-PRI1).
    def matching_sweep(self) -> int:
        with unit_of_work(self._sessions, self._clock) as tx:
            groups = matching.groups_with_waiting_claims(tx)
        made = 0
        failed: list[Any] = []
        for group in groups:
            with (
                self._one_row("matching_sweep", group, failed),
                unit_of_work(self._sessions, self._clock) as tx,
            ):
                made += matching.run_for_group(tx, group)
        return made

    # 7. Queued emails (SM-12). A mail server that can't be reached ends the pass's
    # sending: the other emails would only wait for the same timeout one by one. One
    # refused email (a bad address) doesn't stop the others.
    def send_emails(self) -> int:
        now = self._clock.now()
        due = self._due(
            "send_emails",
            select(EmailOutbox.id)
            .where(EmailOutbox.state.in_(("QUEUED", "FAILED")), EmailOutbox.next_attempt_at <= now)
            .order_by(EmailOutbox.next_attempt_at, EmailOutbox.id),
        )
        sent = 0
        failed: list[Any] = []
        for outbox_id in due:
            outcome = None
            with (
                self._one_row("send_emails", outbox_id, failed),
                unit_of_work(self._sessions, self._clock) as tx,
            ):
                outcome = email.send_one(tx, self._mailer, outbox_id, self._website_url)
            if outcome is email.Outcome.SERVER_DOWN:
                break
            if outcome is email.Outcome.SENT:
                sent += 1
        self._failing["send_emails"] = failed[: self._batch]
        return sent

    # 7b. Accounts their client deleted (R-AU10): what the app's login may not delete
    # (chats, notifications, emails) goes within seconds, with the retention login.
    # Without that login it waits, as the daily purge does.
    def empty_deleted_accounts(self) -> int:
        if self._retention_sessions is None:
            return 0
        due = self._due(
            "empty_deleted_accounts",
            select(ClientProfile.user_id)
            .where(ClientProfile.status == "DELETED", ClientProfile.emptied_at.is_(None))
            .order_by(ClientProfile.user_id),
        )
        done = 0
        failed: list[Any] = []
        for user_id in due:
            with (
                self._one_row("empty_deleted_accounts", user_id, failed),
                unit_of_work(self._retention_sessions, self._clock) as tx,
            ):
                done += daily.empty_deleted_account(tx, user_id)
        self._failing["empty_deleted_accounts"] = failed[: self._batch]
        return done

    # 8. Once a day: delete what has passed its retention time, remind stale pharmacies.
    def run_daily_tasks(self) -> int:
        with unit_of_work(self._sessions, self._clock) as tx:
            if not daily.due_today(tx):
                return 0
            day = tx.today
        done = 0
        retention_failed: bool | None = None
        if self._retention_sessions is None:
            log.warning("retention_skipped", reason="no retention login configured")
        else:
            # A purge that fails must not block the reminders, or be retried every pass:
            # it is logged, and tomorrow's run deletes the same rows. Two days in a row
            # are an alert on the admins' Health page (FO-4).
            try:
                with unit_of_work(self._retention_sessions, self._clock) as tx:
                    purged = daily.purge(tx)
            except Exception:
                log.exception("retention_failed")
                retention_failed = True
            else:
                log.info("retention_done", **purged)
                done += sum(purged.values())
                retention_failed = False
        # The reminders and "done for today" are one transaction, committed before the
        # books are checked: a check that fails (a statement that timed out on a big
        # table) is logged, and the purge and the reminders are not run again 5 s later.
        with unit_of_work(self._sessions, self._clock) as tx:
            done += daily.remind_stale_inventories(tx)
            daily.mark_done(tx, day)
        try:
            self._check_the_books(day, retention_failed=retention_failed)
        except Exception as error:
            if database_lost(error):
                raise
            log.exception("books_check_failed")
        return done

    def _check_the_books(self, day: date, *, retention_failed: bool | None) -> None:
        """The books are checked once a day too (FO-3): read only, and said loudly."""
        with unit_of_work(self._sessions, self._clock) as tx:
            off = daily.books_that_are_off(tx)
            kept = daily.keep_checks(tx, day, off, retention_failed=retention_failed)
        if off["stock_off"] or off["requests_off"]:
            log.error(
                "books_do_not_add_up",
                stock_off=kept["stock_off"],
                stock_off_count=kept["stock_off_count"],
                requests_off=kept["requests_off"],
                requests_off_count=kept["requests_off_count"],
            )

    def tasks(self) -> tuple[Callable[[], None], ...]:
        """The tasks in the order the worker runs them each pass (docs/05 §6)."""
        steps: tuple[Callable[[], int], ...] = (
            self.expire_offers,
            self.expire_reservations,
            self.expire_asks,
            self.resolve_early_release,
            self.send_pickup_reminders,
            self.lift_pauses,
            self.run_window_checks,
            self.end_windows,
            self.expire_watches,
            self.matching_sweep,
            self.send_emails,
            self.empty_deleted_accounts,
            self.run_daily_tasks,
        )
        return tuple(_logged(step) for step in steps)


def _logged(step: Callable[[], int]) -> Callable[[], None]:
    def run() -> None:
        done = step()
        if done:
            log.info("clock_task", task=step.__name__, rows=done)

    run.__name__ = step.__name__
    return run
