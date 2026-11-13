"""A medicine that became controlled after a catalog import (docs/04 R-C6; docs/09 FR-24).

Listings are already hidden: visibility reads the product's flag. What is left is what
was open for that medicine: orders are cancelled by the system, waiting claims end, and
request items become unavailable. Each row is handled in its own transaction, like the
clock check, so no transaction holds many clients' rows at once.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from dawalink.db.models import Claim, Order, Product, RequestItem, SourcingRequest
from dawalink.domain.claims import LIVE_STATES, ClaimState
from dawalink.domain.clock import Clock
from dawalink.domain.requests import FINAL_ITEM_STATES, ItemState
from dawalink.domain.state_machine import Actor
from dawalink.services import needs, orders
from dawalink.services.context import Tx, unit_of_work
from dawalink.services.notify import Template, notify

REASON = "the medicine is now controlled"


@dataclass(frozen=True)
class Withdrawn:
    orders: int
    claims: int
    items: int


def cancel_order(tx: Tx, order_id: uuid.UUID) -> bool:
    cancelled = orders.cancel_by_system(tx, order_id, reason=REASON, reopen_need=False)
    return cancelled is not None


def end_claim(tx: Tx, claim_id: uuid.UUID) -> bool:
    claim = needs.lock_claim(tx, claim_id)
    if ClaimState(claim.state) not in LIVE_STATES:
        return False
    needs.withdraw_asks(tx, claim, fulfilled=False)
    if claim.state == ClaimState.OFFER_PENDING.value:
        needs.move_claim(tx, claim, ClaimState.ACTIVE, Actor.SYSTEM)
    needs.move_claim(tx, claim, ClaimState.EXPIRED, Actor.SYSTEM)
    if claim.kind == "WATCH":
        product = tx.session.get_one(Product, claim.product_id)
        notify(
            tx,
            claim.client_id,
            Template.WATCH_ENDED,
            {"product": product.moph_name, "reason": "no_longer_available"},
            event=f"claim:{claim.id}",
        )
    return True


def end_item(tx: Tx, item_id: uuid.UUID) -> bool:
    item = tx.session.execute(
        select(RequestItem)
        .where(RequestItem.id == item_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if ItemState(item.state) in FINAL_ITEM_STATES:
        return False
    needs.move_item(tx, item, ItemState.UNAVAILABLE, Actor.SYSTEM)
    return True


def withdraw_everything(sessions: sessionmaker[Session], clock: Clock) -> Withdrawn:
    """Ends what is open for every controlled medicine. Safe to run again."""
    controlled = select(Product.id).where(Product.controlled.is_(True))
    with sessions() as session:
        order_ids = session.execute(
            select(Order.id).where(Order.product_id.in_(controlled), Order.state.in_(orders.OPEN))
        ).scalars()
        claim_ids = session.execute(
            select(Claim.id).where(
                Claim.product_id.in_(controlled),
                Claim.state.in_([state.value for state in LIVE_STATES]),
            )
        ).scalars()
        item_ids = session.execute(
            select(RequestItem.id)
            .join(SourcingRequest, SourcingRequest.id == RequestItem.request_id)
            .where(RequestItem.product_id.in_(controlled), SourcingRequest.state == "OPEN")
        ).scalars()
        work = (
            (cancel_order, list(order_ids)),
            (end_claim, list(claim_ids)),
            (end_item, list(item_ids)),
        )
    done = []
    for action, ids in work:
        count = 0
        for row_id in ids:
            with unit_of_work(sessions, clock) as tx:
                count += action(tx, row_id)
        done.append(count)
    return Withdrawn(*done)
