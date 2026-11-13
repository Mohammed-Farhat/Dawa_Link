"""Matching: who gets available stock that several clients wait for (docs/04 R-PRI, ADR-003).

**First come, first served.** The claim that started waiting first chooses first; ties are
broken by the claim's ID, so the same claims and stock always give the same result
(INV-17). Nothing here reads anything a client, the agent or an admin could use to change
that order, because no such thing is stored.

Matching takes an advisory lock per medicine group and then client and item locks, so it
never starts inside a transaction that already holds such locks. Services call `defer`,
and the matching runs right after their commit (docs/05 §6).
"""

import uuid
from typing import Any

import structlog
from sqlalchemy import func, or_, select, text

from dawalink.db.models import Claim, ClaimSkip, ClientProfile, District, Order, Product
from dawalink.domain.allocation import WaitingClaim, allocate
from dawalink.domain.claims import ClaimState
from dawalink.domain.geo import Point
from dawalink.domain.limits import limit_reached_by
from dawalink.domain.orders import OrderSource
from dawalink.domain.state_machine import Actor
from dawalink.services import catalog, travel
from dawalink.services.context import Tx
from dawalink.services.search import Box, visible_boxes
from dawalink.services.travel import Location

log = structlog.get_logger(__name__)
# Orders made by matching, as opposed to early release: the two paths of INV-20.
MATCHING_SOURCES = (OrderSource.WATCH.value, OrderSource.REQUEST.value)


def group_of_claim() -> Any:
    """SQL for a claim's medicine group: its key, or itself when it has none."""
    return func.coalesce(Claim.equivalence_key, func.concat("product:", Claim.product_id))


def defer(tx: Tx, group: str) -> None:
    """Run matching for this medicine group once the current transaction has committed."""

    def run(later: Tx) -> None:
        run_for_group(later, group)

    tx.defer(("match", group), run)


def defer_for_product(tx: Tx, product: Product) -> None:
    """Stock of this product was freed or added, or someone started waiting for it (R-PRI1)."""
    defer(tx, catalog.medicine_group(product))


def groups_with_waiting_claims(tx: Tx) -> list[str]:
    """Every medicine group someone is waiting for: what the clock check's sweep runs over."""
    return list(
        tx.session.execute(
            select(group_of_claim())
            .where(Claim.state.in_(("ACTIVE", "OFFER_PENDING")), Claim.ends_at > tx.now)
            .distinct()
        ).scalars()
    )


def location_of(tx: Tx, claim: Claim) -> Location | None:
    if claim.loc_lat is not None and claim.loc_lon is not None:
        return Location(Point(claim.loc_lat, claim.loc_lon), "shared")
    if claim.district_id is not None:
        district = tx.session.get_one(District, claim.district_id)
        return Location(Point(district.ref_lat, district.ref_lon), "district", district.id)
    return None


def _best_box(tx: Tx, claim: Claim, boxes: list[Box], skipped: set[uuid.UUID]) -> Box | None:
    """The best box this claim may be offered: within reach, lasting, affordable (R-PRI2)."""
    location = location_of(tx, claim)
    if location is None:
        return None
    usable = [
        box
        for box in boxes
        if box.qty_available >= 1
        and box.item_id not in skipped
        and (claim.include_equivalents or box.product_id == claim.product_id)
        and (claim.max_price_lbp is None or box.price_lbp <= claim.max_price_lbp)
        and box.choice(claim.days_of_use).days
    ]
    travels = travel.travel_to(tx, location, list({box.pharmacy_id for box in usable}))
    in_reach = [box for box in usable if travel.within_reach(travels[box.pharmacy_id])]
    if not in_reach:
        return None
    return min(
        in_reach,
        key=lambda box: (
            travels[box.pharmacy_id].car_min,
            box.price_lbp,
            box.expiry_date,
            str(box.item_id),
        ),
    )


def _skip_reason(tx: Tx, claim: Claim, group: str, units: int) -> str | None:
    """Why this claim sits this round out (R-PRI3), or None."""
    from dawalink.services import orders

    status = tx.session.execute(
        select(ClientProfile.status).where(ClientProfile.user_id == claim.client_id)
    ).scalar()
    if status != "ACTIVE":
        return "the client is not active"
    if limit_reached_by(
        orders.open_load(tx, claim.client_id, without_claim=claim.id), [(group, units)]
    ):
        return "the client is at a limit"
    return None


def run_for_group(tx: Tx, group: str) -> int:
    """Offers this group's visible stock to its waiting claims. Returns the offers made."""
    from dawalink.services import orders

    # One allocator per medicine group at a time (FR-13).
    tx.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"match:{group}"}
    )
    waiting = list(
        tx.session.execute(
            select(Claim)
            .where(
                Claim.state.in_(("ACTIVE", "OFFER_PENDING")),
                Claim.ends_at > tx.now,
                Claim.qty_missing > 0,
                group_of_claim() == group,
            )
            .order_by(Claim.created_at, Claim.id)
        ).scalars()
    )
    if not waiting:
        return 0
    product_ids = list(
        tx.session.execute(
            select(Product.id).where(
                or_(
                    Product.equivalence_key == group,
                    func.concat("product:", Product.id) == group,
                ),
                Product.controlled.is_(False),
            )
        ).scalars()
    )
    candidates = visible_boxes(tx, product_ids=product_ids)
    if not candidates:
        return 0

    # The global lock order: clients first, then items (docs/05 §6).
    tx.session.execute(
        select(ClientProfile.user_id)
        .where(ClientProfile.user_id.in_({claim.client_id for claim in waiting}))
        .order_by(ClientProfile.user_id)
        .with_for_update()
    ).all()
    items = orders.lock_items(tx, [box.item_id for box in candidates])
    boxes = visible_boxes(tx, item_ids=list(items))

    made = 0
    for seen in waiting:
        claim = tx.session.execute(
            select(Claim)
            .where(Claim.id == seen.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        if ClaimState(claim.state) not in (ClaimState.ACTIVE, ClaimState.OFFER_PENDING):
            continue
        on_matching_path = tx.session.execute(
            select(Order.id).where(
                Order.claim_id == claim.id,
                Order.state == "OFFERED",
                Order.source.in_(MATCHING_SOURCES),
            )
        ).first()
        if on_matching_path is not None or claim.qty_missing < 1:
            continue
        skipped = set(
            tx.session.execute(
                select(ClaimSkip.inventory_item_id).where(
                    ClaimSkip.claim_id == claim.id, ClaimSkip.skip_until > tx.now
                )
            ).scalars()
        )
        box = _best_box(tx, claim, boxes, skipped)
        if box is None:
            continue
        units = min(claim.qty_missing, box.qty_available)
        result = allocate(
            box.qty_available,
            [
                WaitingClaim(
                    str(claim.id),
                    claim.created_at,
                    claim.qty_missing,
                    _skip_reason(tx, claim, group, units),
                )
            ],
        )
        for skip in result.skipped:
            log.info("matching_skipped", claim_id=skip.claim_id, reason=skip.reason)
        for hold in result.holds:
            orders.create_offer(
                tx,
                claim=claim,
                item=items[box.item_id],
                units=hold.units,
                price_lbp=box.price_lbp,
                source=(OrderSource.REQUEST if claim.kind == "REQUEST_ITEM" else OrderSource.WATCH),
                actor=Actor.SYSTEM,
                reason=hold.reason,
            )
            made += 1
            # What is left on the shelf for the next claim in line.
            boxes = [
                b if b.item_id != box.item_id else _with_available(b, b.qty_available - hold.units)
                for b in boxes
            ]
    return made


def _with_available(box: Box, qty_available: int) -> Box:
    return Box(
        item_id=box.item_id,
        pharmacy_id=box.pharmacy_id,
        product_id=box.product_id,
        expiry_date=box.expiry_date,
        days_left=box.days_left,
        qty_available=qty_available,
        price_lbp=box.price_lbp,
        pharmacy_days=box.pharmacy_days,
    )
