"""The catalog, the search page and reserving from it (docs/06 §6.2, §6.3).

**Nothing here involves the agent**: a reservation made from the search page writes no
chat message and asks for no agent turn (R-AG5). With the assistant switched off, all of
this works the same (C15).
"""

import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Annotated, cast

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from dawalink.api import present
from dawalink.api.deps import AsClient, DoWork, IdempotencyKey, SignedIn, Work
from dawalink.api.errors import ApiError, ErrorCode
from dawalink.api.limits import Limiter
from dawalink.api.schemas.chat import LocationSummary
from dawalink.api.schemas.common import LocationIn, MoneyIn
from dawalink.api.schemas.orders import Reservation
from dawalink.api.schemas.search import (
    DayHours,
    Ingredient,
    ListingDetail,
    MedicineGroup,
    NameSearchResult,
    NoMatch,
    ProductDetail,
    Products,
    Reserve,
    SearchByName,
    Searched,
    Searches,
    SearchListings,
    SearchResult,
    ViewListing,
)
from dawalink.db.models import District, ProductIngredient
from dawalink.domain.accounts import ClientStatus
from dawalink.domain.geo import cell
from dawalink.domain.money import to_lbp
from dawalink.domain.orders import OrderSource
from dawalink.domain.pickup import upcoming_days
from dawalink.services import (
    catalog,
    clients,
    orders,
    pharmacies,
    search,
    search_history,
    travel,
)
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.orders import ReserveLine
from dawalink.services.travel import Location, RoutingService

router = APIRouter(tags=["search"])


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


def location_of(
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
    home = clients.home(tx, client_id)
    if home is None:
        raise ServiceError(
            Code.VALIDATION_ERROR, "Share your location or choose a district.", field="location"
        )
    return home.location, present.home_summary(home)


def count_the_point(request: Request, client_id: uuid.UUID, sent: LocationIn | None) -> None:
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
    if routing is None:
        return
    with work.tx() as tx:
        origin, _ = location_of(tx, client_id, sent)
        pharmacy_ids = pharmacy_ids_of(tx)
        if not pharmacy_ids:
            return
        wanted = travel.missing(tx, origin, pharmacy_ids)
    # A routing service that just failed isn't asked again for a while, by the search page
    # or the agent: `travel.fetch` keeps that pause, and answers nothing meanwhile.
    rows = travel.fetch(routing, wanted)
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
    count_the_point(request, caller.user_id, body.location)
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
        origin, where = location_of(tx, caller.user_id, body.location)
        lbp_per_usd = present.rate(tx)
        max_price_lbp = _price_limit(body.max_price, lbp_per_usd)
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
            open_now=body.open_now,
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


def _price_limit(limit: MoneyIn | None, lbp_per_usd: Decimal | None) -> int | None:
    """A price limit given in either currency, in whole LBP."""
    if limit is None:
        return None
    if limit.currency == "USD" and not lbp_per_usd:
        raise ServiceError(Code.VALIDATION_ERROR, "No exchange rate is known for USD amounts.")
    return to_lbp(limit.amount, limit.currency, int(lbp_per_usd or 1))


@router.post("/listings/search-by-name")
def search_by_name(
    body: SearchByName, caller: AsClient, work: DoWork, request: Request
) -> NameSearchResult:
    """Everything in stock for a typed name, grouped by medicine (CS-6).

    "panadol" answers with every Panadol a pharmacy lists, each under its own name,
    strength and form; a misspelled name answers with the closest one and says so.
    **Still only what was typed** (R-S4): a medicine is here because its name, or what it
    contains, matches the words, never because it could replace another one.
    """
    count_the_point(request, caller.user_id, body.location)
    _road_times_first(
        request,
        work,
        caller.user_id,
        body.location,
        lambda tx: list(
            {
                box.pharmacy_id
                for box in search.visible_boxes(
                    tx, product_ids=[p.id for p in search.medicines_named(tx, body.q).products]
                )
            }
        ),
    )
    with work.tx() as tx:
        origin, where = location_of(tx, caller.user_id, body.location)
        lbp_per_usd = present.rate(tx)
        found = search.search_by_name(
            tx,
            client_id=caller.user_id,
            query=body.q,
            location=origin,
            days_of_use=body.days_of_use,
            pickup_day=body.pickup_day,
            max_price_lbp=_price_limit(body.max_price, lbp_per_usd),
            sort=body.sort,
            on_foot=body.on_foot,
            open_now=body.open_now,
            per_medicine=body.per_medicine,
        )
        # Every group's boxes are presented at once: their pharmacies are read once, not
        # once per medicine (review A#29).
        shown = iter(
            present.listings(
                tx,
                [listing for group in found.groups for listing in group.result.listings],
                lbp_per_usd,
            )
        )
        return NameSearchResult(
            groups=[
                MedicineGroup(
                    product=present.product_summary(group.product, lbp_per_usd),
                    by_ingredient=group.by_ingredient,
                    items=[next(shown) for _ in group.result.listings],
                    total_found=group.result.total_found,
                    no_match=(
                        NoMatch(
                            latest_expiry=group.result.no_match.latest_expiry,
                            latest_pickup_day=group.result.no_match.latest_pickup_day,
                        )
                        if group.result.no_match
                        else None
                    ),
                )
                for group in found.groups
            ],
            closest=found.closest,
            did_you_mean=found.did_you_mean,
            location=where,
            upcoming_days=upcoming_days(tx.now),
            server_now=tx.now,
        )


@router.get("/me/searches")
def last_searches(caller: AsClient, work: DoWork) -> Searches:
    """The caller's last searches, the newest first (CS-6). Nobody else reads them."""
    with work.tx() as tx:
        return Searches(items=search_history.recent(tx, caller.user_id))


@router.post("/me/searches")
def keep_a_search(body: Searched, caller: AsClient, work: DoWork) -> Searches:
    """Keeps a name the client searched. The page sends it when a search led somewhere (a
    result was opened, or Enter was pressed), not for every letter typed. A name that is
    not a medicine's name in shape is quietly left out."""
    with work.tx() as tx:
        _own_searches(tx, caller.user_id)
        search_history.record(tx, caller.user_id, body.q)
        return Searches(items=search_history.recent(tx, caller.user_id))


@router.delete("/me/searches")
def clear_searches(caller: AsClient, work: DoWork) -> Searches:
    """[Clear]: the caller's whole list is deleted."""
    with work.tx() as tx:
        _own_searches(tx, caller.user_id)
        search_history.clear(tx, caller.user_id)
        return Searches(items=[])


def _own_searches(tx: Tx, client_id: uuid.UUID) -> None:
    """The caller's profile, locked, before their list of searches changes, as for their
    other details (`accounts._own_details`). A deletion holds this lock while it empties
    the rows, so a search kept in the moment after a deletion waits for it, finds the
    account deleted, and is answered as a logged-out person is: nothing is written back
    onto the emptied rows (R-AU10)."""
    profile = clients.profile(tx, client_id, lock=True)
    if profile.status == ClientStatus.DELETED.value:
        raise ApiError(ErrorCode.UNAUTHENTICATED)


@router.post("/listings/{listing_id}/view")
def view_listing(
    listing_id: uuid.UUID, body: ViewListing, caller: AsClient, work: DoWork, request: Request
) -> ListingDetail:
    """One box and its pharmacy, for their own page (CS-7). A box that stopped being
    visible answers `NOT_FOUND`."""
    count_the_point(request, caller.user_id, body.location)
    _road_times_first(
        request,
        work,
        caller.user_id,
        body.location,
        lambda tx: [box.pharmacy_id for box in search.visible_boxes(tx, item_ids=[listing_id])],
    )
    with work.tx() as tx:
        origin, where = location_of(tx, caller.user_id, body.location)
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
