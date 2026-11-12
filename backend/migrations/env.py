"""Alembic's entry point: connects to the database and runs the migrations."""

from alembic import context
from sqlalchemy import create_engine

import dawalink.db.models  # noqa: F401  (registers every table on Base.metadata)
from dawalink.config import load_settings
from dawalink.db.base import Base

target_metadata = Base.metadata


def run_migrations() -> None:
    # prepare_db and the tests pass the address in. The alembic command line reads the
    # settings, and uses the migrator login when there is one: it owns the tables.
    database_url = context.config.attributes.get("database_url")
    if not database_url:
        settings = load_settings()
        database_url = settings.database_migrator_url or settings.database_url
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
