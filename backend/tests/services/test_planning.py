"""Plans for several medicines, on the database side (docs/04 R-RQ5, N-48).

The planner's own rules are tested in `tests/unit/domain/test_planning.py`. Here: which
pharmacies it is given when a basket has more of them than it can weigh.
"""

import uuid

from dawalink.domain.geo import cell
from dawalink.domain.numbers import PLAN_MAX_CANDIDATE_PHARMACIES
from dawalink.domain.planning import Preference
from dawalink.services import planning, travel
from dawalink.services.planning import BasketLine
from dawalink.services.travel import shared_location
from tests.services.conftest import World

HAMRA = shared_location(33.8961, 35.4832)
MANY = PLAN_MAX_CANDIDATE_PHARMACIES + 2


def street(world: World, count: int = MANY) -> list[uuid.UUID]:
    """Pharmacies in a row going north, about 300 m apart: the first is the nearest."""
    return [world.make.pharmacy(lat=33.897 + 0.003 * n, lon=35.4832) for n in range(count)]


class TestMorePharmaciesThanThePlannerWeighs:
    def test_a_far_pharmacy_with_the_cheapest_box_is_still_weighed(self, world: World) -> None:
        """N-48: the nearest ones, plus the cheapest one for each medicine."""
        client, concor = world.make.client(), world.make.product()
        row = street(world)
        for pharmacy in row[:-1]:
            world.make.item(pharmacy_id=pharmacy, product_id=concor, days_left=60)
        world.make.item(pharmacy_id=row[-1], product_id=concor, days_left=20)  # 60% off

        def first_stop(preference: Preference | None) -> uuid.UUID:
            found = planning.plan(
                world.tx(),
                client_id=client,
                lines=[BasketLine(concor)],
                location=HAMRA,
                preference=preference,
            )
            return found.trips[0].stops[0].pharmacy.id

        assert first_stop(None) == row[0]
        assert first_stop("cheapest") == row[-1]

    def test_a_medicine_that_only_a_far_pharmacy_has_is_planned(self, world: World) -> None:
        """It used to come back as "none listed", and the agent waited for stock instead."""
        client = world.make.client()
        concor, aspirin = world.make.product(), world.make.product()
        row = street(world)
        for pharmacy in row[:-1]:
            world.make.item(pharmacy_id=pharmacy, product_id=concor)
        world.make.item(pharmacy_id=row[-1], product_id=aspirin)

        found = planning.plan(
            world.tx(),
            client_id=client,
            lines=[BasketLine(concor), BasketLine(aspirin)],
            location=HAMRA,
        )

        best = found.trips[0]
        assert best.missing == ()
        # The concor comes from a pharmacy on the way to the one that has the aspirin.
        assert len(best.stops) == 2
        assert row[-1] in [stop.pharmacy.id for stop in best.stops]
        assert found.unplannable == []

    def test_the_nearest_are_the_nearest_by_road(self, world: World) -> None:
        """The owner, 2026-11-15: a pharmacy far in a straight line and a minute away by road
        is among the nearest; the one it replaces is the last of the others."""
        concor = world.make.product()
        row = street(world)
        world.make.item(pharmacy_id=row[0], product_id=concor, days_left=20)  # the cheapest
        for pharmacy in row[1:]:
            world.make.item(pharmacy_id=pharmacy, product_id=concor)
        lines = [BasketLine(concor)]

        by_estimate = planning.pharmacies_to_weigh(world.tx(), lines=lines, location=HAMRA)
        travel.store(
            world.tx(),
            [
                {
                    "pharmacy_id": row[-1],
                    "origin_cell": cell(HAMRA.point),
                    "mode": mode,
                    "minutes": 1,
                    "km": 0.2,
                    "source": "road",
                }
                for mode in travel.MODES
            ],
        )
        by_road = planning.pharmacies_to_weigh(world.tx(), lines=lines, location=HAMRA)

        assert set(by_estimate) == set(row[:PLAN_MAX_CANDIDATE_PHARMACIES])
        assert set(by_road) == {*row[: PLAN_MAX_CANDIDATE_PHARMACIES - 1], row[-1]}

    def test_every_pharmacy_is_asked_about_only_when_a_choice_must_be_made(
        self, world: World
    ) -> None:
        concor = world.make.product()
        row = street(world)
        for pharmacy in row[:PLAN_MAX_CANDIDATE_PHARMACIES]:
            world.make.item(pharmacy_id=pharmacy, product_id=concor)
        lines = [BasketLine(concor)]

        few = planning.pharmacies_stocking(world.tx(), lines=lines)
        world.make.item(pharmacy_id=row[-1], product_id=concor)
        many = planning.pharmacies_stocking(world.tx(), lines=lines)

        assert few == []
        assert set(many) == {*row[:PLAN_MAX_CANDIDATE_PHARMACIES], row[-1]}

    def test_a_small_basket_weighs_every_pharmacy_that_has_a_box(self, world: World) -> None:
        concor = world.make.product()
        row = street(world, 3)
        for pharmacy in row[:2]:
            world.make.item(pharmacy_id=pharmacy, product_id=concor)

        asked = planning.pharmacies_to_weigh(world.tx(), lines=[BasketLine(concor)], location=HAMRA)

        assert set(asked) == set(row[:2])


class TestTheSameNameInAnotherBoxSize:
    def test_the_other_box_size_is_planned_and_another_brand_is_not(self, world: World) -> None:
        """R-C10, the owner's Q38: a plan for the box of 100 takes the box of 30 that a
        pharmacy has. It came back as "none listed"."""
        key = "aspirin=100mg | tablet | B01AC06"
        same = {"equivalence_key": key, "moph_name": "ZASPICOT", "search_name": "zaspicot"}
        box_of_100, box_of_30 = world.make.product(**same), world.make.product(**same)
        other_brand = world.make.product(equivalence_key=key)
        client, pharmacy = world.make.client(), street(world, 1)[0]
        on_the_shelf = world.make.item(pharmacy_id=pharmacy, product_id=box_of_30)

        found = planning.plan(
            world.tx(), client_id=client, lines=[BasketLine(box_of_100)], location=HAMRA
        )

        (pick,) = found.trips[0].stops[0].picks
        assert (pick.product_id, pick.listing_id) == (box_of_100, on_the_shelf)
        assert found.unplannable == []

        world.make.item(pharmacy_id=pharmacy, product_id=other_brand, days_left=20)  # cheaper
        again = planning.plan(
            world.tx(), client_id=client, lines=[BasketLine(box_of_100)], location=HAMRA
        )
        assert [p.listing_id for p in again.trips[0].stops[0].picks] == [on_the_shelf]
