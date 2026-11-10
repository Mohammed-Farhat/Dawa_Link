"""The base class every table model inherits from; Alembic reads its metadata."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
