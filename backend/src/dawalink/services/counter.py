"""At the pharmacy's counter: [Picked up] and [Not available] (docs/04 SM-5 O2, O3).

The pharmacist finds the reservation by its order number. They never learn who the client
is (INV-9): nothing here returns a name, an email, a phone number or a location.
"""

import uuid

from sqlalchemy import func, select

from dawalink.db.models import AuditEvent, InventoryItem, Order, Pharmacy, Product
from dawalink.domain import orders as order_rules
from dawalink.domain.accounts import PharmacyStatus, pharmacy_can_update_reservations
from dawalink.domain.inventory import Stock
from dawalink.domain.orders import OrderState
from dawalink.domain.refs import normalize_ref
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import CloseReason
from dawalink.services import audit, events, needs, orders
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.events import Decision
from dawalink.services.notify import Template, notify


def _own_reservation(
    tx: Tx, pharmacy_id: uuid.UUID, order_id: uuid.UUID
) -> tuple[Order, InventoryItem]:
    """The pharmacy's own order and its item, both locked: the item first, then the order."""
    pharmacy = tx.session.get(Pharmacy, pharmacy_id)
    if pharmacy is None or not pharmacy_can_update_reservations(PharmacyStatus(pharmacy.status)):
        raise ServiceError(Code.PHARMACY_NOT_APPROVED, "This pharmacy can't update reservations.")
    seen = tx.session.execute(
        select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    ).scalar()
    # Someone else's order looks exactly like one that doesn't exist.
    if seen is None or seen.pharmacy_id != pharmacy_id:
        raise ServiceError(Code.NOT_FOUND, "Unknown reservation.")
    item = orders.lock_items(tx, [seen.inventory_item_id])[seen.inventory_item_id]
    order = orders.lock_order(tx, order_id)
    assert order is not None
    if order.state != OrderState.RESERVED.value:
        raise ServiceError(
            Code.RESERVATION_NOT_ACTIVE, "This reservation is no longer active.", state=order.state
        )
    return order, item


def find_by_number(tx: Tx, pharmacy_id: uuid.UUID, typed: str) -> Order | None:
    """The pharmacy's reservation with this order number, however it was typed."""
    ref = normalize_ref(typed, "R")
    if ref is None:
        return None
    return tx.session.execute(
        select(Order).where(Order.ref == ref, Order.pharmacy_id == pharmacy_id)
    ).scalar()


def mark_picked_up(tx: Tx, pharmacy_id: uuid.UUID, order_id: uuid.UUID) -> Order:
    """The client collected the box (O2). There is no late pickup (INV-7)."""
    order, item = _own_reservation(tx, pharmacy_id, order_id)
    if order.deadline is None or tx.now >= order.deadline:
        raise ServiceError(Code.PICKUP_DEADLINE_PASSED, "The pickup deadline has passed.")
    units = order.qty_locked
    stock = Stock(item.qty_on_hand, item.qty_reserved).remove_reserved(units)
    item.qty_on_hand, item.qty_reserved = stock.on_hand, stock.reserved
    order.qty_picked_up, order.qty_locked = units, 0
    orders.move(
        tx,
        order,
        OrderState.PICKED_UP,
        Actor.PHARMACY,
        "order.picked_up",
        actor_id=pharmacy_id,
        units=units,
    )
    events.post_card(
        tx,
        orders.conversation_of(tx, order),
        "picked_up",
        order_id=str(order.id),
        order_ref=order.ref,
    )
    return order


def mark_not_available(
    tx: Tx, pharmacy_id: uuid.UUID, order_id: uuid.UUID, units: int | None = None
) -> Order:
    """Some or all of the reserved units aren't there (O3). Never a penalty for the client.

    The need behind the reservation opens again while its window is open, which wakes the
    agent to look elsewhere.
    """
    order, item = _own_reservation(tx, pharmacy_id, order_id)
    units = order.qty_locked if units is None else units
    try:
        after = order_rules.mark_not_available(order.qty_locked, units)
    except ValueError:
        raise ServiceError(
            Code.UNITS_INVALID, "Units must be between 1 and the units held.", held=order.qty_locked
        ) from None
    stock = Stock(item.qty_on_hand, item.qty_reserved).remove_reserved(units)
    item.qty_on_hand, item.qty_reserved = stock.on_hand, stock.reserved
    order.qty_locked = after.qty_locked
    if after.state is OrderState.NOT_AVAILABLE:
        order.close_reason = CloseReason.NOT_AVAILABLE.value
    # A partial mark keeps the order reserved: the audit event still records it.
    if after.state is OrderState.NOT_AVAILABLE:
        orders.move(
            tx,
            order,
            OrderState.NOT_AVAILABLE,
            Actor.PHARMACY,
            "order.not_available",
            actor_id=pharmacy_id,
            units=units,
        )
    else:
        audit.record(
            tx,
            Actor.PHARMACY,
            "order.not_available",
            "order",
            order.id,
            actor_id=pharmacy_id,
            before={"state": order.state, "qty_locked": order.qty_locked + units},
            after={"state": order.state, "qty_locked": order.qty_locked, "units": units},
        )

    marks = tx.session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.entity_id == order.id, AuditEvent.action == "order.not_available")
    ).scalar_one()
    product = tx.session.get_one(Product, order.product_id)
    pharmacy = tx.session.get_one(Pharmacy, pharmacy_id)
    notify(
        tx,
        order.client_id,
        Template.NOT_AVAILABLE,
        orders.order_summary(order, product, pharmacy) | {"units_not_available": units},
        # A reservation can be marked more than once, a part at a time.
        event=f"order:{order.id}:not-available:{marks}",
    )
    reopened = needs.units_lost(tx, order, units, Actor.PHARMACY)
    conversation = orders.conversation_of(tx, order)
    events.post_card(
        tx, conversation, "not_available", order_id=str(order.id), order_ref=order.ref, units=units
    )
    # In a chat the agent reacts too, even when no need stands behind the order (R-AG4).
    if reopened or order.source == "assistant":
        events.post_decision(
            tx, conversation, Decision.NOT_AVAILABLE, order_id=order.id, units=units
        )
    return order
