"""Reserving, cancelling and the pharmacy's counter (docs/04 SM-5 O1 to O6, R-L, R-F)."""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from dawalink.domain.orders import OrderSource
from dawalink.services import counter, orders
from dawalink.services.errors import Code, ServiceError
from dawalink.services.orders import ReserveLine
from tests.db.factories import NOW, TODAY
from tests.services.conftest import World

DAY = timedelta(days=1)
# The default pharmacy closes at 21:00 in Beirut, which is 18:00 UTC in October.
CLOSING_TODAY = datetime(2026, 10, 20, 18, 0, tzinfo=UTC)


@dataclass
class Shop:
    """A client, a pharmacy and one visible box of a 1,000,000 LBP medicine."""

    world: World
    client: uuid.UUID
    pharmacy: uuid.UUID
    owner: uuid.UUID
    product: uuid.UUID
    item: uuid.UUID

    def line(self, qty: int = 1, **values: Any) -> ReserveLine:
        asked: dict[str, Any] = {"item_id": self.item, "qty": qty, "expected_price_lbp": 600_000}
        return ReserveLine(**(asked | values))

    def reserve(self, qty: int = 1, *, key: str = "tap-1", **values: Any) -> Any:
        """One tap on [Reserve]; returns the order row as the database has it."""
        pickup_day = values.pop("pickup_day", TODAY)
        source = values.pop("source", OrderSource.SEARCH)
        client = values.pop("client_id", self.client)
        tx = self.world.tx()
        (order,) = orders.reserve(
            tx,
            client_id=client,
            lines=[self.line(qty, **values)],
            pickup_day=pickup_day,
            source=source,
            idempotency_key=key,
        )
        self.world.settle(tx)
        return self.order(order.id)

    def order(self, order_id: uuid.UUID) -> Any:
        return self.world.one("SELECT * FROM orders WHERE id = :id", id=order_id)

    def stock(self, item: uuid.UUID | None = None) -> tuple[int, int]:
        row = self.world.one(
            "SELECT qty_on_hand, qty_reserved FROM inventory_items WHERE id = :id",
            id=item or self.item,
        )
        return (row.qty_on_hand, row.qty_reserved)


@pytest.fixture
def shop(world: World) -> Shop:
    owner = world.make.user("pharmacist")
    pharmacy = world.make.pharmacy(owner_user_id=owner)
    product = world.make.product(equivalence_key="paracetamol=500mg | tablet | N02BE01")
    return Shop(
        world,
        client=world.make.client(),
        pharmacy=pharmacy,
        owner=owner,
        product=product,
        item=world.make.item(pharmacy_id=pharmacy, product_id=product, days_left=60, qty_on_hand=5),
    )


def refusal(action: Any) -> ServiceError:
    with pytest.raises(ServiceError) as refused:
        action()
    return refused.value


def reconciled(world: World) -> None:
    """INV-2: every item's reserved units equal the units its open orders hold."""
    broken = world.all(
        "SELECT ii.id FROM inventory_items ii "
        "LEFT JOIN orders o ON o.inventory_item_id = ii.id AND o.state IN ('OFFERED', 'RESERVED') "
        "GROUP BY ii.id HAVING ii.qty_reserved <> COALESCE(SUM(o.qty_locked), 0)"
    )
    assert broken == []


class TestReserve:
    def test_a_tap_reserves_the_box_at_once(self, shop: Shop, world: World) -> None:
        """O1: no pharmacy confirmation step."""
        order = shop.reserve(2, days_of_use=12)

        assert order.state == "RESERVED"
        assert re.fullmatch(r"R-[2-9A-HJ-NP-Z]{6}", order.ref)
        assert (order.qty_requested, order.qty_locked) == (2, 2)
        assert order.price_snapshot_lbp == 600_000  # 60 days left: 40% off 1,000,000
        assert (order.pickup_day, order.days_of_use) == (TODAY, 12)
        assert order.deadline == CLOSING_TODAY
        assert order.reserved_at == NOW
        assert order.equivalence_key == "paracetamol=500mg | tablet | N02BE01"
        assert shop.stock() == (5, 2)
        reconciled(world)

    def test_the_pharmacy_and_the_client_are_told_and_one_audit_event_is_written(
        self, shop: Shop, world: World
    ) -> None:
        order = shop.reserve()

        assert world.notifications(shop.owner) == ["PN-4"]
        assert world.notifications(shop.client) == ["CN-3"]
        assert world.audit_actions(order.id) == ["order.reserve"]
        to_pharmacy = world.one(
            "SELECT payload FROM notifications WHERE user_id = :u", u=shop.owner
        )
        assert to_pharmacy.payload["order_ref"] == order.ref
        # INV-9: the pharmacy never learns who the client is.
        assert str(shop.client) not in str(to_pharmacy.payload)

    def test_the_same_tap_sent_twice_reserves_once(self, shop: Shop, world: World) -> None:
        """FR-2: a double tap or a network retry."""
        first = shop.reserve(key="tap-1")
        again = shop.reserve(key="tap-1")

        assert again.id == first.id
        assert shop.stock() == (5, 1)
        assert world.audit_actions(first.id) == ["order.reserve"]
        assert world.notifications(shop.owner) == ["PN-4"]

    def test_tomorrow_means_tomorrows_closing_time(self, shop: Shop) -> None:
        """R-T4."""
        order = shop.reserve(pickup_day=TODAY + DAY)

        assert order.deadline == CLOSING_TODAY + DAY

    def test_a_lower_price_is_taken_and_a_higher_one_stops_the_tap(self, shop: Shop) -> None:
        """API-D4: the client never pays more than they saw."""
        cheaper = shop.reserve(key="a", expected_price_lbp=700_000)

        went_up = refusal(lambda: shop.reserve(key="b", expected_price_lbp=599_000))

        assert cheaper.price_snapshot_lbp == 600_000
        assert went_up.code is Code.PRICE_CHANGED
        assert went_up.details == {"new_price": 600_000}
        assert shop.stock() == (5, 1)

    def test_more_units_than_are_left(self, shop: Shop) -> None:
        shop.reserve(3, key="a")

        short = refusal(lambda: shop.reserve(3, key="b", client_id=shop.world.make.client()))

        assert short.code is Code.NOT_ENOUGH_STOCK
        assert short.details == {"available": 2}

    def test_a_box_that_does_not_last_the_days_of_use(self, shop: Shop, world: World) -> None:
        """R-F1, INV-25: the fit is checked at the tap too."""
        short = world.make.item(pharmacy_id=shop.pharmacy, product_id=shop.product, days_left=5)

        error = refusal(
            lambda: shop.reserve(item_id=short, days_of_use=12, expected_price_lbp=400_000)
        )

        assert error.code is Code.DOES_NOT_FIT
        assert error.details == {
            "expiry_date": TODAY + 5 * DAY,
            "last_day_of_use": TODAY + 11 * DAY,
        }

    def test_the_owners_example_at_the_tap(self, world: World, shop: Shop) -> None:
        """R-F6: 7 days left, 7 days of use: fine tomorrow, too late on the third day."""
        three_days = world.make.pharmacy(pickup_days=3)
        box = world.make.item(pharmacy_id=three_days, product_id=shop.product, days_left=7)
        line = {"item_id": box, "days_of_use": 7, "expected_price_lbp": 400_000}

        late = refusal(lambda: shop.reserve(key="late", pickup_day=TODAY + 2 * DAY, **line))
        in_time = shop.reserve(key="ok", pickup_day=TODAY + DAY, **line)

        assert late.code is Code.DOES_NOT_FIT
        assert in_time.state == "RESERVED"

    @pytest.mark.parametrize("ahead", [-1, 2, 9])
    def test_a_pickup_day_the_pharmacy_does_not_accept(self, shop: Shop, ahead: int) -> None:
        """R-F3: this pharmacy holds a reservation for one open day."""
        error = refusal(lambda: shop.reserve(pickup_day=TODAY + ahead * DAY))

        assert error.code is Code.PICKUP_DAY_INVALID

    def test_today_is_refused_within_an_hour_of_closing(self, shop: Shop, world: World) -> None:
        """N-42."""
        world.later(hours=10, minutes=1)  # 20:01

        today = refusal(lambda: shop.reserve(key="a", pickup_day=TODAY))
        tomorrow = shop.reserve(key="b", pickup_day=TODAY + DAY)

        assert today.code is Code.PICKUP_DAY_INVALID
        assert tomorrow.state == "RESERVED"

    def test_a_reservation_can_be_made_while_the_pharmacy_is_closed(
        self, shop: Shop, world: World
    ) -> None:
        world.later(hours=13)  # 23:00

        order = shop.reserve(pickup_day=TODAY + DAY)

        assert order.deadline == CLOSING_TODAY + DAY

    @pytest.mark.parametrize(
        ("change", "code"),
        [
            ("UPDATE inventory_items SET listing_control = 'PAUSED'", Code.LISTING_NOT_AVAILABLE),
            ("UPDATE pharmacies SET status = 'SUSPENDED'", Code.LISTING_NOT_AVAILABLE),
            ("UPDATE products SET controlled = true", Code.LISTING_NOT_AVAILABLE),
            (
                "UPDATE inventory_items SET expiry_date = DATE '2026-10-19'",
                Code.LISTING_NOT_AVAILABLE,
            ),
        ],
    )
    def test_what_is_no_longer_visible_cannot_be_reserved(
        self, shop: Shop, world: World, change: str, code: Code
    ) -> None:
        """INV-16, INV-6."""
        with world.as_owner():
            world.connection.exec_driver_sql(change)

        assert refusal(shop.reserve).code is code

    @pytest.mark.parametrize(
        ("status", "values", "code"),
        [
            ("UNVERIFIED", {}, Code.EMAIL_NOT_VERIFIED),
            ("PAUSED", {"paused_until": NOW + DAY}, Code.CLIENT_PAUSED),
            ("SUSPENDED", {}, Code.ACCOUNT_SUSPENDED),
        ],
    )
    def test_only_an_active_client_reserves(
        self, shop: Shop, world: World, status: str, values: dict[str, Any], code: Code
    ) -> None:
        """SM-2."""
        client = world.make.client(status, **values)

        assert refusal(lambda: shop.reserve(client_id=client)).code is code

    @pytest.mark.parametrize("qty", [0, 4])
    def test_a_quantity_is_one_to_three(self, shop: Shop, qty: int) -> None:
        assert refusal(lambda: shop.reserve(qty)).code is Code.VALIDATION_ERROR


class TestLimits:
    def test_five_open_orders_at_most(self, shop: Shop, world: World) -> None:
        """R-L1, INV-3."""
        for number in range(5):
            other = world.make.item(pharmacy_id=shop.pharmacy, product_id=world.make.product())
            shop.reserve(key=f"tap-{number}", item_id=other)

        sixth = refusal(lambda: shop.reserve(key="tap-6"))

        assert sixth.code is Code.LIMIT_OPEN_ORDERS
        assert shop.stock() == (5, 0)

    def test_three_units_of_the_same_medicine_at_most_across_brands(
        self, shop: Shop, world: World
    ) -> None:
        """R-L2: another brand of the same medicine counts too."""
        other_brand = world.make.product(equivalence_key="paracetamol=500mg | tablet | N02BE01")
        other_box = world.make.item(pharmacy_id=shop.pharmacy, product_id=other_brand)
        shop.reserve(2, key="a")

        too_many = refusal(lambda: shop.reserve(2, key="b", item_id=other_box))
        allowed = shop.reserve(1, key="c", item_id=other_box)

        assert too_many.code is Code.LIMIT_GROUP_UNITS
        assert allowed.state == "RESERVED"

    def test_products_without_a_key_are_never_lumped_together(
        self, shop: Shop, world: World
    ) -> None:
        """A product with no "same medicine" key is a group of its own."""
        boxes = [
            world.make.item(pharmacy_id=shop.pharmacy, product_id=world.make.product())
            for _ in range(2)
        ]

        for number, box in enumerate(boxes):
            assert shop.reserve(3, key=f"k{number}", item_id=box).state == "RESERVED"

    def test_a_closed_order_frees_its_place(self, shop: Shop, world: World) -> None:
        first = shop.reserve(3, key="a")
        full = refusal(lambda: shop.reserve(1, key="b"))
        tx = world.tx()
        orders.cancel_by_client(tx, shop.client, first.id)
        world.settle(tx)

        assert full.code is Code.LIMIT_GROUP_UNITS
        assert shop.reserve(1, key="c").state == "RESERVED"


class TestGroupReserve:
    """R-RQ6: a plan card reserves all its ticked items, or none."""

    def lines(self, shop: Shop, world: World) -> list[ReserveLine]:
        other = world.make.item(
            pharmacy_id=shop.pharmacy, product_id=world.make.product(), qty_on_hand=1
        )
        return [shop.line(1), shop.line(1, item_id=other)]

    def group(self, shop: Shop, lines: list[ReserveLine], key: str = "card-1") -> list[Any]:
        tx = shop.world.tx()
        made = orders.reserve(
            tx,
            client_id=shop.client,
            lines=lines,
            pickup_day=TODAY,
            source=OrderSource.ASSISTANT,
            idempotency_key=key,
        )
        shop.world.settle(tx)
        return [shop.order(order.id) for order in made]

    def test_every_item_is_reserved_with_one_key_each(self, shop: Shop, world: World) -> None:
        lines = self.lines(shop, world)

        first, second = self.group(shop, lines)

        assert first.group_id == second.group_id is not None
        assert (first.idempotency_key, second.idempotency_key) == ("card-1:1", "card-1:2")
        assert world.notifications(shop.owner) == ["PN-4", "PN-4"]
        assert [o.id for o in self.group(shop, lines)] == [first.id, second.id]
        reconciled(world)

    def test_if_one_item_fails_nothing_is_reserved(self, shop: Shop, world: World) -> None:
        """FR-3."""
        lines = self.lines(shop, world)
        taken = lines[1].item_id
        shop.reserve(key="someone-else", item_id=taken, client_id=world.make.client())

        error = refusal(lambda: self.group(shop, lines))

        assert error.code is Code.GROUP_ITEM_FAILED
        assert error.details["failed_items"] == [
            {"item_id": taken, "request_item_id": None, "code": "NOT_ENOUGH_STOCK", "available": 0}
        ]
        assert shop.stock() == (5, 0)
        assert world.all("SELECT 1 FROM orders WHERE client_id = :c", c=shop.client) == []


class TestConversationRouting:
    def test_a_search_order_never_reaches_the_chat(self, shop: Shop, world: World) -> None:
        """R-AG5."""
        chat = world.make.conversation(client_id=shop.client)

        shop.reserve(source=OrderSource.SEARCH)

        assert world.all("SELECT 1 FROM chat_messages WHERE conversation_id = :c", c=chat) == []

    def test_an_assistant_order_posts_a_card_and_asks_for_no_turn(
        self, shop: Shop, world: World
    ) -> None:
        """R-AG3: reserved is informational."""
        chat = world.make.conversation(client_id=shop.client)

        order = shop.reserve(source=OrderSource.ASSISTANT)

        message = world.one("SELECT * FROM chat_messages WHERE conversation_id = :c", c=chat)
        assert (message.kind, message.cards[0]["template"]) == ("card", "reserved")
        assert message.cards[0]["order_ref"] == order.ref
        pending = world.one("SELECT pending_turn_at FROM conversations WHERE id = :c", c=chat)
        assert pending.pending_turn_at is None


class TestClientCancel:
    def cancel(self, shop: Shop, order_id: uuid.UUID, client: uuid.UUID | None = None) -> Any:
        tx = shop.world.tx()
        orders.cancel_by_client(tx, client or shop.client, order_id)
        shop.world.settle(tx)
        return shop.order(order_id)

    def test_cancelling_releases_the_box_and_tells_the_pharmacy(
        self, shop: Shop, world: World
    ) -> None:
        """O5: no penalty."""
        order = shop.reserve(2)

        cancelled = self.cancel(shop, order.id)

        assert (cancelled.state, cancelled.close_reason) == ("CANCELLED_BY_CLIENT", "client_cancel")
        assert (cancelled.qty_locked, cancelled.counts_as_no_show) == (0, False)
        assert cancelled.closed_at == NOW
        assert shop.stock() == (5, 0)
        assert world.notifications(shop.owner) == ["PN-4", "PN-8"]
        assert world.audit_actions(order.id) == ["order.reserve", "order.cancel"]
        reconciled(world)

    def test_it_cannot_be_cancelled_twice_or_after_the_deadline(
        self, shop: Shop, world: World
    ) -> None:
        first, second = shop.reserve(key="a"), shop.reserve(key="b")
        self.cancel(shop, first.id)
        world.later(hours=11)

        assert refusal(lambda: self.cancel(shop, first.id)).code is Code.RESERVATION_NOT_ACTIVE
        assert refusal(lambda: self.cancel(shop, second.id)).code is Code.RESERVATION_NOT_ACTIVE

    def test_someone_elses_reservation_does_not_exist(self, shop: Shop, world: World) -> None:
        order = shop.reserve()

        error = refusal(lambda: self.cancel(shop, order.id, client=world.make.client()))

        assert error.code is Code.NOT_FOUND
        assert shop.order(order.id).state == "RESERVED"


class TestAtTheCounter:
    def test_picked_up_takes_the_units_off_the_shelf(self, shop: Shop, world: World) -> None:
        """O2."""
        order = shop.reserve(2)
        world.later(hours=3)

        counter.mark_picked_up(world.tx(), shop.pharmacy, order.id)

        done = shop.order(order.id)
        assert (done.state, done.qty_picked_up, done.qty_locked) == ("PICKED_UP", 2, 0)
        assert done.closed_at == NOW + timedelta(hours=3)
        assert shop.stock() == (3, 0)
        assert world.audit_actions(order.id) == ["order.reserve", "order.picked_up"]
        reconciled(world)

    def test_a_second_click_finds_it_already_done(self, shop: Shop, world: World) -> None:
        """FR-8, INV-7."""
        order = shop.reserve()
        counter.mark_picked_up(world.tx(), shop.pharmacy, order.id)

        again = refusal(lambda: counter.mark_picked_up(world.tx(), shop.pharmacy, order.id))

        assert again.code is Code.RESERVATION_NOT_ACTIVE
        assert again.details == {"state": "PICKED_UP"}
        assert shop.stock() == (4, 0)

    def test_there_is_no_late_pickup(self, shop: Shop, world: World) -> None:
        """FR-9: at the deadline itself it is already too late."""
        order = shop.reserve()
        world.later(hours=11)

        late = refusal(lambda: counter.mark_picked_up(world.tx(), shop.pharmacy, order.id))

        assert late.code is Code.PICKUP_DEADLINE_PASSED
        assert shop.order(order.id).state == "RESERVED"

    def test_another_pharmacy_cannot_see_or_touch_it(self, shop: Shop, world: World) -> None:
        order = shop.reserve()
        other = world.make.pharmacy()

        error = refusal(lambda: counter.mark_picked_up(world.tx(), other, order.id))

        assert error.code is Code.NOT_FOUND
        assert counter.find_by_number(world.tx(), other, order.ref) is None

    def test_the_order_number_is_found_however_it_is_typed(self, shop: Shop, world: World) -> None:
        order = shop.reserve()

        found = counter.find_by_number(
            world.tx(), shop.pharmacy, order.ref.lower().replace("-", " ")
        )

        assert found is not None
        assert found.id == order.id
        assert counter.find_by_number(world.tx(), shop.pharmacy, "not a number") is None

    def test_a_suspended_pharmacy_still_hands_over_what_was_reserved(
        self, shop: Shop, world: World
    ) -> None:
        """SM-1: reserved orders are kept and can still be picked up."""
        order = shop.reserve()
        with world.as_owner():
            world.connection.exec_driver_sql("UPDATE pharmacies SET status = 'SUSPENDED'")

        counter.mark_picked_up(world.tx(), shop.pharmacy, order.id)

        assert shop.order(order.id).state == "PICKED_UP"

    def test_all_units_not_available_ends_the_reservation_without_a_penalty(
        self, shop: Shop, world: World
    ) -> None:
        """O3, R-N2."""
        order = shop.reserve(2)

        counter.mark_not_available(world.tx(), shop.pharmacy, order.id)

        ended = shop.order(order.id)
        assert (ended.state, ended.close_reason) == ("NOT_AVAILABLE", "not_available")
        assert (ended.qty_locked, ended.counts_as_no_show) == (0, False)
        # The units weren't there: they leave the shelf count too.
        assert shop.stock() == (3, 0)
        assert world.notifications(shop.client) == ["CN-3", "CN-5"]
        reconciled(world)

    def test_some_units_not_available_keeps_the_rest_reserved(
        self, shop: Shop, world: World
    ) -> None:
        order = shop.reserve(3)

        counter.mark_not_available(world.tx(), shop.pharmacy, order.id, 1)
        counter.mark_not_available(world.tx(), shop.pharmacy, order.id, 1)

        kept = shop.order(order.id)
        assert (kept.state, kept.qty_locked) == ("RESERVED", 1)
        assert shop.stock() == (3, 1)
        # One notification per mark, and one audit event per mark.
        assert world.notifications(shop.client) == ["CN-3", "CN-5", "CN-5"]
        assert world.audit_actions(order.id) == [
            "order.reserve",
            "order.not_available",
            "order.not_available",
        ]
        reconciled(world)

    @pytest.mark.parametrize("units", [0, 3])
    def test_units_must_be_between_one_and_the_units_held(
        self, shop: Shop, world: World, units: int
    ) -> None:
        order = shop.reserve(2)

        error = refusal(
            lambda: counter.mark_not_available(world.tx(), shop.pharmacy, order.id, units)
        )

        assert error.code is Code.UNITS_INVALID
        assert shop.stock() == (5, 2)

    def test_in_a_chat_not_available_wakes_the_agent(self, shop: Shop, world: World) -> None:
        """R-AG4: a decision event, so the agent can look elsewhere."""
        chat = world.make.conversation(client_id=shop.client)
        order = shop.reserve(source=OrderSource.ASSISTANT)

        counter.mark_not_available(world.tx(), shop.pharmacy, order.id)

        kinds = world.all(
            "SELECT kind FROM chat_messages WHERE conversation_id = :c ORDER BY seq", c=chat
        )
        assert [k.kind for k in kinds] == ["card", "card", "event"]
        pending = world.one("SELECT pending_turn_at FROM conversations WHERE id = :c", c=chat)
        assert pending.pending_turn_at == NOW

    def test_from_the_search_page_it_does_not(self, shop: Shop, world: World) -> None:
        """R-AG5: the search baseline stays agent-free."""
        chat = world.make.conversation(client_id=shop.client)
        order = shop.reserve(source=OrderSource.SEARCH)

        counter.mark_not_available(world.tx(), shop.pharmacy, order.id)

        assert world.all("SELECT 1 FROM chat_messages WHERE conversation_id = :c", c=chat) == []


class TestSystemCancel:
    def test_the_system_ends_an_open_order_and_tells_the_client(
        self, shop: Shop, world: World
    ) -> None:
        """O6."""
        order = shop.reserve(2)
        tx = world.tx()

        orders.cancel_by_system(tx, order.id, reason="the product became controlled")
        world.settle(tx)

        ended = shop.order(order.id)
        assert (ended.state, ended.close_reason, ended.qty_locked) == (
            "CANCELLED_BY_SYSTEM",
            "system",
            0,
        )
        assert shop.stock() == (5, 0)
        assert world.notifications(shop.client) == ["CN-3", "CN-12"]
        assert orders.cancel_by_system(world.tx(), order.id, reason="again") is None
        reconciled(world)
