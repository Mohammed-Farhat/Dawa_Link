"""What happens because time passed: no-shows, the pause, reminders (docs/04 R-T10, O4, R-N1)."""

import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy.exc import OperationalError

from dawalink.domain.orders import OrderSource
from dawalink.services import daily, orders
from dawalink.services.orders import ReserveLine
from dawalink.worker.loop import ClockCheck
from tests.conftest import logged
from tests.db.factories import NOW
from tests.services.conftest import World

DAY = timedelta(days=1)


class WorkerKilled(BaseException):
    """The process ending mid-row (SIGKILL): nothing in the worker catches it."""


def reserve(world: World, client: uuid.UUID, *, key: str) -> uuid.UUID:
    """A reservation for pickup today, at a fresh pharmacy, for a fresh medicine."""
    item = world.make.item(days_left=60)
    tx = world.tx()
    (order,) = orders.reserve(
        tx,
        client_id=client,
        lines=[ReserveLine(item, 1, expected_price_lbp=600_000)],
        pickup_day=tx.today,
        source=OrderSource.SEARCH,
        idempotency_key=key,
    )
    world.settle(tx)
    return order.id


def order_row(world: World, order_id: uuid.UUID) -> Any:
    return world.one("SELECT * FROM orders WHERE id = :id", id=order_id)


def client_row(world: World, client: uuid.UUID) -> Any:
    return world.one("SELECT * FROM client_profiles WHERE user_id = :id", id=client)


class TestNoShow:
    def test_nothing_happens_before_the_deadline(self, world: World) -> None:
        order = reserve(world, world.make.client(), key="a")
        world.later(hours=10, minutes=59)

        assert world.clock_tasks().expire_reservations() == 0
        assert order_row(world, order).state == "RESERVED"

    def test_at_the_deadline_the_box_goes_back_and_the_no_show_counts(self, world: World) -> None:
        """O4."""
        client = world.make.client()
        order = reserve(world, client, key="a")
        world.later(hours=11)

        assert world.clock_tasks().expire_reservations() == 1

        row = order_row(world, order)
        assert (row.state, row.close_reason, row.counts_as_no_show) == (
            "EXPIRED_NO_SHOW",
            "expired",
            True,
        )
        assert (row.qty_locked, row.closed_at) == (0, NOW + timedelta(hours=11))
        stock = world.one(
            "SELECT qty_on_hand, qty_reserved FROM inventory_items WHERE id = :i",
            i=row.inventory_item_id,
        )
        assert tuple(stock) == (5, 0)
        assert world.notifications(client) == ["CN-3", "CN-7"]
        assert world.audit_actions(order) == ["order.reserve", "order.no_show"]
        assert client_row(world, client).status == "ACTIVE"

    def test_running_the_check_again_does_nothing(self, world: World) -> None:
        order = reserve(world, world.make.client(), key="a")
        world.later(hours=12)
        tasks = world.clock_tasks()

        assert (tasks.expire_reservations(), tasks.expire_reservations()) == (1, 0)
        assert world.audit_actions(order) == ["order.reserve", "order.no_show"]

    def test_a_pickup_just_before_the_check_wins(self, world: World) -> None:
        """FR-10: the row is re-checked under its locks."""
        from dawalink.services import counter

        order = reserve(world, world.make.client(), key="a")
        row = order_row(world, order)
        world.later(hours=10)
        counter.mark_picked_up(world.tx(), row.pharmacy_id, order)
        world.later(hours=2)

        assert world.clock_tasks().expire_reservations() == 0
        assert order_row(world, order).state == "PICKED_UP"


class TestThePause:
    """R-N1: two counted no-shows in 30 days pause the client for 7 days."""

    def no_show(self, world: World, client: uuid.UUID, key: str) -> None:
        reserve(world, client, key=key)
        world.later(hours=24)
        assert world.clock_tasks().expire_reservations() == 1

    def test_the_second_no_show_pauses_for_seven_days(self, world: World) -> None:
        client = world.make.client()

        self.no_show(world, client, "a")
        after_one = client_row(world, client).status
        self.no_show(world, client, "b")

        paused = client_row(world, client)
        assert after_one == "ACTIVE"
        assert paused.status == "PAUSED"
        assert paused.paused_until == NOW + timedelta(hours=48) + 7 * DAY
        assert world.notifications(client).count("CN-8") == 1
        assert "client.pause" in world.audit_actions(client)
        flag = world.one("SELECT * FROM abuse_flags WHERE subject_id = :c", c=client)
        assert (flag.rule, flag.severity, flag.state) == ("no_show_pause", "low", "OPEN")

    def test_a_paused_client_cannot_reserve_until_the_pause_ends(self, world: World) -> None:
        from dawalink.services.errors import Code, ServiceError

        client = world.make.client()
        self.no_show(world, client, "a")
        self.no_show(world, client, "b")

        with pytest.raises(ServiceError) as refused:
            reserve(world, client, key="c")
        still_paused = world.clock_tasks().lift_pauses()
        world.later(days=7, minutes=1)
        lifted = world.clock_tasks().lift_pauses()

        assert refused.value.code is Code.CLIENT_PAUSED
        assert (still_paused, lifted) == (0, 1)
        assert client_row(world, client).status == "ACTIVE"
        assert reserve(world, client, key="d") is not None

    def test_no_shows_older_than_thirty_days_no_longer_count(self, world: World) -> None:
        client = world.make.client()

        self.no_show(world, client, "a")
        world.later(days=31)
        self.no_show(world, client, "b")

        assert client_row(world, client).status == "ACTIVE"

    def test_a_cancel_or_a_not_available_never_counts(self, world: World) -> None:
        """R-N2."""
        from dawalink.services import counter

        client = world.make.client()
        first = reserve(world, client, key="a")
        second = reserve(world, client, key="b")
        tx = world.tx()
        orders.cancel_by_client(tx, client, first)
        counter.mark_not_available(tx, order_row(world, second).pharmacy_id, second)
        world.settle(tx)
        self.no_show(world, client, "c")

        assert client_row(world, client).status == "ACTIVE"


class TestPickupReminder:
    def test_a_same_day_reservation_is_reminded_once_two_hours_before_closing(
        self, world: World
    ) -> None:
        """N-8 (the owner, 2026-11-18). Reserved at 10:00 for a deadline at 21:00: under
        12 hours, so the one reminder is the last one, at 19:00. Nothing comes right
        after reserving."""
        client = world.make.client()
        order = reserve(world, client, key="a")
        tasks = world.clock_tasks()
        assert order_row(world, order).next_reminder_at == NOW + timedelta(hours=9)

        at_once = tasks.send_pickup_reminders()
        world.later(hours=8, minutes=59)
        too_early = tasks.send_pickup_reminders()
        world.later(minutes=1)
        sent = tasks.send_pickup_reminders()
        again = tasks.send_pickup_reminders()

        assert (at_once, too_early, sent, again) == (0, 0, 1, 0)
        assert world.notifications(client) == ["CN-3", "CN-6"]
        row = order_row(world, order)
        assert (row.reminder_sent_at, row.next_reminder_at) == (NOW + timedelta(hours=9), None)

    def test_a_reservation_for_a_later_day_is_reminded_every_12_hours(self, world: World) -> None:
        """The deadline is the pharmacy's closing time two days on, 59 hours after
        reserving: reminders after 12, 24, 36 and 48 hours, and a last one 2 hours before
        the deadline."""
        client = world.make.client()
        pharmacy = world.make.pharmacy(pickup_days=3)
        item = world.make.item(pharmacy_id=pharmacy, days_left=60)
        tx = world.tx()
        (order,) = orders.reserve(
            tx,
            client_id=client,
            lines=[ReserveLine(item, 1, expected_price_lbp=600_000)],
            pickup_day=tx.today + timedelta(days=2),
            source=OrderSource.SEARCH,
            idempotency_key="later",
        )
        world.settle(tx)
        tasks = world.clock_tasks()
        deadline = order_row(world, order.id).deadline
        assert deadline == NOW + timedelta(hours=59)

        sent_after = []
        for hour in range(1, 60):
            world.later(hours=1)
            if tasks.send_pickup_reminders():
                sent_after.append(hour)

        assert sent_after == [12, 24, 36, 48, 57]
        assert world.notifications(client).count("CN-6") == 5

    def test_nothing_is_sent_for_a_reservation_that_ended(self, world: World) -> None:
        client = world.make.client()
        order = reserve(world, client, key="a")
        tx = world.tx()
        orders.cancel_by_client(tx, client, order)
        world.settle(tx)
        # Past the moment its reminder was due (9 hours after reserving, see above).
        world.later(hours=10)

        assert world.clock_tasks().send_pickup_reminders() == 0
        assert "CN-6" not in world.notifications(client)


class TestTheWorkerLoop:
    def test_a_worker_that_stops_mid_pass_leaves_the_rest_for_the_next(self, world: World) -> None:
        """FX-13: each row is its own transaction, so half a pass is still correct."""
        client = world.make.client()
        first, second, third = (reserve(world, client, key=key) for key in "abc")
        world.later(hours=12)
        tasks = world.clock_tasks()
        real = orders.expire_no_show
        handled: list[uuid.UUID] = []

        def crash_on_the_second(tx: Any, order_id: uuid.UUID) -> Any:
            if len(handled) == 1:
                raise WorkerKilled
            handled.append(order_id)
            return real(tx, order_id)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(orders, "expire_no_show", crash_on_the_second)
            with pytest.raises(WorkerKilled):
                tasks.expire_reservations()
        states = [order_row(world, order).state for order in (first, second, third)]

        assert states.count("EXPIRED_NO_SHOW") == 1
        assert tasks.expire_reservations() == 2
        assert {order_row(world, o).state for o in (first, second, third)} == {"EXPIRED_NO_SHOW"}

    def test_a_row_that_fails_is_logged_and_the_rows_behind_it_are_handled(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A#26: one row that always fails (a bug, a broken invariant) never holds up the
        others, even when it is the oldest deadline of a full batch."""
        client = world.make.client()
        made = {reserve(world, client, key=key) for key in "abc"}
        world.later(hours=12)
        tasks = world.clock_tasks()
        tasks._batch = 1  # the broken row fills the whole batch
        real = orders.expire_no_show
        broken: list[uuid.UUID] = []

        def fails_on_the_first_one_seen(tx: Any, order_id: uuid.UUID) -> Any:
            if not broken:
                broken.append(order_id)
            if order_id == broken[0]:
                raise RuntimeError("a bug in this row")
            return real(tx, order_id)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(orders, "expire_no_show", fails_on_the_first_one_seen)
            handled = [tasks.expire_reservations() for _ in range(3)]

        assert handled == [0, 1, 1]
        assert order_row(world, broken[0]).state == "RESERVED"
        assert {order_row(world, o).state for o in made - set(broken)} == {"EXPIRED_NO_SHOW"}
        failures = logged(caplog, "clock_row_failed")
        assert {(entry["task"], entry["row"]) for entry in failures} == {
            ("expire_reservations", str(broken[0]))
        }
        assert len(failures) == 3  # tried again every pass, after the others

    def test_a_statement_that_times_out_on_one_row_is_that_rows_failure(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A#26: a time-out, a deadlock or a lock that isn't free is not "the database
        can't be reached": the other rows of the pass are handled."""
        client = world.make.client()
        slow, other = (reserve(world, client, key=key) for key in "ab")
        world.later(hours=12)
        real = orders.expire_no_show

        def times_out_on_one(tx: Any, order_id: uuid.UUID) -> Any:
            if order_id == slow:
                raise OperationalError("UPDATE orders", {}, psycopg.errors.QueryCanceled())
            return real(tx, order_id)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(orders, "expire_no_show", times_out_on_one)
            handled = world.clock_tasks().expire_reservations()

        assert handled == 1
        assert order_row(world, other).state == "EXPIRED_NO_SHOW"
        assert [entry["row"] for entry in logged(caplog, "clock_row_failed")] == [str(slow)]

    def test_a_lost_connection_ends_the_task_at_once(self, world: World) -> None:
        client = world.make.client()
        for key in "ab":
            reserve(world, client, key=key)
        world.later(hours=12)
        tried: list[uuid.UUID] = []

        def connection_lost(tx: Any, order_id: uuid.UUID) -> Any:
            tried.append(order_id)
            raise OperationalError("UPDATE orders", {}, Exception("server closed the connection"))

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(orders, "expire_no_show", connection_lost)
            with pytest.raises(OperationalError):
                world.clock_tasks().expire_reservations()

        assert len(tried) == 1

    def test_a_task_whose_statement_times_out_is_logged_and_the_pass_goes_on(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        ran: list[str] = []

        def expire_offers() -> None:
            raise OperationalError("SELECT", {}, psycopg.errors.QueryCanceled())

        check = ClockCheck([expire_offers, lambda: ran.append("later task")], tmp_path / "beat")

        check.run_pass()

        assert ran == ["later task"]
        assert logged(caplog, "clock_check_paused") == []
        assert [entry["task"] for entry in logged(caplog, "clock_task_failed")] == ["expire_offers"]

    def test_a_daily_check_that_fails_is_not_run_again_every_pass(
        self, world: World, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The day is marked done with its reminders, before the books are checked: a
        check that times out is logged, and the purge doesn't run again 5 s later."""
        purges: list[int] = []
        real_purge = daily.purge

        def counted_purge(tx: Any) -> dict[str, int]:
            purges.append(1)
            return real_purge(tx)

        def times_out(_: Any) -> dict[str, list[str]]:
            raise OperationalError("SELECT", {}, psycopg.errors.QueryCanceled())

        tasks = world.clock_tasks()
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(daily, "purge", counted_purge)
            patch.setattr(daily, "books_that_are_off", times_out)
            tasks.run_daily_tasks()
            again = tasks.run_daily_tasks()

        assert (len(purges), again) == (1, 0)
        assert len(logged(caplog, "books_check_failed")) == 1
        assert daily.due_today(world.tx()) is False

    def test_when_the_database_is_down_the_pass_pauses_and_the_worker_stays_alive(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """FX-10: no error storm, nothing lost, and the heartbeat is still written."""
        ran: list[str] = []

        def database_down() -> None:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        heartbeat = tmp_path / "heartbeat"
        check = ClockCheck([database_down, lambda: ran.append("later task")], heartbeat)

        check.run_pass()

        assert ran == []
        assert heartbeat.exists()
        assert len(logged(caplog, "clock_check_paused")) == 1
        assert logged(caplog, "clock_task_failed") == []

    def test_the_worker_builds_its_tasks_from_the_settings(
        self, world: World, tmp_path: Path
    ) -> None:
        from dawalink.worker.__main__ import clock_tasks
        from tests.conftest import make_settings

        settings = make_settings(str(world.connection.engine.url), tmp_path)
        tasks = clock_tasks(settings, world.sessions(), world.clock)

        assert [task.__name__ for task in tasks][:2] == ["expire_offers", "expire_reservations"]


class TestFollowUpThatFailed:
    """Follow-up work runs after the commit. If it failed, the clock check still does it."""

    def test_a_request_whose_medicines_are_all_settled_is_closed(self, world: World) -> None:
        request = world.make.request()
        world.make.request_item(request, state="SECURED", qty_secured=1)
        still_searching = world.make.request()
        world.make.request_item(still_searching)

        assert world.clock_tasks().end_windows() == 1

        closed = world.one("SELECT state, outcome FROM sourcing_requests WHERE id = :r", r=request)
        assert (closed.state, closed.outcome) == ("CLOSED", "FULFILLED")
        other = world.one("SELECT state FROM sourcing_requests WHERE id = :r", r=still_searching)
        assert other.state == "OPEN"

    def test_an_early_release_request_with_no_ask_left_is_ended(self, world: World) -> None:
        answered = world.make.early_release_request()
        world.make.early_release_ask(er_request_id=answered, state="DECLINED")
        waiting = world.make.early_release_request()
        world.make.early_release_ask(er_request_id=waiting)

        assert world.clock_tasks().resolve_early_release() == 1

        states = {
            row.id: row.state for row in world.all("SELECT id, state FROM early_release_requests")
        }
        assert states == {answered: "UNFULFILLED", waiting: "OPEN"}
