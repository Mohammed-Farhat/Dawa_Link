"""What a turn is given to read (docs/07 §3.1 `load_context`, §6).

Nothing comes from the model's own memory: every turn loads the case state, the last
messages, the client's facts and the clock fresh from our tables, and writes them into
one block of text.

Everything in that block is chosen here, field by field. A system card or an event is
never copied as stored: only the listed facts of each kind are written, so an address, a
coordinate or a client's details can't slip in through a new field (INV-10, INV-23, INV-24).
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from dawalink.agent import display, state
from dawalink.agent.guards.redact import Identity, redact
from dawalink.agent.state import CaseState
from dawalink.agent.tools.base import rate
from dawalink.agent.tools.read import request_status
from dawalink.db.models import (
    Area,
    ChatMessage,
    Claim,
    ClientProfile,
    Conversation,
    District,
    EarlyReleaseRequest,
    Order,
    Pharmacy,
    Product,
    Proposal,
    SourcingRequest,
    User,
)
from dawalink.domain.claims import LIVE_STATES
from dawalink.domain.clock import beirut
from dawalink.domain.numbers import (
    MAX_OPEN_EARLY_RELEASE_REQUESTS,
    MAX_OPEN_ORDERS,
    MAX_OPEN_REQUESTS,
    MAX_WATCHES,
    REQUEST_HOURS_END,
    REQUEST_HOURS_START,
)
from dawalink.domain.pickup import upcoming_days
from dawalink.domain.vocabulary import AgentMode, TurnTrigger
from dawalink.domain.windows import in_request_hours
from dawalink.services import conversations, proposals
from dawalink.services.context import Tx
from dawalink.services.events import Decision

# The facts of a system card the model may read, by card template.
_CARD_FACTS = {
    "reserved": ("order_ref", "product", "pharmacy", "units", "price_lbp", "pickup_by"),
    "picked_up": ("order_ref",),
    "not_available": ("order_ref", "units"),
    "cancelled": ("order_ref",),
    "cancelled_by_system": ("order_ref",),
    "expired": ("order_ref",),
    "offer": ("order_ref", "product", "pharmacy", "units", "price_lbp"),
    "offer_ended": ("state",),
    "request_closed": ("request_ref", "outcome"),
}


@dataclass(frozen=True)
class Loaded:
    """Everything a turn needs, read in one short transaction."""

    conversation_id: uuid.UUID
    client_id: uuid.UUID
    mode: AgentMode
    request_id: uuid.UUID | None
    trigger: TurnTrigger
    case_state: CaseState
    identity: Identity
    # The newest message this turn has read: an event that arrives later isn't lost.
    last_seq: int
    # What the client last wrote in this turn's input, if anything: for the language check.
    client_text: str | None
    # The text block the model reads.
    block: str


def identity_of(tx: Tx, client_id: uuid.UUID) -> Identity:
    """The account's own personal details: read by code, to remove them from text."""
    user = tx.session.get_one(User, client_id)
    return Identity(full_name=user.full_name, email=user.email, phone=user.phone)


def _order_facts(tx: Tx, order_id: Any) -> str:
    found = tx.session.execute(
        select(Order.ref, Product.moph_name, Pharmacy.name, Order.qty_requested)
        .join(Product, Product.id == Order.product_id)
        .join(Pharmacy, Pharmacy.id == Order.pharmacy_id)
        .where(Order.id == uuid.UUID(str(order_id)))
    ).one_or_none()
    if found is None:
        return "an order"
    ref, product, pharmacy, units = found
    return f"order {ref} ({product} x {units} at {pharmacy})"


def _event_line(tx: Tx, body: dict[str, Any]) -> str:
    """One decision event, as a sentence of facts (docs/06 §8)."""
    kind = body.get("type")
    if kind == Decision.NOT_AVAILABLE and body.get("order_id"):
        return (
            f"not_available: the pharmacy marked {_order_facts(tx, body['order_id'])} "
            f"not available for {body.get('units', '?')} unit(s)"
        )
    if kind == Decision.SYSTEM_CANCELLED and body.get("order_id"):
        return f"system_cancelled: DawaLink cancelled {_order_facts(tx, body['order_id'])}"
    if kind == Decision.EARLY_RELEASE_UNFULFILLED and body.get("claim_id"):
        product = tx.session.execute(
            select(Product.moph_name)
            .join(Claim, Claim.product_id == Product.id)
            .where(Claim.id == uuid.UUID(str(body["claim_id"])))
        ).scalar()
        return (
            "early_release_unfulfilled: no pharmacy released stock for "
            f"{product or 'a medicine'} (claim_id {body['claim_id']})"
        )
    if kind == Decision.GROUP_ITEM_FAILED:
        failed = [
            f"{item.get('request_item_id') or item.get('listing_id')}: {item.get('code')}"
            for item in body.get("failed_items", [])
        ]
        return "group_item_failed: a plan card couldn't be reserved, nothing was. " + "; ".join(
            failed
        )
    if kind == Decision.ITEMS_UNTICKED:
        return "items_unticked: the client left these items unticked: " + ", ".join(
            str(item) for item in body.get("items", [])
        )
    if kind == Decision.WINDOW_CHECK:
        return "window_check: one hour is left, and these items aren't secured: " + ", ".join(
            str(item) for item in body.get("items", [])
        )
    if kind == Decision.REQUEST_SUBMITTED:
        return "request_submitted: the client started this request"
    return f"{kind}: something changed"


def _card_line(tx: Tx, card: dict[str, Any], money: Any) -> str:
    template = str(card.get("template"))
    facts = []
    for name in _CARD_FACTS.get(template, ()):
        value = card.get(name)
        if value is None:
            continue
        if name == "price_lbp":
            value = display.money(int(value), money)
        elif name == "pickup_by":
            value = display.when(datetime.fromisoformat(str(value)))
        facts.append(f"{name.removesuffix('_lbp')} {value}")
    return f"{template}" + (": " + ", ".join(facts) if facts else "")


def _agent_cards(tx: Tx, known: dict[uuid.UUID, Proposal], cards: Sequence[Any]) -> str:
    """The cards an agent message showed, with whether each can still be tapped."""
    shown = []
    for card in cards:
        try:
            proposal = known.get(uuid.UUID(str(card)))
        except ValueError:
            continue
        if proposal is not None:
            title = proposal.payload.get("card", {}).get("title", proposal.kind)
            shown.append(f'{proposal.id} "{title}" [{proposals.state_of(tx, proposal)}]')
    return " (cards: " + "; ".join(shown) + ")" if shown else ""


def _transcript(
    tx: Tx, conversation_id: uuid.UUID, messages: Sequence[ChatMessage], money: Any
) -> list[str]:
    ids = []
    for message in messages:
        if message.author == "agent" and message.cards:
            for card in message.cards:
                try:
                    ids.append(uuid.UUID(str(card)))
                except ValueError:
                    continue
    known = proposals.of_conversation(tx, conversation_id, ids)
    lines = []
    for message in messages:
        head = f"[{message.seq}]"
        if message.kind == "event":
            try:
                body = json.loads(message.text_redacted or "{}")
            except ValueError:
                body = {}
            lines.append(f"{head} event: {_event_line(tx, body)}")
        elif message.author == "system":
            for card in message.cards or []:
                if isinstance(card, dict):
                    lines.append(f"{head} system card: {_card_line(tx, card, money)}")
        elif message.author == "agent":
            cards = _agent_cards(tx, known, message.cards or [])
            lines.append(f"{head} you: {message.text_redacted or ''}{cards}")
        elif message.author == "admin":
            # Typed by a person from DawaLink: patterns are removed again before the model.
            lines.append(f"{head} DawaLink team: {redact(message.text_redacted or '').text}")
        else:
            lines.append(f"{head} client: {message.text_redacted or ''}")
    return lines


def _trigger(
    messages: Sequence[ChatMessage], followup: bool, read_up_to: int
) -> tuple[TurnTrigger | None, str | None]:
    """Why this turn runs, from what arrived since the last turn read the conversation.

    None: nothing arrived and no follow-up is due, so there is nothing to answer.
    """
    # Newest first: everything after the last message the previous turn read.
    fresh = [
        message
        for message in reversed(messages)
        if message.seq > read_up_to and message.author != "agent"
    ]
    events = []
    for message in fresh:
        if message.kind == "event":
            try:
                events.append(json.loads(message.text_redacted or "{}").get("type"))
            except ValueError:
                continue
    client_texts = [m.text_redacted for m in fresh if m.author == "client" and m.text_redacted]
    client_text = client_texts[0] if client_texts else None  # `fresh` is newest first
    if Decision.REQUEST_SUBMITTED in events:
        return TurnTrigger.REQUEST_SUBMITTED, client_text
    if client_text:
        return TurnTrigger.CLIENT_MESSAGE, client_text
    if Decision.WINDOW_CHECK in events:
        return TurnTrigger.WINDOW_CHECK, None
    if events:
        return TurnTrigger.DECISION_EVENT, None
    return (TurnTrigger.FOLLOWUP if followup else None), None


_WHAT_NOW = {
    TurnTrigger.CLIENT_MESSAGE: "The client wrote the last message. Answer it.",
    TurnTrigger.REQUEST_SUBMITTED: (
        "The client just started this request. Plan what is listed, start waiting for what "
        "isn't, ask pharmacies where it helps, and report medicine by medicine."
    ),
    TurnTrigger.DECISION_EVENT: (
        "Something changed (see the newest events). Re-plan only what changed and tell the client."
    ),
    TurnTrigger.WINDOW_CHECK: (
        "One hour is left in this request's window and some medicines aren't secured. Propose "
        "relaxing a constraint if that could help, or prepare the client for what is missing."
    ),
    TurnTrigger.FOLLOWUP: (
        "This is the follow-up you scheduled. Do what waiting has made possible, or say "
        "nothing new happened only if the client needs to know."
    ),
}


def _location_line(tx: Tx, conversation: Conversation, *, has_home_area: bool) -> str:
    """What the model is told about where the client is: a name at most, never a point."""
    if conversation.loc_area_id is not None:
        name, district, whole = tx.session.execute(
            select(Area.name, District.name, Area.whole_district)
            .join(District, District.id == Area.district_id)
            .where(Area.id == conversation.loc_area_id)
        ).one()
        if whole:
            return (
                f"Location: the district the client named, {name}. Travel times are counted "
                "from its main town: a rough start. "
            )
        return (
            f"Location: the area the client named, {name} ({district}). Travel times are "
            "counted from its centre. "
        )
    if conversation.loc_lat is not None:
        return "Location: shared for this conversation. "
    if has_home_area:
        return ""
    return "Location: not known yet. "


def load(tx: Tx, conversation_id: uuid.UUID, *, followup: bool = False) -> Loaded | None:
    """Everything a turn reads. None when there is nothing for a turn to answer."""
    conversation = tx.session.get_one(Conversation, conversation_id)
    client_id = conversation.client_id
    mode = AgentMode.SOURCING if conversation.kind == "request" else AgentMode.ASSISTANT
    messages = conversations.history(tx, conversation_id)
    case = state.tidy(state.load(conversation.case_state), tx.today)
    trigger, client_text = _trigger(messages, followup, case.read_up_to)
    if trigger is None:
        return None
    still_open = proposals.of_conversation(tx, conversation_id, case.open_proposal_ids)
    case.open_proposal_ids = [
        proposal_id
        for proposal_id in case.open_proposal_ids
        if proposal_id in still_open and proposals.state_of(tx, still_open[proposal_id]) == "open"
    ]
    money = rate(tx)

    profile = tx.session.get_one(ClientProfile, client_id)
    area = None
    if profile.district_id is not None:
        area = tx.session.execute(
            select(District.name).where(District.id == profile.district_id)
        ).scalar()
    open_orders = tx.session.execute(
        select(func.count())
        .select_from(Order)
        .where(Order.client_id == client_id, Order.state == "RESERVED")
    ).scalar_one()
    open_requests = tx.session.execute(
        select(func.count())
        .select_from(SourcingRequest)
        .where(SourcingRequest.client_id == client_id, SourcingRequest.state == "OPEN")
    ).scalar_one()
    watches = tx.session.execute(
        select(func.count())
        .select_from(Claim)
        .where(
            Claim.client_id == client_id,
            Claim.kind == "WATCH",
            Claim.state.in_([s.value for s in LIVE_STATES]),
        )
    ).scalar_one()
    asks = tx.session.execute(
        select(func.count())
        .select_from(EarlyReleaseRequest)
        .where(EarlyReleaseRequest.client_id == client_id, EarlyReleaseRequest.state == "OPEN")
    ).scalar_one()

    now = beirut(tx.now)
    days = upcoming_days(tx.now)
    block: list[str] = [
        "## Now",
        f"{display.day(now.date())} {now.year}, {now:%H:%M} (Beirut time).",
        f"Request hours ({REQUEST_HOURS_START:%H:%M}-{REQUEST_HOURS_END:%H:%M}): "
        + ("open." if in_request_hours(tx.now) else "closed: no new watch or request now."),
        "Upcoming days (copy a pickup_day from here, never work out a date): "
        + ", ".join(
            f"{display.day(day)} = {day.isoformat()}" + (" (today)" if index == 0 else "")
            for index, day in enumerate(days)
        ),
        "",
        "## Client",
        f"Account status: {profile.status}. "
        + _location_line(tx, conversation, has_home_area=area is not None)
        + (f"Home area: {area}. " if area else "Home area: not set. ")
        + f"Wants to hear about other brands by default: "
        f"{'yes' if profile.alternatives_ok_default else 'no'}.",
        f"Limits used: reservations {open_orders}/{MAX_OPEN_ORDERS}, "
        f"requests {open_requests}/{MAX_OPEN_REQUESTS}, watches {watches}/{MAX_WATCHES}, "
        f"early-release requests {asks}/{MAX_OPEN_EARLY_RELEASE_REQUESTS}.",
        "",
        "## What you remember (case state)",
        json.dumps(state.for_model(case), ensure_ascii=False),
    ]
    request_id = conversation.request_id
    if request_id is not None:
        request = tx.session.get_one(SourcingRequest, request_id)
        block += [
            "",
            "## This request",
            request_status(tx, request).model_dump_json(exclude_none=True),
        ]
    block += ["", "## The conversation so far (oldest first)"]
    block += _transcript(tx, conversation_id, messages, money) or ["(nothing yet)"]
    block += ["", "## What to do now", _WHAT_NOW[trigger]]

    return Loaded(
        conversation_id=conversation_id,
        client_id=client_id,
        mode=mode,
        request_id=request_id,
        trigger=trigger,
        case_state=case,
        identity=identity_of(tx, client_id),
        last_seq=messages[-1].seq if messages else 0,
        client_text=client_text,
        block="\n".join(block),
    )
