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

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import aliased

from dawalink.catalog.composition import normalize
from dawalink.db.models import (
    InventoryItem,
    InventoryUpload,
    InventoryUploadRow,
    Pharmacy,
    Product,
)
from dawalink.domain.accounts import PharmacyStatus, pharmacy_can_manage_inventory
from dawalink.domain.expiry import AmbiguousDate, Zone, day_month_order, parse_expiry_cell
from dawalink.domain.inventory import ListingControl, Stock
from dawalink.domain.pharmacy_details import clean_batch
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
# What the pharmacy downloads and fills in (PS-6). The two rows are invented examples.
TEMPLATE_CSV = (
    "product,strength,batch,expiry,quantity\r\n"
    "Example medicine,500mg,A123,2027-03,12\r\n"
    # Months only: a spreadsheet leaves "2027-03" alone and rewrites a full date in the
    # computer's own style ("6/30/2027"), tried with Excel on 2026-11-16.
    "Another example,,B77,2027-06,4\r\n"
)
# A spreadsheet saves "CSV" with a comma, or with a semicolon where the comma is the
# decimal sign, or with tabs.
DELIMITERS = (",", ";", "\t")
# A cell that starts like this is a formula in a spreadsheet: the file is refused (SM-4).
FORMULA_STARTS = ("=", "+", "@", "\t", "\r")
UNSET: Any = object()


@dataclass(frozen=True)
class Edited:
    item: InventoryItem
    # The quantity was raised to keep what clients have reserved (R-U3).
    reserved_kept: bool


def can_manage(tx: Tx, pharmacy_id: uuid.UUID) -> Pharmacy:
    """Only an approved pharmacy has an inventory (P-D2)."""
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
    can_manage(tx, pharmacy_id)
    product = catalog.allowed_product(tx, product_id)
    try:
        batch = clean_batch(batch)
    except ValueError as problem:
        raise ServiceError(Code.VALIDATION_ERROR, str(problem), field="batch") from None
    if quantity < 0 or expiry_date < tx.today:
        raise ServiceError(
            Code.VALIDATION_ERROR, "A box needs a quantity and an expiry that hasn't passed."
        )
    _check_price(product, price_override_lbp)
    existing = tx.session.execute(
        select(InventoryItem.id).where(
            InventoryItem.pharmacy_id == pharmacy_id,
            InventoryItem.product_id == product_id,
            InventoryItem.batch == batch,
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
        batch=batch,
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
    can_manage(tx, pharmacy_id)
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
    if b"\x00" in content[:4096] or content.startswith(b"PK"):
        # An Excel workbook, or anything else that isn't text.
        raise _fail("not a CSV file: in Excel, use File > Save As > CSV")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel's plain "CSV" on Windows. Product names are plain letters, so the
        # Western code page reads them right.
        text = content.decode("cp1252", errors="replace")
    first_line = text.split("\n", 1)[0]
    reader = None
    for delimiter in DELIMITERS:
        candidate = [normalize(name) for name in first_line.split(delimiter)]
        named = {name for name in candidate if name}
        if set(REQUIRED_COLUMNS) <= named <= set(ALLOWED_COLUMNS):
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            break
    if reader is None:
        raise _fail("the columns must be: product, strength, batch, expiry, quantity")
    rows: list[dict[str, str]] = []
    for raw in reader:
        row = {
            normalize(key): (value or "").strip()
            for key, value in raw.items()
            # A spreadsheet may add empty columns after the last one.
            if key is not None and normalize(key) and isinstance(value, str | None)
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
        if len(strengths) > 1:
            return None, {
                "problem": "several products have this name: add the strength",
                "strengths": strengths,
            }
        # The Ministry lists this name and strength several times: other pack sizes,
        # other makers, each with its own price. A file can't say which one, and a
        # guess would put the wrong price on the box.
        packs = sorted({" ".join(filter(None, (p.form_text, p.presentation_text))) for p in found})
        return None, {
            "problem": "several medicines have this name and strength (other packs or "
            "makers): add this box by hand, choosing it from the list",
            "did_you_mean": [pack for pack in packs if pack][:5],
        }
    suggestions = catalog.search_products(tx, name, limit=3)
    names = [p.name for p in suggestions.products] or suggestions.did_you_mean
    return None, {"problem": "no product with this name", "did_you_mean": names}


def no_file_can_name(tx: Tx, product_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Of these products, the ones a stock file has no way to point at: the Ministry
    lists their name and strength several times (other packs, other makers), and a file
    has a name and a strength only.

    Their rows are refused when a file is read, and the pharmacy adds such a box by
    hand. So a file must not set it to 0 for "not being in the file" (R-U2): it never
    can be in one.
    """
    if not product_ids:
        return set()
    twin = aliased(Product)
    return set(
        tx.session.execute(
            select(Product.id).where(
                Product.id.in_(product_ids),
                select(twin.id)
                .where(
                    twin.id != Product.id,
                    twin.search_name == Product.search_name,
                    func.coalesce(twin.dosage_text, "") == func.coalesce(Product.dosage_text, ""),
                )
                .exists(),
            )
        ).scalars()
    )


def validate_upload(
    tx: Tx, pharmacy_id: uuid.UUID, user_id: uuid.UUID, file_name: str, content: bytes
) -> InventoryUpload:
    """Reads a stock file and stages its good rows. Nothing changes until [Apply] (SM-4).

    The file itself is never stored. A row with a problem is reported and never blocks the
    others (R-U5). A new upload replaces the one that was waiting.
    """
    can_manage(tx, pharmacy_id)
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
    rows_error = 0
    # "3/31/2027" or "31/03/2027"? Read only if the file's own dates show which (FI-20).
    order = day_month_order(row.get("expiry", "") for row in rows)
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        problem: dict[str, Any] = {}
        product, problem = _match_product(tx, row.get("product", ""), row.get("strength", ""))
        expiry: date | None = None
        quantity: int | None = None
        batch = ""
        if product is not None:
            try:
                expiry = parse_expiry_cell(row.get("expiry", ""), order)
            except AmbiguousDate:
                problem = {
                    "problem": "this date can be read two ways, and no date in the file "
                    "shows which: write the expiry as the month and the year (03/2027)"
                }
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
        if product is not None and not problem:
            try:
                batch = clean_batch(row.get("batch", ""))
            except ValueError:
                problem = {
                    "problem": "the batch is missing"
                    if not row.get("batch")
                    else "the batch must be letters and digits, as printed on the box"
                }
        if problem or product is None or expiry is None or quantity is None:
            rows_error += 1
            if len(errors) < MAX_ERRORS_KEPT:
                # Only the start of what was typed is kept, to show which row it was.
                errors.append({"row": number, "product": row.get("product", "")[:80], **problem})
            continue
        key = (product.id, batch, expiry)
        staged[key] = staged.get(key, 0) + quantity  # R-U1: duplicate keys are summed

    existing = {
        (item.product_id, item.batch, item.expiry_date): item
        for item in tx.session.execute(
            select(InventoryItem).where(InventoryItem.pharmacy_id == pharmacy_id)
        ).scalars()
    }
    beyond = no_file_can_name(tx, {key[0] for key in existing})
    # What the file doesn't name is set to 0, except what no file could name.
    dropped = [item for key, item in existing.items() if key not in staged and key[0] not in beyond]
    summary = {
        "new": sum(1 for key in staged if key not in existing),
        "changed": sum(
            1 for key, qty in staged.items() if key in existing and existing[key].qty_on_hand != qty
        ),
        "zeroed": sum(1 for item in dropped if item.qty_on_hand > 0),
        "reserved_kept": sum(1 for item in dropped if item.qty_reserved > 0)
        + sum(
            1 for key, qty in staged.items() if key in existing and qty < existing[key].qty_reserved
        ),
    }
    upload = InventoryUpload(
        id=uuid.uuid4(),
        pharmacy_id=pharmacy_id,
        status="VALIDATED",
        file_name=file_name,
        rows_total=len(rows),
        rows_ok=len(rows) - rows_error,
        rows_error=rows_error,
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
    survive. Reserved units are never taken away. **A box that no file can name stays as
    it is** (`no_file_can_name`): it was added by hand because it had to be.
    """
    can_manage(tx, pharmacy_id)
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
    beyond = no_file_can_name(tx, {key[0] for key in current})
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
        if key not in staged and key[0] not in beyond:
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


def waiting_upload(tx: Tx, pharmacy_id: uuid.UUID) -> InventoryUpload | None:
    """The file that was read and waits for [Apply] or [Discard], if there is one."""
    return tx.session.execute(
        select(InventoryUpload).where(
            InventoryUpload.pharmacy_id == pharmacy_id, InventoryUpload.status == "VALIDATED"
        )
    ).scalar()


def own_upload(tx: Tx, pharmacy_id: uuid.UUID, upload_id: uuid.UUID) -> InventoryUpload:
    upload = tx.session.execute(
        select(InventoryUpload).where(
            InventoryUpload.id == upload_id, InventoryUpload.pharmacy_id == pharmacy_id
        )
    ).scalar()
    if upload is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown upload.")
    return upload


def discard_upload(tx: Tx, pharmacy_id: uuid.UUID, upload_id: uuid.UUID) -> None:
    """[Discard]: the staged rows go, and the stock stays as it was (SM-4)."""
    can_manage(tx, pharmacy_id)
    upload = tx.session.execute(
        select(InventoryUpload)
        .where(InventoryUpload.id == upload_id, InventoryUpload.pharmacy_id == pharmacy_id)
        .with_for_update()
    ).scalar()
    if upload is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown upload.")
    if upload.status != "VALIDATED":
        raise ServiceError(Code.UPLOAD_NOT_VALIDATED, "This upload was replaced or discarded.")
    tx.session.execute(delete(InventoryUploadRow).where(InventoryUploadRow.upload_id == upload.id))
    upload.status = "DISCARDED"


def _safe_cell(value: Any) -> str:
    """A cell that a spreadsheet won't run as a formula (docs/09 FS-10): what the pharmacy
    typed in its file comes back in this one."""
    text = str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def errors_csv(upload: InventoryUpload) -> str:
    """The rows that weren't read, to correct in a spreadsheet and upload again."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["row", "product", "problem", "did you mean"])
    for error in upload.errors:
        hints = error.get("did_you_mean") or error.get("strengths") or []
        writer.writerow(
            [
                error.get("row", ""),
                _safe_cell(error.get("product", "")),
                _safe_cell(error.get("problem", "")),
                _safe_cell(" | ".join(str(hint) for hint in hints)),
            ]
        )
    return out.getvalue()


# --- Reading the stock ----------------------------------------------------------------


@dataclass(frozen=True)
class StockLine:
    """One box of the pharmacy's stock, with what is computed from it today: its zone and
    its price are never stored (R-T9)."""

    item: InventoryItem
    product: Product
    days_left: int
    zone: Zone
    # What a client pays today, when the box is in the published window.
    price_lbp: int | None
    # The system's price for it, whatever the pharmacy's own price is.
    system_price_lbp: int | None


def stock_lines(
    tx: Tx,
    pharmacy_id: uuid.UUID,
    *,
    query: str = "",
    zone: Zone | None = None,
    item_ids: list[uuid.UUID] | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[StockLine]:
    """The pharmacy's boxes, soonest expiry first. Private: only the pharmacy reads this."""
    days = InventoryItem.expiry_date - tx.today
    zone_now = func.expiry_zone(days, Product.controlled.is_(False))
    statement = (
        select(
            InventoryItem,
            Product,
            days,
            zone_now,
            func.effective_price_lbp(
                Product.public_price_lbp, InventoryItem.price_override_lbp, days
            ),
            func.effective_price_lbp(Product.public_price_lbp, None, days),
        )
        .join(Product, Product.id == InventoryItem.product_id)
        .where(InventoryItem.pharmacy_id == pharmacy_id)
        .order_by(InventoryItem.expiry_date, Product.moph_name, InventoryItem.id)
    )
    if item_ids is not None:
        statement = statement.where(InventoryItem.id.in_(item_ids))
    wanted = normalize(query)
    if wanted:
        statement = statement.where(
            or_(
                Product.search_name.contains(wanted),
                func.lower(InventoryItem.batch).contains(query.strip().lower()),
            )
        )
    if zone is not None:
        statement = statement.where(zone_now == zone.value)
    return [
        StockLine(
            item=item,
            product=product,
            days_left=int(left),
            zone=Zone(zone_text),
            price_lbp=int(price) if price is not None and zone_text == Zone.NEAR_EXPIRY else None,
            system_price_lbp=int(system) if system is not None else None,
        )
        for item, product, left, zone_text, price, system in tx.session.execute(
            statement.offset(offset).limit(limit)
        )
    ]
