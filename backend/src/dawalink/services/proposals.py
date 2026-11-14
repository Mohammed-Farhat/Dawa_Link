"""Proposals: the agent's cards, and what a tap on one does (docs/04 R-AG7, docs/06 §6.7).

A card exists only as a stored row created by a tool. The model chooses which rows to
show; it can't write what is on them. A tap sends the row's ID and nothing else, and
everything is checked again as if the action were new: what a client sees on a card is
exactly what its button does (INV-21).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select

from dawalink.db.models import Conversation, Order, Proposal, SourcingRequest
from dawalink.domain.numbers import PROPOSAL_VALIDITY
from dawalink.domain.orders import OrderSource
from dawalink.domain.vocabulary import ProposalKind
from dawalink.services import events, orders, requests, travel
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.events import Decision
from dawalink.services.orders import ReserveLine
from dawalink.services.requests import RequestLine


@dataclass(frozen=True)
class CardText:
    """What a card shows. Written by code when the card is created, and stored with it."""

    title: str
    lines: Sequence[tuple[str, str]]  # (label, value)
    prescription_notice: bool = False
    recommended: bool = False

    def stored(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "lines": [list(line) for line in self.lines],
            "prescription_notice": self.prescription_notice,
            "recommended": self.recommended,
        }


@dataclass(frozen=True)
class Executed:
    """What a tap did."""

    kind: ProposalKind
    orders: list[Order] = field(default_factory=list)
    request: SourcingRequest | None = None


def create(
    tx: Tx,
    *,
    conversation_id: uuid.UUID,
    client_id: uuid.UUID,
    kind: ProposalKind,
    payload: dict[str, Any],
    card: CardText,
    run_id: uuid.UUID | None,
) -> Proposal:
    """Stores a card. Only tools call this; the model never supplies a card's content."""
    proposal = Proposal(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        client_id=client_id,
        kind=kind.value,
        payload={**payload, "card": card.stored()},
        agent_run_id=run_id,
        expires_at=tx.now + PROPOSAL_VALIDITY,
        created_at=tx.now,
    )
    tx.session.add(proposal)
    tx.session.flush()
    return proposal


def state_of(tx: Tx, proposal: Proposal) -> str:
    if proposal.used_at is not None:
        return "used"
    return "expired" if proposal.expires_at <= tx.now else "open"


def of_conversation(
    tx: Tx, conversation_id: uuid.UUID, proposal_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Proposal]:
    """These cards, if they belong to this conversation. A foreign or invented ID is absent."""
    if not proposal_ids:
        return {}
    rows = tx.session.execute(
        select(Proposal).where(
            Proposal.id.in_(proposal_ids), Proposal.conversation_id == conversation_id
        )
    ).scalars()
    return {proposal.id: proposal for proposal in rows}


def _own_open(tx: Tx, client_id: uuid.UUID, proposal_id: uuid.UUID) -> Proposal:
    proposal = tx.session.execute(
        select(Proposal)
        .where(Proposal.id == proposal_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    if proposal is None or proposal.client_id != client_id:
        raise ServiceError(Code.NOT_FOUND, "Unknown card.")
    if proposal.used_at is not None:
        raise ServiceError(Code.PROPOSAL_USED, "This card's button was already used.")
    if proposal.expires_at <= tx.now:
        raise ServiceError(
            Code.PROPOSAL_EXPIRED, "This option has expired; ask the assistant for fresh options."
        )
    return proposal


def _order_source(tx: Tx, proposal: Proposal) -> OrderSource:
    conversation = tx.session.get_one(Conversation, proposal.conversation_id)
    return OrderSource.REQUEST if conversation.kind == "request" else OrderSource.ASSISTANT


def _lines(items: Sequence[dict[str, Any]]) -> list[ReserveLine]:
    return [
        ReserveLine(
            item_id=uuid.UUID(item["listing_id"]),
            qty=int(item["qty"]),
            expected_price_lbp=int(item["price_lbp_shown"]),
            days_of_use=int(item["days_of_use"]),
            request_item_id=(
                uuid.UUID(item["request_item_id"]) if item.get("request_item_id") else None
            ),
        )
        for item in items
    ]


def execute(
    tx: Tx,
    *,
    client_id: uuid.UUID,
    proposal_id: uuid.UUID,
    selected_item_keys: Sequence[str] | None = None,
) -> Executed:
    """The client tapped an agent card. The action is checked again as if it were new.

    If it is refused, nothing changed and the card stays usable (the transaction is rolled
    back by the caller). A card works once.
    """
    proposal = _own_open(tx, client_id, proposal_id)
    kind = ProposalKind(proposal.kind)
    payload = proposal.payload
    key = f"proposal:{proposal.id}"
    done = Executed(kind)

    if kind is ProposalKind.RESERVE:
        done = Executed(
            kind,
            orders=orders.reserve(
                tx,
                client_id=client_id,
                lines=_lines([payload]),
                pickup_day=date.fromisoformat(payload["pickup_day"]),
                source=_order_source(tx, proposal),
                idempotency_key=key,
            ),
        )
    elif kind is ProposalKind.RESERVE_GROUP:
        done = _reserve_group(tx, client_id, proposal, selected_item_keys, key)
    elif kind is ProposalKind.CANCEL:
        done = Executed(
            kind, orders=[orders.cancel_by_client(tx, client_id, uuid.UUID(payload["order_id"]))]
        )
    elif kind is ProposalKind.REQUEST_SUMMARY:
        done = Executed(kind, request=_start_request(tx, client_id, proposal, key))
    elif kind is ProposalKind.CONSTRAINT_CHANGE:
        prices = payload.get("item_max_prices")
        done = Executed(
            kind,
            request=requests.change_constraints(
                tx,
                client_id,
                uuid.UUID(payload["request_id"]),
                alternatives_ok=payload.get("alternatives_ok"),
                max_prices=(
                    {uuid.UUID(item): price for item, price in prices.items()} if prices else None
                ),
            ),
        )
    elif kind is ProposalKind.REMOVE_ITEM:
        requests.remove_item(tx, client_id, uuid.UUID(payload["request_item_id"]))
    else:
        # No tool creates an "accept offer" card: offers are system cards with their own
        # button (docs/06 §5.5). The kind stays in the vocabulary for a later version.
        raise ServiceError(Code.NOT_FOUND, "Unknown card.")
    proposal.used_at = tx.now
    return done


def _reserve_group(
    tx: Tx,
    client_id: uuid.UUID,
    proposal: Proposal,
    selected_item_keys: Sequence[str] | None,
    key: str,
) -> Executed:
    """[Reserve these]: the ticked items of one pharmacy's card, all or none (R-RQ6)."""
    items: list[dict[str, Any]] = proposal.payload["items"]
    known = {item["item_key"] for item in items}
    ticked = set(known if selected_item_keys is None else selected_item_keys)
    if not ticked or not ticked <= known:
        raise ServiceError(Code.SELECTION_INVALID, "Choose at least one of the items on this card.")
    chosen = [item for item in items if item["item_key"] in ticked]
    made = orders.reserve(
        tx,
        client_id=client_id,
        lines=_lines(chosen),
        pickup_day=date.fromisoformat(proposal.payload["pickup_day"]),
        source=_order_source(tx, proposal),
        idempotency_key=key,
    )
    left = [item for item in items if item["item_key"] not in ticked]
    if left:
        _tell_the_agent(
            tx,
            proposal,
            Decision.ITEMS_UNTICKED,
            [item["request_item_id"] for item in left if item.get("request_item_id")],
            items=[item["item_key"] for item in left],
        )
    return Executed(ProposalKind.RESERVE_GROUP, orders=made)


def _tell_the_agent(
    tx: Tx,
    proposal: Proposal,
    decision: Decision,
    request_item_ids: Sequence[str],
    **facts: Any,
) -> None:
    """Unticked or failed items go back to the agent, in the card's own conversation."""
    conversation = tx.session.get_one(Conversation, proposal.conversation_id)
    if conversation.kind == "request" and conversation.request_id is not None:
        if decision is Decision.ITEMS_UNTICKED:
            requests.items_unticked(
                tx,
                proposal.client_id,
                conversation.request_id,
                [uuid.UUID(item) for item in request_item_ids],
            )
        else:
            requests.group_item_failed(
                tx, proposal.client_id, conversation.request_id, facts["failed_items"]
            )
        return
    events.post_decision(tx, conversation.id, decision, proposal_id=proposal.id, **facts)


def report_failed_group(
    tx: Tx, *, client_id: uuid.UUID, proposal_id: uuid.UUID, error: ServiceError
) -> None:
    """A plan card couldn't be reserved. Run this in a new transaction after the refusal.

    Nothing was reserved. The agent gets a turn: it says which item failed, offers the
    rest again and keeps looking for the failed one (R-RQ6, docs/09 FA-22).
    """
    if error.code is not Code.GROUP_ITEM_FAILED:
        return
    proposal = tx.session.get(Proposal, proposal_id)
    if proposal is None or proposal.client_id != client_id:
        return
    failed = [
        {
            "request_item_id": item.get("request_item_id"),
            "listing_id": str(item.get("item_id")),
            "code": item.get("code"),
        }
        for item in error.details.get("failed_items", [])
    ]
    _tell_the_agent(tx, proposal, Decision.GROUP_ITEM_FAILED, [], failed_items=failed)


def _start_request(tx: Tx, client_id: uuid.UUID, proposal: Proposal, key: str) -> SourcingRequest:
    """[Start sourcing] on the agent's summary card (R-RQ1)."""
    payload = proposal.payload
    conversation = tx.session.get_one(Conversation, proposal.conversation_id)
    if conversation.loc_lat is not None and conversation.loc_lon is not None:
        location = travel.shared_location(str(conversation.loc_lat), str(conversation.loc_lon))
    elif payload.get("district_id") is not None:
        location = travel.district_location(tx, int(payload["district_id"]))
    else:
        raise ServiceError(Code.VALIDATION_ERROR, "Share your location or choose a district first.")
    return requests.create_request(
        tx,
        client_id=client_id,
        lines=[
            RequestLine(
                product_id=uuid.UUID(item["product_id"]),
                qty=int(item["qty"]),
                days_of_use=int(item["days_of_use"]),
                max_price_lbp=item.get("max_price_lbp"),
            )
            for item in payload["items"]
        ],
        location=location,
        alternatives_ok=bool(payload["alternatives_ok"]),
        idempotency_key=key,
    )
