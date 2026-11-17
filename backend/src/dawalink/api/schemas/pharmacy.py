"""What a pharmacy sees (docs/06 §6.9). **Never anything about a client**: an order
number, a product, units, a price and times (INV-9, docs/03 §2.5)."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from dawalink.api.schemas.accounts import OpeningRange, PinIn
from dawalink.api.schemas.common import DistrictId, In, Money, Out, Pin, ProductSummary
from dawalink.api.schemas.search import DayHours


class PharmacyProfile(Out):
    id: uuid.UUID
    name: str
    status: Literal["PENDING", "APPROVED", "REJECTED", "SUSPENDED"]
    status_reason: str | None
    info_requested: bool
    # False until the link of the confirmation email was followed: the registration
    # is not in the admin's queue yet (R-AU7).
    email_verified: bool
    address: str
    district: str
    district_id: int
    phone: str
    license_number: str
    location: Pin
    pickup_days: int
    # Its weekly schedule as it was entered, for the forms.
    hours: list[OpeningRange]
    # Its opening hours for the next 7 days, today first.
    week: list[DayHours]
    open_now: bool
    # When the range that is open right now ends: a pharmacy may close at midday and
    # open again in the afternoon.
    closes_at: datetime | None
    server_now: datetime


class RegistrationChange(In):
    """A pharmacy that waits for approval, or was rejected, corrects what it typed
    (PS-2). Only what is sent changes."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    license_number: str | None = Field(default=None, min_length=1, max_length=40)
    phone: str | None = Field(default=None, min_length=1, max_length=30)
    address: str | None = Field(default=None, min_length=1, max_length=300)
    district_id: DistrictId | None = None
    location: PinIn | None = None
    pickup_days: int | None = Field(default=None, ge=1, le=3)
    hours: list[OpeningRange] | None = Field(default=None, max_length=14)


class SettingsChange(In):
    """What an approved pharmacy changes by itself (PS-10): its hours, its pickup time,
    its phone number, its address and its pin. Its name and its licence are changed by
    DawaLink's team."""

    pickup_days: int | None = Field(default=None, ge=1, le=3)
    phone: str | None = Field(default=None, min_length=1, max_length=30)
    address: str | None = Field(default=None, min_length=1, max_length=300)
    district_id: DistrictId | None = None
    location: PinIn | None = None
    hours: list[OpeningRange] | None = Field(default=None, max_length=14)


class Dashboard(Out):
    """Today in numbers (PS-3)."""

    # Reserved in the last 24 hours and still waiting: put these boxes aside.
    new_reservations: int
    due_today: int
    open_asks: int
    live_listings: int
    units_reserved: int
    last_inventory_update: datetime | None
    # No update for a week: the stock shown to clients may be out of date (N-16).
    stale: bool
    server_now: datetime


class PharmacyReservation(Out):
    id: uuid.UUID
    ref: str
    state: Literal[
        "RESERVED",
        "PICKED_UP",
        "NOT_AVAILABLE",
        "EXPIRED_NO_SHOW",
        "CANCELLED_BY_CLIENT",
        "CANCELLED_BY_SYSTEM",
    ]
    status_text: str
    product: ProductSummary
    batch: str
    expiry_date: date
    # The packs held now (or handed over, once picked up).
    qty: int
    qty_requested: int
    price_each: Money
    total: Money
    pickup_day: date | None
    deadline: datetime | None
    is_new: bool
    created_at: datetime
    closed_at: datetime | None


class PharmacyReservations(Out):
    items: list[PharmacyReservation]
    next_cursor: str | None
    server_now: datetime


class NotAvailable(In):
    # None: every pack of the reservation.
    units: int | None = Field(default=None, ge=1, le=10)


class PrivateItem(Out):
    batch: str
    expiry_date: date
    qty_available: int


class EarlyReleaseAsk(Out):
    """ "A client needs 2 packs today. You hold 5 that aren't listed yet. Release them?"
    Nothing here says who the client is (R-E8)."""

    id: uuid.UUID
    state: Literal["ASKED", "ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN"]
    product: ProductSummary
    qty_needed: int
    private_item: PrivateItem
    suggested_price: Money
    respond_by: datetime
    answered_at: datetime | None


class EarlyReleaseAsks(Out):
    items: list[EarlyReleaseAsk]
    server_now: datetime


class AcceptAsk(In):
    qty: int = Field(ge=1, le=3)
    price_lbp: int = Field(ge=0)


class DeclineAsk(In):
    # A reason from a list, never free text: nothing a pharmacy types reaches the AI (R-AG8).
    reason: Literal["keeping_it", "no_longer_in_stock", "price", "other"]


class AskAnswered(Out):
    state: Literal["ACCEPTED", "WITHDRAWN", "DECLINED"]
    message: str
