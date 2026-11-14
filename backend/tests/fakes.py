"""Stand-ins for the outside services, shared by the tests (docs/09 FM-D4)."""

import uuid
from collections.abc import Mapping

from dawalink.domain.geo import Point


class FakeRouting:
    """Stands in for the routing service: every pair takes `minutes` by car, 5 times on foot."""

    def __init__(self, minutes: int = 12, *, fail: bool = False) -> None:
        self.minutes, self.fail, self.calls = minutes, fail, 0
        # Everything it was asked for, so a test can check what would leave the system.
        self.asked: list[tuple[Mapping[str, Point], Mapping[uuid.UUID, Point], str]] = []

    def road_times(
        self, origins: Mapping[str, Point], destinations: Mapping[uuid.UUID, Point], mode: str
    ) -> Mapping[tuple[str, uuid.UUID], tuple[int, float]]:
        self.calls += 1
        self.asked.append((dict(origins), dict(destinations), mode))
        if self.fail:
            raise TimeoutError("the routing service did not answer")
        factor = 1 if mode == "car" else 5
        return {
            (origin, pharmacy): (self.minutes * factor, 4.2)
            for origin in origins
            for pharmacy in destinations
        }
