"""FX-11, FX-12: the database is there but slow, or has no free connection. And what the
log keeps of an error the database raised (docs/09 FS-13)."""

import json
import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from dawalink.db.session import make_engine
from dawalink.domain.numbers import DB_CONNECT_TIMEOUT_S
from dawalink.observability.logging import configure_logging
from tests.conftest import DatabaseUrls, logged

A_KEY = "test-of-a-slow-statement"


def test_a_statement_that_is_cut_off_answers_503_and_undoes_what_came_before_it(
    app: FastAPI, client: TestClient, urls: DatabaseUrls, caplog: pytest.LogCaptureFixture
) -> None:
    """FX-11. The cut-off is the database's own (N-40), set short here so nothing waits."""

    def write_then_wait(request: Request) -> None:
        with request.app.state.engine.begin() as connection:
            connection.execute(
                text("INSERT INTO app_state (key, value) VALUES (:key, '1'::jsonb)"),
                {"key": A_KEY},
            )
            connection.execute(text("SET LOCAL statement_timeout = '50ms'"))
            connection.execute(text("SELECT pg_sleep(2)"))

    app.add_api_route("/api/v1/_test/slow", write_then_wait, methods=["GET"])
    owner = create_engine(urls.migrator)
    started = time.monotonic()

    response = client.get("/api/v1/_test/slow")

    waited = time.monotonic() - started
    with owner.begin() as connection:
        # Read, and removed in case the write was kept: the next run starts clean.
        kept = connection.execute(
            text("DELETE FROM app_state WHERE key = :key RETURNING key"), {"key": A_KEY}
        ).all()
    owner.dispose()
    assert waited < 1.5
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert len(logged(caplog, "database_unavailable")) == 1
    assert kept == []


def test_with_no_free_connection_the_answer_is_a_quick_503(
    app: FastAPI, client: TestClient, test_database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    """FX-12: a pool of one, and that one is taken."""
    tiny = create_engine(test_database_url, pool_size=1, max_overflow=0, pool_timeout=0.2)
    app.state.engine = tiny

    def read_something(request: Request) -> None:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    app.add_api_route("/api/v1/_test/read", read_something, methods=["GET"])

    with tiny.connect():
        started = time.monotonic()
        response = client.get("/api/v1/_test/read")
        waited = time.monotonic() - started
    after = client.get("/api/v1/_test/read")
    tiny.dispose()

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert waited < 1.5
    assert [entry["error"] for entry in logged(caplog, "database_unavailable")] == ["TimeoutError"]
    # The connection is free again: the next request is served.
    assert after.status_code == 200


def test_the_apps_own_engine_never_waits_long_for_a_connection(test_database_url: str) -> None:
    """FX-12: the library's own wait is 30 seconds."""
    engine = make_engine(test_database_url)

    assert engine.pool.timeout() == DB_CONNECT_TIMEOUT_S  # type: ignore[attr-defined]
    assert engine.hide_parameters is True
    engine.dispose()


def test_an_error_of_the_database_is_logged_without_the_values_it_was_given(
    capsys: pytest.CaptureFixture[str], app: FastAPI, client: TestClient
) -> None:
    """FS-13: PostgreSQL repeats the value in its own message ("invalid input … "x""), and
    the statement's values come with the error. Neither may reach a log line."""

    def store_what_was_sent(request: Request) -> None:
        with request.app.state.engine.connect() as connection:
            connection.execute(
                text("SELECT CAST(:sent AS integer)"), {"sent": "someone@example.com"}
            )

    app.add_api_route("/api/v1/_test/refused", store_what_was_sent, methods=["GET"])
    # The log's lines go where the output is at this moment: the test's own capture.
    configure_logging("INFO")

    response = client.get("/api/v1/_test/refused")

    written = capsys.readouterr().out
    assert response.status_code == 500
    assert "someone@example.com" not in written
    assert "someone@example.com" not in response.text
    (line,) = [
        json.loads(row)
        for row in written.splitlines()
        if row.startswith("{") and json.loads(row).get("event") == "unhandled_error"
    ]
    # What is kept: the kind of error, the database's own code for it, and where it happened.
    assert "DataError" in line["exception"]
    assert "SQLSTATE 22P02" in line["exception"]
    assert "store_what_was_sent" in line["exception"]
