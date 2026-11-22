"""Conversations, messages and cards (docs/06 §5.5, §6.6, §6.7)."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from dawalink.api.schemas.common import In, Money, Out, Travel
from dawalink.api.schemas.orders import Reservation


class CardLine(Out):
    label: str
    value: str


class CardBox(Out):
    """What a reserve, plan or "another brand" card shows of its boxes, as search shows a
    box (B#5). Written by code when the card was made; the model never reads it."""

    # At the counter, for every pack on the card, and what that saves.
    price: Money
    saving: Money
    # The box's expiry, or the soonest of the card's boxes.
    expiry_date: date
    # The client's days of use, which every box lasts. None when the boxes are for
    # different days (each lasts its own). 1 is also what is used when they didn't say.
    days_of_use: int | None
    # The pharmacy's opening hours on the pickup day: "08:00-13:00, 16:00-21:00".
    hours_on_pickup_day: str | None
    travel: Travel | None


class SelectableItem(Out):
    """One checkbox of a [Reserve these] card (R-RQ6)."""

    item_key: str
    label: str
    price: Money


class Card(Out):
    """A card under a message. **Its words are written by code and stored**; the model
    only chose to show it (R-AG7).

    - `origin = "proposal"`: made by one of the agent's tools. Its button calls
      `POST /proposals/{card_id}/execute`.
    - `origin = "system"`: a template card about something that happened (reserved, picked
      up, an offer). `type` names the template and `data` holds its facts.
    """

    card_id: str
    origin: Literal["proposal", "system"]
    type: str
    title: str
    lines: list[CardLine]
    prescription_notice: bool
    recommended: bool
    state: Literal["open", "used", "expired"]
    expires_at: datetime | None
    # The label of the card's one button, or None when a tap on it does nothing.
    action_label: str | None
    selectable_items: list[SelectableItem]
    # An "another brand" card: the pharmacy's phone, read from its record when the card
    # is served. It never passes the model (R-AG8).
    call_number: str | None
    data: dict[str, Any]
    # A proposal card's boxes: its price, saving, fit and hours. None on the other cards,
    # and on cards made before these were stored.
    box: CardBox | None = None


class ChatMessage(Out):
    seq: int
    author: Literal["client", "agent", "system", "admin"]
    kind: Literal["text", "card", "timeline"]
    # Stored without personal details (INV-10): a phone number shows as "[phone]".
    text: str | None
    cards: list[Card]
    # Tapping a chip only sends its text as a new message.
    quick_replies: list[str]
    reportable: bool
    # The client already pressed the thumbs-down on it: once per reply (SM-10).
    reported: bool
    created_at: datetime


class ChatSummary(Out):
    """One line of the client's list of chats (D9)."""

    conversation_id: uuid.UUID
    active: bool
    started_at: datetime
    last_activity_at: datetime
    # The start of the client's first message, or None for a chat with none yet.
    title: str | None


class Chats(Out):
    items: list[ChatSummary]
    server_now: datetime


class MessagesPage(Out):
    """What the page asks for every few seconds while it is open (API-D7)."""

    conversation_id: uuid.UUID
    kind: Literal["chat", "request"]
    request_id: uuid.UUID | None
    messages: list[ChatMessage]
    last_seq: int
    # An agent turn is running: show "…".
    busy: bool
    # An earlier chat, put away by [New chat]: it can be read, not written in.
    archived: bool
    # Where the agent's tools count travel times from, as words. Never coordinates.
    location: "LocationSummary"
    server_now: datetime


class LocationSummary(Out):
    # "place": the place saved in the profile; "profile": its home town or district.
    source: Literal["shared", "district", "area", "profile", "place", "none"]
    label: str | None


class ConversationRef(Out):
    conversation_id: uuid.UUID
    kind: Literal["chat", "request"]


class SendMessage(In):
    text: str = Field(min_length=1, max_length=4000)
    # Chosen by the website for each message: the same ID is never processed twice.
    client_message_id: uuid.UUID


class MessageAccepted(Out):
    message_seq: int


class ExecuteProposal(In):
    # Only for a [Reserve these] card: the items left ticked.
    selected_item_keys: list[str] | None = Field(default=None, max_length=10)


class ExecuteResult(Out):
    proposal_id: uuid.UUID
    kind: str
    reservations: list[Reservation]
    request_id: uuid.UUID | None
    request_ref: str | None
    message: str
