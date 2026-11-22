"""A pharmacy's own stock and its stock files (docs/06 §6.9; docs/03 PS-6, PS-7).

Private: only the pharmacy that owns the stock reads any of this. What clients see of it
is a listing (docs/06 §5.3).
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from dawalink.api.schemas.common import In, Lbp, Money, Out, ProductSummary
from dawalink.domain.numbers import MAX_BOX_QUANTITY


class StockPrice(Out):
    # What a client pays today. None while the box isn't in the published window.
    effective: Money | None
    # The system's price for the days left (docs/04 N-4), whatever the pharmacy chose.
    system: Money | None
    # The pharmacy's own price, if it set one (0 is a donation).
    override: Money | None
    discount_pct: int | None


class StockItem(Out):
    id: uuid.UUID
    product: ProductSummary
    batch: str
    expiry_date: date
    days_left: int
    # NEAR_EXPIRY: published · EARLY_RELEASE: private, the agent may ask ·
    # PRIVATE · EXPIRED · NOT_ELIGIBLE: a medicine DawaLink doesn't list.
    zone: Literal["NEAR_EXPIRY", "EARLY_RELEASE", "PRIVATE", "EXPIRED", "NOT_ELIGIBLE"]
    qty_on_hand: int
    qty_reserved: int
    qty_available: int
    paused: bool
    # The pharmacy listed this box by hand, whatever its own rule says ([List now]).
    listed_by_hand: bool
    # It could be listed today and isn't: the pharmacy's rule waits until it has
    # `auto_list_days` left (`/pharmacy/me`). [List now] lists it; the agent may ask for it.
    held_back: bool
    # Clients can find it right now (INV-16).
    visible: bool
    price: StockPrice
    last_edited_at: datetime | None


class Stock(Out):
    items: list[StockItem]
    next_cursor: str | None
    server_now: datetime


class AddStockItem(In):
    product_id: uuid.UUID
    batch: str = Field(min_length=1, max_length=60)
    expiry_date: date
    qty: int = Field(ge=0, le=MAX_BOX_QUANTITY)


class StockItemChange(In):
    """Only what is sent changes. `price_override_lbp: null` goes back to the system's
    price."""

    qty_on_hand: int | None = Field(default=None, ge=0, le=MAX_BOX_QUANTITY)
    price_override_lbp: Lbp | None = None
    paused: bool | None = None
    # true: list this box now, whatever the pharmacy's rule says. false: back to the rule.
    # Never sent together with `paused`.
    listed: bool | None = None


class StockItemChanged(Out):
    item: StockItem
    # The quantity asked for was below what clients have reserved: the reserved packs
    # were kept (R-U3). To give one up, use [Not available] on the reservation.
    reserved_kept: bool


class UploadRowError(Out):
    row: int
    product: str
    problem: str
    did_you_mean: list[str]


class UploadSummary(Out):
    new: int
    changed: int
    # In stock now and missing from the file: set to 0 when applied (R-U2).
    zeroed: int
    # The file says less than clients have reserved: the reserved packs stay (R-U3).
    reserved_kept: int
    # In stock, absent from the file, and left as they are: boxes of a medicine that only
    # the `code` column can name. A row with their code and quantity 0 empties them.
    left_alone: int


class StockUpload(Out):
    """A stock file that was read. Nothing changes until it is applied (SM-4)."""

    id: uuid.UUID
    status: Literal["VALIDATED", "APPLIED", "DISCARDED"]
    file_name: str
    rows_total: int
    rows_ok: int
    rows_error: int
    summary: UploadSummary
    # The first 500. The errors file holds the same rows, to correct in a spreadsheet.
    errors: list[UploadRowError]
    created_at: datetime


class WaitingUpload(Out):
    upload: StockUpload | None
