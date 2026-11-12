"""The database step that runs before the services start (docs/12 §7; FO-1)."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from dawalink.ops.prepare_db import DatabaseNotReady, run_migrations, wait_for_database
from tests.conftest import UNREACHABLE_DATABASE, DatabaseUrls


def test_waiting_returns_as_soon_as_the_database_answers(test_database_url: str) -> None:
    sleeps: list[float] = []

    wait_for_database(test_database_url, timeout_s=5, sleep=sleeps.append)

    assert sleeps == []


def test_waiting_gives_up_after_the_timeout() -> None:
    sleeps: list[float] = []

    with pytest.raises(DatabaseNotReady):
        wait_for_database(UNREACHABLE_DATABASE, timeout_s=3, sleep=sleeps.append)

    assert sleeps == [1.0, 1.0, 1.0]


def test_migrations_run_and_running_them_twice_is_safe(urls: DatabaseUrls) -> None:
    run_migrations(urls.migrator)
    run_migrations(urls.migrator)

    engine = create_engine(urls.migrator)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT to_regclass('alembic_version')")).scalar()
    finally:
        engine.dispose()


def test_a_missing_alembic_file_is_explained(urls: DatabaseUrls, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="backend folder"):
        run_migrations(urls.migrator, tmp_path / "alembic.ini")
