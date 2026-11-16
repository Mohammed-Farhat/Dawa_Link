"""Reservations as a client sees them (docs/06 §5.3)."""

import uuid
from datetime import date, datetime
from typing import Literal

from dawalink.api.schemas.common import Money, Out, PharmacyCard, ProductSummary


class Reservation(Out):
    id: uuid.UUID
    # The order number shown at the counter.
    ref: str
    state: Literal[
        "RESERVED",
        "PICKED_UP",
        "NOT_AVAILABLE",
        "EXPIRED_NO_SHOW",
        "CANCELLED_BY_CLIENT",
        "CANCELLED_BY_SYSTEM",
    ]
    # In plain words: "Reserved: pick up by Tue 21:00".
    status_text: str
    product: ProductSummary
    pharmacy: PharmacyCard
    qty: int
    qty_requested: int
    # The price when it was reserved; it never changes (INV-5).
    price_each: Money
    total: Money
    # What the client saves against the public price, for the same quantity.
    saving: Money
    pickup_day: date | None
    deadline: datetime | None
    expiry_date: date
    source: Literal["search", "assistant", "request", "watch", "early_release"]
    request_id: uuid.UUID | None
    created_at: datetime
    closed_at: datetime | None
    # An expired reservation the client may still contest (R-N3).
    contestable: bool
    # The app clock when this was written: "today" and "tomorrow" are counted from it,
    # so the demo clock works on every screen (docs/06 §1).
    server_now: datetime


class ReservationsPage(Out):
    items: list[Reservation]
    next_cursor: str | None
    server_now: datetime
