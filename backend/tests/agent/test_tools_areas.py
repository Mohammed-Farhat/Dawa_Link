"""The agent's search tools, for the owner's findings of 2026-11-22: an area to look in
is not where the client is, an empty answer says why, and an option says which box it is.
What the model is given is names and reasons, never a point (INV-24)."""

import uuid

import pytest

from tests.agent.conftest import Scene
from tests.db.factories import TODAY
from tests.services.conftest import World


def district(world: World, name: str) -> int:
    return int(world.one("SELECT id FROM districts WHERE name = :n", n=name).id)


class TestTheAgentsTools:
    """What the model is given: names and reasons, never a point (INV-24)."""

    @pytest.fixture
    def sidon(self, scene: Scene) -> uuid.UUID:
        return scene.world.make.pharmacy(  # type: ignore[no-any-return]
            name="Sea Pharmacy", lat=33.563, lon=35.376, district_id=district(scene.world, "Sidon")
        )

    def test_an_area_to_look_in_is_not_where_the_client_is(
        self, scene: Scene, sidon: uuid.UUID
    ) -> None:
        scene.stock()
        scene.stock(pharmacy_id=sidon)

        found = scene.tool(
            "find_options", product_ids=[scene.augmentin], areas=[{"place": "saida"}]
        )

        assert [option["pharmacy"]["name"] for option in found["options"]] == ["Sea Pharmacy"]
        assert found["searched_in"] == ["Sidon"]
        # The chat's own location is untouched: the client is still where they were.
        chat = scene.conversation()
        assert (chat.loc_source, chat.loc_area_id) == ("shared", None)

    def test_several_areas_are_searched_together(self, scene: Scene, sidon: uuid.UUID) -> None:
        scene.stock()
        scene.stock(pharmacy_id=sidon)

        found = scene.tool(
            "find_options",
            product_ids=[scene.augmentin],
            areas=[{"place": "Saida"}, {"place": "Hamra"}],
        )

        names = {option["pharmacy"]["name"] for option in found["options"]}
        assert names == {"Sea Pharmacy", "Hamra Pharmacy"}
        assert found["searched_in"] == ["Beirut", "Sidon"]  # Hamra counts as its district

    def test_none_in_the_areas_is_said_with_what_is_elsewhere(self, scene: Scene) -> None:
        scene.stock()

        found = scene.tool(
            "find_options", product_ids=[scene.augmentin], areas=[{"place": "Saida"}]
        )

        assert found["options"] == []
        assert (found["why_none"], found["elsewhere"]) == ("not_in_these_areas", 1)

    def test_a_name_that_is_not_listed_is_never_guessed(self, scene: Scene) -> None:
        scene.stock()

        told = scene.tool(
            "find_options", product_ids=[scene.augmentin], areas=[{"place": "Timbuktu"}]
        )

        assert (told["ok"], told["error_code"]) == (False, "AREA_NOT_FOUND")

    def test_listed_nowhere_is_told_apart_from_another_day(self, scene: Scene) -> None:
        found = scene.tool(
            "find_options", product_ids=[scene.augmentin], days_of_use=7, pickup_day=TODAY
        )

        assert (found["options"], found["why_none"]) == ([], "none_listed")

    def test_an_option_says_which_box_it_is_and_the_last_day_it_lasts(self, scene: Scene) -> None:
        """One name comes in several box sizes: each option says its own. A box that lasts
        only if picked up today says so, as a day."""
        zentrol = scene.world.make.product(
            moph_name="ZENTROL",
            search_name="zentrol",
            dosage_text="500mg",
            form_text="Tablet",
            presentation_text="24",
        )
        scene.stock(zentrol, days_left=2)  # 3 days of use: from today yes, from tomorrow no

        (option,) = scene.tool("find_options", product_ids=[zentrol], days_of_use=3)["options"]

        assert (option["strength"], option["form"], option["pack"]) == ("500mg", "Tablet", "24")
        assert option["expiry_limits_pickup"] is True
        assert option["pick_up_by"] == TODAY.isoformat()
        assert option["pickup_days_allowed"] == [TODAY.isoformat()]

    def test_a_plan_can_be_kept_to_the_areas(self, scene: Scene, sidon: uuid.UUID) -> None:
        scene.stock()

        planned = scene.tool(
            "plan_basket",
            items=[{"product_id": scene.augmentin}],
            areas=[{"place": "Saida"}],
        )

        assert planned["plans"] == []
        assert [gap["reason"] for gap in planned["unplannable"]] == ["not_in_these_areas"]
