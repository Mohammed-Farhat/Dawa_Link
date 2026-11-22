"""A number too large for its column reaches the database (A#9's safety net; docs/09 FS-13).

Every number the API takes has a bound, so this should never happen. If it does, it is
the sender's mistake: a 422 VALIDATION_ERROR, never a server error, and the log keeps the
kind of error only.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.conftest import logged

A_BARCODE = 6_281_086_011_234


def test_a_number_no_column_can_hold_is_the_senders_mistake(
    app: FastAPI, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    def store_a_huge_number(request: Request) -> None:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT CAST(:sent AS integer)"), {"sent": A_BARCODE})

    app.add_api_route("/api/v1/_test/huge", store_a_huge_number, methods=["GET"])

    response = client.get("/api/v1/_test/huge")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert str(A_BARCODE) not in response.text
    (entry,) = logged(caplog, "database_number_out_of_range")
    assert (entry["error"], entry["request_id"]) == ("DataError", error["request_id"])
    assert str(A_BARCODE) not in str(entry)
