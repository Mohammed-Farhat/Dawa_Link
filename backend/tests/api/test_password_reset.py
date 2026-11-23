""" "Forgot my password": a link by email, then a new password (docs/04 R-AU9, R-AU7;
docs/10 TH-1 to TH-3, TH-53).

Every answer to an ask is the same, whoever's email it is; a link goes only to an account
that could log in today; it works once, for 30 minutes of real time; only the newest
works; using it ends every login and every other link, and tells the owner.
"""

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response

from dawalink.api.routes import accounts
from dawalink.domain.numbers import (
    RESET_ASKS_PER_ADDRESS_PER_HOUR,
    RESET_EMAILS_PER_DAY,
    RESET_EMAILS_PER_HOUR,
)
from dawalink.services import admin_clients, auth
from tests.api.conftest import PASSWORD, Api, code_of

ASK = "/api/v1/auth/password/forgot"
RESET = "/api/v1/auth/password/reset"
NEW_PASSWORD = "A brand new passphrase, 3"
SUBJECT = "Set a new password for DawaLink"
NOTICE = "Your DawaLink password was changed"


def reset_link(body: str) -> str:
    found = re.search(r"/reset-password\?token=(\S+)", body)
    assert found, body
    return found.group(1)


def links_in(sent: list[tuple[str, str, str]]) -> list[tuple[str, str]]:
    """`(to, token)` of each reset email sent."""
    return [(to, reset_link(body)) for to, subject, body in sent if subject == SUBJECT]


def logs_in(http: TestClient, email: str, password: str) -> int:
    return http.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code


def error_of(response: Response) -> dict[str, object]:
    """An error answer without its request's own ID: what two answers must share."""
    error: dict[str, object] = response.json()["error"]
    return {name: value for name, value in error.items() if name != "request_id"}


def queued(api: Api, template: str = auth.RESET_PASSWORD) -> int:
    (count,) = api.world.one("SELECT count(*) FROM email_outbox WHERE template = :t", t=template)
    return int(count)


@pytest.fixture
def rami(api: Api) -> uuid.UUID:
    """A client who can log in today."""
    return api.client(email="rami@example.com")


def a_link(api: Api, email: str = "rami@example.com") -> str:
    """Asks for a link from a network of its own, and returns the token it carries."""
    assert api.http().post(ASK, json={"email": email}).status_code == 202
    ((to, token),) = links_in(api.emails())
    assert to == email
    return token


class TestAsking:
    def test_the_answer_is_the_same_whoever_asks(self, api: Api) -> None:
        """R-AU7, R-AU9: a known, an unknown, an unconfirmed, a suspended, an admin's and a
        passwordless email get the same status and the same words. Only the two accounts
        that could log in today get a link."""
        api.client(email="rami@example.com")
        api.client("UNVERIFIED", email="new@example.com")
        api.client("SUSPENDED", email="gone@example.com")
        api.world.make.user("admin", email="admin@example.com", totp_secret=b"not-a-real-secret")
        api.world.make.client(person={"email": "seeded@example.com", "password_hash": "!"})
        # A pharmacist logs in whatever the pharmacy's state (SM-1): so a link for them too.
        pharmacist = api.world.make.user(
            "pharmacist",
            email="pharmacy@example.com",
            password_hash=auth.hash_password(PASSWORD),
            email_verified_at=api.world.clock.now(),
        )
        api.world.make.pharmacy("SUSPENDED", owner_user_id=pharmacist)
        emails = [
            "rami@example.com",
            "nobody@example.com",
            "new@example.com",
            "gone@example.com",
            "admin@example.com",
            "seeded@example.com",
            "pharmacy@example.com",
        ]

        # Each from a network of its own: the limit per address is not what is tested.
        answers = [api.http().post(ASK, json={"email": email}) for email in emails]

        assert {(answer.status_code, answer.text) for answer in answers} == {
            (
                202,
                '{"message":"If this email has an account, a link to set a new password is on '
                'its way. It works for 30 minutes."}',
            )
        }
        assert queued(api) == 2
        assert sorted(to for to, _ in links_in(api.emails())) == [
            "pharmacy@example.com",
            "rami@example.com",
        ]

    def test_the_email_says_how_long_the_link_works_and_nothing_else_is_stored(
        self, api: Api, rami: uuid.UUID
    ) -> None:
        api.http().post(ASK, json={"email": "rami@example.com"})
        ((_, subject, body),) = api.emails()

        assert subject == SUBJECT
        assert "It works once, for 30 minutes" in body
        # Only a hash of the token is kept, and it lasts 30 minutes of real time.
        token = reset_link(body)
        (stored, left) = api.world.one(
            "SELECT token_hash, extract(epoch FROM expires_at - now()) "
            "FROM password_reset_tokens WHERE user_id = :u",
            u=rami,
        )
        assert token.encode() not in bytes(stored)
        # `now()` is when the test's transaction began, a moment before the link was made.
        assert 29 * 60 < float(left) < 31 * 60
        assert api.world.one("SELECT params FROM email_outbox WHERE template = 'CN-19'") == ({},)

    def test_a_spelled_differently_email_finds_its_account(self, api: Api, rami: uuid.UUID) -> None:
        """Emails are compared without case, as at the login."""
        api.http().post(ASK, json={"email": "  Rami@Example.com "})

        assert queued(api) == 1

    def test_an_account_gets_a_few_links_an_hour_and_the_answer_never_shows_it(
        self, api: Api, rami: uuid.UUID
    ) -> None:
        """TH-53: nobody can make DawaLink send one address email after email. An ask over
        the cap is answered the same, sends nothing, and ends no link."""
        tokens = [a_link(api) for _ in range(RESET_EMAILS_PER_HOUR)]

        over = api.http().post(ASK, json={"email": "rami@example.com"})

        assert over.status_code == 202
        assert api.emails() == []
        assert queued(api) == RESET_EMAILS_PER_HOUR
        # The newest link still works: an ask over the cap took nothing away.
        done = api.http().post(RESET, json={"token": tokens[-1], "new_password": NEW_PASSWORD})
        assert done.status_code == 204
        assert logs_in(api.http(), "rami@example.com", NEW_PASSWORD) == 200

    def test_and_a_few_a_day(self, api: Api, rami: uuid.UUID) -> None:
        sent = 0
        for _ in range(RESET_EMAILS_PER_DAY + 2):
            api.http().post(ASK, json={"email": "rami@example.com"})
            sent += len(api.emails())
            with api.world.as_owner():
                # An hour passes: the hourly cap is not what is tested.
                api.world.connection.exec_driver_sql(
                    "UPDATE email_outbox SET created_at = created_at - interval '61 minutes'"
                )

        assert sent == RESET_EMAILS_PER_DAY

    def test_too_many_asks_from_one_network_are_refused_whatever_the_email(
        self, api: Api, rami: uuid.UUID
    ) -> None:
        http = api.http()
        for number in range(RESET_ASKS_PER_ADDRESS_PER_HOUR):
            asked = http.post(ASK, json={"email": f"n{number}@example.com"})
            assert asked.status_code == 202

        known = http.post(ASK, json={"email": "rami@example.com"})
        unknown = http.post(ASK, json={"email": "nobody@example.com"})

        for refused in (known, unknown):
            assert (refused.status_code, code_of(refused)) == (429, "RATE_LIMITED")
            assert 0 < int(refused.headers["Retry-After"]) <= 3601
        assert error_of(known) == error_of(unknown)
        assert queued(api) == 0

    def test_without_a_known_address_no_ask_is_refused_for_the_others(
        self, api: Api, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R-AU8: in AWS with CloudFront's header missing, every visitor would seem to be
        the load balancer. The limit per address is then not counted, as for a login."""
        monkeypatch.setattr(accounts, "stated_address", lambda request, settings: None)
        http = api.http(assistant=False)

        answers = [
            http.post(ASK, json={"email": f"n{number}@example.com"})
            for number in range(RESET_ASKS_PER_ADDRESS_PER_HOUR + 2)
        ]

        assert {answer.status_code for answer in answers} == {202}

    def test_asking_changes_nothing_about_the_account(self, api: Api, rami: uuid.UUID) -> None:
        """Someone else may ask for your email: your password and your logins stay."""
        headers = api.token(rami)

        api.http().post(ASK, json={"email": "rami@example.com"})
        api.emails()

        assert api.http().get("/api/v1/auth/me", headers=headers).status_code == 200
        assert logs_in(api.http(), "rami@example.com", PASSWORD) == 200


class TestUsingTheLink:
    def test_it_sets_the_new_password_and_logs_nobody_in(self, api: Api, rami: uuid.UUID) -> None:
        headers = api.token(rami)
        token = a_link(api)
        http = api.http()

        done = http.post(RESET, json={"token": token, "new_password": NEW_PASSWORD})

        assert (done.status_code, done.content) == (204, b"")
        # Every login of the account ended, this one's included: nobody is logged in.
        assert http.get("/api/v1/auth/me", headers=headers).status_code == 401
        assert logs_in(http, "rami@example.com", PASSWORD) == 401
        assert logs_in(http, "rami@example.com", NEW_PASSWORD) == 200
        # The fields that changed, never a value.
        assert "password.reset" in api.world.audit_actions(rami)
        assert api.world.one("SELECT after FROM audit_events WHERE action = 'password.reset'") == (
            {"fields": ["password"]},
        )

    def test_it_works_once(self, api: Api, rami: uuid.UUID) -> None:
        token = a_link(api)
        http = api.http()
        http.post(RESET, json={"token": token, "new_password": NEW_PASSWORD})

        again = http.post(RESET, json={"token": token, "new_password": "Yet another one, 4!"})
        unknown = http.post(RESET, json={"token": "x" * 43, "new_password": NEW_PASSWORD})

        assert (again.status_code, code_of(again)) == (400, "TOKEN_INVALID")
        assert error_of(again) == error_of(unknown)
        assert logs_in(http, "rami@example.com", NEW_PASSWORD) == 200

    def test_it_ends_after_30_real_minutes(self, api: Api, rami: uuid.UUID) -> None:
        token = a_link(api)
        with api.world.as_owner():
            api.world.connection.exec_driver_sql(
                "UPDATE password_reset_tokens SET expires_at = now() - interval '1 second'"
            )

        late = api.http().post(RESET, json={"token": token, "new_password": NEW_PASSWORD})

        assert code_of(late) == "TOKEN_INVALID"
        assert logs_in(api.http(), "rami@example.com", PASSWORD) == 200

    def test_moving_the_demo_clock_ends_no_link(self, api: Api, rami: uuid.UUID) -> None:
        """R-T11: what protects a login is counted in real time."""
        token = a_link(api)

        api.world.later(hours=5)
        api.world.clock_tasks().run_daily_tasks()

        done = api.http().post(RESET, json={"token": token, "new_password": NEW_PASSWORD})
        assert done.status_code == 204

    def test_a_newer_link_ends_the_older_one(self, api: Api, rami: uuid.UUID) -> None:
        older = a_link(api)
        newer = a_link(api)
        http = api.http()

        stale = http.post(RESET, json={"token": older, "new_password": NEW_PASSWORD})
        done = http.post(RESET, json={"token": newer, "new_password": NEW_PASSWORD})

        assert code_of(stale) == "TOKEN_INVALID"
        assert done.status_code == 204

    def test_a_weak_password_is_refused_and_the_link_still_works(
        self, api: Api, rami: uuid.UUID
    ) -> None:
        token = a_link(api)
        http = api.http()

        weak = http.post(RESET, json={"token": token, "new_password": "password"})
        common = http.post(RESET, json={"token": token, "new_password": "Password123!"})
        done = http.post(RESET, json={"token": token, "new_password": NEW_PASSWORD})

        assert code_of(weak) == code_of(common) == "WEAK_PASSWORD"
        assert common.json()["error"]["details"]["missing"] == ["uncommon"]
        assert done.status_code == 204

    def test_a_wrong_link_costs_no_password_hash(
        self, api: Api, rami: uuid.UUID, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def no_hash(password: str) -> str:
            raise AssertionError("a wrong link was hashed for")

        monkeypatch.setattr(auth, "hash_password", no_hash)

        wrong = api.http().post(RESET, json={"token": "y" * 43, "new_password": NEW_PASSWORD})

        assert code_of(wrong) == "TOKEN_INVALID"

    def test_the_lock_of_wrong_passwords_is_lifted(self, api: Api, rami: uuid.UUID) -> None:
        """Someone who forgot their password has often locked their account by trying."""
        http = api.http()
        for _ in range(5):
            http.post("/api/v1/auth/login", json={"email": "rami@example.com", "password": "no"})
        locked = http.post(
            "/api/v1/auth/login", json={"email": "rami@example.com", "password": PASSWORD}
        )
        assert code_of(locked) == "ACCOUNT_LOCKED"

        api.http().post(RESET, json={"token": a_link(api), "new_password": NEW_PASSWORD})

        assert logs_in(api.http(), "rami@example.com", NEW_PASSWORD) == 200
        assert api.world.one(
            "SELECT failed_logins, locked_until FROM users WHERE id = :u", u=rami
        ) == (
            0,
            None,
        )

    def test_it_ends_every_other_link_of_the_account(self, api: Api, rami: uuid.UUID) -> None:
        token = a_link(api)
        auth.new_verification_token(api.world.tx(), rami)  # a confirmation email's link

        api.http().post(RESET, json={"token": token, "new_password": NEW_PASSWORD})

        for table in ("password_reset_tokens", "email_verification_tokens"):
            assert api.world.one(
                f"SELECT count(*) FROM {table} WHERE user_id = :u AND used_at IS NULL", u=rami
            ) == (0,), table

    def test_the_owner_is_told_and_the_notice_carries_no_link(
        self, api: Api, rami: uuid.UUID
    ) -> None:
        api.http().post(RESET, json={"token": a_link(api), "new_password": NEW_PASSWORD})

        ((to, subject, body),) = api.emails()

        assert (to, subject) == ("rami@example.com", NOTICE)
        # When, in Beirut time, as every email writes a moment.
        assert re.search(r"was changed on \w{3} \d{2} \w{3}, \d{2}:\d{2}, with a link", body)
        assert "http" not in body
        assert "token" not in body
        assert 'press "Forgot your password?"' in body


class TestOnlyAUsedLinkLiftsTheLock:
    """Only a new password set with a good link lifts the lock and clears the count of
    failed logins: an ask, its email, a wrong link or a refused password leave both as
    they were. Otherwise anyone who knows an email could undo its lock for free."""

    @pytest.fixture
    def locked(self, api: Api, rami: uuid.UUID) -> tuple[int, object]:
        with api.world.as_owner():
            # Three failures counted and a lock running: two things a reset could clear.
            api.world.connection.exec_driver_sql(
                "UPDATE users SET failed_logins = 3, locked_until = now() + interval '10 minutes' "
                "WHERE id = %s",
                (rami,),
            )
        return self.state(api, rami)

    @staticmethod
    def state(api: Api, user: uuid.UUID) -> tuple[int, object]:
        row = api.world.one("SELECT failed_logins, locked_until FROM users WHERE id = :u", u=user)
        return int(row[0]), row[1]

    def test_an_ask_and_its_email_change_neither(
        self, api: Api, rami: uuid.UUID, locked: tuple[int, object]
    ) -> None:
        assert api.http().post(ASK, json={"email": "rami@example.com"}).status_code == 202
        assert self.state(api, rami) == locked
        assert len(links_in(api.emails())) == 1  # the link's token is made here
        assert self.state(api, rami) == locked

    def test_a_wrong_link_or_a_refused_password_change_neither(
        self, api: Api, rami: uuid.UUID, locked: tuple[int, object]
    ) -> None:
        token = a_link(api)
        http = api.http()

        wrong = http.post(RESET, json={"token": "z" * 43, "new_password": NEW_PASSWORD})
        weak = http.post(RESET, json={"token": token, "new_password": "password"})

        assert code_of(wrong) == "TOKEN_INVALID"
        assert code_of(weak) == "WEAK_PASSWORD"
        assert self.state(api, rami) == locked
        # The good link still lifts both.
        assert http.post(RESET, json={"token": token, "new_password": NEW_PASSWORD}).is_success
        assert self.state(api, rami) == (0, None)


class TestLinksThatEnd:
    """Rule 5 and rule 7 of R-AU9: an account that can no longer log in has no link, and
    every way a user's links end ends the reset links too."""

    def test_a_suspension_between_asking_and_using_wins(self, api: Api, rami: uuid.UUID) -> None:
        token = a_link(api)
        with api.world.as_owner():
            # Only the status: the link itself is left as it was.
            api.world.connection.exec_driver_sql(
                f"UPDATE client_profiles SET status = 'SUSPENDED' WHERE user_id = '{rami}'"
            )

        late = api.http().post(RESET, json={"token": token, "new_password": NEW_PASSWORD})

        assert code_of(late) == "TOKEN_INVALID"
        (stored,) = api.world.one("SELECT password_hash FROM users WHERE id = :u", u=rami)
        assert auth._password_matches(stored, PASSWORD)

    def test_an_admins_suspension_ends_the_link_for_good(self, api: Api, rami: uuid.UUID) -> None:
        token = a_link(api)
        admin = api.world.make.user("admin", totp_secret=b"not-a-real-secret")
        admin_clients.suspend(api.world.tx(), admin, rami, reason="abuse of the service")
        with api.world.as_owner():
            # Reinstated: the link still doesn't come back.
            api.world.connection.exec_driver_sql(
                f"UPDATE client_profiles SET status = 'ACTIVE' WHERE user_id = '{rami}'"
            )

        late = api.http().post(RESET, json={"token": token, "new_password": NEW_PASSWORD})

        assert code_of(late) == "TOKEN_INVALID"

    def test_a_password_changed_while_logged_in_ends_the_link(
        self, api: Api, rami: uuid.UUID
    ) -> None:
        token = a_link(api)
        http = api.http()
        changed = http.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": "Changed while in, 5!"},
            headers=api.token(rami),
        )

        late = http.post(RESET, json={"token": token, "new_password": NEW_PASSWORD})

        assert changed.status_code == 204
        assert code_of(late) == "TOKEN_INVALID"
