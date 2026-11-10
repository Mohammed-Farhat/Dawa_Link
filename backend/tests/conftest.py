"""Shared test setup. Run from the backend folder: uv run --env-file ../.env pytest"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from dawalink.api.main import create_app
from dawalink.config import Settings
from dawalink.domain.numbers import DB_CONNECT_TIMEOUT_S
from dawalink.observability.logging import configure_logging

WEBSITE = "http://localhost:5173"
# Nothing listens on port 1, so connecting always fails: this is "the database is down".
UNREACHABLE_DATABASE = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/nowhere"


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


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """A separate `<name>_test` database next to the development one, created if missing."""
    base = os.environ.get("DATABASE_URL")
    if not base:
        pytest.exit("DATABASE_URL is not set. Run: uv run --env-file ../.env pytest", 2)
    url = make_url(base)
    test_url = url.set(database=f"{url.database}_test")
    admin = create_engine(
        url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": DB_CONNECT_TIMEOUT_S},
    )
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": test_url.database},
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{test_url.database}"'))
    except OperationalError:
        pytest.exit("PostgreSQL isn't reachable. Run: docker compose up -d postgres", 2)
    finally:
        admin.dispose()
    return test_url.render_as_string(hide_password=False)


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
