"""Orders: reservations and offers, from their creation to their end (docs/04 SM-5).

Only three things create or change an order: a client's tap, a pharmacy's click, and the
system's rules. No agent tool calls anything in this module (INV-11).

Locks are always taken in the same order, so two transactions can never wait for each
other: the client, then the inventory items (sorted), then the orders, then the need's
rows, then the conversation (docs/05 §6).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as upsert

from dawalink.db.models import (
    AbuseFlag,
    Claim,
    ClaimSkip,
    ClientProfile,
    InventoryItem,
    Order,
    Pharmacy,
    Product,
    RequestItem,
    SourcingRequest,
)
from dawalink.domain.accounts import CLIENT_MACHINE, ClientStatus, PharmacyStatus
from dawalink.domain.claims import ClaimState
from dawalink.domain.expiry import days_left, fits, last_day_of_use, zone_of
from dawalink.domain.inventory import ListingControl, Stock, is_visible
from dawalink.domain.limits import (
    LimitReached,
    OpenOrder,
    limit_reached_by,
    open_order_load,
    pause_after_no_show,
)
from dawalink.domain.numbers import (
    DEFAULT_DAYS_OF_USE,
    MAX_AVAILABILITY_SHOWN,
    MAX_UNITS_PER_GROUP,
    OFFER_SKIP_AFTER_DECLINE,
    PICKUP_REMINDER_BEFORE,
)
from dawalink.domain.orders import OPEN_STATES, ORDER_MACHINE, OrderSource, OrderState
from dawalink.domain.pickup import pharmacy_pickup_days, pickup_deadline
from dawalink.domain.refs import new_ref
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import CloseReason
from dawalink.domain.windows import offer_expires_at
from dawalink.services import audit, catalog, clients, events, matching, needs, pharmacies
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.events import Decision
from dawalink.services.notify import Template, notify
from dawalink.services.search import Box, visible_boxes

OPEN = tuple(state.value for state in OPEN_STATES)


@dataclass(frozen=True)
class ReserveLine:
    """One box in a tap: a single reserve has one line, a plan card several."""

    item_id: uuid.UUID
    qty: int
    # The price the client saw. If it went up since, nothing is reserved (docs/06 API-D4).
    expected_price_lbp: int
    days_of_use: int = DEFAULT_DAYS_OF_USE
    request_item_id: uuid.UUID | None = None


# --- Reading and locking --------------------------------------------------------------


def lock_items(tx: Tx, item_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, InventoryItem]:
    """Locks inventory items, always in the same order."""
    if not item_ids:
        return {}
    rows = tx.session.execute(
        select(InventoryItem)
        .where(InventoryItem.id.in_(set(item_ids)))
        .order_by(InventoryItem.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalars()
    return {item.id: item for item in rows}


def lock_order(tx: Tx, order_id: uuid.UUID) -> Order | None:
    return tx.session.execute(
        select(Order)
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()


def _peek(tx: Tx, order_id: uuid.UUID) -> Order | None:
    """Reads an order without locking it, to learn which rows must be locked first."""
    return tx.session.execute(
        select(Order).where(Order.id == order_id).execution_options(populate_existing=True)
    ).scalar()


def open_offers(tx: Tx, claim_ids: Sequence[uuid.UUID]) -> list[Order]:
    if not claim_ids:
        return []
    return list(
        tx.session.execute(
            select(Order).where(Order.claim_id.in_(claim_ids), Order.state == "OFFERED")
        ).scalars()
    )


def open_load(tx: Tx, client_id: uuid.UUID, *, without_claim: uuid.UUID | None = None) -> Any:
    """How much of the client's limits their open orders use (R-L1, R-L2, INV-3)."""
    rows = tx.session.execute(
        select(Order).where(Order.client_id == client_id, Order.state.in_(OPEN))
    ).scalars()
    return open_order_load(
        [
            OpenOrder(
                equivalence_group=order.equivalence_key or f"product:{order.product_id}",
                units=order.qty_locked,
                offer_for_claim=str(order.claim_id) if order.state == "OFFERED" else None,
            )
            for order in rows
            if not (order.state == "OFFERED" and order.claim_id == without_claim)
        ]
    )


def _limit_error(limit: LimitReached) -> ServiceError:
    if limit is LimitReached.OPEN_ORDERS:
        return ServiceError(Code.LIMIT_OPEN_ORDERS, "You have 5 open reservations (the maximum).")
    return ServiceError(Code.LIMIT_GROUP_UNITS, "Max 3 of the same medicine.")


def _new_ref(tx: Tx) -> str:
    """A random order number nobody else has (docs/05 §1, TM-D4)."""
    while True:
        ref = new_ref("R")
        if tx.session.execute(select(Order.id).where(Order.ref == ref)).scalar() is None:
            return ref


def _pickup_by(tx: Tx, pharmacy: Pharmacy, pickup_day: date, expiry_date: date) -> datetime:
    hours = pharmacies.weekly_hours(tx, [pharmacy.id])[pharmacy.id]
    return pickup_deadline(hours, pickup_day, expiry_date)


def conversation_of(tx: Tx, order: Order) -> uuid.UUID | None:
    """Where this order's cards and events go, or None for notifications only (R-AG5)."""
    source = order.source
    if order.claim_id is not None:
        # An offer follows its claim: a watch made on the search page stays agent-free.
        source = tx.session.execute(
            select(Claim.source).where(Claim.id == order.claim_id)
        ).scalar_one()
    return events.conversation_for(
        tx, source=source, client_id=order.client_id, request_item_id=order.request_item_id
    )


def order_summary(order: Order, product: Product, pharmacy: Pharmacy) -> dict[str, Any]:
    """What a notification may say about an order. No client identity (INV-9)."""
    return {
        "order_ref": order.ref,
        "product": product.moph_name,
        "pharmacy": pharmacy.name,
        "units": order.qty_requested,
        "price_lbp": order.price_snapshot_lbp,
        "pickup_by": order.deadline.isoformat() if order.deadline else None,
        "prescription_required": product.prescription_required,
    }


# --- State changes --------------------------------------------------------------------


def move(
    tx: Tx,
    order: Order,
    target: OrderState,
    actor: Actor,
    action: str,
    *,
    actor_id: uuid.UUID | None = None,
    reason: str | None = None,
    **after: Any,
) -> None:
    """Changes an order's state, checked by the state machine, with its one audit event."""
    current = OrderState(order.state)
    ORDER_MACHINE.check(current, target, actor)
    order.state = target.value
    if target not in OPEN_STATES:
        order.closed_at = tx.now
    audit.record(
        tx,
        actor,
        action,
        "order",
        order.id,
        actor_id=actor_id,
        before={"state": current.value},
        after={"state": target.value, **after},
        reason=reason,
    )


def _release(tx: Tx, order: Order, item: InventoryItem) -> int:
    """Gives the order's held units back to the shelf. Returns how many."""
    units = order.qty_locked
    if units:
        item.qty_reserved = Stock(item.qty_on_hand, item.qty_reserved).release(units).reserved
        order.qty_locked = 0
    return units


def _need_covered(tx: Tx, claim: Claim, *, kept: Order, by_offer_from_early_release: bool) -> None:
    """A need is covered: its other offers and its asks are withdrawn (R-RQ7, R-W3)."""
    withdraw_offers(tx, claim.id, reason="the need was covered", keep=kept.id)
    needs.withdraw_asks(tx, claim, fulfilled=by_offer_from_early_release)


def withdraw_offers(
    tx: Tx, claim_id: uuid.UUID, *, reason: str, keep: uuid.UUID | None = None
) -> int:
    """The claim's open offers end at once (O11). Their items must already be locked."""
    withdrawn = 0
    for offer in open_offers(tx, [claim_id]):
        if offer.id == keep:
            continue
        locked = lock_order(tx, offer.id)
        if locked is None or locked.state != "OFFERED":
            continue
        item = lock_items(tx, [locked.inventory_item_id])[locked.inventory_item_id]
        _release(tx, locked, item)
        locked.close_reason = CloseReason.WITHDRAWN.value
        move(tx, locked, OrderState.OFFER_WITHDRAWN, Actor.SYSTEM, "order.withdraw", reason=reason)
        _stock_freed(tx, locked.product_id)
        withdrawn += 1
    return withdrawn


def _stock_freed(tx: Tx, product_id: uuid.UUID) -> None:
    """Units went back on the shelf: the next waiting claim may get them (R-PRI1)."""
    product = tx.session.get(Product, product_id)
    if product is not None:
        matching.defer_for_product(tx, product)


# --- O1: reserve ----------------------------------------------------------------------


def _check_line(line: ReserveLine, box: Box | None, pickup_day: date) -> ServiceError | None:
    """Why this box can't be reserved as asked, or None (O1's guards, in a fixed order)."""
    if not 1 <= line.qty <= MAX_UNITS_PER_GROUP or line.days_of_use < 1:
        return ServiceError(Code.VALIDATION_ERROR, "Quantity is 1 to 3; days of use start at 1.")
    if box is None:
        return ServiceError(Code.LISTING_NOT_AVAILABLE, "This option is no longer available.")
    if pickup_day not in box.pharmacy_days:
        return ServiceError(Code.PICKUP_DAY_INVALID, "The pharmacy doesn't accept that pickup day.")
    if not fits(box.expiry_date, pickup_day, line.days_of_use):
        return ServiceError(
            Code.DOES_NOT_FIT,
            "This box expires before your last day of use.",
            expiry_date=box.expiry_date,
            last_day_of_use=last_day_of_use(pickup_day, line.days_of_use),
        )
    if line.qty > box.qty_available:
        return ServiceError(
            Code.NOT_ENOUGH_STOCK,
            "Someone reserved this a moment ago.",
            available=min(box.qty_available, MAX_AVAILABILITY_SHOWN),
        )
    if box.price_lbp > line.expected_price_lbp:
        return ServiceError(
            Code.PRICE_CHANGED, "The price went up since you saw it.", new_price=box.price_lbp
        )
    return None


def _sold_out(tx: Tx, item: InventoryItem | None) -> bool:
    """True if this box would be visible but for having no unit left."""
    if item is None or item.qty_on_hand - item.qty_reserved >= 1:
        return False
    product = tx.session.get_one(Product, item.product_id)
    pharmacy = tx.session.get_one(Pharmacy, item.pharmacy_id)
    return is_visible(
        zone=zone_of(days_left(item.expiry_date, tx.today)),
        control=ListingControl(item.listing_control),
        pharmacy_status=PharmacyStatus(pharmacy.status),
        qty_available=1,
        controlled=product.controlled,
    )


def _check_request_items(
    tx: Tx, client_id: uuid.UUID, lines: Sequence[ReserveLine], boxes: dict[uuid.UUID, Box]
) -> None:
    """A line for a request item must be for that item's medicine, in its open request."""
    for line in lines:
        if line.request_item_id is None:
            continue
        found = tx.session.execute(
            select(RequestItem, SourcingRequest)
            .join(SourcingRequest, SourcingRequest.id == RequestItem.request_id)
            .where(RequestItem.id == line.request_item_id, SourcingRequest.client_id == client_id)
        ).one_or_none()
        if found is None:
            raise ServiceError(Code.NOT_FOUND, "Unknown request item.")
        item, request = found
        if request.state != "OPEN":
            raise ServiceError(Code.REQUEST_CLOSED, "This request is closed.")
        box = boxes.get(line.item_id)
        if box is None:
            continue
        wanted = catalog.allowed_product(tx, item.product_id)
        allowed = catalog.products_in_group(tx, wanted, with_equivalents=request.alternatives_ok)
        if box.product_id not in allowed or line.qty > item.qty - item.qty_secured:
            raise ServiceError(Code.VALIDATION_ERROR, "That isn't what this request item asks for.")


def reserve(
    tx: Tx,
    *,
    client_id: uuid.UUID,
    lines: Sequence[ReserveLine],
    pickup_day: date,
    source: OrderSource,
    idempotency_key: str,
) -> list[Order]:
    """The client taps [Reserve]: the boxes are theirs at once (O1).

    Several lines are a group reserve: all of them, or none (R-RQ6). The same tap sent twice
    returns the same orders.
    """
    client = clients.profile(tx, client_id, lock=True)
    clients.require_reserve(tx, client)
    if not lines or len({line.item_id for line in lines}) != len(lines) or not idempotency_key:
        raise ServiceError(Code.VALIDATION_ERROR, "A tap reserves each box once.")
    keys = (
        [idempotency_key]
        if len(lines) == 1
        else [f"{idempotency_key}:{position}" for position in range(1, len(lines) + 1)]
    )
    done = {
        order.idempotency_key: order
        for order in tx.session.execute(
            select(Order).where(Order.client_id == client_id, Order.idempotency_key.in_(keys))
        ).scalars()
    }
    if done:
        if len(done) != len(keys):
            raise ServiceError(
                Code.VALIDATION_ERROR, "This tap was already used for something else."
            )
        return [done[key] for key in keys]

    # Every item this tap may touch is locked now, in one sorted pass: the boxes themselves,
    # and the boxes held by offers that will be withdrawn if a need gets covered.
    request_items = [line.request_item_id for line in lines if line.request_item_id]
    claim_ids = list(
        tx.session.execute(
            select(Claim.id).where(Claim.request_item_id.in_(request_items))
        ).scalars()
    )
    held_by_offers = [offer.inventory_item_id for offer in open_offers(tx, claim_ids)]
    items = lock_items(tx, [*(line.item_id for line in lines), *held_by_offers])
    boxes = {
        box.item_id: box for box in visible_boxes(tx, item_ids=[line.item_id for line in lines])
    }
    _check_request_items(tx, client_id, lines, boxes)

    failures = []
    for line in lines:
        error = _check_line(line, boxes.get(line.item_id), pickup_day)
        gone = error is not None and error.code is Code.LISTING_NOT_AVAILABLE
        if gone and _sold_out(tx, items.get(line.item_id)):
            # Visible a moment ago, and someone took the last unit: say so (FR-1).
            error = ServiceError(
                Code.NOT_ENOUGH_STOCK, "Someone reserved this a moment ago.", available=0
            )
        if error is not None:
            failures.append((line, error))
    if failures and len(lines) == 1:
        raise failures[0][1]
    if failures:
        raise ServiceError(
            Code.GROUP_ITEM_FAILED,
            "One item is no longer available, so nothing was reserved yet.",
            failed_items=[
                {
                    "item_id": line.item_id,
                    "request_item_id": line.request_item_id,
                    "code": error.code.value,
                    **error.details,
                }
                for line, error in failures
            ],
        )

    products = {
        product.id: product
        for product in tx.session.execute(
            select(Product).where(Product.id.in_({box.product_id for box in boxes.values()}))
        ).scalars()
    }
    limit = limit_reached_by(
        open_load(tx, client_id),
        [
            (catalog.medicine_group(products[boxes[line.item_id].product_id]), line.qty)
            for line in lines
        ],
    )
    if limit is not None:
        raise _limit_error(limit)

    group_id = uuid.uuid4() if len(lines) > 1 else None
    orders: list[Order] = []
    for line, key in zip(lines, keys, strict=True):
        box, item = boxes[line.item_id], items[line.item_id]
        product = products[box.product_id]
        pharmacy = tx.session.get_one(Pharmacy, box.pharmacy_id)
        item.qty_reserved = Stock(item.qty_on_hand, item.qty_reserved).reserve(line.qty).reserved
        order = Order(
            id=uuid.uuid4(),
            ref=_new_ref(tx),
            client_id=client_id,
            pharmacy_id=box.pharmacy_id,
            inventory_item_id=item.id,
            product_id=product.id,
            equivalence_key=product.equivalence_key,
            source=source.value,
            request_item_id=line.request_item_id,
            group_id=group_id,
            state=OrderState.RESERVED.value,
            qty_requested=line.qty,
            qty_locked=line.qty,
            pickup_day=pickup_day,
            days_of_use=line.days_of_use,
            price_snapshot_lbp=box.price_lbp,
            deadline=_pickup_by(tx, pharmacy, pickup_day, box.expiry_date),
            idempotency_key=key,
            reserved_at=tx.now,
        )
        tx.session.add(order)
        tx.session.flush()
        audit.record(
            tx,
            Actor.CLIENT,
            "order.reserve",
            "order",
            order.id,
            actor_id=client_id,
            after={"state": order.state, "units": line.qty, "price_lbp": box.price_lbp},
        )
        _after_reserved(tx, order, product, pharmacy, from_early_release=False)
        orders.append(order)
    return orders


def _after_reserved(
    tx: Tx, order: Order, product: Product, pharmacy: Pharmacy, *, from_early_release: bool
) -> None:
    """What follows any new reservation: the need, the pharmacy, the client (O1, O9)."""
    covered = needs.units_gained(tx, order, order.qty_locked, Actor.CLIENT)
    if covered is not None:
        _need_covered(tx, covered, kept=order, by_offer_from_early_release=from_early_release)
    summary = order_summary(order, product, pharmacy)
    notify(tx, pharmacy.owner_user_id, Template.NEW_RESERVATION, summary, event=f"order:{order.id}")
    # Only this notification carries the address: it is typed by the pharmacy, so it stays
    # out of chat cards, which the agent can read (R-AG8).
    where = {
        "pharmacy_address": pharmacy.address,
        "open_hours": pharmacies.hours_text(tx, pharmacy.id, order.pickup_day),
    }
    notify(tx, order.client_id, Template.RESERVED, summary | where, event=f"order:{order.id}")
    events.post_card(tx, conversation_of(tx, order), "reserved", order_id=str(order.id), **summary)


# --- O5, O6, O4: cancel, system cancel, no-show ---------------------------------------


def cancel_by_client(tx: Tx, client_id: uuid.UUID, order_id: uuid.UUID) -> Order:
    """The client cancels a reservation before its deadline. Never a penalty (O5, R-N2)."""
    clients.profile(tx, client_id, lock=True)
    seen = _peek(tx, order_id)
    if seen is None or seen.client_id != client_id:
        raise ServiceError(Code.NOT_FOUND, "Unknown reservation.")
    item = lock_items(tx, [seen.inventory_item_id])[seen.inventory_item_id]
    order = lock_order(tx, order_id)
    assert order is not None
    if order.state != "RESERVED" or order.deadline is None or tx.now >= order.deadline:
        raise ServiceError(Code.RESERVATION_NOT_ACTIVE, "This reservation is no longer active.")
    units = _release(tx, order, item)
    order.close_reason = CloseReason.CLIENT_CANCEL.value
    move(
        tx, order, OrderState.CANCELLED_BY_CLIENT, Actor.CLIENT, "order.cancel", actor_id=client_id
    )
    ended = needs.need_ended(tx, order, units, Actor.CLIENT)
    if ended is not None:
        withdraw_offers(tx, ended.id, reason="the client cancelled")
        needs.withdraw_asks(tx, ended, fulfilled=False)
    product = tx.session.get_one(Product, order.product_id)
    pharmacy = tx.session.get_one(Pharmacy, order.pharmacy_id)
    notify(
        tx,
        pharmacy.owner_user_id,
        Template.CLIENT_CANCELLED,
        order_summary(order, product, pharmacy),
        event=f"order:{order.id}",
    )
    events.post_card(
        tx, conversation_of(tx, order), "cancelled", order_id=str(order.id), order_ref=order.ref
    )
    _stock_freed(tx, order.product_id)
    return order


def cancel_by_system(
    tx: Tx, order_id: uuid.UUID, *, reason: str, reopen_need: bool = True
) -> Order | None:
    """The system ends an open order (O6): a suspension, or a product that became controlled.

    `reopen_need` is False when the client themselves was suspended: nothing is searched
    for them again. Returns None if the order was no longer open.
    """
    seen = _peek(tx, order_id)
    if seen is None:
        return None
    item = lock_items(tx, [seen.inventory_item_id])[seen.inventory_item_id]
    order = lock_order(tx, order_id)
    if order is None or OrderState(order.state) not in OPEN_STATES:
        return None
    was_reserved = order.state == "RESERVED"
    units = _release(tx, order, item)
    order.close_reason = CloseReason.SYSTEM.value
    move(
        tx,
        order,
        OrderState.CANCELLED_BY_SYSTEM,
        Actor.SYSTEM,
        "order.system_cancel",
        reason=reason,
    )
    product = tx.session.get_one(Product, order.product_id)
    pharmacy = tx.session.get_one(Pharmacy, order.pharmacy_id)
    notify(
        tx,
        order.client_id,
        Template.CANCELLED_BY_SYSTEM,
        order_summary(order, product, pharmacy),
        event=f"order:{order.id}",
    )
    reopened = False
    if was_reserved and reopen_need:
        reopened = needs.units_lost(tx, order, units, Actor.SYSTEM)
    elif was_reserved:
        # Nothing is searched again: the need behind this reservation ends with it.
        ended = needs.need_ended(tx, order, units, Actor.SYSTEM)
        if ended is not None:
            needs.withdraw_asks(tx, ended, fulfilled=False)
    _claim_after_offer_ended(tx, order)
    conversation = conversation_of(tx, order)
    events.post_card(
        tx, conversation, "cancelled_by_system", order_id=str(order.id), order_ref=order.ref
    )
    if reopened:
        events.post_decision(tx, conversation, Decision.SYSTEM_CANCELLED, order_id=order.id)
    if not product.controlled:
        _stock_freed(tx, order.product_id)
    return order


def expire_no_show(tx: Tx, order_id: uuid.UUID) -> Order | None:
    """The deadline passed and the box wasn't collected (O4). Run by the clock check.

    Returns None if there was nothing to do: the row is re-checked under its locks, so a
    pickup or a cancel that got there first wins.
    """
    seen = _peek(tx, order_id)
    if seen is None:
        return None
    client = clients.profile(tx, seen.client_id, lock=True)
    item = lock_items(tx, [seen.inventory_item_id])[seen.inventory_item_id]
    order = lock_order(tx, order_id)
    if order is None or order.state != "RESERVED" or order.deadline is None:
        return None
    if tx.now < order.deadline:
        return None
    units = _release(tx, order, item)
    order.counts_as_no_show = True
    order.close_reason = CloseReason.EXPIRED.value
    move(tx, order, OrderState.EXPIRED_NO_SHOW, Actor.SYSTEM, "order.no_show")
    _pause_after_no_shows(tx, client)
    ended = needs.need_ended(tx, order, units, Actor.SYSTEM)
    if ended is not None:
        withdraw_offers(tx, ended.id, reason="the client didn't come")
        needs.withdraw_asks(tx, ended, fulfilled=False)
    product = tx.session.get_one(Product, order.product_id)
    pharmacy = tx.session.get_one(Pharmacy, order.pharmacy_id)
    notify(
        tx,
        order.client_id,
        Template.EXPIRED_NO_SHOW,
        order_summary(order, product, pharmacy),
        event=f"order:{order.id}",
    )
    events.post_card(
        tx, conversation_of(tx, order), "expired", order_id=str(order.id), order_ref=order.ref
    )
    _stock_freed(tx, order.product_id)
    return order


def _pause_after_no_shows(tx: Tx, client: ClientProfile) -> None:
    """Two counted no-shows in 30 days pause the client for 7 days; each later one adds 7 (R-N1).

    The client's row is already locked, so two no-shows handled at once can't both miss
    the pause.
    """
    counted = list(
        tx.session.execute(
            select(Order.closed_at).where(
                Order.client_id == client.user_id,
                Order.counts_as_no_show.is_(True),
                Order.closed_at.is_not(None),
            )
        ).scalars()
    )
    until = pause_after_no_show(
        [moment for moment in counted if moment], tx.now, client.paused_until
    )
    if until is None or until == client.paused_until:
        return
    before = {"status": client.status, "paused_until": str(client.paused_until)}
    if client.status == ClientStatus.ACTIVE.value:
        CLIENT_MACHINE.check(ClientStatus.ACTIVE, ClientStatus.PAUSED, Actor.SYSTEM)
        client.status = ClientStatus.PAUSED.value
    if client.status != ClientStatus.PAUSED.value:
        return  # suspended: nothing to pause
    client.paused_until = until
    audit.record(
        tx,
        Actor.SYSTEM,
        "client.pause",
        "client",
        client.user_id,
        before=before,
        after={"status": client.status, "paused_until": until.isoformat()},
        reason="counted no-shows (R-N1)",
    )
    notify(
        tx,
        client.user_id,
        Template.PAUSED,
        {"paused_until": until.isoformat()},
        event=f"pause:{until.isoformat()}",
    )
    tx.session.execute(
        upsert(AbuseFlag)
        .values(
            subject_type="client",
            subject_id=client.user_id,
            rule="no_show_pause",
            severity="low",
            evidence={"no_shows": len(counted)},
        )
        .on_conflict_do_nothing(
            index_elements=["subject_type", "subject_id", "rule"],
            index_where=sql_text("state = 'OPEN'"),
        )
    )


def lift_pause(tx: Tx, client_id: uuid.UUID) -> bool:
    """A pause that has run out ends: the client is active again (SM-2). Run by the clock check."""
    client = clients.profile(tx, client_id, lock=True)
    if client.status != ClientStatus.PAUSED.value or client.paused_until is None:
        return False
    if client.paused_until > tx.now:
        return False
    CLIENT_MACHINE.check(ClientStatus.PAUSED, ClientStatus.ACTIVE, Actor.SYSTEM)
    client.status = ClientStatus.ACTIVE.value
    audit.record(
        tx,
        Actor.SYSTEM,
        "client.pause_ended",
        "client",
        client_id,
        before={"status": "PAUSED"},
        after={"status": "ACTIVE"},
    )
    return True


def send_pickup_reminder(tx: Tx, order_id: uuid.UUID) -> bool:
    """One reminder, a few hours before the deadline (N-8). Run by the clock check."""
    order = lock_order(tx, order_id)
    if order is None or order.state != "RESERVED" or order.reminder_sent_at is not None:
        return False
    if (
        order.deadline is None
        or not order.deadline - PICKUP_REMINDER_BEFORE <= tx.now < order.deadline
    ):
        return False
    order.reminder_sent_at = tx.now
    product = tx.session.get_one(Product, order.product_id)
    pharmacy = tx.session.get_one(Pharmacy, order.pharmacy_id)
    notify(
        tx,
        order.client_id,
        Template.PICKUP_REMINDER,
        order_summary(order, product, pharmacy),
        event=f"order:{order.id}",
    )
    return True


# --- O7 to O11: offers ----------------------------------------------------------------


def create_offer(
    tx: Tx,
    *,
    claim: Claim,
    item: InventoryItem,
    units: int,
    price_lbp: int,
    source: OrderSource,
    actor: Actor,
    reason: str,
    early_release_ask_id: uuid.UUID | None = None,
) -> Order:
    """Stock is held for one claim for two hours (O7, O8). `claim` and `item` are locked."""
    product = tx.session.get_one(Product, item.product_id)
    pharmacy = tx.session.get_one(Pharmacy, item.pharmacy_id)
    item.qty_reserved = Stock(item.qty_on_hand, item.qty_reserved).reserve(units).reserved
    order = Order(
        id=uuid.uuid4(),
        ref=_new_ref(tx),
        client_id=claim.client_id,
        pharmacy_id=item.pharmacy_id,
        inventory_item_id=item.id,
        product_id=product.id,
        equivalence_key=product.equivalence_key,
        source=source.value,
        claim_id=claim.id,
        request_item_id=claim.request_item_id,
        early_release_ask_id=early_release_ask_id,
        state=OrderState.OFFERED.value,
        qty_requested=units,
        qty_locked=units,
        days_of_use=claim.days_of_use,
        price_snapshot_lbp=price_lbp,
        offer_expires_at=offer_expires_at(tx.now),
        idempotency_key=f"offer:{uuid.uuid4()}",
    )
    tx.session.add(order)
    tx.session.flush()
    audit.record(
        tx,
        actor,
        "order.offer",
        "order",
        order.id,
        after={"state": order.state, "units": units, "claim_id": str(claim.id)},
        reason=reason,
    )
    needs.move_claim(tx, claim, ClaimState.OFFER_PENDING, actor)
    template = (
        Template.EARLY_RELEASE_OFFER
        if source is OrderSource.EARLY_RELEASE
        else Template.MATCHING_OFFER
    )
    summary = order_summary(order, product, pharmacy) | {
        "offer_expires_at": order.offer_expires_at.isoformat() if order.offer_expires_at else None,
        "expiry_date": item.expiry_date.isoformat(),
    }
    notify(tx, claim.client_id, template, summary, event=f"order:{order.id}")
    conversation = events.conversation_for(
        tx, source=claim.source, client_id=claim.client_id, request_item_id=claim.request_item_id
    )
    events.post_card(tx, conversation, "offer", order_id=str(order.id), **summary)
    return order


def _claim_after_offer_ended(tx: Tx, order: Order) -> None:
    """An offer ended without being accepted: its claim waits again unless another offer holds."""
    if order.claim_id is None:
        return
    claim = tx.session.execute(
        select(Claim)
        .where(Claim.id == order.claim_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if claim.state == "OFFER_PENDING" and not open_offers(tx, [claim.id]):
        needs.move_claim(tx, claim, ClaimState.ACTIVE, Actor.SYSTEM)


def accept_offer(tx: Tx, client_id: uuid.UUID, order_id: uuid.UUID, pickup_day: date) -> Order:
    """The client accepts an offer: it becomes a reservation (O9).

    The claim's other offers are withdrawn at once, so a need is never served twice (INV-20).
    """
    client = clients.profile(tx, client_id, lock=True)
    clients.require_reserve(tx, client)
    seen = _peek(tx, order_id)
    if seen is None or seen.client_id != client_id or seen.claim_id is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown offer.")
    siblings = open_offers(tx, [seen.claim_id])
    items = lock_items(tx, [seen.inventory_item_id, *(o.inventory_item_id for o in siblings)])
    order = lock_order(tx, order_id)
    assert order is not None
    if order.state != "OFFERED" or order.offer_expires_at is None:
        raise ServiceError(Code.OFFER_NOT_OPEN, "This offer is no longer open.", reason=order.state)
    if tx.now >= order.offer_expires_at:
        raise ServiceError(Code.OFFER_NOT_OPEN, "This offer has expired.", reason="OFFER_EXPIRED")

    item = items[order.inventory_item_id]
    product = tx.session.get_one(Product, order.product_id)
    pharmacy = tx.session.get_one(Pharmacy, order.pharmacy_id)
    hours = pharmacies.weekly_hours(tx, [pharmacy.id])[pharmacy.id]
    if pickup_day not in pharmacy_pickup_days(hours, pharmacy.pickup_days, tx.now):
        raise ServiceError(Code.PICKUP_DAY_INVALID, "The pharmacy doesn't accept that pickup day.")
    if not fits(item.expiry_date, pickup_day, order.days_of_use):
        raise ServiceError(
            Code.DOES_NOT_FIT,
            "This box expires before your last day of use.",
            expiry_date=item.expiry_date,
            last_day_of_use=last_day_of_use(pickup_day, order.days_of_use),
        )
    # The claim's offers counted once while they waited; this one now counts as itself.
    limit = limit_reached_by(
        open_load(tx, client_id, without_claim=order.claim_id),
        [(catalog.medicine_group(product), order.qty_locked)],
    )
    if limit is not None:
        raise _limit_error(limit)

    order.pickup_day = pickup_day
    order.deadline = pickup_deadline(hours, pickup_day, item.expiry_date)
    order.reserved_at = tx.now
    move(
        tx,
        order,
        OrderState.RESERVED,
        Actor.CLIENT,
        "order.accept_offer",
        actor_id=client_id,
        units=order.qty_locked,
    )
    from_early_release = order.source == OrderSource.EARLY_RELEASE.value
    withdraw_offers(tx, seen.claim_id, reason="another offer was accepted", keep=order.id)
    _after_reserved(tx, order, product, pharmacy, from_early_release=from_early_release)
    claim = tx.session.get_one(Claim, seen.claim_id)
    if claim.state == "OFFER_PENDING":
        # Covered only in part: the claim waits for the rest (R-W4).
        needs.move_claim(tx, claim, ClaimState.ACTIVE, Actor.CLIENT)
        if from_early_release:
            needs.withdraw_asks(tx, claim, fulfilled=True)
        matching.defer_for_product(tx, product)
    return order


def end_offer(tx: Tx, order_id: uuid.UUID, *, declined_by: uuid.UUID | None = None) -> Order | None:
    """An offer ends without a reservation: the client declines, or its two hours pass (O10).

    A matching offer's unit goes to the next claim, and this claim skips that box for a
    day. An early-release offer's box simply goes back to being private. Returns None if
    there was nothing to do (the clock check re-checks under the locks).
    """
    seen = _peek(tx, order_id)
    if seen is None or (declined_by is not None and seen.client_id != declined_by):
        if declined_by is not None:
            raise ServiceError(Code.NOT_FOUND, "Unknown offer.")
        return None
    item = lock_items(tx, [seen.inventory_item_id])[seen.inventory_item_id]
    order = lock_order(tx, order_id)
    assert order is not None
    if order.state != "OFFERED" or order.offer_expires_at is None:
        if declined_by is not None:
            raise ServiceError(
                Code.OFFER_NOT_OPEN, "This offer is no longer open.", reason=order.state
            )
        return None
    if declined_by is None and tx.now < order.offer_expires_at:
        return None
    _release(tx, order, item)
    if declined_by is not None:
        order.close_reason = CloseReason.DECLINED.value
        move(
            tx,
            order,
            OrderState.OFFER_DECLINED,
            Actor.CLIENT,
            "order.decline_offer",
            actor_id=declined_by,
        )
    else:
        order.close_reason = CloseReason.EXPIRED.value
        move(tx, order, OrderState.OFFER_EXPIRED, Actor.SYSTEM, "order.offer_expired")
    if order.claim_id is not None and order.source != OrderSource.EARLY_RELEASE.value:
        statement = upsert(ClaimSkip).values(
            claim_id=order.claim_id,
            inventory_item_id=order.inventory_item_id,
            skip_until=tx.now + OFFER_SKIP_AFTER_DECLINE,
        )
        tx.session.execute(
            statement.on_conflict_do_update(
                index_elements=["claim_id", "inventory_item_id"],
                set_={"skip_until": statement.excluded.skip_until},
            )
        )
    _claim_after_offer_ended(tx, order)
    events.post_card(
        tx, conversation_of(tx, order), "offer_ended", order_id=str(order.id), state=order.state
    )
    if order.source == OrderSource.EARLY_RELEASE.value:
        claim_id = order.claim_id

        def is_the_request_over(later: Tx) -> None:
            # Imported here: early release itself creates offers through this module.
            from dawalink.services.early_release import resolve_for_claim

            resolve_for_claim(later, claim_id)

        tx.defer(("early-release", claim_id), is_the_request_over)
    else:
        _stock_freed(tx, order.product_id)
    return order
