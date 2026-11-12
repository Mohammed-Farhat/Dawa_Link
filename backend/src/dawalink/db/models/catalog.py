"""The medicine catalog, imported from the Ministry's lists (docs/05 §3.2, docs/04 §2)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, Index, Integer, Numeric, SmallInteger, Text, Uuid
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from dawalink.db.base import Base
from dawalink.db.columns import CreatedAt, UuidKey, check, references, values_check
from dawalink.domain.vocabulary import BrandOrGeneric


class CatalogImport(Base):
    """One run of the import: which Ministry list, of which date, at which exchange rate."""

    __tablename__ = "catalog_imports"

    id: Mapped[UuidKey]
    file_name: Mapped[str] = mapped_column(Text)
    source_date: Mapped[date] = mapped_column(Date)
    # The rate the Ministry used for this list; the default display rate (docs/04 R-C3).
    lbp_per_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    rows_total: Mapped[int] = mapped_column(Integer)
    rows_imported: Mapped[int] = mapped_column(Integer)
    imported_at: Mapped[CreatedAt]


class Product(Base):
    """One medicine on the Ministry's price list (docs/04 R-C2)."""

    __tablename__ = "products"
    __table_args__ = (
        values_check("brand_generic", BrandOrGeneric),
        check("public_price_not_negative", "public_price_lbp >= 0"),
        check("units_per_pack_positive", "units_per_pack >= 1"),
        Index(
            "ix_products_search_name_trgm",
            "search_name",
            postgresql_using="gin",
            postgresql_ops={"search_name": "gin_trgm_ops"},
        ),
        Index("ix_products_atc_code", "atc_code"),
        Index("ix_products_equivalence_key", "equivalence_key"),
    )

    id: Mapped[UuidKey]
    # The Ministry's own code for this product: what a new import matches on.
    moph_code: Mapped[int] = mapped_column(Integer, unique=True)
    # The last import that contained this product (docs/04 R-C1).
    import_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("catalog_imports.id"), index=True)
    registration_number: Mapped[str | None] = mapped_column(Text)
    moph_name: Mapped[str] = mapped_column(Text)
    # Lowercase, no punctuation: what fuzzy search runs on.
    search_name: Mapped[str] = mapped_column(Text)
    brand_generic: Mapped[str | None] = mapped_column(Text)
    ingredients_raw: Mapped[str | None] = mapped_column(Text)
    dosage_text: Mapped[str | None] = mapped_column(Text)
    form_text: Mapped[str | None] = mapped_column(Text)
    # The pack as the Ministry writes it: "30", "100ml", "1Vial*2ml".
    presentation_text: Mapped[str | None] = mapped_column(Text)
    manufacturer: Mapped[str | None] = mapped_column(Text)
    # `tablet`, `capsule`, `tablet_mr`, ...: what "the same form" means (docs/04 R-C5).
    form_group: Mapped[str | None] = mapped_column(Text)
    atc_code: Mapped[str | None] = mapped_column(Text)
    public_price_lbp: Mapped[int] = mapped_column(BigInteger)
    units_per_pack: Mapped[int] = mapped_column(Integer, server_default=sql("1"))
    # Only shows the "bring your prescription" notice (docs/04 R-C7, R-P1).
    prescription_required: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    # Controlled medicines never appear anywhere on DawaLink (docs/04 R-C6).
    controlled: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))
    # Same key = same ingredients, strengths and form. Null = no equivalents (docs/04 R-C5).
    equivalence_key: Mapped[str | None] = mapped_column(Text)


class ProductIngredient(Base):
    __tablename__ = "product_ingredients"
    __table_args__ = (
        Index(
            "ix_product_ingredients_name_trgm",
            "name_normalized",
            postgresql_using="gin",
            postgresql_ops={"name_normalized": "gin_trgm_ops"},
        ),
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, references("products.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    name_normalized: Mapped[str] = mapped_column(Text)
    strength_value: Mapped[Decimal | None] = mapped_column(Numeric)
    strength_unit: Mapped[str | None] = mapped_column(Text)


class PricingTier(Base):
    """The system discount for a range of days left before expiry (docs/04 N-4)."""

    __tablename__ = "pricing_tiers"
    __table_args__ = (
        check("days_in_order", "min_days >= 0 AND min_days <= max_days"),
        check("discount_is_a_percentage", "discount_pct BETWEEN 0 AND 100"),
        # Two tiers never overlap, so a number of days left has at most one discount.
        ExcludeConstraint(
            (sql("int4range(min_days, max_days, '[]')"), "&&"),
            name="ex_pricing_tiers_no_overlap",
            using="gist",
        ),
    )

    min_days: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    max_days: Mapped[int] = mapped_column(Integer)
    discount_pct: Mapped[int] = mapped_column(SmallInteger)
