"""Sourcing requests: "find these medicines for me now" (docs/04 SM-8, R-RQ, ADR-002).

The client starts a request with a tap. The agent then owns it for the six-hour window:
it plans, proposes cards, opens claims and asks pharmacies. What it can never do is
reserve, accept, cancel or give up on an item (R-RQ4, INV-11): those are the client's
taps and the system's rules, and they are the functions of this module that take a
`client_id` or are run by the clock check.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import func, select

from dawalink.db.models import Claim, Conversation, Order, Product, RequestItem, SourcingRequest
from dawalink.domain.claims import LIVE_STATES, ClaimState
from dawalink.domain.numbers import (
    DEFAULT_DAYS_OF_USE,
    MAX_ITEMS_PER_REQUEST,
    MAX_OPEN_REQUESTS,
    MAX_UNITS_PER_GROUP,
)
from dawalink.domain.refs import new_ref
from dawalink.domain.requests import (
    FINAL_ITEM_STATES,
    REQUEST_MACHINE,
    ItemProgress,
    ItemState,
    RequestOutcome,
    RequestState,
    closing_outcome,
    should_close,
)
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import ClaimKind, ClaimSource
from dawalink.domain.windows import search_window_end, window_check_at
from dawalink.services import audit, catalog, claims, clients, events, matching, needs, orders
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.events import Decision
from dawalink.services.notify import Template, notify
from dawalink.services.travel import Location

LIVE = tuple(state.value for state in LIVE_STATES)


@dataclass(frozen=True)
class RequestLine:
    """One medicine the client asks for."""

    product_id: uuid.UUID
    qty: int = 1
    days_of_use: int = DEFAULT_DAYS_OF_USE
    max_price_lbp: int | None = None


def _new_ref(tx: Tx) -> str:
    while True:
        ref = new_ref("Q")
        if (
            tx.session.execute(
                select(SourcingRequest.id).where(SourcingRequest.ref == ref)
            ).scalar()
            is None
        ):
            return ref


def _own_open_request(tx: Tx, client_id: uuid.UUID, request_id: uuid.UUID) -> SourcingRequest:
    request = tx.session.execute(
        select(SourcingRequest)
        .where(SourcingRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    if request is None or request.client_id != client_id:
        raise ServiceError(Code.NOT_FOUND, "Unknown request.")
    if request.state != RequestState.OPEN.value:
        raise ServiceError(Code.REQUEST_CLOSED, "This request is closed.")
    return request


def items_of(tx: Tx, request_id: uuid.UUID, *, lock: bool = False) -> list[RequestItem]:
    statement = (
        select(RequestItem)
        .where(RequestItem.request_id == request_id)
        .order_by(RequestItem.position)
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return list(tx.session.execute(statement).scalars())


def _thread(tx: Tx, request_id: uuid.UUID) -> uuid.UUID | None:
    return events.thread_of_request(tx, request_id)


# --- The client's taps ----------------------------------------------------------------


def create_request(
    tx: Tx,
    *,
    client_id: uuid.UUID,
    lines: Sequence[RequestLine],
    location: Location,
    alternatives_ok: bool,
    idempotency_key: str,
) -> SourcingRequest:
    """[Start sourcing]: the request, its items and its thread (R-RQ1).

    The agent's first turn is asked for at once, so what is listed is reported within
    seconds; the window is how long DawaLink keeps trying for the rest (R-T8).
    """
    client = clients.profile(tx, client_id, lock=True)
    clients.require_reserve(tx, client)
    done = tx.session.execute(
        select(SourcingRequest).where(
            SourcingRequest.client_id == client_id,
            SourcingRequest.idempotency_key == idempotency_key,
        )
    ).scalar()
    if done is not None:
        return done
    claims.require_request_hours(tx)
    if not 1 <= len(lines) <= MAX_ITEMS_PER_REQUEST:
        raise ServiceError(Code.VALIDATION_ERROR, "A request has 1 to 5 medicines.")
    if len({line.product_id for line in lines}) != len(lines):
        raise ServiceError(Code.VALIDATION_ERROR, "Each medicine appears once in a request.")
    for line in lines:
        catalog.allowed_product(tx, line.product_id)
        if not 1 <= line.qty <= MAX_UNITS_PER_GROUP or line.days_of_use < 1:
            raise ServiceError(Code.VALIDATION_ERROR, "Quantity is 1 to 3; days of use start at 1.")
        if line.max_price_lbp is not None and line.max_price_lbp < 0:
            raise ServiceError(Code.VALIDATION_ERROR, "A budget can't be negative.")
    open_requests = tx.session.execute(
        select(func.count())
        .select_from(SourcingRequest)
        .where(SourcingRequest.client_id == client_id, SourcingRequest.state == "OPEN")
    ).scalar_one()
    if open_requests >= MAX_OPEN_REQUESTS:
        raise ServiceError(Code.LIMIT_OPEN_REQUESTS, "You have 2 open requests (the maximum).")

    request = SourcingRequest(
        id=uuid.uuid4(),
        ref=_new_ref(tx),
        client_id=client_id,
        district_id=location.district_id or client.district_id,
        loc_lat=location.point.lat,
        loc_lon=location.point.lon,
        loc_source=location.source,
        alternatives_ok=alternatives_ok,
        ends_at=search_window_end(tx.now),
        idempotency_key=idempotency_key,
        created_at=tx.now,
    )
    tx.session.add(request)
    tx.session.flush()
    for position, line in enumerate(lines, start=1):
        tx.session.add(
            RequestItem(
                id=uuid.uuid4(),
                request_id=request.id,
                position=position,
                product_id=line.product_id,
                qty=line.qty,
                days_of_use=line.days_of_use,
                max_price_lbp=line.max_price_lbp,
            )
        )
    conversation = Conversation(
        id=uuid.uuid4(),
        client_id=client_id,
        kind="request",
        request_id=request.id,
        # The location lives beside the case state, never in it (INV-24).
        loc_lat=location.point.lat,
        loc_lon=location.point.lon,
        loc_source=location.source,
        loc_area_id=location.area_id,
        loc_set_at=tx.now,
        last_activity_at=tx.now,
    )
    tx.session.add(conversation)
    tx.session.flush()
    audit.record(
        tx,
        Actor.CLIENT,
        "request.create",
        "sourcing_request",
        request.id,
        actor_id=client_id,
        after={"state": "OPEN", "items": len(lines)},
    )
    events.post_decision(tx, conversation.id, Decision.REQUEST_SUBMITTED, request_id=request.id)
    return request


def _cancel_item(tx: Tx, item: RequestItem, actor: Actor, reason: str) -> None:
    """An item is given up by the client: its claim, offers and asks end with it."""
    if ItemState(item.state) in FINAL_ITEM_STATES:
        return
    claim = tx.session.execute(
        select(Claim)
        .where(Claim.request_item_id == item.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    if claim is not None and ClaimState(claim.state) in LIVE_STATES:
        orders.withdraw_offers(tx, claim.id, reason=reason)
        needs.withdraw_asks(tx, claim, fulfilled=False)
        needs.move_claim(tx, claim, ClaimState.CANCELLED, actor)
    needs.move_item(tx, item, ItemState.CANCELLED, actor)


def _lock_offer_items(tx: Tx, request_id: uuid.UUID) -> None:
    """Locks the boxes held by this request's open offers: items come before orders."""
    claim_ids = list(
        tx.session.execute(
            select(Claim.id)
            .join(RequestItem, RequestItem.id == Claim.request_item_id)
            .where(RequestItem.request_id == request_id)
        ).scalars()
    )
    orders.lock_items(tx, [o.inventory_item_id for o in orders.open_offers(tx, claim_ids)])


def cancel_request(tx: Tx, client_id: uuid.UUID, request_id: uuid.UUID) -> SourcingRequest:
    """The client stops the search. What is already reserved stays reserved."""
    clients.profile(tx, client_id, lock=True)
    _lock_offer_items(tx, request_id)
    request = _own_open_request(tx, client_id, request_id)
    for item in items_of(tx, request.id, lock=True):
        _cancel_item(tx, item, Actor.CLIENT, "the client cancelled the request")
    _close(tx, request, RequestOutcome.CANCELLED, Actor.CLIENT, actor_id=client_id)
    return request


def remove_item(tx: Tx, client_id: uuid.UUID, request_item_id: uuid.UUID) -> RequestItem:
    """The client drops one medicine from the request (the agent may only propose it)."""
    clients.profile(tx, client_id, lock=True)
    seen = tx.session.get(RequestItem, request_item_id)
    if seen is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown request item.")
    _lock_offer_items(tx, seen.request_id)
    request = _own_open_request(tx, client_id, seen.request_id)
    item = next(i for i in items_of(tx, request.id, lock=True) if i.id == request_item_id)
    _cancel_item(tx, item, Actor.CLIENT, "the client removed the item")
    return item


def change_constraints(
    tx: Tx,
    client_id: uuid.UUID,
    request_id: uuid.UUID,
    *,
    alternatives_ok: bool | None = None,
    max_prices: Mapping[uuid.UUID, int | None] | None = None,
) -> SourcingRequest:
    """The client changes the budget or allows other brands. Waiting claims follow."""
    clients.profile(tx, client_id, lock=True)
    request = _own_open_request(tx, client_id, request_id)
    before = {"alternatives_ok": request.alternatives_ok}
    if alternatives_ok is not None:
        request.alternatives_ok = alternatives_ok
    for item in items_of(tx, request.id, lock=True):
        if max_prices is not None and item.id in max_prices:
            price = max_prices[item.id]
            if price is not None and price < 0:
                raise ServiceError(Code.VALIDATION_ERROR, "A budget can't be negative.")
            item.max_price_lbp = price
        claim = tx.session.execute(
            select(Claim)
            .where(Claim.request_item_id == item.id, Claim.state.in_(LIVE))
            .with_for_update()
        ).scalar()
        if claim is not None:
            claim.max_price_lbp = item.max_price_lbp
            matching.defer_for_product(tx, tx.session.get_one(Product, claim.product_id))
    audit.record(
        tx,
        Actor.CLIENT,
        "request.change_constraints",
        "sourcing_request",
        request.id,
        actor_id=client_id,
        before=before,
        after={"alternatives_ok": request.alternatives_ok},
    )
    return request


def items_unticked(
    tx: Tx, client_id: uuid.UUID, request_id: uuid.UUID, item_ids: Sequence[uuid.UUID]
) -> None:
    """The client left some items of a plan card unticked: the agent looks again (R-RQ6)."""
    request = _own_open_request(tx, client_id, request_id)
    changed = []
    for item in items_of(tx, request.id, lock=True):
        if item.id in item_ids and ItemState(item.state) is ItemState.PROPOSED:
            needs.move_item(tx, item, ItemState.SEARCHING, Actor.CLIENT)
            changed.append(str(item.id))
    if changed:
        events.post_decision(
            tx,
            _thread(tx, request.id),
            Decision.ITEMS_UNTICKED,
            request_id=request.id,
            items=changed,
        )


def group_item_failed(
    tx: Tx, client_id: uuid.UUID, request_id: uuid.UUID, failed: Sequence[Mapping[str, object]]
) -> None:
    """A plan card couldn't be reserved: nothing was, and the agent hears which item (R-RQ6)."""
    request = _own_open_request(tx, client_id, request_id)
    for item in items_of(tx, request.id, lock=True):
        if ItemState(item.state) is ItemState.PROPOSED:
            needs.move_item(tx, item, ItemState.SEARCHING, Actor.SYSTEM)
    events.post_decision(
        tx,
        _thread(tx, request.id),
        Decision.GROUP_ITEM_FAILED,
        request_id=request.id,
        failed_items=[
            {"request_item_id": str(f.get("request_item_id")), "code": f.get("code")}
            for f in failed
        ],
    )


# --- What the agent may do without a tap (R-RQ4) --------------------------------------


def _open_item(tx: Tx, request_item_id: uuid.UUID) -> tuple[SourcingRequest, RequestItem]:
    seen = tx.session.get(RequestItem, request_item_id)
    if seen is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown request item.")
    request = tx.session.execute(
        select(SourcingRequest)
        .where(SourcingRequest.id == seen.request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if request.state != RequestState.OPEN.value:
        raise ServiceError(Code.REQUEST_CLOSED, "This request is closed.")
    item = next(i for i in items_of(tx, request.id, lock=True) if i.id == request_item_id)
    return request, item


def open_claim(tx: Tx, request_item_id: uuid.UUID) -> Claim:
    """The agent starts waiting for stock for an item (R-W1, the tool `open_claim`).

    The item's place in the queue is the moment this is called, from the app clock.
    Calling it again returns the same claim (R-AG6).

    Request hours aren't checked here: the request itself was started during them, and
    its 6 hours are what the client was promised, so the agent may start waiting for
    one of its medicines at 21:00 (decision log BLD-D6). A watch keeps the rule.
    """
    seen = tx.session.get(RequestItem, request_item_id)
    if seen is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown request item.")
    client_id = tx.session.execute(
        select(SourcingRequest.client_id).where(SourcingRequest.id == seen.request_id)
    ).scalar_one()
    clients.require_reserve(tx, clients.profile(tx, client_id, lock=True))
    request, item = _open_item(tx, request_item_id)
    existing = tx.session.execute(select(Claim).where(Claim.request_item_id == item.id)).scalar()
    if existing is not None and ClaimState(existing.state) in LIVE_STATES:
        return existing
    if existing is not None or ItemState(item.state) in FINAL_ITEM_STATES:
        raise ServiceError(Code.CLAIM_NOT_ACTIVE, "This item isn't being searched for any more.")
    if item.qty_secured >= item.qty:
        raise ServiceError(Code.CLAIM_NOT_ACTIVE, "This item is already secured.")
    product = catalog.allowed_product(tx, item.product_id)
    claim = Claim(
        id=uuid.uuid4(),
        kind=ClaimKind.REQUEST_ITEM.value,
        source=ClaimSource.REQUEST.value,
        client_id=request.client_id,
        request_item_id=item.id,
        product_id=product.id,
        equivalence_key=product.equivalence_key,
        district_id=request.district_id,
        loc_lat=request.loc_lat,
        loc_lon=request.loc_lon,
        days_of_use=item.days_of_use,
        max_price_lbp=item.max_price_lbp,
        qty=item.qty,
        qty_missing=item.qty - item.qty_secured,
        ends_at=request.ends_at,
        state=ClaimState.ACTIVE.value,
        created_at=tx.now,
    )
    tx.session.add(claim)
    tx.session.flush()
    audit.record(
        tx,
        Actor.AGENT,
        "claim.create",
        "claim",
        claim.id,
        after={"state": claim.state, "kind": claim.kind, "qty": claim.qty_missing},
    )
    if ItemState(item.state) is ItemState.SEARCHING:
        needs.move_item(tx, item, ItemState.WAITING, Actor.AGENT)
    matching.defer_for_product(tx, product)
    return claim


def items_proposed(tx: Tx, request_id: uuid.UUID, item_ids: Sequence[uuid.UUID]) -> int:
    """The agent showed a plan card for these items: they wait for the client's tap."""
    request = tx.session.get(SourcingRequest, request_id)
    if request is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown request.")
    if request.state != RequestState.OPEN.value:
        raise ServiceError(Code.REQUEST_CLOSED, "This request is closed.")
    moved = 0
    for item in items_of(tx, request_id, lock=True):
        if item.id in item_ids and ItemState(item.state) in (
            ItemState.SEARCHING,
            ItemState.WAITING,
        ):
            needs.move_item(tx, item, ItemState.PROPOSED, Actor.AGENT)
            moved += 1
    if moved:
        notify(
            tx,
            request.client_id,
            Template.PLAN_READY,
            {"request_ref": request.ref, "items": moved},
            event=f"request:{request.id}:plan:{tx.now.isoformat()}",
        )
    return moved


# --- The system's rules: the window check and closing ---------------------------------


def run_window_check(tx: Tx, request_id: uuid.UUID) -> bool:
    """One hour before the window ends, the agent gets a last chance (N-24, R-RQ3). Once."""
    request = tx.session.execute(
        select(SourcingRequest)
        .where(SourcingRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if request.state != RequestState.OPEN.value or request.window_checked_at is not None:
        return False
    if tx.now < window_check_at(request.ends_at):
        return False
    request.window_checked_at = tx.now
    missing = [
        item for item in items_of(tx, request.id) if ItemState(item.state) not in FINAL_ITEM_STATES
    ]
    if not missing:
        return True
    notify(
        tx,
        request.client_id,
        Template.WINDOW_ENDING,
        {"request_ref": request.ref, "items_missing": len(missing)},
        event=f"request:{request.id}",
    )
    events.post_decision(
        tx,
        _thread(tx, request.id),
        Decision.WINDOW_CHECK,
        request_id=request.id,
        items=[str(item.id) for item in missing],
    )
    return True


def _close(
    tx: Tx,
    request: SourcingRequest,
    outcome: RequestOutcome,
    actor: Actor,
    *,
    actor_id: uuid.UUID | None = None,
) -> None:
    REQUEST_MACHINE.check(RequestState.OPEN, RequestState.CLOSED, actor)
    request.state = RequestState.CLOSED.value
    request.outcome = outcome.value
    request.closed_at = tx.now
    audit.record(
        tx,
        actor,
        "request.close",
        "sourcing_request",
        request.id,
        actor_id=actor_id,
        before={"state": "OPEN"},
        after={"state": "CLOSED", "outcome": outcome.value},
    )
    items = items_of(tx, request.id)
    summary = {
        "request_ref": request.ref,
        "outcome": outcome.value,
        "items": [
            {
                "request_item_id": str(i.id),
                "state": i.state,
                "qty": i.qty,
                "qty_secured": i.qty_secured,
            }
            for i in items
        ],
    }
    notify(tx, request.client_id, Template.REQUEST_CLOSED, summary, event=f"request:{request.id}")
    events.post_card(tx, _thread(tx, request.id), "request_closed", **summary)


def close_if_done(tx: Tx, request_id: uuid.UUID) -> bool:
    """Closes the request when every item is final, or its window ended (R-RQ9).

    An offer made before the end stays valid for its two hours, so it keeps the request
    open. After closing, the outcome never changes.
    """
    _lock_offer_items(tx, request_id)
    request = tx.session.execute(
        select(SourcingRequest)
        .where(SourcingRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if request.state != RequestState.OPEN.value:
        return False
    items = items_of(tx, request.id, lock=True)
    item_ids = [item.id for item in items]
    request_claims = list(
        tx.session.execute(
            select(Claim).where(Claim.request_item_id.in_(item_ids)).with_for_update()
        ).scalars()
    )
    offers_pending = tx.session.execute(
        select(func.count())
        .select_from(Order)
        .where(Order.claim_id.in_([c.id for c in request_claims]), Order.state == "OFFERED")
    ).scalar_one()
    if not should_close(
        [ItemState(item.state) for item in items],
        now=tx.now,
        ends_at=request.ends_at,
        offers_pending=offers_pending,
    ):
        return False
    for claim in request_claims:
        if ClaimState(claim.state) in LIVE_STATES:
            needs.withdraw_asks(tx, claim, fulfilled=False)
            if claim.state == ClaimState.OFFER_PENDING.value:
                needs.move_claim(tx, claim, ClaimState.ACTIVE, Actor.SYSTEM)
            needs.move_claim(tx, claim, ClaimState.EXPIRED, Actor.SYSTEM)
    for item in items:
        if ItemState(item.state) not in FINAL_ITEM_STATES:
            needs.move_item(tx, item, ItemState.UNAVAILABLE, Actor.SYSTEM)
    progress = [ItemProgress(item.qty, item.qty_secured) for item in items]
    _close(tx, request, closing_outcome(progress), Actor.SYSTEM)
    return True
