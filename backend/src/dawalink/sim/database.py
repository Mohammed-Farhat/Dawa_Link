"""A database of its own for every simulation run (docs/08 §2.3).

The app's database holds development chats, and its worker runs agent turns on a paid
model. A simulation must never touch it. So:
- a **template** database is prepared once: the tables, the logins' rights, the reference
  data and the catalog;
- every run starts from a **fresh copy** of the template, which takes about a second.

Every name starts with `dawalink_sim`, and this module refuses any other.
"""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, create_engine, make_url, text

from dawalink.config import Settings, required
from dawalink.db.reference import seed_areas, seed_districts, seed_pricing_tiers
from dawalink.db.roles import APP, MIGRATOR, RETENTION, ensure_roles, grant_privileges, login_of
from dawalink.ops.import_catalog import DEFAULT_FOLDER, catalog_is_available, import_from_folder
from dawalink.ops.prepare_db import run_migrations

PREFIX = "dawalink_sim"
TEMPLATE = f"{PREFIX}_template"


@dataclass(frozen=True)
class Addresses:
    """The four logins' addresses for one database (docs/05 §7)."""

    admin: str
    migrator: str
    app: str
    retention: str

    def on(self, database: str) -> "Addresses":
        def moved(url: str) -> str:
            return make_url(url).set(database=database).render_as_string(hide_password=False)

        return Addresses(
            *(moved(url) for url in (self.admin, self.migrator, self.app, self.retention))
        )


def addresses(settings: Settings) -> Addresses:
    """The app's four addresses, as the settings give them."""
    return Addresses(
        *required(
            settings,
            "database_admin_url",
            "database_migrator_url",
            "database_url",
            "database_retention_url",
        )
    )


def _checked(name: str) -> str:
    if not name.startswith(PREFIX) or not name.replace("_", "").isalnum():
        raise ValueError(f"A simulation database is named {PREFIX}_..., not {name!r}.")
    return name


def _outside_a_transaction(admin_url: str) -> Engine:
    # CREATE DATABASE and DROP DATABASE can't run inside a transaction.
    return create_engine(admin_url, isolation_level="AUTOCOMMIT")


def _exists(engine: Engine, name: str) -> bool:
    with engine.connect() as connection:
        found = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
        ).scalar()
    return found is not None


def ensure_template(settings: Settings, *, catalog_folder: Path = DEFAULT_FOLDER) -> Addresses:
    """Prepares the template once: tables, rights, reference data and the catalog."""
    base = addresses(settings)
    template = base.on(TEMPLATE)
    admin = _outside_a_transaction(base.admin)
    try:
        if _exists(admin, TEMPLATE):
            return template
        if not catalog_is_available(catalog_folder):
            raise FileNotFoundError(
                f"No catalog file in {catalog_folder}: the simulation needs the medicines. "
                "Run dawalink.ops.fetch_moph and dawalink.ops.build_catalog first."
            )
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{TEMPLATE}"'))
    finally:
        admin.dispose()

    passwords = {
        role: login_of(url)[1]
        for role, url in ((MIGRATOR, base.migrator), (APP, base.app), (RETENTION, base.retention))
    }
    ensure_roles(template.admin, passwords)
    run_migrations(template.migrator)
    grant_privileges(template.migrator)
    engine = create_engine(template.migrator)
    try:
        with engine.begin() as connection:
            seed_pricing_tiers(connection)
            seed_districts(connection)
            seed_areas(connection)
            import_from_folder(connection, catalog_folder)
    finally:
        engine.dispose()
    return template


def fresh(settings: Settings, name: str) -> Addresses:
    """A new copy of the template under `name`, replacing an earlier one of that name."""
    name = _checked(name)
    if name == TEMPLATE:
        raise ValueError("The template is not a database to run in.")
    ensure_template(settings)
    admin = _outside_a_transaction(addresses(settings).admin)
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{TEMPLATE}"'))
    finally:
        admin.dispose()
    return addresses(settings).on(name)


def drop(settings: Settings, name: str) -> None:
    name = _checked(name)
    admin = _outside_a_transaction(addresses(settings).admin)
    try:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()
