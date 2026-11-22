"""What a client may do in their current status (docs/04 SM-2)."""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import select

from dawalink.db.models import Area, ClientProfile, District, User
from dawalink.domain import client_details
from dawalink.domain.accounts import ClientStatus, client_can_reserve, client_can_search
from dawalink.domain.geo import Point, rounded
from dawalink.domain.pharmacy_details import check_pin
from dawalink.services import travel
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.travel import Location


def profile(tx: Tx, client_id: uuid.UUID, *, lock: bool = False) -> ClientProfile:
    """The client's profile. With `lock`, the row is locked until the transaction ends.

    The lock is what serializes one client's reservations, so two taps at once can't both
    pass a limit (docs/05 §6). It is always the first lock a transaction takes.
    """
    statement = select(ClientProfile).where(ClientProfile.user_id == client_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    found = tx.session.execute(statement).scalar()
    if found is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown client.")
    return found


def require_search(client: ClientProfile) -> None:
    # A deleted account has no session left, so only a suspended one is ever refused here.
    if not client_can_search(ClientStatus(client.status)):
        raise ServiceError(Code.ACCOUNT_SUSPENDED, "This account is suspended.")


def require_reserve(tx: Tx, client: ClientProfile) -> None:
    """Reserving, accepting an offer, starting a request or a watch need an ACTIVE client."""
    status = ClientStatus(client.status)
    if client_can_reserve(status):
        return
    if status is ClientStatus.UNVERIFIED:
        raise ServiceError(Code.EMAIL_NOT_VERIFIED, "Please confirm your email first.")
    if status is ClientStatus.PAUSED:
        raise ServiceError(
            Code.CLIENT_PAUSED,
            "Reservations are paused after missed pickups.",
            paused_until=client.paused_until,
        )
    raise ServiceError(Code.ACCOUNT_SUSPENDED, "This account is suspended.")


# --- What a client says about themselves (CS-13, decision log BLD-D40) -------------------


def _refuse(field: str, problem: ValueError | str) -> ServiceError:
    return ServiceError(Code.VALIDATION_ERROR, str(problem), field=field)


def _put_name(client: ClientProfile, first: str, middle: str | None, last: str) -> str:
    """Checks the parts, puts them on the profile and returns the name in one line."""
    cleaned: dict[str, str | None] = {}
    for field, value, required in (
        ("first_name", first, True),
        ("middle_name", middle, False),
        ("last_name", last, True),
    ):
        try:
            cleaned[field] = client_details.clean_name_part(value, required=required)
        except ValueError as problem:
            raise _refuse(field, problem) from None
    client.first_name = cleaned["first_name"]
    client.middle_name = cleaned["middle_name"]
    client.last_name = cleaned["last_name"]
    return client_details.whole_name(
        cleaned["first_name"] or "", cleaned["middle_name"], cleaned["last_name"] or ""
    )


def set_name(tx: Tx, client: ClientProfile, *, first: str, middle: str | None, last: str) -> None:
    """The one place a client's name is changed: its parts on the profile, and the same
    name in one line on the user, which is what emails and the redaction of the client's
    own name read (INV-10)."""
    tx.session.get_one(User, client.user_id).full_name = _put_name(client, first, middle, last)


def check_details(
    tx: Tx,
    client: ClientProfile,
    *,
    first: str,
    middle: str | None,
    last: str,
    born: date,
    district_id: int | None,
    area_id: int | None,
    place: tuple[float, float] | None = None,
) -> None:
    """What a sign-up form says about a new client, checked and put on a profile that
    isn't stored yet (the account is made after it).

    Where they live is a place on the map, or a district (with a town of it), or both;
    one of the two is needed, or no search would know where to start.
    """
    _put_name(client, first, middle, last)
    set_birth_date(tx, client, born)
    if place is None and district_id is None:
        raise _refuse("district_id", "Put your place on the map, or choose your district.")
    if place is not None:
        set_home_place(tx, client, place[0], place[1])
    if district_id is not None:
        set_home(tx, client, district_id=district_id, area_id=area_id)
    elif area_id is not None:
        raise _refuse("home_area_id", "A town needs its district.")


def set_birth_date(tx: Tx, client: ClientProfile, born: date) -> None:
    """Checked against the real day: the demo clock doesn't make anyone older."""
    try:
        client_details.check_birth_date(born, tx.real_now.date())
    except ValueError as problem:
        raise _refuse("birth_date", problem) from None
    client.birth_date = born


def set_home(tx: Tx, client: ClientProfile, *, district_id: int, area_id: int | None) -> None:
    """The home district, and with it the home town or none. A town belongs to its
    district: one from another district is refused, never moved."""
    if tx.session.get(District, district_id) is None:
        raise _refuse("district_id", "Unknown district.")
    if area_id is not None:
        town = tx.session.get(Area, area_id)
        if town is None or town.district_id != district_id:
            raise _refuse("home_area_id", "This town isn't in the district you chose.")
    client.district_id = district_id
    client.home_area_id = area_id


def check_place(lat: float, lon: float) -> None:
    """A home place is a point in Lebanon."""
    try:
        check_pin(lat, lon)
    except ValueError as problem:
        raise _refuse("location", problem) from None


def set_home_place(tx: Tx, client: ClientProfile, lat: float, lon: float) -> None:
    """The place the client put on the map, kept rounded to about 100 m (N-43)."""
    check_place(lat, lon)
    point = rounded(lat, lon)
    client.home_lat, client.home_lon = point.lat, point.lon


def clear_home_place(client: ClientProfile) -> None:
    client.home_lat = client.home_lon = None


# The name a deleted account keeps (R-AU10): the same for everyone, so it names nobody.
DELETED_NAME = "Deleted account"


def erase(tx: Tx, client: ClientProfile) -> None:
    """The client deleted their account (R-AU10): everything they told DawaLink about
    themselves goes now, on the profile and on the user. With `set_name`, the only other
    place a client's name is written."""
    user = tx.session.get_one(User, client.user_id)
    user.full_name = DELETED_NAME
    user.phone = None
    client.first_name = client.middle_name = client.last_name = None
    client.birth_date = None
    client.district_id = client.home_area_id = None
    clear_home_place(client)
    client.alternatives_ok_default = False
    client.paused_until = None
    client.status_reason = None


@dataclass(frozen=True)
class Home:
    """Where a client's searches start when nothing is shared: the place they saved, else
    their home town, else their home district (R-S2)."""

    location: Location
    kind: Literal["place", "town", "district"]
    # The name a person or the model may be told: a town or a district, never a point.
    name: str | None


def home(tx: Tx, client_id: uuid.UUID) -> Home | None:
    client = tx.session.get(ClientProfile, client_id)
    if client is None:
        return None
    district = tx.session.get(District, client.district_id) if client.district_id else None
    town = tx.session.get(Area, client.home_area_id) if client.home_area_id else None
    name = (
        f"{town.name} ({district.name})"
        if town and district and town.name != district.name
        else (district.name if district else None)
    )
    if client.home_lat is not None and client.home_lon is not None:
        place = Location(Point(client.home_lat, client.home_lon), "shared", client.district_id)
        return Home(place, "place", name)
    if town is not None:
        return Home(travel.area_location(tx, town.id), "town", name)
    if district is not None:
        return Home(travel.district_location(tx, district.id), "district", name)
    return None
