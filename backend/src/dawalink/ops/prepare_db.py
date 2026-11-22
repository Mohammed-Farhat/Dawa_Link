"""Prepares the database before the services start: python -m dawalink.ops.prepare_db

Run from the backend folder (where alembic.ini is). Running it twice is safe (docs/12 §7):
1. waits for the database;
2. creates or updates the three database logins (docs/05 DB-D10);
3. applies the migrations, as the migrator login;
4. gives the app and retention logins exactly their privileges;
5. writes the reference data (discount tiers, districts, areas);
6. imports the catalog, if there are no products yet and the catalog file is there; if
   there are, sets their prescription marks from the file (nothing else about them changes);
7. in demo mode, adds the demo data if there are no pharmacies yet. Without a catalog it
   stops instead: pharmacies seeded then would stay without stock for good.

If it fails, the services must not be updated: the old version keeps running (FO-1).
"""

import argparse
import time
from collections.abc import Callable
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, make_url

from dawalink.config import ConfigError, Settings, load_settings, required
from dawalink.db.reference import seed_areas, seed_districts, seed_pricing_tiers
from dawalink.db.roles import APP, MIGRATOR, RETENTION, ensure_roles, grant_privileges, login_of
from dawalink.db.session import database_answer, make_engine
from dawalink.domain.clock import SystemClock
from dawalink.observability.logging import configure_logging
from dawalink.ops.import_catalog import (
    DEFAULT_FOLDER,
    catalog_is_available,
    catalog_is_empty,
    import_from_folder,
    log_result,
    refresh_marks_from_folder,
)
from dawalink.ops.seed_demo import (
    DEFAULT_SEED,
    NoCatalogYet,
    has_pharmacies,
    move_demo_pins_onto_land,
    refuse_without_a_catalog,
    seed_demo,
    set_demo_passwords,
)

log = structlog.get_logger(__name__)


class DatabaseNotReady(Exception):
    pass


class DatabaseLoginRefused(DatabaseNotReady):
    """The database answered and refused a login: a wrong password, user or database name.
    Said at once, with the setting to fix, rather than after the whole wait (docs/09 FO-1)."""


def wait_for_database(
    database_url: str,
    *,
    timeout_s: float,
    setting: str = "DATABASE_URL",
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Waits until the database answers. `setting` names the address in the error, which
    shows the login's name and never its password."""
    engine = make_engine(database_url)
    try:
        waited = 0.0
        while (answer := database_answer(engine)) != "up":
            if answer == "login_refused":
                raise DatabaseLoginRefused(
                    f"The database refused the login of {setting} "
                    f"(user {make_url(database_url).username}): check its password, its "
                    "user name and its database name."
                )
            if waited >= timeout_s:
                raise DatabaseNotReady(
                    f"The database did not answer {setting} within {timeout_s:.0f} s."
                )
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


def login_passwords(settings: Settings) -> tuple[str, str, dict[str, str]]:
    """The master and migrator addresses, and each login's password.

    The login names are fixed, because a trigger and the grants name them.
    """
    admin_url, migrator_url, app_url, retention_url = required(
        settings,
        "database_admin_url",
        "database_migrator_url",
        "database_url",
        "database_retention_url",
    )
    passwords: dict[str, str] = {}
    wrong: list[str] = []
    for setting, role, url in (
        ("DATABASE_MIGRATOR_URL", MIGRATOR, migrator_url),
        ("DATABASE_URL", APP, app_url),
        ("DATABASE_RETENTION_URL", RETENTION, retention_url),
    ):
        user, password = login_of(url)
        if user != role or not password:
            wrong.append(f"{setting} (must log in as {role}, with a password)")
        passwords[role] = password
    if wrong:
        raise ConfigError("Missing or invalid settings: " + ", ".join(wrong))
    return admin_url, migrator_url, passwords


def prepare(
    settings: Settings,
    *,
    wait_seconds: float = 60.0,
    seed: int = DEFAULT_SEED,
    catalog_folder: Path = DEFAULT_FOLDER,
) -> None:
    admin_url, migrator_url, passwords = login_passwords(settings)
    wait_for_database(admin_url, timeout_s=wait_seconds, setting="DATABASE_ADMIN_URL")
    ensure_roles(admin_url, passwords)
    # The migrator's password was just set from its own address, so a refusal here means
    # that address names another server or database than the master's.
    wait_for_database(migrator_url, timeout_s=wait_seconds, setting="DATABASE_MIGRATOR_URL")
    run_migrations(migrator_url)
    grant_privileges(migrator_url)

    engine = create_engine(migrator_url)
    try:
        with engine.begin() as connection:
            seed_pricing_tiers(connection)
            districts = seed_districts(connection)
            areas = seed_areas(connection)
        log.info("reference_data_written", districts=districts, areas=areas)

        with engine.begin() as connection:
            if not catalog_is_empty(connection):
                log.info("catalog_import_skipped", reason="products already exist")
                # The Ministry's no-prescription marks came after the first imports: a
                # database with its catalog gets them, and loses them, from the file too.
                if catalog_is_available(catalog_folder):
                    refresh_marks_from_folder(connection, catalog_folder)
            elif not catalog_is_available(catalog_folder):
                # Not an error: the app runs, but there is nothing to search for yet.
                log.warning("catalog_import_skipped", reason="no catalog file in data/moph")
            else:
                log_result(import_from_folder(connection, catalog_folder))

        if settings.demo_mode:
            with engine.begin() as connection:
                if has_pharmacies(connection):
                    log.info("demo_seed_skipped", reason="pharmacies already exist")
                    # A database seeded before 2026-11-18 has demo pharmacies at random
                    # points, some in the sea.
                    moved = move_demo_pins_onto_land(connection, now=SystemClock().now())
                    if moved:
                        log.info("demo_pins_moved_onto_land", pharmacies=moved)
                else:
                    refuse_without_a_catalog(connection)
                    result = seed_demo(connection, seed=seed, now=SystemClock().now())
                    log.info(
                        "demo_seeded",
                        pharmacies=result.pharmacies,
                        clients=result.clients,
                        inventory_items=result.inventory_items,
                    )
                if settings.demo_accounts_password is not None:
                    # One password for every demo account, from the settings: never in git.
                    accounts = set_demo_passwords(
                        connection, settings.demo_accounts_password.get_secret_value()
                    )
                    log.info("demo_passwords_set", accounts=accounts)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-seconds", type=float, default=60.0)
    arguments = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.log_level)
    try:
        prepare(settings, wait_seconds=arguments.wait_seconds)
    except (DatabaseNotReady, NoCatalogYet) as stopped:
        # A sentence for the person running it, and a failed exit: the services must not
        # be updated (FO-1).
        raise SystemExit(str(stopped)) from None
    log.info("database_prepared", version=settings.app_version)


if __name__ == "__main__":
    main()
