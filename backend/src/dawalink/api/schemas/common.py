"""The pieces every answer is built from (docs/06 §5.1)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Out(BaseModel):
    """Something the API answers with."""

    model_config = ConfigDict(frozen=True)


class In(BaseModel):
    """Something the API is sent. A field nobody declared is refused, never ignored."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Message(Out):
    """A plain sentence, for the answers that say nothing else."""

    message: str


class Money(Out):
    lbp: int
    # Computed here with the rate of the newest price list; absent when no rate is known.
    usd_approx: float | None


class MoneyIn(In):
    amount: Decimal = Field(gt=0)
    currency: Literal["LBP", "USD"]


class District(Out):
    id: int
    name: str
    governorate: str
    # The district's centre, public like any map: where a map opens before a pharmacy
    # puts its pin. (A client's own location never leaves the server.)
    lat: float
    lon: float


class ProductSummary(Out):
    id: uuid.UUID
    name: str
    strength: str | None
    form: str | None
    pack: str | None
    prescription_required: bool
    public_price: Money


class Pin(Out):
    """Where a pharmacy is: public, like its address. It is what [Directions] opens and
    what the map shows. (A **client's** location is what never leaves the server.)"""

    lat: float
    lon: float


class PharmacyCard(Out):
    """What a client sees about a pharmacy."""

    id: uuid.UUID
    name: str
    district: str
    governorate: str
    address: str
    phone: str
    open_now: bool
    closes_at: datetime | None
    pickup_days: int
    pin: Pin


class LocationIn(In):
    """Where the client is: a shared or picked point, or a district. Stored rounded, and
    never sent to the AI (R-S2)."""

    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    district_id: int | None = None
