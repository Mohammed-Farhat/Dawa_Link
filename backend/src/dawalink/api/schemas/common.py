"""The pieces every answer is built from (docs/06 §5.1)."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Out(BaseModel):
    """Something the API answers with."""

    model_config = ConfigDict(frozen=True)


class In(BaseModel):
    """Something the API is sent. A field nobody declared is refused, never ignored."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _no_zero_byte(cls, sent: Any) -> Any:
        """PostgreSQL can't store a zero byte in a text: refused here, as a field that is
        wrong, before it can reach a statement and come back as a server error."""
        if _holds_a_zero_byte(sent):
            raise ValueError("Text can't contain a zero byte.")
        return sent


def _holds_a_zero_byte(sent: Any) -> bool:
    if isinstance(sent, str):
        return "\x00" in sent
    if isinstance(sent, dict):
        return any(_holds_a_zero_byte(part) for pair in sent.items() for part in pair)
    if isinstance(sent, list | tuple):
        return any(_holds_a_zero_byte(part) for part in sent)
    return False


# Every number that goes on to the database has an upper bound. Without one, a number the
# column can't hold comes back as the database's own error, a server error (found by the
# random requests of `tests/api/test_fuzz.py`, as the district's number was by hand).
MAX_SKIP = 1_000_000  # rows a list may skip: far more than any list here has
MAX_ID = 2**63 - 1  # the largest ID of a log table
MAX_SEQ = 2**31 - 1  # the largest number of a message in its conversation
MAX_LBP = 100_000_000_000  # no medicine costs more: about a million dollars

# Where a list goes on. Lists that grow at the top go on "before this ID"; the others
# skip the rows already shown.
Skip = Annotated[int, Query(ge=0, le=MAX_SKIP)]
BeforeId = Annotated[int | None, Query(ge=1, le=MAX_ID)]
Lbp = Annotated[int, Field(ge=0, le=MAX_LBP)]

# A district's number as a form sends it. The range is the column's own: a larger number
# used to reach the database and come back as a server error (found on 2026-11-16).
DistrictId = Annotated[int, Field(ge=1, le=32_767)]
AreaId = Annotated[int, Field(ge=1, le=32_767)]


class Message(Out):
    """A plain sentence, for the answers that say nothing else."""

    message: str


class Money(Out):
    lbp: int
    # Computed here with the rate of the newest price list; absent when no rate is known.
    usd_approx: float | None


class MoneyIn(In):
    amount: Decimal = Field(gt=0, le=MAX_LBP)
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
    # The Ministry's number for this product. A pharmacy writes it in the `code` column
    # of a stock file when a name and a strength alone could mean several packs.
    code: int


class Pin(Out):
    """Where a pharmacy is: public, like its address. It is what [Directions] opens and
    what the map shows. (A **client's** location is what never leaves the server.)"""

    lat: float
    lon: float


class Travel(Out):
    """How far a pharmacy is from the client. Computed by code; never a coordinate."""

    car_min: int
    walk_min: int
    km: float
    # "straight" is an estimate, shown as "about".
    source: Literal["road", "straight"]


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
    district_id: DistrictId | None = None
