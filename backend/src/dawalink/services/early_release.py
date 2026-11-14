"""Early release: asking pharmacies to release stock they hold privately (docs/04 SM-6, R-E).

The agent starts it, for one claim. Up to three open pharmacies nearby are asked at once
and have two hours to answer. A pharmacy that accepts makes an **offer**: the client still
has to tap to reserve (INV-11).

Privacy both ways (R-E8): the client and the agent only learn how many pharmacies were
asked, never which, until one accepts. A pharmacy never learns who the client is.
"""

import uuid
from dataclasses import dataclass
from datetime import time, timedelta

from sqlalchemy import func, select

from dawalink.db.models import (
    Claim,
    ClientProfile,
    EarlyReleaseAsk,
    EarlyReleaseRequest,
    InventoryItem,
    Order,
    Pharmacy,
    Product,
)
from dawalink.domain.clock import at_beirut
from dawalink.domain.early_release import (
    ASK_MACHINE,
    AskCandidate,
    AskState,
    is_valid_acceptance,
    pharmacies_to_ask,
)
from dawalink.domain.numbers import (
    EARLY_RELEASE_DECLINE_MEMORY,
    EARLY_RELEASE_MAX_DAYS,
    MAX_OPEN_EARLY_RELEASE_REQUESTS,
    NEAR_EXPIRY_MAX_DAYS,
    SAME_PRODUCT_EARLY_RELEASE_WAIT,
)
from dawalink.domain.opening_hours import is_open
from dawalink.domain.orders import OrderSource
from dawalink.domain.pricing import early_release_suggested_price_lbp
from dawalink.domain.state_machine import Actor
from dawalink.domain.windows import early_release_respond_by
from dawalink.services import (
    audit,
    catalog,
    clients,
    events,
    matching,
    needs,
    orders,
    pharmacies,
    travel,
)
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.events import Decision
from dawalink.services.notify import Template, notify

# The reasons a pharmacy can give. Codes only: nothing a pharmacy types reaches the agent (R-AG8).
DECLINE_REASONS = frozenset({"keeping_it", "no_longer_in_stock", "price", "other"})


@dataclass(frozen=True)
class Asked:
    """All the client and the agent may know: how many pharmacies were asked (R-E8)."""

    request_id: uuid.UUID | None
    pharmacies_asked: int


def _move_ask(
    tx: Tx, ask: EarlyReleaseAsk, target: AskState, actor: Actor, **after: object
) -> None:
    current = AskState(ask.state)
    ASK_MACHINE.check(current, target, actor)
    ask.state = target.value
    ask.answered_at = tx.now
    audit.record(
        tx,
        actor,
        "early_release_ask.state",
        "early_release_ask",
        ask.id,
        actor_id=ask.pharmacy_id if actor is Actor.PHARMACY else None,
        before={"state": current.value},
        after={"state": target.value, **after},
    )


def _candidates(
    tx: Tx, claim: Claim, product: Product
) -> tuple[list[AskCandidate], dict[tuple[str, object], InventoryItem]]:
    """Private boxes of the medicine near the client, as the selection rule sees them (R-E2)."""
    location = matching.location_of(tx, claim)
    if location is None:
        return [], {}
    wanted = [product.id]  # never another brand (R-C10)
    rows = tx.session.execute(
        select(InventoryItem, Pharmacy)
        .join(Pharmacy, Pharmacy.id == InventoryItem.pharmacy_id)
        .where(
            InventoryItem.product_id.in_(wanted),
            Pharmacy.status == "APPROVED",
            InventoryItem.qty_on_hand - InventoryItem.qty_reserved >= 1,
            # The early-release zone: 181 to 270 days left (N-3).
            InventoryItem.expiry_date > tx.today + timedelta(days=NEAR_EXPIRY_MAX_DAYS),
            InventoryItem.expiry_date <= tx.today + timedelta(days=EARLY_RELEASE_MAX_DAYS),
        )
    ).all()
    pharmacy_ids = list({pharmacy.id for _, pharmacy in rows})
    hours = pharmacies.weekly_hours(tx, pharmacy_ids)
    travels = travel.travel_to(tx, location, pharmacy_ids)
    start_of_today = at_beirut(tx.today, time.min)

    candidates: list[AskCandidate] = []
    by_candidate: dict[tuple[str, object], InventoryItem] = {}
    for item, pharmacy in rows:
        asks_today = tx.session.execute(
            select(func.count())
            .select_from(EarlyReleaseAsk)
            .where(
                EarlyReleaseAsk.pharmacy_id == pharmacy.id,
                EarlyReleaseAsk.created_at >= start_of_today,
            )
        ).scalar_one()
        declined_at = tx.session.execute(
            select(func.max(EarlyReleaseAsk.answered_at)).where(
                EarlyReleaseAsk.pharmacy_id == pharmacy.id,
                EarlyReleaseAsk.product_id == item.product_id,
                EarlyReleaseAsk.state == "DECLINED",
                EarlyReleaseAsk.answered_at > tx.now - EARLY_RELEASE_DECLINE_MEMORY,
            )
        ).scalar()
        marks = tx.session.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.pharmacy_id == pharmacy.id,
                Order.state == "NOT_AVAILABLE",
                Order.closed_at > tx.now - timedelta(days=30),
            )
        ).scalar_one()
        candidate = AskCandidate(
            pharmacy_id=str(pharmacy.id),
            car_min=travels[pharmacy.id].car_min,
            expiry_date=item.expiry_date,
            not_available_marks_30d=marks,
            open_now=is_open(hours[pharmacy.id], tx.now),
            asks_today=asks_today,
            declined_this_product_at=declined_at,
        )
        candidates.append(candidate)
        by_candidate.setdefault((candidate.pharmacy_id, candidate.expiry_date), item)
    return candidates, by_candidate


def request_early_release(
    tx: Tx, *, claim_id: uuid.UUID, idempotency_key: str, actor: Actor = Actor.AGENT
) -> Asked:
    """The agent asks pharmacies to release private stock for one claim (R-E1).

    Calling it again with the same key, or while the claim's request is still open, returns
    that request: a turn that is retried finds its own work (R-AG6).
    """
    seen = tx.session.get(Claim, claim_id)
    if seen is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown claim.")
    client = clients.profile(tx, seen.client_id, lock=True)
    clients.require_reserve(tx, client)
    claim = needs.lock_claim(tx, claim_id)

    existing = (
        tx.session.execute(
            select(EarlyReleaseRequest).where(
                EarlyReleaseRequest.client_id == claim.client_id,
                (EarlyReleaseRequest.idempotency_key == idempotency_key)
                | (
                    (EarlyReleaseRequest.claim_id == claim.id)
                    & (EarlyReleaseRequest.state == "OPEN")
                ),
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        asked = tx.session.execute(
            select(func.count())
            .select_from(EarlyReleaseAsk)
            .where(EarlyReleaseAsk.er_request_id == existing.id)
        ).scalar_one()
        return Asked(existing.id, asked)

    if claim.state != "ACTIVE" or claim.qty_missing < 1 or claim.ends_at <= tx.now:
        raise ServiceError(
            Code.CLAIM_NOT_ACTIVE, "This need isn't waiting any more.", state=claim.state
        )
    product = catalog.allowed_product(tx, claim.product_id)
    open_requests = tx.session.execute(
        select(func.count())
        .select_from(EarlyReleaseRequest)
        .where(
            EarlyReleaseRequest.client_id == claim.client_id, EarlyReleaseRequest.state == "OPEN"
        )
    ).scalar_one()
    if open_requests >= MAX_OPEN_EARLY_RELEASE_REQUESTS:
        raise ServiceError(Code.LIMIT_EARLY_RELEASE, "Too many open early-release requests.")
    last_failed = tx.session.execute(
        select(func.max(EarlyReleaseRequest.closed_at)).where(
            EarlyReleaseRequest.client_id == claim.client_id,
            EarlyReleaseRequest.product_id == claim.product_id,
            EarlyReleaseRequest.state == "UNFULFILLED",
        )
    ).scalar()
    if last_failed is not None and tx.now - last_failed < SAME_PRODUCT_EARLY_RELEASE_WAIT:
        raise ServiceError(
            Code.LIMIT_EARLY_RELEASE,
            "Pharmacies were asked for this medicine recently.",
            retry_after=last_failed + SAME_PRODUCT_EARLY_RELEASE_WAIT,
        )

    candidates, items = _candidates(tx, claim, product)
    chosen = pharmacies_to_ask(candidates, tx.now)
    if not chosen:
        return Asked(None, 0)

    request = EarlyReleaseRequest(
        id=uuid.uuid4(),
        client_id=claim.client_id,
        claim_id=claim.id,
        product_id=claim.product_id,
        qty=claim.qty_missing,
        idempotency_key=idempotency_key,
    )
    tx.session.add(request)
    tx.session.flush()
    audit.record(
        tx,
        actor,
        "early_release.request",
        "early_release_request",
        request.id,
        after={"state": "OPEN", "claim_id": str(claim.id), "asks": len(chosen)},
    )
    for candidate in chosen:
        item = items[(candidate.pharmacy_id, candidate.expiry_date)]
        pharmacy = tx.session.get_one(Pharmacy, item.pharmacy_id)
        asked_product = tx.session.get_one(Product, item.product_id)
        ask = EarlyReleaseAsk(
            id=uuid.uuid4(),
            er_request_id=request.id,
            pharmacy_id=pharmacy.id,
            inventory_item_id=item.id,
            product_id=item.product_id,
            respond_by=early_release_respond_by(tx.now),
        )
        tx.session.add(ask)
        tx.session.flush()
        notify(
            tx,
            pharmacy.owner_user_id,
            Template.EARLY_RELEASE_ASK,
            {
                "ask_id": str(ask.id),
                "product": asked_product.moph_name,
                "units": request.qty,
                "suggested_price_lbp": early_release_suggested_price_lbp(
                    asked_product.public_price_lbp
                ),
                "respond_by": ask.respond_by.isoformat(),
            },
            event=f"ask:{ask.id}",
        )
    return Asked(request.id, len(chosen))


def _own_open_ask(tx: Tx, pharmacy_id: uuid.UUID, ask_id: uuid.UUID) -> EarlyReleaseAsk:
    pharmacy = tx.session.get(Pharmacy, pharmacy_id)
    if pharmacy is None or pharmacy.status != "APPROVED":
        raise ServiceError(Code.PHARMACY_NOT_APPROVED, "This pharmacy can't answer asks.")
    ask = tx.session.get(EarlyReleaseAsk, ask_id)
    if ask is None or ask.pharmacy_id != pharmacy_id:
        raise ServiceError(Code.NOT_FOUND, "Unknown ask.")
    return ask


def _lock_ask(tx: Tx, ask_id: uuid.UUID) -> EarlyReleaseAsk:
    ask = tx.session.execute(
        select(EarlyReleaseAsk)
        .where(EarlyReleaseAsk.id == ask_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if ask.state != AskState.ASKED.value or tx.now >= ask.respond_by:
        raise ServiceError(Code.ASK_NOT_OPEN, "This ask is no longer open.", state=ask.state)
    return ask


def accept_ask(
    tx: Tx, pharmacy_id: uuid.UUID, ask_id: uuid.UUID, *, qty: int, price_lbp: int
) -> EarlyReleaseAsk:
    """The pharmacy releases the box: the client gets a two-hour offer (R-E6, O8).

    If the need was met in the meantime, nothing is locked and the ask is simply withdrawn
    ("Thank you, this need was just met").
    """
    seen = _own_open_ask(tx, pharmacy_id, ask_id)
    request = tx.session.get_one(EarlyReleaseRequest, seen.er_request_id)
    # The global lock order: the client, the item, the claim, then the ask (docs/05 §6).
    client = tx.session.execute(
        select(ClientProfile).where(ClientProfile.user_id == request.client_id).with_for_update()
    ).scalar_one()
    item = orders.lock_items(tx, [seen.inventory_item_id])[seen.inventory_item_id]
    claim = needs.lock_claim(tx, request.claim_id)
    ask = _lock_ask(tx, ask_id)

    already_offered = tx.session.execute(
        select(Order.id).where(
            Order.claim_id == claim.id,
            Order.state == "OFFERED",
            Order.source == OrderSource.EARLY_RELEASE.value,
        )
    ).first()
    covered = (
        claim.state not in ("ACTIVE", "OFFER_PENDING")
        or claim.qty_missing < 1
        or request.state != "OPEN"
        or client.status != "ACTIVE"
        or already_offered is not None
    )
    if covered:
        _move_ask(tx, ask, AskState.WITHDRAWN, Actor.SYSTEM, reason="the need was already met")
        return ask

    product = tx.session.get_one(Product, item.product_id)
    if price_lbp > product.public_price_lbp:
        raise ServiceError(
            Code.PRICE_ABOVE_PUBLIC,
            "The price can't be above the public price.",
            public_price_lbp=product.public_price_lbp,
        )
    if not is_valid_acceptance(
        qty=qty,
        price_lbp=price_lbp,
        qty_missing=claim.qty_missing,
        private_available=item.qty_on_hand - item.qty_reserved,
        public_price_lbp=product.public_price_lbp,
    ):
        raise ServiceError(
            Code.UNITS_INVALID,
            "Units must be between 1 and what the client still needs and you have.",
            needed=claim.qty_missing,
        )
    ask.accepted_qty, ask.accepted_price_lbp = qty, price_lbp
    _move_ask(tx, ask, AskState.ACCEPTED, Actor.PHARMACY, units=qty, price_lbp=price_lbp)
    orders.create_offer(
        tx,
        claim=claim,
        item=item,
        units=qty,
        price_lbp=price_lbp,
        source=OrderSource.EARLY_RELEASE,
        actor=Actor.PHARMACY,
        reason="a pharmacy released private stock",
        early_release_ask_id=ask.id,
    )
    return ask


def decline_ask(tx: Tx, pharmacy_id: uuid.UUID, ask_id: uuid.UUID, reason: str) -> EarlyReleaseAsk:
    """The pharmacy keeps its stock. No penalty, and it isn't asked again for a week."""
    if reason not in DECLINE_REASONS:
        raise ServiceError(Code.VALIDATION_ERROR, "Unknown reason.")
    seen = _own_open_ask(tx, pharmacy_id, ask_id)
    ask = _lock_ask(tx, seen.id)
    ask.decline_reason = reason
    _move_ask(tx, ask, AskState.DECLINED, Actor.PHARMACY, reason_code=reason)
    resolve(tx, ask.er_request_id)
    return ask


def expire_ask(tx: Tx, ask_id: uuid.UUID) -> bool:
    """The pharmacy didn't answer in time (R-E6). Run by the clock check."""
    ask = tx.session.execute(
        select(EarlyReleaseAsk)
        .where(EarlyReleaseAsk.id == ask_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if ask.state != AskState.ASKED.value or tx.now < ask.respond_by:
        return False
    _move_ask(tx, ask, AskState.EXPIRED, Actor.SYSTEM)
    resolve(tx, ask.er_request_id)
    return True


def resolve(tx: Tx, er_request_id: uuid.UUID) -> bool:
    """Every ask ended and nothing was accepted: the request is UNFULFILLED (R-E7).

    That is a decision event while the claim's window is open: the agent thinks again.
    Returns True if the request was closed here.
    """
    request = tx.session.execute(
        select(EarlyReleaseRequest)
        .where(EarlyReleaseRequest.id == er_request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if request.state != "OPEN":
        return False
    still_asked = tx.session.execute(
        select(EarlyReleaseAsk.id).where(
            EarlyReleaseAsk.er_request_id == request.id, EarlyReleaseAsk.state == "ASKED"
        )
    ).first()
    offer_pending = tx.session.execute(
        select(Order.id).where(
            Order.claim_id == request.claim_id,
            Order.state == "OFFERED",
            Order.source == OrderSource.EARLY_RELEASE.value,
        )
    ).first()
    if still_asked is not None or offer_pending is not None:
        return False
    request.state = "UNFULFILLED"
    request.closed_at = tx.now
    audit.record(
        tx,
        Actor.SYSTEM,
        "early_release.close",
        "early_release_request",
        request.id,
        before={"state": "OPEN"},
        after={"state": "UNFULFILLED"},
    )
    claim = tx.session.get_one(Claim, request.claim_id)
    if claim.state in ("ACTIVE", "OFFER_PENDING") and claim.ends_at > tx.now:
        conversation = events.conversation_for(
            tx,
            source=claim.source,
            client_id=claim.client_id,
            request_item_id=claim.request_item_id,
        )
        events.post_decision(
            tx,
            conversation,
            Decision.EARLY_RELEASE_UNFULFILLED,
            claim_id=claim.id,
            early_release_request_id=request.id,
        )
    return True


def resolve_for_claim(tx: Tx, claim_id: uuid.UUID | None) -> None:
    """An early-release offer ended without being accepted: is the request over?"""
    if claim_id is None:
        return
    request_id = tx.session.execute(
        select(EarlyReleaseRequest.id).where(
            EarlyReleaseRequest.claim_id == claim_id, EarlyReleaseRequest.state == "OPEN"
        )
    ).scalar()
    if request_id is not None:
        resolve(tx, request_id)
