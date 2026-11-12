"""Users, logins, districts and pharmacies (docs/05 §3.1)."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Index,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
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
from dawalink.domain.accounts import ClientStatus, PharmacyStatus
from dawalink.domain.vocabulary import UserRole


class User(Base):
    """One login. `email`, `full_name` and `phone` are the only personal data columns."""

    __tablename__ = "users"
    __table_args__ = (
        values_check("role", UserRole),
        check("full_name_length", "char_length(full_name) BETWEEN 2 AND 80"),
        check("failed_logins_not_negative", "failed_logins >= 0"),
        # An admin always has a second login factor (docs/04 R-AU6).
        check("admin_has_totp", "role <> 'admin' OR totp_secret IS NOT NULL"),
    )

    id: Mapped[UuidKey]
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(Moment)
    failed_logins: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(Moment)
    totp_secret: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    signup_ip_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class District(Base):
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text, unique=True)
    governorate: Mapped[str] = mapped_column(Text)
    # The point used when a client picks a district instead of sharing a location (R-S2).
    ref_lat: Mapped[Decimal] = mapped_column(Numeric(8, 5))
    ref_lon: Mapped[Decimal] = mapped_column(Numeric(8, 5))


class ClientProfile(Base):
    __tablename__ = "client_profiles"
    __table_args__ = (
        values_check("status", ClientStatus),
        check("paused_has_an_end", "status <> 'PAUSED' OR paused_until IS NOT NULL"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(Text, server_default=text("'UNVERIFIED'"))
    paused_until: Mapped[datetime | None] = mapped_column(Moment)
    district_id: Mapped[int | None] = mapped_column(SmallInteger, references("districts.id"))
    alternatives_ok_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status_reason: Mapped[str | None] = mapped_column(Text)


class Session(Base):
    """A login. The browser holds a random token; only its hash is stored (docs/04 R-AU3)."""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_live", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )

    id: Mapped[UuidKey]
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_at: Mapped[CreatedAt]
    expires_at: Mapped[datetime] = mapped_column(Moment)
    last_seen_at: Mapped[datetime | None] = mapped_column(Moment)
    revoked_at: Mapped[datetime | None] = mapped_column(Moment)


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    id: Mapped[UuidKey]
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"), index=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    expires_at: Mapped[datetime] = mapped_column(Moment)
    used_at: Mapped[datetime | None] = mapped_column(Moment)


class Pharmacy(Base):
    __tablename__ = "pharmacies"
    __table_args__ = (
        values_check("status", PharmacyStatus),
        check("pickup_days_range", "pickup_days BETWEEN 1 AND 3"),
        check("pin_in_range", "lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180"),
        Index("ix_pharmacies_status", "status"),
    )

    id: Mapped[UuidKey]
    # One account per pharmacy (decision log P-D5).
    owner_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"), unique=True)
    name: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(Text)
    license_number: Mapped[str] = mapped_column(Text, unique=True)
    phone: Mapped[str] = mapped_column(Text, unique=True)
    district_id: Mapped[int] = mapped_column(SmallInteger, references("districts.id"))
    # The map pin set at registration and checked by an admin (docs/04 R-S2).
    lat: Mapped[Decimal] = mapped_column(Numeric(8, 5))
    lon: Mapped[Decimal] = mapped_column(Numeric(8, 5))
    location_checked_at: Mapped[datetime | None] = mapped_column(Moment)
    location_checked_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, references("users.id"))
    # How many open days ahead a client may choose the pickup day (docs/04 N-6).
    pickup_days: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'PENDING'"))
    info_requested: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status_reason: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(Moment)
    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


class PharmacyHours(Base):
    """One opening range. Up to two per day; overlaps are checked by the service (R-T2)."""

    __tablename__ = "pharmacy_hours"
    __table_args__ = (
        check("weekday_range", "weekday BETWEEN 0 AND 6"),
        check("seq_range", "seq BETWEEN 1 AND 2"),
        check("open_minute_range", "open_minute BETWEEN 0 AND 1439"),
        check("close_minute_range", "close_minute BETWEEN 1 AND 1440"),
        check("opens_before_it_closes", "open_minute < close_minute"),
    )

    pharmacy_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, references("pharmacies.id"), primary_key=True
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, primary_key=True)  # 0 = Monday
    seq: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    open_minute: Mapped[int] = mapped_column(SmallInteger)
    close_minute: Mapped[int] = mapped_column(SmallInteger)  # 1440 = 24:00
