"""Registration, logins and the checks every endpoint makes (docs/04 R-AU, SM-2;
docs/06 §2, §6.1; docs/10 TH-1 to TH-9)."""

import re
from datetime import timedelta
from typing import Any

import pyotp
import pytest

from dawalink.api.limits import Limiter
from dawalink.api.main import create_app
from dawalink.config import ConfigError
from dawalink.domain.numbers import FAILED_LOGINS_PER_ADDRESS
from dawalink.services import auth
from tests.api.conftest import PASSWORD, Api, code_of

NEW = {
    "email": "nour@example.com",
    "password": PASSWORD,
    "full_name": "Nour Khoury",
    "district_id": 1,
    "accept_terms": True,
}


def link_token(body: str) -> str:
    found = re.search(r"/verify-email\?token=(\S+)", body)
    assert found, body
    return found.group(1)


class TestRegistration:
    def test_a_new_client_confirms_the_email_and_is_logged_in(self, api: Api) -> None:
        http = api.http()

        answer = http.post("/api/v1/auth/register/client", json=NEW)

        assert answer.status_code == 202
        assert api.world.one(
            "SELECT status FROM client_profiles JOIN users ON id = user_id WHERE email = :e",
            e=NEW["email"],
        ) == ("UNVERIFIED",)
        ((to, subject, body),) = api.emails()
        assert (to, subject) == (NEW["email"], "Confirm your email for DawaLink")

        confirmed = http.post("/api/v1/auth/verify-email", json={"token": link_token(body)})

        assert confirmed.status_code == 200
        me = confirmed.json()["me"]
        assert (me["email_verified"], me["client"]["status"]) == (True, "ACTIVE")
        # The link logged them in: the token it gave works.
        headers = {"Authorization": f"Bearer {confirmed.json()['token']}"}
        assert http.get("/api/v1/auth/me", headers=headers).json()["full_name"] == "Nour Khoury"

    def test_the_answer_never_says_whether_the_email_has_an_account(self, api: Api) -> None:
        """R-AU7: the same answer; the owner of the address gets "just log in", once a day."""
        http = api.http()
        first = http.post("/api/v1/auth/register/client", json=NEW)
        api.emails()

        again = http.post("/api/v1/auth/register/client", json=NEW | {"full_name": "Someone"})
        third = http.post("/api/v1/auth/register/client", json=NEW)

        assert (again.status_code, again.json()) == (first.status_code, first.json())
        assert third.json() == first.json()
        assert api.world.one("SELECT count(*) FROM users WHERE email = :e", e=NEW["email"]) == (1,)
        assert [subject for _, subject, _ in api.emails()] == [
            "You already have a DawaLink account"
        ]

    @pytest.mark.parametrize("password", ["short", "PASSWORD123", "qwertyuiop"])
    def test_a_weak_password_is_refused(self, api: Api, password: str) -> None:
        answer = api.http().post("/api/v1/auth/register/client", json=NEW | {"password": password})

        assert (answer.status_code, code_of(answer)) == (422, "WEAK_PASSWORD")

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

        assert http.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
        used = http.post("/api/v1/auth/verify-email", json={"token": token})
        unknown = http.post("/api/v1/auth/verify-email", json={"token": "x" * 43})

        assert (used.status_code, code_of(used)) == (400, "TOKEN_INVALID")
        assert code_of(unknown) == "TOKEN_INVALID"

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
            json={"current_password": "not it", "new_password": "another long passphrase"},
            headers=here,
        )
        done = http.post(
            "/api/v1/auth/password",
            json={"current_password": PASSWORD, "new_password": "another long passphrase"},
            headers=here,
        )

        assert code_of(wrong) == "INVALID_CREDENTIALS"
        assert done.status_code == 204
        assert http.get("/api/v1/auth/me", headers=here).status_code == 200
        assert http.get("/api/v1/auth/me", headers=elsewhere).status_code == 401
        login = {"email": "rami@example.com", "password": "another long passphrase"}
        assert http.post("/api/v1/auth/login", json=login).status_code == 200


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
