"""Alembic's entry point: connects to the database and runs the migrations."""

from alembic import context
from sqlalchemy import create_engine

from dawalink.config import load_settings
from dawalink.db.base import Base

target_metadata = Base.metadata


def run_migrations() -> None:
    # prepare_db and the tests pass the address in; the alembic command line reads the settings.
    database_url = context.config.attributes.get("database_url") or load_settings().database_url
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
