"""Accounts and logins (docs/06 §5.2, §6.1)."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from dawalink.api.schemas.common import AreaId, District, DistrictId, In, Out


class Place(Out):
    """A town or a neighbourhood of our own list of places (docs/04 R-S2)."""

    id: int
    name: str


class ClientState(Out):
    status: Literal["UNVERIFIED", "ACTIVE", "PAUSED", "SUSPENDED"]
    paused_until: datetime | None
    district: District | None
    # The home town, when the client chose one inside their district.
    home_area: Place | None
    # A place is saved on the map. The point itself is only ever sent by its own
    # endpoint, to the client who saved it.
    home_place_saved: bool
    first_name: str | None
    middle_name: str | None
    last_name: str | None
    birth_date: date | None
    alternatives_ok_default: bool
    # "Missed pickups: 0 of 2" (R-N1).
    missed_pickups_30d: int
    missed_pickups_before_pause: int
    # The rule's own numbers, so the page can say it in a sentence (R-N1).
    missed_pickups_window_days: int
    missed_pickups_pause_days: int


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
    # The caller's own phone, for their profile's form. Nobody else's is ever in an answer.
    phone: str | None
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


class PinIn(In):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RegisterClient(In):
    email: str = Field(max_length=320, pattern=EMAIL_SHAPE)
    password: str = Field(min_length=1, max_length=200)
    first_name: str = Field(min_length=1, max_length=40)
    middle_name: str | None = Field(default=None, max_length=40)
    last_name: str = Field(min_length=1, max_length=40)
    birth_date: date
    phone: str | None = Field(default=None, max_length=30)
    # Where the client lives, one way or the other (the owner, 2026-11-18): a place they
    # put on a map (or their device's location), **or** their district, with a town of it
    # if they want. At least one of the two.
    home_place: PinIn | None = None
    district_id: DistrictId | None = None
    home_area_id: AreaId | None = None
    accept_terms: Literal[True]


class OpeningRange(In):
    """One opening range of a weekday, Monday = 0: `{weekday: 0, open: "08:00",
    close: "13:00"}`. A day has up to two; a day with none is closed. `close` may be
    "24:00"."""

    weekday: int = Field(ge=0, le=6)
    open: str = Field(pattern="^[0-2][0-9]:[0-5][0-9]$")
    close: str = Field(pattern="^[0-2][0-9]:[0-5][0-9]$")


class PharmacyDetails(In):
    """What a pharmacy says about itself (PS-1). The exact shape of each field is checked
    by the rules, which answer with the field's name and a sentence."""

    name: str = Field(min_length=1, max_length=120)
    license_number: str = Field(min_length=1, max_length=40)
    phone: str = Field(min_length=1, max_length=30)
    address: str = Field(min_length=1, max_length=300)
    district_id: DistrictId
    # The pin the pharmacy put on the map. An admin checks it against the address.
    location: PinIn
    pickup_days: int = Field(default=1, ge=1, le=3)
    hours: list[OpeningRange] = Field(max_length=14)


class RegisterPharmacy(In):
    email: str = Field(max_length=320, pattern=EMAIL_SHAPE)
    password: str = Field(min_length=1, max_length=200)
    pharmacy: PharmacyDetails
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
    """Only what is sent changes. The three name parts are sent together; so are the
    district and the town, because a town belongs to its district."""

    phone: str | None = Field(default=None, max_length=30)
    first_name: str | None = Field(default=None, max_length=40)
    middle_name: str | None = Field(default=None, max_length=40)
    last_name: str | None = Field(default=None, max_length=40)
    birth_date: date | None = None
    district_id: DistrictId | None = None
    home_area_id: AreaId | None = None
    alternatives_ok_default: bool | None = None


class HomePlace(Out):
    """The client's own saved place, as they put it (rounded to about 100 m)."""

    lat: float
    lon: float


class DiscountTier(Out):
    min_days: int
    max_days: int
    discount_pct: int


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
    # The system's discounts by days left before expiry (docs/04 N-4), read-only.
    discount_tiers: list[DiscountTier]
    server_now: datetime
    demo_mode: bool
    assistant_available: bool
