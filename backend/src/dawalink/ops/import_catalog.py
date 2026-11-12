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

from dawalink.catalog.importer import ImportResult, import_catalog
from dawalink.catalog.moph import read_catalog
from dawalink.catalog.rules import DEFAULT_RULES_FILE, load_rules
from dawalink.config import load_settings, required
from dawalink.db.models import Product
from dawalink.observability.logging import configure_logging
from dawalink.ops.build_catalog import CATALOG_FILE, DETAILS_FILE

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


if __name__ == "__main__":
    main()
