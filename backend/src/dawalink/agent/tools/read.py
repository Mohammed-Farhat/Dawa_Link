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
from dawalink.services import catalog, pharmacies, planning, search
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
    return GetEquivalentsOut(
        products=[product_out(tx, ref) for ref in catalog.equivalents(tx, args.product_id)]
    )


# --- find_options ----------------------------------------------------------------------


class FindOptions(Arguments):
    product_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=10,
        description="The medicine first, then its equivalents if the client agreed to them.",
    )
    qty: Qty = 1
    days_of_use: Days = 1
    pickup_day: date | None = Field(
        default=None, description="One of the upcoming days. Leave empty if the client didn't say."
    )
    max_price: Money | None = None
    sort: Literal["best", "nearest", "cheapest", "latest_expiry"] = "best"
    limit: int = Field(default=5, ge=1, le=10)


class DayHours(Output):
    day: date
    hours: str


class OptionOut(Output):
    listing_id: uuid.UUID
    product_id: uuid.UUID
    product: str
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


class NoMatchOut(Output):
    latest_expiry: date
    latest_pickup_day: date | None = None


class FindOptionsOut(Output):
    options: list[OptionOut]
    total_found: int
    left_out_by_pickup_day: int
    no_match: NoMatchOut | None = None


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


def _prepare_find_options(turn: Turn, args: FindOptions) -> None:
    def pharmacies(tx: Tx) -> list[uuid.UUID]:
        return sorted({box.pharmacy_id for box in visible_boxes(tx, product_ids=args.product_ids)})

    road_times_first(turn, pharmacies)


def find_options(turn: Turn, tx: Tx, args: FindOptions) -> FindOptionsOut:
    _same_medicine(tx, args.product_ids)
    asked = args.product_ids[0]
    found = search.search_listings(
        tx,
        client_id=turn.client_id,
        product_ids=args.product_ids,
        location=location_of(tx, turn),
        days_of_use=args.days_of_use,
        pickup_day=args.pickup_day,
        max_price_lbp=display.in_lbp(args.max_price, rate(tx)),
        sort=args.sort,
        on_foot=turn.state.preference == "walkable",
        limit=args.limit,
    )
    money = rate(tx)
    hours = pharmacies.weekly_hours(tx, [listing.pharmacy.id for listing in found.listings])
    options = [
        OptionOut(
            listing_id=listing.id,
            product_id=listing.product.id,
            product=listing.product.name,
            is_alternative=listing.product.id != asked,
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
    )


# --- plan_basket -----------------------------------------------------------------------


class BasketItemIn(Arguments):
    product_id: uuid.UUID
    qty: Qty = 1
    days_of_use: Days = 1
    allow_alternatives: bool = False
    max_price: Money | None = None


class PlanBasket(Arguments):
    items: list[BasketItemIn] = Field(min_length=1, max_length=5)
    pickup_day: date | None = Field(
        default=None, description="One of the upcoming days. Leave empty if the client didn't say."
    )
    preference: Literal["fewest_trips", "cheapest", "nearest", "walkable"] | None = None
    max_plans: int = Field(default=3, ge=1, le=3)


class PlanItemOut(Output):
    product_id: uuid.UUID
    product: str
    listing_id: uuid.UUID
    is_alternative: bool
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
            allow_alternatives=item.allow_alternatives,
            max_price_lbp=display.in_lbp(item.max_price, money),
            request_item_id=items_of_request.get(item.product_id),
        )
        for item in args.items
    ]


def _prepare_plan_basket(turn: Turn, args: PlanBasket) -> None:
    def pharmacies(tx: Tx) -> list[uuid.UUID]:
        in_play = planning.pharmacies_in_play(tx, _lines(turn, tx, args))
        return planning.nearest(tx, location_of(tx, turn), in_play)

    road_times_first(turn, pharmacies, between=True)


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
    )
    wanted = {item.product_id for item in args.items}
    names = _names(
        tx,
        wanted
        | {
            pick.listing_product_id
            for trip in found.trips
            for stop in trip.stops
            for pick in stop.picks
        },
    )
    money = rate(tx)

    def missing(gaps: Any) -> list[MissingOut]:
        return [
            MissingOut(
                product_id=gap.product_id,
                product=names[gap.product_id],
                qty_missing=gap.qty_missing,
                reason=gap.reason,
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
                                product=names[pick.listing_product_id],
                                listing_id=pick.listing_id,
                                is_alternative=pick.listing_product_id != pick.product_id,
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
        "The only source of alternatives, and only after the client agreed to them.",
        GetEquivalents,
        get_equivalents,
        BOTH,
    ),
    Tool(
        "find_options",
        "Where one medicine can be reserved now: pharmacies with a box that lasts the "
        "client's days of use from the pickup day, with travel time, opening hours, price "
        "and expiry. Use it to decide which pharmacy to recommend.",
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
        "One plan is one trip on one day.",
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
