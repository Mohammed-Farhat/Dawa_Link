"""The admin's side of a client's account (docs/04 SM-2, R-N3; docs/03 AS-5).

An admin sees a client as a status, a few counts and what they have going (their
reservations and their requests), **never as a person**: the name, the email and the
phone are read through one function only (`contact`), which writes an audit event each
time and stops after 30 views in an hour (N-47). A list of medicines beside an ID names
nobody; beside a name it is someone's health, which is why the name stays behind that
one audited view.

Suspending a client ends what they had going, in an order that matters:
1. their open requests close as cancelled, and their watches end;
2. then their open reservations and offers are cancelled by the system;
3. then the flags about them that nobody handled close, as handled by the suspension.
Because the requests are already closed as cancelled when the reservations go, nothing
opens a request again (R-RQ12) and no agent turn is started for someone who is gone.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ScalarSelect, Select, distinct, func, or_, select
from sqlalchemy.orm import aliased

from dawalink.db.models import (
    AbuseFlag,
    AuditEvent,
    Claim,
    ClientProfile,
    District,
    Order,
    Pharmacy,
    Product,
    RequestItem,
    SourcingRequest,
    User,
)
from dawalink.domain.accounts import CLIENT_MACHINE, ClientStatus
from dawalink.domain.claims import LIVE_STATES
from dawalink.domain.numbers import NO_SHOW_WINDOW
from dawalink.domain.orders import OPEN_STATES, OrderState
from dawalink.domain.requests import ItemState, RequestState
from dawalink.domain.state_machine import Actor, TransitionNotAllowed
from dawalink.domain.vocabulary import ClaimKind, FlagState, FlagSubject
from dawalink.services import audit, auth, claims, clients, orders, requests
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.paging import count_rows

CONTACT_VIEWS_PER_HOUR = 30  # N-47
PII_VIEW = "pii.view"
# How much of a client's history their page shows, newest first.
RESERVATIONS_SHOWN = 30
REQUESTS_SHOWN = 10
# An offer the client let go was never a reservation: it is not in their list.
_NEVER_RESERVED = (
    OrderState.OFFER_DECLINED.value,
    OrderState.OFFER_EXPIRED.value,
    OrderState.OFFER_WITHDRAWN.value,
)
# The lists an admin can ask for: who has something going, and who needs a look.
HAVING = ("reservation", "picked_up", "request", "look")


@dataclass(frozen=True)
class Listed:
    client_id: uuid.UUID
    status: str
    paused_until: datetime | None
    district: str | None
    open_orders: int
    # Everything they ever collected at a counter, as far back as orders are kept.
    picked_up: int
    # Missed pickups that still count (30 days), one per trip (R-N1).
    no_shows: int
    open_requests: int
    # Missed pickups the client says they collected, waiting for an admin's look: one per
    # trip, like `no_shows`.
    contested: int
    # Flags raised about them that nobody has handled yet (R-AB).
    flags_open: int


@dataclass(frozen=True)
class OrderLine:
    """One reservation with the names an admin reads it by."""

    order: Order
    product: str
    pharmacy: str


@dataclass(frozen=True)
class RequestLine:
    request: SourcingRequest
    medicines: int
    # How many of them are fully reserved.
    secured: int


@dataclass(frozen=True)
class Contact:
    full_name: str
    email: str
    phone: str | None


@dataclass(frozen=True)
class _Counts:
    open_orders: int = 0
    picked_up: int = 0
    no_shows: int = 0
    contested: int = 0
    open_requests: int = 0
    flags_open: int = 0


def _counts(tx: Tx, client_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, _Counts]:
    """What each client has going, in numbers."""
    if not client_ids:
        return {}
    open_states = [state.value for state in OPEN_STATES]
    counted = (Order.counts_as_no_show.is_(True)) & (Order.closed_at > tx.now - NO_SHOW_WINDOW)
    # A missed pickup is a trip, not a box (R-N1): the boxes of one plan card missed
    # together are one, as the pause counts them, and one contest covers them all.
    trips = func.count(distinct(orders.TRIP))
    by_order = {
        client_id: (int(opened), int(collected), int(missed), int(contested))
        for client_id, opened, collected, missed, contested in tx.session.execute(
            select(
                Order.client_id,
                func.count().filter(Order.state.in_(open_states)),
                func.count().filter(Order.state == OrderState.PICKED_UP.value),
                trips.filter(counted),
                trips.filter(counted & Order.contested_at.is_not(None)),
            )
            .where(Order.client_id.in_(client_ids))
            .group_by(Order.client_id)
        )
    }
    by_request = dict(
        tx.session.execute(
            select(SourcingRequest.client_id, func.count())
            .where(
                SourcingRequest.client_id.in_(client_ids),
                SourcingRequest.state == RequestState.OPEN.value,
            )
            .group_by(SourcingRequest.client_id)
        ).all()
    )
    by_flag = dict(
        tx.session.execute(
            select(AbuseFlag.subject_id, func.count())
            .where(
                AbuseFlag.subject_type == FlagSubject.CLIENT.value,
                AbuseFlag.subject_id.in_(client_ids),
                AbuseFlag.state == FlagState.OPEN.value,
            )
            .group_by(AbuseFlag.subject_id)
        ).all()
    )
    found = {}
    for client_id in client_ids:
        opened, collected, missed, contested = by_order.get(client_id, (0, 0, 0, 0))
        found[client_id] = _Counts(
            open_orders=opened,
            picked_up=collected,
            no_shows=missed,
            contested=contested,
            open_requests=int(by_request.get(client_id, 0)),
            flags_open=int(by_flag.get(client_id, 0)),
        )
    return found


def _rows(tx: Tx, found: Sequence[tuple[ClientProfile, str | None]]) -> list[Listed]:
    counts = _counts(tx, [profile.user_id for profile, _ in found])
    return [
        Listed(
            client_id=profile.user_id,
            status=profile.status,
            paused_until=profile.paused_until,
            district=district,
            open_orders=counts[profile.user_id].open_orders,
            picked_up=counts[profile.user_id].picked_up,
            no_shows=counts[profile.user_id].no_shows,
            open_requests=counts[profile.user_id].open_requests,
            contested=counts[profile.user_id].contested,
            flags_open=counts[profile.user_id].flags_open,
        )
        for profile, district in found
    ]


def _contests_waiting() -> ScalarSelect[int]:
    """A client's missed pickups they contest, waiting for an admin's look."""
    return (
        select(func.count())
        .select_from(Order)
        .where(
            Order.client_id == ClientProfile.user_id,
            Order.counts_as_no_show.is_(True),
            Order.contested_at.is_not(None),
        )
        .scalar_subquery()
    )


def _flags_open() -> ScalarSelect[int]:
    """The flags about a client that nobody handled yet."""
    return (
        select(func.count())
        .select_from(AbuseFlag)
        .where(
            AbuseFlag.subject_type == FlagSubject.CLIENT.value,
            AbuseFlag.subject_id == ClientProfile.user_id,
            AbuseFlag.state == FlagState.OPEN.value,
        )
        .scalar_subquery()
    )


def _filtered(
    status: ClientStatus | None, having: str | None, ref: str
) -> Select[ClientProfile, str]:
    """The clients an admin's choices keep, with their district: what a page of the list
    reads, and what its total counts."""
    statement = select(ClientProfile, District.name).outerjoin(
        District, District.id == ClientProfile.district_id
    )
    if status is not None:
        statement = statement.where(ClientProfile.status == status.value)
    wanted = ref.strip().upper()
    if wanted:
        statement = statement.where(
            or_(
                ClientProfile.user_id.in_(select(Order.client_id).where(Order.ref == wanted)),
                ClientProfile.user_id.in_(
                    select(SourcingRequest.client_id).where(SourcingRequest.ref == wanted)
                ),
            )
        )
    if having == "reservation":
        statement = statement.where(
            ClientProfile.user_id.in_(
                select(Order.client_id).where(
                    Order.state.in_([state.value for state in OPEN_STATES])
                )
            )
        )
    elif having == "picked_up":
        statement = statement.where(
            ClientProfile.user_id.in_(
                select(Order.client_id).where(Order.state == OrderState.PICKED_UP.value)
            )
        )
    elif having == "request":
        statement = statement.where(
            ClientProfile.user_id.in_(
                select(SourcingRequest.client_id).where(
                    SourcingRequest.state == RequestState.OPEN.value
                )
            )
        )
    elif having == "look":
        # A deleted account needs no look: there is nobody left to answer (R-AU10).
        statement = statement.where(
            (_contests_waiting() > 0) | (_flags_open() > 0),
            ClientProfile.status != ClientStatus.DELETED.value,
        )
    return statement


def listed_total(
    tx: Tx, *, status: ClientStatus | None = None, having: str | None = None, ref: str = ""
) -> int:
    """How many clients the same choices keep, on every page of the list."""
    # Counted by its clients: the same rows, one column (what `count_rows` takes).
    return count_rows(tx, _filtered(status, having, ref).with_only_columns(ClientProfile.user_id))


def listed(
    tx: Tx,
    *,
    status: ClientStatus | None = None,
    having: str | None = None,
    ref: str = "",
    offset: int = 0,
    limit: int = 50,
) -> list[Listed]:
    """Clients, without a name or a contact detail. `ref` finds the client of an order
    number or a request number (`R-7K3Q2F`, `Q-4HX9TM`): what a complaint quotes.
    `having` keeps those with a reservation going, who picked an order up, with an
    open request, or who need a look (a contested no-show, or an open flag)."""
    statement = _filtered(status, having, ref)
    # Who needs a look comes first: a contest waiting, a flag, then the paused and the
    # suspended. Deleted accounts come last, whatever they left behind.
    deleted = ClientProfile.status == ClientStatus.DELETED.value
    found = tx.session.execute(
        statement.order_by(
            deleted,
            _contests_waiting().desc(),
            _flags_open().desc(),
            ClientProfile.status.desc(),
            ClientProfile.user_id,
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return _rows(tx, [(profile, district) for profile, district in found])


def one(tx: Tx, client_id: uuid.UUID) -> Listed:
    found = tx.session.execute(
        select(ClientProfile, District.name)
        .outerjoin(District, District.id == ClientProfile.district_id)
        .where(ClientProfile.user_id == client_id)
    ).one_or_none()
    if found is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown client.")
    return _rows(tx, [(found[0], found[1])])[0]


def reservations(tx: Tx, client_id: uuid.UUID) -> list[OrderLine]:
    """What this client reserved, newest first: waiting to be collected, picked up,
    cancelled, missed. The last 30; an offer they let go is not one of them."""
    rows = tx.session.execute(
        select(Order, Product.moph_name, Pharmacy.name)
        .join(Product, Product.id == Order.product_id)
        .join(Pharmacy, Pharmacy.id == Order.pharmacy_id)
        .where(Order.client_id == client_id, Order.state.not_in(_NEVER_RESERVED))
        .order_by(Order.created_at.desc(), Order.id)
        .limit(RESERVATIONS_SHOWN)
    )
    return [OrderLine(order, product, pharmacy) for order, product, pharmacy in rows]


def requests_of(tx: Tx, client_id: uuid.UUID) -> list[RequestLine]:
    """This client's sourcing requests, the open ones first, then the newest: the last 10."""
    found = (
        tx.session.execute(
            select(SourcingRequest)
            .where(SourcingRequest.client_id == client_id)
            .order_by(
                (SourcingRequest.state == RequestState.OPEN.value).desc(),
                SourcingRequest.created_at.desc(),
                SourcingRequest.id,
            )
            .limit(REQUESTS_SHOWN)
        )
        .scalars()
        .all()
    )
    if not found:
        return []
    items = {
        request_id: (int(medicines), int(secured))
        for request_id, medicines, secured in tx.session.execute(
            select(
                RequestItem.request_id,
                func.count(),
                func.count().filter(RequestItem.state == ItemState.SECURED.value),
            )
            .where(RequestItem.request_id.in_([request.id for request in found]))
            .group_by(RequestItem.request_id)
        )
    }
    return [RequestLine(request, *items.get(request.id, (0, 0))) for request in found]


def contested_orders(tx: Tx, client_id: uuid.UUID) -> list[OrderLine]:
    """The no-shows this client contests and that still count: each waits for [Clear]."""
    rows = tx.session.execute(
        select(Order, Product.moph_name, Pharmacy.name)
        .join(Product, Product.id == Order.product_id)
        .join(Pharmacy, Pharmacy.id == Order.pharmacy_id)
        .where(
            Order.client_id == client_id,
            Order.state == OrderState.EXPIRED_NO_SHOW.value,
            Order.counts_as_no_show.is_(True),
            Order.contested_at.is_not(None),
        )
        .order_by(Order.contested_at)
    )
    return [OrderLine(order, product, pharmacy) for order, product, pharmacy in rows]


def missed_trips_of(
    tx: Tx, client_id: uuid.UUID, order_ids: Sequence[uuid.UUID]
) -> list[OrderLine]:
    """Every missed box of the trips these reservations belong to, cleared or not: what a
    contest is about, and how it ended. The trip is read now, not when the contest was
    made, so a box of the plan card that expired later is in it too (R-N1). A reservation
    deleted after its time is simply not there."""
    if not order_ids:
        return []
    # Its own name for the table, or the subquery would be read as the outer query's row.
    pressed = aliased(Order)
    trips = select(func.coalesce(pressed.group_id, pressed.id)).where(
        pressed.id.in_(order_ids), pressed.client_id == client_id
    )
    rows = tx.session.execute(
        select(Order, Product.moph_name, Pharmacy.name)
        .join(Product, Product.id == Order.product_id)
        .join(Pharmacy, Pharmacy.id == Order.pharmacy_id)
        .where(
            Order.client_id == client_id,
            Order.state == OrderState.EXPIRED_NO_SHOW.value,
            orders.TRIP.in_(trips),
        )
        .order_by(Order.closed_at, Order.id)
    )
    return [OrderLine(order, product, pharmacy) for order, product, pharmacy in rows]


def contested_by_number(tx: Tx, client_id: uuid.UUID, refs: Sequence[str]) -> list[OrderLine]:
    """The contested missed pickups of this client with these order numbers, and their
    trips, cleared or not: what an older complaint quotes."""
    if not refs:
        return []
    named = (
        tx.session.execute(
            select(Order.id).where(
                Order.client_id == client_id,
                Order.ref.in_(refs),
                Order.contested_at.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    return missed_trips_of(tx, client_id, named)


def contact(tx: Tx, admin_id: uuid.UUID, client_id: uuid.UUID) -> Contact:
    """The client's name, email and phone, for support (A-D3). **Every view is audited**,
    and an admin gets at most 30 in an hour (N-47): the 31st is refused, and the refusal
    is audited too, so the other admins see it in the log (R-AL).

    The hour is counted on the app's clock, like the audit log it is counted from. In
    demo mode an admin who moves the demo clock moves this hour too; the move is itself
    in the audit log.
    """
    user = tx.session.get(User, client_id)
    profile = tx.session.get(ClientProfile, client_id)
    if user is None or profile is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown client.")
    if profile.status == ClientStatus.DELETED.value:
        # Nothing is kept to show (R-AU10), so nothing is viewed: not counted, not audited.
        raise ServiceError(
            Code.NOT_FOUND,
            "This client deleted their account: no name, email or phone is kept.",
            reason="ACCOUNT_DELETED",
        )
    seen = tx.session.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.action == PII_VIEW,
            AuditEvent.actor_id == admin_id,
            AuditEvent.occurred_at > tx.now - timedelta(hours=1),
        )
    ).scalar_one()
    if seen >= CONTACT_VIEWS_PER_HOUR:
        raise ServiceError(
            Code.RATE_LIMITED, "Too many contact details viewed in an hour.", limit="pii_view"
        )
    audit.record(tx, Actor.ADMIN, PII_VIEW, "client", client_id, actor_id=admin_id)
    return Contact(full_name=user.full_name, email=user.email, phone=user.phone)


def note_contact_limit(tx: Tx, admin_id: uuid.UUID) -> None:
    """Written in a transaction of its own after `contact` refused: the refusal itself
    rolled its own transaction back."""
    audit.record(
        tx, Actor.ADMIN, "pii.view_limit", "user", admin_id, actor_id=admin_id, after={"limit": 30}
    )


def _move(client: ClientProfile, target: ClientStatus) -> ClientStatus:
    before = ClientStatus(client.status)
    try:
        CLIENT_MACHINE.check(before, target, Actor.ADMIN)
    except TransitionNotAllowed:
        raise ServiceError(
            Code.CHANGED_SINCE, "This client's status changed: look at it again."
        ) from None
    client.status = target.value
    return before


def lift_pause(tx: Tx, admin_id: uuid.UUID, client_id: uuid.UUID, *, reason: str) -> Listed:
    """PAUSED → ACTIVE before the pause runs out (SM-2)."""
    reason = audit.required_reason(reason)
    client = clients.profile(tx, client_id, lock=True)
    paused_until = client.paused_until
    before = _move(client, ClientStatus.ACTIVE)
    if before is not ClientStatus.PAUSED:
        raise ServiceError(Code.CHANGED_SINCE, "This client is not paused.")
    client.paused_until = None
    audit.record(
        tx,
        Actor.ADMIN,
        "client.pause_lifted",
        "client",
        client_id,
        actor_id=admin_id,
        before={"status": before.value, "paused_until": str(paused_until)},
        after={"status": client.status},
        reason=reason,
    )
    return one(tx, client_id)


@dataclass(frozen=True)
class Ended:
    """What ended with a client's account: counts, for the audit event."""

    requests_closed: int
    watches_ended: int
    orders_cancelled: int


def end_what_they_have(
    tx: Tx, client_id: uuid.UUID, *, admin_id: uuid.UUID | None, reason: str
) -> Ended:
    """Everything the client has going ends, **in the order that matters** (see the top of
    this module): their open requests close and their watches end first, then their open
    reservations and offers go. The other order would open a request again (R-RQ12) and
    start an agent turn for someone who is gone. The caller holds the client's lock.

    With `admin_id`, an admin suspended them: each thing ends by the admin or the system.
    Without, the client is deleting their own account (R-AU10): each thing ends as if the
    client had pressed its own button, with the client's own end states (the pharmacy is
    told of a cancelled reservation as for any cancel), and no missed pickup is counted.
    """
    open_orders = list(
        tx.session.execute(
            select(Order.id, Order.inventory_item_id).where(
                Order.client_id == client_id,
                Order.state.in_([state.value for state in OPEN_STATES]),
            )
        ).all()
    )
    # Boxes before orders, orders before request rows (docs/05 §6).
    orders.lock_items(tx, [item_id for _, item_id in open_orders])
    if admin_id is not None:
        ended_requests = requests.end_for_suspension(tx, client_id, admin_id)
        ended_watches = claims.end_watches_for_suspension(tx, client_id)
    else:
        ended_requests = _cancel_each(
            tx, client_id, _open_requests(tx, client_id), requests.cancel_request
        )
        ended_watches = _cancel_each(
            tx, client_id, _live_watches(tx, client_id), claims.cancel_watch
        )
    cancelled = 0
    for order_id, _ in open_orders:
        if admin_id is not None:
            done = orders.cancel_by_system(tx, order_id, reason=reason, reopen_need=False)
        else:
            done = _let_go(tx, client_id, order_id)
        cancelled += done is not None
    return Ended(ended_requests, ended_watches, cancelled)


def _open_requests(tx: Tx, client_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        tx.session.execute(
            select(SourcingRequest.id)
            .where(
                SourcingRequest.client_id == client_id,
                SourcingRequest.state == RequestState.OPEN.value,
            )
            .order_by(SourcingRequest.created_at, SourcingRequest.id)
        ).scalars()
    )


def _live_watches(tx: Tx, client_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        tx.session.execute(
            select(Claim.id)
            .where(
                Claim.client_id == client_id,
                Claim.kind == ClaimKind.WATCH.value,
                Claim.state.in_([state.value for state in LIVE_STATES]),
            )
            .order_by(Claim.created_at, Claim.id)
        ).scalars()
    )


def _cancel_each(
    tx: Tx,
    client_id: uuid.UUID,
    ids: Sequence[uuid.UUID],
    cancel: Callable[[Tx, uuid.UUID, uuid.UUID], object],
) -> int:
    for found in ids:
        cancel(tx, client_id, found)
    return len(ids)


def _let_go(tx: Tx, client_id: uuid.UUID, order_id: uuid.UUID) -> Order | None:
    """One open order of a client who is leaving, ended as they would end it themselves:
    a reservation cancelled, an offer declined. None if it had already ended (an offer
    goes with the watch or the request it was made for)."""
    order = tx.session.get(Order, order_id)
    if order is None:
        return None
    tx.session.refresh(order)
    if order.state == OrderState.OFFERED.value:
        return orders.end_offer(tx, order_id, declined_by=client_id)
    if order.state != OrderState.RESERVED.value:
        return None
    if order.deadline is not None and tx.now < order.deadline:
        return orders.cancel_by_client(tx, client_id, order_id)
    # Its deadline passed a moment ago and the clock check has not yet called it a missed
    # pickup: the client can no longer cancel it, and it must not count against anyone.
    # The system ends it, and nothing is searched for again.
    return orders.cancel_by_system(
        tx, order_id, reason="the client deleted their account", reopen_need=False
    )


def suspend(tx: Tx, admin_id: uuid.UUID, client_id: uuid.UUID, *, reason: str) -> Listed:
    """ACTIVE or PAUSED → SUSPENDED (SM-2): every login ends at once, and everything the
    client had going ends with it. See the top of this module for the order."""
    reason = audit.required_reason(reason)
    client = clients.profile(tx, client_id, lock=True)
    before = _move(client, ClientStatus.SUSPENDED)
    client.paused_until, client.status_reason = None, reason
    auth.revoke_sessions(tx, client_id)
    ended = end_what_they_have(tx, client_id, admin_id=admin_id, reason="the client was suspended")
    ended_requests, ended_watches, cancelled = (
        ended.requests_closed,
        ended.watches_ended,
        ended.orders_cancelled,
    )
    # Imported here: the flags' own service suspends clients through this function.
    from dawalink.services import abuse_flags

    # A suspended client needs no more looks: their open flags close with the suspension.
    flags_closed = abuse_flags.close_for_suspended_client(tx, admin_id, client_id, reason=reason)
    audit.record(
        tx,
        Actor.ADMIN,
        "client.suspend",
        "client",
        client_id,
        actor_id=admin_id,
        before={"status": before.value},
        after={
            "status": client.status,
            "orders_cancelled": cancelled,
            "requests_closed": ended_requests,
            "watches_ended": ended_watches,
            "flags_closed": flags_closed,
        },
        reason=reason,
    )
    return one(tx, client_id)


def reinstate(tx: Tx, admin_id: uuid.UUID, client_id: uuid.UUID, *, reason: str) -> Listed:
    """SUSPENDED → ACTIVE (SM-2). Nothing that was cancelled comes back."""
    reason = audit.required_reason(reason)
    client = clients.profile(tx, client_id, lock=True)
    before = _move(client, ClientStatus.ACTIVE)
    if before is not ClientStatus.SUSPENDED:
        raise ServiceError(Code.CHANGED_SINCE, "This client is not suspended.")
    client.status_reason = None
    audit.record(
        tx,
        Actor.ADMIN,
        "client.reinstate",
        "client",
        client_id,
        actor_id=admin_id,
        before={"status": before.value},
        after={"status": client.status},
        reason=reason,
    )
    return one(tx, client_id)
