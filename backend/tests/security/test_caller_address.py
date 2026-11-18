"""Whose network address a request counts under (docs/04 R-AU8; docs/09 FS-21; docs/10
TH-41). The sign-up limit is counted per address, so a visitor must not be able to choose
theirs."""

from pathlib import Path

import pytest
from starlette.requests import Request

from dawalink.api.deps import caller_address, stated_address
from tests.api.conftest import Api, api, code_of  # noqa: F401  (the fixture)
from tests.conftest import UNREACHABLE_DATABASE, logged, make_settings
from tests.services.conftest import world  # noqa: F401  (the fixture)

NEW = {
    "password": "A long enough passphrase, 1",
    "first_name": "Nour",
    "last_name": "Khoury",
    "birth_date": "1990-05-17",
    "district_id": 1,
    "accept_terms": True,
}


def a_request(headers: dict[str, str], peer: str = "10.0.0.7") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
            "client": (peer, 44321),
        }
    )


def test_in_aws_the_address_is_the_one_cloudfront_states(tmp_path: Path) -> None:
    aws = make_settings(UNREACHABLE_DATABASE, tmp_path, app_env="aws")

    stated = a_request({"CloudFront-Viewer-Address": "198.51.100.10:46532"})
    ipv6 = a_request({"CloudFront-Viewer-Address": "2001:0db8:85a3:0000:0000:8a2e:0370:7334:46532"})
    forged = a_request(
        {"X-Forwarded-For": "203.0.113.99", "CloudFront-Viewer-Address": "198.51.100.10:46532"}
    )

    assert caller_address(stated, aws) == "198.51.100.10"
    assert caller_address(ipv6, aws) == "2001:0db8:85a3:0000:0000:8a2e:0370:7334"
    assert caller_address(forged, aws) == "198.51.100.10"


def test_a_header_a_visitor_can_write_is_never_believed(tmp_path: Path) -> None:
    """`X-Forwarded-For` is the visitor's own text. Nor is CloudFront's header believed
    where there is no CloudFront in front: on a laptop anyone could send it."""
    aws = make_settings(UNREACHABLE_DATABASE, tmp_path, app_env="aws")
    local = make_settings(UNREACHABLE_DATABASE, tmp_path, app_env="local")
    forged = a_request(
        {"X-Forwarded-For": "203.0.113.99", "X-Real-IP": "203.0.113.99", "Forwarded": "for=1.2.3.4"}
    )
    pretending = a_request({"CloudFront-Viewer-Address": "203.0.113.99:1"})

    assert caller_address(forged, aws) == "10.0.0.7"
    assert caller_address(forged, local) == "10.0.0.7"
    assert caller_address(pretending, local) == "10.0.0.7"


def test_a_new_forwarded_address_for_every_sign_up_dodges_nothing(api: Api) -> None:  # noqa: F811
    """FS-21: the sixth sign-up from one network is refused, whatever the headers claim."""
    http = api.http(assistant=False)

    answers = [
        http.post(
            "/api/v1/auth/register/client",
            json=NEW | {"email": f"n{number}@example.com"},
            headers={"X-Forwarded-For": f"203.0.113.{number}", "X-Real-IP": f"203.0.113.{number}"},
        )
        for number in range(6)
    ]

    assert [answer.status_code for answer in answers[:5]] == [202] * 5
    assert (answers[5].status_code, code_of(answers[5])) == (429, "SIGNUP_LIMIT")


def test_in_aws_without_cloudfronts_header_nobodys_address_is_known(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """If the distribution ever stops stating the visitor's address, every request would
    seem to come from the load balancer. A limit per address is then not counted at all,
    rather than counted for everybody together, and the log says so (docs/12 §4)."""
    aws = make_settings(UNREACHABLE_DATABASE, tmp_path, app_env="aws")
    local = make_settings(UNREACHABLE_DATABASE, tmp_path, app_env="local")

    assert stated_address(a_request({}), aws) is None
    assert len(logged(caplog, "visitor_address_not_stated")) == 1
    assert stated_address(a_request({"CloudFront-Viewer-Address": "198.51.100.10:1"}), aws) == (
        "198.51.100.10"
    )
    assert stated_address(a_request({}), local) == "10.0.0.7"
