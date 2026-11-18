"""Public configuration, registration and logins (docs/06 §6.1)."""

import re
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select

from dawalink.agent.turn import Agent
from dawalink.api import present
from dawalink.api.deps import (
    AsClient,
    DoWork,
    SignedIn,
    TheSettings,
    caller_address,
    get_agent,
    secret_key,
    stated_address,
)
from dawalink.api.errors import ApiError, ErrorCode
from dawalink.api.limits import Limiter
from dawalink.api.schemas.accounts import (
    ChangePassword,
    DiscountTier,
    LoggedIn,
    Login,
    Me,
    ProfileChange,
    PublicConfig,
    RegisterClient,
    RegisterPharmacy,
    VerifyEmail,
)
from dawalink.api.schemas.common import District as DistrictOut
from dawalink.api.schemas.common import Message
from dawalink.db.models import CatalogImport, ClientProfile, District, PricingTier, User
from dawalink.domain.numbers import (
    MAX_MESSAGE_CHARS,
    OFFER_VALIDITY,
    POLL_EVERY_S,
    REQUEST_HOURS_END,
    REQUEST_HOURS_START,
    SEARCH_WINDOW,
)
from dawalink.services import auth, pharmacy_profile
from dawalink.services.errors import Code, ServiceError

router = APIRouter(tags=["accounts"])

CHECK_YOUR_EMAIL = Message(message="Check your email to continue.")


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


@router.post("/auth/register/client", status_code=202)
def register_client(
    body: RegisterClient, request: Request, work: DoWork, settings: TheSettings
) -> Message:
    """Always "check your email", whether or not the address already has an account
    (R-AU7): nobody can find out here who uses DawaLink."""
    address = auth.address_hash(secret_key(settings), caller_address(request, settings))
    phone = _a_phone_or_nothing(body.phone)
    _refuse_a_full_address(request, address)
    with work.tx() as tx:
        auth.register_client(
            tx,
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            phone=phone,
            district_id=body.district_id,
            signup_address=address,
        )
    _count_the_sign_up(request, address)
    return CHECK_YOUR_EMAIL


def _refuse_a_full_address(request: Request, address: bytes) -> None:
    """R-AU5, for every sign-up that got as far as an account or an "already registered"
    email, whichever it was.

    The service counts the accounts made, and that count survives a restart. Counting
    only those would tell who already has an account: after four new sign-ups, one more
    with someone's email and one more again, the limit would come one sign-up later if
    that email was known (docs/10 TH-3).
    """
    limiter = cast(Limiter, request.app.state.signups_per_address)
    if limiter.full(address):
        raise ServiceError(Code.SIGNUP_LIMIT, "Too many sign-ups. Please try again later.")


def _count_the_sign_up(request: Request, address: bytes) -> None:
    cast(Limiter, request.app.state.signups_per_address).wait_s(address)


@router.post("/auth/register/pharmacy", status_code=202)
def register_pharmacy(
    body: RegisterPharmacy, request: Request, work: DoWork, settings: TheSettings
) -> Message:
    """A pharmacy registers itself and its one account (PS-1). Like a client's sign-up
    it always answers "check your email" (R-AU7); the registration reaches DawaLink's
    team once the email is confirmed. A licence or a phone number that another pharmacy
    has is refused."""
    address = auth.address_hash(secret_key(settings), caller_address(request, settings))
    _refuse_a_full_address(request, address)
    details = body.pharmacy
    with work.tx() as tx:
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
        with work.tx() as tx:
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


@router.post("/auth/verify-email")
def verify_email(body: VerifyEmail, work: DoWork) -> LoggedIn:
    """The link of the confirmation email. It also logs the user in (R-AU4)."""
    with work.tx() as tx:
        done = auth.verify_email(tx, body.token)
        return LoggedIn(me=present.me(tx, done.user), token=done.token, expires_at=done.expires_at)


@router.post("/auth/verify-email/resend", status_code=202)
def resend_verification(caller: SignedIn, work: DoWork) -> Message:
    with work.tx() as tx:
        auth.resend_verification(tx, caller.user_id)
    return CHECK_YOUR_EMAIL


@router.post("/auth/password", status_code=204)
def change_password(body: ChangePassword, caller: SignedIn, work: DoWork) -> Response:
    with work.tx() as tx:
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


@router.patch("/me/profile")
def change_profile(body: ProfileChange, caller: AsClient, work: DoWork) -> Me:
    """Only what was sent changes (CS-13). An empty phone removes it."""
    sent = body.model_fields_set
    with work.tx() as tx:
        user = tx.session.get_one(User, caller.user_id)
        profile = tx.session.get_one(ClientProfile, caller.user_id)
        if "phone" in sent:
            user.phone = _a_phone_or_nothing(body.phone)
        if "district_id" in sent and body.district_id is not None:
            if tx.session.get(District, body.district_id) is None:
                raise ServiceError(Code.VALIDATION_ERROR, "Unknown district.", field="district_id")
            profile.district_id = body.district_id
        if "alternatives_ok_default" in sent and body.alternatives_ok_default is not None:
            profile.alternatives_ok_default = body.alternatives_ok_default
        tx.session.flush()
        return present.me(tx, user)
