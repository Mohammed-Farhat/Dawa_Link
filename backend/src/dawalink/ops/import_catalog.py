"""Loads the catalog file into the database: python -m dawalink.ops.import_catalog

Run after `build_catalog`. Running it again updates the same products (docs/04 R-C1, R-C8).
"""

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import structlog
from sqlalchemy import Connection, create_engine, func, select
from sqlalchemy.orm import sessionmaker

from dawalink.catalog.importer import ImportResult, import_catalog
from dawalink.catalog.moph import read_catalog
from dawalink.catalog.rules import DEFAULT_RULES_FILE, load_rules
from dawalink.config import Settings, load_settings, required
from dawalink.db.models import Product
from dawalink.db.session import make_engine
from dawalink.observability.logging import configure_logging
from dawalink.ops.build_catalog import CATALOG_FILE, DETAILS_FILE
from dawalink.services import controlled
from dawalink.services.clock import AppClock

log = structlog.get_logger(__name__)
DEFAULT_FOLDER = Path("data/moph")


def catalog_is_available(folder: Path = DEFAULT_FOLDER) -> bool:
    return (folder / CATALOG_FILE).is_file() and (folder / DETAILS_FILE).is_file()


def catalog_is_empty(connection: Connection) -> bool:
    return not connection.execute(select(func.count()).select_from(Product)).scalar_one()


def import_from_folder(
    connection: Connection, folder: Path = DEFAULT_FOLDER, rules_file: Path = DEFAULT_RULES_FILE
) -> ImportResult:
    details = json.loads((folder / DETAILS_FILE).read_text(encoding="utf-8"))
    return import_catalog(
        connection,
        read_catalog(folder / CATALOG_FILE),
        load_rules(rules_file),
        file_name=details["file_name"],
        source_date=date.fromisoformat(details["source_date"]),
        lbp_per_usd=Decimal(details["lbp_per_usd"]),
        rows_total=int(details["rows_total"]),
    )


def log_result(result: ImportResult) -> None:
    log.info(
        "catalog_imported",
        rows_total=result.rows_total,
        rows_imported=result.rows_imported,
        controlled=result.controlled,
        with_equivalence_key=result.with_equivalence_key,
        no_prescription_notice=result.no_prescription_notice,
        overrides_capped=result.overrides_capped,
    )


def close_what_became_controlled(settings: Settings) -> controlled.Withdrawn:
    """After an import: open orders, watches and request items for a medicine that is now
    controlled are ended (docs/04 R-C6; docs/09 FR-24). Runs as the app, like any service.
    """
    engine = make_engine(settings.database_url)
    try:
        clock = AppClock(engine, demo_mode=settings.demo_mode)
        sessions = sessionmaker(engine, expire_on_commit=False)
        return controlled.withdraw_everything(sessions, clock)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_FILE)
    arguments = parser.parse_args()
    settings = load_settings()
    configure_logging(settings.log_level)
    (migrator_url,) = required(settings, "database_migrator_url")
    engine = create_engine(migrator_url)
    try:
        with engine.begin() as connection:
            result = import_from_folder(connection, arguments.folder, arguments.rules)
        log_result(result)
    finally:
        engine.dispose()
    withdrawn = close_what_became_controlled(settings)
    log.info(
        "controlled_medicines_withdrawn",
        orders_cancelled=withdrawn.orders,
        claims_ended=withdrawn.claims,
        request_items_ended=withdrawn.items,
    )


if __name__ == "__main__":
    main()
