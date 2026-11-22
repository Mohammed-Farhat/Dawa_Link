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
import string
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from zxcvbn.frequency_lists import FREQUENCY_LISTS

from dawalink.db.models import (
    ClientProfile,
    EmailOutbox,
    EmailVerificationToken,
    PasswordResetToken,
    Pharmacy,
    SearchHistory,
    Session,
    User,
)
from dawalink.domain import client_details
from dawalink.domain.accounts import ClientStatus
from dawalink.domain.numbers import (
    ADMIN_SESSION_LIFETIME,
    COMMON_PASSWORDS,
    FAILED_LOGINS_BEFORE_LOCK,
    LOGIN_LOCK,
    PASSWORD_HASH_LANES,
    PASSWORD_HASH_MEMORY_KIB,
    PASSWORD_HASH_PASSES,
    PASSWORD_HASH_WAIT,
    PASSWORD_HASHES_AT_ONCE,
    PASSWORD_MIN_CHARS,
    RESEND_VERIFICATION_EVERY,
    RESEND_VERIFICATION_PER_DAY,
    RESET_EMAILS_PER_DAY,
    RESET_EMAILS_PER_HOUR,
    RESET_LINK_VALID,
    SESSION_LIFETIME,
    SIGNUPS_PER_ADDRESS_PER_HOUR,
    VERIFICATION_LINK_VALID,
)
from dawalink.domain.state_machine import Actor
from dawalink.domain.vocabulary import UserRole
from dawalink.services import audit, clients, pharmacy_profile
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

VERIFY_EMAIL = "CN-1"
ALREADY_REGISTERED = "CN-18"
RESET_PASSWORD = "CN-19"
PASSWORD_CHANGED = "CN-20"

# argon2id with parameters of our own (R-AU1), never the library's defaults: those are
# 64 MiB a hash, and change with the library. A hash made with other parameters still
# verifies with its own, and is made again at its owner's next login.
_hasher = PasswordHasher(
    memory_cost=PASSWORD_HASH_MEMORY_KIB,
    time_cost=PASSWORD_HASH_PASSES,
    parallelism=PASSWORD_HASH_LANES,
)
# Checked for an email nobody has, so a login takes as long either way (R-AU7).
_NOBODY = _hasher.hash(secrets.token_urlsafe(16))
# How many hashes and checks may run at once in this process, and how long a request waits
# for one. Module names, so that a test can make the wait short.
_slots = threading.BoundedSemaphore(PASSWORD_HASHES_AT_ONCE)
_slot_wait_s = PASSWORD_HASH_WAIT.total_seconds()
# R-AU1: the most common passwords, lower case.
_COMMON = frozenset(word.lower() for word in FREQUENCY_LISTS["passwords"][:COMMON_PASSWORDS])


@dataclass(frozen=True)
class LoggedIn:
    user: User
    # Given to the browser once. Only its hash is stored.
    token: str
    expires_at: datetime


# --- Passwords --------------------------------------------------------------------------


# R-AU1 (the owner, 2026-11-18): what a password must hold, in the order the form lists
# it. Letters and symbols are the plain ASCII ones, which is also what Cognito counts
# (docs/12 §10), so the rule can move there unchanged.
PASSWORD_PARTS: dict[str, Callable[[str], bool]] = {
    "length": lambda password: len(password) >= PASSWORD_MIN_CHARS,
    "capital": lambda password: any(c in string.ascii_uppercase for c in password),
    "small": lambda password: any(c in string.ascii_lowercase for c in password),
    "number": lambda password: any(c in string.digits for c in password),
    "symbol": lambda password: any(c in string.punctuation for c in password),
}


def password_gaps(password: str) -> list[str]:
    """What this password still lacks, by the names of `PASSWORD_PARTS`."""
    return [part for part, holds in PASSWORD_PARTS.items() if not holds(password)]


def check_strength(password: str) -> None:
    """R-AU1: at least 10 characters with a capital letter, a small letter, a number and
    a symbol, and not one of the most common passwords."""
    missing = password_gaps(password)
    if missing:
        raise ServiceError(
            Code.WEAK_PASSWORD,
            f"Use at least {PASSWORD_MIN_CHARS} characters, with a capital letter, "
            "a small letter, a number and a symbol.",
            min_chars=PASSWORD_MIN_CHARS,
            missing=missing,
        )
    # A common word dressed up to pass the rule ("Password123!") is still the common word:
    # the numbers and symbols around it are not counted.
    word = password.lower()
    if word in _COMMON or word.strip(string.digits + string.punctuation) in _COMMON:
        raise ServiceError(
            Code.WEAK_PASSWORD, "This password is too common. Choose another.", missing=["uncommon"]
        )


class NoSlotFree(Exception):
    """No slot for a password's hash came free in time. Nothing was counted or changed:
    the caller answers "try again shortly" (docs/09 FX-12's answer)."""


@contextmanager
def password_slot() -> Iterator[None]:
    """One of the few slots in which passwords are hashed or checked (R-AU1).

    The routes that hash take one **before** their transaction opens, so a request that
    waits here holds no database connection and no row. The hashing functions below don't
    take it themselves: a semaphore is not re-entrant, and the commands and the demo seed
    that call them run alone.
    """
    if not _slots.acquire(timeout=_slot_wait_s):
        raise NoSlotFree
    try:
        yield
    finally:
        _slots.release()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _password_matches(stored: str, password: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        # Also a demo account whose password was never set: nothing matches it.
        return False


def _renew_old_hash(user: User, password: str) -> None:
    """After a password matched: a hash made with other parameters (the library's old
    defaults) is made again with ours, so every account ends up costing the same."""
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)


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


def _queue(
    tx: Tx, user_id: uuid.UUID, template: str, event: str, params: dict[str, str] | None = None
) -> bool:
    """An email with no in-app notification. True if it was queued (the event is new)."""
    return (
        tx.session.execute(
            insert(EmailOutbox)
            .values(
                user_id=user_id,
                template=template,
                params=params or {},
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


def _check_signup_limit(tx: Tx, signup_address: bytes | None) -> None:
    """R-AU5: a handful of sign-ups per network address per hour.

    No address (in AWS, CloudFront's header missing, R-AU8): nothing is counted. Every
    sign-up would otherwise count under the load balancer's address, and five strangers
    would stop all sign-ups for an hour.
    """
    if signup_address is None:
        return
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
    first_name: str,
    middle_name: str | None,
    last_name: str,
    birth_date: date,
    phone: str | None,
    district_id: int | None = None,
    home_area_id: int | None = None,
    home_place: tuple[float, float] | None = None,
    signup_address: bytes | None,
) -> None:
    """A new client account, not yet confirmed. **It answers the same way whether or not
    the email already has an account** (R-AU7): the difference is only in the email sent.

    An email whose earlier client sign-up was never confirmed is signed up again: this
    sign-up replaces that one (`_sign_up_again`). Otherwise anyone could take an address
    first, and its owner could never claim it (a reset link goes only to a confirmed
    address, R-AU9).
    """
    check_strength(password)
    # Everything typed is checked before the email is looked at, so a mistake in the form
    # answers the same way for a known address as for a new one (R-AU7).
    profile = ClientProfile(user_id=uuid.uuid4())
    clients.check_details(
        tx,
        profile,
        first=first_name,
        middle=middle_name,
        last=last_name,
        born=birth_date,
        district_id=district_id,
        area_id=home_area_id,
        place=home_place,
    )
    _check_signup_limit(tx, signup_address)
    # Hashed before we look: registering takes as long for a known email as for a new one.
    password_hash = hash_password(password)
    existing = _lock_account_of(tx, email)
    if existing is not None:
        earlier = tx.session.get(ClientProfile, existing.id)
        if (
            earlier is not None
            and existing.email_verified_at is None
            and earlier.status == ClientStatus.UNVERIFIED.value
        ):
            _sign_up_again(tx, existing, earlier, profile, password_hash=password_hash, phone=phone)
            return
        # "You already have an account: just log in", once per address per day (N-47).
        _queue(tx, existing.id, ALREADY_REGISTERED, tx.real_now.date().isoformat())
        return
    user = User(
        id=profile.user_id,
        email=email.strip(),
        password_hash=password_hash,
        role=UserRole.CLIENT.value,
        full_name=client_details.whole_name(
            profile.first_name or "", profile.middle_name, profile.last_name or ""
        ),
        phone=(phone or "").strip() or None,
        signup_ip_hash=signup_address,
    )
    tx.session.add(user)
    tx.session.flush()
    tx.session.add(profile)
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


def _lock_account_of(tx: Tx, email: str) -> User | None:
    """The account of this email, locked in the global order: a client's profile first,
    then the user's row (docs/05 §6), as a deletion and a confirmation link lock them.
    Locking the user's row first could deadlock with a deletion of an unconfirmed client.

    The id is read without a lock, then the rows are locked and the email read again: an
    account deleted in between has another email (`deleted_email`), and is no account of
    this address any more.
    """
    found = tx.session.execute(select(User.id).where(User.email == email.strip())).scalar()
    if found is None:
        return None
    tx.session.execute(
        select(ClientProfile)
        .where(ClientProfile.user_id == found)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    return tx.session.execute(
        select(User)
        .where(User.id == found, User.email == email.strip())
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()


def _sign_up_again(
    tx: Tx,
    user: User,
    stored: ClientProfile,
    typed: ClientProfile,
    *,
    password_hash: str,
    phone: str | None,
) -> None:
    """A client sign-up for an email whose earlier sign-up was never confirmed: this one
    replaces it.

    Whoever signed up first may not own the address. Their password and details give way
    to these, their logins and confirmation links end, and a fresh link goes to the
    address: its owner ends up with the password they chose. The caller answers as for
    any sign-up (R-AU7), and the limits counted are the same.
    """
    user.password_hash = password_hash
    user.phone = (phone or "").strip() or None
    user.failed_logins, user.locked_until = 0, None
    clients.set_name(
        tx,
        stored,
        first=typed.first_name or "",
        middle=typed.middle_name,
        last=typed.last_name or "",
    )
    stored.birth_date = typed.birth_date
    # Everything the form says, empty parts included: an earlier town or place must not
    # stay behind under the new owner.
    stored.district_id, stored.home_area_id = typed.district_id, typed.home_area_id
    stored.home_lat, stored.home_lon = typed.home_lat, typed.home_lon
    stored.alternatives_ok_default = False
    # What the earlier signer searched is theirs, not the new owner's.
    tx.session.execute(delete(SearchHistory).where(SearchHistory.client_id == user.id))
    revoke_sessions(tx, user.id)  # their logins and their links
    audit.record(tx, Actor.CLIENT, "client.registered_again", "client", user.id, actor_id=user.id)
    # A fresh link, within the day's cap of confirmation emails (N-47), so that signing up
    # again and again can't flood an address. Over it nothing is sent, silently: a refusal
    # here would say that the address was known. The owner can still log in with the
    # password just chosen and ask for a link the next day.
    if _confirmation_refusal(tx, user.id, minute_too=False) is None:
        _queue(tx, user.id, VERIFY_EMAIL, uuid.uuid4().hex)


def register_pharmacy(
    tx: Tx,
    *,
    email: str,
    password: str,
    details: pharmacy_profile.Details,
    signup_address: bytes | None,
) -> None:
    """A new pharmacy and its one account (P-D5), not yet confirmed. Like a client's
    sign-up, **it answers the same way whether or not the email has an account** (R-AU7).

    The licence and the phone are checked first, whoever asks: a taken one is refused the
    same way for a new email and for a known one, so that refusal says nothing about the
    email. The pharmacy enters the admin's queue once its email is confirmed.
    """
    check_strength(password)
    _check_signup_limit(tx, signup_address)
    # A taken licence or phone is refused before the hash: a refusal costs no hash, so
    # repeating one costs the server nothing (the sign-up limit counts only sign-ups).
    pharmacy_profile.check_free(tx, details)
    password_hash = hash_password(password)
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
    refusal = _confirmation_refusal(tx, user_id)
    if refusal is not None:
        raise refusal
    _queue(tx, user.id, VERIFY_EMAIL, uuid.uuid4().hex)


def _confirmation_refusal(
    tx: Tx, user_id: uuid.UUID, *, minute_too: bool = True
) -> ServiceError | None:
    """Why no other confirmation email may go to this user now (N-47), or None.

    `minute_too=False` keeps only the day's cap: a sign-up that replaces another needs its
    own link at once, since the earlier ones stopped working.
    """
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
        return ServiceError(Code.RATE_LIMITED, "Too many emails today.", retry_after_s=3600)
    if minute_too and sent and sent[0] > tx.real_now - RESEND_VERIFICATION_EVERY:
        wait = RESEND_VERIFICATION_EVERY - (tx.real_now - sent[0])
        return ServiceError(
            Code.RATE_LIMITED,
            "Please wait a minute before asking again.",
            retry_after_s=max(1, int(wait.total_seconds())),
        )
    return None


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


def verify_email(tx: Tx, token: str) -> None:
    """Following the link confirms the address, and **logs nobody in** (R-AU4; the owner,
    2026-11-22). The person then logs in with their password.

    Why no login: the password of an unconfirmed account may be someone else's. A
    stranger who signs up with the owner's address after the owner did replaces the
    owner's sign-up (`_sign_up_again`), and the fresh link looks like any other. Had the
    link logged in, the owner would have been logged in to an account whose password the
    stranger knows.

    A link works once, and only while the address is not confirmed (TM-D7): once it is,
    every other link of the user ends, and one made afterwards (an email that was still
    waiting to be sent) is refused.

    Confirming ends every earlier login of the account: whoever logged in before the
    address was confirmed may not own it. After it, nobody is logged in.

    A suspended client's address is not confirmed (`_refuse_suspended`, and the
    transaction is rolled back): they can't log in anyway (SM-2), and the link stays as it
    was.
    """
    by_hash = select(EmailVerificationToken).where(
        EmailVerificationToken.token_hash == _digest(token)
    )
    owner = tx.session.execute(by_hash.with_only_columns(EmailVerificationToken.user_id)).scalar()
    if owner is None:
        raise ServiceError(Code.TOKEN_INVALID, "This link is no longer valid. Ask for a new one.")
    # A client's profile is the first lock (docs/05 §6), as in a deletion, which locks it
    # and then the user's row: the other order could deadlock with it.
    profile = tx.session.execute(
        select(ClientProfile)
        .where(ClientProfile.user_id == owner)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar()
    # The user's row is locked before the link's, as everywhere a user's links change (a
    # new password, a sign-up again, the daily clean-up): one order, no deadlock.
    user = tx.session.execute(select(User).where(User.id == owner).with_for_update()).scalar()
    found = tx.session.execute(
        by_hash.with_for_update().execution_options(populate_existing=True)
    ).scalar()
    # Either may be gone between the two reads: the daily clean-up deletes a pharmacy's
    # registration that was never confirmed, with its links.
    if (
        user is None
        or found is None
        or found.used_at is not None
        or found.expires_at <= tx.real_now
    ):
        raise ServiceError(Code.TOKEN_INVALID, "This link is no longer valid. Ask for a new one.")
    if user.email_verified_at is not None:
        raise ServiceError(Code.TOKEN_INVALID, "This email is already confirmed. Please log in.")
    user.email_verified_at = tx.real_now
    revoke_sessions(tx, user.id)  # every earlier login, and every other link
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


def _end_links(tx: Tx, user_id: uuid.UUID) -> None:
    """Every link of this user that is still good stops working: confirmation links and
    "set a new password" links alike. This is the one place a user's links end."""
    for link in (EmailVerificationToken, PasswordResetToken):
        tx.session.execute(
            update(link)
            .where(link.user_id == user_id, link.used_at.is_(None))
            .values(used_at=tx.real_now)
        )


# --- Sessions ---------------------------------------------------------------------------


def _refuse_suspended(tx: Tx, user: User) -> None:
    """A suspended client can't log in (SM-2). A suspended pharmacy still can, to finish
    the reservations it holds (SM-1).

    A deleted account can't be reached here at all: its email is one nobody can type, and
    its links ended with it (R-AU10). Should one ever get this far, it is refused like a
    login that doesn't work, which says nothing about it."""
    profile = tx.session.get(ClientProfile, user.id)
    if profile is not None and profile.status == ClientStatus.SUSPENDED.value:
        raise ServiceError(Code.ACCOUNT_SUSPENDED, "This account is suspended.")
    if profile is not None and profile.status == ClientStatus.DELETED.value:
        raise ServiceError(Code.TOKEN_INVALID, "This link is no longer valid. Ask for a new one.")


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


class FailedLoginsOfNobody:
    """Failed logins for emails that have **no account**, counted exactly like an
    account's own (R-AU2): five within 15 minutes, then "locked" for 15 minutes.

    Without it the lock itself says who has an account: after five wrong passwords a real
    email answers `ACCOUNT_LOCKED`, while an email nobody has would answer
    `INVALID_CREDENTIALS` for ever (docs/10 TH-3, TM-D7).

    Kept in memory, under a hash of the email: there is no row to count on, and nothing
    here has to outlive a restart. The API keeps one for its whole life.
    """

    MOST = 10_000

    def __init__(self) -> None:
        # hash of the email -> (failures, when the last one was, locked until)
        self._seen: dict[bytes, tuple[int, datetime, datetime | None]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(email: str) -> bytes:
        return hashlib.sha256(email.strip().lower().encode()).digest()

    def locked_until(self, email: str, now: datetime) -> datetime | None:
        with self._lock:
            found = self._seen.get(self._key(email))
        return found[2] if found and found[2] is not None and found[2] > now else None

    def count(self, email: str, now: datetime) -> None:
        """One more failure, by the rule of `_count_failure`."""
        key = self._key(email)
        with self._lock:
            failures, last, _ = self._seen.get(key, (0, now, None))
            if failures and last < now - LOGIN_LOCK:
                failures = 0
            failures += 1
            locked = failures >= FAILED_LOGINS_BEFORE_LOCK
            self._seen[key] = (
                0 if locked else failures,
                now,
                now + LOGIN_LOCK if locked else None,
            )
            if len(self._seen) > self.MOST:
                self._forget(now)

    def _forget(self, now: datetime) -> None:
        idle = [key for key, (_, last, _until) in self._seen.items() if last < now - LOGIN_LOCK]
        for key in idle or list(self._seen)[: self.MOST // 2]:
            del self._seen[key]


def _locked(until: datetime, now: datetime) -> ServiceError:
    return ServiceError(
        Code.ACCOUNT_LOCKED,
        "Too many failed logins. Please try again in a few minutes.",
        retry_after=int((until - now).total_seconds()) + 1,
    )


def login(
    tx: Tx,
    *,
    email: str,
    password: str,
    totp_code: str | None,
    secret_key: str,
    nobody: FailedLoginsOfNobody,
) -> LoggedIn | None:
    """Checks a login. **Returns None for a wrong email, password or code**, after
    counting the failure: the caller commits that count, then answers
    `INVALID_CREDENTIALS`. Raising here would undo the count with the transaction.

    An email that has no account goes the same way as one that has: the same work, the
    same answers, the same lock after the same number of failures (`nobody` counts them).
    """
    user = tx.session.execute(
        select(User).where(User.email == email.strip()).with_for_update()
    ).scalar()
    if user is None:
        until = nobody.locked_until(email, tx.real_now)
        if until is not None:
            raise _locked(until, tx.real_now)
        _password_matches(_NOBODY, password)
        nobody.count(email, tx.real_now)
        return None
    if user.locked_until is not None and user.locked_until > tx.real_now:
        raise _locked(user.locked_until, tx.real_now)
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
    _renew_old_hash(user, password)
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
    """Every login of this user ends now (a suspension, a new password, a sign-up that
    replaces an unconfirmed one, a confirmed address). Its links end too: a confirmation
    link confirms the address of whoever set the password (docs/10 TH-2), and a reset
    link is a new password in one form (R-AU9)."""
    statement = (
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=tx.real_now)
    )
    if keep is not None:
        statement = statement.where(Session.id != keep)
    tx.session.execute(statement)
    _end_links(tx, user_id)


def confirm_password(tx: Tx, user_id: uuid.UUID, password: str) -> User | None:
    """Someone already logged in types their password again, to prove it is them before
    something that a stolen session alone must not do: a new password (R-AU3), deleting
    the account (R-AU10). Returns the user, locked, or **None if the password is wrong**.

    A wrong password counts like a failed login (R-AU2), on the same counter and lock:
    the caller commits that count, then answers. Otherwise a stolen session could guess
    the password for ever. While the account is locked, nothing is checked. The caller
    holds a password slot (`password_slot`).
    """
    user = tx.session.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one()
    if user.locked_until is not None and user.locked_until > tx.real_now:
        raise _locked(user.locked_until, tx.real_now)
    if not _password_matches(user.password_hash, password):
        _count_failure(tx, user)
        return None
    return user


def change_password(
    tx: Tx, user_id: uuid.UUID, *, current: str, new: str, keep_session: uuid.UUID
) -> bool:
    """A new password; every other login ends (R-AU3).

    **Returns False if `current` is wrong**, after counting it (`confirm_password`).
    """
    user = confirm_password(tx, user_id, current)
    if user is None:
        return False
    check_strength(new)
    user.failed_logins = 0
    user.password_hash = hash_password(new)
    revoke_sessions(tx, user_id, keep=keep_session)
    audit.record(tx, Actor(_actor_of(user)), "password.changed", "user", user.id, actor_id=user.id)
    return True


def deleted_email(user_id: uuid.UUID) -> str:
    """What a deleted account's email becomes (R-AU10).

    - **Nobody can type it:** it starts with a space, and every email typed into DawaLink
      is trimmed before it is stored or looked up (`api.schemas.common.In`, and `.strip()`
      here). So a login, a sign-up or a reset with the old address, or with this one,
      finds no account, exactly like an address nobody ever used.
    - **No mail can reach it:** `.invalid` is a name reserved never to exist (RFC 2606);
      and nothing is sent to a deleted account anyway (`email.send_one`).
    - **It never collides:** the account's own ID is in it.
    """
    return f" deleted-{user_id.hex}@deleted.invalid"


# What a deleted account's password hash becomes: not an argon2 hash, so no password
# matches it (`_password_matches`) and no reset link can be asked for it (`_may_reset`).
DELETED_PASSWORD_HASH = "!deleted"


def close_login(tx: Tx, user: User) -> None:
    """A client deleted their account (R-AU10): their login ends for good. Every session
    ends (every device is logged out), every link ends, and nothing about the login is
    left that could lead to them: the email, the network address they signed up from.
    The caller holds the user's row."""
    user.email = deleted_email(user.id)
    user.password_hash = DELETED_PASSWORD_HASH
    user.signup_ip_hash = None
    user.failed_logins, user.locked_until = 0, None
    user.totp_secret, user.totp_last_step = None, None
    revoke_sessions(tx, user.id)


def _actor_of(user: User) -> str:
    return {
        UserRole.CLIENT.value: Actor.CLIENT.value,
        UserRole.PHARMACIST.value: Actor.PHARMACY.value,
        UserRole.ADMIN.value: Actor.ADMIN.value,
    }[user.role]


# --- A forgotten password (R-AU9) -------------------------------------------------------
#
# Kept to these functions and one pair of routes, so that it can be rebuilt on Cognito's
# own "forgot password" flow (docs/12 §10).

_LINK_GONE = "This link is no longer valid. Ask for a new one."


def _may_reset(tx: Tx, user: User) -> bool:
    """Whether this account may have a reset link: exactly an account that could log in
    with its right password today (R-AU9).

    - Never an admin: a lost admin is made again by the command (A-D1, R-AU6).
    - Never an email that was never confirmed: its owner signs up again, which replaces
      that sign-up.
    - Never an account with no password at all (a demo account whose password was never
      set): it can't log in today.
    - A client, unless suspended (SM-2). A pharmacist logs in whatever its pharmacy's
      state (SM-1), so any pharmacist whose email is confirmed.
    """
    if user.role == UserRole.ADMIN.value or user.email_verified_at is None:
        return False
    if not user.password_hash.startswith("$argon2"):
        return False
    if user.role == UserRole.PHARMACIST.value:
        return True
    profile = tx.session.get(ClientProfile, user.id)
    return profile is not None and profile.status in (
        ClientStatus.ACTIVE.value,
        ClientStatus.PAUSED.value,
    )


def _reset_emails_left(tx: Tx, user_id: uuid.UUID) -> bool:
    """Whether one more reset email may go to this account (R-AU9): a few an hour and a
    day, so that nobody can make DawaLink send one address email after email."""
    sent = (
        tx.session.execute(
            select(EmailOutbox.created_at).where(
                EmailOutbox.user_id == user_id,
                EmailOutbox.template == RESET_PASSWORD,
                EmailOutbox.created_at > tx.real_now - timedelta(days=1),
            )
        )
        .scalars()
        .all()
    )
    this_hour = [at for at in sent if at > tx.real_now - timedelta(hours=1)]
    return len(sent) < RESET_EMAILS_PER_DAY and len(this_hour) < RESET_EMAILS_PER_HOUR


def ask_password_reset(tx: Tx, email: str) -> None:
    """Someone asks for a link to set a new password (R-AU9).

    **The caller answers the same thing whatever happens here** (R-AU7): the email is
    queued only for an account that may have a link and is under its caps; for an email
    nobody has, an admin, an unconfirmed or a suspended account, or one over its caps,
    nothing is sent and nothing is said. Nothing is hashed either way.

    The user's row is locked, so that two asks at once can't both pass the caps. Asking
    ends no link: one that is still good stops only when a newer one is written, so an ask
    over the caps can't take a working link away from its owner.
    """
    user = tx.session.execute(
        select(User).where(User.email == email.strip()).with_for_update()
    ).scalar()
    if user is None or not _may_reset(tx, user) or not _reset_emails_left(tx, user.id):
        return
    _queue(tx, user.id, RESET_PASSWORD, uuid.uuid4().hex)


def new_reset_token(tx: Tx, user_id: uuid.UUID) -> str:
    """A reset link's token, made when its email is written: the token itself is never
    stored, only its hash. Only the newest link works: the user's earlier ones end here."""
    tx.session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
        .values(used_at=tx.real_now)
    )
    token = secrets.token_urlsafe(32)
    tx.session.add(
        PasswordResetToken(
            id=uuid.uuid4(),
            user_id=user_id,
            token_hash=_digest(token),
            expires_at=tx.real_now + RESET_LINK_VALID,
        )
    )
    return token


def reset_password(tx: Tx, token: str, new: str) -> None:
    """The link's form: a new password for its account (R-AU9). Nobody is logged in.

    A link that can't be used is one answer, `TOKEN_INVALID`, whatever the reason: unknown,
    used, older than 30 real minutes, or its account can no longer log in (suspended or
    deleted since it was asked for). The link is checked before the password, so a wrong
    link costs no hash, and a password refused as too weak leaves the link as it was.

    On success every session of the user ends, every other link ends, a failed-login lock
    is lifted, and the owner is told by email (CN-20).
    """
    by_hash = select(PasswordResetToken).where(PasswordResetToken.token_hash == _digest(token))
    owner = tx.session.execute(by_hash.with_only_columns(PasswordResetToken.user_id)).scalar()
    if owner is None:
        raise ServiceError(Code.TOKEN_INVALID, _LINK_GONE)
    # The user's row before the link's, as everywhere a user's links change.
    user = tx.session.execute(select(User).where(User.id == owner).with_for_update()).scalar()
    found = tx.session.execute(
        by_hash.with_for_update().execution_options(populate_existing=True)
    ).scalar()
    if (
        user is None
        or found is None
        or found.used_at is not None
        or found.expires_at <= tx.real_now
        or not _may_reset(tx, user)
    ):
        raise ServiceError(Code.TOKEN_INVALID, _LINK_GONE)
    check_strength(new)
    user.password_hash = hash_password(new)
    user.failed_logins, user.locked_until = 0, None
    found.used_at = tx.real_now
    revoke_sessions(tx, user.id)  # every login, and every other link
    audit.record(
        tx,
        Actor(_actor_of(user)),
        "password.reset",
        "user",
        user.id,
        actor_id=user.id,
        after={"fields": ["password"]},
    )
    _queue(
        tx,
        user.id,
        PASSWORD_CHANGED,
        uuid.uuid4().hex,
        params={"changed_at": tx.real_now.isoformat()},
    )


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
