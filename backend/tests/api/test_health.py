"""GET /health with the database up (docs/06 §6.1), and the headers every response carries."""

import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from dawalink.api import health as health_module
from dawalink.domain.numbers import HEALTH_DB_WAIT_S
from tests.conftest import logged


def test_health_is_ok_when_the_database_answers(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "version": "test-version"}


def test_every_response_has_a_request_id_and_is_never_cached(client: TestClient) -> None:
    first = client.get("/api/v1/health")
    second = client.get("/api/v1/health")

    assert len(first.headers["X-Request-ID"]) == 32
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]
    assert first.headers["Cache-Control"] == "no-store"


def test_requests_are_logged_once_but_healthy_health_checks_are_not(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    client.get("/api/v1/health")
    client.get("/api/v1/nothing-here?q=panadol")

    assert [(entry["path"], entry["status"]) for entry in logged(caplog, "request")] == [
        ("/api/v1/nothing-here", 404)
    ]


def test_a_database_that_doesnt_answer_in_time_is_down_and_is_asked_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A#6: the check answers within its wait whatever the database does, and a database
    that hangs is never asked again while the first question is out."""
    release = threading.Event()
    asked: list[int] = []

    def hangs(_: Engine) -> bool:
        asked.append(1)
        release.wait(30)
        return True

    monkeypatch.setattr(health_module, "database_is_up", hangs)
    try:
        started = time.monotonic()
        first = client.get("/api/v1/health")
        took = time.monotonic() - started
        second = client.get("/api/v1/health")
    finally:
        release.set()

    assert first.status_code == second.status_code == 200
    assert first.json()["db"] == second.json()["db"] == "down"
    assert first.json()["status"] == "degraded"
    assert took < HEALTH_DB_WAIT_S + 1
    assert len(asked) == 1
