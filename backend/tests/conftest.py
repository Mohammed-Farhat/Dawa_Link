"""Shared test setup. Run from the backend folder: uv run --env-file ../.env pytest

Tests use their own `<name>_test` database next to the development one. It is prepared once
per run exactly like a real one: the three logins, the migrations, the grants and the
reference data (docs/12 §7).
"""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from dawalink.api.main import create_app
from dawalink.config import Settings
from dawalink.db.reference import seed_districts, seed_pricing_tiers
from dawalink.db.roles import APP, MIGRATOR, RETENTION, ensure_roles, grant_privileges, login_of
from dawalink.domain.numbers import DB_CONNECT_TIMEOUT_S
from dawalink.observability.logging import configure_logging
from dawalink.ops.prepare_db import run_migrations

WEBSITE = "http://localhost:5173"
# Nothing listens on port 1, so connecting always fails: this is "the database is down".
UNREACHABLE_DATABASE = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/nowhere"
URL_SETTINGS = {
    "admin": "DATABASE_ADMIN_URL",
    "migrator": "DATABASE_MIGRATOR_URL",
    "app": "DATABASE_URL",
    "retention": "DATABASE_RETENTION_URL",
}


@dataclass(frozen=True)
class DatabaseUrls:
    """The four logins' addresses for one database (docs/05 §7)."""

    admin: str
    migrator: str
    app: str
    retention: str

    def on(self, database: str) -> "DatabaseUrls":
        """The same logins on another database of the same server."""
        return DatabaseUrls(
            *(
                make_url(url).set(database=database).render_as_string(hide_password=False)
                for url in (self.admin, self.migrator, self.app, self.retention)
            )
        )


@pytest.fixture(autouse=True)
def _json_logging() -> None:
    configure_logging("INFO")


def logged(caplog: pytest.LogCaptureFixture, event: str) -> list[dict[str, object]]:
    """Our log entries with this event name, as the dictionaries that become JSON lines."""
    return [
        record.msg
        for record in caplog.records
        if isinstance(record.msg, dict) and record.msg.get("event") == event
    ]


def run_as_admin(urls: DatabaseUrls, *statements: str) -> None:
    """Runs statements on the server's `postgres` database, outside any transaction."""
    admin = create_engine(
        make_url(urls.admin).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_S},
    )
    try:
        with admin.connect() as connection:
            for statement in statements:
                connection.execute(text(statement))
    except OperationalError:
        pytest.exit("PostgreSQL isn't reachable. Run: docker compose up -d postgres", 2)
    finally:
        admin.dispose()


def prepare_database(urls: DatabaseUrls) -> None:
    """Logins, migrations, grants and reference data: what `prepare_db` does, without data."""
    passwords = {
        role: login_of(url)[1]
        for role, url in ((MIGRATOR, urls.migrator), (APP, urls.app), (RETENTION, urls.retention))
    }
    ensure_roles(urls.admin, passwords)
    run_migrations(urls.migrator)
    grant_privileges(urls.migrator)
    engine = create_engine(urls.migrator)
    try:
        with engine.begin() as connection:
            seed_pricing_tiers(connection)
            seed_districts(connection)
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def development_urls() -> DatabaseUrls:
    missing = [name for name in URL_SETTINGS.values() if not os.environ.get(name)]
    if missing:
        pytest.exit(f"{', '.join(missing)} not set. Run: uv run --env-file ../.env pytest", 2)
    return DatabaseUrls(**{key: os.environ[name] for key, name in URL_SETTINGS.items()})


@pytest.fixture(scope="session")
def urls(development_urls: DatabaseUrls) -> DatabaseUrls:
    """The prepared `<name>_test` database."""
    name = f"{make_url(development_urls.admin).database}_test"
    test_urls = development_urls.on(name)
    admin = create_engine(
        make_url(development_urls.admin).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_S},
    )
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        pytest.exit("PostgreSQL isn't reachable. Run: docker compose up -d postgres", 2)
    finally:
        admin.dispose()
    prepare_database(test_urls)
    return test_urls


@pytest.fixture(scope="session")
def test_database_url(urls: DatabaseUrls) -> str:
    """The app login's address: what the API and the worker connect with."""
    return urls.app


def _connection(url: str) -> Iterator[Connection]:
    """A connection whose work is undone when the test ends."""
    engine = create_engine(url)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture
def db(urls: DatabaseUrls) -> Iterator[Connection]:
    """A connection as the tables' owner. Everything a test writes is rolled back."""
    yield from _connection(urls.migrator)


def make_settings(database_url: str, tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "app_version": "test-version",
        "database_url": database_url,
        "website_url": WEBSITE,
        "demo_mode": False,
        "log_level": "INFO",
        "worker_heartbeat_file": tmp_path / "heartbeat",
    }
    values.update(overrides)
    return Settings.model_validate(values)


@pytest.fixture
def settings(test_database_url: str, tmp_path: Path) -> Settings:
    return make_settings(test_database_url, tmp_path)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def app_without_database(tmp_path: Path) -> FastAPI:
    return create_app(make_settings(UNREACHABLE_DATABASE, tmp_path))


@pytest.fixture
def client_without_database(app_without_database: FastAPI) -> Iterator[TestClient]:
    with TestClient(app_without_database) as test_client:
        yield test_client
