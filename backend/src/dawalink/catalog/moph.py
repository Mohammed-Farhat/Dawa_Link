"""Reads the Ministry of Public Health's two sources and joins them into one catalog file.

- The **price list** (.xls) is the list of products: the Ministry's code, registration
  number, name, strength, pack, form, manufacturer and public price.
- The **Lebanon National Drugs Database** pages add what the price list lacks: the ATC
  code, brand or generic, and the ingredients with their strengths.

The two have no common key, so a product is matched by its name and price, then by its
strength and form. A product that can't be matched safely is left out and counted.
"""

import csv
import html
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from dawalink.catalog.composition import normalize, parse_ingredients

_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL = re.compile(r'<a href="/en/Drugs/view/(\d+)"[^>]*class="drugLink">(.*?)</a>', re.S)
_MARKUP = re.compile(r"<!--.*?-->|<[^>]+>", re.S)
_EXCEL_DAY_ZERO = date(1899, 12, 30)
PRICE_LIST_COLUMNS = (
    "Code",
    "Registration number",
    "Brand name",
    "Strength",
    "Presentation",
    "Form",
    "Agent",
    "Manufacturer",
    "Country",
    "Public Price LL",
)


@dataclass(frozen=True)
class PriceRow:
    """One product on the price list."""

    code: int
    registration_number: str
    name: str
    strength: str
    presentation: str
    form: str
    manufacturer: str
    price_lbp: int


@dataclass(frozen=True)
class DatabaseRow:
    """One row of the Lebanon National Drugs Database."""

    atc: str
    name: str
    brand_generic: str
    ingredients: str
    dosage: str
    form: str
    price_lbp: int | None


@dataclass(frozen=True)
class CatalogRow:
    """One product ready to import: the price list's row with the database's details."""

    code: int
    registration_number: str
    name: str
    strength: str
    presentation: str
    form: str
    manufacturer: str
    price_lbp: int
    atc: str
    brand_generic: str
    ingredients: str


@dataclass(frozen=True)
class PriceList:
    rows: list[PriceRow]
    rows_total: int
    source_date: date | None
    lbp_per_usd: Decimal | None


@dataclass(frozen=True)
class JoinReport:
    matched: int
    not_found: int
    unclear: int


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def price_list_from_rows(header: Sequence[object], rows: Iterable[Sequence[object]]) -> PriceList:
    """The price list from the sheet's cells. Rows without a price or a code are left out."""
    names = [_text(cell) for cell in header]
    if tuple(names[: len(PRICE_LIST_COLUMNS)]) != PRICE_LIST_COLUMNS:
        raise ValueError("The price list's columns have changed: " + ", ".join(names))
    usd_column = next((i for i, n in enumerate(names) if n.startswith("public price")), None)
    date_column = names.index("Exch_Dates") if "Exch_Dates" in names else None

    products: list[PriceRow] = []
    total = 0
    source_date: date | None = None
    rates: list[Decimal] = []
    for row in rows:
        total += 1
        code, price = row[0], row[9]
        if not isinstance(code, int | float) or not isinstance(price, int | float) or price <= 0:
            continue
        products.append(
            PriceRow(
                code=int(code),
                registration_number=_text(row[1]),
                name=_text(row[2]),
                strength=_text(row[3]),
                presentation=_text(row[4]),
                form=_text(row[5]),
                manufacturer=_text(row[7]),
                price_lbp=round(price),
            )
        )
        if usd_column is not None and isinstance(row[usd_column], int | float) and row[usd_column]:
            rates.append(Decimal(str(price)) / Decimal(str(row[usd_column])))
        if date_column is not None and isinstance(day := row[date_column], int | float):
            source_date = _EXCEL_DAY_ZERO + timedelta(days=int(day))
    rate = sorted(rates)[len(rates) // 2].quantize(Decimal("0.01")) if rates else None
    return PriceList(products, total, source_date, rate)


def read_price_list(path: Path) -> PriceList:
    import xlrd  # only this command needs it

    sheet = xlrd.open_workbook(str(path)).sheet_by_index(0)
    return price_list_from_rows(
        sheet.row_values(0), (sheet.row_values(r) for r in range(1, sheet.nrows))
    )


def database_rows_from_html(page: str) -> list[DatabaseRow]:
    """The rows of one page of the database's listing."""
    rows: list[DatabaseRow] = []
    for row in _ROW.findall(page):
        cells = [html.unescape(_MARKUP.sub("", cell)).strip() for _, cell in _CELL.findall(row)]
        if len(cells) != 7:
            continue
        digits = re.sub(r"\D", "", cells[6])
        rows.append(
            DatabaseRow(
                atc=_text(cells[0]),
                name=_text(cells[1]),
                brand_generic=_text(cells[2]),
                ingredients=_text(cells[3]),
                dosage=_text(cells[4]),
                form=_text(cells[5]),
                price_lbp=int(digits) if digits else None,
            )
        )
    return rows


def read_database_pages(folder: Path) -> list[DatabaseRow]:
    rows: list[DatabaseRow] = []
    for page in sorted(folder.glob("page_*.html")):
        rows.extend(database_rows_from_html(page.read_text(encoding="utf-8", errors="replace")))
    return rows


def _compact(text: str) -> str:
    """For comparing two spellings: "500 mg" and "500mg" are the same."""
    return normalize(text).replace(" ", "")


def _strengths(row: DatabaseRow) -> set[str]:
    """How a row's strength may be written: its dosage, or its ingredients' strengths in order
    ("5mg/160mg" for "Amlodipine - 5mg, Valsartan - 160mg")."""
    combined = "/".join(i.strength_text or "" for i in parse_ingredients(row.ingredients))
    return {_compact(row.dosage), _compact(combined)} - {""}


def _details(row: DatabaseRow) -> tuple[str, str, str]:
    return (row.atc, row.brand_generic, row.ingredients)


def _match(product: PriceRow, candidates: list[DatabaseRow]) -> DatabaseRow | str:
    """The database row for a product, or why there is none: "not found" or "unclear"."""
    if not candidates:
        return "not found"
    strength, form = _compact(product.strength), _compact(product.form)

    def narrowed(pool: list[DatabaseRow]) -> list[DatabaseRow]:
        """Keep the rows with the same strength, then the same form, where any have them."""
        pool = [c for c in pool if strength and strength in _strengths(c)] or pool
        return [c for c in pool if form and _compact(c.form) == form] or pool

    # The two sources round a price differently, so 1 LBP apart is the same price.
    same_price = [
        c for c in candidates if c.price_lbp and abs(c.price_lbp - product.price_lbp) <= 1
    ]
    chosen = narrowed(same_price)
    if not chosen:
        chosen = narrowed(candidates)
        if chosen is candidates and len(candidates) > 1:
            # Only the name matches, and several rows carry it: not enough to go on.
            return "unclear"
    # Several rows are fine when they say the same thing (one medicine in several packs).
    # Otherwise we can't tell which of them this product is.
    return chosen[0] if len({_details(c) for c in chosen}) == 1 else "unclear"


def join(
    products: Iterable[PriceRow], database: Iterable[DatabaseRow]
) -> tuple[list[CatalogRow], JoinReport]:
    by_name: dict[str, list[DatabaseRow]] = defaultdict(list)
    for row in database:
        by_name[normalize(row.name)].append(row)

    catalog: list[CatalogRow] = []
    not_found = unclear = 0
    for product in products:
        match = _match(product, by_name.get(normalize(product.name), []))
        if match == "not found":
            not_found += 1
        elif isinstance(match, str):
            unclear += 1
        else:
            catalog.append(
                CatalogRow(
                    code=product.code,
                    registration_number=product.registration_number,
                    name=product.name,
                    strength=product.strength,
                    presentation=product.presentation,
                    # The database names forms in one consistent way; the price list often
                    # leaves the form empty or writes it freely, sometimes in French.
                    form=match.form or product.form,
                    manufacturer=product.manufacturer,
                    price_lbp=product.price_lbp,
                    atc=match.atc,
                    brand_generic=match.brand_generic,
                    ingredients=match.ingredients,
                )
            )
    return catalog, JoinReport(len(catalog), not_found, unclear)


def write_catalog(path: Path, rows: Iterable[CatalogRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=[f.name for f in fields(CatalogRow)])
        writer.writeheader()
        for row in sorted(rows, key=lambda r: r.code):
            writer.writerow(asdict(row))


def read_catalog(path: Path) -> list[CatalogRow]:
    with path.open(encoding="utf-8", newline="") as file:
        return [
            CatalogRow(
                code=int(row["code"]),
                registration_number=row["registration_number"],
                name=row["name"],
                strength=row["strength"],
                presentation=row["presentation"],
                form=row["form"],
                manufacturer=row["manufacturer"],
                price_lbp=int(row["price_lbp"]),
                atc=row["atc"],
                brand_generic=row["brand_generic"],
                ingredients=row["ingredients"],
            )
            for row in csv.DictReader(file)
        ]
