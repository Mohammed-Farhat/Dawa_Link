"""Plans for several medicines at once (docs/04 R-RQ5, R-RT2; the tool `plan_basket`).

This is the database side of the planner: it finds the boxes that can serve each medicine
on the chosen pickup day, reads the travel legs, and hands both to the deterministic
planner in `domain/planning.py`. One plan is one trip on one day. The agent chooses among
the plans it gets; it never computes one (R-AG9). The scripted policy of the evaluation
calls the same function, so both contenders see the same plans.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from dawalink.db.models import Product
from dawalink.domain import planning
from dawalink.domain.expiry import fits
from dawalink.domain.numbers import (
    MAX_ITEMS_PER_REQUEST,
    MAX_UNITS_PER_GROUP,
    PLAN_MAX_CANDIDATE_PHARMACIES,
)
from dawalink.domain.planning import BasketItem, MissingReason, Preference
from dawalink.services import catalog, clients, pharmacies, travel
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.pharmacies import PharmacyCard
from dawalink.services.search import Box, visible_boxes
from dawalink.services.travel import Location


@dataclass(frozen=True)
class BasketLine:
    """One medicine to plan for."""

    product_id: uuid.UUID
    qty: int = 1
    days_of_use: int = 1
    max_price_lbp: int | None = None
    request_item_id: uuid.UUID | None = None


@dataclass(frozen=True)
class PlannedPick:
    product_id: uuid.UUID  # the medicine that was asked for
    listing_id: uuid.UUID
    qty: int
    price_lbp: int
    days_of_use: int
    expiry_date: date
    request_item_id: uuid.UUID | None


@dataclass(frozen=True)
class PlannedStop:
    pharmacy: PharmacyCard
    picks: tuple[PlannedPick, ...]


@dataclass(frozen=True)
class StillMissing:
    product_id: uuid.UUID
    qty_missing: int
    reason: MissingReason


@dataclass(frozen=True)
class PlannedTrip:
    pickup_day: date
    stops: tuple[PlannedStop, ...]  # in visiting order
    total_car_min: int
    total_walk_min: int
    source: planning.TravelSource
    total_lbp: int
    missing: tuple[StillMissing, ...]


@dataclass(frozen=True)
class Planned:
    pickup_day: date | None
    trips: list[PlannedTrip]
    # Medicines no plan can include at all, and why.
    unplannable: list[StillMissing]


def _checked(tx: Tx, lines: Sequence[BasketLine]) -> dict[uuid.UUID, Product]:
    if not 1 <= len(lines) <= MAX_ITEMS_PER_REQUEST:
        raise ServiceError(Code.VALIDATION_ERROR, "A plan has 1 to 5 medicines.")
    products = {line.product_id: catalog.allowed_product(tx, line.product_id) for line in lines}
    groups = [catalog.medicine_group(product) for product in products.values()]
    if len(products) != len(lines) or len(set(groups)) != len(lines):
        raise ServiceError(Code.VALIDATION_ERROR, "Each medicine appears once in a plan.")
    for line in lines:
        if not 1 <= line.qty <= MAX_UNITS_PER_GROUP or line.days_of_use < 1:
            raise ServiceError(Code.VALIDATION_ERROR, "Quantity is 1 to 3; days of use start at 1.")
        if line.max_price_lbp is not None and line.max_price_lbp < 0:
            raise ServiceError(Code.VALIDATION_ERROR, "A budget can't be negative.")
    return products


def _boxes_by_line(tx: Tx, lines: Sequence[BasketLine]) -> dict[uuid.UUID, list[Box]]:
    """The visible boxes of each asked medicine itself.

    Never another brand: a plan's card reserves everything with one tap, and only a
    pharmacist can say another brand suits the client (R-C10).
    """
    boxes = visible_boxes(tx, product_ids=[line.product_id for line in lines])
    return {
        line.product_id: [box for box in boxes if box.product_id == line.product_id]
        for line in lines
    }


def _usable(
    line: BasketLine, boxes: Sequence[Box], day: date | None
) -> tuple[list[Box], MissingReason]:
    """The boxes that can serve this medicine on that day, or why none can."""
    if not boxes or day is None:
        return [], "none_listed"
    in_budget = [
        box for box in boxes if line.max_price_lbp is None or box.price_lbp <= line.max_price_lbp
    ]
    if not in_budget:
        return [], "over_budget"
    that_day = [box for box in in_budget if day in box.pharmacy_days]
    if not that_day:
        return [], "not_on_that_day"
    lasting = [box for box in that_day if fits(box.expiry_date, day, line.days_of_use)]
    if not lasting:
        return [], "expires_too_early"
    return lasting, "none_listed"


@dataclass(frozen=True)
class _Basket:
    """A basket as the planner takes it: the day, and the boxes that can serve it that day."""

    day: date | None
    items: list[BasketItem]
    usable: list[planning.Box]
    by_listing: dict[str, Box]


def _basket(tx: Tx, lines: Sequence[BasketLine], pickup_day: date | None) -> _Basket:
    by_line = _boxes_by_line(tx, lines)
    every_box = [box for boxes in by_line.values() for box in boxes]
    first_days = [box.pharmacy_days[0] for box in every_box if box.pharmacy_days]
    # Without a day from the client: the earliest day a pharmacy with a wanted box accepts.
    day = pickup_day or (min(first_days) if first_days else None)

    usable: list[planning.Box] = []
    items: list[BasketItem] = []
    by_listing: dict[str, Box] = {}
    for line in lines:
        kept, reason = _usable(line, by_line[line.product_id], day)
        items.append(BasketItem(str(line.product_id), line.qty, reason_if_none=reason))
        for box in kept:
            by_listing[str(box.item_id)] = box
            usable.append(
                planning.Box(
                    listing_id=str(box.item_id),
                    item_key=str(line.product_id),
                    pharmacy_id=str(box.pharmacy_id),
                    price_lbp=box.price_lbp,
                    available=box.qty_available,
                )
            )
    return _Basket(day, items, usable, by_listing)


def _weighed(tx: Tx, location: Location, usable: Sequence[planning.Box]) -> list[uuid.UUID]:
    """The pharmacies the planner weighs (N-48): the nearest ones, plus the cheapest one for
    each medicine, so a medicine that only a far pharmacy has is still planned.

    "Nearest" is by road, by car. When there are more pharmacies than the planner weighs,
    the road times from the client to all of them are asked for first (`pharmacies_stocking`),
    so the choice is made on real trips. Where the routing service gave nothing, the
    straight-line estimate stands in, as everywhere else (R-RT1).
    """
    stocking = sorted({uuid.UUID(box.pharmacy_id) for box in usable})
    if len(stocking) <= PLAN_MAX_CANDIDATE_PHARMACIES:
        return stocking
    away = travel.travel_to(tx, location, stocking)
    nearest = sorted(
        stocking,
        key=lambda pharmacy_id: (away[pharmacy_id].car_min, away[pharmacy_id].km, str(pharmacy_id)),
    )
    keep = set(nearest[:PLAN_MAX_CANDIDATE_PHARMACIES])
    # Of the pharmacies with a medicine's lowest price, the nearest.
    place = {pharmacy_id: position for position, pharmacy_id in enumerate(nearest)}
    cheapest: dict[str, tuple[int, int]] = {}
    for box in usable:
        offer = (box.price_lbp, place[uuid.UUID(box.pharmacy_id)])
        if box.item_key not in cheapest or offer < cheapest[box.item_key]:
            cheapest[box.item_key] = offer
    keep |= {nearest[position] for _, position in cheapest.values()}
    return sorted(keep)


def pharmacies_stocking(
    tx: Tx, *, lines: Sequence[BasketLine], pickup_day: date | None = None
) -> list[uuid.UUID]:
    """Every pharmacy with a box that can serve this basket, when there are more of them
    than the planner weighs; otherwise none.

    These are the pharmacies whose trip from the client must be known before the nearest
    ones can be chosen. With few pharmacies there is no choice to make, and nothing to ask.
    """
    _checked(tx, lines)
    usable = _basket(tx, lines, pickup_day).usable
    stocking = sorted({uuid.UUID(box.pharmacy_id) for box in usable})
    return stocking if len(stocking) > PLAN_MAX_CANDIDATE_PHARMACIES else []


def pharmacies_to_weigh(
    tx: Tx, *, lines: Sequence[BasketLine], location: Location, pickup_day: date | None = None
) -> list[uuid.UUID]:
    """The pharmacies `plan` will weigh for this basket: the trips between them, and from
    the client to them, are the road times a plan needs."""
    _checked(tx, lines)
    return _weighed(tx, location, _basket(tx, lines, pickup_day).usable)


def plan(
    tx: Tx,
    *,
    client_id: uuid.UUID,
    lines: Sequence[BasketLine],
    location: Location,
    pickup_day: date | None = None,
    preference: Preference | None = None,
    max_plans: int = 3,
) -> Planned:
    clients.require_search(clients.profile(tx, client_id))
    if pickup_day is not None and pickup_day < tx.today:
        raise ServiceError(Code.PICKUP_DAY_INVALID, "The pickup day can't be in the past.")
    _checked(tx, lines)
    basket = _basket(tx, lines, pickup_day)
    day, items, usable, by_listing = basket.day, basket.items, basket.usable, basket.by_listing

    unplannable = [
        StillMissing(uuid.UUID(item.key), item.qty, item.reason_if_none)
        for item in items
        if not any(box.item_key == item.key for box in usable)
    ]
    if day is None or not usable:
        return Planned(day, [], unplannable)

    in_play = _weighed(tx, location, usable)
    legs = travel.legs(tx, location, in_play)
    weighed = [box for box in usable if uuid.UUID(box.pharmacy_id) in in_play]
    found = planning.plan_basket(
        items, weighed, legs, preference=preference, max_plans=max(1, min(max_plans, 3))
    )

    hours = pharmacies.weekly_hours(tx, in_play)
    cards = pharmacies.cards(tx, in_play, hours)
    line_of = {str(line.product_id): line for line in lines}
    trips = [
        PlannedTrip(
            pickup_day=day,
            stops=tuple(
                PlannedStop(
                    pharmacy=cards[uuid.UUID(stop.pharmacy_id)],
                    picks=tuple(
                        PlannedPick(
                            product_id=uuid.UUID(pick.item_key),
                            listing_id=uuid.UUID(pick.listing_id),
                            qty=pick.qty,
                            price_lbp=pick.price_lbp,
                            days_of_use=line_of[pick.item_key].days_of_use,
                            expiry_date=by_listing[pick.listing_id].expiry_date,
                            request_item_id=line_of[pick.item_key].request_item_id,
                        )
                        for pick in stop.picks
                    ),
                )
                for stop in trip.stops
            ),
            total_car_min=trip.total_car_min,
            total_walk_min=trip.total_walk_min,
            source=trip.source,
            total_lbp=trip.total_lbp,
            missing=tuple(
                StillMissing(uuid.UUID(gap.item_key), gap.qty_missing, gap.reason)
                for gap in trip.missing
            ),
        )
        for trip in found
    ]
    return Planned(day, trips, unplannable)
