"""Small building blocks shared by the table models (docs/05 §1)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Uuid, func, text
from sqlalchemy.orm import mapped_column

# A business entity's key: a random UUID, so it can't be guessed in a URL.
UuidKey = Annotated[
    uuid.UUID,
    mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    ),
]
# A high-volume log's key: a compact counter.
BigKey = Annotated[int, mapped_column(BigInteger, Identity(always=True), primary_key=True)]

# `created_at` may be the database's own time: it only orders "who came first" (docs/04 R-T11).
CreatedAt = Annotated[
    datetime, mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
]
UpdatedAt = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    ),
]
# A business time, always written from the app clock (docs/05 DB-D6).
Moment = DateTime(timezone=True)


def values_check(column: str, values: type[StrEnum]) -> CheckConstraint:
    """`column` holds one of the enum's values (docs/05 DB-D2: text + CHECK, not a native enum)."""
    listed = ", ".join(f"'{member.value}'" for member in values)
    return CheckConstraint(f"{column} IN ({listed})", name=f"{column}_values")


def check(name: str, condition: str) -> CheckConstraint:
    return CheckConstraint(condition, name=name)


def references(target: str, *, ondelete: str = "RESTRICT") -> ForeignKey:
    """A foreign key. Rows are never deleted in normal flows, so the default is RESTRICT."""
    return ForeignKey(target, ondelete=ondelete)
