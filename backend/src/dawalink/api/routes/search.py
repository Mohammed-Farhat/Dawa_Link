"""The catalog, the search page and reserving from it (docs/06 §6.2, §6.3).

**Nothing here involves the agent**: a reservation made from the search page writes no
chat message and asks for no agent turn (R-AG5). With the assistant switched off, all of
this works the same (C15).
"""

import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Annotated, cast

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from dawalink.api import present
from dawalink.api.deps import AsClient, DoWork, IdempotencyKey, SignedIn, Work
from dawalink.api.errors import ApiError, ErrorCode
from dawalink.api.limits import Limiter
from dawalink.api.schemas.chat import LocationSummary
from dawalink.api.schemas.common import LocationIn
from dawalink.api.schemas.orders import Reservation
from dawalink.api.schemas.search import (
    DayHours,
    Ingredient,
    ListingDetail,
    NoMatch,
    ProductDetail,
    Products,
    Reserve,
    SearchListings,
    SearchResult,
    ViewListing,
)
from dawalink.db.models import ClientProfile, District, ProductIngredient
from dawalink.domain.geo import cell
from dawalink.domain.money import to_lbp
from dawalink.domain.orders import OrderSource
from dawalink.domain.pickup import upcoming_days
from dawalink.services import catalog, orders, pharmacies, search, travel
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.orders import ReserveLine
from dawalink.services.travel import Location, RoutingService

router = APIRouter(tags=["search"])

ROUTING_PAUSE_S = 60


@router.get("/catalog/products")
def find_products(
    _caller: SignedIn,
    work: DoWork,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
) -> Products:
    """Medicines whose name or ingredient looks like `q`. Spelling mistakes are
    tolerated, and **controlled medicines are never among them** (R-C6)."""
    with work.tx() as tx:
        lbp_per_usd = present.rate(tx)
        found = catalog.search_products(tx, q, limit=limit)
        return Products(
            items=[present.product_from_ref(ref, lbp_per_usd) for ref in found.products],
            did_you_mean=found.did_you_mean,
        )


@router.get("/catalog/products/{product_id}")
def read_product(product_id: uuid.UUID, _caller: SignedIn, work: DoWork) -> ProductDetail:
    with work.tx() as tx:
        try:
            product = catalog.allowed_product(tx, product_id)
        except ServiceError as refused:
            # A controlled medicine doesn't exist here, like one that was never listed.
            raise ServiceError(Code.NOT_FOUND, "Unknown medicine.") from refused
        ingredients = tx.session.execute(
            select(ProductIngredient)
            .where(ProductIngredient.product_id == product.id)
            .order_by(ProductIngredient.position)
        ).scalars()
        summary = present.product_summary(product, present.rate(tx))
        return ProductDetail(
            **summary.model_dump(),
            ingredients=[
                Ingredient(
                    name=row.name,
                    strength=(
                        f"{row.strength_value.normalize():f} {row.strength_unit or ''}".strip()
                        if row.strength_value is not None
                        else None
                    ),
                )
                for row in ingredients
            ],
            atc_code=product.atc_code,
            manufacturer=product.manufacturer,
        )


def _location(
    tx: Tx, client_id: uuid.UUID, sent: LocationIn | None
) -> tuple[Location, LocationSummary]:
    """Where travel times are counted from in this search: what was sent, or the
    profile's home district (R-S2). The summary says it in words, never as a point."""
    if sent is not None and sent.lat is not None and sent.lon is not None:
        here = travel.shared_location(sent.lat, sent.lon)
        return here, LocationSummary(source="shared", label="Your location")
    if sent is not None and sent.district_id is not None:
        chosen = tx.session.get(District, sent.district_id)
        if chosen is None:
            raise ServiceError(Code.VALIDATION_ERROR, "Unknown district.", field="district_id")
        return (
            travel.district_location(tx, chosen.id),
            LocationSummary(source="district", label=chosen.name),
        )
    profile = tx.session.get(ClientProfile, client_id)
    home_id = profile.district_id if profile else None
    home = tx.session.get(District, home_id) if home_id else None
    if home is None:
        raise ServiceError(
            Code.VALIDATION_ERROR, "Share your location or choose a district.", field="location"
        )
    return travel.district_location(tx, home.id), LocationSummary(source="profile", label=home.name)


def _count_the_point(request: Request, client_id: uuid.UUID, sent: LocationIn | None) -> None:
    """A new shared point can start a paid routing call, so a client may send only so
    many different ones an hour (N-47). The same place again costs nothing."""
    if sent is None or sent.lat is None or sent.lon is None:
        return
    here = cell(travel.shared_location(sent.lat, sent.lon).point)
    last = cast(dict[uuid.UUID, str], request.app.state.last_point_of_client)
    if last.get(client_id) == here:
        return
    wait_s = cast(Limiter, request.app.state.locations_per_client).wait_s(client_id)
    if wait_s:
        raise ApiError(ErrorCode.RATE_LIMITED, details={"retry_after_s": wait_s})
    last[client_id] = here


def _road_times_first(
    request: Request,
    work: Work,
    client_id: uuid.UUID,
    sent: LocationIn | None,
    pharmacy_ids_of: Callable[[Tx], list[uuid.UUID]],
) -> None:
    """Asks the routing service for the road times the search is about to show.

    No transaction is open while it answers. If it fails or isn't configured, the search
    shows straight-line estimates, labeled "about" (FX-18).
    """
    routing = cast("RoutingService | None", request.app.state.routing)
    # A routing service that just failed isn't asked again for a minute: without this,
    # every search would wait for its timeout while it is down.
    if routing is None or time.monotonic() < request.app.state.routing_paused_until:
        return
    with work.tx() as tx:
        origin, _ = _location(tx, client_id, sent)
        pharmacy_ids = pharmacy_ids_of(tx)
        if not pharmacy_ids:
            return
        wanted = travel.missing(tx, origin, pharmacy_ids)
    rows = travel.fetch(routing, wanted)
    if wanted and not rows:
        request.app.state.routing_paused_until = time.monotonic() + ROUTING_PAUSE_S
    if rows:
        with work.tx() as tx:
            travel.store(tx, rows)


@router.post("/listings/search")
def search_listings(
    body: SearchListings, caller: AsClient, work: DoWork, request: Request
) -> SearchResult:
    """The visible boxes of one medicine, **and only of that medicine**: search never
    shows another brand (R-S4).

    With `days_of_use`, boxes that don't last are left out. With `pickup_day`, only
    pharmacies that accept that day are shown, and the fit is counted from it.
    """
    _count_the_point(request, caller.user_id, body.location)
    _road_times_first(
        request,
        work,
        caller.user_id,
        body.location,
        lambda tx: list(
            {box.pharmacy_id for box in search.visible_boxes(tx, product_ids=[body.product_id])}
        ),
    )
    with work.tx() as tx:
        origin, where = _location(tx, caller.user_id, body.location)
        lbp_per_usd = present.rate(tx)
        max_price_lbp = (
            to_lbp(body.max_price.amount, body.max_price.currency, int(lbp_per_usd or 1))
            if body.max_price
            else None
        )
        if body.max_price and body.max_price.currency == "USD" and not lbp_per_usd:
            raise ServiceError(Code.VALIDATION_ERROR, "No exchange rate is known for USD amounts.")
        found = search.search_listings(
            tx,
            client_id=caller.user_id,
            product_ids=[body.product_id],
            location=origin,
            days_of_use=body.days_of_use,
            pickup_day=body.pickup_day,
            max_price_lbp=max_price_lbp,
            sort=body.sort,
            on_foot=body.on_foot,
            limit=body.limit,
            offset=body.cursor,
        )
        product = catalog.allowed_product(tx, body.product_id)
        shown = present.listings(tx, found.listings, lbp_per_usd)
        after = body.cursor + len(shown)
        return SearchResult(
            product=present.product_summary(product, lbp_per_usd),
            items=shown,
            total_found=found.total_found,
            left_out_by_pickup_day=found.left_out_by_pickup_day,
            no_match=(
                NoMatch(
                    latest_expiry=found.no_match.latest_expiry,
                    latest_pickup_day=found.no_match.latest_pickup_day,
                )
                if found.no_match
                else None
            ),
            next_cursor=after if after < found.total_found else None,
            location=where,
            upcoming_days=upcoming_days(tx.now),
            server_now=tx.now,
        )


@router.post("/listings/{listing_id}/view")
def view_listing(
    listing_id: uuid.UUID, body: ViewListing, caller: AsClient, work: DoWork, request: Request
) -> ListingDetail:
    """One box and its pharmacy, for their own page (CS-7). A box that stopped being
    visible answers `NOT_FOUND`."""
    _count_the_point(request, caller.user_id, body.location)
    _road_times_first(
        request,
        work,
        caller.user_id,
        body.location,
        lambda tx: [box.pharmacy_id for box in search.visible_boxes(tx, item_ids=[listing_id])],
    )
    with work.tx() as tx:
        origin, where = _location(tx, caller.user_id, body.location)
        found = search.one_listing(
            tx,
            client_id=caller.user_id,
            item_id=listing_id,
            location=origin,
            days_of_use=body.days_of_use,
        )
        weekly = pharmacies.weekly_hours(tx, [found.pharmacy.id])[found.pharmacy.id]
        return ListingDetail(
            listing=present.listings(tx, [found], present.rate(tx))[0],
            week=[
                DayHours(day=day, hours=pharmacies.day_hours(weekly, day))
                for day in (tx.today + timedelta(days=ahead) for ahead in range(7))
            ],
            location=where,
            server_now=tx.now,
        )


@router.post("/reservations", status_code=201)
def reserve(body: Reserve, caller: AsClient, work: DoWork, key: IdempotencyKey) -> Reservation:
    """[Reserve] on the search page: the box is the client's at once (O1).

    The same `Idempotency-Key` sent twice returns the same reservation: a double tap or a
    network retry never reserves two boxes. `source` is "search", so the agent is never
    told (R-AG5).
    """
    with work.tx() as tx:
        made = orders.reserve(
            tx,
            client_id=caller.user_id,
            lines=[
                ReserveLine(body.listing_id, body.qty, body.expected_price_lbp, body.days_of_use)
            ],
            pickup_day=body.pickup_day,
            source=OrderSource.SEARCH,
            idempotency_key=f"search:{key}",
        )
        return present.reservations(tx, made)[0]
