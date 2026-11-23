"""An account changes at the same moment as something else acts for it (docs/04 R-AU9,
R-AU10; docs/05 §6).

Both actions start inside open transactions (`Arena.together`), so the outcome never
depends on timing luck. Either may go first; what is checked is what must hold whichever
did.
"""

import uuid
from datetime import date
from typing import Any

from dawalink.domain.vocabulary import EscalationReason
from dawalink.services import account_deletion, auth, escalations
from dawalink.services.errors import Code, ServiceError
from tests.db.factories import NOW
from tests.races.conftest import Arena

PASSWORD = "A long passphrase, 1"


def a_client(arena: Arena) -> uuid.UUID:
    """A client who can log in, with a real password."""
    return arena.make.client(  # type: ignore[no-any-return]
        "ACTIVE",
        person={"password_hash": auth.hash_password(PASSWORD), "email_verified_at": NOW},
    )


def failures(results: list[Any]) -> list[ServiceError]:
    """The refusals. Anything else that went wrong is a real failure."""
    for result in results:
        if isinstance(result, Exception) and not isinstance(result, ServiceError):
            raise result
    return [result for result in results if isinstance(result, ServiceError)]


def test_a_case_opened_while_the_client_deletes_their_account_does_not_stay_open(
    arena: Arena,
) -> None:
    """An agent turn that was running escalates as the client deletes the account. If the
    deletion goes first, the escalation is refused; if the escalation goes first, the
    deletion closes it. Either way no case is left open for nobody (R-AU10)."""
    client = a_client(arena)

    results = arena.together(
        lambda tx: account_deletion.delete_own_account(tx, client, password=PASSWORD),
        lambda tx: escalations.escalate(
            tx,
            client_id=client,
            reason=EscalationReason.CANNOT_RESOLVE,
            summary="The client needs a person.",
        ),
        hold="escalations",
    )

    refused = failures(results)
    assert results[0] is True  # the deletion always goes through
    assert [error.code for error in refused] in ([], [Code.NOT_FOUND])
    assert arena.one("SELECT status FROM client_profiles WHERE user_id = :c", c=client)[0] == (
        "DELETED"
    )
    assert arena.one(
        "SELECT count(*) FROM escalations WHERE client_id = :c AND state <> 'RESOLVED'", c=client
    ) == (0,)


def test_a_confirmation_link_followed_while_the_account_is_deleted(arena: Arena) -> None:
    """Both lock the client's profile first, then the user's row (docs/05 §6), so they
    queue instead of deadlocking. Whichever goes first, the account ends deleted with no
    login left."""
    client = arena.make.client("UNVERIFIED", person={"password_hash": auth.hash_password(PASSWORD)})
    token = arena.run(lambda tx: auth.new_verification_token(tx, client))

    results = arena.together(
        lambda tx: account_deletion.delete_own_account(tx, client, password=PASSWORD),
        lambda tx: auth.verify_email(tx, token),
        hold="users",
    )

    refused = failures(results)  # a deadlock would be a database error, not a refusal
    assert results[0] is True
    assert [error.code for error in refused] in ([], [Code.TOKEN_INVALID])
    assert arena.one("SELECT status FROM client_profiles WHERE user_id = :c", c=client)[0] == (
        "DELETED"
    )
    assert arena.one(
        "SELECT count(*) FROM sessions WHERE user_id = :c AND revoked_at IS NULL", c=client
    ) == (0,)


def test_a_sign_up_again_while_the_unconfirmed_client_deletes_the_account(arena: Arena) -> None:
    """Someone signs up with the address of a client who never confirmed it, as that
    client deletes the account. Both lock the profile first, then the user's row (docs/05
    §6): they queue instead of deadlocking. The deletion goes through either way (the
    sign-up again keeps the password the same here, so the deletion's check still passes);
    if it went first, the sign-up makes a new account of the freed address."""
    email = "unconfirmed@example.com"
    client = arena.make.client(
        "UNVERIFIED", person={"password_hash": auth.hash_password(PASSWORD), "email": email}
    )

    results = arena.together(
        lambda tx: account_deletion.delete_own_account(tx, client, password=PASSWORD),
        lambda tx: auth.register_client(
            tx,
            email=email,
            password=PASSWORD,
            first_name="Nour",
            middle_name=None,
            last_name="Khoury",
            birth_date=date(1990, 5, 17),
            phone=None,
            district_id=1,
            signup_address=None,
        ),
        hold="client_profiles",
    )

    assert failures(results) == []  # a deadlock would be a database error, not a refusal
    assert results[0] is True
    assert arena.one("SELECT status FROM client_profiles WHERE user_id = :c", c=client)[0] == (
        "DELETED"
    )
    (others,) = arena.one("SELECT count(*) FROM users WHERE email = :e", e=email)
    assert others in (0, 1)
    assert arena.one(
        "SELECT count(*) FROM sessions WHERE user_id = :c AND revoked_at IS NULL", c=client
    ) == (0,)


def test_a_reset_link_sent_twice_at_once_sets_one_password(arena: Arena) -> None:
    """A double tap on the link's form, or the link used on two devices at once: one new
    password is set, the other is refused as a used link."""
    client = a_client(arena)
    token = arena.run(lambda tx: auth.new_reset_token(tx, client))
    first, second = "First new passphrase, 2", "Second new passphrase, 3"

    results = arena.together(
        lambda tx: auth.reset_password(tx, token, first),
        lambda tx: auth.reset_password(tx, token, second),
        hold="password_reset_tokens",
    )

    (refused,) = failures(results)
    assert refused.code is Code.TOKEN_INVALID
    (stored,) = arena.one("SELECT password_hash FROM users WHERE id = :u", u=client)
    winner = first if results[0] is None else second
    loser = second if winner == first else first
    assert auth._password_matches(stored, winner)
    assert not auth._password_matches(stored, loser)
