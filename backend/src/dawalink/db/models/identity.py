"""Users, logins, districts and pharmacies (docs/05 §3.1)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Index,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from dawalink.db.base import Base
from dawalink.db.columns import (
    BigKey,
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


class Area(Base):
    """A place a client can name in chat instead of sharing a location: a neighbourhood,
    a town, or a district as a whole (docs/04 R-S2, decision log BLD-D14).

    Reference data, written by the import from `data/areas.csv`.
    """

    __tablename__ = "areas"
    __table_args__ = (UniqueConstraint("name", "district_id"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text)
    district_id: Mapped[int] = mapped_column(SmallInteger, references("districts.id"))
    # Other ways the same place is written: other spellings, Arabic script.
    other_names: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    # True when the row stands for the whole district: its centre is only a rough start.
    whole_district: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # The area's centre: what travel times are counted from. Never sent to the LLM (INV-24).
    ref_lat: Mapped[Decimal] = mapped_column(Numeric(8, 5))
    ref_lon: Mapped[Decimal] = mapped_column(Numeric(8, 5))


class ClientProfile(Base):
    __tablename__ = "client_profiles"
    __table_args__ = (
        values_check("status", ClientStatus),
        check("paused_has_an_end", "status <> 'PAUSED' OR paused_until IS NOT NULL"),
        check("home_place_is_whole", "(home_lat IS NULL) = (home_lon IS NULL)"),
        # A deleted account says when; an account is emptied only after it was deleted.
        check("deleted_has_a_moment", "(status = 'DELETED') = (deleted_at IS NOT NULL)"),
        check("emptied_after_deleted", "emptied_at IS NULL OR deleted_at IS NOT NULL"),
        # What the clean-up looks for: deleted accounts it has not emptied yet (R-AU10).
        Index(
            "ix_client_profiles_to_empty",
            "user_id",
            postgresql_where=text("status = 'DELETED' AND emptied_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(Text, server_default=text("'UNVERIFIED'"))
    paused_until: Mapped[datetime | None] = mapped_column(Moment)
    district_id: Mapped[int | None] = mapped_column(SmallInteger, references("districts.id"))
    alternatives_ok_default: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status_reason: Mapped[str | None] = mapped_column(Text)
    # The name in parts (BLD-D40). `users.full_name` is these in one line, written by the
    # one function that changes a client's name (services/clients.py).
    first_name: Mapped[str | None] = mapped_column(Text)
    middle_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    # No rule reads it, and it is never sent to the LLM, a pharmacy or an admin.
    birth_date: Mapped[date | None] = mapped_column(Date)
    # The home town, from our own list of places; always inside `district_id`.
    home_area_id: Mapped[int | None] = mapped_column(SmallInteger, references("areas.id"))
    # A place the client put on a map, rounded to about 100 m like every location we
    # keep (N-43). Searches and the agent's tools start from it; it never leaves code.
    home_lat: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    home_lon: Mapped[Decimal | None] = mapped_column(Numeric(7, 3))
    # The client deleted their account (R-AU10): when, in real time. What was personal on
    # this row and on the user's was erased at that moment.
    deleted_at: Mapped[datetime | None] = mapped_column(Moment)
    # When the clean-up erased what the app's login may not delete (the chats, the
    # notifications, the emails, the ended logins). Null until then.
    emptied_at: Mapped[datetime | None] = mapped_column(Moment)


class SearchHistory(Base):
    """What a client searched lately, to search it again in one tap (BLD-D42). Read only
    by its client; purged after 30 days."""

    __tablename__ = "search_history"
    __table_args__ = (
        Index("ix_search_history_client", "client_id", "searched_at"),
        check("query_not_empty", "length(query) BETWEEN 2 AND 60"),
    )

    id: Mapped[BigKey]
    client_id: Mapped[uuid.UUID] = mapped_column(Uuid, references("users.id"))
    query: Mapped[str] = mapped_column(Text)
    searched_at: Mapped[datetime] = mapped_column(Moment)


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


class PasswordResetToken(Base):
    """A "set a new password" link (docs/04 R-AU9). Like a confirmation link, only the
    token's hash is stored. It works once, for 30 minutes of real time, and only the
    newest of a user's links works."""

    __tablename__ = "password_reset_tokens"

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
        check("auto_list_days_range", "auto_list_days BETWEEN 0 AND 180"),
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
    # The pharmacy's own rule: its boxes are listed by themselves when they have this many
    # days left or fewer; 0: never by themselves (N-54). 180 is the most (N-1).
    auto_list_days: Mapped[int] = mapped_column(SmallInteger, server_default=text("180"))
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
