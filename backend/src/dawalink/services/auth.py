"""Accounts and logins (docs/04 R-AU, SM-2; docs/06 §2.1, §6.1; docs/10).

**This is the one module that knows how a login works**: passwords, email confirmation,
sessions and the admins' second factor. Nothing else hashes a password or reads a token.
That keeps the later switch to Cognito small (docs/12 §10): Cognito will take over the
passwords, the confirmation emails and the second factor, and our own session token
stays.

Every limit here is counted in **real time** (`tx.real_now`), never on the demo clock:
moving the demo clock must not log anyone out or lift a lock.
"""

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from zxcvbn.frequency_lists import FREQUENCY_LISTS

from dawalink.db.models import (
    ClientProfile,
    District,
    EmailOutbox,
    EmailVerificationToken,
    Pharmacy,
    Session,
    User,
)
from dawalink.domain.accounts import ClientStatus
from dawalink.domain.numbers import (
    ADMIN_SESSION_LIFETIME,
    COMMON_PASSWORDS,
    FAILED_LOGINS_BEFORE_LOCK,
    LOGIN_LOCK,
    PASSWORD_MIN_CHARS,
    RESEND_VERIFICATION_EVERY,
    RESEND_VERIFICATION_PER_DAY,
    SESSION_LIFETIME,
    SIGNUPS_PER_ADDRESS_PER_HOUR,
    VERIFICATION_LINK_VALID,
)
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import UserRole
from dawalink.services import audit, pharmacy_profile
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

VERIFY_EMAIL = "CN-1"
ALREADY_REGISTERED = "CN-18"

_hasher = PasswordHasher()  # argon2id with the library's current defaults (R-AU1)
# Checked for an email nobody has, so a login takes as long either way (R-AU7).
_NOBODY = _hasher.hash(secrets.token_urlsafe(16))
# R-AU1: the most common passwords, lower case.
_COMMON = frozenset(word.lower() for word in FREQUENCY_LISTS["passwords"][:COMMON_PASSWORDS])


@dataclass(frozen=True)
class LoggedIn:
    user: User
    # Given to the browser once. Only its hash is stored.
    token: str
    expires_at: datetime


# --- Passwords --------------------------------------------------------------------------


def check_strength(password: str) -> None:
    """R-AU1: at least 10 characters, and not one of the most common passwords."""
    if len(password) < PASSWORD_MIN_CHARS:
        raise ServiceError(
            Code.WEAK_PASSWORD,
            f"Use at least {PASSWORD_MIN_CHARS} characters.",
            min_chars=PASSWORD_MIN_CHARS,
        )
    if password.lower() in _COMMON:
        raise ServiceError(Code.WEAK_PASSWORD, "This password is too common. Choose another.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _password_matches(stored: str, password: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        # Also a demo account whose password was never set: nothing matches it.
        return False


# --- Tokens -----------------------------------------------------------------------------


def _digest(token: str) -> bytes:
    """What we store of a token. A stolen database gives no working token."""
    return hashlib.sha256(token.encode()).digest()


def address_hash(secret_key: str, address: str) -> bytes:
    """The network address of a sign-up, hashed with our secret: enough to count sign-ups
    from one network, and not reversible (docs/05 `users.signup_ip_hash`)."""
    return hmac.new(secret_key.encode(), address.encode(), hashlib.sha256).digest()


# --- The second factor (admins) ---------------------------------------------------------


def _vault(secret_key: str) -> Fernet:
    key = hashlib.sha256(b"dawalink-totp:" + secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def new_totp_secret(secret_key: str) -> tuple[str, bytes]:
    """A new authenticator secret: as the admin types or scans it, and as it is stored."""
    plain = pyotp.random_base32()
    return plain, _vault(secret_key).encrypt(plain.encode())


def totp_setup_link(plain_secret: str, email: str) -> str:
    """The address an authenticator app reads from a QR code."""
    return pyotp.TOTP(plain_secret).provisioning_uri(name=email, issuer_name="DawaLink")


def _totp_step(user: User, code: str | None, secret_key: str, now: datetime) -> int | None:
    """The 30-second step this code belongs to, or None if the code is wrong.

    The step before and after are accepted too (a phone's clock is rarely exact). A code
    is good once: a step at or before the last one used is refused (R-AU6).
    """
    if not code or user.totp_secret is None:
        return None
    try:
        plain = _vault(secret_key).decrypt(bytes(user.totp_secret)).decode()
    except InvalidToken:
        return None
    totp = pyotp.TOTP(plain)
    current = int(now.timestamp()) // totp.interval
    for step in (current - 1, current, current + 1):
        expected = totp.at(step * totp.interval)
        if hmac.compare_digest(expected, code.strip()) and step > (user.totp_last_step or 0):
            return step
    return None


# --- Registration -----------------------------------------------------------------------


def _queue(tx: Tx, user_id: uuid.UUID, template: str, event: str) -> bool:
    """An email with no in-app notification. True if it was queued (the event is new)."""
    return (
        tx.session.execute(
            insert(EmailOutbox)
            .values(
                user_id=user_id,
                template=template,
                params={},
                dedupe_key=f"{template}:{user_id}:{event}",
                next_attempt_at=tx.now,
            )
            .on_conflict_do_nothing(index_elements=[EmailOutbox.dedupe_key])
            .returning(EmailOutbox.id)
        ).scalar()
        is not None
    )


def _user_by_email(tx: Tx, email: str) -> User | None:
    return tx.session.execute(select(User).where(User.email == email.strip())).scalar()


def _check_signup_limit(tx: Tx, signup_address: bytes) -> None:
    """R-AU5: a handful of sign-ups per network address per hour."""
    recent = tx.session.execute(
        select(func.count())
        .select_from(User)
        .where(
            User.signup_ip_hash == signup_address,
            User.created_at > tx.real_now - timedelta(hours=1),
        )
    ).scalar_one()
    if recent >= SIGNUPS_PER_ADDRESS_PER_HOUR:
        raise ServiceError(Code.SIGNUP_LIMIT, "Too many sign-ups. Please try again later.")


def register_client(
    tx: Tx,
    *,
    email: str,
    password: str,
    full_name: str,
    phone: str | None,
    district_id: int,
    signup_address: bytes,
) -> None:
    """A new client account, not yet confirmed. **It answers the same way whether or not
    the email already has an account** (R-AU7): the difference is only in the email sent.
    """
    check_strength(password)
    if tx.session.get(District, district_id) is None:
        raise ServiceError(Code.VALIDATION_ERROR, "Unknown district.", field="district_id")
    _check_signup_limit(tx, signup_address)
    # Hashed before we look: registering takes as long for a known email as for a new one.
    password_hash = hash_password(password)
    existing = _user_by_email(tx, email)
    if existing is not None:
        # "You already have an account: just log in", once per address per day (N-47).
        _queue(tx, existing.id, ALREADY_REGISTERED, tx.real_now.date().isoformat())
        return
    user = User(
        id=uuid.uuid4(),
        email=email.strip(),
        password_hash=password_hash,
        role=UserRole.CLIENT.value,
        full_name=full_name.strip(),
        phone=(phone or "").strip() or None,
        signup_ip_hash=signup_address,
    )
    tx.session.add(user)
    tx.session.flush()
    tx.session.add(ClientProfile(user_id=user.id, district_id=district_id))
    audit.record(
        tx,
        Actor.CLIENT,
        "client.registered",
        "client",
        user.id,
        actor_id=user.id,
        after={"status": ClientStatus.UNVERIFIED.value},
    )
    _queue(tx, user.id, VERIFY_EMAIL, uuid.uuid4().hex)


def register_pharmacy(
    tx: Tx,
    *,
    email: str,
    password: str,
    details: pharmacy_profile.Details,
    signup_address: bytes,
) -> None:
    """A new pharmacy and its one account (P-D5), not yet confirmed. Like a client's
    sign-up, **it answers the same way whether or not the email has an account** (R-AU7).

    The licence and the phone are checked first, whoever asks: a taken one is refused the
    same way for a new email and for a known one, so that refusal says nothing about the
    email. The pharmacy enters the admin's queue once its email is confirmed.
    """
    check_strength(password)
    _check_signup_limit(tx, signup_address)
    password_hash = hash_password(password)
    pharmacy_profile.check_free(tx, details)
    existing = _user_by_email(tx, email)
    if existing is not None:
        _queue(tx, existing.id, ALREADY_REGISTERED, tx.real_now.date().isoformat())
        return
    user = User(
        id=uuid.uuid4(),
        email=email.strip(),
        password_hash=password_hash,
        role=UserRole.PHARMACIST.value,
        full_name=details.name,
        signup_ip_hash=signup_address,
    )
    tx.session.add(user)
    tx.session.flush()
    pharmacy_profile.create(tx, user.id, details)
    _queue(tx, user.id, VERIFY_EMAIL, uuid.uuid4().hex)


def resend_verification(tx: Tx, user_id: uuid.UUID) -> None:
    """Another confirmation email, at most once a minute and 5 times a day (N-47)."""
    user = tx.session.get_one(User, user_id)
    if user.email_verified_at is not None:
        return
    sent = (
        tx.session.execute(
            select(EmailOutbox.created_at)
            .where(
                EmailOutbox.user_id == user_id,
                EmailOutbox.template == VERIFY_EMAIL,
                EmailOutbox.created_at > tx.real_now - timedelta(days=1),
            )
            .order_by(EmailOutbox.created_at.desc())
        )
        .scalars()
        .all()
    )
    # The first email, sent at registration, is not a resend.
    if len(sent) > RESEND_VERIFICATION_PER_DAY:
        raise ServiceError(Code.RATE_LIMITED, "Too many emails today.", retry_after_s=3600)
    if sent and sent[0] > tx.real_now - RESEND_VERIFICATION_EVERY:
        wait = RESEND_VERIFICATION_EVERY - (tx.real_now - sent[0])
        raise ServiceError(
            Code.RATE_LIMITED,
            "Please wait a minute before asking again.",
            retry_after_s=max(1, int(wait.total_seconds())),
        )
    _queue(tx, user.id, VERIFY_EMAIL, uuid.uuid4().hex)


def new_verification_token(tx: Tx, user_id: uuid.UUID) -> str:
    """A confirmation link's token, made when its email is written. The token itself is
    never stored: only its hash (R-AU4)."""
    token = secrets.token_urlsafe(32)
    tx.session.add(
        EmailVerificationToken(
            id=uuid.uuid4(),
            user_id=user_id,
            token_hash=_digest(token),
            expires_at=tx.real_now + VERIFICATION_LINK_VALID,
        )
    )
    return token


def verify_email(tx: Tx, token: str) -> LoggedIn:
    """Following the link confirms the address **and logs the user in** (R-AU4)."""
    found = tx.session.execute(
        select(EmailVerificationToken)
        .where(EmailVerificationToken.token_hash == _digest(token))
        .with_for_update()
    ).scalar()
    if found is None or found.used_at is not None or found.expires_at <= tx.real_now:
        raise ServiceError(Code.TOKEN_INVALID, "This link is no longer valid. Ask for a new one.")
    found.used_at = tx.real_now
    user = tx.session.get_one(User, found.user_id)
    if user.email_verified_at is None:
        user.email_verified_at = tx.real_now
        profile = tx.session.get(ClientProfile, user.id)
        if profile is not None and profile.status == ClientStatus.UNVERIFIED.value:
            profile.status = ClientStatus.ACTIVE.value
            audit.record(
                tx,
                Actor.CLIENT,
                "client.verified",
                "client",
                user.id,
                actor_id=user.id,
                before={"status": ClientStatus.UNVERIFIED.value},
                after={"status": ClientStatus.ACTIVE.value},
            )
        own = pharmacy_of(tx, user.id)
        if own is not None:
            pharmacy_profile.email_confirmed(tx, own)
    _refuse_suspended(tx, user)
    return start_session(tx, user)


# --- Sessions ---------------------------------------------------------------------------


def _refuse_suspended(tx: Tx, user: User) -> None:
    """A suspended client can't log in (SM-2). A suspended pharmacy still can, to finish
    the reservations it holds (SM-1)."""
    profile = tx.session.get(ClientProfile, user.id)
    if profile is not None and profile.status == ClientStatus.SUSPENDED.value:
        raise ServiceError(Code.ACCOUNT_SUSPENDED, "This account is suspended.")


def start_session(tx: Tx, user: User) -> LoggedIn:
    token = secrets.token_urlsafe(32)
    lifetime = ADMIN_SESSION_LIFETIME if user.role == UserRole.ADMIN.value else SESSION_LIFETIME
    expires_at = tx.real_now + lifetime
    tx.session.add(
        Session(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=_digest(token),
            expires_at=expires_at,
            last_seen_at=tx.real_now,
        )
    )
    return LoggedIn(user, token, expires_at)


def _count_failure(tx: Tx, user: User) -> None:
    """R-AU2: 5 failures within 15 minutes lock the account for 15 minutes."""
    last_touched = user.updated_at
    if user.failed_logins and last_touched < tx.real_now - LOGIN_LOCK:
        user.failed_logins = 0
    user.failed_logins += 1
    if user.failed_logins >= FAILED_LOGINS_BEFORE_LOCK:
        user.locked_until = tx.real_now + LOGIN_LOCK
        user.failed_logins = 0
        audit.record(tx, Actor.SYSTEM, "login.locked", "user", user.id)


def login(
    tx: Tx, *, email: str, password: str, totp_code: str | None, secret_key: str
) -> LoggedIn | None:
    """Checks a login. **Returns None for a wrong email, password or code**, after
    counting the failure: the caller commits that count, then answers
    `INVALID_CREDENTIALS`. Raising here would undo the count with the transaction.
    """
    user = tx.session.execute(
        select(User).where(User.email == email.strip()).with_for_update()
    ).scalar()
    if user is None:
        _password_matches(_NOBODY, password)
        return None
    if user.locked_until is not None and user.locked_until > tx.real_now:
        retry_after = int((user.locked_until - tx.real_now).total_seconds()) + 1
        raise ServiceError(
            Code.ACCOUNT_LOCKED,
            "Too many failed logins. Please try again in a few minutes.",
            retry_after=retry_after,
        )
    step: int | None = None
    known = _password_matches(user.password_hash, password)
    if known and user.role == UserRole.ADMIN.value:
        # A wrong or missing code looks exactly like a wrong password (docs/06 §2.1).
        step = _totp_step(user, totp_code, secret_key, tx.real_now)
        known = step is not None
    if not known:
        _count_failure(tx, user)
        return None
    _refuse_suspended(tx, user)
    user.failed_logins, user.locked_until = 0, None
    if step is not None:
        user.totp_last_step = step
    return start_session(tx, user)


def session_user(tx: Tx, token: str) -> tuple[User, Session] | None:
    """Who a token belongs to, or None: unknown, expired, logged out or revoked."""
    found = tx.session.execute(
        select(Session, User)
        .join(User, User.id == Session.user_id)
        .where(Session.token_hash == _digest(token))
    ).first()
    if found is None:
        return None
    session, user = found
    if session.revoked_at is not None or session.expires_at <= tx.real_now:
        return None
    return user, session


def logout(tx: Tx, session_id: uuid.UUID) -> None:
    tx.session.execute(
        update(Session)
        .where(Session.id == session_id, Session.revoked_at.is_(None))
        .values(revoked_at=tx.real_now)
    )


def revoke_sessions(tx: Tx, user_id: uuid.UUID, *, keep: uuid.UUID | None = None) -> None:
    """Every login of this user ends now (a suspension, a new password)."""
    statement = (
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=tx.real_now)
    )
    if keep is not None:
        statement = statement.where(Session.id != keep)
    tx.session.execute(statement)


def change_password(
    tx: Tx, user_id: uuid.UUID, *, current: str, new: str, keep_session: uuid.UUID
) -> bool:
    """A new password; every other login ends (R-AU3). False if `current` is wrong."""
    user = tx.session.get_one(User, user_id)
    if not _password_matches(user.password_hash, current):
        return False
    check_strength(new)
    user.password_hash = hash_password(new)
    revoke_sessions(tx, user_id, keep=keep_session)
    audit.record(tx, Actor(_actor_of(user)), "password.changed", "user", user.id, actor_id=user.id)
    return True


def _actor_of(user: User) -> str:
    return {
        UserRole.CLIENT.value: Actor.CLIENT.value,
        UserRole.PHARMACIST.value: Actor.PHARMACY.value,
        UserRole.ADMIN.value: Actor.ADMIN.value,
    }[user.role]


# --- Accounts made by a command ---------------------------------------------------------


def create_admin(
    tx: Tx, *, email: str, password: str, full_name: str, secret_key: str
) -> tuple[User, str]:
    """The only way an admin exists (A-D1). Returns the user and the authenticator
    secret, shown once by the command and never again."""
    check_strength(password)
    if _user_by_email(tx, email) is not None:
        raise ServiceError(Code.VALIDATION_ERROR, "This email already has an account.")
    plain, stored = new_totp_secret(secret_key)
    user = User(
        id=uuid.uuid4(),
        email=email.strip(),
        password_hash=hash_password(password),
        role=UserRole.ADMIN.value,
        full_name=full_name.strip(),
        email_verified_at=tx.real_now,
        totp_secret=stored,
    )
    tx.session.add(user)
    tx.session.flush()
    audit.record(tx, Actor.SYSTEM, "admin.created", "user", user.id)
    return user, plain


def pharmacy_of(tx: Tx, user_id: uuid.UUID) -> Pharmacy | None:
    return tx.session.execute(select(Pharmacy).where(Pharmacy.owner_user_id == user_id)).scalar()
