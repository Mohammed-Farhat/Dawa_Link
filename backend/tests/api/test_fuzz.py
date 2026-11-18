"""Random requests against the API's own description (docs/06 §9, with Schemathesis).

For every endpoint, requests are generated from its schema: ones that fit it, and ones
made to break it (wrong types, missing fields, values out of range). Whatever is sent,
the API never answers `500`, and an answer it describes has the shape it describes.

The requests are the same on every run (no randomness is left to chance), and nothing
outside the test database can be reached: no model, no routing service, no email.

It runs with every other test (about half a minute); alone: `pytest -m fuzz`. To look
harder after a change to the API, raise `EXAMPLES` for one run.
"""

from collections.abc import Callable
from typing import Any

import pytest
import schemathesis
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis.errors import Unsatisfiable
from schemathesis import APIOperation, Case, GenerationMode
from schemathesis.checks import not_a_server_error, response_schema_conformance
from schemathesis.core.result import Ok

from tests.api.conftest import Api
from tests.api.test_contract import callers, owner_of
from tests.conftest import WEBSITE

pytestmark = pytest.mark.fuzz

Operation = APIOperation[Any, Any, Any, Any]
AnyCase = Case[Any]

# Left out, and why.
NOT_HERE = {
    # A file, sent as a browser's form: its own tests send files of every bad kind
    # (tests/api/test_pharmacy_stock.py, tests/services/test_inventory.py).
    ("POST", "/api/v1/pharmacy/inventory/uploads"),
}

# How many requests of each kind an endpoint gets.
EXAMPLES = 12

SAME_EVERY_RUN = settings(
    max_examples=EXAMPLES,
    derandomize=True,
    database=None,
    deadline=None,
    phases=[Phase.generate],
    suppress_health_check=list(HealthCheck),
)


def sender(
    http: TestClient, operation: Operation, mode: GenerationMode, login: dict[str, str]
) -> Callable[[], None]:
    """The check of one endpoint: generated requests, each sent and its answer checked."""

    @SAME_EVERY_RUN
    @given(case=operation.as_strategy(generation_mode=mode))
    def send(case: AnyCase) -> None:
        sent: dict[str, Any] = case.as_transport_kwargs(
            base_url="http://testserver", headers={**login, "Origin": WEBSITE}
        )
        answer = http.request(**sent)
        case.validate_response(answer, checks=[not_a_server_error, response_schema_conformance])

    return send


@pytest.mark.parametrize("mode", [GenerationMode.POSITIVE, GenerationMode.NEGATIVE])
def test_no_request_makes_the_api_crash_or_answer_off_its_description(
    api: Api, mode: GenerationMode
) -> None:
    app = api.app(assistant=False)
    http = api.http(assistant=False)
    logins = callers(api)
    described = schemathesis.openapi.from_dict(app.openapi())

    tried = 0
    failures: list[str] = []
    for found in described.get_all_operations():
        assert isinstance(found, Ok), found
        operation = found.ok()
        if (operation.method.upper(), operation.path) in NOT_HERE:
            continue
        tried += 1
        try:
            sender(http, operation, mode, owner_of(operation.path, logins))()
        except Unsatisfiable:
            # Nothing can be sent wrong to an endpoint that takes nothing.
            assert mode is GenerationMode.NEGATIVE, operation.path
        except (Exception, BaseExceptionGroup) as problem:
            failures.append(f"{operation.method.upper()} {operation.path}: {problem}"[:700])

    assert tried >= 90, tried
    assert not failures, "\n\n".join(failures)
