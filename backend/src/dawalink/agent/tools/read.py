"""The read tools: search, options, plans, status (docs/07 §4.2).

They return what a client may see, written for the model: names, areas, travel minutes,
prices and dates already formatted. Never an address, a coordinate, private stock, or an
availability above 5.
"""

import uuid
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import Field
from sqlalchemy import select

from dawalink.agent import display
from dawalink.agent.state import Money, PlanGroup, PlanPick, PlanRef
from dawalink.agent.tools.base import (
    Arguments,
    Output,
    Refused,
    Tool,
    ToolError,
    Turn,
    location_of,
    note_asked,
    rate,
    road_times_first,
)
from dawalink.db.models import (
    Claim,
    EarlyReleaseAsk,
    EarlyReleaseRequest,
    Order,
    Pharmacy,
    Product,
    RequestItem,
    SourcingRequest,
)
from dawalink.domain.claims import LIVE_STATES
from dawalink.domain.geo import Travel
from dawalink.domain.orders import OrderState
from dawalink.domain.requests import FINAL_ITEM_STATES, ItemState
from dawalink.domain.vocabulary import AgentMode
from dawalink.services import areas, catalog, pharmacies, planning, search
from dawalink.services.catalog import ProductRef
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.pharmacies import PharmacyCard
from dawalink.services.planning import BasketLine, PlannedTrip
from dawalink.services.search import visible_boxes

BOTH = frozenset({AgentMode.ASSISTANT, AgentMode.SOURCING})
Qty = Annotated[int, Field(ge=1, le=3)]
Days = Annotated[int, Field(ge=1, le=365)]


# --- What the outputs are made of ------------------------------------------------------


class ProductOut(Output):
    id: uuid.UUID
    name: str
    strength: str | None = None
    form: str | None = None
    pack: str | None = None
    prescription_required: bool
    public_price: str


class PharmacyOut(Output):
    """A pharmacy as the model may know it: its approved name and its area. No address."""

    name: str
    area: str
    open_now: bool
    # If it is open now: until when. It may open again later the same day (see the hours).
    open_until: str | None = None
    pickup_days: int


class TravelOut(Output):
    car_min: int
    walk_min: int
    km: float
    # "road": a real road time. "straight": an estimate, to be called "about".
    source: str


def product_out(tx: Tx, ref: ProductRef) -> ProductOut:
    return ProductOut(
        id=ref.id,
        name=ref.name,
        strength=ref.strength,
        form=ref.form,
        pack=ref.pack,
        prescription_required=ref.prescription_required,
        public_price=display.money(ref.public_price_lbp, rate(tx)),
    )


def pharmacy_out(card: PharmacyCard) -> PharmacyOut:
    return PharmacyOut(
        name=card.name,
        area=card.district,
        open_now=card.open_now,
        open_until=display.when(card.closes_at) if card.closes_at else None,
        pickup_days=card.pickup_days,
    )


def travel_out(travel: Travel) -> TravelOut:
    return TravelOut(
        car_min=travel.car_min,
        walk_min=travel.walk_min,
        km=round(travel.km, 1),
        source=travel.source,
    )


# --- Where to look ---------------------------------------------------------------------


class AreaIn(Arguments):
    place: str = Field(
        min_length=2,
        max_length=60,
        description="An area, town or district the client wants the pharmacy to be in, as "
        "they wrote it: 'Beirut', 'saida', 'Hamra'. Only a place the client named.",
    )
    district: str | None = Field(
        default=None,
        max_length=40,
        description="The district, only when the client said it or chose it after "
        "AREA_AMBIGUOUS. Never your own guess.",
    )


Areas = Annotated[
    list[AreaIn] | None,
    Field(
        max_length=3,
        description="Where the client wants to pick up, when they named places to look in "
        "('in Beirut', 'Saida or Beirut'): only pharmacies of these areas are searched, all "
        "of them together. It is not where the client is: travel times still count from "
        "where they are. Leave empty when they said nearest, anywhere, or nothing.",
    ),
]


def districts_of(tx: Tx, wanted: list[AreaIn] | None) -> frozenset[str] | None:
    """The districts the client asked to look in, from the names they wrote (R-S2).

    Each name is looked up in our own list, exactly as `set_area` does: a name that isn't
    listed, or that stands for places in several districts, is asked about, never guessed
    (BLD-D14, BLD-D15). A town or a neighbourhood counts as its district: "Hamra" looks in
    Beirut. The model gets names back, never a point (INV-24).
    """
    if not wanted:
        return None
    found: set[str] = set()
    for area in wanted:
        looked_up = areas.look_up(tx, area.place, area.district)
        if not looked_up.named:
            raise Refused(
                ToolError.AREA_NOT_FOUND,
                f"No listed area is written like '{area.place}'. If one of `closest` is "
                "clearly the same place spelled differently, call again with that name. "
                "Otherwise ask the client for a better-known area or town.",
                closest=[
                    {"area": place.name, "district": place.district} for place in looked_up.close
                ],
            )
        districts = {place.district for place in looked_up.named}
        if len(districts) > 1:
            raise Refused(
                ToolError.AREA_AMBIGUOUS,
                f"Several places are called '{area.place}'. Ask the client which one, with "
                "each choice as a quick reply ('Hamra, Beirut'), then call again with the "
                "district. Do not choose for them.",
                choices=[
                    {"area": place.name, "district": place.district} for place in looked_up.named
                ],
            )
        found |= districts
    return frozenset(found)


# --- search_catalog --------------------------------------------------------------------


class SearchCatalog(Arguments):
    query: str = Field(min_length=1, max_length=100, description="A brand or an ingredient.")
    limit: int = Field(default=8, ge=1, le=10)


class SearchCatalogOut(Output):
    products: list[ProductOut]
    did_you_mean: list[str]


def search_catalog(turn: Turn, tx: Tx, args: SearchCatalog) -> SearchCatalogOut:
    found = catalog.search_products(tx, args.query, limit=args.limit)
    return SearchCatalogOut(
        products=[product_out(tx, ref) for ref in found.products],
        did_you_mean=list(found.did_you_mean),
    )


# --- get_equivalents -------------------------------------------------------------------


class GetEquivalents(Arguments):
    product_id: uuid.UUID


class GetEquivalentsOut(Output):
    products: list[ProductOut]


def get_equivalents(turn: Turn, tx: Tx, args: GetEquivalents) -> GetEquivalentsOut:
    catalog.allowed_product(tx, args.product_id)
    others = catalog.equivalents(tx, args.product_id)
    note_asked(turn, tx, args.product_id)
    return GetEquivalentsOut(products=[product_out(tx, ref) for ref in others])


# --- find_options ----------------------------------------------------------------------


class FindOptions(Arguments):
    product_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=10,
        description="The medicine the client asked for first, then its other brands from "
        "get_equivalents if the client agreed to hear about them.",
    )
    qty: Qty = 1
    days_of_use: Days = 1
    pickup_day: date | None = Field(
        default=None,
        description="One of the upcoming days, only when the client named one day. Leave "
        "empty otherwise ('any day', 'today or tomorrow', nothing said): every day the "
        "pharmacy accepts is then searched, and each option lists the days that work.",
    )
    max_price: Money | None = None
    sort: Literal["best", "nearest", "cheapest", "latest_expiry"] = "best"
    limit: int = Field(default=5, ge=1, le=10)
    areas: Areas = None


class DayHours(Output):
    day: date
    hours: str


class OptionOut(Output):
    listing_id: uuid.UUID
    product_id: uuid.UUID
    product: str
    # Which box this is: one name can come in several strengths, forms and box sizes.
    strength: str | None = None
    form: str | None = None
    pack: str | None = None
    # True: another brand than the client asked for. Show it with show_other_brand;
    # never propose_reservation for it unless the client then asks for that brand.
    is_alternative: bool
    prescription_required: bool
    pharmacy: PharmacyOut
    travel: TravelOut
    price: str
    discount_pct: int
    expiry_date: date
    days_left: int
    available: int
    more_available: bool
    pickup_days_allowed: list[date]
    # The pharmacy's opening hours on each of those days: a pharmacy can close at
    # midday and open again in the afternoon.
    open_hours: list[DayHours]
    expiry_limits_pickup: bool
    # Set when expiry_limits_pickup is true: the last day this box can be picked up and
    # still last the client's days of use. From a later day it would not.
    pick_up_by: date | None = None


class NoMatchOut(Output):
    latest_expiry: date
    latest_pickup_day: date | None = None


class FindOptionsOut(Output):
    options: list[OptionOut]
    total_found: int
    left_out_by_pickup_day: int
    no_match: NoMatchOut | None = None
    # Why there is no option, when there is none. Say this reason, never another one:
    # none_listed (no pharmacy has it at all: another day changes nothing),
    # not_in_these_areas, over_budget, expires_too_early, not_on_that_day, not_enough
    # (no single box holds the quantity asked for; `most_in_one_box` says how many one has).
    why_none: str | None = None
    most_in_one_box: int | None = None
    # not_on_that_day: the days on which a pharmacy has it and it still lasts.
    days_that_work: list[date] = Field(default_factory=list)
    # not_in_these_areas: how many boxes other areas have (0: none anywhere).
    elsewhere: int | None = None
    # over_budget: the lowest price there is.
    cheapest: str | None = None
    # The districts that were searched, when `areas` was given.
    searched_in: list[str] = Field(default_factory=list)


def _why_none(found: search.SearchResult, options: list[OptionOut]) -> str | None:
    if options:
        return None
    if found.listings:
        return "not_enough"
    return found.why_none.value if found.why_none else None


def _same_medicine(tx: Tx, product_ids: list[uuid.UUID]) -> None:
    """Everything asked for in one search is one medicine: the first, or its equivalents."""
    first = catalog.allowed_product(tx, product_ids[0])
    allowed = set(catalog.products_in_group(tx, first, with_equivalents=True))
    if not set(product_ids) <= allowed:
        raise Refused(
            ToolError.NOT_SAME_MEDICINE,
            "These aren't the same medicine. Search one medicine at a time; other brands come "
            "only from get_equivalents.",
        )


def _the_brand(turn: Turn, tx: Tx, product_id: uuid.UUID) -> set[uuid.UUID]:
    """The catalog rows that are "the medicine the client asked for".

    In a chat: every row of the brand they named (another box size, another importer).
    The Ministry lists some brands several times, and a client who names the brand means
    any of its boxes (`09` FA-43). In a request: the one row its item names, because
    plans, claims and the item's count are all for that row (`04` R-C10).
    """
    if turn.request_id is not None:
        return {product_id}
    return catalog.same_brand(tx, product_id)


def _with_the_brands_other_rows(
    turn: Turn, tx: Tx, product_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """The products to search: those asked for, and the other rows of the first one's brand."""
    more = sorted(_the_brand(turn, tx, product_ids[0]) - set(product_ids), key=str)
    return [*product_ids, *more]


def _prepare_find_options(turn: Turn, args: FindOptions) -> None:
    def pharmacies(tx: Tx) -> list[uuid.UUID]:
        products = _with_the_brands_other_rows(turn, tx, args.product_ids)
        return sorted({box.pharmacy_id for box in visible_boxes(tx, product_ids=products)})

    road_times_first(turn, pharmacies)


def find_options(turn: Turn, tx: Tx, args: FindOptions) -> FindOptionsOut:
    _same_medicine(tx, args.product_ids)
    districts = districts_of(tx, args.areas)
    asked = args.product_ids[0]
    note_asked(turn, tx, asked)
    found = search.search_listings(
        tx,
        client_id=turn.client_id,
        product_ids=_with_the_brands_other_rows(turn, tx, args.product_ids),
        location=location_of(tx, turn),
        days_of_use=args.days_of_use,
        pickup_day=args.pickup_day,
        max_price_lbp=display.in_lbp(args.max_price, rate(tx)),
        sort=args.sort,
        on_foot=turn.state.preference == "walkable",
        limit=args.limit,
        districts=districts,
    )
    money = rate(tx)
    hours = pharmacies.weekly_hours(tx, [listing.pharmacy.id for listing in found.listings])
    # Another box size of the brand asked for is that brand, not an alternative.
    the_brand = _the_brand(turn, tx, asked)
    options = [
        OptionOut(
            listing_id=listing.id,
            product_id=listing.product.id,
            product=listing.product.name,
            strength=listing.product.strength,
            form=listing.product.form,
            pack=listing.product.pack,
            is_alternative=listing.product.id not in the_brand,
            prescription_required=listing.product.prescription_required,
            pharmacy=pharmacy_out(listing.pharmacy),
            travel=travel_out(listing.travel),
            price=display.money(listing.price_lbp, money),
            discount_pct=listing.discount_pct,
            expiry_date=listing.expiry_date,
            days_left=listing.days_left,
            available=listing.available,
            more_available=listing.more_available,
            pickup_days_allowed=list(listing.pickup_days_allowed),
            open_hours=[
                DayHours(day=day, hours=pharmacies.day_hours(hours[listing.pharmacy.id], day))
                for day in listing.pickup_days_allowed
            ],
            expiry_limits_pickup=listing.expiry_limits_pickup,
            pick_up_by=(
                listing.pickup_days_allowed[-1]
                if listing.expiry_limits_pickup and listing.pickup_days_allowed
                else None
            ),
        )
        for listing in found.listings
        if listing.available >= args.qty
    ]
    turn.state.shown_listing_ids.extend(option.listing_id for option in options)
    return FindOptionsOut(
        options=options,
        total_found=found.total_found,
        left_out_by_pickup_day=found.left_out_by_pickup_day,
        no_match=(
            NoMatchOut(
                latest_expiry=found.no_match.latest_expiry,
                latest_pickup_day=found.no_match.latest_pickup_day,
            )
            if found.no_match
            else None
        ),
        # A reason whenever the client is shown nothing. Boxes found, but none with the
        # quantity asked for, is the tool's own reason: the search doesn't know of it.
        why_none=_why_none(found, options),
        most_in_one_box=(
            max(listing.available for listing in found.listings)
            if found.listings and not options
            else None
        ),
        days_that_work=list(found.days_that_work),
        elsewhere=found.elsewhere if found.why_none is search.WhyNone.NOT_IN_THESE_AREAS else None,
        cheapest=display.money(found.cheapest_lbp, money) if found.cheapest_lbp else None,
        searched_in=sorted(districts) if districts else [],
    )


# --- plan_basket -----------------------------------------------------------------------


class BasketItemIn(Arguments):
    product_id: uuid.UUID
    qty: Qty = 1
    days_of_use: Days = 1
    max_price: Money | None = None


class PlanBasket(Arguments):
    items: list[BasketItemIn] = Field(min_length=1, max_length=5)
    pickup_day: date | None = Field(
        default=None, description="One of the upcoming days. Leave empty if the client didn't say."
    )
    preference: Literal["fewest_trips", "cheapest", "nearest", "walkable"] | None = None
    max_plans: int = Field(default=3, ge=1, le=3)
    areas: Areas = None


class PlanItemOut(Output):
    product_id: uuid.UUID
    product: str
    listing_id: uuid.UUID
    qty: int
    price: str
    expiry_date: date


class PlanGroupOut(Output):
    group_index: int
    pharmacy: PharmacyOut
    hours_on_pickup_day: str
    items: list[PlanItemOut]


class RouteOut(Output):
    order: list[str]  # pharmacy names, in visiting order
    total_car_min: int
    total_walk_min: int
    source: str


class MissingOut(Output):
    product_id: uuid.UUID
    product: str
    qty_missing: int
    reason: str


class PlanOut(Output):
    plan_id: str
    pickup_day: date
    groups: list[PlanGroupOut]
    route: RouteOut
    total: str
    pharmacies_count: int
    missing: list[MissingOut]


class PlanBasketOut(Output):
    plans: list[PlanOut]
    unplannable: list[MissingOut]


def _lines(turn: Turn, tx: Tx, args: PlanBasket) -> list[BasketLine]:
    """The basket as the planner takes it. In a request, each medicine is tied to its item."""
    items_of_request: dict[uuid.UUID, uuid.UUID] = {}
    if turn.request_id is not None:
        rows = tx.session.execute(
            select(RequestItem.product_id, RequestItem.id, RequestItem.state).where(
                RequestItem.request_id == turn.request_id
            )
        )
        items_of_request = {
            product_id: item_id
            for product_id, item_id, state in rows
            if ItemState(state) not in FINAL_ITEM_STATES
        }
    money = rate(tx)
    return [
        BasketLine(
            product_id=item.product_id,
            qty=item.qty,
            days_of_use=item.days_of_use,
            max_price_lbp=display.in_lbp(item.max_price, money),
            request_item_id=items_of_request.get(item.product_id),
        )
        for item in args.items
    ]


def _prepare_plan_basket(turn: Turn, args: PlanBasket) -> None:
    """The road times a plan needs. With more pharmacies than the planner weighs (N-48),
    the trips from the client to all of them come first: the nearest are chosen by road."""

    def everyone(tx: Tx) -> list[uuid.UUID]:
        return planning.pharmacies_stocking(
            tx,
            lines=_lines(turn, tx, args),
            pickup_day=args.pickup_day,
            districts=districts_of(tx, args.areas),
        )

    def weighed(tx: Tx) -> list[uuid.UUID]:
        return planning.pharmacies_to_weigh(
            tx,
            lines=_lines(turn, tx, args),
            location=location_of(tx, turn),
            pickup_day=args.pickup_day,
            districts=districts_of(tx, args.areas),
        )

    road_times_first(turn, everyone)
    road_times_first(turn, weighed, between=True)


def _names(tx: Tx, product_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    rows = tx.session.execute(
        select(Product.id, Product.moph_name).where(Product.id.in_(product_ids))
    ).all()
    return {row[0]: row[1] for row in rows}


def _plan_id(turn: Turn, position: int) -> str:
    return f"plan-{str(turn.run_id)[:8]}-{len(turn.state.plans) + position}"


def plan_basket(turn: Turn, tx: Tx, args: PlanBasket) -> PlanBasketOut:
    found = planning.plan(
        tx,
        client_id=turn.client_id,
        lines=_lines(turn, tx, args),
        location=location_of(tx, turn),
        pickup_day=args.pickup_day,
        preference=args.preference or turn.state.preference,
        max_plans=args.max_plans,
        districts=districts_of(tx, args.areas),
    )
    names = _names(tx, {item.product_id for item in args.items})
    money = rate(tx)

    def missing(gaps: Any) -> list[MissingOut]:
        return [
            MissingOut(
                product_id=gap.product_id,
                product=names[gap.product_id],
                qty_missing=gap.qty_missing,
                # Pharmacies have it, but none in the areas the client asked to look in.
                reason=(
                    "not_in_these_areas" if gap.product_id in found.only_elsewhere else gap.reason
                ),
            )
            for gap in gaps
        ]

    hours = pharmacies.weekly_hours(
        tx, [stop.pharmacy.id for trip in found.trips for stop in trip.stops]
    )
    plans: list[PlanOut] = []
    stored: dict[str, PlanRef] = {}
    for position, trip in enumerate(found.trips, start=1):
        plan_id = _plan_id(turn, position)
        stored[plan_id] = _stored(trip)
        plans.append(
            PlanOut(
                plan_id=plan_id,
                pickup_day=trip.pickup_day,
                groups=[
                    PlanGroupOut(
                        group_index=index,
                        pharmacy=pharmacy_out(stop.pharmacy),
                        hours_on_pickup_day=pharmacies.day_hours(
                            hours[stop.pharmacy.id], trip.pickup_day
                        ),
                        items=[
                            PlanItemOut(
                                product_id=pick.product_id,
                                product=names[pick.product_id],
                                listing_id=pick.listing_id,
                                qty=pick.qty,
                                price=display.money(pick.price_lbp, money),
                                expiry_date=pick.expiry_date,
                            )
                            for pick in stop.picks
                        ],
                    )
                    for index, stop in enumerate(trip.stops)
                ],
                route=RouteOut(
                    order=[stop.pharmacy.name for stop in trip.stops],
                    total_car_min=trip.total_car_min,
                    total_walk_min=trip.total_walk_min,
                    source=trip.source,
                ),
                total=display.money(trip.total_lbp, money),
                pharmacies_count=len(trip.stops),
                missing=missing(trip.missing),
            )
        )
    turn.state.plans.update(stored)
    return PlanBasketOut(plans=plans, unplannable=missing(found.unplannable))


def _stored(trip: PlannedTrip) -> PlanRef:
    return PlanRef(
        pickup_day=trip.pickup_day,
        groups=[
            PlanGroup(
                pharmacy_id=stop.pharmacy.id,
                picks=[
                    PlanPick(
                        product_id=pick.product_id,
                        listing_id=pick.listing_id,
                        qty=pick.qty,
                        price_lbp=pick.price_lbp,
                        days_of_use=pick.days_of_use,
                        request_item_id=pick.request_item_id,
                    )
                    for pick in stop.picks
                ],
            )
            for stop in trip.stops
        ],
    )


# --- get_reservations ------------------------------------------------------------------


class GetReservations(Arguments):
    view: Literal["active", "recent"] = "active"


class ReservationOut(Output):
    ref: str
    product: str
    pharmacy_name: str
    units: int
    state: str
    status_text: str
    deadline_display: str | None = None
    prescription_required: bool


class GetReservationsOut(Output):
    reservations: list[ReservationOut]


_STATUS_TEXT = {
    OrderState.OFFERED: "Offered to the client; waiting for their tap",
    OrderState.RESERVED: "Reserved; waiting for pickup",
    OrderState.PICKED_UP: "Picked up",
    OrderState.NOT_AVAILABLE: "The pharmacy marked it not available",
    OrderState.EXPIRED_NO_SHOW: "Not picked up in time",
    OrderState.CANCELLED_BY_CLIENT: "Cancelled by the client",
    OrderState.CANCELLED_BY_SYSTEM: "Cancelled by DawaLink",
    OrderState.OFFER_DECLINED: "Offer declined",
    OrderState.OFFER_EXPIRED: "Offer expired",
    OrderState.OFFER_WITHDRAWN: "Offer withdrawn",
}


def _until(order: Order) -> str | None:
    """When a reservation must be picked up, or an offer accepted."""
    moment = order.deadline or order.offer_expires_at
    return display.when(moment) if moment else None


def get_reservations(turn: Turn, tx: Tx, args: GetReservations) -> GetReservationsOut:
    statement = (
        select(Order, Product, Pharmacy.name)
        .join(Product, Product.id == Order.product_id)
        .join(Pharmacy, Pharmacy.id == Order.pharmacy_id)
        .where(Order.client_id == turn.client_id)
        .order_by(Order.created_at.desc())
        .limit(10)
    )
    if args.view == "active":
        statement = statement.where(Order.state.in_(["OFFERED", "RESERVED"]))
    rows = tx.session.execute(statement).all()
    return GetReservationsOut(
        reservations=[
            ReservationOut(
                ref=order.ref,
                product=product.moph_name,
                pharmacy_name=pharmacy_name,
                units=order.qty_requested,
                state=order.state,
                status_text=_STATUS_TEXT[OrderState(order.state)],
                deadline_display=_until(order),
                prescription_required=product.prescription_required,
            )
            for order, product, pharmacy_name in rows
        ]
    )


# --- get_request_status ----------------------------------------------------------------


class GetRequestStatus(Arguments):
    request_id: uuid.UUID


class WaitingOut(Output):
    claim_id: uuid.UUID | None = None
    watching: bool
    asked_pharmacies: int
    answers_by_display: str | None = None
    open_offer_count: int


class RequestItemOut(Output):
    item_id: uuid.UUID
    product_id: uuid.UUID
    product: str
    qty: int
    qty_secured: int
    days_of_use: int
    max_price: str | None = None
    state: str
    waiting: WaitingOut


class RequestStatusOut(Output):
    request_id: uuid.UUID
    ref: str
    state: str
    outcome: str | None = None
    alternatives_ok: bool
    ends_display: str
    minutes_left: int
    items: list[RequestItemOut]


def own_request(tx: Tx, turn: Turn, request_id: uuid.UUID) -> SourcingRequest:
    """The client's own request. Someone else's doesn't exist for this turn (FA-13)."""
    request = tx.session.get(SourcingRequest, request_id)
    if request is None or request.client_id != turn.client_id:
        raise ServiceError(Code.NOT_FOUND, "Unknown request.")
    return request


def request_status(tx: Tx, request: SourcingRequest) -> RequestStatusOut:
    """One shape for the tool and for the context of a sourcing turn (docs/07 §3.1)."""
    items = tx.session.execute(
        select(RequestItem, Product.moph_name)
        .join(Product, Product.id == RequestItem.product_id)
        .where(RequestItem.request_id == request.id)
        .order_by(RequestItem.position)
    ).all()
    live = [state.value for state in LIVE_STATES]
    claims = {
        claim.request_item_id: claim
        for claim in tx.session.execute(
            select(Claim).where(
                Claim.request_item_id.in_([item.id for item, _ in items]), Claim.state.in_(live)
            )
        ).scalars()
    }
    money = rate(tx)
    out: list[RequestItemOut] = []
    for item, name in items:
        claim = claims.get(item.id)
        asked, answers_by, offers = 0, None, 0
        if claim is not None:
            asks = (
                tx.session.execute(
                    select(EarlyReleaseAsk.respond_by)
                    .join(
                        EarlyReleaseRequest, EarlyReleaseRequest.id == EarlyReleaseAsk.er_request_id
                    )
                    .where(
                        EarlyReleaseRequest.claim_id == claim.id,
                        EarlyReleaseRequest.state == "OPEN",
                        EarlyReleaseAsk.state == "ASKED",
                    )
                )
                .scalars()
                .all()
            )
            asked = len(asks)
            answers_by = display.when(max(asks)) if asks else None
            offers = len(
                tx.session.execute(
                    select(Order.id).where(Order.claim_id == claim.id, Order.state == "OFFERED")
                ).all()
            )
        out.append(
            RequestItemOut(
                item_id=item.id,
                product_id=item.product_id,
                product=name,
                qty=item.qty,
                qty_secured=item.qty_secured,
                days_of_use=item.days_of_use,
                max_price=(
                    display.money(item.max_price_lbp, money)
                    if item.max_price_lbp is not None
                    else None
                ),
                state=item.state,
                waiting=WaitingOut(
                    claim_id=claim.id if claim else None,
                    watching=claim is not None,
                    asked_pharmacies=asked,
                    answers_by_display=answers_by,
                    open_offer_count=offers,
                ),
            )
        )
    left = int((request.ends_at - tx.now).total_seconds() // 60)
    return RequestStatusOut(
        request_id=request.id,
        ref=request.ref,
        state=request.state,
        outcome=request.outcome,
        alternatives_ok=request.alternatives_ok,
        ends_display=display.when(request.ends_at),
        minutes_left=max(left, 0),
        items=out,
    )


def get_request_status(turn: Turn, tx: Tx, args: GetRequestStatus) -> RequestStatusOut:
    return request_status(tx, own_request(tx, turn, args.request_id))


TOOLS = (
    Tool(
        "search_catalog",
        "Find medicines in the catalog by brand or ingredient. Returns products with their "
        "IDs. Always use it to turn what the client typed into a product ID.",
        SearchCatalog,
        search_catalog,
        BOTH,
        progress="Searching…",
    ),
    Tool(
        "get_equivalents",
        "The other brands of exactly the same medicine (same ingredient, strength and form). "
        "The only source of other brands, and only after the client agreed to hear about them. "
        "You never reserve one for the client: a pharmacist decides whether it suits them.",
        GetEquivalents,
        get_equivalents,
        BOTH,
    ),
    Tool(
        "find_options",
        "Where one medicine can be reserved now: pharmacies with a box that lasts the "
        "client's days of use from the pickup day, with travel time, opening hours, price "
        "and expiry. Use it to decide which pharmacy to recommend. An option with "
        "is_alternative true is another brand: show it with show_other_brand, don't reserve it.",
        FindOptions,
        find_options,
        BOTH,
        progress="Searching…",
        prepare=_prepare_find_options,
    ),
    Tool(
        "plan_basket",
        "Plans for several medicines at once: which pharmacies to visit, in which order, "
        "what to take from each, the total travel time and price, and what stays missing. "
        "One plan is one trip on one day. A plan holds the asked medicines themselves, never "
        "another brand.",
        PlanBasket,
        plan_basket,
        BOTH,
        progress="Planning…",
        prepare=_prepare_plan_basket,
    ),
    Tool(
        "get_reservations",
        "The client's own reservations and their status.",
        GetReservations,
        get_reservations,
        BOTH,
    ),
    Tool(
        "get_request_status",
        "The status of one of the client's sourcing requests: each medicine, what is secured, "
        "what is still being looked for, and the time left.",
        GetRequestStatus,
        get_request_status,
        BOTH,
    ),
)
