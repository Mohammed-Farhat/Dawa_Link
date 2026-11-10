"""FX-10: the database is unreachable."""

import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import text

from dawalink.domain.numbers import DB_CONNECT_TIMEOUT_S
from tests.conftest import logged


def test_health_still_answers_200_and_says_the_database_is_down(
    client_without_database: TestClient,
) -> None:
    started = time.monotonic()

    response = client_without_database.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "db": "down", "version": "test-version"}
    # The load balancer gives up after a few seconds, so the answer must come quickly.
    assert time.monotonic() - started < DB_CONNECT_TIMEOUT_S + 1


def test_an_endpoint_that_needs_the_database_answers_503_and_leaves_a_trail(
    app_without_database: FastAPI,
    client_without_database: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def read_something(request: Request) -> None:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    app_without_database.add_api_route("/api/v1/_test/read", read_something, methods=["GET"])

    response = client_without_database.get("/api/v1/_test/read")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "SERVICE_UNAVAILABLE"
    assert "127.0.0.1" not in response.text
    trail = logged(caplog, "database_unavailable")
    assert [entry["request_id"] for entry in trail] == [error["request_id"]]
