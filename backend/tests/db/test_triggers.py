"""The three triggers that guard what must never break (docs/05 §4; INV-4, INV-5, INV-15)."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, delete, insert, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from dawalink.db.models import AuditEvent, InventoryItem, Order
from dawalink.domain.orders import OPEN_STATES, OrderState
from tests.db import factories as make
from tests.db.factories import NOW

TERMINAL = sorted(state.value for state in OrderState if state not in OPEN_STATES)


def refused(db: Connection, action: Callable[[], Any], message: str) -> None:
    with pytest.raises(IntegrityError, match=message), db.begin_nested():
        action()


def change(db: Connection, order: Any, **values: Any) -> None:
    db.execute(update(Order).where(Order.id == order).values(**values))


class TestOrdersGuard:
    @pytest.mark.parametrize("state", TERMINAL)
    def test_a_finished_order_never_changes(self, db: Connection, state: str) -> None:
        """INV-4, for every one of the eight final states."""
        order = make.order(db, state)

        refused(db, lambda: change(db, order, state="RESERVED", qty_locked=1), "finished order")
        refused(db, lambda: change(db, order, close_reason="system"), "finished order")
        refused(db, lambda: change(db, order, qty_requested=2), "finished order")

    def test_an_open_order_can_move_on(self, db: Connection) -> None:
        order = make.order(db, "RESERVED")

        change(db, order, state="PICKED_UP", qty_locked=0, qty_picked_up=1, closed_at=NOW)

        assert (
            db.execute(text("SELECT state FROM orders WHERE id = :id"), {"id": order}).scalar()
            == "PICKED_UP"
        )

    @pytest.mark.parametrize("state", ["OFFERED", "RESERVED"])
    def test_the_price_snapshot_never_changes(self, db: Connection, state: str) -> None:
        """INV-5."""
        order = make.order(db, state)

        refused(db, lambda: change(db, order, price_snapshot_lbp=1), "price snapshot")

    def test_a_deadline_never_changes_once_set(self, db: Connection) -> None:
        """INV-15."""
        order = make.order(db, "RESERVED")

        refused(db, lambda: change(db, order, deadline=NOW + timedelta(days=3)), "deadline")
        refused(
            db,
            lambda: change(db, order, deadline=None, state="OFFERED", offer_expires_at=NOW),
            "deadline",
        )

    def test_an_offer_gets_its_deadline_when_it_is_accepted(self, db: Connection) -> None:
        order = make.order(db, "OFFERED")

        change(db, order, state="RESERVED", deadline=NOW + timedelta(hours=11), reserved_at=NOW)

    def test_a_no_show_can_be_contested_once_and_then_cleared(self, db: Connection) -> None:
        """The one exception to INV-4 (R-N3)."""
        order = make.order(db, "EXPIRED_NO_SHOW", counts_as_no_show=True)

        change(db, order, contested_at=NOW)
        refused(
            db, lambda: change(db, order, contested_at=NOW + timedelta(hours=1)), "finished order"
        )
        change(db, order, counts_as_no_show=False)
        refused(db, lambda: change(db, order, counts_as_no_show=True), "finished order")

    def test_contesting_changes_nothing_else(self, db: Connection) -> None:
        order = make.order(db, "EXPIRED_NO_SHOW", counts_as_no_show=True)

        refused(db, lambda: change(db, order, contested_at=NOW, qty_requested=3), "finished order")
        refused(
            db,
            lambda: change(db, order, contested_at=NOW, state="PICKED_UP", qty_picked_up=1),
            "finished order",
        )

    def test_only_a_no_show_can_be_contested(self, db: Connection) -> None:
        order = make.order(db, "CANCELLED_BY_CLIENT")

        refused(db, lambda: change(db, order, contested_at=NOW), "finished order")


class TestPriceOverride:
    def test_a_pharmacys_price_is_never_above_the_public_price(self, db: Connection) -> None:
        """INV-5, R-PR1."""
        product = make.product(db, public_price_lbp=500_000)

        refused(
            db,
            lambda: make.item(db, product_id=product, price_override_lbp=500_001),
            "above the public price",
        )
        item = make.item(db, product_id=product, price_override_lbp=500_000)
        refused(
            db,
            lambda: db.execute(
                update(InventoryItem)
                .where(InventoryItem.id == item)
                .values(price_override_lbp=900_000)
            ),
            "above the public price",
        )

    def test_a_free_item_and_no_override_are_both_allowed(self, db: Connection) -> None:
        product = make.product(db, public_price_lbp=500_000)

        make.item(db, product_id=product, price_override_lbp=0)  # a donation (P-D7)
        make.item(db, product_id=product, price_override_lbp=None)

    def test_moving_an_item_to_a_cheaper_product_is_checked_too(self, db: Connection) -> None:
        dear, cheap = (
            make.product(db, public_price_lbp=900_000),
            make.product(db, public_price_lbp=100_000),
        )
        item = make.item(db, product_id=dear, price_override_lbp=800_000)

        refused(
            db,
            lambda: db.execute(
                update(InventoryItem).where(InventoryItem.id == item).values(product_id=cheap)
            ),
            "above the public price",
        )


def audit_event(db: Connection) -> int:
    return db.execute(
        insert(AuditEvent)
        .values(occurred_at=NOW, actor_type="SYSTEM", entity_type="order", action="order.expire")
        .returning(AuditEvent.id)
    ).scalar_one()


class TestAuditLog:
    """Append-only for everyone, the tables' owner included (docs/05 §3.8)."""

    def test_an_event_can_be_added_and_read(self, db: Connection) -> None:
        event = audit_event(db)

        assert (
            db.execute(
                text("SELECT action FROM audit_events WHERE id = :id"), {"id": event}
            ).scalar()
            == "order.expire"
        )

    def test_an_event_can_never_be_changed(self, db: Connection) -> None:
        event = audit_event(db)

        with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
            db.execute(update(AuditEvent).where(AuditEvent.id == event).values(action="tampered"))

    def test_the_owner_cannot_delete_or_empty_it(self, db: Connection) -> None:
        event = audit_event(db)

        with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
            db.execute(delete(AuditEvent).where(AuditEvent.id == event))
        with pytest.raises(DBAPIError, match="append-only"), db.begin_nested():
            db.execute(text("TRUNCATE audit_events"))
