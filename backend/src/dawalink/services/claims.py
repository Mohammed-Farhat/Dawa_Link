"""Watches: "tell me when this medicine appears" (docs/04 SM-7, R-W).

A watch is a claim: one need for one medicine, waiting for stock for the search window.
`created_at` is the claim's place in the queue, written from the app clock when the watch
is created. Nothing can change it afterwards (R-PRI4).
"""

import uuid

from sqlalchemy import func, select

from dawalink.db.models import Claim, Product
from dawalink.domain.claims import LIVE_STATES, ClaimState
from dawalink.domain.numbers import DEFAULT_DAYS_OF_USE, MAX_UNITS_PER_GROUP, MAX_WATCHES
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import ClaimKind, ClaimSource
from dawalink.domain.windows import in_request_hours, request_hours_open_at, search_window_end
from dawalink.services import audit, catalog, clients, matching, needs, orders
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.notify import Template, notify
from dawalink.services.travel import Location

LIVE = tuple(state.value for state in LIVE_STATES)


def require_request_hours(tx: Tx) -> None:
    """Requests and watches start only during the day (R-T3, INV-22)."""
    if not in_request_hours(tx.now):
        raise ServiceError(
            Code.OUTSIDE_REQUEST_HOURS,
            "DawaLink searches during the day. Please come back tomorrow from 08:00.",
            opens_at=request_hours_open_at(tx.now),
        )


def create_watch(
    tx: Tx,
    *,
    client_id: uuid.UUID,
    product_id: uuid.UUID,
    location: Location,
    source: ClaimSource,
    actor: Actor = Actor.CLIENT,
    qty: int = 1,
    days_of_use: int = DEFAULT_DAYS_OF_USE,
    max_price_lbp: int | None = None,
) -> Claim:
    """[Notify me], or the agent's `create_watch` in a chat (R-W1).

    Asking twice for the same medicine isn't an error to repeat: the answer names the
    watch that already exists, so a retried tool call finds its own work (R-AG6).
    """
    client = clients.profile(tx, client_id, lock=True)
    clients.require_reserve(tx, client)
    require_request_hours(tx)
    product = catalog.allowed_product(tx, product_id)
    if not 1 <= qty <= MAX_UNITS_PER_GROUP or days_of_use < 1:
        raise ServiceError(Code.VALIDATION_ERROR, "Quantity is 1 to 3; days of use start at 1.")
    if max_price_lbp is not None and max_price_lbp < 0:
        raise ServiceError(Code.VALIDATION_ERROR, "A budget can't be negative.")

    live = (
        Claim.client_id == client_id,
        Claim.kind == ClaimKind.WATCH.value,
        Claim.state.in_(LIVE),
    )
    existing = tx.session.execute(
        select(Claim.id).where(*live, Claim.product_id == product_id)
    ).scalar()
    if existing is not None:
        raise ServiceError(
            Code.WATCH_EXISTS, "You're already watching this medicine.", watch_id=existing
        )
    count = tx.session.execute(select(func.count()).select_from(Claim).where(*live)).scalar_one()
    if count >= MAX_WATCHES:
        raise ServiceError(Code.LIMIT_WATCHES, "You have 5 watches (the maximum).")

    claim = Claim(
        id=uuid.uuid4(),
        kind=ClaimKind.WATCH.value,
        source=source.value,
        client_id=client_id,
        product_id=product.id,
        equivalence_key=product.equivalence_key,
        district_id=location.district_id or client.district_id,
        loc_lat=location.point.lat,
        loc_lon=location.point.lon,
        days_of_use=days_of_use,
        max_price_lbp=max_price_lbp,
        qty=qty,
        qty_missing=qty,
        ends_at=search_window_end(tx.now),
        state=ClaimState.ACTIVE.value,
        # The place in the queue: the app clock's time, not the database's (R-PRI2).
        created_at=tx.now,
    )
    tx.session.add(claim)
    tx.session.flush()
    audit.record(
        tx,
        actor,
        "claim.create",
        "claim",
        claim.id,
        actor_id=client_id,
        after={"state": claim.state, "kind": claim.kind, "qty": qty},
    )
    # Stock that is already visible must not be missed (R-PRI1).
    matching.defer_for_product(tx, product)
    return claim


def cancel_watch(tx: Tx, client_id: uuid.UUID, claim_id: uuid.UUID) -> Claim:
    """The client stops watching. Any offer it held goes to the next claim."""
    clients.profile(tx, client_id, lock=True)
    seen = tx.session.get(Claim, claim_id)
    if seen is None or seen.client_id != client_id or seen.kind != ClaimKind.WATCH.value:
        raise ServiceError(Code.NOT_FOUND, "Unknown watch.")
    # Items before orders, orders before the claim (docs/05 §6).
    orders.lock_items(tx, [o.inventory_item_id for o in orders.open_offers(tx, [claim_id])])
    claim = needs.lock_claim(tx, claim_id)
    if ClaimState(claim.state) not in LIVE_STATES:
        raise ServiceError(
            Code.CLAIM_NOT_ACTIVE, "This watch has already ended.", state=claim.state
        )
    orders.withdraw_offers(tx, claim.id, reason="the client cancelled the watch")
    needs.withdraw_asks(tx, claim, fulfilled=False)
    needs.move_claim(tx, claim, ClaimState.CANCELLED, Actor.CLIENT)
    return claim


def expire_watch(tx: Tx, claim_id: uuid.UUID) -> bool:
    """A watch's window ended (SM-7). Run by the clock check.

    A watch with an offer still pending waits for that offer: an offer made before the end
    stays valid for its two hours.
    """
    claim = needs.lock_claim(tx, claim_id)
    if claim.kind != ClaimKind.WATCH.value or ClaimState(claim.state) not in LIVE_STATES:
        return False
    if claim.ends_at > tx.now or orders.open_offers(tx, [claim.id]):
        return False
    if claim.state == ClaimState.OFFER_PENDING.value:
        needs.move_claim(tx, claim, ClaimState.ACTIVE, Actor.SYSTEM)
    needs.withdraw_asks(tx, claim, fulfilled=False)
    needs.move_claim(tx, claim, ClaimState.EXPIRED, Actor.SYSTEM)
    if claim.qty_missing == claim.qty:
        product = tx.session.get_one(Product, claim.product_id)
        notify(
            tx,
            claim.client_id,
            Template.WATCH_ENDED,
            {"product": product.moph_name},
            event=f"claim:{claim.id}",
        )
    return True
