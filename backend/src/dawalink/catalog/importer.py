"""Loads the joined catalog into the database (docs/04 R-C1 to R-C8, docs/05 §9).

Running it again with a newer list updates the same products (matched on the Ministry's
code), so their IDs, and everything that points at them, stay valid.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, delete, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as upsert

from dawalink.catalog.composition import (
    Ingredient,
    equivalence_key,
    form_group,
    normalize,
    parse_ingredients,
)
from dawalink.catalog.moph import CatalogRow
from dawalink.catalog.rules import CatalogRules
from dawalink.db.models import CatalogImport, Product, ProductIngredient
from dawalink.domain.vocabulary import BrandOrGeneric

BATCH = 500
_KNOWN_KINDS = {kind.value for kind in BrandOrGeneric}


@dataclass(frozen=True)
class ImportResult:
    import_id: uuid.UUID
    rows_total: int
    rows_imported: int
    controlled: int
    with_equivalence_key: int
    no_prescription_notice: int
    overrides_capped: int


def product_values(row: CatalogRow, rules: CatalogRules) -> tuple[dict[str, Any], list[Ingredient]]:
    """One product's columns, with everything the rules decide (R-C5, R-C6, R-C7)."""
    ingredients = parse_ingredients(row.ingredients)
    group = form_group(row.form)
    values: dict[str, Any] = {
        "moph_code": row.code,
        "registration_number": row.registration_number or None,
        "moph_name": row.name,
        "search_name": normalize(row.name),
        "brand_generic": row.brand_generic if row.brand_generic in _KNOWN_KINDS else None,
        "ingredients_raw": row.ingredients or None,
        "dosage_text": row.strength or None,
        "form_text": row.form or None,
        "presentation_text": row.presentation or None,
        "manufacturer": row.manufacturer or None,
        "form_group": group,
        "atc_code": row.atc or None,
        "public_price_lbp": row.price_lbp,
        "units_per_pack": 1,
        "prescription_required": rules.needs_prescription(ingredients),
        "controlled": rules.is_controlled(row.atc, ingredients),
        "equivalence_key": equivalence_key(ingredients, group, row.atc),
    }
    override = rules.products.get(row.code)
    if override is not None:
        for column in ("controlled", "prescription_required", "units_per_pack"):
            if (value := getattr(override, column)) is not None:
                values[column] = value
        if override.equivalence_key is not None:
            values["equivalence_key"] = override.equivalence_key or None
    return values, ingredients


def import_catalog(
    connection: Connection,
    rows: Sequence[CatalogRow],
    rules: CatalogRules,
    *,
    file_name: str,
    source_date: date,
    lbp_per_usd: Decimal,
    rows_total: int,
) -> ImportResult:
    """Inserts or updates every product, inside the caller's transaction."""
    import_id = connection.execute(
        insert(CatalogImport)
        .values(
            file_name=file_name,
            source_date=source_date,
            lbp_per_usd=lbp_per_usd,
            rows_total=rows_total,
            rows_imported=len(rows),
        )
        .returning(CatalogImport.id)
    ).scalar_one()

    products: list[dict[str, Any]] = []
    ingredients_by_code: dict[int, list[Ingredient]] = {}
    for row in rows:
        values, ingredients = product_values(row, rules)
        products.append({**values, "import_id": import_id})
        ingredients_by_code[row.code] = ingredients

    updated_columns = [c for c in products[0] if c != "moph_code"] if products else []
    for start in range(0, len(products), BATCH):
        statement = upsert(Product).values(products[start : start + BATCH])
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[Product.moph_code],
                set_={column: statement.excluded[column] for column in updated_columns},
            )
        )

    id_by_code: Mapping[int, uuid.UUID] = {
        code: product_id
        for product_id, code in connection.execute(
            select(Product.id, Product.moph_code).where(Product.import_id == import_id)
        )
    }
    connection.execute(
        delete(ProductIngredient).where(
            ProductIngredient.product_id.in_(
                select(Product.id).where(Product.import_id == import_id)
            )
        )
    )
    ingredient_rows = [
        {
            "product_id": id_by_code[code],
            "position": position,
            "name": ingredient.name,
            "name_normalized": ingredient.name_normalized,
            "strength_value": ingredient.strength_value,
            "strength_unit": ingredient.strength_unit,
        }
        for code, ingredients in ingredients_by_code.items()
        for position, ingredient in enumerate(ingredients, start=1)
    ]
    for start in range(0, len(ingredient_rows), BATCH):
        connection.execute(insert(ProductIngredient), ingredient_rows[start : start + BATCH])

    # R-C8: a pharmacy's own price is never above the new public price.
    capped = connection.execute(
        text(
            "UPDATE inventory_items ii SET price_override_lbp = p.public_price_lbp "
            "FROM products p WHERE p.id = ii.product_id "
            "AND ii.price_override_lbp > p.public_price_lbp"
        )
    ).rowcount

    def count(*conditions: Any) -> int:
        return connection.execute(
            select(func.count())
            .select_from(Product)
            .where(Product.import_id == import_id, *conditions)
        ).scalar_one()

    return ImportResult(
        import_id=import_id,
        rows_total=rows_total,
        rows_imported=len(rows),
        controlled=count(Product.controlled),
        with_equivalence_key=count(Product.equivalence_key.is_not(None)),
        no_prescription_notice=count(Product.prescription_required.is_(False)),
        overrides_capped=capped,
    )
