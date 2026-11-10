"""The one error format (docs/06 §3.1), shown through small test-only routes."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from dawalink.api.errors import ApiError, ErrorCode
from tests.conftest import logged


class Item(BaseModel):
    qty: int = Field(ge=1, le=3)


class Basket(BaseModel):
    items: list[Item]


def add_test_routes(app: FastAPI) -> None:
    def explode() -> None:
        raise RuntimeError("connection string postgresql://user:hunter2@db leaked")

    def not_yours() -> None:
        raise ApiError(ErrorCode.NOT_FOUND, details={"hint": "kept"})

    def take(basket: Basket) -> dict[str, int]:
        return {"count": len(basket.items)}

    def teapot() -> None:
        raise HTTPException(status_code=418, detail="internal note")

    app.add_api_route("/api/v1/_test/explode", explode, methods=["GET"])
    app.add_api_route("/api/v1/_test/not-yours", not_yours, methods=["GET"])
    app.add_api_route("/api/v1/_test/basket", take, methods=["POST"])
    app.add_api_route("/api/v1/_test/teapot", teapot, methods=["GET"])


def test_an_unknown_path_is_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/nothing-here")

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "NOT_FOUND"
    assert error["message"]
    assert error["details"] == {}
    assert error["request_id"] == response.headers["X-Request-ID"]


def test_a_wrong_method_is_refused(client: TestClient) -> None:
    response = client.post("/api/v1/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_an_api_error_answers_with_its_code_and_details(app: FastAPI, client: TestClient) -> None:
    add_test_routes(app)

    response = client.get("/api/v1/_test/not-yours")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["details"] == {"hint": "kept"}


def test_a_validation_error_lists_each_field(app: FastAPI, client: TestClient) -> None:
    add_test_routes(app)

    response = client.post("/api/v1/_test/basket", json={"items": [{"qty": 1}, {"qty": 9}]})

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert [field["field"] for field in error["details"]["fields"]] == ["items[1].qty"]
    assert error["details"]["fields"][0]["problem"]


def test_a_missing_body_is_a_validation_error(app: FastAPI, client: TestClient) -> None:
    add_test_routes(app)

    response = client.post("/api/v1/_test/basket")

    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"] == [
        {"field": "body", "problem": "Field required"}
    ]


def test_an_unexpected_error_hides_its_details_and_leaves_a_trail(
    app: FastAPI, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    add_test_routes(app)

    response = client.get("/api/v1/_test/explode")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in response.text
    assert "RuntimeError" not in response.text
    trail = logged(caplog, "unhandled_error")
    assert [entry["request_id"] for entry in trail] == [error["request_id"]]
    assert response.headers["X-Request-ID"] == error["request_id"]


def test_a_status_outside_the_catalog_is_treated_as_unexpected(
    app: FastAPI, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    add_test_routes(app)

    response = client.get("/api/v1/_test/teapot")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "internal note" not in response.text
    assert [entry["status"] for entry in logged(caplog, "unexpected_http_error")] == [418]
