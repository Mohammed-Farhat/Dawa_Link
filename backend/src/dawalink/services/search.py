"""Searching visible listings (docs/04 R-S, R-F; the agent's `find_options`).

The search page and the agent's tool call the same function, so they can never disagree.
What it returns is what a client may see: never private stock, never a controlled
medicine, never a coordinate.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy import select, text

from dawalink.db.models import Product
from dawalink.domain.expiry import fits
from dawalink.domain.geo import Travel
from dawalink.domain.numbers import DEFAULT_DAYS_OF_USE, DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from dawalink.domain.opening_hours import WeeklyHours, is_open
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


class WhyNone(StrEnum):
    """Why a search found nothing to offer. One reason, the first that applies, so that
    whoever explains it to the client never has to guess (the owner, 2026-11-23: a
    medicine listed nowhere must not be answered with "try another day")."""

    # No pharmacy lists the medicine at all. Another day changes nothing.
    NONE_LISTED = "none_listed"
    # Listed, but in no pharmacy of the areas the client asked for.
    NOT_IN_THESE_AREAS = "not_in_these_areas"
    # Listed, but every box costs more than the client's limit.
    OVER_BUDGET = "over_budget"
    # Listed, but no box lasts the client's days of use, whatever the pickup day.
    EXPIRES_TOO_EARLY = "expires_too_early"
    # A box lasts, but not when picked up on the day asked for: the pharmacy is closed
    # that day, or the box would not last from it. `days_that_work` says which days do.
    NOT_ON_THAT_DAY = "not_on_that_day"


@dataclass(frozen=True)
class SearchResult:
    listings: list[Listing]
    total_found: int
    # Boxes that an earlier pickup day would add (R-F6).
    left_out_by_pickup_day: int
    no_match: NoMatch | None
    # Set only when `listings` is empty and nothing was skipped by paging.
    why_none: WhyNone | None = None
    # NOT_ON_THAT_DAY: the pickup days on which some box can be had and still lasts.
    days_that_work: tuple[date, ...] = ()
    # NOT_IN_THESE_AREAS: how many boxes other areas have (0: none anywhere else either).
    elsewhere: int = 0
    # OVER_BUDGET: the cheapest box there is.
    cheapest_lbp: int | None = None


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
    return _boxes_and_hours(tx, product_ids=product_ids, item_ids=item_ids)[0]


def _boxes_and_hours(
    tx: Tx, *, product_ids: Sequence[uuid.UUID] = (), item_ids: Sequence[uuid.UUID] = ()
) -> tuple[list[Box], dict[uuid.UUID, WeeklyHours]]:
    """The visible boxes, and the weekly hours of their pharmacies."""
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
    boxes = [
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
    return boxes, hours


def one_listing(
    tx: Tx,
    *,
    client_id: uuid.UUID,
    item_id: uuid.UUID,
    location: Location,
    days_of_use: int | None = None,
) -> Listing:
    """One visible box, for its own page (CS-7). A box that stopped being visible is
    "not found": the page never shows what can't be reserved (docs/06 §6.2)."""
    clients.require_search(clients.profile(tx, client_id))
    boxes = visible_boxes(tx, item_ids=[item_id])
    if not boxes:
        raise ServiceError(Code.NOT_FOUND, "This offer is no longer available.")
    box = boxes[0]
    product = catalog.allowed_product(tx, box.product_id)
    choice = box.choice(days_of_use or DEFAULT_DAYS_OF_USE)
    hours = pharmacies.weekly_hours(tx, [box.pharmacy_id])
    shown, more = availability_shown(box.qty_available)
    return Listing(
        id=box.item_id,
        product=catalog.ref(product),
        pharmacy=pharmacies.cards(tx, [box.pharmacy_id], hours)[box.pharmacy_id],
        price_lbp=box.price_lbp,
        discount_pct=discount_shown_pct(product.public_price_lbp, box.price_lbp),
        expiry_date=box.expiry_date,
        days_left=box.days_left,
        available=shown,
        more_available=more,
        travel=travel.travel_to(tx, location, [box.pharmacy_id])[box.pharmacy_id],
        # Here the box is shown even when it doesn't last: the page then says so.
        fits=None if days_of_use is None else bool(choice.days),
        pickup_days_allowed=choice.days,
        expiry_limits_pickup=choice.expiry_limits_pickup,
    )


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
    open_now: bool = False,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    districts: frozenset[str] | None = None,
) -> SearchResult:
    """`districts`: only the pharmacies of these districts, by name: the areas a client
    asked to look in ("in Saida or Beirut"). Travel times still count from `location`,
    which is where the client is (the owner, 2026-11-23)."""
    clients.require_search(clients.profile(tx, client_id))
    _check(tx, days_of_use, pickup_day)

    # Exactly the products asked for, never another brand of them (R-S4). The agent's
    # `find_options` is the one caller that passes other brands, to show them (R-C10).
    wanted = {catalog.allowed_product(tx, product_id).id for product_id in product_ids}
    products = {
        product.id: product
        for product in tx.session.execute(select(Product).where(Product.id.in_(wanted))).scalars()
    }
    shelf = _shelf(tx, list(wanted), location)
    return _result(
        tx,
        shelf,
        shelf.boxes,
        products,
        days_of_use=days_of_use,
        pickup_day=pickup_day,
        max_price_lbp=max_price_lbp,
        sort=sort,
        on_foot=on_foot,
        open_now=open_now,
        limit=limit,
        offset=offset,
        districts=districts,
    )


def _check(tx: Tx, days_of_use: int | None, pickup_day: date | None) -> None:
    if days_of_use is not None and days_of_use < 1:
        raise ServiceError(Code.VALIDATION_ERROR, "Days of use start at 1.")
    if pickup_day is not None and pickup_day < tx.today:
        raise ServiceError(Code.PICKUP_DAY_INVALID, "The pickup day can't be in the past.")


@dataclass(frozen=True)
class _Shelf:
    """What a search reads once, however many medicines it shows: the visible boxes, and
    their pharmacies' hours, travel times and cards."""

    boxes: list[Box]
    hours: dict[uuid.UUID, WeeklyHours]
    travels: dict[uuid.UUID, Travel]
    cards: dict[uuid.UUID, PharmacyCard]


def _shelf(tx: Tx, product_ids: Sequence[uuid.UUID], location: Location) -> _Shelf:
    boxes, hours = _boxes_and_hours(tx, product_ids=product_ids)
    if not boxes:
        return _Shelf([], {}, {}, {})
    pharmacy_ids = list(hours)
    return _Shelf(
        boxes,
        hours,
        travel.travel_to(tx, location, pharmacy_ids),
        pharmacies.cards(tx, pharmacy_ids, hours),
    )


def _result(
    tx: Tx,
    shelf: _Shelf,
    boxes: list[Box],
    products: Mapping[uuid.UUID, Product],
    *,
    days_of_use: int | None,
    pickup_day: date | None,
    max_price_lbp: int | None,
    sort: Sort,
    on_foot: bool,
    open_now: bool,
    limit: int,
    offset: int,
    districts: frozenset[str] | None = None,
) -> SearchResult:
    """One answer, from these boxes of the shelf. Reads nothing more: the search by name
    builds one per medicine from a single shelf (review A#29)."""
    limit = max(1, min(limit, MAX_PAGE_SIZE))
    days = days_of_use or DEFAULT_DAYS_OF_USE
    choices = {box.item_id: box.choice(days) for box in boxes}
    listed = boxes
    if districts is not None:
        boxes = [box for box in boxes if shelf.cards[box.pharmacy_id].district in districts]
    in_the_areas = boxes
    if max_price_lbp is not None:
        boxes = [box for box in boxes if box.price_lbp <= max_price_lbp]
    affordable = boxes
    if open_now:
        boxes = [box for box in boxes if is_open(shelf.hours[box.pharmacy_id], tx.now)]

    kept: list[Box] = []
    left_out_by_pickup_day = 0
    for box in boxes:
        if not choices[box.item_id].days:
            continue  # it never lasts: counted in `no_match` below
        if pickup_day is None or pickup_day in choices[box.item_id].days:
            kept.append(box)
        else:
            left_out_by_pickup_day += 1

    travels = shelf.travels
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
    cards = shelf.cards

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
    why_none: WhyNone | None = None
    days_that_work: tuple[date, ...] = ()
    if not kept and not open_now:
        # "Open now" is the search page's own filter; the page explains itself.
        why_none, days_that_work = _why_none(listed, in_the_areas, affordable, choices)
    return SearchResult(
        listings,
        len(kept),
        left_out_by_pickup_day,
        no_match,
        why_none=why_none,
        days_that_work=days_that_work,
        elsewhere=len(listed) - len(in_the_areas) if why_none is WhyNone.NOT_IN_THESE_AREAS else 0,
        cheapest_lbp=(
            min(box.price_lbp for box in in_the_areas) if why_none is WhyNone.OVER_BUDGET else None
        ),
    )


def _why_none(
    listed: Sequence[Box],
    in_the_areas: Sequence[Box],
    affordable: Sequence[Box],
    choices: Mapping[uuid.UUID, PickupChoice],
) -> tuple[WhyNone, tuple[date, ...]]:
    """The one reason nothing can be offered, and the days that would work if any.

    The filters are looked at in the order they were applied: listed at all, in the areas
    asked for, within the price limit, lasting the days of use, on the day asked for.
    """
    if not listed:
        return WhyNone.NONE_LISTED, ()
    if not in_the_areas:
        return WhyNone.NOT_IN_THESE_AREAS, ()
    if not affordable:
        return WhyNone.OVER_BUDGET, ()
    days = sorted({day for box in affordable for day in choices[box.item_id].days})
    if not days:
        return WhyNone.EXPIRES_TOO_EARLY, ()
    return WhyNone.NOT_ON_THAT_DAY, tuple(days)


@dataclass(frozen=True)
class MedicineGroup:
    """One medicine of a search by name, with its best boxes."""

    product: Product
    by_ingredient: bool
    result: SearchResult


@dataclass(frozen=True)
class NameResult:
    groups: list[MedicineGroup]
    closest: bool
    did_you_mean: list[str]


def stocked_products(tx: Tx) -> list[uuid.UUID]:
    """The medicines some pharmacy lists right now. Visibility has one definition, the
    `visible_listings` function (INV-16)."""
    rows = tx.session.execute(
        text("SELECT DISTINCT v.product_id FROM visible_listings(:today) v"), {"today": tx.today}
    ).scalars()
    return list(rows)


def search_by_name(
    tx: Tx,
    *,
    client_id: uuid.UUID,
    query: str,
    location: Location,
    days_of_use: int | None = None,
    pickup_day: date | None = None,
    max_price_lbp: int | None = None,
    sort: Sort = "best",
    on_foot: bool = False,
    open_now: bool = False,
    per_medicine: int = 3,
) -> NameResult:
    """Everything in stock for a typed name, grouped by medicine (CS-6). **Only what a
    pharmacy lists now:** a medicine nobody has is not shown, and the name is matched
    among the medicines in stock, from its first letter (the owner, 2026-11-18, BLD-D42).

    Each group is one catalog product under its own name, strength and form, so a
    misspelled name can't lead to reserving another medicine unseen. A medicine is "in
    stock" when a pharmacy has a visible box of it, whether or not that box lasts the
    client's days: a group whose boxes all expire too early says so (R-F4).

    A name that the catalog knows is that medicine or nothing: never the closest name in
    stock, which could be another brand of it (`catalog.find_in_stock`, review B#1).

    Each group is what `search_listings` answers for that one medicine, but the shelf is
    read once for all of them: one or two letters match up to 40 medicines (review A#29).
    """
    clients.require_search(clients.profile(tx, client_id))
    _check(tx, days_of_use, pickup_day)
    named = medicines_named(tx, query)
    shelf = _shelf(tx, [product.id for product in named.products], location)
    boxes_of: dict[uuid.UUID, list[Box]] = {product.id: [] for product in named.products}
    for box in shelf.boxes:
        boxes_of[box.product_id].append(box)
    groups = [
        MedicineGroup(
            product=product,
            by_ingredient=product.id in named.by_ingredient,
            result=_result(
                tx,
                shelf,
                boxes_of[product.id],
                {product.id: product},
                days_of_use=days_of_use,
                pickup_day=pickup_day,
                max_price_lbp=max_price_lbp,
                sort=sort,
                on_foot=on_foot,
                open_now=open_now,
                limit=per_medicine,
                offset=0,
            ),
        )
        for product in named.products
    ]
    return NameResult(groups=groups, closest=named.closest, did_you_mean=named.did_you_mean)


def medicines_named(tx: Tx, query: str) -> catalog.NameSearch:
    """The medicines in stock a typed name stands for: what the search page shows, and
    the pharmacies whose road times it asks for first. One place, so the two never differ."""
    return catalog.find_in_stock(tx, query, stocked_products(tx))
