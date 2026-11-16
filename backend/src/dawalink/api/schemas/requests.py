"""Sourcing requests and offers as a client sees them (docs/06 §5.3, §5.4)."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from dawalink.api.schemas.common import In, Money, Out, PharmacyCard, ProductSummary


class ReservationRef(Out):
    id: uuid.UUID
    ref: str
    pharmacy_name: str
    qty: int


class Waiting(Out):
    """What DawaLink is doing for a medicine that isn't secured yet."""

    watching_new_stock: bool
    # "Asked 2 pharmacies": only how many, never which (R-E8).
    asked_pharmacies: int
    answers_by: datetime | None
    open_offer_ids: list[uuid.UUID]


class RequestItem(Out):
    id: uuid.UUID
    position: int
    product: ProductSummary
    qty: int
    qty_secured: int
    days_of_use: int
    max_price: Money | None
    state: Literal["SEARCHING", "PROPOSED", "WAITING", "SECURED", "UNAVAILABLE", "CANCELLED"]
    # In plain words: "1 of 2 reserved, looking for 1 more".
    status_text: str
    reservations: list[ReservationRef]
    waiting: Waiting | None


class SourcingRequest(Out):
    id: uuid.UUID
    ref: str
    state: Literal["OPEN", "CLOSED"]
    outcome: Literal["FULFILLED", "PARTIAL", "UNFULFILLED", "CANCELLED"] | None
    # "Tell me about other brands": shown, never reserved or waited for (R-C10).
    alternatives_ok: bool
    ends_at: datetime
    items: list[RequestItem]
    units_wanted: int
    units_secured: int
    # The request's thread: the agent's messages and cards about it.
    conversation_id: uuid.UUID | None
    created_at: datetime
    closed_at: datetime | None
    server_now: datetime


class SourcingRequests(Out):
    items: list[SourcingRequest]
    server_now: datetime


class Offer(Out):
    """Stock held for the client for two hours: from new stock that matched their need,
    or released by a pharmacy the agent asked. A tap accepts it (O7, O8)."""

    id: uuid.UUID
    kind: Literal["matching", "early_release"]
    product: ProductSummary
    # Named only now that the client has an offer from it (INV-8).
    pharmacy: PharmacyCard
    qty: int
    price_each: Money
    total: Money
    saving: Money
    expiry_date: date
    days_of_use: int
    expires_at: datetime
    # The days the client may come for it, the soonest first.
    pickup_days_allowed: list[date]
    request_id: uuid.UUID | None


class Offers(Out):
    items: list[Offer]
    server_now: datetime


class AcceptOffer(In):
    pickup_day: date


class AdvanceClock(In):
    minutes: int = Field(ge=1, le=7 * 24 * 60)
    reason: str = Field(default="demo", min_length=1, max_length=200)


class DemoClock(Out):
    """The app's own time (R-DEMO). Outside demo mode it is the real time, always."""

    server_now: datetime
    offset_minutes: int
    demo_mode: bool
