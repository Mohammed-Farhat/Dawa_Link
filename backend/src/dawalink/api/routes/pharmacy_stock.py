"""The pharmacy's stock: its boxes, its prices, its stock files (docs/06 §6.9).

A listing is not a separate thing: it is a box of the stock that clients can see today
(near its expiry, not paused, in stock). So one list and one edit serve both the
Inventory and the Listings screens.
"""

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, UploadFile

from dawalink.api import present
from dawalink.api.deps import AsPharmacist, DoWork
from dawalink.api.routes.pharmacy import OwnPharmacy
from dawalink.api.schemas.common import Money
from dawalink.api.schemas.stock import (
    AddStockItem,
    Stock,
    StockItem,
    StockItemChange,
    StockItemChanged,
    StockPrice,
    StockUpload,
    UploadRowError,
    UploadSummary,
    WaitingUpload,
)
from dawalink.db.models import InventoryUpload, Pharmacy
from dawalink.domain.accounts import PharmacyStatus
from dawalink.domain.expiry import Zone
from dawalink.domain.inventory import ListingControl, is_visible
from dawalink.domain.numbers import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from dawalink.domain.pricing import discount_shown_pct
from dawalink.services import inventory
from dawalink.services.context import Tx

router = APIRouter(prefix="/pharmacy", tags=["pharmacy stock"])

CSV = "text/csv; charset=utf-8"


def _download(text: str, file_name: str) -> Response:
    return Response(
        # The mark at the start makes Excel read the file as UTF-8.
        content=("﻿" + text).encode("utf-8"),
        media_type=CSV,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


def _items(tx: Tx, pharmacy_id: uuid.UUID, lines: list[inventory.StockLine]) -> list[StockItem]:
    lbp_per_usd = present.rate(tx)
    status = PharmacyStatus(tx.session.get_one(Pharmacy, pharmacy_id).status)
    shown = []
    for line in lines:
        item, product = line.item, line.product
        available = max(0, item.qty_on_hand - item.qty_reserved)
        control = ListingControl(item.listing_control)
        shown.append(
            StockItem(
                id=item.id,
                product=present.product_summary(product, lbp_per_usd),
                batch=item.batch,
                expiry_date=item.expiry_date,
                days_left=line.days_left,
                zone=line.zone.value,
                qty_on_hand=item.qty_on_hand,
                qty_reserved=item.qty_reserved,
                qty_available=available,
                paused=control is ListingControl.PAUSED,
                visible=is_visible(
                    zone=line.zone,
                    control=control,
                    pharmacy_status=status,
                    qty_available=available,
                    controlled=product.controlled,
                ),
                price=StockPrice(
                    effective=_money(line.price_lbp, lbp_per_usd),
                    system=_money(line.system_price_lbp, lbp_per_usd),
                    override=_money(item.price_override_lbp, lbp_per_usd),
                    discount_pct=(
                        discount_shown_pct(product.public_price_lbp, line.price_lbp)
                        if line.price_lbp is not None
                        else None
                    ),
                ),
                last_edited_at=item.last_edited_at,
            )
        )
    return shown


def _money(lbp: int | None, lbp_per_usd: Decimal | None) -> Money | None:
    return present.money(lbp, lbp_per_usd) if lbp is not None else None


def _one(tx: Tx, pharmacy_id: uuid.UUID, item_id: uuid.UUID) -> StockItem:
    lines = inventory.stock_lines(tx, pharmacy_id, item_ids=[item_id])
    return _items(tx, pharmacy_id, lines)[0]


@router.get("/inventory")
def list_stock(
    pharmacy_id: OwnPharmacy,
    work: DoWork,
    q: Annotated[str, Query(max_length=100)] = "",
    zone: Literal["NEAR_EXPIRY", "EARLY_RELEASE", "PRIVATE", "EXPIRED"] | None = None,
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Stock:
    """The pharmacy's boxes, soonest expiry first. `zone=NEAR_EXPIRY` is its listings."""
    with work.tx() as tx:
        inventory.can_manage(tx, pharmacy_id)
        lines = inventory.stock_lines(
            tx,
            pharmacy_id,
            query=q,
            zone=Zone(zone) if zone else None,
            offset=cursor,
            limit=limit + 1,
        )
        return Stock(
            items=_items(tx, pharmacy_id, lines[:limit]),
            next_cursor=str(cursor + limit) if len(lines) > limit else None,
            server_now=tx.now,
        )


@router.post("/inventory/items", status_code=201)
def add_stock_item(body: AddStockItem, pharmacy_id: OwnPharmacy, work: DoWork) -> StockItem:
    """One box typed by hand. The same medicine, batch and expiry twice is refused
    (`ITEM_EXISTS`): the pharmacy corrects the quantity of the one it has."""
    with work.tx() as tx:
        item = inventory.add_item(
            tx,
            pharmacy_id,
            product_id=body.product_id,
            batch=body.batch,
            expiry_date=body.expiry_date,
            quantity=body.qty,
        )
        return _one(tx, pharmacy_id, item.id)


@router.patch("/inventory/items/{item_id}")
def change_stock_item(
    item_id: uuid.UUID, body: StockItemChange, pharmacy_id: OwnPharmacy, work: DoWork
) -> StockItemChanged:
    """A quantity corrected after a sale in the shop, the pharmacy's own price, or a
    pause. Reserved packs are never taken away here (R-U3)."""
    sent = body.model_fields_set
    with work.tx() as tx:
        edited = inventory.edit_item(
            tx,
            pharmacy_id,
            item_id,
            quantity=body.qty_on_hand if "qty_on_hand" in sent else None,
            price_override_lbp=(
                body.price_override_lbp if "price_override_lbp" in sent else inventory.UNSET
            ),
            listing_control=(
                None
                if "paused" not in sent or body.paused is None
                else ListingControl.PAUSED
                if body.paused
                else ListingControl.LIVE
            ),
        )
        tx.session.flush()
        return StockItemChanged(
            item=_one(tx, pharmacy_id, item_id), reserved_kept=edited.reserved_kept
        )


# --- Stock files ------------------------------------------------------------------------


def _upload(row: InventoryUpload) -> StockUpload:
    return StockUpload(
        id=row.id,
        status=row.status,
        file_name=row.file_name,
        rows_total=row.rows_total,
        rows_ok=row.rows_ok,
        rows_error=row.rows_error,
        summary=UploadSummary(
            new=row.summary.get("new", 0),
            changed=row.summary.get("changed", 0),
            zeroed=row.summary.get("zeroed", 0),
            reserved_kept=row.summary.get("reserved_kept", 0),
        ),
        errors=[
            UploadRowError(
                row=error.get("row", 0),
                product=str(error.get("product", "")),
                problem=str(error.get("problem", "")),
                did_you_mean=[
                    str(hint) for hint in error.get("did_you_mean") or error.get("strengths") or []
                ],
            )
            for error in row.errors
        ],
        created_at=row.created_at,
    )


@router.get("/inventory/template")
def stock_file_template(_caller: AsPharmacist) -> Response:
    """The file to fill in: five columns, two example rows."""
    return _download(inventory.TEMPLATE_CSV, "dawalink-stock-template.csv")


@router.post("/inventory/uploads", status_code=201)
def upload_stock_file(
    file: UploadFile, caller: AsPharmacist, pharmacy_id: OwnPharmacy, work: DoWork
) -> StockUpload:
    """Reads a stock file and says what applying it would change. **Nothing changes
    yet**, and the file itself is never kept (SM-4). A new file replaces the one that was
    waiting."""
    # One byte more than allowed is enough to know it is too large.
    content = file.file.read(inventory.MAX_FILE_BYTES + 1)
    with work.tx() as tx:
        upload = inventory.validate_upload(
            tx, pharmacy_id, caller.user_id, (file.filename or "stock.csv")[:120], content
        )
        return _upload(upload)


@router.get("/inventory/uploads/waiting")
def waiting_stock_file(pharmacy_id: OwnPharmacy, work: DoWork) -> WaitingUpload:
    """The file that waits for [Apply] or [Discard]: the screen finds it again after a
    reload."""
    with work.tx() as tx:
        inventory.can_manage(tx, pharmacy_id)
        waiting = inventory.waiting_upload(tx, pharmacy_id)
        return WaitingUpload(upload=_upload(waiting) if waiting else None)


@router.get("/inventory/uploads/{upload_id}/errors.csv")
def stock_file_errors(upload_id: uuid.UUID, pharmacy_id: OwnPharmacy, work: DoWork) -> Response:
    with work.tx() as tx:
        upload = inventory.own_upload(tx, pharmacy_id, upload_id)
        return _download(inventory.errors_csv(upload), "dawalink-stock-errors.csv")


@router.post("/inventory/uploads/{upload_id}/apply")
def apply_stock_file(upload_id: uuid.UUID, pharmacy_id: OwnPharmacy, work: DoWork) -> StockUpload:
    """[Apply]: the file becomes the pharmacy's stock, all rows or none (R-U1 to R-U4)."""
    with work.tx() as tx:
        return _upload(inventory.apply_upload(tx, pharmacy_id, upload_id))


@router.post("/inventory/uploads/{upload_id}/discard", status_code=204)
def discard_stock_file(upload_id: uuid.UUID, pharmacy_id: OwnPharmacy, work: DoWork) -> Response:
    with work.tx() as tx:
        inventory.discard_upload(tx, pharmacy_id, upload_id)
    return Response(status_code=204)
