"""Accounts and logins (docs/06 §5.2, §6.1)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from dawalink.api.schemas.common import District, In, Out


class ClientState(Out):
    status: Literal["UNVERIFIED", "ACTIVE", "PAUSED", "SUSPENDED"]
    paused_until: datetime | None
    district: District | None
    alternatives_ok_default: bool
    # "Missed pickups: 0 of 2" (R-N1).
    missed_pickups_30d: int
    missed_pickups_before_pause: int


class PharmacyState(Out):
    id: uuid.UUID
    name: str
    status: Literal["PENDING", "APPROVED", "REJECTED", "SUSPENDED"]
    status_reason: str | None
    info_requested: bool


class Me(Out):
    id: uuid.UUID
    role: Literal["client", "pharmacist", "admin"]
    email: str
    full_name: str
    email_verified: bool
    client: ClientState | None
    pharmacy: PharmacyState | None


class LoggedIn(Out):
    """Who logged in, and the token the website sends from now on (docs/06 §2.1)."""

    me: Me
    token: str
    expires_at: datetime


# Only the shape is checked here: the confirmation link is what proves an address.
EMAIL_SHAPE = "^[^@ ]+@[^@ ]+[.][^@ ]+$"


class RegisterClient(In):
    email: str = Field(max_length=320, pattern=EMAIL_SHAPE)
    password: str = Field(min_length=1, max_length=200)
    full_name: str = Field(min_length=2, max_length=80)
    phone: str | None = Field(default=None, max_length=30)
    district_id: int
    accept_terms: Literal[True]


class Login(In):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=200)
    # Admins only: the 6 digits of their authenticator app (R-AU6).
    totp_code: str | None = Field(default=None, max_length=10)


class VerifyEmail(In):
    token: str = Field(min_length=10, max_length=200)


class ChangePassword(In):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class ProfileChange(In):
    phone: str | None = Field(default=None, max_length=30)
    district_id: int | None = None
    alternatives_ok_default: bool | None = None


class PublicConfig(Out):
    """What the website needs before anyone logs in. No secret, no stock."""

    request_hours_start: str
    request_hours_end: str
    search_window_hours: int
    offer_hours: int
    lbp_per_usd: int | None
    rate_date: str | None
    poll_every_s: int
    max_message_chars: int
    server_now: datetime
    demo_mode: bool
    assistant_available: bool
