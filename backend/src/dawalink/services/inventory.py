"""A pharmacy's stock: manual edits and file uploads (docs/04 SM-3, SM-4, R-U1 to R-U5).

Two rules run through everything here:
- **reserved units are protected** (R-U3): no edit or upload can take a box away from a
  client who reserved it. To give one up, the pharmacy presses [Not available];
- every change that can put stock on the shelf triggers matching (R-PRI1).
"""

import csv
import io
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Select, delete, func, or_, select
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
from dawalink.domain.expiry import (
    AmbiguousDate,
    Zone,
    day_month_order,
    days_left,
    parse_expiry_cell,
    zone_of,
)
from dawalink.domain.inventory import ListingControl, Stock
from dawalink.domain.numbers import MAX_BOX_QUANTITY, NEAR_EXPIRY_MAX_DAYS
from dawalink.domain.pharmacy_details import clean_batch
from dawalink.domain.pricing import is_valid_override
from dawalink.domain.state_machine import Actor
from dawalink.services import audit, catalog, matching, orders
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.paging import count_rows

MAX_FILE_BYTES = 5 * 1024 * 1024  # N-15
MAX_ROWS = 10_000  # N-15
MAX_ERRORS_KEPT = 500
REQUIRED_COLUMNS = ("product", "batch", "expiry", "quantity")
# `code` is the Ministry's own number for a product. It is only needed for a medicine
# whose name and strength the Ministry lists several times (other packs, other makers):
# the file of rows that weren't read gives the code of each choice (the owner, Q44).
ALLOWED_COLUMNS = (*REQUIRED_COLUMNS, "strength", "code")
COLUMNS_SENTENCE = (
    "the columns must be: product, strength, batch, expiry, quantity, and code if you use it"
)
# What the pharmacy downloads and fills in (PS-6). The two rows are invented examples.
TEMPLATE_CSV = (
    "product,strength,batch,expiry,quantity,code\r\n"
    "Example medicine,500mg,A123,2027-03,12,\r\n"
    # Months only: a spreadsheet leaves "2027-03" alone and rewrites a full date in the
    # computer's own style ("6/30/2027"), tried with Excel on 2026-11-16.
    "Another example,,B77,2027-06,4,\r\n"
)
# How many choices a refused row lists.
MAX_CHOICES = 8
# A spreadsheet saves "CSV" with a comma, or with a semicolon where the comma is the
# decimal sign, or with tabs.
DELIMITERS = (",", ";", "\t")
# A cell that starts like this is a formula in a spreadsheet: the file is refused (SM-4).
FORMULA_STARTS = ("=", "+", "@", "\t", "\r")
# A quantity and a code are plain digits 0 to 9, nothing else: `isdigit()` also takes
# "²", which `int()` then refuses. A quantity of more than six digits is past
# MAX_BOX_QUANTITY (a barcode in the quantity column), and is never turned into a number.
# No Ministry code is near 12 digits.
PLAIN_DIGITS = re.compile(r"[0-9]+")
QUANTITY_MAX_DIGITS = len(str(MAX_BOX_QUANTITY))
PLAIN_CODE = re.compile(r"[0-9]{1,12}")
NO_SUCH_NAME = "no product with this name"
UNSET: Any = object()


@dataclass(frozen=True)
class Edited:
    item: InventoryItem
    # The quantity was raised to keep what clients have reserved (R-U3).
    reserved_kept: bool


def can_manage(tx: Tx, pharmacy_id: uuid.UUID, *, lock: bool = False) -> Pharmacy:
    """Only an approved pharmacy has an inventory (P-D2).

    `lock` makes the pharmacy's other work of this kind wait for this transaction. It is
    FOR NO KEY UPDATE: a client reserving one of its boxes is never held up by it.
    """
    if lock:
        pharmacy = tx.session.execute(
            select(Pharmacy)
            .where(Pharmacy.id == pharmacy_id)
            .with_for_update(key_share=True)  # FOR NO KEY UPDATE on PostgreSQL
            .execution_options(populate_existing=True)
        ).scalar()
    else:
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
    """A pharmacy corrects a quantity, sets or clears its own price, pauses or resumes a
    box, or lists it by hand ([List now]) and takes that back."""
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
        # Between "paused" and "listed by hand" the box goes back to the rule first
        # (SM-3): each screen offers one way out of a state, and the API allows no other.
        if {ListingControl(item.listing_control), listing_control} == {
            ListingControl.PAUSED,
            ListingControl.LISTED,
        }:
            raise ServiceError(
                Code.VALIDATION_ERROR,
                "Give the box back to your rule first.",
                field="listed" if listing_control is ListingControl.LISTED else "paused",
            )
        if listing_control is ListingControl.LISTED:
            # By hand as by itself: only a box of the published window (N-1), in date.
            zone = zone_of(days_left(item.expiry_date, tx.today), eligible=not product.controlled)
            if zone is not Zone.NEAR_EXPIRY:
                raise ServiceError(
                    Code.VALIDATION_ERROR,
                    f"Only a box with {NEAR_EXPIRY_MAX_DAYS} days left or fewer can be listed.",
                    field="listed",
                )
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
    if b"\x00" in content or content.startswith(b"PK"):
        # An Excel workbook, or anything else that isn't text. A zero byte anywhere: no
        # text file has one, and the database can't store one.
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
        raise _fail(COLUMNS_SENTENCE)
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


def _choice(product: Product) -> str:
    """One of several medicines with the same name, as the errors file lists it: what
    tells it apart (its form, its pack, its maker), then the code to copy into the file.

    A pack the Ministry writes as a bare number ("30") is said as "Pack: 30", as the
    website says it: after a form it would read as part of it ("Tablet, film coated 30").
    """
    pack = (product.presentation_text or "").strip()
    if pack.isascii() and pack.isdigit():
        pack = f"Pack: {pack}"
    what = " ".join(filter(None, (product.form_text, pack)))
    told_apart = ", ".join(filter(None, (what, product.manufacturer)))
    return f"{told_apart or product.moph_name}: code {product.moph_code}"


def _products_named(tx: Tx, rows: list[dict[str, str]]) -> dict[str, list[Product]]:
    """The catalog's products for every name the file uses, in one query: a file of
    10,000 rows must not cost 10,000 questions to the database (N-15)."""
    names = {normalize(row.get("product", "")) for row in rows} - {""}
    by_name: dict[str, list[Product]] = {}
    if names:
        for product in tx.session.execute(
            select(Product).where(Product.search_name.in_(names))
        ).scalars():
            by_name.setdefault(product.search_name, []).append(product)
    return by_name


# How a strength's numbers are written. The Ministry groups thousands with a comma
# ("100,000 IU"); a spreadsheet set to French writes the decimal point as a comma
# ("2,5 mg", in a file saved with semicolons).
_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")
_BARE_POINT = re.compile(r"(?<!\d)\.(?=\d)")
_STRENGTH_PARTS = re.compile(r"\d+(?:\.\d+)?|[a-z]+")


def _strength_key(text: str) -> str:
    """A strength as two strengths are compared: "2.5 mg", "2.5MG", "2,5mg" and "2.50 mg"
    are one strength, **"25 mg" is another**. A number keeps its decimal point; capitals,
    spaces and every other sign only separate the parts, so "5mg/5ml" matches
    "5 mg / 5 ml" and "100,000 IU" matches "100000 IU".

    Before, every sign was dropped, so 2.5 mg and 25 mg were the same strength.
    """
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    plain = _THOUSANDS_COMMA.sub("", plain.lower())
    plain = _DECIMAL_COMMA.sub(".", plain)
    plain = _BARE_POINT.sub("0.", plain)  # ".5 mg" is 0.5 mg, never 5 mg
    key = ""
    for part in _STRENGTH_PARTS.findall(plain):
        # Two numbers in a row stay apart ("1/25" is not "12/5"); words are joined, as
        # they were before, so "mg/ml" is "mgml".
        if key and key[-1].isdigit() and part[0].isdigit():
            key += " "
        key += _plain_number(part)
    return key


def _plain_number(part: str) -> str:
    """A number without the zeros that change nothing after its point: "2.50" is "2.5",
    "2.0" is "2". A word is left as it is."""
    if "." not in part or not part[0].isdigit():
        return part
    return part.rstrip("0").rstrip(".")


def _match_product(
    by_name: list[Product], strength: str, code: str = ""
) -> tuple[Product | None, dict[str, Any]]:
    """The catalog product a row names, or why not (R-C9). `by_name` is every product
    whose name is the row's. Close names to suggest for an unknown one are the caller's.

    **A code chooses among the products the name already matches; it never replaces the
    name.** A mistyped code would otherwise put another medicine on the shelf, at another
    price, without anyone seeing it: the row has to say the same thing twice.
    """
    found = list(by_name)
    # A row's strength that no product of that name has: without a code it is taken as a
    # slip of the pen when the name is enough by itself. With a code it is a
    # contradiction, and the row is refused: the code may not overrule what the row says.
    strength_is_wrong = False
    if strength:
        wanted = _strength_key(strength)
        with_it = [p for p in by_name if _strength_key(p.dosage_text or "") == wanted]
        strength_is_wrong = not with_it
        found = with_it or by_name
    if any(product.controlled for product in found):
        return None, {"problem": "this medicine can't be listed on DawaLink"}
    if code and found:
        named = [
            p
            for p in found
            # Plain digits only: "²" passes `isdigit()` and then breaks `int()`.
            if not strength_is_wrong and PLAIN_CODE.fullmatch(code) and p.moph_code == int(code)
        ]
        if named:
            return named[0], {}
        found.sort(key=lambda p: p.moph_code)
        return None, {
            "problem": "this code is not the code of a medicine with this name and "
            "strength: check both",
            "did_you_mean": [_choice(p) for p in found[:MAX_CHOICES]],
        }
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
        # other makers, each with its own price. The name can't say which one, and a
        # guess would put the wrong price on the box: the code says it.
        found.sort(key=lambda p: p.moph_code)
        return None, {
            "problem": "several medicines have this name and strength (other packs or "
            "makers): write the code of yours in the code column, or add this box by hand",
            "did_you_mean": [_choice(p) for p in found[:MAX_CHOICES]],
        }
    return None, {"problem": NO_SUCH_NAME}


class _CloseNames:
    """The "did you mean" of an unknown name, asked once per name in one upload.

    A fuzzy search costs about 50 ms on the real catalog, and a file in the pharmacy's
    own names may have thousands of them (BLD-D44, Q65): asked for every row, a large
    file took minutes, past the API's time limit.
    """

    def __init__(self, tx: Tx) -> None:
        self._tx = tx
        self._known: dict[str, list[str]] = {}

    def of(self, name: str) -> list[str]:
        key = normalize(name)
        if key not in self._known:
            found = catalog.search_products(self._tx, name, limit=3)
            self._known[key] = [p.name for p in found.products] or found.did_you_mean
        return self._known[key]


def _quantity(cell: str) -> int | str:
    """A row's quantity, or what is wrong with it."""
    if not PLAIN_DIGITS.fullmatch(cell):
        return "the quantity must be a whole number, 0 or more"
    digits = cell.lstrip("0") or "0"
    if len(digits) > QUANTITY_MAX_DIGITS or int(digits) > MAX_BOX_QUANTITY:
        return f"the quantity must be {MAX_BOX_QUANTITY:,} or fewer"
    return int(digits)


def needs_a_code(tx: Tx, product_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """Of these products, the ones a name and a strength don't identify: the Ministry
    lists them several times (other packs, other makers). A file names one only with
    the `code` column; without it the row is refused and the box is added by hand.

    **Such a box is changed by a row that names it, never by its absence** (the
    exception to R-U2). A pharmacy whose files have no codes keeps these boxes by hand,
    and its next file must not erase them. A pharmacy that does use codes writes the row
    with quantity 0 when the box is gone. The count of boxes left alone is in the
    upload's summary, so nobody takes them for updated.
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

    staged: dict[tuple[uuid.UUID, str, date], int] = {}
    errors: list[dict[str, Any]] = []
    rows_error = 0
    # "3/31/2027" or "31/03/2027"? Read only if the file's own dates show which (FI-20).
    order = day_month_order(row.get("expiry", "") for row in rows)
    products_named = _products_named(tx, rows)
    close_names = _CloseNames(tx)
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        problem: dict[str, Any] = {}
        product, problem = _match_product(
            products_named.get(normalize(row.get("product", "")), []),
            row.get("strength", ""),
            row.get("code", ""),
        )
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
            read = _quantity(row.get("quantity", ""))
            if isinstance(read, str):
                problem = {"problem": read}
            else:
                quantity = read
        if product is not None and not problem:
            try:
                batch = clean_batch(row.get("batch", ""))
            except ValueError:
                problem = {
                    "problem": "the batch is missing"
                    if not row.get("batch")
                    else "the batch must be letters and digits, as printed on the box"
                }
        # R-U1: rows for the same box are added up, and the sum is a box's quantity too.
        # The row that would take the sum over the most is refused; the ones above stand.
        if (
            product is not None
            and expiry is not None
            and quantity is not None
            and not problem
            and staged.get((product.id, batch, expiry), 0) + quantity > MAX_BOX_QUANTITY
        ):
            problem = {
                "problem": "with the rows above for the same box, the quantity is more "
                f"than {MAX_BOX_QUANTITY:,}"
            }
        if problem or product is None or expiry is None or quantity is None:
            rows_error += 1
            if len(errors) < MAX_ERRORS_KEPT:
                if problem.get("problem") == NO_SUCH_NAME:
                    # Only for the rows that are shown: the search is the slow part.
                    problem = {**problem, "did_you_mean": close_names.of(row.get("product", ""))}
                # Only the start of what was typed is kept, to show which row it was.
                errors.append({"row": number, "product": row.get("product", "")[:80], **problem})
            continue
        key = (product.id, batch, expiry)
        staged[key] = staged.get(key, 0) + quantity

    # The same file sent twice at once (a double click, a retry): the second waits here
    # for the first, then replaces it. Otherwise both see no file waiting, and the second
    # breaks the rule of one waiting file per pharmacy with a server error. Taken only
    # now, after the slow reading, so nothing else of the pharmacy's waits on it long.
    can_manage(tx, pharmacy_id, lock=True)
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

    existing = {
        (item.product_id, item.batch, item.expiry_date): item
        for item in tx.session.execute(
            select(InventoryItem).where(InventoryItem.pharmacy_id == pharmacy_id)
        ).scalars()
    }
    beyond = needs_a_code(tx, {key[0] for key in existing})
    # What the file doesn't name is set to 0, except a box that only a code can name.
    absent = [item for key, item in existing.items() if key not in staged]
    dropped = [item for item in absent if item.product_id not in beyond]
    summary = {
        # In stock, absent from the file, and left as they are (R-U2's exception).
        "left_alone": sum(
            1 for item in absent if item.product_id in beyond and item.qty_on_hand > 0
        ),
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
    survive. Reserved units are never taken away. **A box that only a code can name is
    changed by a row that names it, never by its absence** (`needs_a_code`).
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
    beyond = needs_a_code(tx, {key[0] for key in current})
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


# The orders of the stock's list: the soonest expiry first, or one medicine's boxes side
# by side (two batches of one medicine, each with its own expiry), the soonest first.
STOCK_SORTS = ("expiry", "medicine")


def stock_lines(
    tx: Tx,
    pharmacy_id: uuid.UUID,
    *,
    query: str = "",
    zone: Zone | None = None,
    item_ids: list[uuid.UUID] | None = None,
    sort: str = "expiry",
    offset: int = 0,
    limit: int = 50,
) -> list[StockLine]:
    """The pharmacy's boxes, soonest expiry first, or by medicine (`STOCK_SORTS`).
    Private: only the pharmacy reads this."""
    days = InventoryItem.expiry_date - tx.today
    statement = _stock_filtered(
        select(
            InventoryItem,
            Product,
            days,
            func.expiry_zone(days, Product.controlled.is_(False)),
            func.effective_price_lbp(
                Product.public_price_lbp, InventoryItem.price_override_lbp, days
            ),
            func.effective_price_lbp(Product.public_price_lbp, None, days),
        ),
        tx,
        pharmacy_id,
        query=query,
        zone=zone,
        item_ids=item_ids,
    )
    if sort == "medicine":
        statement = statement.order_by(
            Product.moph_name, Product.id, InventoryItem.expiry_date, InventoryItem.id
        )
    else:
        statement = statement.order_by(
            InventoryItem.expiry_date, Product.moph_name, InventoryItem.id
        )
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


def count_stock(
    tx: Tx, pharmacy_id: uuid.UUID, *, query: str = "", zone: Zone | None = None
) -> int:
    """How many boxes `stock_lines` lists with these choices, on every page: the same
    filters, counted (the "134 in all" under the list)."""
    return count_rows(
        tx, _stock_filtered(select(InventoryItem.id), tx, pharmacy_id, query=query, zone=zone)
    )


def _stock_filtered(
    statement: Select[Any],
    tx: Tx,
    pharmacy_id: uuid.UUID,
    *,
    query: str,
    zone: Zone | None,
    item_ids: list[uuid.UUID] | None = None,
) -> Select[Any]:
    """The pharmacy's boxes that the choices keep, in one place for the list and its
    count, so that the two never disagree about what a choice means."""
    days = InventoryItem.expiry_date - tx.today
    zone_now = func.expiry_zone(days, Product.controlled.is_(False))
    statement = statement.join(Product, Product.id == InventoryItem.product_id).where(
        InventoryItem.pharmacy_id == pharmacy_id
    )
    if item_ids is not None:
        statement = statement.where(InventoryItem.id.in_(item_ids))
    typed = query.strip().lower()
    if typed:
        # A batch is searched as typed (`%` and `_` are only themselves); a medicine's
        # name by its letters and digits, when the text has any.
        in_the_batch = func.lower(InventoryItem.batch).contains(typed, autoescape=True)
        wanted = normalize(query)
        statement = statement.where(
            or_(Product.search_name.contains(wanted), in_the_batch) if wanted else in_the_batch
        )
    if zone is not None:
        statement = statement.where(zone_now == zone.value)
    return statement
