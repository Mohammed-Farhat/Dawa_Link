"""Searching visible listings (docs/04 R-S, R-F; the agent's `find_options`).

The search page and the agent's tool call the same function, so they can never disagree.
What it returns is what a client may see: never private stock, never a controlled
medicine, never a coordinate.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select, text

from dawalink.db.models import Product
from dawalink.domain.expiry import fits
from dawalink.domain.geo import Travel
from dawalink.domain.numbers import DEFAULT_DAYS_OF_USE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from dawalink.domain.pickup import PickupChoice, pharmacy_pickup_days
from dawalink.domain.pricing import discount_shown_pct
from dawalink.domain.search import Ranked, Sort, availability_shown, sort_options
from dawalink.services import catalog, clients, pharmacies, travel
from dawalink.services.catalog import ProductRef
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.pharmacies import PharmacyCard
from dawalink.services.travel import Location


@dataclass(frozen=True)
class Listing:
    """One visible box a client can reserve."""

    id: uuid.UUID  # the inventory item's id
    product: ProductRef
    pharmacy: PharmacyCard
    price_lbp: int
    discount_pct: int
    expiry_date: date
    days_left: int
    available: int  # shown exactly up to 5 (R-S5)
    more_available: bool
    travel: Travel
    # Lasts the client's days of use. None: the client didn't say, so only a warning shows.
    fits: bool | None
    # The days this box can be picked up and still last (R-F3).
    pickup_days_allowed: tuple[date, ...]
    # The pharmacy accepts a later day, but the box wouldn't last from it (R-F6).
    expiry_limits_pickup: bool


@dataclass(frozen=True)
class NoMatch:
    """Why nothing fits (R-F4): boxes exist, but none lasts or none can be had that day."""

    latest_expiry: date
    latest_pickup_day: date | None


@dataclass(frozen=True)
class SearchResult:
    listings: list[Listing]
    total_found: int
    # Boxes that an earlier pickup day would add (R-F6).
    left_out_by_pickup_day: int
    no_match: NoMatch | None


@dataclass(frozen=True)
class Box:
    """A visible listing, with the days its pharmacy accepts a pickup."""

    item_id: uuid.UUID
    pharmacy_id: uuid.UUID
    product_id: uuid.UUID
    expiry_date: date
    days_left: int
    qty_available: int
    price_lbp: int
    # Today (if the pharmacy stays open long enough) and its next open days (R-F3).
    pharmacy_days: tuple[date, ...]

    def choice(self, days_of_use: int) -> PickupChoice:
        """The days on which this box still lasts `days_of_use` (R-F1, R-F6)."""
        days = tuple(day for day in self.pharmacy_days if fits(self.expiry_date, day, days_of_use))
        return PickupChoice(days, expiry_limits_pickup=len(days) < len(self.pharmacy_days))


def visible_boxes(
    tx: Tx, *, product_ids: Sequence[uuid.UUID] = (), item_ids: Sequence[uuid.UUID] = ()
) -> list[Box]:
    """The visible boxes of these products, or these exact items.

    Visibility has one definition, the `visible_listings` function (INV-16), and `today`
    comes from the app clock.
    """
    if item_ids:
        condition, wanted = "v.inventory_item_id = ANY(:wanted)", list(item_ids)
    else:
        condition, wanted = "v.product_id = ANY(:wanted)", list(product_ids)
    rows = tx.session.execute(
        text(
            "SELECT v.*, ph.pickup_days FROM visible_listings(:today) v "
            f"JOIN pharmacies ph ON ph.id = v.pharmacy_id WHERE {condition}"
        ),
        {"today": tx.today, "wanted": wanted},
    ).all()
    hours = pharmacies.weekly_hours(tx, list({row.pharmacy_id for row in rows}))
    return [
        Box(
            item_id=row.inventory_item_id,
            pharmacy_id=row.pharmacy_id,
            product_id=row.product_id,
            expiry_date=row.expiry_date,
            days_left=row.days_left,
            qty_available=row.qty_available,
            price_lbp=row.price_lbp,
            pharmacy_days=tuple(
                pharmacy_pickup_days(hours[row.pharmacy_id], row.pickup_days, tx.now)
            ),
        )
        for row in rows
    ]


def search_listings(
    tx: Tx,
    *,
    client_id: uuid.UUID,
    product_ids: Sequence[uuid.UUID],
    location: Location,
    days_of_use: int | None = None,
    pickup_day: date | None = None,
    max_price_lbp: int | None = None,
    sort: Sort = "best",
    on_foot: bool = False,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> SearchResult:
    clients.require_search(clients.profile(tx, client_id))
    if days_of_use is not None and days_of_use < 1:
        raise ServiceError(Code.VALIDATION_ERROR, "Days of use start at 1.")
    if pickup_day is not None and pickup_day < tx.today:
        raise ServiceError(Code.PICKUP_DAY_INVALID, "The pickup day can't be in the past.")
    limit = max(1, min(limit, MAX_PAGE_SIZE))

    # Exactly the products asked for, never another brand of them (R-S4). The agent's
    # `find_options` is the one caller that passes other brands, to show them (R-C10).
    wanted = {catalog.allowed_product(tx, product_id).id for product_id in product_ids}
    products = {
        product.id: product
        for product in tx.session.execute(select(Product).where(Product.id.in_(wanted))).scalars()
    }

    days = days_of_use or DEFAULT_DAYS_OF_USE
    boxes = visible_boxes(tx, product_ids=list(wanted))
    choices = {box.item_id: box.choice(days) for box in boxes}
    if max_price_lbp is not None:
        boxes = [box for box in boxes if box.price_lbp <= max_price_lbp]

    kept: list[Box] = []
    left_out_by_pickup_day = 0
    for box in boxes:
        if not choices[box.item_id].days:
            continue  # it never lasts: counted in `no_match` below
        if pickup_day is None or pickup_day in choices[box.item_id].days:
            kept.append(box)
        else:
            left_out_by_pickup_day += 1

    travels = travel.travel_to(tx, location, list({box.pharmacy_id for box in kept}))
    order = sort_options(
        [
            Ranked(
                listing_id=str(box.item_id),
                car_min=travels[box.pharmacy_id].car_min,
                walk_min=travels[box.pharmacy_id].walk_min,
                km=travels[box.pharmacy_id].km,
                price_lbp=box.price_lbp,
                expiry_date=box.expiry_date,
            )
            for box in kept
        ],
        sort,
        on_foot=on_foot,
    )
    by_id = {str(box.item_id): box for box in kept}
    page = [by_id[ranked.listing_id] for ranked in order[offset : offset + limit]]
    hours = pharmacies.weekly_hours(tx, list({box.pharmacy_id for box in page}))
    cards = pharmacies.cards(tx, list(hours), hours)

    listings = []
    for box in page:
        product = products[box.product_id]
        shown, more = availability_shown(box.qty_available)
        listings.append(
            Listing(
                id=box.item_id,
                product=catalog.ref(product),
                pharmacy=cards[box.pharmacy_id],
                price_lbp=box.price_lbp,
                discount_pct=discount_shown_pct(product.public_price_lbp, box.price_lbp),
                expiry_date=box.expiry_date,
                days_left=box.days_left,
                available=shown,
                more_available=more,
                travel=travels[box.pharmacy_id],
                fits=None if days_of_use is None else True,
                pickup_days_allowed=choices[box.item_id].days,
                expiry_limits_pickup=choices[box.item_id].expiry_limits_pickup,
            )
        )

    no_match = None
    if not kept and boxes:
        possible = [choices[box.item_id].days[-1] for box in boxes if choices[box.item_id].days]
        no_match = NoMatch(
            latest_expiry=max(box.expiry_date for box in boxes),
            latest_pickup_day=max(possible) if possible else None,
        )
    return SearchResult(listings, len(kept), left_out_by_pickup_day, no_match)
