"""The areas a client can name in chat instead of sharing a location (docs/04 R-S2).

"I'm in Hamra": the agent passes the name, this module finds it in our own list and puts
that area's centre on the conversation. Nothing the client typed leaves the system, and
the model only ever gets names back, never a coordinate (INV-24).
"""

from dataclasses import dataclass

from sqlalchemy import select

from dawalink.db.models import Area, Conversation, District
from dawalink.domain import places
from dawalink.domain.places import Place
from dawalink.domain.vocabulary import LocationSource
from dawalink.services import travel
from dawalink.services.context import Tx
from dawalink.services.travel import Location


@dataclass(frozen=True)
class Lookup:
    """What a name gave: the places written exactly so, or else the ones that look like it."""

    named: list[Place]
    close: list[Place]


def listed(tx: Tx) -> list[Place]:
    rows = tx.session.execute(
        select(Area.id, Area.name, District.name, Area.other_names, Area.whole_district)
        .join(District, District.id == Area.district_id)
        .order_by(Area.id)
    )
    return [
        Place(area_id, name, district, tuple(other_names), whole)
        for area_id, name, district, other_names, whole in rows
    ]


def look_up(tx: Tx, text: str, district: str | None = None) -> Lookup:
    everything = listed(tx)
    named = places.named(everything, text, district)
    return Lookup(named, [] if named else places.close(everything, text))


def use(tx: Tx, conversation: Conversation, area_id: int) -> Location:
    """Makes the area's centre this conversation's location. It replaces any earlier one."""
    location = travel.area_location(tx, area_id)
    conversation.loc_lat, conversation.loc_lon = location.point.lat, location.point.lon
    conversation.loc_source = LocationSource.AREA
    conversation.loc_area_id = area_id
    conversation.loc_set_at = tx.now
    tx.session.flush()
    return location
