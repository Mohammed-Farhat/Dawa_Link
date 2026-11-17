"""Public configuration, registration and logins (docs/06 §6.1)."""

import re
from typing import Annotated

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
)
from dawalink.api.errors import ApiError, ErrorCode
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
    with work.tx() as tx:
        auth.register_client(
            tx,
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            phone=body.phone,
            district_id=body.district_id,
            signup_address=address,
        )
    return CHECK_YOUR_EMAIL


@router.post("/auth/register/pharmacy", status_code=202)
def register_pharmacy(
    body: RegisterPharmacy, request: Request, work: DoWork, settings: TheSettings
) -> Message:
    """A pharmacy registers itself and its one account (PS-1). Like a client's sign-up
    it always answers "check your email" (R-AU7); the registration reaches DawaLink's
    team once the email is confirmed. A licence or a phone number that another pharmacy
    has is refused."""
    address = auth.address_hash(secret_key(settings), caller_address(request, settings))
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
    return CHECK_YOUR_EMAIL


@router.post("/auth/login")
def login(body: Login, work: DoWork, settings: TheSettings) -> LoggedIn:
    with work.tx() as tx:
        # A wrong login is counted, and the count is committed, before we answer.
        done = auth.login(
            tx,
            email=body.email,
            password=body.password,
            totp_code=body.totp_code,
            secret_key=secret_key(settings),
        )
        if done is not None:
            return LoggedIn(
                me=present.me(tx, done.user), token=done.token, expires_at=done.expires_at
            )
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
            phone = (body.phone or "").strip()
            # A phone is digits with the marks people write around them. Anything else
            # is refused: the field is shown to DawaLink's team for support.
            if phone and not PHONE_SHAPE.fullmatch(phone):
                raise ServiceError(
                    Code.VALIDATION_ERROR, "Enter a phone number, or leave it empty.", field="phone"
                )
            user.phone = phone or None
        if "district_id" in sent and body.district_id is not None:
            if tx.session.get(District, body.district_id) is None:
                raise ServiceError(Code.VALIDATION_ERROR, "Unknown district.", field="district_id")
            profile.district_id = body.district_id
        if "alternatives_ok_default" in sent and body.alternatives_ok_default is not None:
            profile.alternatives_ok_default = body.alternatives_ok_default
        tx.session.flush()
        return present.me(tx, user)
