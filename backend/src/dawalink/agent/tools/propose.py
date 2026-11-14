"""The proposal tools: they create cards, and only a client's tap acts (docs/07 §4.3).

Each tool runs the same checks as the real action, without locking or changing anything.
If the action wouldn't be allowed now, the tool answers with the reason instead of a
card. The tap checks everything again (INV-11, INV-21).
"""

import uuid
from datetime import date
from typing import Annotated

from pydantic import Field, model_validator
from sqlalchemy import func, select

from dawalink.agent import display
from dawalink.agent.state import Money
from dawalink.agent.tools.base import (
    Arguments,
    Output,
    Refused,
    Tool,
    ToolError,
    Turn,
    location_of,
    rate,
)
from dawalink.agent.tools.read import BOTH, Days, Qty, own_request
from dawalink.db.models import (
    ClientProfile,
    Conversation,
    Order,
    Pharmacy,
    Product,
    Proposal,
    RequestItem,
    SourcingRequest,
)
from dawalink.domain.numbers import MAX_OPEN_REQUESTS, SEARCH_WINDOW
from dawalink.domain.requests import FINAL_ITEM_STATES, ItemState
from dawalink.domain.vocabulary import AgentMode, ProposalKind
from dawalink.services import (
    catalog,
    claims,
    clients,
    orders,
    pharmacies,
    proposals,
    requests,
    travel,
)
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.orders import ReserveLine
from dawalink.services.proposals import CardText
from dawalink.services.search import visible_boxes

ASSISTANT = frozenset({AgentMode.ASSISTANT})
SOURCING = frozenset({AgentMode.SOURCING})


class Preview(Output):
    title: str
    lines: list[str]


class Proposed(Output):
    proposal_id: uuid.UUID
    preview: Preview


def _keep(
    turn: Turn, tx: Tx, kind: ProposalKind, payload: dict[str, object], card: CardText
) -> Proposed:
    """Stores the card and remembers it for this turn's reply."""
    proposal = proposals.create(
        tx,
        conversation_id=turn.conversation_id,
        client_id=turn.client_id,
        kind=kind,
        payload=payload,
        card=card,
        run_id=turn.run_id,
    )
    turn.created_proposals.append(proposal.id)
    turn.state.open_proposal_ids.append(proposal.id)
    return Proposed(
        proposal_id=proposal.id,
        preview=Preview(
            title=card.title, lines=[f"{label}: {value}" for label, value in card.lines]
        ),
    )


def _packs(qty: int) -> str:
    return "1 pack" if qty == 1 else f"{qty} packs"


def _trip(way: object) -> str:
    """ "8 min by car · 25 min on foot", with "about" for a straight-line estimate."""
    car, walk, source = way.car_min, way.walk_min, way.source  # type: ignore[attr-defined]
    about = "about " if source == "straight" else ""
    return f"{about}{car} min by car · {about}{walk} min on foot"


def _item_of_request(turn: Turn, tx: Tx, product_id: uuid.UUID) -> uuid.UUID | None:
    """In a request's thread, the item this box would serve. None in a chat."""
    if turn.request_id is None:
        return None
    request = tx.session.get_one(SourcingRequest, turn.request_id)
    product = catalog.allowed_product(tx, product_id)
    for item in requests.items_of(tx, request.id):
        if ItemState(item.state) in FINAL_ITEM_STATES:
            continue
        wanted = catalog.allowed_product(tx, item.product_id)
        allowed = catalog.products_in_group(tx, wanted, with_equivalents=request.alternatives_ok)
        if product.id in allowed:
            return item.id
    raise ServiceError(
        Code.VALIDATION_ERROR, "This box isn't one of the medicines this request still needs."
    )


# --- propose_reservation ---------------------------------------------------------------


class ProposeReservation(Arguments):
    listing_id: uuid.UUID
    qty: Qty = 1
    pickup_day: date = Field(description="One of the option's pickup_days_allowed.")
    days_of_use: Days = 1
    recommended: bool = Field(
        default=False, description="True for the one pharmacy you recommend for this medicine."
    )


def propose_reservation(turn: Turn, tx: Tx, args: ProposeReservation) -> Proposed:
    boxes = visible_boxes(tx, item_ids=[args.listing_id])
    if not boxes:
        raise ServiceError(Code.LISTING_NOT_AVAILABLE, "This option is no longer available.")
    box = boxes[0]
    item_id = _item_of_request(turn, tx, box.product_id)
    line = ReserveLine(args.listing_id, args.qty, box.price_lbp, args.days_of_use, item_id)
    orders.check_reservable(tx, client_id=turn.client_id, lines=[line], pickup_day=args.pickup_day)
    product = tx.session.get_one(Product, box.product_id)
    hours = pharmacies.weekly_hours(tx, [box.pharmacy_id])
    pharmacy = pharmacies.cards(tx, [box.pharmacy_id], hours)[box.pharmacy_id]
    way = travel.travel_to(tx, location_of(tx, turn), [box.pharmacy_id])[box.pharmacy_id]
    card = CardText(
        title=f"{product.moph_name} at {pharmacy.name}",
        lines=[
            ("Pharmacy", f"{pharmacy.name}, {pharmacy.district}"),
            ("Quantity", _packs(args.qty)),
            ("At the counter", display.money(box.price_lbp * args.qty, rate(tx))),
            ("Pick up", display.day(args.pickup_day)),
            ("Expires", display.day(box.expiry_date) + f" {box.expiry_date.year}"),
            ("Travel", _trip(way)),
        ],
        prescription_notice=product.prescription_required,
        recommended=args.recommended,
    )
    payload: dict[str, object] = {
        "listing_id": str(args.listing_id),
        "product_id": str(box.product_id),
        "qty": args.qty,
        "price_lbp_shown": box.price_lbp,
        "pickup_day": args.pickup_day.isoformat(),
        "days_of_use": args.days_of_use,
        "request_item_id": str(item_id) if item_id else None,
    }
    proposed = _keep(turn, tx, ProposalKind.RESERVE, payload, card)
    if item_id is not None and turn.request_id is not None:
        requests.items_proposed(tx, turn.request_id, [item_id])
    return proposed


# --- propose_plan ----------------------------------------------------------------------


class ProposePlan(Arguments):
    plan_id: str = Field(description="A plan_id from plan_basket.")
    group_indexes: list[Annotated[int, Field(ge=0, le=3)]] | None = Field(
        default=None, description="Which pharmacies of the plan. Leave empty for all of them."
    )


class PlanCard(Output):
    proposal_id: uuid.UUID
    pharmacy_name: str
    items: list[str]


class GroupRefused(Output):
    group_index: int
    error_code: str
    hint: str


class ProposedPlan(Output):
    proposals: list[PlanCard]
    # A pharmacy whose card couldn't be made, and why. The others are still valid.
    refused: list[GroupRefused]


def propose_plan(turn: Turn, tx: Tx, args: ProposePlan) -> ProposedPlan:
    plan = turn.state.plans.get(args.plan_id)
    if plan is None:
        raise Refused(
            ToolError.PLAN_NOT_FOUND, "Unknown plan. Call plan_basket again and use its plan_id."
        )
    wanted = range(len(plan.groups)) if args.group_indexes is None else args.group_indexes
    if any(index >= len(plan.groups) for index in wanted):
        raise Refused(ToolError.PLAN_NOT_FOUND, "This plan has no pharmacy with that index.")
    money = rate(tx)
    cards: list[PlanCard] = []
    refused: list[GroupRefused] = []
    for index in dict.fromkeys(wanted):
        group = plan.groups[index]
        lines = [
            ReserveLine(
                pick.listing_id, pick.qty, pick.price_lbp, pick.days_of_use, pick.request_item_id
            )
            for pick in group.picks
        ]
        try:
            boxes = orders.check_reservable(
                tx, client_id=turn.client_id, lines=lines, pickup_day=plan.pickup_day
            )
        except ServiceError as error:
            refused.append(
                GroupRefused(group_index=index, error_code=error.code.value, hint=str(error))
            )
            continue
        products = {
            product.id: product
            for product in tx.session.execute(
                select(Product).where(Product.id.in_({box.product_id for box in boxes.values()}))
            ).scalars()
        }
        pharmacy = tx.session.get_one(Pharmacy, group.pharmacy_id)
        named = [(products[boxes[pick.listing_id].product_id], pick) for pick in group.picks]
        total = sum(pick.price_lbp * pick.qty for pick in group.picks)
        card = CardText(
            title=f"{pharmacy.name} · {len(group.picks)} "
            + ("medicine" if len(group.picks) == 1 else "medicines"),
            lines=[
                *(
                    (
                        f"{product.moph_name} x {pick.qty}",
                        display.money(pick.price_lbp * pick.qty, money),
                    )
                    for product, pick in named
                ),
                ("Total at the counter", display.money(total, money)),
                ("Pick up", display.day(plan.pickup_day)),
            ],
            prescription_notice=any(product.prescription_required for product, _ in named),
        )
        payload: dict[str, object] = {
            "pharmacy_id": str(group.pharmacy_id),
            "pickup_day": plan.pickup_day.isoformat(),
            "items": [
                {
                    "item_key": str(pick.listing_id),
                    "listing_id": str(pick.listing_id),
                    "product_id": str(boxes[pick.listing_id].product_id),
                    "label": f"{product.moph_name} x {pick.qty}",
                    "qty": pick.qty,
                    "price_lbp_shown": pick.price_lbp,
                    "days_of_use": pick.days_of_use,
                    "request_item_id": str(pick.request_item_id) if pick.request_item_id else None,
                }
                for product, pick in named
            ],
        }
        proposed = _keep(turn, tx, ProposalKind.RESERVE_GROUP, payload, card)
        cards.append(
            PlanCard(
                proposal_id=proposed.proposal_id,
                pharmacy_name=pharmacy.name,
                items=[f"{product.moph_name} x {pick.qty}" for product, pick in named],
            )
        )
        item_ids = [pick.request_item_id for pick in group.picks if pick.request_item_id]
        if item_ids and turn.request_id is not None:
            requests.items_proposed(tx, turn.request_id, item_ids)
    return ProposedPlan(proposals=cards, refused=refused)


# --- propose_cancellation --------------------------------------------------------------


class ProposeCancellation(Arguments):
    order_ref: str = Field(
        min_length=3, max_length=12, description="An order number, like R-7K3Q2F."
    )


def propose_cancellation(turn: Turn, tx: Tx, args: ProposeCancellation) -> Proposed:
    found = tx.session.execute(
        select(Order, Product.moph_name, Pharmacy.name)
        .join(Product, Product.id == Order.product_id)
        .join(Pharmacy, Pharmacy.id == Order.pharmacy_id)
        .where(Order.ref == args.order_ref.strip().upper(), Order.client_id == turn.client_id)
    ).one_or_none()
    if found is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown reservation.")
    order, product_name, pharmacy_name = found
    if order.state != "RESERVED":
        raise ServiceError(
            Code.RESERVATION_NOT_ACTIVE, "This reservation is no longer active.", state=order.state
        )
    card = CardText(
        title=f"Cancel {order.ref}?",
        lines=[
            ("Medicine", f"{product_name} x {order.qty_locked}"),
            ("Pharmacy", pharmacy_name),
            ("After cancelling", "The box goes back to the pharmacy's stock."),
        ],
    )
    return _keep(turn, tx, ProposalKind.CANCEL, {"order_id": str(order.id)}, card)


# --- prepare_request_summary -----------------------------------------------------------


class SummaryItem(Arguments):
    product_id: uuid.UUID
    qty: Qty = 1
    days_of_use: Days = 1
    max_price: Money | None = None


class PrepareRequestSummary(Arguments):
    items: list[SummaryItem] = Field(min_length=1, max_length=5)
    alternatives_ok: bool = Field(description="Whether the client agreed to other brands.")


def prepare_request_summary(turn: Turn, tx: Tx, args: PrepareRequestSummary) -> Proposed:
    clients.require_reserve(tx, clients.profile(tx, turn.client_id))
    claims.require_request_hours(tx)
    open_requests = tx.session.execute(
        select(func.count())
        .select_from(SourcingRequest)
        .where(SourcingRequest.client_id == turn.client_id, SourcingRequest.state == "OPEN")
    ).scalar_one()
    if open_requests >= MAX_OPEN_REQUESTS:
        raise ServiceError(Code.LIMIT_OPEN_REQUESTS, "You have 2 open requests (the maximum).")
    if len({item.product_id for item in args.items}) != len(args.items):
        raise ServiceError(Code.VALIDATION_ERROR, "Each medicine appears once in a request.")
    location_of(tx, turn)  # a request needs a location: say so now, not at the tap
    conversation = tx.session.get_one(Conversation, turn.conversation_id)
    profile = tx.session.get(ClientProfile, turn.client_id)
    money = rate(tx)
    lines: list[tuple[str, str]] = []
    stored = []
    notice = False
    for item in args.items:
        product = catalog.allowed_product(tx, item.product_id)
        notice = notice or product.prescription_required
        limit = display.in_lbp(item.max_price, money)
        lines.append(
            (
                f"{product.moph_name} x {item.qty}",
                f"for {item.days_of_use} day"
                + ("" if item.days_of_use == 1 else "s")
                + (f", up to {display.money(limit, money)}" if limit is not None else ""),
            )
        )
        stored.append(
            {
                "product_id": str(product.id),
                "qty": item.qty,
                "days_of_use": item.days_of_use,
                "max_price_lbp": limit,
            }
        )
    hours = int(SEARCH_WINDOW.total_seconds() // 3600)
    lines.append(("Other brands of the same medicine", "allowed" if args.alternatives_ok else "no"))
    lines.append(("DawaLink keeps searching for", f"{hours} hours"))
    card = CardText(title="Find these medicines for me", lines=lines, prescription_notice=notice)
    payload: dict[str, object] = {
        "items": stored,
        "alternatives_ok": args.alternatives_ok,
        # Used only when the chat has no shared location (the tap reads that itself).
        "district_id": (
            profile.district_id if profile is not None and conversation.loc_lat is None else None
        ),
    }
    return _keep(turn, tx, ProposalKind.REQUEST_SUMMARY, payload, card)


# --- propose_constraint_change ---------------------------------------------------------


class ProposeConstraintChange(Arguments):
    request_id: uuid.UUID
    allow_alternatives: bool = Field(
        default=False, description="Propose allowing other brands of the same medicines."
    )
    item_id: uuid.UUID | None = Field(default=None, description="The item whose budget would rise.")
    max_price: Money | None = Field(default=None, description="The new, higher budget for item_id.")

    @model_validator(mode="after")
    def _one_change(self) -> "ProposeConstraintChange":
        budget = self.item_id is not None and self.max_price is not None
        if (self.item_id is None) != (self.max_price is None):
            raise ValueError("item_id and max_price go together")
        if budget == self.allow_alternatives:
            raise ValueError("propose exactly one change: allow_alternatives, or a new max_price")
        return self


def _open(request: SourcingRequest) -> None:
    if request.state != "OPEN":
        raise ServiceError(Code.REQUEST_CLOSED, "This request is closed.")


def propose_constraint_change(turn: Turn, tx: Tx, args: ProposeConstraintChange) -> Proposed:
    request = own_request(tx, turn, args.request_id)
    _open(request)
    payload: dict[str, object] = {"request_id": str(request.id)}
    if args.allow_alternatives:
        if request.alternatives_ok:
            raise Refused(ToolError.NOTHING_TO_CHANGE, "Other brands are already allowed.")
        payload["alternatives_ok"] = True
        card = CardText(
            title="Allow other brands?",
            lines=[
                ("Request", request.ref),
                ("Change", "Also accept other brands of exactly the same medicines"),
            ],
        )
    else:
        item = tx.session.get(RequestItem, args.item_id)
        if item is None or item.request_id != request.id:
            raise ServiceError(Code.NOT_FOUND, "Unknown request item.")
        money = rate(tx)
        new_limit = display.in_lbp(args.max_price, money)
        if item.max_price_lbp is None or new_limit is None or new_limit <= item.max_price_lbp:
            raise Refused(
                ToolError.NOTHING_TO_CHANGE, "The new budget must be higher than the current one."
            )
        product = tx.session.get_one(Product, item.product_id)
        payload["item_max_prices"] = {str(item.id): new_limit}
        card = CardText(
            title="Raise the budget?",
            lines=[
                ("Request", request.ref),
                ("Medicine", product.moph_name),
                ("Budget now", display.money(item.max_price_lbp, money)),
                ("New budget", display.money(new_limit, money)),
            ],
        )
    return _keep(turn, tx, ProposalKind.CONSTRAINT_CHANGE, payload, card)


# --- propose_remove_item ---------------------------------------------------------------


class ProposeRemoveItem(Arguments):
    request_id: uuid.UUID
    item_id: uuid.UUID


def propose_remove_item(turn: Turn, tx: Tx, args: ProposeRemoveItem) -> Proposed:
    request = own_request(tx, turn, args.request_id)
    _open(request)
    item = tx.session.get(RequestItem, args.item_id)
    if item is None or item.request_id != request.id:
        raise ServiceError(Code.NOT_FOUND, "Unknown request item.")
    if ItemState(item.state) in FINAL_ITEM_STATES:
        raise Refused(ToolError.NOTHING_TO_CHANGE, "This medicine is already settled.")
    product = tx.session.get_one(Product, item.product_id)
    card = CardText(
        title="Stop looking for this medicine?",
        lines=[
            ("Request", request.ref),
            ("Medicine", f"{product.moph_name} x {item.qty}"),
            ("After removing", "The other medicines carry on."),
        ],
    )
    payload: dict[str, object] = {"request_id": str(request.id), "request_item_id": str(item.id)}
    return _keep(turn, tx, ProposalKind.REMOVE_ITEM, payload, card)


def card_of(proposal: Proposal) -> CardText:
    """The stored card of a proposal, as text."""
    stored = proposal.payload.get("card", {})
    return CardText(
        title=str(stored.get("title", "")),
        lines=[(str(label), str(value)) for label, value in stored.get("lines", [])],
        prescription_notice=bool(stored.get("prescription_notice")),
        recommended=bool(stored.get("recommended")),
    )


TOOLS = (
    Tool(
        "propose_reservation",
        "Creates a [Reserve] card for one option. It reserves nothing: only the client's tap "
        "does. Answers with a reason instead of a card when the reservation wouldn't be "
        "allowed (a limit, the stock, the expiry, the pickup day).",
        ProposeReservation,
        propose_reservation,
        BOTH,
    ),
    Tool(
        "propose_plan",
        "Creates one [Reserve these] card per pharmacy of a plan from plan_basket. Nothing is "
        "reserved until the client taps.",
        ProposePlan,
        propose_plan,
        BOTH,
    ),
    Tool(
        "propose_cancellation",
        "Creates a [Cancel] card for one of the client's own reservations. Only the tap cancels.",
        ProposeCancellation,
        propose_cancellation,
        BOTH,
    ),
    Tool(
        "prepare_request_summary",
        "Creates the [Start sourcing] card for 1 to 5 medicines the client needs now. Use it "
        "when several medicines are needed or nothing is listed. Only the tap starts the request.",
        PrepareRequestSummary,
        prepare_request_summary,
        ASSISTANT,
    ),
    Tool(
        "propose_constraint_change",
        "Creates a card proposing to relax a request: allow other brands, or raise one "
        "medicine's budget. Applied only if the client taps.",
        ProposeConstraintChange,
        propose_constraint_change,
        SOURCING,
    ),
    Tool(
        "propose_remove_item",
        "Creates a card proposing to stop looking for one medicine of a request. Applied only "
        "if the client taps.",
        ProposeRemoveItem,
        propose_remove_item,
        SOURCING,
    ),
)
