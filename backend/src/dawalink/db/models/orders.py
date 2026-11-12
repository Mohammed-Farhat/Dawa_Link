"""Orders: one quantity from one pharmacy, from offer or reservation to its end (docs/05 §3.4).

The `orders_guard` trigger (in the migration) freezes a finished order, its price snapshot
and its deadline (INV-4, INV-5, INV-15).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
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
from dawalink.domain.orders import OrderSource, OrderState
from dawalink.domain.vocabulary import CloseReason

OPEN = "state IN ('OFFERED', 'RESERVED')"
# The alphabet of order and request numbers: no 0/O and no 1/I (docs/05 §1).
REF_CHARACTERS = "[2-9A-HJ-NP-Z]{6}"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        values_check("state", OrderState),
        values_check("source", OrderSource),
        values_check("close_reason", CloseReason),
        check("ref_format", f"ref ~ '^R-{REF_CHARACTERS}$'"),
        check("qty_requested_positive", "qty_requested > 0"),
        check("qty_locked_range", "qty_locked BETWEEN 0 AND qty_requested"),
        # A finished order holds no stock.
        check("only_open_orders_hold_stock", f"{OPEN} OR qty_locked = 0"),
        check(
            "qty_picked_up_range",
            "qty_picked_up IS NULL OR qty_picked_up BETWEEN 0 AND qty_requested",
        ),
        check("picked_up_has_a_quantity", "state <> 'PICKED_UP' OR qty_picked_up IS NOT NULL"),
        check("days_of_use_positive", "days_of_use >= 1"),
        check("price_snapshot_not_negative", "price_snapshot_lbp >= 0"),
        # INV-14: a timed state always has its deadline.
        check("offer_has_an_end", "state <> 'OFFERED' OR offer_expires_at IS NOT NULL"),
        check("reservation_has_a_deadline", "state <> 'RESERVED' OR deadline IS NOT NULL"),
        check("reservation_has_a_pickup_day", "state <> 'RESERVED' OR pickup_day IS NOT NULL"),
        # One key per order; a group reserve stores "<key>:<position>" for each of its orders.
        UniqueConstraint("client_id", "idempotency_key"),
        # INV-20: at most one offer per path per claim. The path is the order's source.
        Index(
            "uq_orders_one_offer_per_path",
            "claim_id",
            "source",
            unique=True,
            postgresql_where=text("state = 'OFFERED'"),
        ),
        Index("ix_orders_client_open", "client_id", postgresql_where=text(OPEN)),
        Index("ix_orders_pharmacy_state", "pharmacy_id", "state"),
        Index("ix_orders_item_open", "inventory_item_id", postgresql_where=text(OPEN)),
        # What the clock check looks for.
        Index("ix_orders_deadline_due", "deadline", postgresql_where=text("state = 'RESERVED'")),
        Index(
            "ix_orders_offer_due", "offer_expires_at", postgresql_where=text("state = 'OFFERED'")
        ),
        Index("ix_orders_request_item_id", "request_item_id"),
        Index("ix_orders_claim_id", "claim_id"),
        Index("ix_orders_group_id", "group_id"),
    )

    id: Mapped[UuidKey]
    # The order number the client shows at the counter: "R-7K3Q2F", random.
    ref: Mapped[str] = mapped_column(Text, unique=True)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    pharmacy_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("pharmacies.id"))
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("inventory_items.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("products.id"))
    # Copied at creation, for the limit per medicine group (docs/04 R-L2).
    equivalence_key: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, references("claims.id"))
    request_item_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, references("request_items.id"))
    early_release_ask_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, references("early_release_asks.id")
    )
    # Shared by the orders of one group reserve (docs/04 R-RQ6).
    group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(Text)
    qty_requested: Mapped[int] = mapped_column(Integer)
    qty_locked: Mapped[int] = mapped_column(Integer)
    qty_picked_up: Mapped[int | None] = mapped_column(Integer)
    # Chosen by the client; the box lasts the days of use from the pickup day (INV-25).
    pickup_day: Mapped[date | None] = mapped_column(Date)
    days_of_use: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    price_snapshot_lbp: Mapped[int] = mapped_column(BigInteger)
    offer_expires_at: Mapped[datetime | None] = mapped_column(Moment)
    deadline: Mapped[datetime | None] = mapped_column(Moment)
    counts_as_no_show: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    contested_at: Mapped[datetime | None] = mapped_column(Moment)
    close_reason: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[CreatedAt]
    reserved_at: Mapped[datetime | None] = mapped_column(Moment)
    closed_at: Mapped[datetime | None] = mapped_column(Moment)
    updated_at: Mapped[UpdatedAt]
