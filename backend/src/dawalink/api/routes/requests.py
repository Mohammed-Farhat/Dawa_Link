"""Sourcing requests, offers and the demo clock (docs/06 §6.3, §6.5, §6.10).

A request is **created** only by the tap on the agent's [Start sourcing] card
(`/proposals/{id}/execute`, BLD-D30). Here the client reads it, cancels it, and answers
the offers it brings.
"""

import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Response
from sqlalchemy import select

from dawalink.api import present
from dawalink.api.deps import AsAdmin, AsClient, DoWork, IdempotencyKey, TheSettings
from dawalink.api.schemas.orders import Reservation
from dawalink.api.schemas.requests import (
    AcceptOffer,
    AdvanceClock,
    DemoClock,
    Offer,
    Offers,
    RequestItem,
    ReservationRef,
    SourcingRequest,
    SourcingRequests,
    Waiting,
)
from dawalink.api.schemas.search import DayHours
from dawalink.db.models import (
    Claim,
    Conversation,
    EarlyReleaseAsk,
    EarlyReleaseRequest,
    InventoryItem,
    Order,
    Pharmacy,
    Product,
)
from dawalink.db.models import RequestItem as ItemRow
from dawalink.db.models import SourcingRequest as RequestRow
from dawalink.domain.claims import LIVE_STATES
from dawalink.domain.expiry import fits
from dawalink.domain.numbers import MAX_PAGE_SIZE
from dawalink.domain.orders import OrderSource, OrderState
from dawalink.domain.pickup import pharmacy_pickup_days
from dawalink.services import clock, orders, pharmacies, requests
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

router = APIRouter(tags=["requests"])

_HELD = (OrderState.RESERVED.value, OrderState.PICKED_UP.value)


def _item_words(item: ItemRow, waiting: Waiting | None = None) -> str:
    """A medicine's state in plain words (docs/03 §1.1): never a raw state."""
    missing = item.qty - item.qty_secured
    if item.state == "SECURED":
        return "Reserved"
    if item.state == "CANCELLED":
        return "Stopped"
    if item.state == "UNAVAILABLE":
        return (
            "Not found in time"
            if item.qty_secured == 0
            else f"{item.qty_secured} of {item.qty} reserved; the rest was not found in time"
        )
    if waiting is not None and waiting.open_offer_ids:
        # A box is held for the client and waits for their tap: say so, as the page does
        # (B#17), never "still looking".
        return "An offer is waiting for you: see it below"
    if item.qty_secured:
        return f"{item.qty_secured} of {item.qty} reserved, looking for {missing} more"
    return {
        "PROPOSED": "Found: see the card to reserve",
        "WAITING": "Not listed yet: still looking",
    }.get(item.state, "Searching")


def _requests(tx: Tx, rows: list[RequestRow]) -> list[SourcingRequest]:
    if not rows:
        return []
    lbp_per_usd = present.rate(tx)
    ids = [row.id for row in rows]
    items = list(
        tx.session.execute(
            select(ItemRow).where(ItemRow.request_id.in_(ids)).order_by(ItemRow.position)
        ).scalars()
    )
    item_ids = [item.id for item in items]
    products = {
        product.id: product
        for product in tx.session.execute(
            select(Product).where(Product.id.in_({item.product_id for item in items}))
        ).scalars()
    }
    held: dict[uuid.UUID | None, list[ReservationRef]] = {}
    for order, pharmacy_name in tx.session.execute(
        select(Order, Pharmacy.name)
        .join(Pharmacy, Pharmacy.id == Order.pharmacy_id)
        .where(Order.request_item_id.in_(item_ids), Order.state.in_(_HELD))
        .order_by(Order.created_at)
    ):
        held.setdefault(order.request_item_id, []).append(
            ReservationRef(
                id=order.id,
                ref=order.ref,
                pharmacy_name=pharmacy_name,
                qty=order.qty_picked_up or order.qty_locked,
            )
        )
    claims = {
        claim.request_item_id: claim
        for claim in tx.session.execute(
            select(Claim).where(
                Claim.request_item_id.in_(item_ids),
                Claim.state.in_([state.value for state in LIVE_STATES]),
            )
        ).scalars()
    }
    threads = dict(
        tx.session.execute(
            select(Conversation.request_id, Conversation.id).where(Conversation.request_id.in_(ids))
        ).all()
    )

    def waiting(item: ItemRow) -> Waiting | None:
        claim = claims.get(item.id)
        if claim is None:
            return None
        asks = list(
            tx.session.execute(
                select(EarlyReleaseAsk.respond_by)
                .join(EarlyReleaseRequest, EarlyReleaseRequest.id == EarlyReleaseAsk.er_request_id)
                .where(
                    EarlyReleaseRequest.claim_id == claim.id,
                    EarlyReleaseRequest.state == "OPEN",
                    EarlyReleaseAsk.state == "ASKED",
                )
            ).scalars()
        )
        offers = list(
            tx.session.execute(
                select(Order.id).where(Order.claim_id == claim.id, Order.state == "OFFERED")
            ).scalars()
        )
        return Waiting(
            watching_new_stock=True,
            asked_pharmacies=len(asks),
            answers_by=max(asks) if asks else None,
            open_offer_ids=offers,
        )

    shown = []
    for row in rows:
        own = [item for item in items if item.request_id == row.id]
        waits = {item.id: waiting(item) for item in own}
        shown.append(
            SourcingRequest(
                id=row.id,
                ref=row.ref,
                state=row.state,
                outcome=row.outcome,
                alternatives_ok=row.alternatives_ok,
                ends_at=row.ends_at,
                items=[
                    RequestItem(
                        id=item.id,
                        position=item.position,
                        product=present.product_summary(products[item.product_id], lbp_per_usd),
                        qty=item.qty,
                        qty_secured=item.qty_secured,
                        days_of_use=item.days_of_use,
                        max_price=(
                            present.money(item.max_price_lbp, lbp_per_usd)
                            if item.max_price_lbp is not None
                            else None
                        ),
                        state=item.state,
                        status_text=_item_words(item, waits[item.id]),
                        reservations=held.get(item.id, []),
                        waiting=waits[item.id],
                    )
                    for item in own
                ],
                units_wanted=sum(item.qty for item in own if item.state != "CANCELLED"),
                units_secured=sum(item.qty_secured for item in own),
                conversation_id=threads.get(row.id),
                created_at=row.created_at,
                closed_at=row.closed_at,
                server_now=tx.now,
            )
        )
    return shown


def _own(tx: Tx, client_id: uuid.UUID, request_id: uuid.UUID) -> RequestRow:
    row = tx.session.get(RequestRow, request_id)
    if row is None or row.client_id != client_id:
        raise ServiceError(Code.NOT_FOUND, "Unknown request.")
    return row


@router.get("/requests")
def list_requests(
    caller: AsClient, work: DoWork, state: Literal["open", "closed"] = "open"
) -> SourcingRequests:
    """The client's requests: the open ones (2 at most, R-RQ2), or the closed ones, the
    newest first."""
    with work.tx() as tx:
        statement = select(RequestRow).where(
            RequestRow.client_id == caller.user_id, RequestRow.state == state.upper()
        )
        rows = list(
            tx.session.execute(
                statement.order_by(RequestRow.created_at.desc()).limit(MAX_PAGE_SIZE)
            ).scalars()
        )
        return SourcingRequests(items=_requests(tx, rows), server_now=tx.now)


@router.get("/requests/{request_id}")
def read_request(request_id: uuid.UUID, caller: AsClient, work: DoWork) -> SourcingRequest:
    with work.tx() as tx:
        return _requests(tx, [_own(tx, caller.user_id, request_id)])[0]


@router.post("/requests/{request_id}/cancel")
def cancel_request(request_id: uuid.UUID, caller: AsClient, work: DoWork) -> SourcingRequest:
    """The client stops the search. What is already reserved stays reserved (R-RQ9)."""
    with work.tx() as tx:
        _own(tx, caller.user_id, request_id)
        cancelled = requests.cancel_request(tx, caller.user_id, request_id)
        tx.session.flush()
        return _requests(tx, [cancelled])[0]


# --- Offers ------------------------------------------------------------------------------


def _offers(tx: Tx, rows: list[Order]) -> list[Offer]:
    if not rows:
        return []
    lbp_per_usd = present.rate(tx)
    shops = present.pharmacy_cards(tx, [row.pharmacy_id for row in rows])
    hours = pharmacies.weekly_hours(tx, [row.pharmacy_id for row in rows])
    pickup_days = dict(
        tx.session.execute(
            select(Pharmacy.id, Pharmacy.pickup_days).where(
                Pharmacy.id.in_({row.pharmacy_id for row in rows})
            )
        ).all()
    )
    products = {
        product.id: product
        for product in tx.session.execute(
            select(Product).where(Product.id.in_({row.product_id for row in rows}))
        ).scalars()
    }
    expiries = dict(
        tx.session.execute(
            select(InventoryItem.id, InventoryItem.expiry_date).where(
                InventoryItem.id.in_({row.inventory_item_id for row in rows})
            )
        ).all()
    )
    request_of_item = dict(
        tx.session.execute(
            select(ItemRow.id, ItemRow.request_id).where(
                ItemRow.id.in_({row.request_item_id for row in rows if row.request_item_id})
            )
        ).all()
    )
    shown = []
    for row in rows:
        product = products[row.product_id]
        expiry = expiries[row.inventory_item_id]
        allowed = [
            day
            for day in pharmacy_pickup_days(
                hours[row.pharmacy_id], pickup_days[row.pharmacy_id], tx.now
            )
            if fits(expiry, day, row.days_of_use)
        ]
        assert row.offer_expires_at is not None
        shown.append(
            Offer(
                id=row.id,
                kind=(
                    "early_release" if row.source == OrderSource.EARLY_RELEASE.value else "matching"
                ),
                product=present.product_summary(product, lbp_per_usd),
                pharmacy=shops[row.pharmacy_id],
                qty=row.qty_locked,
                price_each=present.money(row.price_snapshot_lbp, lbp_per_usd),
                total=present.money(row.price_snapshot_lbp * row.qty_locked, lbp_per_usd),
                saving=present.money(
                    max(0, product.public_price_lbp - row.price_snapshot_lbp) * row.qty_locked,
                    lbp_per_usd,
                ),
                expiry_date=expiry,
                days_of_use=row.days_of_use,
                expires_at=row.offer_expires_at,
                pickup_days_allowed=allowed,
                request_id=request_of_item.get(row.request_item_id)
                if row.request_item_id
                else None,
                pickup_day_hours=[
                    DayHours(day=day, hours=pharmacies.day_hours(hours[row.pharmacy_id], day))
                    for day in allowed
                ],
            )
        )
    return shown


@router.get("/offers")
def list_offers(caller: AsClient, work: DoWork) -> Offers:
    """The offers waiting for the client's answer, the one that ends soonest first."""
    with work.tx() as tx:
        rows = list(
            tx.session.execute(
                select(Order)
                .where(
                    Order.client_id == caller.user_id,
                    Order.state == OrderState.OFFERED.value,
                    Order.offer_expires_at > tx.now,
                )
                .order_by(Order.offer_expires_at)
            ).scalars()
        )
        return Offers(items=_offers(tx, rows), server_now=tx.now)


@router.post("/offers/{offer_id}/accept", status_code=201)
def accept_offer(
    offer_id: uuid.UUID, body: AcceptOffer, caller: AsClient, work: DoWork, _key: IdempotencyKey
) -> Reservation:
    """The offer becomes a reservation; the need's other offers are withdrawn at once
    (O9). An offer is accepted once: a second tap answers with the reservation the first
    one made, as it is (its pickup day included), and reserves nothing more."""
    with work.tx() as tx:
        order = orders.accept_offer(tx, caller.user_id, offer_id, body.pickup_day)
        return present.reservations(tx, [order])[0]


@router.post("/offers/{offer_id}/decline", status_code=204)
def decline_offer(offer_id: uuid.UUID, caller: AsClient, work: DoWork) -> Response:
    """ "No thanks": the box goes to the next client who waits for it (O10)."""
    with work.tx() as tx:
        ended = orders.end_offer(tx, offer_id, declined_by=caller.user_id)
        if ended is None:
            raise ServiceError(Code.OFFER_NOT_OPEN, "This offer is no longer open.")
    return Response(status_code=204)


# --- The demo clock (R-DEMO) -----------------------------------------------------------------


@router.get("/admin/demo-clock")
def read_demo_clock(_caller: AsAdmin, work: DoWork, settings: TheSettings) -> DemoClock:
    with work.tx() as tx:
        offset = clock.demo_offset(tx) if settings.demo_mode else timedelta(0)
        return DemoClock(
            server_now=tx.now,
            offset_minutes=int(offset.total_seconds() // 60),
            demo_mode=settings.demo_mode,
        )


@router.post("/admin/demo-clock/advance")
def advance_demo_clock(
    body: AdvanceClock, caller: AsAdmin, work: DoWork, settings: TheSettings
) -> DemoClock:
    """Moves the app's time forward, to show time-based behavior live: an offer expiring,
    the one-hour-left check, a no-show. **Demo mode only**, and every move is audited
    (R-DEMO). Logins are counted in real time, so nobody is logged out by it."""
    if not settings.demo_mode:
        raise ServiceError(Code.DEMO_MODE_OFF, "The demo clock is off.")
    with work.tx() as tx:
        offset = clock.advance_demo_clock(
            tx,
            caller.user_id,
            timedelta(minutes=body.minutes),
            demo_mode=True,
            reason=body.reason,
        )
        return DemoClock(
            server_now=tx.now + timedelta(minutes=body.minutes),
            offset_minutes=int(offset.total_seconds() // 60),
            demo_mode=True,
        )
