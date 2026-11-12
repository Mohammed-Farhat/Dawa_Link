"""A pharmacy's stock and its uploads (docs/05 §3.3).

The expiry zone and the price are never stored here: they are computed from the expiry
date and the app clock's `today`, every time (docs/04 R-T9).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, Index, Integer, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dawalink.db.base import Base
from dawalink.db.columns import (
    CreatedAt,
    Moment,
    UpdatedAt,
    UuidKey,
    check,
    references,
    values_check,
)
from dawalink.domain.inventory import ListingControl
from dawalink.domain.vocabulary import UploadStatus


class InventoryUpload(Base):
    """One uploaded file's result. The file itself is never stored (docs/05 DB-D4)."""

    __tablename__ = "inventory_uploads"
    __table_args__ = (
        values_check("status", UploadStatus),
        # A pharmacy has one upload waiting for [Apply] at a time.
        Index(
            "uq_inventory_uploads_one_validated",
            "pharmacy_id",
            unique=True,
            postgresql_where=text("status = 'VALIDATED'"),
        ),
    )

    id: Mapped[UuidKey]
    pharmacy_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("pharmacies.id"), index=True)
    status: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(Text)
    rows_total: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rows_ok: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rows_error: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    errors: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    created_at: Mapped[CreatedAt]
    applied_at: Mapped[datetime | None] = mapped_column(Moment)


class InventoryUploadRow(Base):
    """A staged row, kept only until the upload is applied or discarded."""

    __tablename__ = "inventory_upload_rows"
    __table_args__ = (check("quantity_not_negative", "quantity >= 0"),)

    upload_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, references("inventory_uploads.id", ondelete="CASCADE"), primary_key=True
    )
    row_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("products.id"))
    batch: Mapped[str] = mapped_column(Text)
    expiry_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[int] = mapped_column(Integer)


class InventoryItem(Base):
    """One batch of one product in one pharmacy."""

    __tablename__ = "inventory_items"
    __table_args__ = (
        values_check("listing_control", ListingControl),
        check("on_hand_not_negative", "qty_on_hand >= 0"),
        check("reserved_not_negative", "qty_reserved >= 0"),
        # INV-1: a pharmacy never holds more reservations than boxes.
        check("reserved_within_on_hand", "qty_reserved <= qty_on_hand"),
        check(
            "price_override_not_negative", "price_override_lbp IS NULL OR price_override_lbp >= 0"
        ),
        UniqueConstraint("pharmacy_id", "product_id", "batch", "expiry_date"),
        Index("ix_inventory_items_product_expiry", "product_id", "expiry_date"),
        Index("ix_inventory_items_pharmacy_expiry", "pharmacy_id", "expiry_date"),
    )

    id: Mapped[UuidKey]
    pharmacy_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("pharmacies.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("products.id"))
    batch: Mapped[str] = mapped_column(Text)
    expiry_date: Mapped[date] = mapped_column(Date)
    qty_on_hand: Mapped[int] = mapped_column(Integer)
    qty_reserved: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    splittable: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    listing_control: Mapped[str] = mapped_column(Text, server_default=text("'LIVE'"))
    # The pharmacy's own price. A trigger keeps it at or below the public price (INV-5).
    price_override_lbp: Mapped[int | None] = mapped_column(BigInteger)
    last_edited_at: Mapped[datetime | None] = mapped_column(Moment)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]
