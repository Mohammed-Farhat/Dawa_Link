"""Road travel times from OpenRouteService (docs/04 R-RT1; docs/06 §8 "Routing").

OpenRouteService computes road times on OpenStreetMap data, by car and on foot. One call
to its matrix endpoint gives the times for every (origin, pharmacy) pair at once.

**What leaves the system** (docs/10 §4.3): points only. A client's location is already
rounded to about 100 m, and nothing says whose it is: no account, no conversation, no
request ID. Pharmacies' pins are public places.

A failure is not this module's problem to solve: it raises, and the caller falls back to
the straight-line estimate (FX-18).
"""

import uuid
from collections.abc import Mapping
from typing import Any

import httpx2

from dawalink.domain.geo import Point
from dawalink.domain.numbers import ROUTING_TIMEOUT_S
from dawalink.services.travel import Mode

# OpenRouteService's names for our two ways of travelling.
PROFILES: dict[Mode, str] = {"car": "driving-car", "walk": "foot-walking"}


class RoutingError(Exception):
    """The routing service didn't give usable times. Its message never holds a location."""


class OpenRouteService:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_s: float = ROUTING_TIMEOUT_S,
        client: httpx2.Client | None = None,
    ) -> None:
        self._key = api_key
        self._timeout_s = timeout_s
        self._client = client or httpx2.Client(base_url=base_url)

    @staticmethod
    def request(
        origins: Mapping[str, Point], destinations: Mapping[uuid.UUID, Point]
    ) -> dict[str, Any]:
        """The matrix request: origins first, then pharmacies. Longitude comes first."""
        places = [*origins.values(), *destinations.values()]
        return {
            "locations": [[float(place.lon), float(place.lat)] for place in places],
            "sources": list(range(len(origins))),
            "destinations": list(range(len(origins), len(places))),
            "metrics": ["duration", "distance"],
            "units": "km",
        }

    def road_times(
        self, origins: Mapping[str, Point], destinations: Mapping[uuid.UUID, Point], mode: Mode
    ) -> Mapping[tuple[str, uuid.UUID], tuple[int, float]]:
        """`{(origin, pharmacy): (minutes, km)}`. A pair with no road between is left out."""
        if not origins or not destinations:
            return {}
        try:
            response = self._client.post(
                f"/v2/matrix/{PROFILES[mode]}",
                json=self.request(origins, destinations),
                headers={"Authorization": self._key},
                timeout=self._timeout_s,
            )
        except httpx2.TransportError as error:
            raise RoutingError(type(error).__name__) from None
        if response.status_code != 200:
            # 429 and 403 are the free plan's limits; either way the estimate is used.
            raise RoutingError(f"status {response.status_code}")
        try:
            body = response.json()
            durations, distances = body["durations"], body["distances"]
        except (ValueError, KeyError, TypeError):
            raise RoutingError("an answer that can't be read") from None
        times: dict[tuple[str, uuid.UUID], tuple[int, float]] = {}
        for row, origin in enumerate(origins):
            for column, pharmacy_id in enumerate(destinations):
                seconds, km = durations[row][column], distances[row][column]
                if seconds is None or km is None:
                    continue
                # A minute at least: "0 min" reads as a mistake.
                times[(origin, pharmacy_id)] = (max(1, round(seconds / 60)), round(float(km), 2))
        return times
