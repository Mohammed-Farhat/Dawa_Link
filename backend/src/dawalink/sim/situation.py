"""A simulated client's real situation, and what it makes of a pharmacy (docs/08 §2.3, E2).

Each client has a hidden situation: a car or not, and the hours they are free. A contender
only knows what the client told it. The evaluation knows everything, and uses this module
to say how good a choice of pharmacy really was for that client:
- **can it work at all?** The pharmacy must be open while the client is free on the pickup
  day, and reachable: a client without a car walks, and not for more than 45 minutes;
- **how long is the trip** by the client's own means.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from dawalink.domain.clock import at_beirut, beirut
from dawalink.sim.world import SCHEDULES, SimClient, SimPharmacy

WALK_LIMIT_MIN = 45  # farther than this on foot is "can't get there"
# The hours a client is free, in minutes after midnight.
FREE_HOURS = {"any": (0, 24 * 60), "after_18": (18 * 60, 24 * 60), "before_14": (0, 14 * 60)}
# A pharmacy must stay open at least this long after "now" for a pickup today (N-42).
MIN_OPEN_LEFT_MIN = 60


@dataclass(frozen=True)
class Trip:
    car_min: int
    walk_min: int

    def minutes_for(self, client: SimClient) -> int:
        """The trip by the client's own means."""
        return self.car_min if client.has_car else self.walk_min


def open_ranges(pharmacy: SimPharmacy, day: date) -> tuple[tuple[int, int], ...]:
    days, ranges = SCHEDULES[pharmacy.schedule]
    return ranges if day.weekday() in days else ()


AT_THE_COUNTER_MIN = 1  # from the door to being served


def pickup_moment(
    client: SimClient, pharmacy: SimPharmacy, trip: Trip, day: date, now: datetime
) -> datetime | None:
    """When this client is served at the counter on that day: a minute after the first
    moment they are free, have had time to travel, and the pharmacy is open. None when
    there is no such moment.

    The pharmacy must still be open at that minute: a reservation ends at closing time
    (R-T4), so arriving on the stroke of it is arriving too late.
    """
    free_from, free_until = FREE_HOURS[client.free]
    local = beirut(now)
    if day == local.date():
        free_from = max(free_from, local.hour * 60 + local.minute + trip.minutes_for(client))
    for opens, closes in open_ranges(pharmacy, day):
        served = max(opens, free_from) + AT_THE_COUNTER_MIN
        if served < min(closes, free_until):
            return at_beirut(day, time(0)) + timedelta(minutes=served)
    return None


def can_reach(client: SimClient, trip: Trip) -> bool:
    return client.has_car or trip.walk_min <= WALK_LIMIT_MIN


def can_go(client: SimClient, pharmacy: SimPharmacy, trip: Trip, day: date, now: datetime) -> bool:
    """Is the pharmacy open at some moment the client is free and can have arrived?"""
    return pickup_moment(client, pharmacy, trip, day, now) is not None


def works(client: SimClient, pharmacy: SimPharmacy, trip: Trip, day: date, now: datetime) -> bool:
    """Can this client really pick up there on that day?"""
    return can_reach(client, trip) and can_go(client, pharmacy, trip, day, now)
