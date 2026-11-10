"""CORS: only the website may call the API from a browser (docs/06 §2.1)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import WEBSITE

OTHER_SITE = "https://evil.example"


def preflight(client: TestClient, origin: str) -> dict[str, str]:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key",
        },
    )
    return {name.lower(): value for name, value in response.headers.items()}


def test_the_website_may_send_the_login_and_idempotency_headers(
    client_without_database: TestClient,
) -> None:
    headers = preflight(client_without_database, WEBSITE)

    assert headers["access-control-allow-origin"] == WEBSITE
    allowed = headers["access-control-allow-headers"].lower()
    assert all(name in allowed for name in ("authorization", "content-type", "idempotency-key"))
    assert headers["access-control-max-age"] == "7200"
    assert "access-control-allow-credentials" not in headers


def test_another_site_gets_no_permission(client_without_database: TestClient) -> None:
    assert "access-control-allow-origin" not in preflight(client_without_database, OTHER_SITE)

    response = client_without_database.get("/api/v1/health", headers={"Origin": OTHER_SITE})

    assert "access-control-allow-origin" not in response.headers


def test_the_website_can_read_the_request_id(client_without_database: TestClient) -> None:
    response = client_without_database.get("/api/v1/health", headers={"Origin": WEBSITE})

    assert response.headers["access-control-allow-origin"] == WEBSITE
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()


def test_the_website_can_read_an_unexpected_error_too(
    app_without_database: FastAPI, client_without_database: TestClient
) -> None:
    def explode() -> None:
        raise RuntimeError("boom")

    app_without_database.add_api_route("/api/v1/_test/explode", explode, methods=["GET"])

    response = client_without_database.get("/api/v1/_test/explode", headers={"Origin": WEBSITE})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == WEBSITE
