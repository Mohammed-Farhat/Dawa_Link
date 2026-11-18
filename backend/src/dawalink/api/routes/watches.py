"""Watches ([Notify me]) and the in-app notifications (docs/06 §6.4, §6.8; docs/03 CS-11,
CS-12, PS-11).

A watch is a client's wait for one medicine, for the 6 hours of a search window. When a
box appears, the first client who waited gets an offer (R-PRI: code decides, nobody
else). The place a watch searches around travels in the request's body and is never
sent back: the answer says it in words.

A notification is something that already happened, said by a template. Its title and
its lines are built here from the same templates as its email, so no text typed by a
client or by an AI is in one; the only typed words are DawaLink's team's own, to a
pharmacy about its registration.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import Field
from sqlalchemy import func, select, update

from dawalink.api import present
from dawalink.api.deps import AsClient, DoWork, SignedIn
from dawalink.api.routes.search import count_the_point, location_of
from dawalink.api.schemas.common import (
    BeforeId,
    In,
    LocationIn,
    Money,
    MoneyIn,
    Out,
    ProductSummary,
)
from dawalink.db.models import Claim, District, Notification, Product
from dawalink.domain.claims import LIVE_STATES
from dawalink.domain.money import to_lbp
from dawalink.domain.numbers import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from dawalink.domain.vocabulary import ClaimKind, ClaimSource, UserRole
from dawalink.services import claims, email
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

router = APIRouter(tags=["watches and notifications"])


# --- Watches ------------------------------------------------------------------------------


class NewWatch(In):
    product_id: uuid.UUID
    qty: int = Field(default=1, ge=1, le=3)
    days_of_use: int = Field(default=1, ge=1, le=365)
    max_price: MoneyIn | None = None
    # None: the profile's home district (R-S2). A point is stored rounded, with the watch.
    location: LocationIn | None = None


class Watch(Out):
    id: uuid.UUID
    product: ProductSummary
    qty: int
    qty_missing: int
    days_of_use: int
    max_price: Money | None
    state: Literal["ACTIVE", "OFFER_PENDING", "FULFILLED", "EXPIRED", "CANCELLED"]
    # The district the watch searches around, as a name. Never a point (INV-24).
    district: str | None
    ends_at: datetime
    created_at: datetime


class Watches(Out):
    items: list[Watch]
    server_now: datetime


def _watch(tx: Tx, claim: Claim) -> Watch:
    rate = email.display_rate(tx)
    product = tx.session.get_one(Product, claim.product_id)
    district = tx.session.get(District, claim.district_id) if claim.district_id else None
    return Watch(
        id=claim.id,
        product=present.product_summary(product, rate),
        qty=claim.qty,
        qty_missing=claim.qty_missing,
        days_of_use=claim.days_of_use,
        max_price=present.money(claim.max_price_lbp, rate) if claim.max_price_lbp else None,
        state=claim.state,
        district=district.name if district else None,
        ends_at=claim.ends_at,
        created_at=claim.created_at,
    )


@router.post("/watches", status_code=201)
def notify_me(body: NewWatch, request: Request, caller: AsClient, work: DoWork) -> Watch:
    """[Notify me]: DawaLink watches for this medicine for 6 hours and offers the first
    box that appears, to whoever asked first (R-W1, R-PRI). Only during request hours.

    Asking twice for the same medicine answers `WATCH_EXISTS` with the watch's ID, so a
    repeated tap creates nothing: this endpoint needs no idempotency key.
    """
    count_the_point(request, caller.user_id, body.location)
    with work.tx() as tx:
        here, _ = location_of(tx, caller.user_id, body.location)
        rate = email.display_rate(tx)
        if body.max_price and body.max_price.currency == "USD" and not rate:
            raise ServiceError(
                Code.VALIDATION_ERROR, "No exchange rate is known: give the price in LBP."
            )
        claim = claims.create_watch(
            tx,
            client_id=caller.user_id,
            product_id=body.product_id,
            location=here,
            source=ClaimSource.SEARCH,
            qty=body.qty,
            days_of_use=body.days_of_use,
            max_price_lbp=to_lbp(body.max_price.amount, body.max_price.currency, int(rate or 1))
            if body.max_price
            else None,
        )
        return _watch(tx, claim)


@router.get("/watches")
def list_watches(caller: AsClient, work: DoWork, state: Literal["live", "all"] = "live") -> Watches:
    """The client's own watches, the newest first. `live`: still waiting or holding an
    offer."""
    with work.tx() as tx:
        statement = select(Claim).where(
            Claim.client_id == caller.user_id, Claim.kind == ClaimKind.WATCH.value
        )
        if state == "live":
            statement = statement.where(Claim.state.in_([s.value for s in LIVE_STATES]))
        rows = tx.session.execute(
            statement.order_by(Claim.created_at.desc()).limit(MAX_PAGE_SIZE)
        ).scalars()
        return Watches(items=[_watch(tx, row) for row in rows], server_now=tx.now)


@router.post("/watches/{watch_id}/cancel")
def stop_watching(watch_id: uuid.UUID, caller: AsClient, work: DoWork) -> Watch:
    """[Stop watching]. An offer the watch held goes to the next client who waits."""
    with work.tx() as tx:
        return _watch(tx, claims.cancel_watch(tx, caller.user_id, watch_id))


# --- Notifications (R-NT) -----------------------------------------------------------------


class NotificationOut(Out):
    id: int
    # CN-x for a client, PN-x for a pharmacy.
    type: str
    title: str
    # The facts of the event, one per line ("Order number: R-7K3Q2F").
    lines: list[str]
    # Where the website goes on a tap; None: nowhere in particular.
    link: str | None
    read: bool
    created_at: datetime


class NotificationsPage(Out):
    items: list[NotificationOut]
    next_cursor: str | None
    unread: int


class UnreadCount(Out):
    count: int


class MarkRead(In):
    """`ids`, or `all: true` for everything."""

    ids: list[int] = Field(default_factory=list, max_length=200)
    all: bool = False


def _link(row: Notification, role: UserRole) -> str | None:
    """Where a tap on this notification goes. Built from what the event was about (the
    event's own key), never from text."""
    _, _, event = row.dedupe_key.split(":", 2)
    kind, _, rest = event.partition(":")
    thing = rest.split(":", 1)[0]
    if role is UserRole.PHARMACIST:
        if kind == "order":
            return "/pharmacy/reservations"
        return "/pharmacy/inventory" if row.type == "PN-10" else "/pharmacy"
    if row.type in ("CN-9", "CN-10"):  # an offer: its card is on Home
        return "/"
    if row.type == "CN-14":  # the team answered: in the request's thread, or the chat
        request_id = row.payload.get("request_id")
        return f"/requests/{request_id}" if request_id else "/assistant"
    if kind == "order":
        return f"/reservations/{thing}"
    if kind == "request":
        return f"/requests/{thing}"
    if kind == "claim":
        return "/medicines"
    return "/me" if kind == "pause" else None


def _notification(tx: Tx, row: Notification, role: UserRole) -> NotificationOut:
    title, _ = email.render(row.type, row.payload, email.display_rate(tx))
    return NotificationOut(
        id=row.id,
        type=row.type,
        title=title,
        lines=email.facts(row.type, row.payload, email.display_rate(tx)),
        link=_link(row, role),
        read=row.read_at is not None,
        created_at=row.created_at,
    )


def _unread(tx: Tx, user_id: uuid.UUID) -> int:
    return tx.session.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    ).scalar_one()


@router.get("/notifications")
def list_notifications(
    caller: SignedIn,
    work: DoWork,
    cursor: BeforeId = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> NotificationsPage:
    """The caller's own notifications, the newest first. `cursor` is the last ID seen."""
    with work.tx() as tx:
        statement = select(Notification).where(Notification.user_id == caller.user_id)
        if cursor is not None:
            statement = statement.where(Notification.id < cursor)
        rows = (
            tx.session.execute(statement.order_by(Notification.id.desc()).limit(limit + 1))
            .scalars()
            .all()
        )
        shown = rows[:limit]
        return NotificationsPage(
            items=[_notification(tx, row, caller.role) for row in shown],
            next_cursor=str(shown[-1].id) if len(rows) > limit and shown else None,
            unread=_unread(tx, caller.user_id),
        )


@router.get("/notifications/unread-count")
def count_unread(caller: SignedIn, work: DoWork) -> UnreadCount:
    with work.tx() as tx:
        return UnreadCount(count=_unread(tx, caller.user_id))


@router.post("/notifications/read", status_code=204)
def mark_read(body: MarkRead, caller: SignedIn, work: DoWork) -> Response:
    """Marks the caller's own notifications as read. An ID that isn't theirs changes
    nothing: the numbers follow each other, so they must not be a way in."""
    with work.tx() as tx:
        statement = (
            update(Notification)
            .where(Notification.user_id == caller.user_id, Notification.read_at.is_(None))
            .values(read_at=tx.now)
        )
        if not body.all:
            if not body.ids:
                return Response(status_code=204)
            statement = statement.where(Notification.id.in_(body.ids))
        tx.session.execute(statement)
    return Response(status_code=204)
