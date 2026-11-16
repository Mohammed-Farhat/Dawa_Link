"""The legs of a route with several pharmacies (docs/04 R-RT2)."""

from dawalink.domain.planning import CLIENT
from dawalink.services import travel
from dawalink.services.travel import shared_location
from tests.services.conftest import World


class TestLegs:
    def test_every_start_has_a_leg_to_every_other_pharmacy(self, world: World) -> None:
        near = world.make.pharmacy(lat=33.896, lon=35.483)
        north = world.make.pharmacy(lat=33.905, lon=35.483)

        legs = travel.legs(world.tx(), shared_location(33.890, 35.480), [near, north])

        assert set(legs) == {
            (CLIENT, str(near)),
            (CLIENT, str(north)),
            (str(near), str(north)),
            (str(north), str(near)),
        }

    def test_a_client_next_to_a_pharmacy_still_has_their_own_legs(self, world: World) -> None:
        """Found by the simulation: the client and a pharmacy in the same 100 m square, and
        the planner crashed because the client's legs were the pharmacy's."""
        here = world.make.pharmacy(lat=33.896, lon=35.483)
        north = world.make.pharmacy(lat=33.905, lon=35.483)

        legs = travel.legs(world.tx(), shared_location(33.896, 35.483), [here, north])

        assert (CLIENT, str(here)) in legs
        assert legs[(CLIENT, str(north))] == legs[(str(here), str(north))]
        assert legs[(CLIENT, str(here))].car_min <= 1

    def test_two_pharmacies_side_by_side_both_keep_their_legs(self, world: World) -> None:
        one = world.make.pharmacy(lat=33.896, lon=35.483)
        next_door = world.make.pharmacy(lat=33.8961, lon=35.4831)
        north = world.make.pharmacy(lat=33.905, lon=35.483)

        legs = travel.legs(world.tx(), shared_location(33.890, 35.480), [one, next_door, north])

        assert len(legs) == 3 + 3 * 2  # from the client, and between each pair, both ways
        assert (str(one), str(next_door)) in legs
        assert (str(next_door), str(north)) in legs
