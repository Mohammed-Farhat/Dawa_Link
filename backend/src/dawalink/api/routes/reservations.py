"""A client's reservations: the list, the pickup ticket, cancelling (docs/06 §6.3)."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from dawalink.api import present
from dawalink.api.deps import AsClient, DoWork
from dawalink.api.schemas.common import Skip
from dawalink.api.schemas.orders import Reservation, ReservationsPage
from dawalink.db.models import Order
from dawalink.domain.numbers import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from dawalink.domain.orders import OrderState
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import EscalationReason
from dawalink.services import escalations, orders
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

router = APIRouter(tags=["reservations"])

_SHOWN = [state.value for state in present.RESERVATION_STATES]


@router.get("/reservations")
def list_reservations(
    caller: AsClient,
    work: DoWork,
    view: Literal["active", "history"] = "active",
    cursor: Skip = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> ReservationsPage:
    """`active`: what is reserved now, the soonest pickup first. `history`: the rest,
    the newest first."""
    with work.tx() as tx:
        statement = select(Order).where(Order.client_id == caller.user_id)
        if view == "active":
            statement = statement.where(Order.state == OrderState.RESERVED.value).order_by(
                Order.deadline, Order.id
            )
        else:
            statement = statement.where(
                Order.state.in_(_SHOWN), Order.state != OrderState.RESERVED.value
            ).order_by(Order.closed_at.desc(), Order.id)
        rows = tx.session.execute(statement.offset(cursor).limit(limit + 1)).scalars().all()
        more = len(rows) > limit
        return ReservationsPage(
            items=present.reservations(tx, rows[:limit]),
            next_cursor=str(cursor + limit) if more else None,
            server_now=tx.now,
        )


def _own(tx: Tx, client_id: uuid.UUID, reservation_id: uuid.UUID) -> Order:
    """The client's own reservation. Someone else's doesn't exist for them (docs/06 §2.2)."""
    order = tx.session.get(Order, reservation_id)
    if order is None or order.client_id != client_id or order.state not in _SHOWN:
        raise ServiceError(Code.NOT_FOUND, "Unknown reservation.")
    return order


@router.get("/reservations/{reservation_id}")
def read_reservation(reservation_id: uuid.UUID, caller: AsClient, work: DoWork) -> Reservation:
    with work.tx() as tx:
        return present.reservations(tx, [_own(tx, caller.user_id, reservation_id)])[0]


@router.post("/reservations/{reservation_id}/cancel")
def cancel_reservation(reservation_id: uuid.UUID, caller: AsClient, work: DoWork) -> Reservation:
    """The client cancels before the deadline. It is never a penalty (O5, R-N2)."""
    with work.tx() as tx:
        _own(tx, caller.user_id, reservation_id)
        order = orders.cancel_by_client(tx, caller.user_id, reservation_id)
        return present.reservations(tx, [order])[0]


@router.post("/reservations/{reservation_id}/contest")
def contest_no_show(reservation_id: uuid.UUID, caller: AsClient, work: DoWork) -> Reservation:
    """[I picked it up] on an expired reservation: the pharmacy forgot to press
    [Picked up] (R-N3). Once per reservation, while the no-show still counts. A person
    from DawaLink looks at it: nothing changes until they do."""
    with work.tx() as tx:
        order = orders.contest_no_show(tx, caller.user_id, reservation_id)
        escalations.escalate(
            tx,
            client_id=caller.user_id,
            reason=EscalationReason.COMPLAINT,
            # An order number names no person.
            summary=f"The client says they picked up {order.ref}; it expired as a no-show.",
            conversation_id=orders.conversation_of(tx, order),
            actor=Actor.CLIENT,
        )
        return present.reservations(tx, [order])[0]
