"""Sourcing requests, claims and early release: what the agent works on (docs/05 §3.5).

A client's location is stored here rounded to about 100 m, and never reaches the LLM
(docs/04 INV-24).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Index,
    Integer,
    Numeric,
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
from dawalink.db.models.orders import REF_CHARACTERS
from dawalink.domain.claims import ClaimState
from dawalink.domain.early_release import AskState, EarlyReleaseState
from dawalink.domain.requests import ItemState, RequestOutcome, RequestState
from dawalink.domain.vocabulary import ClaimKind, ClaimSource, LocationSource

LIVE_CLAIM = "state IN ('ACTIVE', 'OFFER_PENDING')"
# A rounded coordinate: 3 decimals, about 100 m (docs/04 N-43).
RoundedCoordinate = Numeric(7, 3)


class SourcingRequest(Base):
    """ "Find these 1-5 medicines for me now" (docs/04 SM-8)."""

    __tablename__ = "sourcing_requests"
    __table_args__ = (
        values_check("state", RequestState),
        values_check("outcome", RequestOutcome),
        values_check("loc_source", LocationSource),
        check("ref_format", f"ref ~ '^Q-{REF_CHARACTERS}$'"),
        check("closed_has_an_outcome", "(state = 'CLOSED') = (outcome IS NOT NULL)"),
        UniqueConstraint("client_id", "idempotency_key"),
        Index(
            "ix_sourcing_requests_client_open", "client_id", postgresql_where=text("state = 'OPEN'")
        ),
        Index("ix_sourcing_requests_ends_due", "ends_at", postgresql_where=text("state = 'OPEN'")),
    )

    id: Mapped[UuidKey]
    ref: Mapped[str] = mapped_column(Text, unique=True)
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    state: Mapped[str] = mapped_column(Text, server_default=text("'OPEN'"))
    outcome: Mapped[str | None] = mapped_column(Text)
    district_id: Mapped[int | None] = mapped_column(SmallInteger, references("districts.id"))
    loc_lat: Mapped[Decimal | None] = mapped_column(RoundedCoordinate)
    loc_lon: Mapped[Decimal | None] = mapped_column(RoundedCoordinate)
    loc_source: Mapped[str | None] = mapped_column(Text)
    alternatives_ok: Mapped[bool] = mapped_column(Boolean)
    # Creation + the search window, from the app clock (docs/04 N-11).
    ends_at: Mapped[datetime] = mapped_column(Moment)
    # Set when the check one hour before the end has run, so it runs once (N-24).
    window_checked_at: Mapped[datetime | None] = mapped_column(Moment)
    escalated: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    idempotency_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[CreatedAt]
    closed_at: Mapped[datetime | None] = mapped_column(Moment)


class RequestItem(Base):
    """One medicine in a request."""

    __tablename__ = "request_items"
    __table_args__ = (
        values_check("state", ItemState),
        check("position_range", "position BETWEEN 1 AND 5"),
        check("qty_range", "qty BETWEEN 1 AND 3"),
        check("qty_secured_range", "qty_secured BETWEEN 0 AND qty"),
        check("days_of_use_positive", "days_of_use >= 1"),
        check("max_price_not_negative", "max_price_lbp IS NULL OR max_price_lbp >= 0"),
        UniqueConstraint("request_id", "position"),
    )

    id: Mapped[UuidKey]
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("sourcing_requests.id"))
    position: Mapped[int] = mapped_column(SmallInteger)
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("products.id"))
    qty: Mapped[int] = mapped_column(Integer)
    # Units in this item's reserved or picked-up orders (INV-18).
    qty_secured: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    days_of_use: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    max_price_lbp: Mapped[int | None] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(Text, server_default=text("'SEARCHING'"))
    updated_at: Mapped[UpdatedAt]


class Claim(Base):
    """One need for one medicine, waiting for stock: a watch or a waiting request item.

    `created_at`, then `id`, is the priority order: first come, first served (docs/04 R-PRI).
    Nothing in this table, or anywhere else, can change that order.
    """

    __tablename__ = "claims"
    __table_args__ = (
        values_check("kind", ClaimKind),
        values_check("source", ClaimSource),
        values_check("state", ClaimState),
        check(
            "request_item_only_for_its_kind",
            "(kind = 'REQUEST_ITEM') = (request_item_id IS NOT NULL)",
        ),
        check("qty_range", "qty BETWEEN 1 AND 3"),
        check("qty_missing_range", "qty_missing BETWEEN 0 AND qty"),
        check("days_of_use_positive", "days_of_use >= 1"),
        check("max_price_not_negative", "max_price_lbp IS NULL OR max_price_lbp >= 0"),
        # One live watch per product per client (docs/04 R-W2).
        Index(
            "uq_claims_one_live_watch",
            "client_id",
            "product_id",
            unique=True,
            postgresql_where=text(f"kind = 'WATCH' AND {LIVE_CLAIM}"),
        ),
        # Matching reads the waiting claims of a medicine group in priority order.
        Index(
            "ix_claims_matching",
            "equivalence_key",
            "created_at",
            "id",
            postgresql_where=text("state = 'ACTIVE'"),
        ),
        Index("ix_claims_product_active", "product_id", postgresql_where=text("state = 'ACTIVE'")),
        Index("ix_claims_ends_due", "ends_at", postgresql_where=text(LIVE_CLAIM)),
        Index("ix_claims_client_live", "client_id", postgresql_where=text(LIVE_CLAIM)),
    )

    id: Mapped[UuidKey]
    kind: Mapped[str] = mapped_column(Text)
    # Where it was created: decides where its events go (docs/04 R-AG5).
    source: Mapped[str] = mapped_column(Text, server_default=text("'search'"))
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    request_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, references("request_items.id"), unique=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("products.id"))
    include_equivalents: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    equivalence_key: Mapped[str | None] = mapped_column(Text)
    district_id: Mapped[int | None] = mapped_column(SmallInteger, references("districts.id"))
    loc_lat: Mapped[Decimal | None] = mapped_column(RoundedCoordinate)
    loc_lon: Mapped[Decimal | None] = mapped_column(RoundedCoordinate)
    # Only boxes that last this long are offered (docs/04 R-F1).
    days_of_use: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    max_price_lbp: Mapped[int | None] = mapped_column(BigInteger)
    qty: Mapped[int] = mapped_column(Integer)
    qty_missing: Mapped[int] = mapped_column(Integer)
    ends_at: Mapped[datetime] = mapped_column(Moment)
    state: Mapped[str] = mapped_column(Text, server_default=text("'ACTIVE'"))
    created_at: Mapped[CreatedAt]
    closed_at: Mapped[datetime | None] = mapped_column(Moment)


class ClaimSkip(Base):
    """A claim that declined an offer, or let it expire, skips that item for a while (O10)."""

    __tablename__ = "claim_skips"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, references("claims.id", ondelete="CASCADE"), primary_key=True
    )
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, references("inventory_items.id"), primary_key=True
    )
    skip_until: Mapped[datetime] = mapped_column(Moment)


class EarlyReleaseRequest(Base):
    """The agent asks pharmacies to release private stock for one claim (docs/04 SM-6)."""

    __tablename__ = "early_release_requests"
    __table_args__ = (
        values_check("state", EarlyReleaseState),
        check("qty_range", "qty BETWEEN 1 AND 3"),
        UniqueConstraint("client_id", "idempotency_key"),
        Index(
            "ix_early_release_requests_client_open",
            "client_id",
            postgresql_where=text("state = 'OPEN'"),
        ),
        # A need has one early-release request at a time (docs/04 SM-6).
        Index(
            "uq_early_release_requests_one_open_per_claim",
            "claim_id",
            unique=True,
            postgresql_where=text("state = 'OPEN'"),
        ),
        Index("ix_early_release_requests_claim_id", "claim_id"),
    )

    id: Mapped[UuidKey]
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("claims.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("products.id"))
    include_equivalents: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    qty: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(Text, server_default=text("'OPEN'"))
    idempotency_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[CreatedAt]
    closed_at: Mapped[datetime | None] = mapped_column(Moment)


class EarlyReleaseAsk(Base):
    """One pharmacy asked about one private item.

    `inventory_item_id` is private stock: it is never returned to the client or the agent
    (docs/04 INV-8).
    """

    __tablename__ = "early_release_asks"
    __table_args__ = (
        values_check("state", AskState),
        check("accepted_qty_positive", "accepted_qty IS NULL OR accepted_qty >= 1"),
        check(
            "accepted_price_not_negative", "accepted_price_lbp IS NULL OR accepted_price_lbp >= 0"
        ),
        check(
            "accepted_has_its_terms",
            "state <> 'ACCEPTED' OR (accepted_qty IS NOT NULL AND accepted_price_lbp IS NOT NULL)",
        ),
        UniqueConstraint("er_request_id", "pharmacy_id"),
        # The limit of asks per pharmacy per day (docs/04 R-E3).
        Index("ix_early_release_asks_pharmacy_created", "pharmacy_id", "created_at"),
        # A pharmacy that declined a product isn't asked again for a while.
        Index(
            "ix_early_release_asks_declined",
            "pharmacy_id",
            "product_id",
            "answered_at",
            postgresql_where=text("state = 'DECLINED'"),
        ),
        Index(
            "ix_early_release_asks_respond_due",
            "respond_by",
            postgresql_where=text("state = 'ASKED'"),
        ),
    )

    id: Mapped[UuidKey]
    er_request_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("early_release_requests.id"))
    pharmacy_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("pharmacies.id"))
    inventory_item_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("inventory_items.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("products.id"))
    state: Mapped[str] = mapped_column(Text, server_default=text("'ASKED'"))
    respond_by: Mapped[datetime] = mapped_column(Moment)
    accepted_qty: Mapped[int | None] = mapped_column(Integer)
    accepted_price_lbp: Mapped[int | None] = mapped_column(BigInteger)
    # A code, never free text: nothing a pharmacy types reaches the agent (docs/04 R-AG8).
    decline_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[CreatedAt]
    answered_at: Mapped[datetime | None] = mapped_column(Moment)
    updated_at: Mapped[UpdatedAt]
