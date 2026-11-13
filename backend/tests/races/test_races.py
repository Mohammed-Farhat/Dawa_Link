"""Two people act at the same moment (docs/05 §6; docs/09 FR-1, FR-2, FR-13).

Each test starts both actions inside open transactions (see `Arena.together`), so the
outcome never depends on timing luck. Either may win; what is checked is that exactly one
does, that the loser is told why, and that the books still balance (the fixture checks
INV-2 and INV-20 after every test).
"""

import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dawalink.config import Settings
from dawalink.db.models import Product
from dawalink.domain.orders import OrderSource
from dawalink.domain.vocabulary import ClaimSource
from dawalink.ops.import_catalog import close_what_became_controlled
from dawalink.services import catalog, claims, counter, early_release, email, matching, orders
from dawalink.services.clock_check import ClockTasks
from dawalink.services.context import Tx, unit_of_work
from dawalink.services.errors import Code, ServiceError
from dawalink.services.notify import Template, notify
from dawalink.services.orders import ReserveLine
from dawalink.services.travel import shared_location
from tests.conftest import logged
from tests.db.factories import NOW
from tests.races.conftest import Arena

HAMRA = shared_location(33.896, 35.483)
PRICE = 600_000  # a 1,000,000 LBP box with 60 days left: 40% off


def tap_reserve(client: uuid.UUID, item: uuid.UUID, key: str = "tap") -> Callable[[Tx], Any]:
    return lambda tx: orders.reserve(
        tx,
        client_id=client,
        lines=[ReserveLine(item, 1, expected_price_lbp=PRICE)],
        pickup_day=tx.today,
        source=OrderSource.SEARCH,
        idempotency_key=key,
    )


def split(results: list[Any]) -> tuple[list[Any], list[ServiceError]]:
    """What succeeded, and the refusals. Anything else is a real failure."""
    refused = [result for result in results if isinstance(result, ServiceError)]
    for result in results:
        if isinstance(result, Exception) and not isinstance(result, ServiceError):
            raise result
    return [result for result in results if not isinstance(result, Exception)], refused


def item_row(arena: Arena, item: uuid.UUID) -> Any:
    return arena.one("SELECT * FROM inventory_items WHERE id = :id", id=item)


class TestTheLastBox:
    def test_two_clients_tap_reserve_on_the_last_box(self, arena: Arena) -> None:
        """FR-1: one gets it, the other is told it is gone. Never both."""
        item = arena.make.item(days_left=60, qty_on_hand=1)
        first, second = arena.make.client(), arena.make.client()

        won, refused = split(
            arena.together(
                tap_reserve(first, item), tap_reserve(second, item), hold="inventory_items"
            )
        )

        assert len(won) == 1
        assert [error.code for error in refused] == [Code.NOT_ENOUGH_STOCK]
        assert item_row(arena, item).qty_reserved == 1
        assert (
            arena.one("SELECT count(*) AS n FROM orders WHERE inventory_item_id = :i", i=item).n
            == 1
        )

    def test_one_client_cancels_while_another_reserves(self, arena: Arena) -> None:
        """Whichever comes first, the box is never promised twice, and never lost."""
        item = arena.make.item(days_left=60, qty_on_hand=1)
        holder, hopeful = arena.make.client(), arena.make.client()
        (held,) = arena.run(tap_reserve(holder, item))

        results = arena.together(
            lambda tx: orders.cancel_by_client(tx, holder, held.id),
            tap_reserve(hopeful, item),
            hold="inventory_items",
        )

        _, refused = split(results)
        assert not isinstance(results[0], Exception)  # the cancel always goes through
        open_orders = arena.all(
            "SELECT client_id FROM orders WHERE inventory_item_id = :i AND state = 'RESERVED'",
            i=item,
        )
        if refused:  # the reserve came first: the box was still held
            assert [error.code for error in refused] == [Code.NOT_ENOUGH_STOCK]
            assert open_orders == []
        else:
            assert [row.client_id for row in open_orders] == [hopeful]
        assert item_row(arena, item).qty_reserved == len(open_orders)


class TestTheSameTapTwice:
    def test_a_double_tap_on_reserve_makes_one_order(self, arena: Arena) -> None:
        """FR-2: the same key gives the same order, even when both taps arrive together."""
        item = arena.make.item(days_left=60, qty_on_hand=5)
        client = arena.make.client()

        won, refused = split(
            arena.together(
                tap_reserve(client, item), tap_reserve(client, item), hold="client_profiles"
            )
        )

        assert refused == []
        assert {order.id for (order,) in won} == {won[0][0].id}
        assert item_row(arena, item).qty_reserved == 1
        assert (
            arena.one("SELECT count(*) AS n FROM notifications WHERE user_id = :c", c=client).n == 1
        )

    def test_two_tabs_cannot_go_past_the_open_orders_limit(self, arena: Arena) -> None:
        """FR-4, INV-3: a client with 4 open orders taps two different boxes at once."""
        client = arena.make.client()
        for number in range(4):
            arena.run(tap_reserve(client, arena.make.item(days_left=60), key=f"earlier-{number}"))
        one, other = arena.make.item(days_left=60), arena.make.item(days_left=60)

        won, refused = split(
            arena.together(
                tap_reserve(client, one, key="tab-1"),
                tap_reserve(client, other, key="tab-2"),
                hold="client_profiles",
            )
        )

        assert len(won) == 1
        assert [error.code for error in refused] == [Code.LIMIT_OPEN_ORDERS]
        open_orders = arena.one(
            "SELECT count(*) AS n FROM orders WHERE client_id = :c AND state = 'RESERVED'", c=client
        )
        assert open_orders.n == 5

    def test_two_clicks_on_picked_up_hand_over_one_box(self, arena: Arena) -> None:
        pharmacy = arena.make.pharmacy()
        item = arena.make.item(pharmacy_id=pharmacy, days_left=60, qty_on_hand=3)
        (order,) = arena.run(tap_reserve(arena.make.client(), item))

        def click(tx: Tx) -> Any:
            return counter.mark_picked_up(tx, pharmacy, order.id)

        won, refused = split(arena.together(click, click, hold="orders"))

        assert (len(won), len(refused)) == (1, 1)
        row = item_row(arena, item)
        assert (row.qty_on_hand, row.qty_reserved) == (2, 0)
        events = arena.all(
            "SELECT action FROM audit_events WHERE entity_id = :o AND action = 'order.picked_up'",
            o=order.id,
        )
        assert len(events) == 1  # INV-13


class TestOffers:
    def watch(self, arena: Arena, product: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
        client = arena.make.client()
        claim = arena.run(
            lambda tx: claims.create_watch(
                tx, client_id=client, product_id=product, location=HAMRA, source=ClaimSource.SEARCH
            )
        )
        return client, claim.id

    def group(self, arena: Arena, product: uuid.UUID) -> str:
        return arena.run(lambda tx: catalog.medicine_group(tx.session.get_one(Product, product)))

    def offers(self, arena: Arena, claim: uuid.UUID) -> list[Any]:
        return arena.all(
            "SELECT id, source FROM orders WHERE claim_id = :c AND state = 'OFFERED'", c=claim
        )

    def test_two_offers_for_one_need_accepted_at_once(self, arena: Arena) -> None:
        """INV-20, R-W3: matching and early release both found a box. The first accepted
        offer wins, and the other box goes back at once.
        """
        product = arena.make.product()
        client, claim = self.watch(arena, product)
        private = arena.make.pharmacy(lat=33.897, lon=35.483)
        arena.make.item(pharmacy_id=private, product_id=product, days_left=200, qty_on_hand=4)
        asked = arena.run(
            lambda tx: early_release.request_early_release(tx, claim_id=claim, idempotency_key="a")
        )
        ask = arena.one(
            "SELECT id FROM early_release_asks WHERE er_request_id = :r", r=asked.request_id
        )
        arena.run(
            lambda tx: early_release.accept_ask(tx, private, ask.id, qty=1, price_lbp=750_000)
        )
        arena.make.item(product_id=product, days_left=60, qty_on_hand=2)
        arena.run(lambda tx: matching.run_for_group(tx, self.group(arena, product)))
        offers = self.offers(arena, claim)
        assert sorted(offer.source for offer in offers) == ["early_release", "watch"]

        def accept(offer_id: uuid.UUID) -> Callable[[Tx], Any]:
            return lambda tx: orders.accept_offer(tx, client, offer_id, tx.today)

        won, refused = split(arena.together(*(accept(offer.id) for offer in offers), hold="orders"))

        assert len(won) == 1
        assert [error.code for error in refused] == [Code.OFFER_NOT_OPEN]
        states = [
            row.state for row in arena.all("SELECT state FROM orders WHERE claim_id = :c", c=claim)
        ]
        assert sorted(states) == ["OFFER_WITHDRAWN", "RESERVED"]
        assert arena.one("SELECT state FROM claims WHERE id = :c", c=claim).state == "FULFILLED"

    def test_two_matching_runs_make_one_offer(self, arena: Arena) -> None:
        """FR-13: one allocator per medicine at a time."""
        product = arena.make.product()
        _, claim = self.watch(arena, product)
        arena.make.item(product_id=product, days_left=60, qty_on_hand=5)
        group = self.group(arena, product)

        def allocate(tx: Tx) -> int:
            return matching.run_for_group(tx, group)

        won, refused = split(arena.together(allocate, allocate, hold="claims"))

        assert refused == []
        assert sorted(won) == [0, 1]
        offers = arena.all(
            "SELECT id FROM orders WHERE claim_id = :c AND state = 'OFFERED'", c=claim
        )
        assert len(offers) == 1

    def test_a_double_tap_on_accept_reserves_once(self, arena: Arena) -> None:
        product = arena.make.product()
        client, claim = self.watch(arena, product)
        item = arena.make.item(product_id=product, days_left=60, qty_on_hand=5)
        arena.run(lambda tx: matching.run_for_group(tx, self.group(arena, product)))
        offer = arena.one(
            "SELECT id FROM orders WHERE claim_id = :c AND state = 'OFFERED'", c=claim
        )

        def accept(tx: Tx) -> Any:
            return orders.accept_offer(tx, client, offer.id, tx.today)

        won, refused = split(arena.together(accept, accept, hold="orders"))

        assert len(won) == 1
        assert [error.code for error in refused] == [Code.OFFER_NOT_OPEN]
        assert item_row(arena, item).qty_reserved == 1


class SlowMailer:
    """Takes a moment to send, so a second worker arrives while the first is still busy."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, to: str, subject: str, body: str) -> None:
        time.sleep(0.3)
        self.sent.append(to)


class TestTheWorker:
    def test_two_workers_never_send_the_same_email(self, arena: Arena) -> None:
        client, mailer = arena.make.client(), SlowMailer()
        arena.run(
            lambda tx: notify(tx, client, Template.WATCH_ENDED, {"product": "Testol"}, event="race")
        )
        outbox = arena.one("SELECT id FROM email_outbox WHERE user_id = :c", c=client)

        def send(tx: Tx) -> email.Outcome:
            return email.send_one(tx, mailer, outbox.id)

        outcomes = arena.together(send, send, hold="email_outbox")

        assert sorted(outcomes) == [email.Outcome.NOTHING, email.Outcome.SENT]
        assert len(mailer.sent) == 1
        assert (
            arena.one("SELECT state FROM email_outbox WHERE id = :o", o=outbox.id).state == "SENT"
        )

    def test_the_purge_runs_with_the_real_retention_login(self, arena: Arena) -> None:
        """The login the worker really uses: it may delete old rows, and the app may not."""
        client = arena.make.client()
        arena.write("DELETE FROM app_state WHERE key = 'daily_tasks_last_run'")
        for key, age_days in (("old", 91), ("recent", 1)):
            arena.write(
                "INSERT INTO notifications (user_id, type, dedupe_key, created_at) "
                "VALUES (:c, 'CN-3', :key, :at)",
                c=client,
                key=f"{client}:{key}",
                at=NOW - timedelta(days=age_days),
            )
        retention = create_engine(arena.urls.retention)
        try:
            tasks = ClockTasks(
                arena.sessions,
                arena.clock,
                retention_sessions=sessionmaker(retention, expire_on_commit=False),
            )

            assert tasks.run_daily_tasks() >= 1
            assert tasks.run_daily_tasks() == 0  # once a day
        finally:
            retention.dispose()

        left = arena.all("SELECT dedupe_key FROM notifications WHERE user_id = :c", c=client)
        assert [row.dedupe_key for row in left] == [f"{client}:recent"]

    def test_a_follow_up_that_fails_never_undoes_the_work(
        self, arena: Arena, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The reservation is committed before its follow-up work runs. If that work fails,
        the client still has the box, the failure is logged, and the rest still runs.
        """
        item = arena.make.item(days_left=60, qty_on_hand=2)
        client = arena.make.client()
        ran: list[str] = []

        def broken(_: Tx) -> None:
            raise RuntimeError("the follow-up broke")

        with unit_of_work(arena.sessions, arena.clock) as tx:
            tap_reserve(client, item)(tx)
            tx.defer("first", broken)
            tx.defer("second", lambda _: ran.append("second"))

        assert item_row(arena, item).qty_reserved == 1
        assert ran == ["second"]
        assert len(logged(caplog, "deferred_action_failed")) == 1


def test_the_catalog_import_ends_what_became_controlled(arena: Arena) -> None:
    """FR-24: the import command's last step, run the way the command runs it."""
    product = arena.make.product()
    item = arena.make.item(product_id=product, days_left=60, qty_on_hand=2)
    client = arena.make.client()
    (order,) = arena.run(tap_reserve(client, item))
    arena.write("UPDATE products SET controlled = true WHERE id = :p", p=product)
    settings = Settings(database_url=arena.urls.app, website_url="http://localhost:5173")

    withdrawn = close_what_became_controlled(settings)

    assert withdrawn.orders == 1
    state = arena.one("SELECT state FROM orders WHERE id = :o", o=order.id).state
    assert state == "CANCELLED_BY_SYSTEM"
    assert item_row(arena, item).qty_reserved == 0


class TestTheClockAgainstATap:
    """The clock check acts at a deadline while someone taps just before it (FR-7, FR-10).

    Each action runs at its own time: the tap a second before the deadline, the clock
    check at the deadline. Both are inside open transactions before either continues.
    """

    def test_a_no_show_against_picked_up_a_second_before(self, arena: Arena) -> None:
        pharmacy = arena.make.pharmacy()
        item = arena.make.item(pharmacy_id=pharmacy, days_left=60, qty_on_hand=3)
        (order,) = arena.run(tap_reserve(arena.make.client(), item))
        deadline = order.deadline

        results = arena.together(
            arena.when(deadline, lambda tx: orders.expire_no_show(tx, order.id)),
            arena.when(
                deadline - timedelta(seconds=1),
                lambda tx: counter.mark_picked_up(tx, pharmacy, order.id),
            ),
            hold="orders",
        )

        split(results)
        state = arena.one("SELECT state FROM orders WHERE id = :o", o=order.id).state
        row = item_row(arena, item)
        if state == "PICKED_UP":
            assert results[0] is None  # the clock check found nothing left to do
            assert (row.qty_on_hand, row.qty_reserved) == (2, 0)
        else:
            assert state == "EXPIRED_NO_SHOW"
            assert isinstance(results[1], ServiceError)
            assert (row.qty_on_hand, row.qty_reserved) == (3, 0)

    def test_a_no_show_against_the_same_client_reserving_the_same_box(self, arena: Arena) -> None:
        """Both paths lock the client, then the box, then the order: no deadlock, and the
        box is never promised twice.
        """
        item = arena.make.item(days_left=60, qty_on_hand=1)
        client = arena.make.client()
        (order,) = arena.run(tap_reserve(client, item))
        deadline = order.deadline

        def reserve_again(tx: Tx) -> Any:
            # At closing time the pharmacy takes no pickup today: the next open day.
            return orders.reserve(
                tx,
                client_id=client,
                lines=[ReserveLine(item, 1, expected_price_lbp=PRICE)],
                pickup_day=tx.today + timedelta(days=1),
                source=OrderSource.SEARCH,
                idempotency_key="again",
            )

        results = arena.together(
            arena.when(deadline, lambda tx: orders.expire_no_show(tx, order.id)),
            arena.when(deadline, reserve_again),
            hold="inventory_items",
        )

        _, refused = split(results)
        assert arena.one("SELECT state FROM orders WHERE id = :o", o=order.id).state == (
            "EXPIRED_NO_SHOW"
        )
        reserved = arena.all(
            "SELECT id FROM orders WHERE inventory_item_id = :i AND state = 'RESERVED'", i=item
        )
        if refused:  # the tap came first: the box was still held
            assert [error.code for error in refused] == [Code.NOT_ENOUGH_STOCK]
            assert reserved == []
        else:
            assert len(reserved) == 1
        assert item_row(arena, item).qty_reserved == len(reserved)

    def test_an_offer_expiring_against_accept_a_second_before(self, arena: Arena) -> None:
        """FR-7."""
        product = arena.make.product()
        client = arena.make.client()
        claim = arena.run(
            lambda tx: claims.create_watch(
                tx, client_id=client, product_id=product, location=HAMRA, source=ClaimSource.SEARCH
            )
        )
        item = arena.make.item(product_id=product, days_left=60, qty_on_hand=2)
        group = arena.run(lambda tx: catalog.medicine_group(tx.session.get_one(Product, product)))
        arena.run(lambda tx: matching.run_for_group(tx, group))
        offer = arena.one(
            "SELECT id, offer_expires_at FROM orders WHERE claim_id = :c AND state = 'OFFERED'",
            c=claim.id,
        )
        expires = offer.offer_expires_at

        results = arena.together(
            arena.when(expires, lambda tx: orders.end_offer(tx, offer.id)),
            arena.when(
                expires - timedelta(seconds=1),
                lambda tx: orders.accept_offer(tx, client, offer.id, tx.today),
            ),
            hold="orders",
        )

        _, refused = split(results)
        state = arena.one("SELECT state FROM orders WHERE id = :o", o=offer.id).state
        if refused:  # the offer expired first
            assert [error.code for error in refused] == [Code.OFFER_NOT_OPEN]
            assert state == "OFFER_EXPIRED"
            assert item_row(arena, item).qty_reserved == 0
        else:
            assert state == "RESERVED"
            assert results[0] is None
            assert item_row(arena, item).qty_reserved == 1
