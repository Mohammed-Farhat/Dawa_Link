"""The clock check's tasks: what happens because time passed (docs/04 R-T10, SM-12).

There is no jobs table. Each task asks the database for rows whose deadline has passed,
then handles each row **in its own transaction**, re-checking it under its locks. So a
row is never handled twice, two workers can run at once, and a worker that stops in the
middle simply leaves the rest for the next pass (FX-13).
"""

from collections.abc import Callable, Sequence
from typing import Any

import structlog
from sqlalchemy import Select, or_, select
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
from dawalink.domain.numbers import PICKUP_REMINDER_BEFORE, WINDOW_CHECK_BEFORE_END
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


class ClockTasks:
    """Every task returns how many rows it acted on."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        clock: Clock,
        *,
        mailer: email.EmailSender | None = None,
        retention_sessions: sessionmaker[Session] | None = None,
        batch: int = BATCH,
    ) -> None:
        self._sessions = sessions
        self._clock = clock
        self._mailer = mailer or email.LogSender()
        # The login that may delete old rows. Without it, the purge is skipped.
        self._retention_sessions = retention_sessions
        self._batch = batch

    def _due(self, statement: Select[Any]) -> list[Any]:
        """The IDs of the rows a task must look at, oldest deadline first."""
        with self._sessions() as session:
            return list(session.execute(statement.limit(self._batch)).scalars())

    def _each(self, ids: Sequence[Any], action: Callable[[Tx, Any], Any]) -> int:
        """Handles each row in its own transaction. A row that needed nothing isn't counted."""
        done = 0
        for row_id in ids:
            with unit_of_work(self._sessions, self._clock) as tx:
                if action(tx, row_id):
                    done += 1
        return done

    # 1. Offers whose two hours passed (O10).
    def expire_offers(self) -> int:
        now = self._clock.now()
        due = self._due(
            select(Order.id)
            .where(Order.state == "OFFERED", Order.offer_expires_at <= now)
            .order_by(Order.offer_expires_at)
        )
        return self._each(due, lambda tx, order_id: orders.end_offer(tx, order_id))

    # 2. Reservations nobody came for (O4), and the pause that may follow (R-N1).
    def expire_reservations(self) -> int:
        now = self._clock.now()
        due = self._due(
            select(Order.id)
            .where(Order.state == "RESERVED", Order.deadline <= now)
            .order_by(Order.deadline)
        )
        return self._each(due, lambda tx, order_id: orders.expire_no_show(tx, order_id))

    def send_pickup_reminders(self) -> int:
        now = self._clock.now()
        due = self._due(
            select(Order.id)
            .where(
                Order.state == "RESERVED",
                Order.reminder_sent_at.is_(None),
                Order.deadline <= now + PICKUP_REMINDER_BEFORE,
                Order.deadline > now,
            )
            .order_by(Order.deadline)
        )
        return self._each(due, lambda tx, order_id: orders.send_pickup_reminder(tx, order_id))

    def lift_pauses(self) -> int:
        now = self._clock.now()
        due = self._due(
            select(ClientProfile.user_id).where(
                ClientProfile.status == "PAUSED", ClientProfile.paused_until <= now
            )
        )
        return self._each(due, lambda tx, client_id: orders.lift_pause(tx, client_id))

    # 3. Early-release asks a pharmacy didn't answer in time (R-E6).
    def expire_asks(self) -> int:
        now = self._clock.now()
        due = self._due(
            select(EarlyReleaseAsk.id)
            .where(EarlyReleaseAsk.state == "ASKED", EarlyReleaseAsk.respond_by <= now)
            .order_by(EarlyReleaseAsk.respond_by)
        )
        return self._each(due, lambda tx, ask_id: early_release.expire_ask(tx, ask_id))

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
            select(EarlyReleaseRequest.id)
            .where(EarlyReleaseRequest.state == "OPEN", ~waiting)
            .order_by(EarlyReleaseRequest.created_at)
        )
        return self._each(due, lambda tx, request_id: early_release.resolve(tx, request_id))

    # 4. The window check, one hour before a request's window ends (N-24).
    def run_window_checks(self) -> int:
        now = self._clock.now()
        due = self._due(
            select(SourcingRequest.id)
            .where(
                SourcingRequest.state == "OPEN",
                SourcingRequest.window_checked_at.is_(None),
                SourcingRequest.ends_at <= now + WINDOW_CHECK_BEFORE_END,
            )
            .order_by(SourcingRequest.ends_at)
        )
        return self._each(due, lambda tx, request_id: requests.run_window_check(tx, request_id))

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
            select(SourcingRequest.id)
            .where(
                SourcingRequest.state == "OPEN",
                or_(SourcingRequest.ends_at <= now, ~unsettled),
            )
            .order_by(SourcingRequest.ends_at)
        )
        return self._each(due, lambda tx, request_id: requests.close_if_done(tx, request_id))

    # 5b. Watches whose window ended (SM-7). Request items end with their request.
    def expire_watches(self) -> int:
        now = self._clock.now()
        due = self._due(
            select(Claim.id)
            .where(
                Claim.kind == "WATCH",
                Claim.state.in_(("ACTIVE", "OFFER_PENDING")),
                Claim.ends_at <= now,
            )
            .order_by(Claim.ends_at)
        )
        return self._each(due, lambda tx, claim_id: claims.expire_watch(tx, claim_id))

    # 6. The sweep: visible stock that a waiting claim hasn't been offered yet (R-PRI1).
    def matching_sweep(self) -> int:
        with unit_of_work(self._sessions, self._clock) as tx:
            groups = matching.groups_with_waiting_claims(tx)
        made = 0
        for group in groups:
            with unit_of_work(self._sessions, self._clock) as tx:
                made += matching.run_for_group(tx, group)
        return made

    # 7. Queued emails (SM-12). A mail server that can't be reached ends the pass's
    # sending: the other emails would only wait for the same timeout one by one. One
    # refused email (a bad address) doesn't stop the others.
    def send_emails(self) -> int:
        now = self._clock.now()
        due = self._due(
            select(EmailOutbox.id)
            .where(EmailOutbox.state.in_(("QUEUED", "FAILED")), EmailOutbox.next_attempt_at <= now)
            .order_by(EmailOutbox.next_attempt_at, EmailOutbox.id)
        )
        sent = 0
        for outbox_id in due:
            with unit_of_work(self._sessions, self._clock) as tx:
                outcome = email.send_one(tx, self._mailer, outbox_id)
            if outcome is email.Outcome.SERVER_DOWN:
                break
            if outcome is email.Outcome.SENT:
                sent += 1
        return sent

    # 8. Once a day: delete what has passed its retention time, remind stale pharmacies.
    def run_daily_tasks(self) -> int:
        with unit_of_work(self._sessions, self._clock) as tx:
            if not daily.due_today(tx):
                return 0
            day = tx.today
        done = 0
        if self._retention_sessions is None:
            log.warning("retention_skipped", reason="no retention login configured")
        else:
            # A purge that fails must not block the reminders, or be retried every pass:
            # it is logged, and tomorrow's run deletes the same rows.
            try:
                with unit_of_work(self._retention_sessions, self._clock) as tx:
                    purged = daily.purge(tx)
            except Exception:
                log.exception("retention_failed")
            else:
                log.info("retention_done", **purged)
                done += sum(purged.values())
        with unit_of_work(self._sessions, self._clock) as tx:
            done += daily.remind_stale_inventories(tx)
            daily.mark_done(tx, day)
        return done

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
