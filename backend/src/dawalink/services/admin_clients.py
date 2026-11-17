"""The admin's side of a client's account (docs/04 SM-2, R-N3; docs/03 AS-5).

An admin sees a client as a status and a few counts, **never as a person**: the name,
the email and the phone are read through one function only (`contact`), which writes an
audit event each time and stops after 30 views in an hour (N-47).

Suspending a client ends what they had going, in an order that matters:
1. their open requests close as cancelled, and their watches end;
2. then their open reservations and offers are cancelled by the system.
Because the requests are already closed as cancelled when the reservations go, nothing
opens a request again (R-RQ12) and no agent turn is started for someone who is gone.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select

from dawalink.db.models import (
    AuditEvent,
    ClientProfile,
    District,
    Order,
    Pharmacy,
    Product,
    SourcingRequest,
    User,
)
from dawalink.domain.accounts import CLIENT_MACHINE, ClientStatus
from dawalink.domain.numbers import NO_SHOW_WINDOW
from dawalink.domain.orders import OPEN_STATES, OrderState
from dawalink.domain.requests import RequestState
from dawalink.domain.state_machine import Actor, TransitionNotAllowed
from dawalink.services import audit, auth, claims, clients, orders, requests
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

CONTACT_VIEWS_PER_HOUR = 30  # N-47
PII_VIEW = "pii.view"


@dataclass(frozen=True)
class Listed:
    client_id: uuid.UUID
    status: str
    paused_until: datetime | None
    district: str | None
    open_orders: int
    # No-shows that still count (30 days).
    no_shows: int
    open_requests: int
    # Expired reservations the client says they picked up, waiting for an admin's look.
    contested: int


@dataclass(frozen=True)
class Contested:
    order: Order
    product: str
    pharmacy: str


@dataclass(frozen=True)
class Contact:
    full_name: str
    email: str
    phone: str | None


def _counts(tx: Tx, client_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int, int, int]]:
    """Open orders, counted no-shows, open requests and waiting contests, by client."""
    if not client_ids:
        return {}
    open_states = [state.value for state in OPEN_STATES]
    counted = (Order.counts_as_no_show.is_(True)) & (Order.closed_at > tx.now - NO_SHOW_WINDOW)
    by_order = {
        client_id: (int(opened), int(missed), int(contested))
        for client_id, opened, missed, contested in tx.session.execute(
            select(
                Order.client_id,
                func.count().filter(Order.state.in_(open_states)),
                func.count().filter(counted),
                func.count().filter(counted & Order.contested_at.is_not(None)),
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
    return {
        client_id: (
            *by_order.get(client_id, (0, 0, 0))[:2],
            int(by_request.get(client_id, 0)),
            by_order.get(client_id, (0, 0, 0))[2],
        )
        for client_id in client_ids
    }


def _rows(tx: Tx, found: Sequence[tuple[ClientProfile, str | None]]) -> list[Listed]:
    counts = _counts(tx, [profile.user_id for profile, _ in found])
    return [
        Listed(
            client_id=profile.user_id,
            status=profile.status,
            paused_until=profile.paused_until,
            district=district,
            open_orders=counts[profile.user_id][0],
            no_shows=counts[profile.user_id][1],
            open_requests=counts[profile.user_id][2],
            contested=counts[profile.user_id][3],
        )
        for profile, district in found
    ]


def listed(
    tx: Tx,
    *,
    status: ClientStatus | None = None,
    ref: str = "",
    offset: int = 0,
    limit: int = 50,
) -> list[Listed]:
    """Clients, without a name or a contact detail. `ref` finds the client of an order
    number or a request number (`R-7K3Q2F`, `Q-4HX9TM`): what a complaint quotes."""
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
    # Who needs a look comes first: a contest waiting, then the paused and the suspended.
    waiting = (
        select(func.count())
        .select_from(Order)
        .where(
            Order.client_id == ClientProfile.user_id,
            Order.counts_as_no_show.is_(True),
            Order.contested_at.is_not(None),
        )
        .scalar_subquery()
    )
    found = tx.session.execute(
        statement.order_by(waiting.desc(), ClientProfile.status.desc(), ClientProfile.user_id)
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


def contested_orders(tx: Tx, client_id: uuid.UUID) -> list[Contested]:
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
    return [Contested(order, product, pharmacy) for order, product, pharmacy in rows]


def contact(tx: Tx, admin_id: uuid.UUID, client_id: uuid.UUID) -> Contact:
    """The client's name, email and phone, for support (A-D3). **Every view is audited**,
    and an admin gets at most 30 in an hour (N-47): the 31st is refused, and the refusal
    is audited too, so the other admins see it in the log (R-AL).

    The hour is counted on the app's clock, like the audit log it is counted from. In
    demo mode an admin who moves the demo clock moves this hour too; the move is itself
    in the audit log.
    """
    user = tx.session.get(User, client_id)
    if user is None or tx.session.get(ClientProfile, client_id) is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown client.")
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


def suspend(tx: Tx, admin_id: uuid.UUID, client_id: uuid.UUID, *, reason: str) -> Listed:
    """ACTIVE or PAUSED → SUSPENDED (SM-2): every login ends at once, and everything the
    client had going ends with it. See the top of this module for the order."""
    reason = audit.required_reason(reason)
    client = clients.profile(tx, client_id, lock=True)
    before = _move(client, ClientStatus.SUSPENDED)
    client.paused_until, client.status_reason = None, reason
    auth.revoke_sessions(tx, client_id)
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
    ended_requests = requests.end_for_suspension(tx, client_id, admin_id)
    ended_watches = claims.end_watches_for_suspension(tx, client_id)
    cancelled = 0
    for order_id, _ in open_orders:
        done = orders.cancel_by_system(
            tx, order_id, reason="the client was suspended", reopen_need=False
        )
        cancelled += done is not None
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
