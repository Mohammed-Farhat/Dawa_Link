"""A pharmacy's stock: manual edits and file uploads (docs/04 SM-3, SM-4, R-U1 to R-U5).

Two rules run through everything here:
- **reserved units are protected** (R-U3): no edit or upload can take a box away from a
  client who reserved it. To give one up, the pharmacy presses [Not available];
- every change that can put stock on the shelf triggers matching (R-PRI1).
"""

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import delete, select

from dawalink.catalog.composition import normalize
from dawalink.db.models import (
    InventoryItem,
    InventoryUpload,
    InventoryUploadRow,
    Pharmacy,
    Product,
)
from dawalink.domain.accounts import PharmacyStatus, pharmacy_can_manage_inventory
from dawalink.domain.expiry import parse_expiry
from dawalink.domain.inventory import ListingControl, Stock
from dawalink.domain.pricing import is_valid_override
from dawalink.domain.state_machine import Actor
from dawalink.services import audit, catalog, matching, orders
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

MAX_FILE_BYTES = 5 * 1024 * 1024  # N-15
MAX_ROWS = 10_000  # N-15
MAX_ERRORS_KEPT = 500
REQUIRED_COLUMNS = ("product", "batch", "expiry", "quantity")
ALLOWED_COLUMNS = (*REQUIRED_COLUMNS, "strength")
# A cell that starts like this is a formula in a spreadsheet: the file is refused (SM-4).
FORMULA_STARTS = ("=", "+", "@", "\t", "\r")
UNSET: Any = object()


@dataclass(frozen=True)
class Edited:
    item: InventoryItem
    # The quantity was raised to keep what clients have reserved (R-U3).
    reserved_kept: bool


def _manage(tx: Tx, pharmacy_id: uuid.UUID) -> Pharmacy:
    pharmacy = tx.session.get(Pharmacy, pharmacy_id)
    if pharmacy is None or not pharmacy_can_manage_inventory(PharmacyStatus(pharmacy.status)):
        raise ServiceError(Code.PHARMACY_NOT_APPROVED, "This pharmacy can't manage inventory.")
    return pharmacy


def _check_price(product: Product, price_lbp: int | None) -> None:
    if price_lbp is not None and not is_valid_override(price_lbp, product.public_price_lbp):
        raise ServiceError(
            Code.PRICE_ABOVE_PUBLIC,
            "A price is between 0 and the public price.",
            public_price_lbp=product.public_price_lbp,
        )


# --- The manual form ------------------------------------------------------------------


def add_item(
    tx: Tx,
    pharmacy_id: uuid.UUID,
    *,
    product_id: uuid.UUID,
    batch: str,
    expiry_date: date,
    quantity: int,
    price_override_lbp: int | None = None,
) -> InventoryItem:
    _manage(tx, pharmacy_id)
    product = catalog.allowed_product(tx, product_id)
    if quantity < 0 or not batch.strip() or expiry_date < tx.today:
        raise ServiceError(
            Code.VALIDATION_ERROR, "A box needs a batch, a quantity and a future expiry."
        )
    _check_price(product, price_override_lbp)
    existing = tx.session.execute(
        select(InventoryItem.id).where(
            InventoryItem.pharmacy_id == pharmacy_id,
            InventoryItem.product_id == product_id,
            InventoryItem.batch == batch.strip(),
            InventoryItem.expiry_date == expiry_date,
        )
    ).scalar()
    if existing is not None:
        raise ServiceError(
            Code.ITEM_EXISTS, "This box is already in your inventory.", item_id=existing
        )
    item = InventoryItem(
        id=uuid.uuid4(),
        pharmacy_id=pharmacy_id,
        product_id=product_id,
        batch=batch.strip(),
        expiry_date=expiry_date,
        qty_on_hand=quantity,
        price_override_lbp=price_override_lbp,
        last_edited_at=tx.now,
    )
    tx.session.add(item)
    tx.session.flush()
    audit.record(
        tx,
        Actor.PHARMACY,
        "inventory.add",
        "inventory_item",
        item.id,
        actor_id=pharmacy_id,
        after={"qty_on_hand": quantity},
    )
    matching.defer_for_product(tx, product)
    return item


def edit_item(
    tx: Tx,
    pharmacy_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    quantity: int | None = None,
    price_override_lbp: Any = UNSET,
    listing_control: ListingControl | None = None,
) -> Edited:
    """A pharmacy corrects a quantity, sets or clears its own price, pauses or resumes."""
    _manage(tx, pharmacy_id)
    item = orders.lock_items(tx, [item_id]).get(item_id)
    if item is None or item.pharmacy_id != pharmacy_id:
        raise ServiceError(Code.NOT_FOUND, "Unknown inventory item.")
    product = tx.session.get_one(Product, item.product_id)
    before = {
        "qty_on_hand": item.qty_on_hand,
        "price_override_lbp": item.price_override_lbp,
        "listing_control": item.listing_control,
    }
    protected = False
    if quantity is not None:
        try:
            stock, protected = Stock(item.qty_on_hand, item.qty_reserved).set_on_hand(quantity)
        except ValueError:
            raise ServiceError(Code.VALIDATION_ERROR, "A quantity can't be negative.") from None
        item.qty_on_hand = stock.on_hand
    if price_override_lbp is not UNSET:
        _check_price(product, price_override_lbp)
        item.price_override_lbp = price_override_lbp
    if listing_control is not None:
        item.listing_control = listing_control.value
    item.last_edited_at = tx.now
    audit.record(
        tx,
        Actor.PHARMACY,
        "inventory.edit",
        "inventory_item",
        item.id,
        actor_id=pharmacy_id,
        before=before,
        after={
            "qty_on_hand": item.qty_on_hand,
            "price_override_lbp": item.price_override_lbp,
            "listing_control": item.listing_control,
            "reserved_kept": protected,
        },
    )
    if not product.controlled:
        matching.defer_for_product(tx, product)
    return Edited(item, protected)


# --- Uploads --------------------------------------------------------------------------


def _fail(reason: str) -> ServiceError:
    return ServiceError(Code.UPLOAD_FAILED, "This file can't be used.", reason=reason)


def _read_rows(content: bytes) -> list[dict[str, str]]:
    """The file's rows as dictionaries, or a refusal of the whole file (SM-4: FAILED)."""
    if len(content) > MAX_FILE_BYTES:
        raise ServiceError(Code.FILE_TOO_LARGE, "The file is larger than 5 MB.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _fail("not a CSV file saved as UTF-8") from None
    reader = csv.DictReader(io.StringIO(text))
    columns = [normalize(name or "") for name in reader.fieldnames or []]
    if not set(REQUIRED_COLUMNS) <= set(columns) or not set(columns) <= set(ALLOWED_COLUMNS):
        raise _fail("the columns must be: product, strength, batch, expiry, quantity")
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {
            normalize(key or ""): (value or "").strip()
            for key, value in raw.items()
            if key is not None
        }
        if not any(row.values()):
            continue
        if any(value.startswith(FORMULA_STARTS) for value in row.values()):
            raise _fail("the file contains formulas")
        rows.append(row)
        if len(rows) > MAX_ROWS:
            raise _fail("more than 10,000 rows")
    if not rows:
        raise _fail("the file has no rows")
    return rows


def _match_product(tx: Tx, name: str, strength: str) -> tuple[Product | None, dict[str, Any]]:
    """The catalog product a row names, or why not, with close names to suggest (R-C9)."""
    wanted = normalize(name)
    found = list(tx.session.execute(select(Product).where(Product.search_name == wanted)).scalars())
    if strength:
        compact = normalize(strength).replace(" ", "")
        found = [
            p for p in found if normalize(p.dosage_text or "").replace(" ", "") == compact
        ] or found
    if any(product.controlled for product in found):
        return None, {"problem": "this medicine can't be listed on DawaLink"}
    if len(found) == 1:
        return found[0], {}
    if len(found) > 1:
        strengths = sorted({p.dosage_text or "" for p in found})
        return None, {
            "problem": "several products have this name: add the strength",
            "strengths": strengths,
        }
    suggestions = catalog.search_products(tx, name, limit=3)
    names = [p.name for p in suggestions.products] or suggestions.did_you_mean
    return None, {"problem": "no product with this name", "did_you_mean": names}


def validate_upload(
    tx: Tx, pharmacy_id: uuid.UUID, user_id: uuid.UUID, file_name: str, content: bytes
) -> InventoryUpload:
    """Reads a stock file and stages its good rows. Nothing changes until [Apply] (SM-4).

    The file itself is never stored. A row with a problem is reported and never blocks the
    others (R-U5). A new upload replaces the one that was waiting.
    """
    _manage(tx, pharmacy_id)
    rows = _read_rows(content)

    waiting = tx.session.execute(
        select(InventoryUpload)
        .where(InventoryUpload.pharmacy_id == pharmacy_id, InventoryUpload.status == "VALIDATED")
        .with_for_update()
    ).scalar()
    if waiting is not None:
        tx.session.execute(
            delete(InventoryUploadRow).where(InventoryUploadRow.upload_id == waiting.id)
        )
        waiting.status = "DISCARDED"
        tx.session.flush()

    staged: dict[tuple[uuid.UUID, str, date], int] = {}
    errors: list[dict[str, Any]] = []
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        problem: dict[str, Any] = {}
        product, problem = _match_product(tx, row.get("product", ""), row.get("strength", ""))
        expiry: date | None = None
        quantity: int | None = None
        if product is not None:
            try:
                expiry = parse_expiry(row.get("expiry", ""))
            except ValueError:
                problem = {"problem": "the expiry must be YYYY-MM or YYYY-MM-DD"}
            else:
                if expiry < tx.today:
                    problem = {"problem": "this box has already expired"}
        if product is not None and not problem:
            if row.get("quantity", "").isdigit():
                quantity = int(row["quantity"])
            else:
                problem = {"problem": "the quantity must be a whole number, 0 or more"}
        if product is not None and not problem and not row.get("batch"):
            problem = {"problem": "the batch is missing"}
        if problem or product is None or expiry is None or quantity is None:
            if len(errors) < MAX_ERRORS_KEPT:
                errors.append({"row": number, "product": row.get("product", ""), **problem})
            continue
        key = (product.id, row["batch"], expiry)
        staged[key] = staged.get(key, 0) + quantity  # R-U1: duplicate keys are summed

    existing = {
        (item.product_id, item.batch, item.expiry_date): item
        for item in tx.session.execute(
            select(InventoryItem).where(InventoryItem.pharmacy_id == pharmacy_id)
        ).scalars()
    }
    summary = {
        "new": sum(1 for key in staged if key not in existing),
        "changed": sum(
            1 for key, qty in staged.items() if key in existing and existing[key].qty_on_hand != qty
        ),
        "zeroed": sum(
            1 for key, item in existing.items() if key not in staged and item.qty_on_hand > 0
        ),
        "reserved_kept": sum(
            1 for key, item in existing.items() if staged.get(key, 0) < item.qty_reserved
        ),
    }
    upload = InventoryUpload(
        id=uuid.uuid4(),
        pharmacy_id=pharmacy_id,
        status="VALIDATED",
        file_name=file_name,
        rows_total=len(rows),
        rows_ok=len(rows) - len(errors),
        rows_error=len(errors),
        summary=summary,
        errors=errors,
        created_by=user_id,
    )
    tx.session.add(upload)
    tx.session.flush()
    for row_no, ((product_id, batch, expiry), quantity) in enumerate(staged.items(), start=1):
        tx.session.add(
            InventoryUploadRow(
                upload_id=upload.id,
                row_no=row_no,
                product_id=product_id,
                batch=batch,
                expiry_date=expiry,
                quantity=quantity,
            )
        )
    tx.session.flush()
    return upload


def apply_upload(tx: Tx, pharmacy_id: uuid.UUID, upload_id: uuid.UUID) -> InventoryUpload:
    """[Apply]: the file becomes the pharmacy's stock, in one transaction (R-U1 to R-U4).

    A box missing from the file is set to 0 and kept. Price overrides and paused listings
    survive. Reserved units are never taken away.
    """
    _manage(tx, pharmacy_id)
    current = {
        (item.product_id, item.batch, item.expiry_date): item
        for item in orders.lock_items(
            tx,
            list(
                tx.session.execute(
                    select(InventoryItem.id).where(InventoryItem.pharmacy_id == pharmacy_id)
                ).scalars()
            ),
        ).values()
    }
    upload = tx.session.execute(
        select(InventoryUpload)
        .where(InventoryUpload.id == upload_id, InventoryUpload.pharmacy_id == pharmacy_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    if upload is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown upload.")
    if upload.status != "VALIDATED":
        raise ServiceError(Code.UPLOAD_NOT_VALIDATED, "This upload was replaced or discarded.")
    staged = {
        (row.product_id, row.batch, row.expiry_date): row.quantity
        for row in tx.session.execute(
            select(InventoryUploadRow).where(InventoryUploadRow.upload_id == upload.id)
        ).scalars()
    }
    protected = 0
    touched: set[uuid.UUID] = set()
    for key, quantity in staged.items():
        item = current.get(key)
        if item is None:
            product_id, batch, expiry = key
            tx.session.add(
                InventoryItem(
                    id=uuid.uuid4(),
                    pharmacy_id=pharmacy_id,
                    product_id=product_id,
                    batch=batch,
                    expiry_date=expiry,
                    qty_on_hand=quantity,
                    last_edited_at=tx.now,
                )
            )
        else:
            stock, was_protected = Stock(item.qty_on_hand, item.qty_reserved).set_on_hand(quantity)
            item.qty_on_hand, item.last_edited_at = stock.on_hand, tx.now
            protected += was_protected
        touched.add(key[0])
    for key, item in current.items():
        if key not in staged:
            stock, was_protected = Stock(item.qty_on_hand, item.qty_reserved).set_on_hand(0)
            item.qty_on_hand, item.last_edited_at = stock.on_hand, tx.now
            protected += was_protected
    tx.session.execute(delete(InventoryUploadRow).where(InventoryUploadRow.upload_id == upload.id))
    upload.status = "APPLIED"
    upload.applied_at = tx.now
    upload.summary = {**upload.summary, "reserved_kept": protected}
    audit.record(
        tx,
        Actor.PHARMACY,
        "inventory.upload_apply",
        "inventory_upload",
        upload.id,
        actor_id=pharmacy_id,
        before={"status": "VALIDATED"},
        after={"status": "APPLIED", "boxes": len(staged), "reserved_kept": protected},
    )
    for product in tx.session.execute(select(Product).where(Product.id.in_(touched))).scalars():
        matching.defer_for_product(tx, product)
    return upload
