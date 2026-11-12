"""The three database logins and what each may do (docs/05 §7, DB-D10; docs/12 §7).

- `dawalink_migrator` owns the tables and runs the migrations. Nothing else uses it.
- `dawalink_app` is what the API and the worker use: it reads and writes rows, and it can
  never change the schema, the catalog or an audit event.
- `dawalink_retention` only deletes what has passed its retention time.

`grant_privileges` starts from nothing and grants exactly the lists below, so removing a
line here removes the privilege on the next run. A test fails if a table is missing.
"""

from collections.abc import Mapping

from psycopg import sql
from sqlalchemy import Connection, create_engine, make_url

from dawalink.db.base import Base
from dawalink.domain.numbers import DB_STATEMENT_TIMEOUT_S

MIGRATOR = "dawalink_migrator"
APP = "dawalink_app"
RETENTION = "dawalink_retention"
ROLES = (MIGRATOR, APP, RETENTION)

READ: tuple[str, ...] = ("SELECT",)
WRITE: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE")
# Reference data and the catalog: changed only by the import and by migrations.
_APP_READS_ONLY = (
    "districts",
    "pricing_tiers",
    "catalog_imports",
    "products",
    "product_ingredients",
)
# Logs the app adds to and never changes.
_APP_APPENDS_ONLY = ("audit_events", "agent_tool_calls")
# The few tables where the app replaces rows.
_APP_MAY_DELETE = ("inventory_upload_rows", "pharmacy_hours", "claim_skips")

RETENTION_DELETES = (
    "conversations",
    "chat_messages",
    "proposals",
    "notifications",
    "sessions",
    "email_verification_tokens",
    "travel_time_cache",
    "claim_skips",
    "audit_events",
)
# A request and a claim are kept; only the client's location on them is erased.
RETENTION_ERASES = {
    "sourcing_requests": ("loc_lat", "loc_lon", "loc_source"),
    "claims": ("loc_lat", "loc_lon"),
}


class RoleSetupError(Exception):
    """Creating a login or granting its privileges failed. Never carries a password."""


def app_privileges() -> dict[str, tuple[str, ...]]:
    """What the app login may do on every table."""
    privileges: dict[str, tuple[str, ...]] = dict.fromkeys(Base.metadata.tables, WRITE)
    for table in _APP_READS_ONLY:
        privileges[table] = READ
    for table in _APP_APPENDS_ONLY:
        privileges[table] = ("SELECT", "INSERT")
    for table in _APP_MAY_DELETE:
        privileges[table] = (*WRITE, "DELETE")
    return privileges


def login_of(database_url: str) -> tuple[str, str]:
    """The user name and password in a database address."""
    url = make_url(database_url)
    return url.username or "", url.password or ""


def _run(connection: Connection, statement: sql.Composable) -> None:
    driver = connection.connection.driver_connection
    assert driver is not None
    driver.execute(statement)


def ensure_roles(admin_url: str, passwords: Mapping[str, str]) -> None:
    """Creates the three logins, or updates their passwords. Safe to run again.

    Run with the database's master login. It also adds the two extensions, which need more
    rights than the migrator has.
    """
    missing = [role for role in ROLES if not passwords.get(role)]
    if missing:
        raise RoleSetupError("No password given for: " + ", ".join(missing))
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            database = sql.Identifier(connection.engine.url.database or "")
            existing = set(
                connection.exec_driver_sql("SELECT rolname FROM pg_roles").scalars().all()
            )
            for role in ROLES:
                verb = "ALTER" if role in existing else "CREATE"
                try:
                    _run(
                        connection,
                        sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(
                            sql.Identifier(role), sql.Literal(passwords[role])
                        ),
                    )
                except Exception:
                    # The failed statement holds the password: say which login, nothing more.
                    raise RoleSetupError(f"Could not create or update {role}.") from None
                _run(
                    connection,
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        database, sql.Identifier(role)
                    ),
                )
            _run(
                connection,
                sql.SQL("ALTER ROLE {} SET statement_timeout = {}").format(
                    sql.Identifier(APP), sql.Literal(f"{DB_STATEMENT_TIMEOUT_S}s")
                ),
            )
            _run(
                connection,
                sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(
                    sql.Identifier(MIGRATOR)
                ),
            )
            for extension in ("citext", "pg_trgm"):
                _run(
                    connection,
                    sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(sql.Identifier(extension)),
                )
            # A database prepared before these logins existed has this table under the master.
            _run(
                connection,
                sql.SQL("ALTER TABLE IF EXISTS alembic_version OWNER TO {}").format(
                    sql.Identifier(MIGRATOR)
                ),
            )
    finally:
        engine.dispose()


def _grant(connection: Connection, privileges: tuple[str, ...], table: str, role: str) -> None:
    _run(
        connection,
        sql.SQL("GRANT {} ON {} TO {}").format(
            sql.SQL(", ").join(sql.SQL(p) for p in privileges),
            sql.Identifier(table),
            sql.Identifier(role),
        ),
    )


def grant_privileges(migrator_url: str) -> None:
    """Gives the app and retention logins exactly their privileges. Safe to run again.

    Run with the migrator login, which owns the tables.
    """
    engine = create_engine(migrator_url)
    try:
        with engine.begin() as connection:
            for role in (APP, RETENTION):
                name = sql.Identifier(role)
                _run(
                    connection,
                    sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(name),
                )
                _run(connection, sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(name))
            for table, privileges in app_privileges().items():
                _grant(connection, privileges, table, APP)
            for table in RETENTION_DELETES:
                _grant(connection, ("SELECT", "DELETE"), table, RETENTION)
            for table, columns in RETENTION_ERASES.items():
                _grant(connection, READ, table, RETENTION)
                _run(
                    connection,
                    sql.SQL("GRANT UPDATE ({}) ON {} TO {}").format(
                        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
                        sql.Identifier(table),
                        sql.Identifier(RETENTION),
                    ),
                )
    finally:
        engine.dispose()
