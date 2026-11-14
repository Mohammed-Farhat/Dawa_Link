"""The 19 tools, called one by one as a model would call them (docs/07 §4, §11).

Each test sends JSON arguments and reads the JSON result: exactly what crosses the line
between the model and our code. Rules covered: INV-8, INV-11, INV-21, INV-24; R-AG6 to
R-AG8; R-F1, R-F3; R-S2; R-W1; R-E8; N-39; docs/09 FA-13, FA-21, FA-26, FA-27, FA-31.
"""

import re
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

import dawalink.agent.tools as tools_package
from dawalink.agent.tools import ALL, REPLY_SPEC, for_mode
from dawalink.domain.vocabulary import AgentMode
from dawalink.services.requests import RequestLine
from tests.agent.conftest import Scene
from tests.db.factories import TODAY

DAY = timedelta(days=1)


def keys_in(value: Any) -> set[str]:
    """Every key anywhere in a JSON result."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys_in(item)}
    if isinstance(value, list):
        return {key for item in value for key in keys_in(item)}
    return set()


class TestTheToolList:
    def test_there_are_19_tools_and_reply(self) -> None:
        """AG-D2, BLD-D14, BLD-D17: 6 that read, 7 that make cards, 6 that act."""
        assert len(ALL) == 19
        assert len({tool.name for tool in ALL}) == 19
        assert REPLY_SPEC.name == "reply"

    def test_each_mode_has_its_own_tools(self) -> None:
        """docs/07 §2."""
        assistant, sourcing = set(for_mode(AgentMode.ASSISTANT)), set(for_mode(AgentMode.SOURCING))

        assert assistant - sourcing == {"prepare_request_summary", "create_watch", "set_area"}
        assert sourcing - assistant == {
            "open_claim",
            "propose_constraint_change",
            "propose_remove_item",
            "schedule_followup",
        }

    def test_no_tool_can_reserve_accept_cancel_or_start_anything(self) -> None:
        """INV-11: the code of the tools never calls the actions that only a tap may do."""
        forbidden = (
            r"orders\.reserve\(",
            r"accept_offer\(",
            r"cancel_by_client\(",
            r"cancel_by_system\(",
            r"create_request\(",
            r"cancel_request\(",
            r"requests\.remove_item\(",
            r"change_constraints\(",
            r"proposals\.execute\(",
            r"create_offer\(",
            r"inventory\.",
        )
        folder = Path(tools_package.__file__).parent
        code = "\n".join(path.read_text(encoding="utf-8") for path in folder.glob("*.py"))

        assert [pattern for pattern in forbidden if re.search(pattern, code)] == []

    def test_every_tool_describes_its_arguments(self) -> None:
        for tool in ALL:
            schema = tool.spec().parameters
            assert schema["type"] == "object", tool.name
            assert schema.get("additionalProperties") is False, tool.name
            assert len(tool.description) > 40, tool.name


class TestSearching:
    def test_the_catalog_never_returns_a_controlled_medicine(self, scene: Scene) -> None:
        """R-C6."""
        scene.world.make.product(
            moph_name="AUGMENTIN FORTE", search_name="augmentin forte", controlled=True
        )

        found = scene.tool("search_catalog", query="augmentin")

        assert [product["name"] for product in found["products"]] == ["AUGMENTIN 1G"]
        assert found["products"][0]["public_price"] == "1,000,000 LBP (about $11.17)"

    def test_equivalents_are_the_same_medicine_only(self, scene: Scene) -> None:
        """R-C5, hard rule 2."""
        with scene.world.as_owner():
            scene.world.connection.exec_driver_sql(
                "UPDATE products SET equivalence_key = 'amox-clav|1g|tab' WHERE moph_name = %s",
                ("AUGMENTIN 1G",),
            )
        other = scene.world.make.product(moph_name="CLAVOX 1G", equivalence_key="amox-clav|1g|tab")

        found = scene.tool("get_equivalents", product_id=scene.augmentin)

        assert [product["id"] for product in found["products"]] == [str(other)]

    def test_an_option_says_what_the_agent_needs_to_choose(self, scene: Scene) -> None:
        """R-AG9, R-RT4: travel, hours, price and expiry, for a box that lasts."""
        box = scene.stock(price_override_lbp=700_000)

        found = scene.tool("find_options", product_ids=[scene.augmentin], days_of_use=7)

        (option,) = found["options"]
        assert option["listing_id"] == str(box)
        assert option["pharmacy"] == {
            "name": "Hamra Pharmacy",
            "area": "Beirut",
            "open_now": True,
            "open_until": "Tue 21:00",
            "pickup_days": 1,
        }
        assert option["travel"] == {"car_min": 12, "walk_min": 60, "km": 4.2, "source": "road"}
        assert option["price"] == "700,000 LBP (about $7.82)"
        assert option["pickup_days_allowed"] == [TODAY.isoformat(), (TODAY + DAY).isoformat()]
        assert option["open_hours"][0] == {"day": TODAY.isoformat(), "hours": "08:00-21:00"}
        assert (option["available"], option["more_available"]) == (5, False)

    def test_nothing_about_a_place_leaks_into_an_option(self, scene: Scene) -> None:
        """INV-23, INV-24: no address, no coordinates, no pharmacy ID."""
        scene.stock()

        found = scene.tool("find_options", product_ids=[scene.augmentin])

        assert not {"address", "lat", "lon", "pharmacy_id", "id", "phone"} & keys_in(found)
        assert "12 Secret Lane" not in str(found)
        assert "33.89" not in str(found)

    def test_only_road_times_for_the_pharmacies_in_play_are_asked(self, scene: Scene) -> None:
        scene.stock()
        scene.world.make.pharmacy(name="Elsewhere")

        scene.tool("find_options", product_ids=[scene.augmentin])
        scene.tool("find_options", product_ids=[scene.augmentin])

        # Once by car and once on foot, for the one pharmacy that has it; then the cache.
        assert scene.routing.calls == 2
        assert all(len(destinations) == 1 for _, destinations, _ in scene.routing.asked)

    def test_without_a_routing_service_the_estimate_is_used(self, scene: Scene) -> None:
        """FX-18."""
        scene.routing.fail = True
        scene.stock()

        (option,) = scene.tool("find_options", product_ids=[scene.augmentin])["options"]

        assert option["travel"]["source"] == "straight"

    def test_a_box_that_expires_too_early_is_not_an_option(self, scene: Scene) -> None:
        """R-F1, R-F4, FA-26."""
        scene.stock(days_left=5)

        found = scene.tool("find_options", product_ids=[scene.augmentin], days_of_use=10)

        assert found["options"] == []
        assert found["no_match"]["latest_expiry"] == (TODAY + 5 * DAY).isoformat()

    def test_a_later_pickup_day_leaves_fewer_days(self, scene: Scene) -> None:
        """R-F6, BLD-D2: the box lasts 7 days from today, not from tomorrow."""
        scene.stock(days_left=6)

        today = scene.tool("find_options", product_ids=[scene.augmentin], days_of_use=7)
        tomorrow = scene.tool(
            "find_options", product_ids=[scene.augmentin], days_of_use=7, pickup_day=TODAY + DAY
        )

        assert today["options"][0]["pickup_days_allowed"] == [TODAY.isoformat()]
        assert today["options"][0]["expiry_limits_pickup"] is True
        assert (tomorrow["options"], tomorrow["left_out_by_pickup_day"]) == ([], 1)

    def test_a_pickup_day_in_the_past_is_refused(self, scene: Scene) -> None:
        """FA-27."""
        found = scene.tool("find_options", product_ids=[scene.augmentin], pickup_day=TODAY - DAY)

        assert (found["ok"], found["error_code"]) == (False, "PICKUP_DAY_INVALID")

    def test_two_different_medicines_are_not_one_search(self, scene: Scene) -> None:
        """Hard rule 2 in code: only equivalents may be searched together."""
        found = scene.tool("find_options", product_ids=[scene.augmentin, scene.concor])

        assert found["error_code"] == "NOT_SAME_MEDICINE"

    def test_without_a_location_the_agent_is_told_to_ask(self, scene: Scene) -> None:
        nowhere = scene.world.make.client(district_id=None)
        chat = scene.world.make.conversation(client_id=nowhere)

        found = scene.tool("find_options", chat, product_ids=[scene.augmentin])

        assert found["error_code"] == "LOCATION_NEEDED"


class TestNamingAnArea:
    """ "I'm in Hamra" instead of sharing a location (R-S2, BLD-D14)."""

    @pytest.fixture
    def nowhere(self, scene: Scene) -> uuid.UUID:
        """A chat of a client with no shared location and no home district."""
        return scene.world.make.conversation(  # type: ignore[no-any-return]
            client_id=scene.world.make.client(district_id=None)
        )

    def test_the_area_becomes_the_chats_location(self, scene: Scene, nowhere: uuid.UUID) -> None:
        scene.stock()

        told = scene.tool("set_area", nowhere, place="el hamra")
        found = scene.tool("find_options", nowhere, product_ids=[scene.augmentin])

        assert told == {
            "ok": True,
            "area": "Hamra",
            "district": "Beirut",
            "precision": "area",
            "note": "Travel times are now counted from the centre of this area.",
        }
        chat = scene.conversation(nowhere)
        assert (chat.loc_source, chat.loc_area_id) == ("area", 101)
        assert (float(chat.loc_lat), float(chat.loc_lon)) == (33.895, 35.482)  # rounded, N-43
        assert found["options"][0]["pharmacy"]["name"] == "Hamra Pharmacy"

    def test_the_model_gets_names_and_never_a_point(self, scene: Scene, nowhere: uuid.UUID) -> None:
        """INV-24."""
        answers = [
            scene.tool("set_area", nowhere, place="Hamra"),
            scene.tool("set_area", nowhere, place="Ashrafiyye"),
            scene.tool("set_area", nowhere, place="Chouf"),
        ]

        assert not {"lat", "lon", "ref_lat", "ref_lon", "id", "area_id"} & keys_in(answers)
        assert not re.search(r"3[3-6]\.\d", str(answers))

    def test_another_spelling_is_offered_not_taken(self, scene: Scene, nowhere: uuid.UUID) -> None:
        """FA-31: a wrong area would send the client to the wrong pharmacy unnoticed."""
        told = scene.tool("set_area", nowhere, place="Ashrafiyye")

        assert told["error_code"] == "AREA_NOT_FOUND"
        assert told["details"]["closest"][0] == {"area": "Achrafieh", "district": "Beirut"}
        assert scene.conversation(nowhere).loc_lat is None

    def test_an_unknown_place_changes_nothing(self, scene: Scene) -> None:
        told = scene.tool("set_area", place="Timbuktu")

        assert (told["error_code"], told["details"]) == ("AREA_NOT_FOUND", {"closest": []})
        assert scene.conversation().loc_source == "shared"

    def test_a_name_in_two_districts_is_asked_about(self, scene: Scene, nowhere: uuid.UUID) -> None:
        with scene.world.as_owner():
            scene.world.session.execute(
                text(
                    "INSERT INTO areas (id, name, district_id, ref_lat, ref_lon) "
                    "VALUES (9001, 'Aramoun', 9, 34.01, 35.69)"
                )
            )

        asked = scene.tool("set_area", nowhere, place="aramoun")
        nothing_yet = scene.conversation(nowhere).loc_area_id
        told = scene.tool("set_area", nowhere, place="aramoun", district="Keserwan")

        assert asked["error_code"] == "AREA_AMBIGUOUS"
        assert asked["details"]["choices"] == [
            {"area": "Aramoun", "district": "Aley"},
            {"area": "Aramoun", "district": "Keserwan"},
        ]
        assert nothing_yet is None
        assert (told["ok"], scene.conversation(nowhere).loc_area_id) == (True, 9001)

    def test_the_district_can_be_written_any_listed_way(
        self, scene: Scene, nowhere: uuid.UUID
    ) -> None:
        """BLD-D15: with the map's villages, many names are in several districts."""
        with scene.world.as_owner():
            scene.world.session.execute(
                text(
                    "INSERT INTO areas (id, name, district_id, other_names, ref_lat, ref_lon) "
                    "VALUES (9002, 'El Hamra', 23, ARRAY['الحمرا'], 33.31, 35.42)"
                )
            )

        asked = scene.tool("set_area", nowhere, place="الحمرا")
        beirut = scene.tool("set_area", nowhere, place="Hamra", district="Beyrouth")
        nabatieh = scene.tool("set_area", nowhere, place="hamra", district="nabatiyeh")
        elsewhere = scene.tool("set_area", nowhere, place="hamra", district="Zahle")

        assert asked["details"]["choices"] == [
            {"area": "El Hamra", "district": "Nabatieh"},
            {"area": "Hamra", "district": "Beirut"},
        ]
        assert (beirut["area"], beirut["district"]) == ("Hamra", "Beirut")
        assert (nabatieh["area"], nabatieh["district"]) == ("El Hamra", "Nabatieh")
        assert elsewhere["error_code"] == "AREA_NOT_FOUND"
        assert scene.conversation(nowhere).loc_area_id == 9002

    def test_a_whole_district_is_a_rough_start(self, scene: Scene, nowhere: uuid.UUID) -> None:
        told = scene.tool("set_area", nowhere, place="Shouf")

        assert (told["area"], told["precision"]) == ("Chouf", "district")
        assert scene.conversation(nowhere).loc_area_id == 14

    def test_the_place_named_last_replaces_a_shared_location(self, scene: Scene) -> None:
        """The client said where to search: that wins over the phone's earlier location."""
        scene.tool("set_area", place="Jounieh")
        scene.tool("set_area", place="Jounieh")

        chat = scene.conversation()
        assert (chat.loc_source, chat.loc_area_id) == ("area", 190)

    def test_only_a_chat_can_name_an_area(self, scene: Scene) -> None:
        """A request's location is fixed when it starts (R-RQ1)."""
        _, thread = scene.start_request()

        assert scene.tool("set_area", thread, place="Hamra")["error_code"] == "UNKNOWN_TOOL"

    def test_a_request_started_from_the_chat_keeps_the_area(
        self, scene: Scene, nowhere: uuid.UUID
    ) -> None:
        from dawalink.services import proposals

        client = scene.conversation(nowhere).client_id
        scene.tool("set_area", nowhere, place="Hamra")
        card = scene.tool(
            "prepare_request_summary",
            nowhere,
            items=[{"product_id": scene.augmentin}],
            alternatives_ok=False,
        )

        tx = scene.world.tx()
        proposals.execute(tx, client_id=client, proposal_id=uuid.UUID(card["proposal_id"]))
        scene.world.settle(tx)

        request = scene.world.one("SELECT * FROM sourcing_requests WHERE client_id = :c", c=client)
        thread = scene.world.one("SELECT * FROM conversations WHERE request_id = :r", r=request.id)
        assert (request.loc_source, request.district_id) == ("area", 1)
        assert (thread.loc_source, thread.loc_area_id) == ("area", 101)


class TestPlanning:
    def test_a_plan_groups_the_medicines_by_pharmacy(self, scene: Scene) -> None:
        """R-RQ5."""
        scene.stock(scene.augmentin, price_override_lbp=700_000)
        scene.stock(scene.concor, price_override_lbp=500_000)
        missing = scene.world.make.product(moph_name="GLUCOPHAGE 850MG")

        found = scene.tool(
            "plan_basket",
            items=[
                {"product_id": scene.augmentin, "qty": 2},
                {"product_id": scene.concor},
                {"product_id": missing},
            ],
        )

        (plan,) = found["plans"]
        (group,) = plan["groups"]
        assert group["pharmacy"]["name"] == "Hamra Pharmacy"
        assert group["hours_on_pickup_day"] == "08:00-21:00"
        assert [(item["product"], item["qty"]) for item in group["items"]] == [
            ("AUGMENTIN 1G", 2),
            ("CONCOR 5MG", 1),
        ]
        assert plan["total"] == "1,900,000 LBP (about $21.23)"
        assert plan["route"] == {
            "order": ["Hamra Pharmacy"],
            "total_car_min": 12,
            "total_walk_min": 60,
            "source": "road",
        }
        assert [(gap["product"], gap["reason"]) for gap in found["unplannable"]] == [
            ("GLUCOPHAGE 850MG", "none_listed")
        ]
        # The plan is remembered by code, so `propose_plan` can turn it into cards.
        assert list(scene.tool_turn().state.plans) == [plan["plan_id"]]

    def test_why_a_medicine_can_not_be_planned(self, scene: Scene) -> None:
        scene.stock(scene.augmentin, days_left=3)
        scene.stock(scene.concor, price_override_lbp=700_000)

        found = scene.tool(
            "plan_basket",
            items=[
                {"product_id": scene.augmentin, "days_of_use": 10},
                {"product_id": scene.concor, "max_price": {"amount": 5, "currency": "USD"}},
            ],
        )

        assert found["plans"] == []
        assert {gap["product"]: gap["reason"] for gap in found["unplannable"]} == {
            "AUGMENTIN 1G": "expires_too_early",
            "CONCOR 5MG": "over_budget",
        }


class TestProposing:
    def test_a_reserve_card_holds_exactly_what_the_tap_will_do(self, scene: Scene) -> None:
        """R-AG7, INV-21."""
        box = scene.stock(price_override_lbp=700_000)
        scene.tool("find_options", product_ids=[scene.augmentin])  # as a real turn does first

        made = scene.tool(
            "propose_reservation",
            listing_id=box,
            qty=2,
            pickup_day=TODAY,
            days_of_use=7,
            recommended=True,
        )

        proposal = scene.world.one("SELECT * FROM proposals WHERE id = :p", p=made["proposal_id"])
        assert proposal.kind == "reserve"
        assert (proposal.client_id, proposal.conversation_id) == (scene.client, scene.chat)
        assert proposal.agent_run_id == scene.tool_turn().run_id
        assert proposal.payload | {"card": None} == {
            "listing_id": str(box),
            "product_id": str(scene.augmentin),
            "qty": 2,
            "price_lbp_shown": 700_000,
            "pickup_day": TODAY.isoformat(),
            "days_of_use": 7,
            "request_item_id": None,
            "card": None,
        }
        card = proposal.payload["card"]
        assert card["title"] == "AUGMENTIN 1G at Hamra Pharmacy"
        assert ["At the counter", "1,400,000 LBP (about $15.64)"] in card["lines"]
        assert ["Travel", "12 min by car · 60 min on foot"] in card["lines"]
        assert (card["recommended"], card["prescription_notice"]) == (True, True)
        assert made["preview"]["title"] == card["title"]

    def test_proposing_changes_no_stock_and_makes_no_order(self, scene: Scene) -> None:
        """INV-11."""
        box = scene.stock()

        scene.tool("propose_reservation", listing_id=box, qty=3, pickup_day=TODAY)

        stock = scene.world.one("SELECT qty_reserved FROM inventory_items WHERE id = :i", i=box)
        assert stock.qty_reserved == 0
        assert scene.world.one("SELECT count(*) AS n FROM orders").n == 0

    @pytest.mark.parametrize(
        ("arguments", "code"),
        [
            ({"qty": 1, "days_of_use": 90}, "DOES_NOT_FIT"),
            ({"qty": 3, "days_of_use": 1}, "NOT_ENOUGH_STOCK"),
            ({"qty": 1, "pickup_day": TODAY + 5 * DAY}, "PICKUP_DAY_INVALID"),
        ],
    )
    def test_a_card_the_tap_would_refuse_is_not_made(
        self, scene: Scene, arguments: dict[str, Any], code: str
    ) -> None:
        """docs/07 §4.3, FA-26: the same checks as the tap, without a lock."""
        box = scene.stock(units=2, days_left=30)

        made = scene.tool(
            "propose_reservation", listing_id=box, **({"pickup_day": TODAY} | arguments)
        )

        assert (made["ok"], made["error_code"]) == (False, code)
        assert scene.world.one("SELECT count(*) AS n FROM proposals").n == 0

    def test_a_private_box_can_not_be_proposed(self, scene: Scene) -> None:
        """INV-8: stock beyond 180 days is private, even if the model names it."""
        private = scene.stock(days_left=200)

        made = scene.tool("propose_reservation", listing_id=private, pickup_day=TODAY)

        assert made["error_code"] == "LISTING_NOT_AVAILABLE"

    def test_a_plan_becomes_one_card_per_pharmacy(self, scene: Scene) -> None:
        """R-RQ6."""
        far = scene.world.make.pharmacy(name="Far Pharmacy", lat=33.95, lon=35.60)
        scene.stock(scene.augmentin)
        scene.stock(scene.concor, pharmacy_id=far)
        plan = scene.tool(
            "plan_basket",
            items=[{"product_id": scene.augmentin}, {"product_id": scene.concor}],
        )["plans"][0]

        made = scene.tool("propose_plan", plan_id=plan["plan_id"])

        assert sorted(card["pharmacy_name"] for card in made["proposals"]) == [
            "Far Pharmacy",
            "Hamra Pharmacy",
        ]
        kinds = scene.world.all("SELECT kind, payload FROM proposals")
        assert {row.kind for row in kinds} == {"reserve_group"}
        assert all(len(row.payload["items"]) == 1 for row in kinds)

    def test_an_unknown_plan_is_refused(self, scene: Scene) -> None:
        assert scene.tool("propose_plan", plan_id="plan-x")["error_code"] == "PLAN_NOT_FOUND"

    @pytest.mark.rows_by_hand
    def test_a_cancel_card_is_for_the_clients_own_reservation(self, scene: Scene) -> None:
        """FA-13: "cancel R-..." for someone else's order finds nothing."""
        mine = scene.world.make.order(client_id=scene.client, ref="R-MYNE22")
        scene.world.make.order(ref="R-THEYRS")
        done = scene.world.make.order(
            client_id=scene.client, ref="R-DANE22", state="PICKED_UP", qty_picked_up=1
        )

        made = scene.tool("propose_cancellation", order_ref="r-myne22")

        proposal = scene.world.one("SELECT * FROM proposals WHERE id = :p", p=made["proposal_id"])
        assert (proposal.kind, proposal.payload["order_id"]) == ("cancel", str(mine))
        assert scene.tool("propose_cancellation", order_ref="R-THEYRS")["error_code"] == "NOT_FOUND"
        assert (
            scene.tool("propose_cancellation", order_ref="R-DANE22")["error_code"]
            == "RESERVATION_NOT_ACTIVE"
        )
        assert done

    def test_the_start_sourcing_card(self, scene: Scene) -> None:
        """R-RQ1: the card holds the request; only the tap creates it."""
        made = scene.tool(
            "prepare_request_summary",
            items=[
                {"product_id": scene.augmentin, "qty": 2, "days_of_use": 7},
                {"product_id": scene.concor, "max_price": {"amount": 10, "currency": "USD"}},
            ],
            alternatives_ok=True,
        )

        proposal = scene.world.one("SELECT * FROM proposals WHERE id = :p", p=made["proposal_id"])
        assert proposal.kind == "request_summary"
        assert proposal.payload["alternatives_ok"] is True
        assert [item["max_price_lbp"] for item in proposal.payload["items"]] == [None, 895_000]
        assert scene.world.one("SELECT count(*) AS n FROM sourcing_requests").n == 0

    def test_no_request_card_outside_request_hours(self, scene: Scene) -> None:
        """R-T3."""
        scene.world.later(hours=12)

        made = scene.tool(
            "prepare_request_summary",
            items=[{"product_id": scene.augmentin}],
            alternatives_ok=False,
        )

        assert made["error_code"] == "OUTSIDE_REQUEST_HOURS"


class TestInARequest:
    """Sourcing mode: the tools work on the request's own thread and items."""

    def test_the_status_lists_each_medicine(self, scene: Scene) -> None:
        request, thread = scene.start_request()

        status = scene.tool("get_request_status", thread, request_id=request)

        assert (status["state"], status["minutes_left"]) == ("OPEN", 360)
        assert [(item["product"], item["state"]) for item in status["items"]] == [
            ("AUGMENTIN 1G", "SEARCHING"),
            ("CONCOR 5MG", "SEARCHING"),
        ]
        assert status["items"][0]["waiting"] == {
            "watching": False,
            "asked_pharmacies": 0,
            "open_offer_count": 0,
        }

    def test_someone_elses_request_does_not_exist(self, scene: Scene) -> None:
        """FA-13, AG-D4: identity comes from the turn, never from the model."""
        other = scene.world.make.request()

        assert scene.tool("get_request_status", request_id=other)["error_code"] == "NOT_FOUND"

    def test_a_plan_card_in_a_request_is_tied_to_its_items(self, scene: Scene) -> None:
        request, thread = scene.start_request()
        scene.stock(scene.augmentin)
        plan = scene.tool("plan_basket", thread, items=[{"product_id": scene.augmentin}])

        scene.tool("propose_plan", thread, plan_id=plan["plans"][0]["plan_id"])

        item = scene.world.one(
            "SELECT id, state FROM request_items WHERE request_id = :r AND position = 1", r=request
        )
        payload = scene.world.one("SELECT payload FROM proposals").payload
        assert payload["items"][0]["request_item_id"] == str(item.id)
        assert item.state == "PROPOSED"

    def test_waiting_for_a_medicine_and_asking_pharmacies(self, scene: Scene) -> None:
        """R-W1, R-E1, R-E8: the agent only learns how many were asked."""
        request, thread = scene.start_request(RequestLine(scene.augmentin))
        scene.stock(days_left=200)  # private: in the early-release zone
        item = scene.world.one("SELECT id FROM request_items WHERE request_id = :r", r=request).id

        claim = scene.tool("open_claim", thread, request_item_id=item)
        again = scene.tool("open_claim", thread, request_item_id=item)
        asked = scene.tool("request_early_release", thread, claim_id=claim["claim_id"])
        asked_again = scene.tool("request_early_release", thread, claim_id=claim["claim_id"])

        assert claim["claim_id"] == again["claim_id"]
        assert claim["ends_display"] == "Tue 16:00"
        assert asked == {"ok": True, "asked": 1, "answers_by_display": "Tue 12:00"}
        assert asked_again == asked
        assert scene.world.one("SELECT count(*) AS n FROM early_release_asks").n == 1
        assert "Hamra" not in str(asked)

    def test_nobody_to_ask(self, scene: Scene) -> None:
        request, thread = scene.start_request(RequestLine(scene.augmentin))
        item = scene.world.one("SELECT id FROM request_items WHERE request_id = :r", r=request).id
        claim = scene.tool("open_claim", thread, request_item_id=item)

        asked = scene.tool("request_early_release", thread, claim_id=claim["claim_id"])

        assert asked == {"ok": True, "asked": 0, "reason": "no_candidates"}

    def test_another_clients_item_or_claim_does_not_exist(self, scene: Scene) -> None:
        _, thread = scene.start_request()
        their_item = scene.world.make.request_item(scene.world.make.request())
        their_claim = scene.world.make.claim()

        assert scene.tool("open_claim", thread, request_item_id=their_item)["error_code"] == (
            "NOT_FOUND"
        )
        assert scene.tool("request_early_release", thread, claim_id=their_claim)["error_code"] == (
            "NOT_FOUND"
        )

    def test_cards_that_relax_or_shrink_the_request(self, scene: Scene) -> None:
        """R-RQ4: proposed by the agent, applied only by a tap."""
        request, thread = scene.start_request(
            RequestLine(scene.augmentin, max_price_lbp=500_000), RequestLine(scene.concor)
        )
        first, second = scene.world.all(
            "SELECT id FROM request_items WHERE request_id = :r ORDER BY position", r=request
        )

        brands = scene.tool(
            "propose_constraint_change", thread, request_id=request, show_other_brands=True
        )
        budget = scene.tool(
            "propose_constraint_change",
            thread,
            request_id=request,
            item_id=first.id,
            max_price={"amount": 800_000, "currency": "LBP"},
        )
        lower = scene.tool(
            "propose_constraint_change",
            thread,
            request_id=request,
            item_id=first.id,
            max_price={"amount": 100_000, "currency": "LBP"},
        )
        both = scene.tool(
            "propose_constraint_change",
            thread,
            request_id=request,
            show_other_brands=True,
            item_id=first.id,
            max_price={"amount": 800_000, "currency": "LBP"},
        )
        removal = scene.tool("propose_remove_item", thread, request_id=request, item_id=second.id)

        payloads = {
            row.id: row.payload for row in scene.world.all("SELECT id, payload FROM proposals")
        }
        assert payloads[uuid.UUID(brands["proposal_id"])]["alternatives_ok"] is True
        assert payloads[uuid.UUID(budget["proposal_id"])]["item_max_prices"] == {
            str(first.id): 800_000
        }
        assert lower["error_code"] == "NOTHING_TO_CHANGE"
        assert both["error_code"] == "INVALID_ARGUMENTS"
        assert payloads[uuid.UUID(removal["proposal_id"])]["request_item_id"] == str(second.id)
        # Nothing changed yet.
        row = scene.world.one(
            "SELECT alternatives_ok FROM sourcing_requests WHERE id = :r", r=request
        )
        assert row.alternatives_ok is False

    def test_a_follow_up_is_bounded(self, scene: Scene) -> None:
        """N-39, FA-21: inside the window, one pending, four per request."""
        _, thread = scene.start_request()

        first = scene.tool("schedule_followup", thread, in_minutes=40)
        scene.world.later(hours=2)
        too_late = scene.tool("schedule_followup", thread, in_minutes=300)
        too_soon = scene.tool("schedule_followup", thread, in_minutes=5)
        for _ in range(3):
            scene.tool("schedule_followup", thread, in_minutes=60)
        fifth = scene.tool("schedule_followup", thread, in_minutes=60)

        assert first == {"ok": True, "followup_display": "Tue 10:40"}
        assert too_late["error_code"] == "FOLLOWUP_NOT_ALLOWED"
        assert too_soon["error_code"] == "INVALID_ARGUMENTS"
        assert fifth["error_code"] == "FOLLOWUP_NOT_ALLOWED"
        # A new follow-up replaced the earlier one: there is only ever one.
        assert scene.conversation(thread).followup_at == scene.world.clock.now() + timedelta(
            minutes=60
        )


class TestActingInAChat:
    def test_a_watch_is_created_once(self, scene: Scene) -> None:
        """R-W1, R-AG6."""
        made = scene.tool("create_watch", product_id=scene.augmentin, qty=2, days_of_use=7)
        again = scene.tool("create_watch", product_id=scene.augmentin)

        claim = scene.world.one("SELECT * FROM claims")
        assert made == {
            "ok": True,
            "watch_id": str(claim.id),
            "ends_display": "Tue 16:00",
            "already_watching": False,
        }
        assert (claim.kind, claim.source, claim.qty, claim.days_of_use) == (
            "WATCH",
            "assistant",
            2,
            7,
        )
        assert again == made | {"already_watching": True}

    def test_no_watch_at_night(self, scene: Scene) -> None:
        scene.world.later(hours=12)

        assert scene.tool("create_watch", product_id=scene.augmentin)["error_code"] == (
            "OUTSIDE_REQUEST_HOURS"
        )

    def test_an_escalation_holds_no_personal_details_and_is_written_once(
        self, scene: Scene
    ) -> None:
        """SM-9, R-AG6: a turn that is retried doesn't escalate twice."""
        summary = "Client Rami says it is urgent, call 70 123 456. Glucophage missing."

        first = scene.tool("escalate", reason="emergency_claim", summary=summary)
        again = scene.tool("escalate", reason="emergency_claim", summary=summary)
        more = scene.tool("escalate", reason="client_asked_human", summary="Wants a person.")

        row = scene.world.one("SELECT * FROM escalations")
        assert row.summary == "Client [name] says it is urgent, call [phone]. Glucophage missing."
        assert (first["appended"], again["appended"], more["appended"]) == (False, True, True)
        assert [note["reason"] for note in row.notes] == ["client_asked_human"]
        assert scene.tool_turn().state.escalated is True

    @pytest.mark.rows_by_hand
    def test_the_clients_own_reservations(self, scene: Scene) -> None:
        scene.world.make.order(client_id=scene.client, ref="R-MYNE22")
        scene.world.make.order(ref="R-THEYRS")

        found = scene.tool("get_reservations")

        assert [(r["ref"], r["state"]) for r in found["reservations"]] == [("R-MYNE22", "RESERVED")]
