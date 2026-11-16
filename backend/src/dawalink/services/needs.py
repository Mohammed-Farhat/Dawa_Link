"""Keeping a need in step with its orders (docs/04 SM-7, SM-8, R-RQ7, R-W3, R-W4).

A **need** is a claim (a watch, or a waiting request item) and, inside a request, the
request item itself. Orders change; this module makes the need follow:
- units reserved → fewer units missing, and the item is secured when all are (INV-18);
- units lost at the pharmacy → the need opens again while its window is open;
- the client cancels or misses a reservation → the need ends.

Once a request is closed, later events are recorded on the orders only (R-RQ9), with one
exception: a box lost at the pharmacy before the request's six hours are over opens the
request again (R-RQ12).
"""

from sqlalchemy import case, func, select

from dawalink.db.models import (
    Claim,
    EarlyReleaseAsk,
    EarlyReleaseRequest,
    Order,
    RequestItem,
    SourcingRequest,
)
from dawalink.domain.claims import (
    CLAIM_MACHINE,
    LIVE_STATES,
    ClaimState,
    missing_after_losing,
    missing_after_reserving,
)
from dawalink.domain.orders import OrderState
from dawalink.domain.requests import (
    FINAL_ITEM_STATES,
    ITEM_MACHINE,
    REQUEST_MACHINE,
    ItemState,
    RequestOutcome,
    RequestState,
    may_reopen,
)
from dawalink.domain.state_machine import Actor
from dawalink.services import audit, events
from dawalink.services.context import Tx


def _locked_item(tx: Tx, order: Order) -> RequestItem | None:
    """The order's request item, locked, if its request is still open."""
    if order.request_item_id is None:
        return None
    item = tx.session.execute(
        select(RequestItem)
        .where(RequestItem.id == order.request_item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    state = tx.session.execute(
        select(SourcingRequest.state).where(SourcingRequest.id == item.request_id)
    ).scalar_one()
    return item if state == RequestState.OPEN else None


def _units_held(tx: Tx, request_id: object) -> dict[object, int]:
    """The units each item of a request really holds: reserved or picked up (INV-18)."""
    rows = tx.session.execute(
        select(
            Order.request_item_id,
            func.coalesce(
                func.sum(
                    case(
                        (Order.state == OrderState.RESERVED.value, Order.qty_locked),
                        else_=Order.qty_picked_up,
                    )
                ),
                0,
            ),
        )
        .join(RequestItem, RequestItem.id == Order.request_item_id)
        .where(
            RequestItem.request_id == request_id,
            Order.state.in_([OrderState.RESERVED.value, OrderState.PICKED_UP.value]),
        )
        .group_by(Order.request_item_id)
    )
    return {item_id: int(units) for item_id, units in rows}


def _reopen_request(tx: Tx, order: Order, units: int, actor: Actor) -> SourcingRequest | None:
    """A box of a request that already closed is lost before its window ends: the request
    opens again, so the medicine is searched for like in any open request (R-RQ12).

    The request is locked before its items, as when a request closes. It keeps its window:
    it ends when it would have ended. It may be the client's third open request for a
    while; the limit is on starting requests.

    While it was closed, the client's own cancels and no-shows were recorded on the orders
    only (R-RQ9). They are caught up here: a medicine the client gave up on stays given up
    (R-RQ11), and never reopens the request.

    Returns the request if it opened again. The caller says so in its thread, once every
    request row is locked: the conversation comes last in the lock order (docs/05 §6).
    """
    if order.request_item_id is None:
        return None
    request = tx.session.execute(
        select(SourcingRequest)
        .join(RequestItem, RequestItem.request_id == SourcingRequest.id)
        .where(RequestItem.id == order.request_item_id)
        .with_for_update(of=SourcingRequest)
        .execution_options(populate_existing=True)
    ).scalar_one()
    if request.state != RequestState.CLOSED or request.outcome is None:
        return None
    items = list(
        tx.session.execute(
            select(RequestItem)
            .where(RequestItem.request_id == request.id)
            .order_by(RequestItem.position)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalars()
    )
    held = _units_held(tx, request.id)
    # The lost units have already left the order, and not yet the item.
    held[order.request_item_id] = held.get(order.request_item_id, 0) + units
    lost = next(item for item in items if item.id == order.request_item_id)
    outcome = RequestOutcome(request.outcome)
    if held[lost.id] < lost.qty or not may_reopen(
        outcome, ItemState(lost.state), now=tx.now, ends_at=request.ends_at
    ):
        return None
    REQUEST_MACHINE.check(RequestState.CLOSED, RequestState.OPEN, actor)
    request.state = RequestState.OPEN.value
    request.outcome = None
    request.closed_at = None
    audit.record(
        tx,
        actor,
        "request.reopen",
        "sourcing_request",
        request.id,
        before={"state": "CLOSED", "outcome": outcome.value},
        after={"state": "OPEN", "order_id": str(order.id)},
    )
    for item in items:
        if ItemState(item.state) is ItemState.SECURED and held.get(item.id, 0) < item.qty:
            item.qty_secured = held.get(item.id, 0)
            move_item(tx, item, ItemState.CANCELLED, Actor.SYSTEM)
    return request


def _locked_claim(tx: Tx, order: Order) -> Claim | None:
    """The claim this order serves: the one it was offered for, or its request item's."""
    if order.claim_id is not None:
        condition = Claim.id == order.claim_id
    elif order.request_item_id is not None:
        condition = Claim.request_item_id == order.request_item_id
    else:
        return None
    return tx.session.execute(
        select(Claim).where(condition).with_for_update().execution_options(populate_existing=True)
    ).scalar()


def lock_claim(tx: Tx, claim_id: object) -> Claim:
    return tx.session.execute(
        select(Claim)
        .where(Claim.id == claim_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def move_item(tx: Tx, item: RequestItem, target: ItemState, actor: Actor) -> None:
    current = ItemState(item.state)
    if current is target:
        return
    ITEM_MACHINE.check(current, target, actor)
    item.state = target.value
    audit.record(
        tx,
        actor,
        "request_item.state",
        "request_item",
        item.id,
        before={"state": current.value},
        after={"state": target.value, "qty_secured": item.qty_secured},
    )
    if target in FINAL_ITEM_STATES:
        request_id = item.request_id

        def is_the_request_done(later: Tx) -> None:
            # Imported here: the request service itself moves items through this module.
            from dawalink.services.requests import close_if_done

            close_if_done(later, request_id)

        # When every item is final the request closes (R-RQ9), once this work is committed.
        tx.defer(("close-request", request_id), is_the_request_done)


def move_claim(tx: Tx, claim: Claim, target: ClaimState, actor: Actor) -> None:
    current = ClaimState(claim.state)
    if current is target:
        return
    CLAIM_MACHINE.check(current, target, actor)
    claim.state = target.value
    claim.closed_at = None if target in LIVE_STATES else tx.now
    audit.record(
        tx,
        actor,
        "claim.state",
        "claim",
        claim.id,
        before={"state": current.value},
        after={"state": target.value, "qty_missing": claim.qty_missing},
    )


def units_gained(tx: Tx, order: Order, units: int, actor: Actor) -> Claim | None:
    """`units` of this order were just reserved. Returns its claim if the need is now covered."""
    item = _locked_item(tx, order)
    if item is not None:
        item.qty_secured = min(item.qty, item.qty_secured + units)
        if item.qty_secured >= item.qty:
            move_item(tx, item, ItemState.SECURED, actor)
        elif ItemState(item.state) is ItemState.PROPOSED:
            # Reserved only in part: the rest is searched for again (R-RQ6).
            move_item(tx, item, ItemState.SEARCHING, actor)
    claim = _locked_claim(tx, order)
    if claim is None or ClaimState(claim.state) not in LIVE_STATES:
        return None
    claim.qty_missing = missing_after_reserving(claim.qty_missing, min(units, claim.qty_missing))
    if claim.qty_missing > 0:
        return None
    move_claim(tx, claim, ClaimState.FULFILLED, actor)
    return claim


def units_lost(tx: Tx, order: Order, units: int, actor: Actor) -> bool:
    """Reserved units turned out not to be there, or the system cancelled them (O3, O6).

    Returns True when the need is open again, which calls for a decision event.
    """
    opened_again = _reopen_request(tx, order, units, actor)
    item = _locked_item(tx, order)
    claim = _locked_claim(tx, order)
    reopened = False
    if claim is not None and claim.ends_at > tx.now and (item is not None or claim.kind == "WATCH"):
        state = ClaimState(claim.state)
        if state is ClaimState.FULFILLED or state in LIVE_STATES:
            reserved = claim.qty - claim.qty_missing
            claim.qty_missing = (
                missing_after_losing(claim.qty, claim.qty_missing, min(units, reserved))
                if reserved
                else claim.qty_missing
            )
            if state is ClaimState.FULFILLED:
                move_claim(tx, claim, ClaimState.ACTIVE, actor)
            reopened = True
    if item is not None:
        item.qty_secured = max(0, item.qty_secured - units)
        if ItemState(item.state) is ItemState.SECURED:
            waiting = claim is not None and ClaimState(claim.state) in LIVE_STATES
            move_item(tx, item, ItemState.WAITING if waiting else ItemState.SEARCHING, actor)
        reopened = True
    if opened_again is not None:
        events.post_card(
            tx,
            events.thread_of_request(tx, opened_again.id),
            "request_reopened",
            request_ref=opened_again.ref,
            order_ref=order.ref,
        )
    return reopened


def need_ended(tx: Tx, order: Order, units: int, actor: Actor) -> Claim | None:
    """The client cancelled this reservation (O5) or didn't come for it (O4).

    Inside an open request, the item is cancelled and its claim with it: DawaLink doesn't
    look for that medicine again. Returns the claim if it was just cancelled, so its other
    offers and asks can be withdrawn. A watch that led to this reservation stays fulfilled.
    """
    item = _locked_item(tx, order)
    if item is None:
        return None
    item.qty_secured = max(0, item.qty_secured - units)
    current = ItemState(item.state)
    if current in FINAL_ITEM_STATES and current is not ItemState.SECURED:
        return None
    if not ITEM_MACHINE.allows(current, ItemState.CANCELLED, actor):
        # A no-show on a partly secured item: the search for it goes on.
        return None
    move_item(tx, item, ItemState.CANCELLED, actor)
    claim = _locked_claim(tx, order)
    if claim is None or not CLAIM_MACHINE.allows(
        ClaimState(claim.state), ClaimState.CANCELLED, actor
    ):
        return None
    move_claim(tx, claim, ClaimState.CANCELLED, actor)
    return claim


def withdraw_asks(tx: Tx, claim: Claim, *, fulfilled: bool) -> int:
    """The need no longer needs its early-release asks (R-W3, R-E7).

    Open asks become WITHDRAWN, and the claim's open early-release request ends:
    FULFILLED when the client accepted its offer, CANCELLED otherwise.
    """
    request = tx.session.execute(
        select(EarlyReleaseRequest)
        .where(EarlyReleaseRequest.claim_id == claim.id, EarlyReleaseRequest.state == "OPEN")
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    if request is None:
        return 0
    asked = list(
        tx.session.execute(
            select(EarlyReleaseAsk)
            .where(EarlyReleaseAsk.er_request_id == request.id, EarlyReleaseAsk.state == "ASKED")
            .with_for_update()
        ).scalars()
    )
    for ask in asked:
        ask.state = "WITHDRAWN"
        ask.answered_at = tx.now
    withdrawn = len(asked)
    request.state = "FULFILLED" if fulfilled else "CANCELLED"
    request.closed_at = tx.now
    audit.record(
        tx,
        Actor.CLIENT if fulfilled else Actor.SYSTEM,
        "early_release.close",
        "early_release_request",
        request.id,
        before={"state": "OPEN"},
        after={"state": request.state, "asks_withdrawn": withdrawn},
    )
    return withdrawn
