"""Catalog search, listing search and travel times (docs/04 R-S, R-F, R-RT, R-C5, R-C6)."""

import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from dawalink.domain.geo import Point
from dawalink.services import catalog, travel
from dawalink.services.errors import Code, ServiceError
from dawalink.services.search import SearchResult, search_listings
from dawalink.services.travel import Location, district_location, shared_location
from tests.db.factories import TODAY
from tests.fakes import FakeRouting
from tests.services.conftest import World

HAMRA = shared_location(33.896, 35.483)
DAY = timedelta(days=1)


def product(world: World, name: str, **values: Any) -> uuid.UUID:
    return world.make.product(  # type: ignore[no-any-return]
        moph_name=name.upper(), search_name=name.lower(), **values
    )


class TestCatalogSearch:
    def test_a_misspelled_name_still_finds_the_medicine(self, world: World) -> None:
        augmentin = product(world, "Augmentin", dosage_text="1g")
        product(world, "Concor", dosage_text="5mg")

        found = catalog.search_products(world.tx(), "ogmentin")

        assert [p.id for p in found.products] == [augmentin]
        assert found.did_you_mean == []

    def test_a_strength_in_the_query_moves_that_strength_up(self, world: World) -> None:
        small = product(world, "Augmentin", dosage_text="625mg")
        large = product(world, "Augmentin", dosage_text="1g")

        found = catalog.search_products(world.tx(), "baddi Augmentin 1g")

        assert found.products[0].id == large
        assert {p.id for p in found.products} == {small, large}

    def test_an_ingredient_finds_its_products(self, world: World) -> None:
        panadol = product(world, "Panadol")
        with world.as_owner():
            world.connection.exec_driver_sql(
                "INSERT INTO product_ingredients (product_id, position, name, name_normalized) "
                "VALUES (%s, 1, 'Paracetamol', 'paracetamol')",
                (panadol,),
            )

        found = catalog.search_products(world.tx(), "paracetamol")

        assert [p.id for p in found.products] == [panadol]

    def test_a_weak_match_becomes_a_did_you_mean(self, world: World) -> None:
        product(world, "Glucophage")

        found = catalog.search_products(world.tx(), "glucofaj")

        assert found.products == []
        assert found.did_you_mean == ["GLUCOPHAGE"]

    def test_a_controlled_medicine_is_never_found(self, world: World) -> None:
        """R-C6, INV-6."""
        tramal = product(world, "Tramal", controlled=True)

        assert catalog.search_products(world.tx(), "tramal") == catalog.ProductSearch([], [])
        with pytest.raises(ServiceError) as refused:
            catalog.allowed_product(world.tx(), tramal)
        assert refused.value.code is Code.PRODUCT_NOT_ALLOWED

    def test_nothing_to_search_for_gives_nothing(self, world: World) -> None:
        assert catalog.search_products(world.tx(), "  500  ").products == []

    def test_equivalents_share_the_key_and_leave_out_controlled_products(
        self, world: World
    ) -> None:
        """R-C5: same key, nothing looser."""
        key = "paracetamol=500mg | tablet | N02BE01"
        panadol = product(world, "Panadol", equivalence_key=key, public_price_lbp=300_000)
        cheaper = product(world, "Paratest", equivalence_key=key, public_price_lbp=200_000)
        product(world, "Other", equivalence_key="other | tablet | A01")
        product(world, "Hidden", equivalence_key=key, controlled=True)
        alone = product(world, "Alone")

        assert [p.id for p in catalog.equivalents(world.tx(), panadol)] == [cheaper]
        assert catalog.equivalents(world.tx(), alone) == []

    def test_a_product_with_no_key_is_a_group_of_its_own(self, world: World) -> None:
        first, second = product(world, "First"), product(world, "Second")
        tx = world.tx()

        groups = {
            catalog.medicine_group(catalog.allowed_product(tx, product_id))
            for product_id in (first, second)
        }

        assert len(groups) == 2


class TestTravelTimes:
    def test_without_a_road_time_the_estimate_is_used_and_labelled(self, world: World) -> None:
        """R-RT1, FX-18."""
        near = world.make.pharmacy(lat=33.897, lon=35.484)
        far = world.make.pharmacy(lat=34.437, lon=35.850)

        times = travel.travel_to(world.tx(), HAMRA, [near, far])

        assert times[near].source == times[far].source == "straight"
        assert times[near].car_min < 5 < 60 < times[far].car_min

    def test_road_times_are_cached_for_a_day(self, world: World) -> None:
        """N-43."""
        pharmacy = world.make.pharmacy()
        routing = FakeRouting(minutes=12)

        assert travel.refresh(world.tx(), routing, HAMRA, [pharmacy]) == 1
        assert travel.refresh(world.tx(), routing, HAMRA, [pharmacy]) == 0
        cached = travel.travel_to(world.tx(), HAMRA, [pharmacy])[pharmacy]
        world.later(hours=25)
        stale = travel.travel_to(world.tx(), HAMRA, [pharmacy])[pharmacy]

        assert (cached.car_min, cached.walk_min, cached.km, cached.source) == (12, 60, 4.2, "road")
        assert stale.source == "straight"
        assert routing.calls == 2  # once by car, once on foot

    def test_a_failing_routing_service_changes_nothing(self, world: World) -> None:
        pharmacy = world.make.pharmacy()

        assert travel.refresh(world.tx(), FakeRouting(fail=True), HAMRA, [pharmacy]) == 0
        assert travel.travel_to(world.tx(), HAMRA, [pharmacy])[pharmacy].source == "straight"

    def test_reach_is_thirty_minutes_by_car(self, world: World) -> None:
        """N-23."""
        pharmacy = world.make.pharmacy()
        for minutes, expected in ((30, True), (31, False)):
            with world.as_owner():
                world.connection.exec_driver_sql("DELETE FROM travel_time_cache")
            travel.refresh(world.tx(), FakeRouting(minutes), HAMRA, [pharmacy])
            found = travel.travel_to(world.tx(), HAMRA, [pharmacy])[pharmacy]
            assert travel.within_reach(found) is expected

    def test_a_district_stands_in_for_a_location(self, world: World) -> None:
        """R-S2: Beirut's reference point."""
        location = district_location(world.tx(), 1)

        assert location == Location(Point(Decimal("33.89380"), Decimal("35.50180")), "district", 1)
        with pytest.raises(ServiceError):
            district_location(world.tx(), 999)
        with pytest.raises(ServiceError):
            shared_location(120, 35)


class TestListingSearch:
    @pytest.fixture
    def setup(self, world: World) -> dict[str, uuid.UUID]:
        key = "paracetamol=500mg | tablet | N02BE01"
        return {
            "client": world.make.client(),
            "panadol": product(world, "Panadol", equivalence_key=key, public_price_lbp=1_000_000),
            "paratest": product(world, "Paratest", equivalence_key=key, public_price_lbp=800_000),
            "near": world.make.pharmacy(lat=33.897, lon=35.484),
            "far": world.make.pharmacy(lat=34.437, lon=35.850),
        }

    def find(self, world: World, setup: dict[str, uuid.UUID], **values: Any) -> SearchResult:
        return search_listings(
            world.tx(),
            client_id=setup["client"],
            product_ids=[setup["panadol"]],
            location=HAMRA,
            **values,
        )

    def test_it_returns_visible_boxes_with_price_saving_and_travel(
        self, world: World, setup: dict[str, uuid.UUID]
    ) -> None:
        item = world.make.item(
            pharmacy_id=setup["near"], product_id=setup["panadol"], days_left=60, qty_on_hand=7
        )
        world.make.item(pharmacy_id=setup["near"], product_id=setup["panadol"], days_left=200)
        world.make.item(pharmacy_id=setup["near"], product_id=setup["paratest"], days_left=60)

        result = self.find(world, setup)

        (listing,) = result.listings
        assert listing.id == item
        assert (listing.price_lbp, listing.discount_pct, listing.days_left) == (600_000, 40, 60)
        assert (listing.available, listing.more_available) == (5, True)
        assert listing.pharmacy.open_now
        assert listing.pharmacy.district == "Beirut"
        assert listing.travel.source == "straight"
        assert listing.fits is None  # the client didn't say for how many days
        assert listing.pickup_days_allowed == (TODAY, TODAY + DAY)
        assert not hasattr(listing.pharmacy, "lat")
        assert result.total_found == 1

    def test_alternatives_appear_only_when_asked_for_and_are_labelled(
        self, world: World, setup: dict[str, uuid.UUID]
    ) -> None:
        """R-S4."""
        world.make.item(pharmacy_id=setup["near"], product_id=setup["panadol"])
        other = world.make.item(pharmacy_id=setup["near"], product_id=setup["paratest"])

        without = self.find(world, setup)
        with_them = self.find(world, setup, include_alternatives=True)

        assert [listing.is_alternative for listing in without.listings] == [False]
        assert {found.id: found.is_alternative for found in with_them.listings}[other] is True
        assert len(with_them.listings) == 2

    def test_the_best_match_is_the_shortest_trip_then_the_price(
        self, world: World, setup: dict[str, uuid.UUID]
    ) -> None:
        """R-S3."""
        far_cheap = world.make.item(
            pharmacy_id=setup["far"], product_id=setup["panadol"], days_left=10
        )
        near = world.make.item(pharmacy_id=setup["near"], product_id=setup["panadol"], days_left=60)

        best = [found.id for found in self.find(world, setup).listings]
        cheapest = [found.id for found in self.find(world, setup, sort="cheapest").listings]

        assert best == [near, far_cheap]
        assert cheapest == [far_cheap, near]

    def test_a_box_that_does_not_last_is_left_out(
        self, world: World, setup: dict[str, uuid.UUID]
    ) -> None:
        """R-F1, INV-25."""
        short = world.make.item(pharmacy_id=setup["near"], product_id=setup["panadol"], days_left=5)
        long = world.make.item(pharmacy_id=setup["near"], product_id=setup["panadol"], days_left=40)

        result = self.find(world, setup, days_of_use=12)

        assert [found.id for found in result.listings] == [long]
        assert result.listings[0].fits is True
        assert short not in {found.id for found in result.listings}

    def test_when_nothing_lasts_the_client_is_told_the_latest_expiry(
        self, world: World, setup: dict[str, uuid.UUID]
    ) -> None:
        """R-F4."""
        world.make.item(pharmacy_id=setup["near"], product_id=setup["panadol"], days_left=5)
        world.make.item(pharmacy_id=setup["far"], product_id=setup["panadol"], days_left=8)

        result = self.find(world, setup, days_of_use=12)

        assert result.listings == []
        assert result.no_match is not None
        assert result.no_match.latest_expiry == TODAY + 8 * DAY
        assert result.no_match.latest_pickup_day is None

    def test_a_later_pickup_day_can_rule_a_box_out(
        self, world: World, setup: dict[str, uuid.UUID]
    ) -> None:
        """R-F6, the owner's example: 7 days left, 7 days of use, a pharmacy that holds 3 days."""
        three_days = world.make.pharmacy(lat=33.897, lon=35.484, pickup_days=3)
        item = world.make.item(pharmacy_id=three_days, product_id=setup["panadol"], days_left=7)

        any_day = self.find(world, setup, days_of_use=7)
        tomorrow = self.find(world, setup, days_of_use=7, pickup_day=TODAY + DAY)
        third_day = self.find(world, setup, days_of_use=7, pickup_day=TODAY + 2 * DAY)

        (listing,) = any_day.listings
        assert listing.id == item
        assert listing.pickup_days_allowed == (TODAY, TODAY + DAY)
        assert listing.expiry_limits_pickup is True
        assert [found.id for found in tomorrow.listings] == [item]
        assert third_day.listings == []
        assert third_day.left_out_by_pickup_day == 1
        assert third_day.no_match is not None
        assert third_day.no_match.latest_pickup_day == TODAY + DAY

    def test_a_day_the_pharmacy_does_not_accept_leaves_it_out(
        self, world: World, setup: dict[str, uuid.UUID]
    ) -> None:
        """R-F3: the default pharmacy holds a reservation for one open day."""
        world.make.item(pharmacy_id=setup["near"], product_id=setup["panadol"], days_left=90)

        in_three_days = self.find(world, setup, pickup_day=TODAY + 3 * DAY)

        assert in_three_days.listings == []
        assert in_three_days.left_out_by_pickup_day == 1

    def test_a_budget_filters_by_the_price_in_lbp(
        self, world: World, setup: dict[str, uuid.UUID]
    ) -> None:
        world.make.item(pharmacy_id=setup["near"], product_id=setup["panadol"], days_left=60)

        assert len(self.find(world, setup, max_price_lbp=600_000).listings) == 1
        assert self.find(world, setup, max_price_lbp=599_999).listings == []

    @pytest.mark.rows_by_hand
    def test_what_is_not_visible_is_never_returned(
        self, world: World, setup: dict[str, uuid.UUID]
    ) -> None:
        """INV-16, INV-8: paused, sold out, private, or at a pharmacy that isn't approved."""
        pending = world.make.pharmacy("PENDING")
        for values in (
            {"listing_control": "PAUSED"},
            {"qty_on_hand": 2, "qty_reserved": 2},
            {"days_left": 200},
            {"days_left": -1},
            {"pharmacy_id": pending},
        ):
            world.make.item(
                **{"pharmacy_id": setup["near"], "product_id": setup["panadol"]} | values
            )

        assert self.find(world, setup).listings == []
        assert self.find(world, setup).no_match is None

    def test_guards(self, world: World, setup: dict[str, uuid.UUID]) -> None:
        suspended = world.make.client("SUSPENDED")
        controlled = product(world, "Tramal", controlled=True)

        def code(**values: Any) -> Code:
            asked: dict[str, Any] = {
                "client_id": setup["client"],
                "product_ids": [setup["panadol"]],
                "location": HAMRA,
            }
            with pytest.raises(ServiceError) as refused:
                search_listings(world.tx(), **(asked | values))
            return refused.value.code

        assert code(client_id=suspended) is Code.ACCOUNT_SUSPENDED
        assert code(product_ids=[controlled]) is Code.PRODUCT_NOT_ALLOWED
        assert code(pickup_day=TODAY - DAY) is Code.PICKUP_DAY_INVALID
        assert code(days_of_use=0) is Code.VALIDATION_ERROR

    def test_a_paused_or_unverified_client_can_still_search(
        self, world: World, setup: dict[str, uuid.UUID]
    ) -> None:
        """SM-2."""
        world.make.item(pharmacy_id=setup["near"], product_id=setup["panadol"])
        for status, values in (("UNVERIFIED", {}), ("PAUSED", {"paused_until": world.clock.now()})):
            client = world.make.client(status, **values)
            result = search_listings(
                world.tx(), client_id=client, product_ids=[setup["panadol"]], location=HAMRA
            )
            assert len(result.listings) == 1
