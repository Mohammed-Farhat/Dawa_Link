"""Why a search found nothing, and looking only in the areas a client named.

The owner's findings of 2026-11-22: the assistant answered "try another day" for a
medicine no pharmacy had, said "expires too early" for a pharmacy that was closed, and
moved the client to Beirut when they only wanted to look there.
"""

from datetime import timedelta
from typing import Any

import pytest

from dawalink.services import planning
from dawalink.services.planning import BasketLine
from dawalink.services.search import SearchResult, WhyNone, search_listings
from dawalink.services.travel import shared_location
from tests.db.factories import BEIRUT_DISTRICT, TODAY
from tests.services.conftest import World

HAMRA = shared_location(33.896, 35.483)
DAY = timedelta(days=1)
# Open every day but the test's own day (TODAY, a Tuesday): closed today, open tomorrow.
CLOSED_TODAY = {day: [("08:00", "20:00")] for day in range(7) if day != TODAY.weekday()}


def district(world: World, name: str) -> int:
    return int(world.one("SELECT id FROM districts WHERE name = :n", n=name).id)


@pytest.fixture
def shop(world: World) -> dict[str, Any]:
    return {
        "client": world.make.client(),
        "medicine": world.make.product(moph_name="ZENTROL", search_name="zentrol"),
        "beirut": world.make.pharmacy(lat=33.897, lon=35.484, district_id=BEIRUT_DISTRICT),
        "sidon": world.make.pharmacy(lat=33.563, lon=35.376, district_id=district(world, "Sidon")),
    }


def find(world: World, shop: dict[str, Any], **values: Any) -> SearchResult:
    return search_listings(
        world.tx(),
        client_id=shop["client"],
        product_ids=[shop["medicine"]],
        location=HAMRA,
        **values,
    )


class TestWhyNothingWasFound:
    def test_no_pharmacy_lists_it_at_all(self, world: World, shop: dict[str, Any]) -> None:
        result = find(world, shop, days_of_use=7, pickup_day=TODAY)

        assert (result.listings, result.why_none) == ([], WhyNone.NONE_LISTED)
        assert result.days_that_work == ()

    def test_every_box_is_above_the_price_limit(self, world: World, shop: dict[str, Any]) -> None:
        world.make.item(pharmacy_id=shop["beirut"], product_id=shop["medicine"], days_left=60)

        result = find(world, shop, max_price_lbp=100)

        assert result.why_none is WhyNone.OVER_BUDGET
        assert result.cheapest_lbp == 600_000  # 40% off the public price of 1,000,000

    def test_no_box_lasts_the_days_of_use(self, world: World, shop: dict[str, Any]) -> None:
        world.make.item(pharmacy_id=shop["beirut"], product_id=shop["medicine"], days_left=5)

        result = find(world, shop, days_of_use=30)

        assert result.why_none is WhyNone.EXPIRES_TOO_EARLY
        assert result.no_match is not None
        assert result.no_match.latest_expiry == TODAY + 5 * DAY

    def test_the_pharmacy_is_closed_that_day_which_is_not_the_expiry(
        self, world: World, shop: dict[str, Any]
    ) -> None:
        """Seen on 2026-11-22: the only pharmacy was closed on Sunday, and the client was
        told the box expired too early."""
        closed = world.make.pharmacy(lat=33.897, lon=35.484, hours=CLOSED_TODAY)
        world.make.item(pharmacy_id=closed, product_id=shop["medicine"], days_left=60)

        result = find(world, shop, days_of_use=3, pickup_day=TODAY)

        assert result.why_none is WhyNone.NOT_ON_THAT_DAY
        assert result.days_that_work == (TODAY + DAY,)

    def test_with_no_day_asked_the_same_box_is_simply_found(
        self, world: World, shop: dict[str, Any]
    ) -> None:
        closed = world.make.pharmacy(lat=33.897, lon=35.484, hours=CLOSED_TODAY)
        box = world.make.item(pharmacy_id=closed, product_id=shop["medicine"], days_left=60)

        result = find(world, shop, days_of_use=3)

        assert [listing.id for listing in result.listings] == [box]
        assert result.listings[0].pickup_days_allowed == (TODAY + DAY,)
        assert result.why_none is None

    def test_something_found_has_no_reason(self, world: World, shop: dict[str, Any]) -> None:
        world.make.item(pharmacy_id=shop["beirut"], product_id=shop["medicine"], days_left=60)

        assert find(world, shop).why_none is None


class TestLookingOnlyInTheNamedAreas:
    def test_only_pharmacies_of_those_districts_and_times_from_where_the_client_is(
        self, world: World, shop: dict[str, Any]
    ) -> None:
        near = world.make.item(
            pharmacy_id=shop["beirut"], product_id=shop["medicine"], days_left=60
        )
        far = world.make.item(pharmacy_id=shop["sidon"], product_id=shop["medicine"], days_left=60)

        everywhere = find(world, shop)
        in_sidon = find(world, shop, districts=frozenset({"Sidon"}))
        in_both = find(world, shop, districts=frozenset({"Sidon", "Beirut"}))

        assert {listing.id for listing in everywhere.listings} == {near, far}
        assert [listing.id for listing in in_sidon.listings] == [far]
        assert {listing.id for listing in in_both.listings} == {near, far}
        # The trip to Sidon is counted from Hamra, where the client is: about 40 km.
        assert in_sidon.listings[0].travel.km > 30

    def test_none_in_these_areas_says_so_and_how_many_are_elsewhere(
        self, world: World, shop: dict[str, Any]
    ) -> None:
        world.make.item(pharmacy_id=shop["beirut"], product_id=shop["medicine"], days_left=60)

        result = find(world, shop, districts=frozenset({"Sidon"}))

        assert (result.listings, result.why_none) == ([], WhyNone.NOT_IN_THESE_AREAS)
        assert result.elsewhere == 1

    def test_listed_nowhere_is_still_listed_nowhere(
        self, world: World, shop: dict[str, Any]
    ) -> None:
        result = find(world, shop, districts=frozenset({"Sidon"}))

        assert (result.why_none, result.elsewhere) == (WhyNone.NONE_LISTED, 0)

    def test_a_plan_keeps_to_the_areas_and_reports_what_is_only_elsewhere(
        self, world: World, shop: dict[str, Any]
    ) -> None:
        other = world.make.product(moph_name="BRAXIL", search_name="braxil")
        world.make.item(pharmacy_id=shop["sidon"], product_id=shop["medicine"], days_left=60)
        world.make.item(pharmacy_id=shop["beirut"], product_id=other, days_left=60)
        lines = [BasketLine(shop["medicine"], 1, 1, None), BasketLine(other, 1, 1, None)]

        planned = planning.plan(
            world.tx(),
            client_id=shop["client"],
            lines=lines,
            location=HAMRA,
            districts=frozenset({"Sidon"}),
        )

        (trip,) = planned.trips
        assert [stop.pharmacy.id for stop in trip.stops] == [shop["sidon"]]
        assert planned.only_elsewhere == (other,)

    def test_a_plan_with_no_areas_is_unchanged(self, world: World, shop: dict[str, Any]) -> None:
        world.make.item(pharmacy_id=shop["sidon"], product_id=shop["medicine"], days_left=60)

        planned = planning.plan(
            world.tx(),
            client_id=shop["client"],
            lines=[BasketLine(shop["medicine"], 1, 1, None)],
            location=HAMRA,
        )

        assert len(planned.trips) == 1
        assert planned.only_elsewhere == ()
