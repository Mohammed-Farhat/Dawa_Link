"""Loading the catalog into the database (docs/04 R-C1 to R-C8). All data here is invented."""

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from dawalink.catalog.importer import ImportResult, import_catalog
from dawalink.catalog.moph import CatalogRow
from dawalink.catalog.rules import CatalogRules, rules_from
from tests.db import factories as make

RULES = rules_from(
    {
        "controlled": {"atc_prefixes": ["N02A"], "ingredients": ["codeine"]},
        "otc": {"ingredients": ["paracetamol"]},
        "products": {"504": {"equivalence_key": "", "units_per_pack": 2}},
    }
)


def row(code: int, name: str, ingredients: str, price: int = 500_000, **values: Any) -> CatalogRow:
    defaults = {
        "registration_number": "1/1",
        "strength": "500mg",
        "presentation": "20",
        "form": "Tablet",
        "manufacturer": "Maker",
        "atc": "N02BE01",
        "brand_generic": "G",
    }
    return CatalogRow(
        code=code, name=name, ingredients=ingredients, price_lbp=price, **(defaults | values)
    )


ROWS = [
    row(501, "TESTAMOL", "Paracetamol - 500mg", brand_generic="B"),
    row(502, "PARATEST", "Paracetamol - 500mg", form="Tablet, film coated"),
    row(503, "CODATEST", "Paracetamol - 500mg, Codeine phosphate - 30mg", atc="N02AJ06"),
    row(504, "TESTAPRIL", "Enalapril - 5mg", atc="C09AA02"),
    row(505, "ODDTEST", "Something unreadable", form="", brand_generic=""),
]


def run_import(db: Connection, rows: list[CatalogRow], rules: CatalogRules = RULES) -> ImportResult:
    return import_catalog(
        db,
        rows,
        rules,
        file_name="WebMarketed-test.xls",
        source_date=date(2026, 11, 11),
        lbp_per_usd=Decimal("89500.00"),
        rows_total=len(rows) + 2,
    )


def products(db: Connection) -> dict[int, Any]:
    result = db.execute(text("SELECT * FROM products WHERE moph_code BETWEEN 501 AND 599"))
    return {found.moph_code: found for found in result}


def test_it_records_where_the_products_came_from(db: Connection) -> None:
    """R-C1."""
    result = run_import(db, ROWS)

    record = db.execute(
        text("SELECT * FROM catalog_imports WHERE id = :id"), {"id": result.import_id}
    ).one()
    assert (record.file_name, record.source_date) == ("WebMarketed-test.xls", date(2026, 11, 11))
    assert record.lbp_per_usd == Decimal("89500.00")
    assert (record.rows_total, record.rows_imported) == (7, 5)
    assert {p.import_id for p in products(db).values()} == {result.import_id}


def test_a_product_holds_the_ministrys_row(db: Connection) -> None:
    """R-C2."""
    run_import(db, ROWS)

    testamol = products(db)[501]

    assert testamol.moph_name == "TESTAMOL"
    assert testamol.search_name == "testamol"
    assert (testamol.brand_generic, testamol.atc_code) == ("B", "N02BE01")
    assert (testamol.dosage_text, testamol.presentation_text) == ("500mg", "20")
    assert (testamol.public_price_lbp, testamol.units_per_pack) == (500_000, 1)
    ingredients = db.execute(
        text(
            "SELECT name, name_normalized, strength_value, strength_unit "
            "FROM product_ingredients WHERE product_id = :id ORDER BY position"
        ),
        {"id": products(db)[503].id},
    ).all()
    assert [tuple(i) for i in ingredients] == [
        ("Paracetamol", "paracetamol", Decimal(500), "mg"),
        ("Codeine phosphate", "codeine phosphate", Decimal(30), "mg"),
    ]


def test_two_brands_of_the_same_medicine_share_a_key(db: Connection) -> None:
    """R-C5."""
    run_import(db, ROWS)
    found = products(db)

    expected = "paracetamol=500mg | tablet | N02BE01"
    assert found[501].equivalence_key == found[502].equivalence_key == expected
    assert found[503].equivalence_key != found[501].equivalence_key
    assert found[505].equivalence_key is None
    assert found[505].brand_generic is None


def test_controlled_medicines_are_flagged(db: Connection) -> None:
    """R-C6."""
    result = run_import(db, ROWS)

    assert {code for code, p in products(db).items() if p.controlled} == {503}
    assert result.controlled == 1


def test_the_prescription_notice_is_on_unless_the_product_is_on_the_list(db: Connection) -> None:
    """R-C7."""
    result = run_import(db, ROWS)

    assert {code for code, p in products(db).items() if not p.prescription_required} == {501, 502}
    assert result.no_prescription_notice == 2


def test_the_teams_corrections_win(db: Connection) -> None:
    run_import(db, ROWS)

    assert products(db)[504].equivalence_key is None
    assert products(db)[504].units_per_pack == 2


def test_a_newer_list_updates_the_same_products(db: Connection) -> None:
    """Everything that points at a product keeps pointing at it."""
    first = run_import(db, ROWS)
    before = {code: p.id for code, p in products(db).items()}

    second = run_import(
        db, [row(501, "TESTAMOL FORTE", "Paracetamol - 1g", price=650_000), ROWS[1]]
    )
    after = products(db)

    assert {code: p.id for code, p in after.items()} == before
    assert (after[501].moph_name, after[501].public_price_lbp) == ("TESTAMOL FORTE", 650_000)
    assert after[501].equivalence_key == "paracetamol=1000mg | tablet | N02BE01"
    assert after[501].import_id == second.import_id
    # A product missing from the newer list is kept, still pointing at the list it came from.
    assert after[504].import_id == first.import_id
    names = db.execute(
        text("SELECT name FROM product_ingredients WHERE product_id = :id"), {"id": after[501].id}
    ).scalars()
    assert list(names) == ["Paracetamol"]


def test_a_lower_public_price_caps_a_pharmacys_own_price(db: Connection) -> None:
    """R-C8."""
    run_import(db, ROWS)
    item = make.item(db, product_id=products(db)[501].id, price_override_lbp=450_000)
    untouched = make.item(db, product_id=products(db)[504].id, price_override_lbp=100_000)

    result = run_import(db, [row(501, "TESTAMOL", "Paracetamol - 500mg", price=300_000)])

    def override(item_id: object) -> int:
        return db.execute(  # type: ignore[no-any-return]
            text("SELECT price_override_lbp FROM inventory_items WHERE id = :id"), {"id": item_id}
        ).scalar_one()

    assert override(item) == 300_000
    assert override(untouched) == 100_000
    assert result.overrides_capped == 1


def test_a_controlled_product_is_never_visible_even_if_it_is_in_stock(db: Connection) -> None:
    """INV-6, through the one definition of visibility."""
    run_import(db, ROWS)
    codeine = make.item(db, product_id=products(db)[503].id, days_left=60)
    plain = make.item(db, product_id=products(db)[501].id, days_left=60)

    visible = set(
        db.execute(
            text("SELECT inventory_item_id FROM visible_listings(:today)"), {"today": make.TODAY}
        ).scalars()
    )

    assert plain in visible
    assert codeine not in visible
