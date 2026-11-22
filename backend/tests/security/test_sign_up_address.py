"""A sign-up whose network address isn't known (docs/04 R-AU5, R-AU8; docs/10 TH-41).

In AWS the visitor's address is the one CloudFront states. If that header goes missing,
every visitor would seem to be the load balancer, and the limit per address would stop all
sign-ups after five. The limit is then not counted at all, as for a login (N-52).
"""

import pytest
from sqlalchemy import select

from dawalink.api.routes import accounts
from dawalink.db.models import User
from tests.api.conftest import Api, api  # noqa: F401  (the fixture)
from tests.services.conftest import world  # noqa: F401  (the fixture)

NEW = {
    "password": "A long enough passphrase, 1",
    "first_name": "Nour",
    "last_name": "Khoury",
    "birth_date": "1990-05-17",
    "district_id": 1,
    "accept_terms": True,
}


def test_without_a_known_address_no_sign_up_is_refused_for_the_others(
    api: Api,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(accounts, "stated_address", lambda request, settings: None)
    http = api.http(assistant=False)

    answers = [
        http.post("/api/v1/auth/register/client", json=NEW | {"email": f"n{number}@example.org"})
        for number in range(7)
    ]

    assert [answer.status_code for answer in answers] == [202] * 7
    # Nothing is stored to count later either: the database's own count (R-AU5) would
    # otherwise put them all under one address.
    hashes = api.world.session.execute(
        select(User.signup_ip_hash).where(User.email.like("n%@example.org"))
    ).scalars()
    assert list(hashes) == [None] * 7


def test_with_a_known_address_the_sixth_sign_up_is_refused(api: Api) -> None:  # noqa: F811
    """The same seven sign-ups from one known address: the limit holds as before."""
    http = api.http(assistant=False)

    answers = [
        http.post("/api/v1/auth/register/client", json=NEW | {"email": f"k{number}@example.org"})
        for number in range(7)
    ]

    assert [answer.status_code for answer in answers] == [202] * 5 + [429] * 2
