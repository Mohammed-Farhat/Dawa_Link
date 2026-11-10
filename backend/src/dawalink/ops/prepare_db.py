"""Prepares the database before the services start: python -m dawalink.ops.prepare_db

Run from the backend folder (where alembic.ini is). Running it twice is safe (docs/12 §7).
Today it waits for the database and applies the migrations. The database roles, the catalog
import and the demo seed join this command when those features are built.
"""

import argparse
import time
from collections.abc import Callable
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config

from dawalink.config import load_settings
from dawalink.db.session import database_is_up, make_engine
from dawalink.observability.logging import configure_logging

log = structlog.get_logger(__name__)


class DatabaseNotReady(Exception):
    pass


def wait_for_database(
    database_url: str,
    *,
    timeout_s: float,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    engine = make_engine(database_url)
    try:
        waited = 0.0
        while not database_is_up(engine):
            if waited >= timeout_s:
                raise DatabaseNotReady(f"The database did not answer within {timeout_s:.0f} s.")
            sleep(1.0)
            waited += 1.0
    finally:
        engine.dispose()


def run_migrations(database_url: str, alembic_ini: Path = Path("alembic.ini")) -> None:
    if not alembic_ini.is_file():
        raise FileNotFoundError(f"{alembic_ini} not found: run this from the backend folder.")
    config = Config(str(alembic_ini))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-seconds", type=float, default=60.0)
    arguments = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.log_level)
    wait_for_database(settings.database_url, timeout_s=arguments.wait_seconds)
    run_migrations(settings.database_url)
    log.info("database_prepared", version=settings.app_version)


if __name__ == "__main__":
    main()
