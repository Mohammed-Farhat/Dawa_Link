"""GET /health with the database up (docs/06 §6.1), and the headers every response carries."""

import pytest
from fastapi.testclient import TestClient

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
