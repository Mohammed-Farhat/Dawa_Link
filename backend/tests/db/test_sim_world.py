"""The simulated world in a database (docs/08 §2.3): the map file as committed, and a
seed's stock. The catalog here is invented, as in every test."""

import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Connection, text

from dawalink.domain.geo import Point, straight_line_km
from dawalink.sim import geometry, travel_table, world
from dawalink.sim.database import PREFIX, _checked
from tests.db import factories as make
from tests.db.factories import NOW, TODAY


@pytest.fixture
def catalog(db: Connection) -> None:
    for number in range(40):
        make.product(db, equivalence_key=f"group-{number // 2}" if number < 30 else None)
    make.product(db, controlled=True, equivalence_key="group-0")


class TestTheMap:
    def test_the_committed_map_is_what_the_code_makes(self) -> None:
        """The file is generated: a change by hand, or to the areas, shows up here."""
        made = geometry.make()
        committed = geometry.WORLD_FILE.read_text(encoding="utf-8")

        loaded = world.load()

        assert len(loaded.pharmacies) == len(made["pharmacies"]) == 30
        assert len(loaded.clients) == len(made["clients"]) == 200
        assert '"lat": ' + str(made["pharmacies"][0]["lat"]) in committed
        assert [(p.n, p.lat, p.lon) for p in loaded.pharmacies] == [
            (p["n"], p["lat"], p["lon"]) for p in made["pharmacies"]
        ]

    def test_everyone_is_in_lebanon_near_a_pharmacy_of_their_district(self) -> None:
        loaded = world.load()
        for client in loaded.clients:
            assert 33.0 <= client.lat <= 34.7, client.n
            assert 35.1 <= client.lon <= 36.7, client.n
            here = Point(client.lat, client.lon)  # type: ignore[arg-type]
            nearest = min(
                straight_line_km(here, Point(p.lat, p.lon))  # type: ignore[arg-type]
                for p in loaded.pharmacies
                if p.district == client.district
            )
            assert nearest < 40, client.n

    def test_the_map_holds_no_person(self) -> None:
        text_of_file = geometry.WORLD_FILE.read_text(encoding="utf-8")

        assert "@" not in text_of_file
        assert "name" not in text_of_file.replace('"near"', "")


class TestPopulating:
    def test_it_adds_the_pharmacies_the_clients_and_a_seeds_stock(
        self, db: Connection, catalog: None
    ) -> None:
        loaded = world.load()

        done = world.populate(db, loaded, seed=1, now=NOW)

        counts = db.execute(
            text(
                "SELECT (SELECT count(*) FROM pharmacies WHERE status = 'APPROVED'), "
                "(SELECT count(*) FROM client_profiles WHERE status = 'ACTIVE'), "
                "(SELECT count(*) FROM inventory_items), "
                "(SELECT count(DISTINCT pharmacy_id) FROM pharmacy_hours)"
            )
        ).one()
        assert tuple(counts) == (30, 200, done.inventory_items, 30)
        assert done.inventory_items == 30 * 40  # the invented catalog has 40 medicines
        assert len(done.demand) == 40

    def test_a_controlled_medicine_is_never_asked_for_or_stocked(
        self, db: Connection, catalog: None
    ) -> None:
        done = world.populate(db, world.load(), seed=1, now=NOW)

        controlled = db.execute(text("SELECT id FROM products WHERE controlled")).scalar_one()
        stocked = set(db.execute(text("SELECT DISTINCT product_id FROM inventory_items")).scalars())
        assert controlled not in done.demand
        assert controlled not in stocked

    def test_stock_expires_from_today_on_the_runs_own_clock(
        self, db: Connection, catalog: None
    ) -> None:
        world.populate(db, world.load(), seed=1, now=NOW)

        first, last = db.execute(
            text("SELECT min(expiry_date), max(expiry_date) FROM inventory_items")
        ).one()
        assert TODAY + timedelta(days=3) <= first
        assert last <= TODAY + timedelta(days=500)

    def test_the_same_seed_gives_the_same_shelves_and_another_seed_others(self) -> None:
        """Pairing (docs/08 §4): every contender of a seed starts from the same world."""
        loaded = world.load()
        demand = tuple(uuid.uuid5(world.NAMESPACE, f"p{n}") for n in range(300))
        pharmacy = loaded.pharmacies[4]

        one = world.shelf(pharmacy, demand, seed=7, now=NOW)
        again = world.shelf(pharmacy, demand, seed=7, now=NOW)
        other = world.shelf(pharmacy, demand, seed=8, now=NOW)

        assert one == again
        assert [item["product_id"] for item in one] != [item["product_id"] for item in other]
        assert len(one) == world.ITEMS_PER_PHARMACY
        assert len({item["product_id"] for item in one}) == world.ITEMS_PER_PHARMACY

    def test_more_private_stock_changes_the_expiry_dates_and_nothing_else(self) -> None:
        """An assumption of docs/08 §2.4: the share of boxes a pharmacy may release when
        asked (181 to 270 days from expiry). A sweep changes it; the medicines and the
        quantities on the shelf stay what they were."""
        loaded = world.load()
        demand = tuple(uuid.uuid5(world.NAMESPACE, f"p{n}") for n in range(300))

        def shelves(share: float) -> list[dict[str, Any]]:
            return [
                item
                for pharmacy in loaded.pharmacies
                for item in world.shelf(
                    pharmacy, demand, seed=1, now=NOW, early_release_share=share
                )
            ]

        def can_be_asked_for(items: list[dict[str, Any]]) -> float:
            asked = [181 <= (item["expiry_date"] - TODAY).days <= 270 for item in items]
            return float(sum(asked)) / len(asked)

        usual, half, double = shelves(0.25), shelves(0.125), shelves(0.5)

        assert usual == [
            item
            for pharmacy in loaded.pharmacies
            for item in world.shelf(pharmacy, demand, seed=1, now=NOW)
        ]
        assert 0.21 < can_be_asked_for(usual) < 0.29
        assert 0.09 < can_be_asked_for(half) < 0.16
        assert 0.45 < can_be_asked_for(double) < 0.55
        same = ("product_id", "qty_on_hand", "pharmacy_id")
        assert [[item[key] for key in same] for item in double] == [
            [item[key] for key in same] for item in usual
        ]

    def test_one_shelf_does_not_depend_on_the_others(self) -> None:
        """Each draw belongs to its own thing, not to one shared stream."""
        assert (
            world.numbers_for(3, "shelf", 9).random() == world.numbers_for(3, "shelf", 9).random()
        )
        assert (
            world.numbers_for(3, "shelf", 9).random() != world.numbers_for(3, "shelf", 10).random()
        )


class TestTheSimulationsDatabase:
    @pytest.mark.parametrize(
        "name", ["dawalink", "dawalink_test", "postgres", "dawalink_sim; drop"]
    )
    def test_only_a_simulation_database_is_ever_touched(self, name: str) -> None:
        """The app's database holds real development chats and a worker on a paid model."""
        with pytest.raises(ValueError, match="simulation database"):
            _checked(name)

    def test_a_simulation_name_is_accepted(self) -> None:
        assert _checked(f"{PREFIX}_b0_seed_1") == "dawalink_sim_b0_seed_1"


class FakeRoads:
    """Stands in for the routing service: 7 minutes and 3 km to everywhere, and it counts."""

    def __init__(self, *, no_road_to: uuid.UUID | None = None) -> None:
        self.asked: list[tuple[int, int, str]] = []
        self.no_road_to = no_road_to

    def road_times(self, origins: Any, destinations: Any, mode: str) -> Any:
        self.asked.append((len(origins), len(destinations), mode))
        return {
            (origin, pharmacy_id): (7, 3.0)
            for origin in origins
            for pharmacy_id in destinations
            if pharmacy_id != self.no_road_to
        }


class TestRoadTimes:
    def test_every_trip_is_asked_for_in_small_requests(self) -> None:
        loaded = world.load()
        roads = FakeRoads()

        table, requests = travel_table.fetch(roads, loaded, pause_s=0)

        starts = len(travel_table.origins_of(loaded))
        assert requests == len(roads.asked) == 2 * -(-starts // travel_table.ORIGINS_PER_REQUEST)
        assert all(origins <= travel_table.ORIGINS_PER_REQUEST for origins, _, _ in roads.asked)
        assert {mode for _, _, mode in roads.asked} == {"car", "walk"}
        assert len(table) == starts
        assert all(len(by_mode[mode]) == 30 for by_mode in table.values() for mode in by_mode)

    def test_a_pair_with_no_road_is_left_out_of_the_cache(self) -> None:
        loaded = world.load()
        cut_off = loaded.pharmacies[3].id
        table, _ = travel_table.fetch(FakeRoads(no_road_to=cut_off), loaded, pause_s=0)

        rows = travel_table.cache_rows(table, loaded, now=NOW)

        assert cut_off not in {row["pharmacy_id"] for row in rows}
        assert {row["computed_at"] for row in rows} == {NOW}
        assert {(row["minutes"], row["km"], row["source"]) for row in rows} == {(7, 3.0, "road")}

    def test_the_committed_table_covers_every_client_and_pharmacy(self) -> None:
        loaded = world.load()
        table = travel_table.read()

        assert table is not None
        assert set(table) == set(travel_table.origins_of(loaded))
        assert all(set(by_mode) == {"car", "walk"} for by_mode in table.values())
        text_of_file = travel_table.TRAVEL_FILE.read_text(encoding="utf-8")
        assert "OpenStreetMap contributors" in text_of_file
        assert "openrouteservice.org" in text_of_file

    def test_the_app_finds_the_road_times_in_its_cache(self, db: Connection, catalog: None) -> None:
        """The simulation makes no routing call: search and matching read the same cache."""
        loaded = world.load()
        table = travel_table.read()
        assert table is not None

        done = world.populate(
            db, loaded, seed=1, now=NOW, road_times=travel_table.cache_rows(table, loaded, now=NOW)
        )

        client, pharmacy = loaded.clients[0], loaded.pharmacies[0]
        cached = db.execute(
            text(
                "SELECT mode, minutes FROM travel_time_cache "
                "WHERE pharmacy_id = :p AND origin_cell = :c ORDER BY mode"
            ),
            {"p": pharmacy.id, "c": f"{client.lat:.3f},{client.lon:.3f}"},
        ).all()
        assert (
            done.road_times == db.execute(text("SELECT count(*) FROM travel_time_cache")).scalar()
        )
        assert [mode for mode, _ in cached] == ["car", "walk"]
        assert cached[0][1] <= cached[1][1]  # driving is not slower than walking


def test_the_world_folder_is_documented() -> None:
    assert (Path("../eval/world") / "README.md").is_file()
