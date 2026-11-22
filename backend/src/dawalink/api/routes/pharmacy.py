"""The pharmacy's side: its profile, the counter, early-release asks (docs/06 §6.9).

**No answer here says anything about a client** (INV-9): an order number, a product,
units, a price and times. Someone else's reservation or ask doesn't exist.
"""

import uuid
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select, text

from dawalink.api import present
from dawalink.api.deps import AsPharmacist, DoWork, Work, get_work
from dawalink.api.schemas.accounts import OpeningRange
from dawalink.api.schemas.common import Pin, Skip
from dawalink.api.schemas.pharmacy import (
    AcceptAsk,
    AskAnswered,
    Dashboard,
    DeclineAsk,
    EarlyReleaseAsk,
    EarlyReleaseAsks,
    NotAvailable,
    PharmacyProfile,
    PharmacyReservation,
    PharmacyReservations,
    PrivateItem,
    RegistrationChange,
    SettingsChange,
)
from dawalink.api.schemas.search import DayHours
from dawalink.db.models import (
    District,
    EarlyReleaseRequest,
    InventoryItem,
    Order,
    Pharmacy,
    Product,
    User,
)
from dawalink.db.models import EarlyReleaseAsk as AskRow
from dawalink.domain.accounts import (
    PharmacyStatus,
    pharmacy_can_manage_inventory,
    pharmacy_can_update_reservations,
)
from dawalink.domain.clock import end_of_day
from dawalink.domain.expiry import days_left
from dawalink.domain.numbers import (
    AUTO_LIST_CHOICES,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    STALE_INVENTORY_AFTER,
)
from dawalink.domain.opening_hours import closes_at, is_open
from dawalink.domain.orders import OrderState
from dawalink.domain.pricing import release_suggested_price_lbp
from dawalink.services import auth, counter, early_release, pharmacies, pharmacy_profile
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

router = APIRouter(prefix="/pharmacy", tags=["pharmacy"])

NEW_FOR = timedelta(hours=24)  # docs/06 §6.9: "is_new"


def own_pharmacy(caller: AsPharmacist, work: Annotated[Work, Depends(get_work)]) -> uuid.UUID:
    """The pharmacy of the logged-in pharmacist (one account per pharmacy, P-D5)."""
    with work.tx() as tx:
        pharmacy = auth.pharmacy_of(tx, caller.user_id)
        if pharmacy is None:
            raise ServiceError(Code.NOT_FOUND, "This account has no pharmacy.")
        return pharmacy.id


OwnPharmacy = Annotated[uuid.UUID, Depends(own_pharmacy)]


def _require(tx: Tx, pharmacy_id: uuid.UUID, *, inventory: bool = False) -> Pharmacy:
    """The status gate of docs/06 §2.2: an approved pharmacy does everything, a suspended
    one only finishes the reservations it holds, a pending or rejected one neither."""
    pharmacy = tx.session.get_one(Pharmacy, pharmacy_id)
    status = PharmacyStatus(pharmacy.status)
    allowed = (
        pharmacy_can_manage_inventory(status)
        if inventory
        else pharmacy_can_update_reservations(status)
    )
    if not allowed:
        raise ServiceError(
            Code.PHARMACY_NOT_APPROVED,
            "This pharmacy can't do that in its current status.",
            status=status.value,
        )
    return pharmacy


def _profile(tx: Tx, pharmacy_id: uuid.UUID) -> PharmacyProfile:
    tx.session.flush()
    pharmacy = tx.session.get_one(Pharmacy, pharmacy_id)
    weekly = pharmacies.weekly_hours(tx, [pharmacy_id])[pharmacy_id]
    owner = tx.session.get_one(User, pharmacy.owner_user_id)
    return PharmacyProfile(
        id=pharmacy.id,
        name=pharmacy.name,
        status=pharmacy.status,
        status_reason=pharmacy.status_reason,
        info_requested=pharmacy.info_requested,
        email_verified=owner.email_verified_at is not None,
        address=pharmacy.address,
        district=tx.session.get_one(District, pharmacy.district_id).name,
        district_id=pharmacy.district_id,
        phone=pharmacy.phone,
        license_number=pharmacy.license_number,
        location=Pin(lat=float(pharmacy.lat), lon=float(pharmacy.lon)),
        pickup_days=pharmacy.pickup_days,
        auto_list_days=pharmacy.auto_list_days,
        auto_list_choices=list(AUTO_LIST_CHOICES),
        hours=[
            OpeningRange(weekday=weekday, open=opens, close=closes)
            for weekday, opens, closes in pharmacy_profile.hours_rows(weekly)
        ],
        week=[
            DayHours(day=day, hours=pharmacies.day_hours(weekly, day))
            for day in (tx.today + timedelta(days=ahead) for ahead in range(7))
        ],
        open_now=is_open(weekly, tx.now),
        closes_at=closes_at(weekly, tx.now),
        server_now=tx.now,
    )


@router.get("/me")
def read_pharmacy(pharmacy_id: OwnPharmacy, work: DoWork) -> PharmacyProfile:
    """The pharmacy's own details, in any status (a pending one sees it is pending)."""
    with work.tx() as tx:
        return _profile(tx, pharmacy_id)


@router.patch("/me/registration")
def change_registration(
    body: RegistrationChange, pharmacy_id: OwnPharmacy, work: DoWork
) -> PharmacyProfile:
    """While it waits, or after a rejection, the pharmacy corrects what it typed (PS-2).
    Only what is sent changes; everything is checked again as at registration."""
    sent = body.model_fields_set
    with work.tx() as tx:
        pharmacy = tx.session.get_one(Pharmacy, pharmacy_id)
        weekly = pharmacies.weekly_hours(tx, [pharmacy_id])[pharmacy_id]
        now = pharmacy_profile.current(tx, pharmacy, weekly)

        def value(name: str, stored: Any) -> Any:
            given = getattr(body, name)
            return given if name in sent and given is not None else stored

        location = body.location if "location" in sent else None
        details = pharmacy_profile.checked(
            tx,
            name=value("name", now.name),
            license_number=value("license_number", now.license_number),
            phone=value("phone", now.phone),
            address=value("address", now.address),
            district_id=value("district_id", now.district_id),
            lat=location.lat if location else float(now.lat),
            lon=location.lon if location else float(now.lon),
            pickup_days=value("pickup_days", now.pickup_days),
            hours=(
                [(row.weekday, row.open, row.close) for row in body.hours]
                if "hours" in sent and body.hours is not None
                else pharmacy_profile.hours_rows(weekly)
            ),
        )
        pharmacy_profile.change_registration(tx, pharmacy_id, details)
        return _profile(tx, pharmacy_id)


@router.post("/me/resubmit")
def resubmit_registration(pharmacy_id: OwnPharmacy, work: DoWork) -> PharmacyProfile:
    """After a rejection: back in the queue of DawaLink's team (SM-1)."""
    with work.tx() as tx:
        pharmacy_profile.resubmit(tx, pharmacy_id)
        return _profile(tx, pharmacy_id)


@router.patch("/me")
def change_settings(
    body: SettingsChange, pharmacy_id: OwnPharmacy, work: DoWork
) -> PharmacyProfile:
    """An approved pharmacy changes its opening hours, its pickup time, its phone number,
    its address or its pin (PS-10). Reservations already made keep the deadline they were
    given (R-T5). A new address or pin counts at once; an admin looks at the pin again."""
    sent = body.model_fields_set
    with work.tx() as tx:
        weekly = pharmacies.weekly_hours(tx, [pharmacy_id])[pharmacy_id]
        pharmacy_profile.change_settings(
            tx,
            pharmacy_id,
            weekly,
            hours=(
                [(row.weekday, row.open, row.close) for row in body.hours]
                if "hours" in sent and body.hours is not None
                else None
            ),
            pickup_days=body.pickup_days if "pickup_days" in sent else None,
            auto_list_days=body.auto_list_days if "auto_list_days" in sent else None,
            phone=body.phone if "phone" in sent else None,
            address=body.address if "address" in sent else None,
            district_id=body.district_id if "district_id" in sent else None,
            location=(body.location.lat, body.location.lon)
            if "location" in sent and body.location is not None
            else None,
        )
        return _profile(tx, pharmacy_id)


@router.get("/dashboard")
def pharmacy_dashboard(pharmacy_id: OwnPharmacy, work: DoWork) -> Dashboard:
    with work.tx() as tx:
        _require(tx, pharmacy_id)
        reserved = Order.state == OrderState.RESERVED.value
        mine = Order.pharmacy_id == pharmacy_id

        def count(*where: Any) -> int:
            return tx.session.execute(
                select(func.count()).select_from(Order).where(mine, *where)
            ).scalar_one()

        last_update = tx.session.execute(
            select(func.max(InventoryItem.last_edited_at)).where(
                InventoryItem.pharmacy_id == pharmacy_id
            )
        ).scalar()
        return Dashboard(
            new_reservations=count(reserved, Order.reserved_at > tx.now - NEW_FOR),
            due_today=count(reserved, Order.deadline <= end_of_day(tx.today)),
            open_asks=tx.session.execute(
                select(func.count())
                .select_from(AskRow)
                .where(AskRow.pharmacy_id == pharmacy_id, AskRow.state == "ASKED")
            ).scalar_one(),
            # The packs clients can see now, not the boxes' rows: a row may hold several.
            live_listings=tx.session.execute(
                text(
                    "SELECT coalesce(sum(v.qty_available), 0) "
                    "FROM visible_listings(:today) v WHERE v.pharmacy_id = :id"
                ),
                {"today": tx.today, "id": pharmacy_id},
            ).scalar_one(),
            units_reserved=tx.session.execute(
                select(func.coalesce(func.sum(Order.qty_locked), 0)).where(mine, reserved)
            ).scalar_one(),
            last_inventory_update=last_update,
            stale=last_update is None or last_update < tx.now - STALE_INVENTORY_AFTER,
            server_now=tx.now,
        )


# --- The counter ------------------------------------------------------------------------

_SHOWN = [state.value for state in present.RESERVATION_STATES]
_WORDS = {
    OrderState.PICKED_UP: "Picked up",
    OrderState.NOT_AVAILABLE: "Marked not available",
    OrderState.EXPIRED_NO_SHOW: "Missed pickup: back in stock",
    OrderState.CANCELLED_BY_CLIENT: "Cancelled by the client: put the box back",
    OrderState.CANCELLED_BY_SYSTEM: "Cancelled by DawaLink: put the box back",
}


def _reservations(tx: Tx, orders: list[Order]) -> list[PharmacyReservation]:
    if not orders:
        return []
    lbp_per_usd = present.rate(tx)
    products = {
        product.id: product
        for product in tx.session.execute(
            select(Product).where(Product.id.in_({order.product_id for order in orders}))
        ).scalars()
    }
    items = {
        item.id: item
        for item in tx.session.execute(
            select(InventoryItem).where(
                InventoryItem.id.in_({order.inventory_item_id for order in orders})
            )
        ).scalars()
    }
    shown = []
    for order in orders:
        state = OrderState(order.state)
        qty = (
            order.qty_picked_up
            if state is OrderState.PICKED_UP and order.qty_picked_up is not None
            else order.qty_locked or order.qty_requested
        )
        item = items[order.inventory_item_id]
        waiting = state is OrderState.RESERVED
        shown.append(
            PharmacyReservation(
                id=order.id,
                ref=order.ref,
                state=order.state,
                status_text=(
                    f"Hand over by {present.clock_words(order.deadline, tx.now)}"
                    if waiting and order.deadline
                    else _WORDS.get(state, "Reserved")
                ),
                product=present.product_summary(products[order.product_id], lbp_per_usd),
                batch=item.batch,
                expiry_date=item.expiry_date,
                qty=qty,
                qty_requested=order.qty_requested,
                price_each=present.money(order.price_snapshot_lbp, lbp_per_usd),
                total=present.money(order.price_snapshot_lbp * qty, lbp_per_usd),
                pickup_day=order.pickup_day,
                deadline=order.deadline,
                is_new=bool(waiting and order.reserved_at and order.reserved_at > tx.now - NEW_FOR),
                created_at=order.created_at,
                closed_at=order.closed_at,
            )
        )
    return shown


@router.get("/reservations")
def list_pharmacy_reservations(
    pharmacy_id: OwnPharmacy,
    work: DoWork,
    view: Literal["active", "history"] = "active",
    q: Annotated[str | None, Query(max_length=20)] = None,
    cursor: Skip = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PharmacyReservations:
    """The pharmacy's reservations. With `q`, the one with that order number, however it
    was typed ("r7k3q2f" finds R-7K3Q2F), whatever its state: the counter needs to see
    "already picked up" too."""
    with work.tx() as tx:
        _require(tx, pharmacy_id)
        if q is not None and q.strip():
            found = counter.find_by_number(tx, pharmacy_id, q)
            rows = [found] if found is not None and found.state in _SHOWN else []
            return PharmacyReservations(
                items=_reservations(tx, rows), next_cursor=None, server_now=tx.now
            )
        statement = select(Order).where(Order.pharmacy_id == pharmacy_id)
        if view == "active":
            statement = statement.where(Order.state == OrderState.RESERVED.value).order_by(
                Order.deadline, Order.id
            )
        else:
            statement = statement.where(
                Order.state.in_(_SHOWN), Order.state != OrderState.RESERVED.value
            ).order_by(Order.closed_at.desc(), Order.id)
        rows = list(tx.session.execute(statement.offset(cursor).limit(limit + 1)).scalars())
        return PharmacyReservations(
            items=_reservations(tx, rows[:limit]),
            next_cursor=str(cursor + limit) if len(rows) > limit else None,
            server_now=tx.now,
        )


@router.post("/reservations/{reservation_id}/picked-up")
def mark_picked_up(
    reservation_id: uuid.UUID, pharmacy_id: OwnPharmacy, work: DoWork
) -> PharmacyReservation:
    """The client showed the order number and took the box (O2). There is no late
    pickup: after the deadline the box is back in stock (INV-7)."""
    with work.tx() as tx:
        order = counter.mark_picked_up(tx, pharmacy_id, reservation_id)
        return _reservations(tx, [order])[0]


@router.post("/reservations/{reservation_id}/not-available")
def mark_not_available(
    reservation_id: uuid.UUID, body: NotAvailable, pharmacy_id: OwnPharmacy, work: DoWork
) -> PharmacyReservation:
    """Some or all of the packs aren't there (O3). Never a penalty for the client: they
    are told, and the agent looks elsewhere."""
    with work.tx() as tx:
        order = counter.mark_not_available(tx, pharmacy_id, reservation_id, body.units)
        return _reservations(tx, [order])[0]


# --- Early-release asks -----------------------------------------------------------------


def _asks(tx: Tx, rows: list[AskRow]) -> list[EarlyReleaseAsk]:
    if not rows:
        return []
    lbp_per_usd = present.rate(tx)
    products = {
        product.id: product
        for product in tx.session.execute(
            select(Product).where(Product.id.in_({row.product_id for row in rows}))
        ).scalars()
    }
    items = {
        item.id: item
        for item in tx.session.execute(
            select(InventoryItem).where(
                InventoryItem.id.in_({row.inventory_item_id for row in rows})
            )
        ).scalars()
    }
    needed = dict(
        tx.session.execute(
            select(EarlyReleaseRequest.id, EarlyReleaseRequest.qty).where(
                EarlyReleaseRequest.id.in_({row.er_request_id for row in rows})
            )
        ).all()
    )
    shown = []
    for row in rows:
        product, item = products[row.product_id], items[row.inventory_item_id]
        shown.append(
            EarlyReleaseAsk(
                id=row.id,
                state=row.state,
                product=present.product_summary(product, lbp_per_usd),
                qty_needed=needed[row.er_request_id],
                private_item=PrivateItem(
                    batch=item.batch,
                    expiry_date=item.expiry_date,
                    qty_available=max(0, item.qty_on_hand - item.qty_reserved),
                ),
                suggested_price=present.money(
                    release_suggested_price_lbp(
                        product.public_price_lbp,
                        item.price_override_lbp,
                        days_left(item.expiry_date, tx.today),
                    ),
                    lbp_per_usd,
                ),
                respond_by=row.respond_by,
                answered_at=row.answered_at,
            )
        )
    return shown


@router.get("/early-release-asks")
def list_early_release_asks(
    pharmacy_id: OwnPharmacy, work: DoWork, view: Literal["open", "history"] = "open"
) -> EarlyReleaseAsks:
    """ "A client needs this today, and you hold it privately. Release it?" The need is
    described without anything about the client (R-E8)."""
    with work.tx() as tx:
        _require(tx, pharmacy_id, inventory=True)
        statement = select(AskRow).where(AskRow.pharmacy_id == pharmacy_id)
        if view == "open":
            statement = statement.where(AskRow.state == "ASKED").order_by(AskRow.respond_by)
        else:
            statement = (
                statement.where(AskRow.state != "ASKED")
                .order_by(AskRow.updated_at.desc())
                .limit(MAX_PAGE_SIZE)
            )
        rows = list(tx.session.execute(statement).scalars())
        return EarlyReleaseAsks(items=_asks(tx, rows), server_now=tx.now)


@router.post("/early-release-asks/{ask_id}/accept")
def accept_early_release_ask(
    ask_id: uuid.UUID, body: AcceptAsk, pharmacy_id: OwnPharmacy, work: DoWork
) -> AskAnswered:
    """The pharmacy releases the box: the client gets an offer for two hours. If the need
    was met in the meantime, nothing is reserved and the pharmacy is thanked (R-E6)."""
    with work.tx() as tx:
        ask = early_release.accept_ask(
            tx, pharmacy_id, ask_id, qty=body.qty, price_lbp=body.price_lbp
        )
        if ask.state == "WITHDRAWN":
            return AskAnswered(state="WITHDRAWN", message="Thank you, this need was just met.")
        return AskAnswered(
            state="ACCEPTED", message="Thank you. The client has two hours to accept."
        )


@router.post("/early-release-asks/{ask_id}/decline", status_code=204)
def decline_early_release_ask(
    ask_id: uuid.UUID, body: DeclineAsk, pharmacy_id: OwnPharmacy, work: DoWork
) -> Response:
    with work.tx() as tx:
        early_release.decline_ask(tx, pharmacy_id, ask_id, body.reason)
    return Response(status_code=204)
