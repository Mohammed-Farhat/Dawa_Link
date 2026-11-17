"""Rows turned into what the API answers with (docs/06 §5).

Nothing here decides anything: it reads, formats, and leaves out what the caller must not
see (a client never gets coordinates or private stock; a pharmacy never gets a client).
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from dawalink.api.schemas import accounts as account_schemas
from dawalink.api.schemas import chat as chat_schemas
from dawalink.api.schemas import common
from dawalink.api.schemas import orders as order_schemas
from dawalink.api.schemas import search as search_schemas
from dawalink.db.models import (
    Area,
    ChatMessage,
    ClientProfile,
    Conversation,
    District,
    InventoryItem,
    Order,
    Pharmacy,
    Product,
    Proposal,
    RequestItem,
    User,
)
from dawalink.domain.clock import beirut
from dawalink.domain.money import usd_approx
from dawalink.domain.numbers import LOCATION_DECIMALS, NO_SHOW_WINDOW, NO_SHOWS_BEFORE_PAUSE
from dawalink.domain.orders import OrderState
from dawalink.domain.vocabulary import MessageKind, ProposalKind, UserRole
from dawalink.services import answer_reports, auth, email, pharmacies, proposals, search
from dawalink.services.catalog import ProductRef
from dawalink.services.context import Tx

# --- Small pieces -----------------------------------------------------------------------


def rate(tx: Tx) -> Decimal | None:
    """The LBP per USD rate of the newest price list (R-C3)."""
    return email.display_rate(tx)


def money(amount_lbp: int, lbp_per_usd: Decimal | None) -> common.Money:
    return common.Money(
        lbp=amount_lbp,
        usd_approx=usd_approx(amount_lbp, int(lbp_per_usd)) if lbp_per_usd else None,
    )


def district(row: District) -> common.District:
    return common.District(
        id=row.id,
        name=row.name,
        governorate=row.governorate,
        lat=float(row.ref_lat),
        lon=float(row.ref_lon),
    )


def product_summary(product: Product, lbp_per_usd: Decimal | None) -> common.ProductSummary:
    return common.ProductSummary(
        id=product.id,
        name=product.moph_name,
        strength=product.dosage_text,
        form=product.form_text,
        pack=product.presentation_text,
        prescription_required=product.prescription_required,
        public_price=money(product.public_price_lbp, lbp_per_usd),
        code=product.moph_code,
    )


def pharmacy_cards(
    tx: Tx, pharmacy_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, common.PharmacyCard]:
    """What a client sees of these pharmacies. The phone is public: it is on the door."""
    ids = list(set(pharmacy_ids))
    if not ids:
        return {}
    cards = pharmacies.cards(tx, ids, pharmacies.weekly_hours(tx, ids))
    public = {
        pharmacy_id: (phone, lat, lon)
        for pharmacy_id, phone, lat, lon in tx.session.execute(
            select(Pharmacy.id, Pharmacy.phone, Pharmacy.lat, Pharmacy.lon).where(
                Pharmacy.id.in_(ids)
            )
        ).all()
    }
    return {
        pharmacy_id: common.PharmacyCard(
            id=card.id,
            name=card.name,
            district=card.district,
            governorate=card.governorate,
            address=card.address,
            phone=public[pharmacy_id][0],
            open_now=card.open_now,
            closes_at=card.closes_at,
            pickup_days=card.pickup_days,
            pin=common.Pin(lat=float(public[pharmacy_id][1]), lon=float(public[pharmacy_id][2])),
        )
        for pharmacy_id, card in cards.items()
    }


def product_from_ref(ref: ProductRef, lbp_per_usd: Decimal | None) -> common.ProductSummary:
    return common.ProductSummary(
        id=ref.id,
        name=ref.name,
        strength=ref.strength,
        form=ref.form,
        pack=ref.pack,
        prescription_required=ref.prescription_required,
        public_price=money(ref.public_price_lbp, lbp_per_usd),
        code=ref.code,
    )


def listings(
    tx: Tx, found: Sequence[search.Listing], lbp_per_usd: Decimal | None
) -> list[search_schemas.Listing]:
    """Search results as the website gets them: each box with what it saves."""
    shops = pharmacy_cards(tx, [listing.pharmacy.id for listing in found])
    return [
        search_schemas.Listing(
            id=listing.id,
            product=product_from_ref(listing.product, lbp_per_usd),
            pharmacy=shops[listing.pharmacy.id],
            price=money(listing.price_lbp, lbp_per_usd),
            saving=money(max(0, listing.product.public_price_lbp - listing.price_lbp), lbp_per_usd),
            discount_pct=listing.discount_pct,
            expiry_date=listing.expiry_date,
            days_left=listing.days_left,
            available=listing.available,
            more_available=listing.more_available,
            travel=search_schemas.Travel(
                car_min=listing.travel.car_min,
                walk_min=listing.travel.walk_min,
                km=listing.travel.km,
                source=listing.travel.source,
            ),
            fits=listing.fits,
            pickup_days_allowed=list(listing.pickup_days_allowed),
            expiry_limits_pickup=listing.expiry_limits_pickup,
        )
        for listing in found
    ]


# --- Accounts ---------------------------------------------------------------------------


def me(tx: Tx, user: User) -> account_schemas.Me:
    client: account_schemas.ClientState | None = None
    pharmacy: account_schemas.PharmacyState | None = None
    if user.role == UserRole.CLIENT.value:
        profile = tx.session.get_one(ClientProfile, user.id)
        home = tx.session.get(District, profile.district_id) if profile.district_id else None
        missed = tx.session.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.client_id == user.id,
                Order.counts_as_no_show.is_(True),
                Order.closed_at > tx.now - NO_SHOW_WINDOW,
            )
        ).scalar_one()
        client = account_schemas.ClientState(
            status=profile.status,
            paused_until=profile.paused_until,
            district=district(home) if home else None,
            alternatives_ok_default=profile.alternatives_ok_default,
            missed_pickups_30d=missed,
            missed_pickups_before_pause=NO_SHOWS_BEFORE_PAUSE,
        )
    elif user.role == UserRole.PHARMACIST.value:
        own = auth.pharmacy_of(tx, user.id)
        if own is not None:
            pharmacy = account_schemas.PharmacyState(
                id=own.id,
                name=own.name,
                status=own.status,
                status_reason=own.status_reason,
                info_requested=own.info_requested,
            )
    return account_schemas.Me(
        id=user.id,
        role=user.role,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        email_verified=user.email_verified_at is not None,
        client=client,
        pharmacy=pharmacy,
    )


# --- Reservations -----------------------------------------------------------------------

# An offer isn't a reservation yet: it has its own screens and endpoints (docs/06 §6.3).
RESERVATION_STATES = (
    OrderState.RESERVED,
    OrderState.PICKED_UP,
    OrderState.NOT_AVAILABLE,
    OrderState.EXPIRED_NO_SHOW,
    OrderState.CANCELLED_BY_CLIENT,
    OrderState.CANCELLED_BY_SYSTEM,
)
CONTEST_WITHIN_DAYS = 30  # R-N3


def clock_words(moment: datetime, now: datetime) -> str:
    """ "today 21:00", "tomorrow 13:00" or "Fri 21:00", in Beirut time (docs/11 §8)."""
    local, today = beirut(moment), beirut(now).date()
    # A pharmacy open until midnight gives a deadline at 00:00 of the next day: that is
    # "today 24:00", as its opening hours say, not "tomorrow 00:00".
    midnight = (local.hour, local.minute) == (0, 0)
    on = (local - timedelta(minutes=1)).date() if midnight else local.date()
    days = (on - today).days
    day = {0: "today", 1: "tomorrow"}.get(days, f"{on:%a} {on.day} {on:%b}")
    return f"{day} {'24:00' if midnight else f'{local:%H:%M}'}"


def status_text(order: Order, now: datetime) -> str:
    """An order's state in plain words: the website never shows a raw state (docs/03 §1.1)."""
    state = OrderState(order.state)
    if state is OrderState.RESERVED and order.deadline is not None:
        return f"Reserved: pick up by {clock_words(order.deadline, now)}"
    return {
        OrderState.RESERVED: "Reserved",
        OrderState.PICKED_UP: "Picked up",
        OrderState.NOT_AVAILABLE: "Not available: the pharmacy didn't have it",
        OrderState.EXPIRED_NO_SHOW: "Expired: it wasn't picked up in time",
        OrderState.CANCELLED_BY_CLIENT: "Cancelled by you",
        OrderState.CANCELLED_BY_SYSTEM: "Cancelled by DawaLink",
    }.get(state, "Not reserved")


def reservations(tx: Tx, orders: Sequence[Order]) -> list[order_schemas.Reservation]:
    if not orders:
        return []
    lbp_per_usd = rate(tx)
    products = {
        product.id: product
        for product in tx.session.execute(
            select(Product).where(Product.id.in_({order.product_id for order in orders}))
        ).scalars()
    }
    expiries = dict(
        tx.session.execute(
            select(InventoryItem.id, InventoryItem.expiry_date).where(
                InventoryItem.id.in_({order.inventory_item_id for order in orders})
            )
        ).all()
    )
    request_of_item = dict(
        tx.session.execute(
            select(RequestItem.id, RequestItem.request_id).where(
                RequestItem.id.in_(
                    {order.request_item_id for order in orders if order.request_item_id}
                )
            )
        ).all()
    )
    shops = pharmacy_cards(tx, [order.pharmacy_id for order in orders])
    shown: list[order_schemas.Reservation] = []
    for order in orders:
        product = products[order.product_id]
        state = OrderState(order.state)
        # What the client holds now, or was handed; what they asked for once it is over.
        qty = (
            order.qty_picked_up
            if state is OrderState.PICKED_UP and order.qty_picked_up is not None
            else order.qty_locked or order.qty_requested
        )
        saved = max(0, product.public_price_lbp - order.price_snapshot_lbp) * qty
        shown.append(
            order_schemas.Reservation(
                id=order.id,
                ref=order.ref,
                state=order.state,
                status_text=status_text(order, tx.now),
                product=product_summary(product, lbp_per_usd),
                pharmacy=shops[order.pharmacy_id],
                qty=qty,
                qty_requested=order.qty_requested,
                price_each=money(order.price_snapshot_lbp, lbp_per_usd),
                total=money(order.price_snapshot_lbp * qty, lbp_per_usd),
                saving=money(saved, lbp_per_usd),
                pickup_day=order.pickup_day,
                deadline=order.deadline,
                expiry_date=expiries[order.inventory_item_id],
                source=order.source,
                request_id=request_of_item.get(order.request_item_id)
                if order.request_item_id
                else None,
                created_at=order.created_at,
                closed_at=order.closed_at,
                contestable=(
                    state is OrderState.EXPIRED_NO_SHOW
                    and order.contested_at is None
                    and order.closed_at is not None
                    and (tx.now - order.closed_at).days < CONTEST_WITHIN_DAYS
                ),
                server_now=tx.now,
            )
        )
    return shown


# --- Cards and messages -----------------------------------------------------------------

# The one button of each agent card (docs/11 §4). A card with no entry has no button.
ACTION_LABEL: dict[ProposalKind, str] = {
    ProposalKind.RESERVE: "Reserve",
    ProposalKind.RESERVE_GROUP: "Reserve these",
    ProposalKind.CANCEL: "Cancel this reservation",
    ProposalKind.REQUEST_SUMMARY: "Start sourcing",
    ProposalKind.CONSTRAINT_CHANGE: "Yes",
    ProposalKind.REMOVE_ITEM: "Stop looking for it",
}
# What a system card may carry to the website: facts of the event, never an identity.
SYSTEM_CARD_FACTS = frozenset(
    {
        "order_id",
        "order_ref",
        "request_ref",
        "product",
        "pharmacy",
        "units",
        "price_lbp",
        "pickup_by",
        "prescription_required",
        "state",
        "outcome",
        "offer_expires_at",
        "expiry_date",
        "items_secured",
        "items_missing",
        "units_secured",
        "units_requested",
    }
)


def _proposal_card(tx: Tx, proposal: Proposal, lbp_per_usd: Decimal | None) -> chat_schemas.Card:
    stored = proposal.payload.get("card", {})
    kind = ProposalKind(proposal.kind)
    items = [
        chat_schemas.SelectableItem(
            item_key=str(item["item_key"]),
            label=str(item.get("label", "")),
            price=money(int(item["price_lbp_shown"]) * int(item.get("qty", 1)), lbp_per_usd),
        )
        for item in (proposal.payload.get("items") or [])
        if kind is ProposalKind.RESERVE_GROUP
    ]
    return chat_schemas.Card(
        card_id=str(proposal.id),
        origin="proposal",
        type=kind.value,
        title=str(stored.get("title", "")),
        lines=[
            chat_schemas.CardLine(label=str(label), value=str(value))
            for label, value in stored.get("lines", [])
        ],
        prescription_notice=bool(stored.get("prescription_notice")),
        recommended=bool(stored.get("recommended")),
        state=proposals.state_of(tx, proposal),
        expires_at=proposal.expires_at,
        action_label=ACTION_LABEL.get(kind),
        selectable_items=items,
        call_number=proposals.call_number(tx.session, proposal),
        data={},
    )


def _system_card(seq: int, position: int, stored: dict[str, Any]) -> chat_schemas.Card:
    template = str(stored.get("template", "status"))
    return chat_schemas.Card(
        card_id=f"{seq}:{position}",
        origin="system",
        type=template,
        title="",
        lines=[],
        prescription_notice=bool(stored.get("prescription_required")),
        recommended=False,
        state="open",
        expires_at=None,
        action_label=None,
        selectable_items=[],
        call_number=None,
        data={key: value for key, value in stored.items() if key in SYSTEM_CARD_FACTS},
    )


def messages(tx: Tx, rows: Sequence[ChatMessage]) -> list[chat_schemas.ChatMessage]:
    """Messages as the client sees them. **Internal events are never among them**: those
    are what the agent reads, and the client sees the matching card instead (API-D11)."""
    rows = [row for row in rows if row.kind != MessageKind.EVENT.value]
    reported: set[int] = set()
    if rows:
        owner = tx.session.get_one(Conversation, rows[0].conversation_id).client_id
        reported = answer_reports.reported_seqs(tx, owner, rows)
    wanted = [
        uuid.UUID(str(card)) for row in rows if row.author == "agent" for card in (row.cards or [])
    ]
    found = (
        {
            proposal.id: proposal
            for proposal in tx.session.execute(
                select(Proposal).where(Proposal.id.in_(wanted))
            ).scalars()
        }
        if wanted
        else {}
    )
    lbp_per_usd = rate(tx) if wanted else None
    shown: list[chat_schemas.ChatMessage] = []
    for row in rows:
        cards: list[chat_schemas.Card] = []
        for position, card in enumerate(row.cards or []):
            if row.author == "agent":
                proposal = found.get(uuid.UUID(str(card)))
                if proposal is not None and proposal.conversation_id == row.conversation_id:
                    cards.append(_proposal_card(tx, proposal, lbp_per_usd))
            elif isinstance(card, dict):
                cards.append(_system_card(row.seq, position, card))
        shown.append(
            chat_schemas.ChatMessage(
                seq=row.seq,
                author=row.author,
                kind=row.kind,
                text=row.text_redacted,
                cards=cards,
                quick_replies=[str(chip) for chip in (row.quick_replies or [])],
                reportable=row.author == "agent",
                reported=row.seq in reported,
                created_at=row.created_at,
            )
        )
    return shown


def location_summary(tx: Tx, conversation: Conversation) -> chat_schemas.LocationSummary:
    """Where travel times are counted from, in words. Never the point itself (INV-24)."""
    if conversation.loc_lat is None:
        profile = tx.session.get(ClientProfile, conversation.client_id)
        home = (
            tx.session.get(District, profile.district_id)
            if profile and profile.district_id
            else None
        )
        if home is None:
            return chat_schemas.LocationSummary(source="none", label=None)
        return chat_schemas.LocationSummary(source="profile", label=home.name)
    if conversation.loc_area_id is not None:
        area = tx.session.get_one(Area, conversation.loc_area_id)
        return chat_schemas.LocationSummary(source="area", label=area.name)
    if conversation.loc_source == "district":
        named = tx.session.execute(
            select(District.name).where(
                func.round(District.ref_lat, LOCATION_DECIMALS) == conversation.loc_lat,
                func.round(District.ref_lon, LOCATION_DECIMALS) == conversation.loc_lon,
            )
        ).scalar()
        return chat_schemas.LocationSummary(source="district", label=named)
    return chat_schemas.LocationSummary(source="shared", label="Your location")
