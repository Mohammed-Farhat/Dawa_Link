"""Registration, logins and the checks every endpoint makes (docs/04 R-AU, SM-2;
docs/06 §2, §6.1; docs/10 TH-1 to TH-9)."""

import re
import threading
from datetime import timedelta
from typing import Any

import pyotp
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from dawalink.api.limits import Limiter
from dawalink.api.main import create_app
from dawalink.config import ConfigError
from dawalink.domain.numbers import (
    FAILED_LOGINS_PER_ADDRESS,
    PASSWORD_HASHES_AT_ONCE,
    RESEND_VERIFICATION_PER_DAY,
)
from dawalink.services import auth
from tests.api.conftest import PASSWORD, Api, code_of

EMAIL = "nour@example.com"
NEW = {
    "email": EMAIL,
    "password": PASSWORD,
    "first_name": "Nour",
    "last_name": "Khoury",
    "birth_date": "1990-05-17",
    "district_id": 1,
    "accept_terms": True,
}
OTHER = "Another long passphrase, 2"


def link_token(body: str) -> str:
    found = re.search(r"/verify-email\?token=(\S+)", body)
    assert found, body
    return found.group(1)


def logged_in(http: TestClient, password: str, email: str = EMAIL) -> dict[str, str]:
    """Logs in with this password, and returns the login header."""
    answer = http.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert answer.status_code == 200, answer.text
    return {"Authorization": f"Bearer {answer.json()['token']}"}


def logs_in(http: TestClient, password: str, email: str = EMAIL) -> bool:
    body = {"email": email, "password": password}
    return http.post("/api/v1/auth/login", json=body).status_code == 200


def live_sessions(api: Api, email: str = EMAIL) -> int:
    (count,) = api.world.one(
        "SELECT count(*) FROM sessions JOIN users ON users.id = user_id "
        "WHERE email = :e AND revoked_at IS NULL",
        e=email,
    )
    return int(count)


class TestRegistration:
    def test_a_new_client_confirms_the_email_then_logs_in(self, api: Api) -> None:
        http = api.http()

        answer = http.post("/api/v1/auth/register/client", json=NEW)

        assert answer.status_code == 202
        assert api.world.one(
            "SELECT status FROM client_profiles JOIN users ON id = user_id WHERE email = :e",
            e=NEW["email"],
        ) == ("UNVERIFIED",)
        ((to, subject, body),) = api.emails()
        assert (to, subject) == (NEW["email"], "Confirm your email for DawaLink")
        assert "log in with your password" in body

        confirmed = http.post("/api/v1/auth/verify-email", json={"token": link_token(body)})

        assert confirmed.status_code == 204
        # The link logs nobody in (the owner, 2026-11-22): the person logs in with the
        # password.
        me = http.get("/api/v1/auth/me", headers=logged_in(http, PASSWORD)).json()
        assert (me["email_verified"], me["client"]["status"]) == (True, "ACTIVE")
        assert me["full_name"] == "Nour Khoury"

    def test_the_link_answers_nothing_a_login_could_use(self, api: Api) -> None:
        """No token, no body at all, and no session made for the account."""
        http = api.http()
        http.post("/api/v1/auth/register/client", json=NEW)
        ((_, _, body),) = api.emails()

        confirmed = http.post("/api/v1/auth/verify-email", json={"token": link_token(body)})

        assert (confirmed.status_code, confirmed.content) == (204, b"")
        assert "token" not in confirmed.text
        assert api.world.one(
            "SELECT count(*) FROM sessions JOIN users ON users.id = user_id WHERE email = :e",
            e=NEW["email"],
        ) == (0,)

    @pytest.mark.parametrize("first", ["stranger", "owner"])
    def test_a_confirmation_link_never_hands_over_an_account(self, api: Api, first: str) -> None:
        """The takeover the link once allowed (the owner, 2026-11-22). Two people sign up
        with one address, in either order; the second sign-up replaces the first, and the
        owner follows the newest link, which is in their mailbox.

        Whatever the order: no session opened before the link works after it, the
        password that logs in is the last signer's only, and "forgot my password" then
        gives the account to whoever reads the mailbox, and ends every session."""
        stranger_password, owner_password = "A stranger's passphrase, 7", OTHER
        stranger, owner = api.http(), api.http()  # two people, two networks
        order = [(stranger, stranger_password), (owner, owner_password)]
        if first == "owner":
            order.reverse()
        before, newest = [], ""
        for http, password in order:
            assert http.post(
                "/api/v1/auth/register/client", json=NEW | {"password": password}
            ).is_success
            ((_, _, newest),) = api.emails()  # both go to the one mailbox, the owner's
            before.append(logged_in(http, password))  # logged in before confirming
        (_, first_password), (_, last_password) = order

        confirmed = owner.post("/api/v1/auth/verify-email", json={"token": link_token(newest)})

        assert (confirmed.status_code, confirmed.content) == (204, b"")
        for headers in before:
            assert owner.get("/api/v1/auth/me", headers=headers).status_code == 401
        assert live_sessions(api) == 0
        assert not logs_in(owner, first_password)
        # The last signer's password logs in. When that was the stranger, this is what is
        # left of the risk (docs/10): the owner takes the account back by the mailbox.
        last_signer = logged_in(stranger, last_password)

        assert owner.post("/api/v1/auth/password/forgot", json={"email": NEW["email"]}).is_success
        ((_, _, reset_email),) = [
            sent for sent in api.emails() if sent[1] == "Set a new password for DawaLink"
        ]
        found = re.search(r"/reset-password\?token=(\S+)", reset_email)
        assert found
        mailbox_password = "The mailbox's own passphrase, 9"
        reset = owner.post(
            "/api/v1/auth/password/reset",
            json={"token": found.group(1), "new_password": mailbox_password},
        )

        assert reset.status_code == 204
        assert owner.get("/api/v1/auth/me", headers=last_signer).status_code == 401
        assert live_sessions(api) == 0
        assert not logs_in(stranger, stranger_password)
        assert not logs_in(owner, owner_password)
        assert logs_in(owner, mailbox_password)

    def test_the_answer_never_says_whether_the_email_has_an_account(self, api: Api) -> None:
        """R-AU7: the same answer; the owner of a confirmed address gets "just log in",
        once a day, and their account is left as it is."""
        http = api.http()
        first = http.post("/api/v1/auth/register/client", json=NEW)
        ((_, _, body),) = api.emails()
        assert http.post("/api/v1/auth/verify-email", json={"token": link_token(body)}).is_success

        again = http.post("/api/v1/auth/register/client", json=NEW | {"first_name": "Someone"})
        third = http.post("/api/v1/auth/register/client", json=NEW | {"password": OTHER})

        assert (again.status_code, again.json()) == (first.status_code, first.json())
        assert third.json() == first.json()
        assert api.world.one("SELECT count(*) FROM users WHERE email = :e", e=NEW["email"]) == (1,)
        assert api.world.one("SELECT full_name FROM users WHERE email = :e", e=NEW["email"]) == (
            "Nour Khoury",
        )
        assert [subject for _, subject, _ in api.emails()] == [
            "You already have a DawaLink account"
        ]
        login = {"email": NEW["email"], "password": PASSWORD}
        assert http.post("/api/v1/auth/login", json=login).status_code == 200

    def test_a_sign_up_never_confirmed_is_replaced_by_the_next_one(self, api: Api) -> None:
        """Someone signs up with an address that isn't theirs, and logs in. Its owner then
        signs up: the owner's password and details win, the first signer's login and
        link end, and the owner gets a link of their own. The answer is the same 202."""
        http = api.http()
        taker = NEW | {"first_name": "Someone", "phone": "70 000 000", "district_id": 2}
        first = http.post("/api/v1/auth/register/client", json=taker)
        ((_, _, their_link),) = api.emails()
        theirs = http.post("/api/v1/auth/login", json={"email": NEW["email"], "password": PASSWORD})
        their_login = {"Authorization": f"Bearer {theirs.json()['token']}"}
        http.patch(
            "/api/v1/me/profile", json={"alternatives_ok_default": True}, headers=their_login
        )
        place = {"lat": 33.8959, "lon": 35.4828}
        assert http.put("/api/v1/me/home-place", json=place, headers=their_login).is_success
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "INSERT INTO search_history (client_id, query, searched_at) "
                "SELECT id, 'panadol', now() FROM users WHERE email = 'nour@example.com'"
            )
        for _ in range(5):  # and the account ends up locked
            http.post("/api/v1/auth/login", json={"email": NEW["email"], "password": "nope"})

        owner = http.post("/api/v1/auth/register/client", json=NEW | {"password": OTHER})

        assert (owner.status_code, owner.json()) == (first.status_code, first.json())
        assert api.world.one("SELECT count(*) FROM users WHERE email = :e", e=NEW["email"]) == (1,)
        assert http.get("/api/v1/auth/me", headers=their_login).status_code == 401
        old_password = {"email": NEW["email"], "password": PASSWORD}
        assert code_of(http.post("/api/v1/auth/login", json=old_password)) == "INVALID_CREDENTIALS"
        stale = http.post("/api/v1/auth/verify-email", json={"token": link_token(their_link)})
        assert code_of(stale) == "TOKEN_INVALID"
        ((_, subject, own_link),) = api.emails()
        assert subject == "Confirm your email for DawaLink"

        confirmed = http.post("/api/v1/auth/verify-email", json={"token": link_token(own_link)})

        assert confirmed.status_code == 204
        own_login = logged_in(http, OTHER)
        me = http.get("/api/v1/auth/me", headers=own_login).json()
        assert (me["full_name"], me["phone"], me["email_verified"]) == ("Nour Khoury", None, True)
        assert me["client"]["district"]["id"] == 1
        assert me["client"]["alternatives_ok_default"] is False
        assert http.get("/api/v1/me/home-place", headers=own_login).status_code == 404
        assert api.world.one("SELECT count(*) FROM search_history") == (0,)

    def test_signing_up_again_and_again_sends_a_days_links_at_most(self, api: Api) -> None:
        """N-47: one address gets no more confirmation emails by sign-ups than by asking
        for links again, and the answer never shows that the cap was reached."""
        answers = [
            # A new network each time: the sign-up limit per address is not what is tested.
            api.http().post("/api/v1/auth/register/client", json=NEW).status_code
            for _ in range(9)
        ]

        assert set(answers) == {202}
        assert api.world.one("SELECT count(*) FROM email_outbox WHERE template = 'CN-1'") == (
            RESEND_VERIFICATION_PER_DAY + 1,
        )

    def test_a_suspended_account_is_never_signed_up_again(self, api: Api) -> None:
        api.client("SUSPENDED", email=NEW["email"], email_verified_at=None)

        answer = api.http().post("/api/v1/auth/register/client", json=NEW | {"password": OTHER})

        assert answer.status_code == 202
        assert api.world.one(
            "SELECT status FROM client_profiles JOIN users ON id = user_id WHERE email = :e",
            e=NEW["email"],
        ) == ("SUSPENDED",)
        assert [subject for _, subject, _ in api.emails()] == [
            "You already have a DawaLink account"
        ]

    @pytest.mark.parametrize(
        ("password", "missing"),
        [
            ("Sh0rt!", ["length"]),
            ("no capital here 1!", ["capital"]),
            ("NO SMALL LETTER 1!", ["small"]),
            ("No number in it!", ["number"]),
            ("No symbol in it 1", ["symbol"]),
            ("qwertyuiop", ["capital", "number", "symbol"]),
        ],
    )
    def test_a_weak_password_is_refused_and_told_what_it_lacks(
        self, api: Api, password: str, missing: list[str]
    ) -> None:
        """R-AU1: 10 characters or more, with a capital letter, a small letter, a number
        and a symbol."""
        answer = api.http().post("/api/v1/auth/register/client", json=NEW | {"password": password})

        assert (answer.status_code, code_of(answer)) == (422, "WEAK_PASSWORD")
        assert answer.json()["error"]["details"]["missing"] == missing

    def test_a_common_word_with_numbers_and_symbols_around_it_is_refused(self, api: Api) -> None:
        assert not auth.password_gaps("Password123!")
        answer = api.http().post(
            "/api/v1/auth/register/client", json=NEW | {"password": "Password123!"}
        )

        # It holds every part of the rule, and is still "password" with decoration.
        assert (answer.status_code, code_of(answer)) == (422, "WEAK_PASSWORD")
        assert answer.json()["error"]["details"]["missing"] == ["uncommon"]

    def test_the_terms_must_be_accepted_and_the_district_must_exist(self, api: Api) -> None:
        http = api.http()

        no_terms = http.post("/api/v1/auth/register/client", json=NEW | {"accept_terms": False})
        nowhere = http.post("/api/v1/auth/register/client", json=NEW | {"district_id": 999})

        assert (code_of(no_terms), code_of(nowhere)) == ("VALIDATION_ERROR", "VALIDATION_ERROR")

    def test_too_many_sign_ups_from_one_network_are_refused(self, api: Api) -> None:
        http = api.http()
        for number in range(5):
            http.post(
                "/api/v1/auth/register/client", json=NEW | {"email": f"n{number}@example.com"}
            )

        sixth = http.post("/api/v1/auth/register/client", json=NEW | {"email": "n6@example.com"})

        assert (sixth.status_code, code_of(sixth)) == (429, "SIGNUP_LIMIT")

    def test_the_limit_never_tells_whether_an_email_was_known(self, api: Api) -> None:
        """docs/10 TH-3: four new sign-ups, one with someone's email, then one more. The
        sixth is refused whether that email had an account or not; counting only the
        accounts made would have let it through when it had."""
        http = api.http()
        api.client(email="rami@example.com")
        for number in range(4):
            http.post(
                "/api/v1/auth/register/client", json=NEW | {"email": f"n{number}@example.com"}
            )

        known = http.post("/api/v1/auth/register/client", json=NEW | {"email": "rami@example.com"})
        sixth = http.post("/api/v1/auth/register/client", json=NEW | {"email": "n6@example.com"})

        assert known.status_code == 202
        assert (sixth.status_code, code_of(sixth)) == (429, "SIGNUP_LIMIT")

    def test_a_phone_is_a_phone_at_sign_up_too(self, api: Api) -> None:
        """docs/10 TH-63: the field is read by DawaLink's team, so it holds a number or
        nothing, as in the profile."""
        http = api.http()

        words = http.post(
            "/api/v1/auth/register/client", json=NEW | {"phone": "<b>call me</b> 70 123 456"}
        )
        typed = http.post("/api/v1/auth/register/client", json=NEW | {"phone": " +961 70 123 456 "})

        assert (words.status_code, code_of(words)) == (422, "VALIDATION_ERROR")
        assert typed.status_code == 202
        assert api.world.one("SELECT phone FROM users WHERE email = :e", e=NEW["email"]) == (
            "+961 70 123 456",
        )

    def test_a_form_sent_back_for_a_mistake_is_not_a_sign_up(self, api: Api) -> None:
        """Someone who mistypes five times can still sign up."""
        http = api.http()
        for _ in range(6):
            weak = http.post("/api/v1/auth/register/client", json=NEW | {"password": "password"})
            assert code_of(weak) == "WEAK_PASSWORD"

        assert http.post("/api/v1/auth/register/client", json=NEW).status_code == 202

    def test_a_link_works_once_and_for_a_day(self, api: Api) -> None:
        http = api.http()
        http.post("/api/v1/auth/register/client", json=NEW)
        ((_, _, body),) = api.emails()
        token = link_token(body)

        assert http.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 204
        used = http.post("/api/v1/auth/verify-email", json={"token": token})
        unknown = http.post("/api/v1/auth/verify-email", json={"token": "x" * 43})

        assert (used.status_code, code_of(used)) == (400, "TOKEN_INVALID")
        assert code_of(unknown) == "TOKEN_INVALID"
        # The second use changed nothing: the account is confirmed once, nobody logged in.
        assert live_sessions(api) == 0
        assert api.world.one(
            "SELECT count(*) FROM audit_events WHERE action = 'client.verified'"
        ) == (1,)

    def test_an_old_link_is_refused(self, api: Api) -> None:
        http = api.http()
        http.post("/api/v1/auth/register/client", json=NEW)
        ((_, _, body),) = api.emails()
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE email_verification_tokens SET expires_at = now() - interval '1 minute'"
            )

        late = http.post("/api/v1/auth/verify-email", json={"token": link_token(body)})

        assert code_of(late) == "TOKEN_INVALID"

    def test_confirming_ends_every_other_link(self, api: Api) -> None:
        """TM-D7: a link works only while the address is unconfirmed. An earlier link, and
        one written after the confirmation (its email was still waiting to be sent), are
        refused."""
        http = api.http()
        http.post("/api/v1/auth/register/client", json=NEW)
        first = http.post("/api/v1/auth/login", json={"email": NEW["email"], "password": PASSWORD})
        headers = {"Authorization": f"Bearer {first.json()['token']}"}
        self.ask_again(api, http, headers)
        (_, _, one), (_, _, two) = api.emails()
        self.ask_again(api, http, headers)  # its email waits to be sent

        assert http.post("/api/v1/auth/verify-email", json={"token": link_token(two)}).is_success
        (three,) = [body for _, _, body in api.emails() if "/verify-email?" in body]

        for body in (one, three):
            late = http.post("/api/v1/auth/verify-email", json={"token": link_token(body)})
            assert (late.status_code, code_of(late)) == (400, "TOKEN_INVALID")

    def test_confirming_ends_every_earlier_login(self, api: Api) -> None:
        """Whoever logged in before the address was confirmed may not own it: after the
        link, nobody is logged in, and the password logs in again."""
        http = api.http()
        client = api.client("UNVERIFIED", email="rami@example.com")
        before = api.token(client)
        token = auth.new_verification_token(api.world.tx(), client)
        api.world.session.flush()

        confirmed = http.post("/api/v1/auth/verify-email", json={"token": token})

        assert confirmed.status_code == 204
        assert http.get("/api/v1/auth/me", headers=before).status_code == 401
        assert api.world.one(
            "SELECT count(*) FROM sessions WHERE user_id = :u AND revoked_at IS NULL", u=client
        ) == (0,)
        assert logs_in(http, PASSWORD, email="rami@example.com")

    def test_a_suspended_clients_link_confirms_nothing(self, api: Api) -> None:
        """Kept as it was before the link stopped logging in: a suspended client can't log
        in (SM-2),
        so the link is refused, the address stays unconfirmed, and the link stays as it
        was for after a reinstatement."""
        http = api.http()
        client = api.client("SUSPENDED", email="rami@example.com", email_verified_at=None)
        token = auth.new_verification_token(api.world.tx(), client)
        api.world.session.flush()

        refused = http.post("/api/v1/auth/verify-email", json={"token": token})

        assert (refused.status_code, code_of(refused)) == (403, "ACCOUNT_SUSPENDED")
        assert api.world.one("SELECT email_verified_at FROM users WHERE id = :u", u=client) == (
            None,
        )
        assert api.world.one(
            "SELECT used_at FROM email_verification_tokens WHERE user_id = :u", u=client
        ) == (None,)

    def test_a_new_password_ends_the_links_too(self, api: Api) -> None:
        """docs/10 TH-2: "every other login ends", and the links end with them."""
        http = api.http()
        client = api.client("UNVERIFIED", email="rami@example.com")
        headers = api.token(client)
        self.ask_again(api, http, headers)
        ((_, _, body),) = api.emails()

        changed = http.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": OTHER},
            headers=headers,
        )
        late = http.post("/api/v1/auth/verify-email", json={"token": link_token(body)})

        assert changed.status_code == 204
        assert code_of(late) == "TOKEN_INVALID"

    @staticmethod
    def ask_again(api: Api, http: TestClient, headers: dict[str, str]) -> None:
        with api.world.as_owner():
            # Two minutes pass: the wait between two emails is not what is tested.
            api.world.connection.exec_driver_sql(
                "UPDATE email_outbox SET created_at = created_at - interval '2 minutes'"
            )
        assert http.post("/api/v1/auth/verify-email/resend", headers=headers).status_code == 202

    def test_another_link_can_be_asked_for_once_a_minute(self, api: Api) -> None:
        http = api.http()
        client = api.client("UNVERIFIED")
        headers = api.token(client)

        first = http.post("/api/v1/auth/verify-email/resend", headers=headers)
        second = http.post("/api/v1/auth/verify-email/resend", headers=headers)

        assert first.status_code == 202
        assert (second.status_code, code_of(second)) == (429, "RATE_LIMITED")
        assert int(second.headers["Retry-After"]) <= 60
        assert len(api.emails()) == 1

    def test_and_only_so_many_times_a_day(self, api: Api) -> None:
        """N-47, docs/10 TH-53: nobody can make DawaLink send one address email after
        email. The first email is the sign-up's own; five more may be asked for."""
        http = api.http()
        client = api.client("UNVERIFIED")
        headers = api.token(client)

        answers = []
        for _ in range(7):
            answers.append(http.post("/api/v1/auth/verify-email/resend", headers=headers))
            with api.world.as_owner():
                # Two minutes pass: the wait between two emails is not what is tested.
                api.world.connection.exec_driver_sql(
                    "UPDATE email_outbox SET created_at = created_at - interval '2 minutes'"
                )

        assert [answer.status_code for answer in answers] == [202] * 6 + [429]
        assert code_of(answers[-1]) == "RATE_LIMITED"
        assert int(answers[-1].headers["Retry-After"]) == 3600


class TestLogin:
    def test_the_right_password_gives_a_token_that_logout_ends(self, api: Api) -> None:
        http = api.http()
        api.client(email="rami@example.com")

        logged_in = http.post(
            "/api/v1/auth/login", json={"email": "RAMI@example.com", "password": PASSWORD}
        )

        assert logged_in.status_code == 200
        headers = {"Authorization": f"Bearer {logged_in.json()['token']}"}
        assert http.get("/api/v1/auth/me", headers=headers).json()["role"] == "client"
        assert http.post("/api/v1/auth/logout", headers=headers).status_code == 204
        after = http.get("/api/v1/auth/me", headers=headers)
        assert (after.status_code, code_of(after)) == (401, "UNAUTHENTICATED")

    def test_only_a_hash_of_the_token_is_stored(self, api: Api) -> None:
        http = api.http()
        api.client(email="rami@example.com")

        token = http.post(
            "/api/v1/auth/login", json={"email": "rami@example.com", "password": PASSWORD}
        ).json()["token"]

        stored = [bytes(row[0]) for row in api.world.all("SELECT token_hash FROM sessions")]
        assert token.encode() not in stored
        assert all(len(digest) == 32 for digest in stored)

    def test_a_wrong_password_and_an_unknown_email_look_the_same(self, api: Api) -> None:
        http = api.http()
        api.client(email="rami@example.com")

        wrong = http.post(
            "/api/v1/auth/login", json={"email": "rami@example.com", "password": "not this one"}
        )
        nobody = http.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
        )

        assert wrong.status_code == nobody.status_code == 401
        assert wrong.json()["error"] | {"request_id": ""} == nobody.json()["error"] | {
            "request_id": ""
        }

    def test_five_failures_lock_the_account_even_for_the_right_password(self, api: Api) -> None:
        http = api.http()
        client = api.client(email="rami@example.com")
        for _ in range(5):
            http.post("/api/v1/auth/login", json={"email": "rami@example.com", "password": "nope"})

        locked = http.post(
            "/api/v1/auth/login", json={"email": "rami@example.com", "password": PASSWORD}
        )

        assert (locked.status_code, code_of(locked)) == (429, "ACCOUNT_LOCKED")
        assert 0 < locked.json()["error"]["details"]["retry_after"] <= 15 * 60 + 1
        assert "login.locked" in api.world.audit_actions(client)

    def test_an_email_nobody_has_locks_exactly_like_a_real_one(self, api: Api) -> None:
        """docs/10 TH-3: otherwise five wrong passwords would say who has an account."""
        http = api.http()
        api.client(email="rami@example.com")

        def five_then_one(email: str) -> list[tuple[int, str]]:
            answers = [
                http.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
                for _ in range(6)
            ]
            assert 0 < answers[-1].json()["error"]["details"]["retry_after"] <= 15 * 60 + 1
            return [(answer.status_code, code_of(answer)) for answer in answers]

        real = five_then_one("rami@example.com")
        nobody = five_then_one("nobody@example.com")
        someone_else = http.post(
            "/api/v1/auth/login", json={"email": "another@example.com", "password": "nope"}
        )

        assert real == nobody == [(401, "INVALID_CREDENTIALS")] * 5 + [(429, "ACCOUNT_LOCKED")]
        # An account's email is the same in capitals; so is one that nobody has.
        shouted = [
            http.post("/api/v1/auth/login", json={"email": email, "password": "nope"})
            for email in ("RAMI@EXAMPLE.COM", "NOBODY@Example.com")
        ]
        assert [code_of(answer) for answer in shouted] == ["ACCOUNT_LOCKED"] * 2
        # The lock is that email's own: nobody else is slowed down.
        assert someone_else.status_code == 401

    def test_thirty_failed_tries_from_one_network_stop_every_login_from_it(self, api: Api) -> None:
        """N-52 (the owner, Q48): an account's own lock stops guessing that account; this
        stops one visitor from trying a few passwords on each of many accounts."""
        http = api.http()
        api.client(email="rami@example.com")

        def a_try(number: int, password: str = "nope") -> Any:
            # A different email each time: no account's own lock is ever reached.
            body = {"email": f"someone{number}@example.com", "password": password}
            return http.post("/api/v1/auth/login", json=body)

        tries = [a_try(number) for number in range(FAILED_LOGINS_PER_ADDRESS)]
        one_more = a_try(99)
        the_right_password = http.post(
            "/api/v1/auth/login", json={"email": "rami@example.com", "password": PASSWORD}
        )

        assert {answer.status_code for answer in tries} == {401}
        for answer in (one_more, the_right_password):
            assert (answer.status_code, code_of(answer)) == (429, "RATE_LIMITED")
            assert 0 < int(answer.headers["Retry-After"]) <= 15 * 60 + 1
        assert "network" in one_more.json()["error"]["message"]

    def test_logins_that_work_are_never_counted(self, api: Api) -> None:
        """A room of people behind one address logs in as often as it likes."""
        http = api.http()
        api.client(email="rami@example.com")
        right = {"email": "rami@example.com", "password": PASSWORD}

        worked = [
            http.post("/api/v1/auth/login", json=right).status_code
            for _ in range(FAILED_LOGINS_PER_ADDRESS + 5)
        ]
        a_mistake = http.post("/api/v1/auth/login", json=right | {"password": "nope"})

        assert set(worked) == {200}
        assert (a_mistake.status_code, code_of(a_mistake)) == (401, "INVALID_CREDENTIALS")

    def test_a_locked_accounts_tries_count_for_the_network_too(self, api: Api) -> None:
        http = api.http()
        api.client(email="rami@example.com")
        wrong = {"email": "rami@example.com", "password": "nope"}

        answers = [
            http.post("/api/v1/auth/login", json=wrong)
            for _ in range(FAILED_LOGINS_PER_ADDRESS + 1)
        ]

        # Five wrong passwords, then "locked" until the network itself is stopped.
        assert [code_of(answer) for answer in answers[:6]] == ["INVALID_CREDENTIALS"] * 5 + [
            "ACCOUNT_LOCKED"
        ]
        assert code_of(answers[-1]) == "RATE_LIMITED"

    def test_a_lock_ends_by_itself(self, api: Api) -> None:
        http = api.http()
        api.client(email="rami@example.com")
        for _ in range(5):
            http.post("/api/v1/auth/login", json={"email": "rami@example.com", "password": "nope"})
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE users SET locked_until = now() - interval '1 second'"
            )

        again = http.post(
            "/api/v1/auth/login", json={"email": "rami@example.com", "password": PASSWORD}
        )

        assert again.status_code == 200

    def test_a_suspended_client_cant_log_in(self, api: Api) -> None:
        http = api.http()
        api.client("SUSPENDED", email="rami@example.com")

        answer = http.post(
            "/api/v1/auth/login", json={"email": "rami@example.com", "password": PASSWORD}
        )

        assert (answer.status_code, code_of(answer)) == (403, "ACCOUNT_SUSPENDED")

    def test_a_demo_account_without_a_password_cant_log_in(self, api: Api) -> None:
        http = api.http()
        api.world.make.client(person={"email": "seeded@example.com", "password_hash": "!"})

        answer = http.post(
            "/api/v1/auth/login", json={"email": "seeded@example.com", "password": "!"}
        )

        assert code_of(answer) == "INVALID_CREDENTIALS"

    def test_moving_the_demo_clock_logs_nobody_out(self, api: Api) -> None:
        """Sessions are counted in real time: a demo that jumps a day must not end them."""
        http = api.http()
        headers = api.token(api.client())

        api.world.later(days=30)
        # The worker's daily purge runs on that later day too, and must leave it alone.
        api.world.clock_tasks().run_daily_tasks()

        assert http.get("/api/v1/auth/me", headers=headers).status_code == 200

    def test_an_expired_session_is_refused(self, api: Api) -> None:
        http = api.http()
        headers = api.token(api.client())
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE sessions SET expires_at = now() - interval '1 second'"
            )

        assert http.get("/api/v1/auth/me", headers=headers).status_code == 401


class TestAdminSecondFactor:
    def admin(self, api: Api) -> pyotp.TOTP:
        tx = api.world.tx()
        _, secret = auth.create_admin(
            tx,
            email="admin@example.com",
            password=PASSWORD,
            full_name="An Admin",
            secret_key="a-test-only-secret-key",
        )
        api.world.session.flush()
        return pyotp.TOTP(secret)

    def test_an_admin_needs_the_code_and_a_code_works_once(self, api: Api) -> None:
        http = api.http()
        totp = self.admin(api)
        login = {"email": "admin@example.com", "password": PASSWORD}

        without = http.post("/api/v1/auth/login", json=login)
        wrong = http.post("/api/v1/auth/login", json=login | {"totp_code": "000000"})
        right = http.post("/api/v1/auth/login", json=login | {"totp_code": totp.now()})
        replayed = http.post("/api/v1/auth/login", json=login | {"totp_code": totp.now()})

        # A missing or wrong code looks exactly like a wrong password (docs/06 §2.1).
        assert code_of(without) == code_of(wrong) == "INVALID_CREDENTIALS"
        assert right.status_code == 200
        assert right.json()["me"]["role"] == "admin"
        assert code_of(replayed) == "INVALID_CREDENTIALS"

    def test_the_secret_is_stored_encrypted_and_an_admin_session_is_short(self, api: Api) -> None:
        http = api.http()
        totp = self.admin(api)

        answer = http.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": PASSWORD, "totp_code": totp.now()},
        ).json()

        (stored,) = api.world.one("SELECT totp_secret FROM users WHERE role = 'admin'")
        assert totp.secret.encode() not in bytes(stored)
        (left,) = api.world.one("SELECT max(expires_at) - now() FROM sessions")
        # 12 hours for an admin, against 7 days for everyone else (R-AU3).
        assert timedelta(hours=11) < left < timedelta(hours=12, minutes=1)
        assert answer["expires_at"]


class TestEveryEndpoint:
    def test_a_change_from_another_site_is_refused(self, api: Api) -> None:
        http = api.http()

        for origin in ({"Origin": "https://evil.example"}, {"Origin": ""}):
            answer = http.post("/api/v1/auth/login", json={}, headers=origin)
            assert (answer.status_code, code_of(answer)) == (403, "ORIGIN_REJECTED")

    def test_without_a_login_the_answer_is_401(self, api: Api) -> None:
        http = api.http()

        for headers in ({}, {"Authorization": "Bearer nothing"}, {"Authorization": "Basic abc"}):
            answer = http.get("/api/v1/auth/me", headers=headers)
            assert (answer.status_code, code_of(answer)) == (401, "UNAUTHENTICATED")

    def test_the_wrong_role_is_refused(self, api: Api) -> None:
        http = api.http()
        pharmacist = api.world.make.user("pharmacist")

        answer = http.get("/api/v1/me/profile", headers=api.token(pharmacist))

        assert (answer.status_code, code_of(answer)) == (403, "FORBIDDEN")

    def test_a_session_may_call_only_so_often(self, api: Api) -> None:
        http = api.http()
        http.app.state.calls_per_session = Limiter(2, 60)  # type: ignore[attr-defined]
        headers = api.token(api.client())

        answers = [http.get("/api/v1/auth/me", headers=headers) for _ in range(3)]

        assert [answer.status_code for answer in answers] == [200, 200, 429]
        assert code_of(answers[-1]) == "RATE_LIMITED"
        assert int(answers[-1].headers["Retry-After"]) >= 1

    def test_a_body_that_is_too_large_is_refused_unread(self, api: Api) -> None:
        answer = api.http().post("/api/v1/auth/login", json={"email": "x" * 70_000})

        assert (answer.status_code, code_of(answer)) == (413, "BODY_TOO_LARGE")

    def test_an_unknown_field_is_refused(self, api: Api) -> None:
        answer = api.http().post(
            "/api/v1/auth/login", json={"email": "a@b.co", "password": "x", "role": "admin"}
        )

        assert code_of(answer) == "VALIDATION_ERROR"

    def test_the_app_refuses_to_start_without_its_secret(self, api: Api) -> None:
        settings = api.settings.model_copy(update={"app_secret_key": None})

        with pytest.raises(ConfigError, match="APP_SECRET_KEY"):
            create_app(settings)


class TestProfileAndPassword:
    def test_a_client_changes_their_home_district_and_brand_choice(self, api: Api) -> None:
        http = api.http()
        headers = api.token(api.client())

        changed = http.patch(
            "/api/v1/me/profile",
            json={"district_id": 2, "alternatives_ok_default": True},
            headers=headers,
        ).json()

        assert changed["client"]["district"]["id"] == 2
        assert changed["client"]["alternatives_ok_default"] is True
        assert changed["client"]["missed_pickups_30d"] == 0

    def test_a_new_password_ends_the_other_logins(self, api: Api) -> None:
        http = api.http()
        client = api.client(email="rami@example.com")
        here, elsewhere = api.token(client), api.token(client)

        wrong = http.post(
            "/api/v1/auth/password",
            json={"current_password": "not it", "new_password": "Another long passphrase, 2"},
            headers=here,
        )
        done = http.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": "Another long passphrase, 2"},
            headers=here,
        )

        assert code_of(wrong) == "INVALID_CREDENTIALS"
        assert done.status_code == 204
        assert http.get("/api/v1/auth/me", headers=here).status_code == 200
        assert http.get("/api/v1/auth/me", headers=elsewhere).status_code == 401
        login = {"email": "rami@example.com", "password": "Another long passphrase, 2"}
        assert http.post("/api/v1/auth/login", json=login).status_code == 200

    def test_a_wrong_current_password_counts_like_a_failed_login(self, api: Api) -> None:
        """R-AU2: a stolen session can't guess the password for ever. Five wrong ones lock
        the account, here and at the login, even for the right password."""
        http = api.http()
        client = api.client(email="rami@example.com")
        headers = api.token(client)

        def change(current: str) -> Any:
            body = {"current_password": current, "new_password": OTHER}
            return http.post("/api/v1/auth/password", json=body, headers=headers)

        wrong = [change("not it") for _ in range(5)]
        right = change(PASSWORD)
        login = http.post(
            "/api/v1/auth/login", json={"email": "rami@example.com", "password": PASSWORD}
        )

        assert [(answer.status_code, code_of(answer)) for answer in wrong] == [
            (401, "INVALID_CREDENTIALS")
        ] * 5
        assert (right.status_code, code_of(right)) == (429, "ACCOUNT_LOCKED")
        assert 0 < right.json()["error"]["details"]["retry_after"] <= 15 * 60 + 1
        assert code_of(login) == "ACCOUNT_LOCKED"
        assert "login.locked" in api.world.audit_actions(client)
        # Nothing changed: the old password is still the one.
        assert api.world.one(
            "SELECT count(*) FROM audit_events WHERE action = 'password.changed'"
        ) == (0,)

    def test_a_right_current_password_clears_the_count(self, api: Api) -> None:
        http = api.http()
        client = api.client(email="rami@example.com")
        headers = api.token(client)
        for _ in range(4):
            http.post(
                "/api/v1/auth/password",
                json={"current_password": "not it", "new_password": OTHER},
                headers=headers,
            )

        done = http.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": OTHER},
            headers=headers,
        )
        one_mistake = http.post(
            "/api/v1/auth/login", json={"email": "rami@example.com", "password": "nope"}
        )

        assert done.status_code == 204
        assert code_of(one_mistake) == "INVALID_CREDENTIALS"
        assert api.world.one("SELECT failed_logins FROM users WHERE id = :u", u=client) == (1,)


class TestPasswordHashing:
    """R-AU1: argon2id with OWASP's minimum, and only a few hashes at once, so a burst of
    logins or sign-ups can't outgrow the API's memory (docs/12 §6)."""

    def test_a_password_is_hashed_with_our_parameters(self, api: Api) -> None:
        api.http().post("/api/v1/auth/register/client", json=NEW)

        (stored,) = api.world.one(
            "SELECT password_hash FROM users WHERE email = :e", e=NEW["email"]
        )

        assert stored.startswith("$argon2id$v=19$m=19456,t=2,p=1$")

    def test_an_older_hash_still_works_and_is_made_again_at_the_login(self, api: Api) -> None:
        old = PasswordHasher(memory_cost=65_536, time_cost=3, parallelism=4).hash(PASSWORD)
        client = api.client(email="rami@example.com", password_hash=old)
        http = api.http()

        first = http.post(
            "/api/v1/auth/login", json={"email": "rami@example.com", "password": PASSWORD}
        )

        assert first.status_code == 200
        (renewed,) = api.world.one("SELECT password_hash FROM users WHERE id = :u", u=client)
        assert renewed != old
        assert renewed.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
        again = http.post(
            "/api/v1/auth/login", json={"email": "rami@example.com", "password": PASSWORD}
        )
        assert again.status_code == 200

    def test_with_every_slot_taken_a_login_is_asked_to_try_again(
        self, api: Api, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """docs/09 FX-12's answer, and nothing counted: not the account, not the network."""
        monkeypatch.setattr(auth, "_slot_wait_s", 0.05)
        http = api.http()
        client = api.client(email="rami@example.com")
        wrong = {"email": "rami@example.com", "password": "nope"}
        taken = 0
        try:
            for _ in range(PASSWORD_HASHES_AT_ONCE):
                assert auth._slots.acquire(timeout=1)
                taken += 1
            busy = [http.post("/api/v1/auth/login", json=wrong) for _ in range(6)]
            sign_up = http.post("/api/v1/auth/register/client", json=NEW)
        finally:
            for _ in range(taken):
                auth._slots.release()

        for answer in (*busy, sign_up):
            assert (answer.status_code, code_of(answer)) == (503, "SERVICE_UNAVAILABLE")
            assert answer.headers["Retry-After"] == "1"
        assert api.world.one("SELECT failed_logins FROM users WHERE id = :u", u=client) == (0,)
        assert api.world.one("SELECT count(*) FROM users WHERE email = :e", e=NEW["email"]) == (0,)
        # Once a slot is free, the same login is a plain wrong password again.
        assert code_of(http.post("/api/v1/auth/login", json=wrong)) == "INVALID_CREDENTIALS"

    def test_no_more_hashes_run_at_once_than_there_are_slots(self) -> None:
        running, most = 0, 0
        lock = threading.Lock()

        def a_hash() -> None:
            nonlocal running, most
            with auth.password_slot():
                with lock:
                    running += 1
                    most = max(most, running)
                auth.hash_password(PASSWORD)
                with lock:
                    running -= 1

        threads = [threading.Thread(target=a_hash) for _ in range(PASSWORD_HASHES_AT_ONCE * 3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert most <= PASSWORD_HASHES_AT_ONCE

    def test_a_taken_licence_or_phone_costs_no_hash(
        self, api: Api, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Refused before the hash: repeating a refusal that no limit counts costs the
        server nothing."""
        http = api.http()
        pharmacy = {
            "name": "Hamra Pharmacy",
            "license_number": "PH1234",
            "phone": "01 234 567",
            "address": "12 Hamra Street, Beirut",
            "district_id": 1,
            "location": {"lat": 33.8959, "lon": 35.4828},
            "pickup_days": 1,
            "hours": [{"weekday": 0, "open": "08:00", "close": "20:00"}],
        }
        body = {"email": "a@example.com", "password": PASSWORD, "accept_terms": True}
        assert (
            http.post(
                "/api/v1/auth/register/pharmacy", json=body | {"pharmacy": pharmacy}
            ).status_code
            == 202
        )

        def no_hash(password: str) -> str:
            raise AssertionError("hashed")

        monkeypatch.setattr(auth, "hash_password", no_hash)
        same_phone = pharmacy | {"license_number": "PH9999"}
        answer = http.post(
            "/api/v1/auth/register/pharmacy",
            json=body | {"email": "b@example.com", "pharmacy": same_phone},
        )

        assert (answer.status_code, code_of(answer)) == (409, "PHONE_TAKEN")


class TestPublicConfiguration:
    def test_anyone_reads_the_public_settings_and_the_districts(self, api: Api) -> None:
        http = api.http(assistant=False)

        config = http.get("/api/v1/config/public").json()
        districts = http.get("/api/v1/districts").json()

        assert (config["request_hours_start"], config["request_hours_end"]) == ("08:00", "20:00")
        assert config["assistant_available"] is False
        # A district's centre is public, like any map: where the pharmacy's map opens.
        assert {"id", "name", "governorate", "lat", "lon"} == set(districts[0])
        assert [tier["discount_pct"] for tier in config["discount_tiers"]] == [60, 40, 25]
        assert len(districts) == 26
