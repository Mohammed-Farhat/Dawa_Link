"""Public configuration, registration and logins (docs/06 §6.1)."""

import re
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, cast

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select

from dawalink.agent.turn import Agent
from dawalink.api import present
from dawalink.api.deps import (
    AsClient,
    DoWork,
    SignedIn,
    TheSettings,
    get_agent,
    secret_key,
    stated_address,
)
from dawalink.api.errors import ApiError, ErrorCode
from dawalink.api.limits import Limiter
from dawalink.api.schemas.accounts import (
    ChangePassword,
    DeleteAccount,
    DiscountTier,
    ForgotPassword,
    HomePlace,
    LoggedIn,
    Login,
    Me,
    PinIn,
    Place,
    ProfileChange,
    PublicConfig,
    RegisterClient,
    RegisterPharmacy,
    ResetPassword,
    VerifyEmail,
)
from dawalink.api.schemas.common import District as DistrictOut
from dawalink.api.schemas.common import Message
from dawalink.db.models import Area, CatalogImport, ClientProfile, District, PricingTier, User
from dawalink.domain.accounts import ClientStatus
from dawalink.domain.numbers import (
    MAX_MESSAGE_CHARS,
    OFFER_VALIDITY,
    POLL_EVERY_S,
    REQUEST_HOURS_END,
    REQUEST_HOURS_START,
    RESET_ASKS_PER_ADDRESS_PER_HOUR,
    RESET_LINK_VALID,
    SEARCH_WINDOW,
)
from dawalink.services import account_deletion, auth, clients, pharmacy_profile
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

log = structlog.get_logger(__name__)

router = APIRouter(tags=["accounts"])

CHECK_YOUR_EMAIL = Message(message="Check your email to continue.")


@contextmanager
def _password_slot() -> Iterator[None]:
    """One of the few slots in which a password is hashed (R-AU1), taken before the
    transaction opens: a request that waits for one holds no database connection.

    None free within a few seconds: the same "try again shortly" as a database with no
    free connection (docs/09 FX-12). Nothing was looked up or counted, so the answer says
    nothing about the email.
    """
    try:
        with auth.password_slot():
            yield
    except auth.NoSlotFree:
        log.warning("password_slots_full")
        raise ApiError(ErrorCode.SERVICE_UNAVAILABLE, details={"retry_after_s": 1}) from None


@router.get("/config/public")
def public_config(
    work: DoWork, settings: TheSettings, agent: Annotated[Agent | None, Depends(get_agent)]
) -> PublicConfig:
    with work.tx() as tx:
        newest = tx.session.execute(
            select(CatalogImport.lbp_per_usd, CatalogImport.source_date)
            .order_by(CatalogImport.source_date.desc())
            .limit(1)
        ).first()
        return PublicConfig(
            request_hours_start=f"{REQUEST_HOURS_START:%H:%M}",
            request_hours_end=f"{REQUEST_HOURS_END:%H:%M}",
            search_window_hours=int(SEARCH_WINDOW.total_seconds() // 3600),
            offer_hours=int(OFFER_VALIDITY.total_seconds() // 3600),
            lbp_per_usd=int(newest[0]) if newest else None,
            rate_date=newest[1].isoformat() if newest else None,
            poll_every_s=POLL_EVERY_S,
            max_message_chars=MAX_MESSAGE_CHARS,
            discount_tiers=[
                DiscountTier(
                    min_days=tier.min_days, max_days=tier.max_days, discount_pct=tier.discount_pct
                )
                for tier in tx.session.execute(
                    select(PricingTier).order_by(PricingTier.min_days)
                ).scalars()
            ],
            server_now=tx.now,
            demo_mode=settings.demo_mode,
            assistant_available=agent is not None,
        )


@router.get("/districts")
def districts(work: DoWork) -> list[DistrictOut]:
    with work.tx() as tx:
        rows = tx.session.execute(select(District).order_by(District.name)).scalars()
        return [present.district(row) for row in rows]


@router.get("/places")
def places_of_a_district(
    district_id: Annotated[int, Query(ge=1, le=32_767)], work: DoWork
) -> list[Place]:
    """The towns and neighbourhoods of a district, from our own list of places: what a
    client chooses a home town from. Public, like the list of districts.

    Only the places whose name is written in Latin letters: the map gives some villages a
    name in Arabic script only, and one list in two alphabets reads as a mistake (the
    owner, 2026-11-18). Those places can still be named to the assistant.
    """
    with work.tx() as tx:
        rows = tx.session.execute(
            select(Area)
            .where(Area.district_id == district_id, Area.whole_district.is_(False))
            .order_by(Area.name, Area.id)
        ).scalars()
        return [Place(id=row.id, name=row.name) for row in rows if row.name.isascii()]


@router.post("/auth/register/client", status_code=202)
def register_client(
    body: RegisterClient, request: Request, work: DoWork, settings: TheSettings
) -> Message:
    """Always "check your email", whether or not the address already has an account
    (R-AU7): nobody can find out here who uses DawaLink."""
    address = _sign_up_address(request, settings)
    phone = _a_phone_or_nothing(body.phone)
    _refuse_a_full_address(request, address)
    with _password_slot(), work.tx() as tx:
        auth.register_client(
            tx,
            email=body.email,
            password=body.password,
            first_name=body.first_name,
            middle_name=body.middle_name,
            last_name=body.last_name,
            birth_date=body.birth_date,
            phone=phone,
            district_id=body.district_id,
            home_area_id=body.home_area_id,
            home_place=(body.home_place.lat, body.home_place.lon) if body.home_place else None,
            signup_address=address,
        )
    _count_the_sign_up(request, address)
    return CHECK_YOUR_EMAIL


def _sign_up_address(request: Request, settings: TheSettings) -> bytes | None:
    """The hashed network address a sign-up counts under, or None when it isn't known.

    In AWS with CloudFront's header missing, every visitor would seem to be the load
    balancer: one limit for everybody would stop all sign-ups after five. So the limit per
    address is not counted then, as for a login (N-52), and the log says so (R-AU8).
    """
    address = stated_address(request, settings)
    return None if address is None else auth.address_hash(secret_key(settings), address)


def _refuse_a_full_address(request: Request, address: bytes | None) -> None:
    """R-AU5, for every sign-up that got as far as an account or an "already registered"
    email, whichever it was.

    The service counts the accounts made, and that count survives a restart. Counting
    only those would tell who already has an account: after four new sign-ups, one more
    with someone's email and one more again, the limit would come one sign-up later if
    that email was known (docs/10 TH-3).
    """
    limiter = cast(Limiter, request.app.state.signups_per_address)
    if address is not None and limiter.full(address):
        raise ServiceError(Code.SIGNUP_LIMIT, "Too many sign-ups. Please try again later.")


def _count_the_sign_up(request: Request, address: bytes | None) -> None:
    if address is not None:
        cast(Limiter, request.app.state.signups_per_address).wait_s(address)


@router.post("/auth/register/pharmacy", status_code=202)
def register_pharmacy(
    body: RegisterPharmacy, request: Request, work: DoWork, settings: TheSettings
) -> Message:
    """A pharmacy registers itself and its one account (PS-1). Like a client's sign-up
    it always answers "check your email" (R-AU7); the registration reaches DawaLink's
    team once the email is confirmed. A licence or a phone number that another pharmacy
    has is refused."""
    address = _sign_up_address(request, settings)
    _refuse_a_full_address(request, address)
    details = body.pharmacy
    with _password_slot(), work.tx() as tx:
        auth.register_pharmacy(
            tx,
            email=body.email,
            password=body.password,
            details=pharmacy_profile.checked(
                tx,
                name=details.name,
                license_number=details.license_number,
                phone=details.phone,
                address=details.address,
                district_id=details.district_id,
                lat=details.location.lat,
                lon=details.location.lon,
                pickup_days=details.pickup_days,
                hours=[(row.weekday, row.open, row.close) for row in details.hours],
            ),
            signup_address=address,
        )
    _count_the_sign_up(request, address)
    return CHECK_YOUR_EMAIL


@router.post("/auth/login")
def login(body: Login, request: Request, work: DoWork, settings: TheSettings) -> LoggedIn:
    """A wrong login is counted twice before we answer: for its account (R-AU2, five and
    it is locked), and for the network address it came from (N-52). An account's lock
    stops guessing one account; the address's limit stops one visitor from trying a few
    passwords on every account, each of which costs the server a password hash."""
    address = stated_address(request, settings)
    failures = cast(Limiter, request.app.state.failed_logins_per_address)
    if address is not None and failures.full(address):
        # Before any lookup or hash, and whatever the password: a right one too.
        raise ApiError(
            ErrorCode.RATE_LIMITED,
            "Too many failed logins from this network. Please try again in a few minutes.",
            details={"retry_after_s": failures.wait_s(address)},
        )
    try:
        with _password_slot(), work.tx() as tx:
            done = auth.login(
                tx,
                email=body.email,
                password=body.password,
                totp_code=body.totp_code,
                secret_key=secret_key(settings),
                nobody=request.app.state.failed_logins_of_nobody,
            )
            if done is not None:
                # A login that works is never counted: a whole room behind one address
                # (a pharmacy, a classroom) logs in as often as it likes.
                return LoggedIn(
                    me=present.me(tx, done.user), token=done.token, expires_at=done.expires_at
                )
    except ServiceError as refused:
        if refused.code is Code.ACCOUNT_LOCKED and address is not None:
            failures.wait_s(address)
        raise
    if address is not None:
        failures.wait_s(address)
    raise ApiError(ErrorCode.INVALID_CREDENTIALS)


@router.post("/auth/logout", status_code=204)
def logout(caller: SignedIn, work: DoWork) -> Response:
    with work.tx() as tx:
        auth.logout(tx, caller.session_id)
    return Response(status_code=204)


@router.get("/auth/me")
def read_me(caller: SignedIn, work: DoWork) -> Me:
    with work.tx() as tx:
        return present.me(tx, tx.session.get_one(User, caller.user_id))


@router.post("/auth/verify-email", status_code=204)
def verify_email(body: VerifyEmail, work: DoWork) -> Response:
    """The link of the confirmation email. It confirms the address and logs nobody in
    (R-AU4): every earlier session of the account has ended, and the person logs in with
    their password."""
    with work.tx() as tx:
        auth.verify_email(tx, body.token)
    return Response(status_code=204)


@router.post("/auth/verify-email/resend", status_code=202)
def resend_verification(caller: SignedIn, work: DoWork) -> Message:
    with work.tx() as tx:
        auth.resend_verification(tx, caller.user_id)
    return CHECK_YOUR_EMAIL


@router.post("/auth/password", status_code=204)
def change_password(body: ChangePassword, caller: SignedIn, work: DoWork) -> Response:
    # A wrong current password counts like a failed login (R-AU2), and the account's lock
    # refuses this as it refuses a login (ACCOUNT_LOCKED). A comment, not a docstring:
    # FastAPI would put a docstring in the published API description.
    with _password_slot(), work.tx() as tx:
        changed = auth.change_password(
            tx,
            caller.user_id,
            current=body.current_password,
            new=body.new_password,
            keep_session=caller.session_id,
        )
    if not changed:
        raise ApiError(ErrorCode.INVALID_CREDENTIALS, "The current password is wrong.")
    return Response(status_code=204)


@router.post("/me/delete-account", status_code=204)
def delete_account(body: DeleteAccount, caller: AsClient, work: DoWork) -> Response:
    # A client deletes their own account (R-AU10). The password is typed again: a stolen
    # session alone can't do it. A wrong one counts like a failed login (R-AU2) and logs
    # nobody out; the account's lock refuses this as it refuses a login. On success every
    # session of the client has ended, this one too. Pharmacists and admins are refused
    # by the role check: a pharmacy's account is a business record, and an admin is
    # managed by the command. A comment, not a docstring: FastAPI would publish it.
    with _password_slot(), work.tx() as tx:
        deleted = account_deletion.delete_own_account(tx, caller.user_id, password=body.password)
    if not deleted:
        raise ApiError(ErrorCode.INVALID_CREDENTIALS, "The password is wrong.")
    return Response(status_code=204)


# "Forgot my password" (R-AU9): one pair of routes, so that it can be rebuilt on Cognito's
# own flow (docs/12 §10).
LINK_IS_ON_ITS_WAY = Message(
    message="If this email has an account, a link to set a new password is on its way. "
    f"It works for {int(RESET_LINK_VALID.total_seconds() // 60)} minutes."
)
_MAKING_A_LIMITER = threading.Lock()


def _reset_asks_per_address(request: Request) -> Limiter:
    """The asks for a reset link from one network address (R-AU9), kept with the
    application like the other limits per address. Made at the first ask."""
    state = request.app.state
    with _MAKING_A_LIMITER:
        limiter = getattr(state, "reset_asks_per_address", None)
        if limiter is None:
            limiter = Limiter(RESET_ASKS_PER_ADDRESS_PER_HOUR, 3600)
            state.reset_asks_per_address = limiter
    return cast(Limiter, limiter)


@router.post("/auth/password/forgot", status_code=202)
def forgot_password(
    body: ForgotPassword, request: Request, work: DoWork, settings: TheSettings
) -> Message:
    """Always the same answer, whatever the email (R-AU9, R-AU7): nobody can find out
    here who uses DawaLink. A link goes only to an account that could log in today."""
    # Every ask counts for its network address, before anything is looked up, so the
    # limit says nothing about any email. An address that isn't known is not counted
    # (R-AU8), as for a login.
    address = stated_address(request, settings)
    if address is not None:
        wait_s = _reset_asks_per_address(request).wait_s(address)
        if wait_s:
            raise ApiError(ErrorCode.RATE_LIMITED, details={"retry_after_s": wait_s})
    with work.tx() as tx:
        auth.ask_password_reset(tx, body.email)
    return LINK_IS_ON_ITS_WAY


@router.post("/auth/password/reset", status_code=204)
def reset_password(body: ResetPassword, work: DoWork) -> Response:
    # The link's form (R-AU9): the new password, for the account the link was sent to.
    # Nobody is logged in: the person logs in with it. A link that can't be used answers
    # TOKEN_INVALID, whatever the reason. A comment, not a docstring: FastAPI would put a
    # docstring in the published API description.
    with _password_slot(), work.tx() as tx:
        auth.reset_password(tx, body.token, body.new_password)
    return Response(status_code=204)


# 6 to 15 digits, with an optional + and spaces, dots, hyphens or brackets between them.
PHONE_SHAPE = re.compile(r"\+?(?:[\s.()\-]*\d){6,15}[\s.()\-]*")


def _a_phone_or_nothing(sent: str | None) -> str | None:
    """A client's phone as typed at sign-up or in the profile, or nothing.

    A phone is digits with the marks people write around them. Anything else is refused:
    the field is shown to DawaLink's team for support.
    """
    phone = (sent or "").strip()
    if phone and not PHONE_SHAPE.fullmatch(phone):
        raise ServiceError(
            Code.VALIDATION_ERROR, "Enter a phone number, or leave it empty.", field="phone"
        )
    return phone or None


@router.get("/me/profile")
def read_profile(caller: AsClient, work: DoWork) -> Me:
    with work.tx() as tx:
        return present.me(tx, tx.session.get_one(User, caller.user_id))


def _own_details(tx: Tx, client_id: uuid.UUID) -> ClientProfile:
    """The caller's profile, locked, before anything of theirs is written.

    The first lock, as everywhere (docs/05 §6). A deletion holds it while it empties the
    rows, so a change that passed the login check a moment before the client deleted
    their account waits for it, then finds the account deleted and is answered as a
    logged-out person is: nothing is written back onto the emptied rows (R-AU10).
    """
    profile = clients.profile(tx, client_id, lock=True)
    if profile.status == ClientStatus.DELETED.value:
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    return profile


@router.patch("/me/profile")
def change_profile(body: ProfileChange, caller: AsClient, work: DoWork) -> Me:
    """Only what was sent changes (CS-13). An empty phone removes it."""
    sent = body.model_fields_set
    with work.tx() as tx:
        profile = _own_details(tx, caller.user_id)
        user = tx.session.get_one(User, caller.user_id)
        if "phone" in sent:
            user.phone = _a_phone_or_nothing(body.phone)
        if sent & {"first_name", "middle_name", "last_name"}:
            clients.set_name(
                tx,
                profile,
                first=body.first_name or "",
                middle=body.middle_name,
                last=body.last_name or "",
            )
        if "birth_date" in sent and body.birth_date is not None:
            clients.set_birth_date(tx, profile, body.birth_date)
        if "district_id" in sent and body.district_id is not None:
            # A town belongs to its district: changing the district without naming a
            # town of it leaves no town.
            clients.set_home(tx, profile, district_id=body.district_id, area_id=body.home_area_id)
        elif "home_area_id" in sent and profile.district_id is not None:
            clients.set_home(
                tx, profile, district_id=profile.district_id, area_id=body.home_area_id
            )
        if "alternatives_ok_default" in sent and body.alternatives_ok_default is not None:
            profile.alternatives_ok_default = body.alternatives_ok_default
        tx.session.flush()
        return present.me(tx, user)


@router.get("/me/home-place")
def read_home_place(caller: AsClient, work: DoWork) -> HomePlace:
    """The place the caller saved, so their own map can show it. It is sent to nobody
    else, and never in an address."""
    with work.tx() as tx:
        profile = tx.session.get_one(ClientProfile, caller.user_id)
        if profile.home_lat is None or profile.home_lon is None:
            raise ServiceError(Code.NOT_FOUND, "No place is saved.")
        return HomePlace(lat=float(profile.home_lat), lon=float(profile.home_lon))


@router.put("/me/home-place")
def save_home_place(body: PinIn, caller: AsClient, work: DoWork, request: Request) -> Me:
    """Saves or moves the caller's home place (CS-13). Rounded before it is stored; a new
    place can start a paid routing call, so it counts for the hourly limit (N-47)."""
    # A point that can't be a place is refused before it is counted: a mistake must not
    # cost one of the hour's tries.
    clients.check_place(body.lat, body.lon)
    wait_s = cast(Limiter, request.app.state.locations_per_client).wait_s(caller.user_id)
    if wait_s:
        raise ApiError(ErrorCode.RATE_LIMITED, details={"retry_after_s": wait_s})
    with work.tx() as tx:
        profile = _own_details(tx, caller.user_id)
        clients.set_home_place(tx, profile, body.lat, body.lon)
        tx.session.flush()
        return present.me(tx, tx.session.get_one(User, caller.user_id))


@router.delete("/me/home-place")
def forget_home_place(caller: AsClient, work: DoWork) -> Me:
    with work.tx() as tx:
        profile = _own_details(tx, caller.user_id)
        clients.clear_home_place(profile)
        tx.session.flush()
        return present.me(tx, tx.session.get_one(User, caller.user_id))
