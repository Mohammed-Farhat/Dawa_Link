"""What a card shows on the screen, and what the model reads of it (B#5, B#31, A#37).

The model reads a card as the tool's answer: its title and its lines, written as the
model has always been given them (`agent/display.py`). The screen gets more of the same
box: the saving, whether it lasts the client's days, the opening hours on the pickup day,
the trip in the website's words. **What the model reads must not change by a single
character**, so that the saved evaluation runs stay comparable: the first tests pin it.
"""

import json
import re
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import text

from dawalink.agent.tools import for_mode, run_tool
from dawalink.db.models import Proposal
from dawalink.services.requests import RequestLine
from tests.agent.conftest import Scene
from tests.agent.test_other_brand import agreed, clavox, found_as_another_brand  # noqa: F401
from tests.db.factories import TODAY

DAY = timedelta(days=1)

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
REQUEST_REF = re.compile(r"Q-[0-9A-Z]{6}")


def model_reads(
    scene: Scene, name: str, conversation: uuid.UUID | None = None, **arguments: Any
) -> str:
    """The tool's answer exactly as the model reads it, its random IDs blanked."""
    turn = scene.tool_turn(conversation)
    sent = json.loads(json.dumps(arguments, default=str))
    outcome = run_tool(turn, for_mode(turn.mode), name, sent)
    scene.world.session.expire_all()
    return REQUEST_REF.sub("Q-<ref>", UUID.sub("<id>", outcome.as_json()))


def stored_card(scene: Scene) -> dict[str, Any]:
    """The newest card's stored text and facts."""
    (proposal,) = (
        scene.world.session.execute(
            text("SELECT id FROM proposals ORDER BY created_at DESC, id LIMIT 1")
        )
        .scalars()
        .all()
    )
    return dict(scene.world.session.get_one(Proposal, proposal).payload["card"])


class TestWhatTheModelReads:
    """Pinned before the screen got its own facts: the same text, to the character."""

    def test_a_reserve_card(self, scene: Scene) -> None:
        box = scene.stock(price_override_lbp=700_000)
        scene.tool("find_options", product_ids=[scene.augmentin])

        read = model_reads(
            scene,
            "propose_reservation",
            listing_id=box,
            qty=2,
            pickup_day=TODAY,
            days_of_use=7,
            recommended=True,
        )

        assert read == PINNED_RESERVE

    def test_a_reserve_card_far_away(self, scene: Scene) -> None:
        """Where the screen's words differ most: hours, a walk nobody would make."""
        scene.routing.minutes = 75
        box = scene.stock(price_override_lbp=700_000)
        scene.tool("find_options", product_ids=[scene.augmentin])

        read = model_reads(scene, "propose_reservation", listing_id=box, pickup_day=TODAY)

        assert read == PINNED_RESERVE_FAR

    def test_a_reserve_card_with_a_straight_line_estimate(self, scene: Scene) -> None:
        scene.routing.fail = True
        box = scene.stock(price_override_lbp=700_000)
        scene.tool("find_options", product_ids=[scene.augmentin])

        read = model_reads(scene, "propose_reservation", listing_id=box, pickup_day=TODAY)

        assert read == PINNED_RESERVE_STRAIGHT

    def test_a_plan(self, scene: Scene) -> None:
        far = scene.world.make.pharmacy(name="Far Pharmacy", lat=33.95, lon=35.60)
        scene.stock(scene.augmentin, price_override_lbp=700_000)
        scene.stock(scene.concor, pharmacy_id=far, price_override_lbp=500_000)
        plan = scene.tool(
            "plan_basket",
            items=[{"product_id": scene.augmentin, "qty": 2}, {"product_id": scene.concor}],
        )["plans"][0]

        read = model_reads(scene, "propose_plan", plan_id=plan["plan_id"])

        assert read in PINNED_PLAN

    def test_another_brand(self, scene: Scene, clavox: uuid.UUID) -> None:  # noqa: F811
        box = scene.stock(clavox, price_override_lbp=600_000)
        agreed(scene)
        found_as_another_brand(scene, clavox)

        read = model_reads(
            scene, "show_other_brand", listing_id=box, instead_of_product_id=scene.augmentin
        )

        assert read == PINNED_OTHER_BRAND

    def test_a_start_sourcing_card(self, scene: Scene) -> None:
        read = model_reads(
            scene,
            "prepare_request_summary",
            items=[
                {"product_id": scene.augmentin, "qty": 2, "days_of_use": 7},
                {"product_id": scene.concor, "max_price": {"amount": 10, "currency": "USD"}},
            ],
            alternatives_ok=True,
        )

        assert read == PINNED_START_SOURCING

    def test_a_card_that_raises_a_budget(self, scene: Scene) -> None:
        request, thread = scene.start_request(RequestLine(scene.augmentin, max_price_lbp=500_000))
        (item,) = scene.world.all("SELECT id FROM request_items WHERE request_id = :r", r=request)

        read = model_reads(
            scene,
            "propose_constraint_change",
            thread,
            request_id=request,
            item_id=item.id,
            max_price={"amount": 800_000, "currency": "LBP"},
        )

        assert read == PINNED_RAISE_BUDGET


# Recorded from the code before the screen got its own facts (2026-11-19).
PINNED_START_SOURCING = (
    '{"ok":true,"proposal_id":"<id>","preview":{"title":"Find these medicines for me",'
    '"lines":["AUGMENTIN 1G x 2: for 7 days","CONCOR 5MG x 1: for 1 day, up to 895,000 LBP '
    '(about $10.00)","Tell me about other brands: yes","DawaLink keeps searching for: 6 hours"]}}'
)
PINNED_RAISE_BUDGET = (
    '{"ok":true,"proposal_id":"<id>","preview":{"title":"Raise the budget?","lines":['
    '"Request: Q-<ref>","Medicine: AUGMENTIN 1G","Budget now: 500,000 LBP (about $5.59)",'
    '"New budget: 800,000 LBP (about $8.94)"]}}'
)
PINNED_RESERVE = (
    '{"ok":true,"proposal_id":"<id>","preview":{"title":"AUGMENTIN 1G at Hamra Pharmacy",'
    '"lines":["Pharmacy: Hamra Pharmacy, Beirut","Quantity: 2 packs",'
    '"At the counter: 1,400,000 LBP (about $15.64)","Pick up: Tue 20 Oct",'
    '"Expires: Sat 19 Dec 2026","Travel: 12 min by car · 60 min on foot"]}}'
)
PINNED_RESERVE_FAR = (
    '{"ok":true,"proposal_id":"<id>","preview":{"title":"AUGMENTIN 1G at Hamra Pharmacy",'
    '"lines":["Pharmacy: Hamra Pharmacy, Beirut","Quantity: 1 pack",'
    '"At the counter: 700,000 LBP (about $7.82)","Pick up: Tue 20 Oct",'
    '"Expires: Sat 19 Dec 2026","Travel: 75 min by car · 375 min on foot"]}}'
)
PINNED_RESERVE_STRAIGHT = (
    '{"ok":true,"proposal_id":"<id>","preview":{"title":"AUGMENTIN 1G at Hamra Pharmacy",'
    '"lines":["Pharmacy: Hamra Pharmacy, Beirut","Quantity: 1 pack",'
    '"At the counter: 700,000 LBP (about $7.82)","Pick up: Tue 20 Oct",'
    '"Expires: Sat 19 Dec 2026","Travel: about 1 min by car · about 3 min on foot"]}}'
)
# Two pharmacies at the same road time come in either order: both orders are this text.
_HAMRA = '{"proposal_id":"<id>","pharmacy_name":"Hamra Pharmacy","items":["AUGMENTIN 1G x 2"]}'
_FAR = '{"proposal_id":"<id>","pharmacy_name":"Far Pharmacy","items":["CONCOR 5MG x 1"]}'
PINNED_PLAN = {
    '{"ok":true,"proposals":[' + first + "," + second + '],"refused":[]}'
    for first, second in ((_HAMRA, _FAR), (_FAR, _HAMRA))
}
PINNED_OTHER_BRAND = (
    '{"ok":true,"proposal_id":"<id>","preview":{"title":"Another brand: CLAVOX 1G at Hamra '
    'Pharmacy","lines":["Instead of: AUGMENTIN 1G","It has: the same ingredient, strength '
    'and form","Pharmacy: Hamra Pharmacy, Beirut","Price: 600,000 LBP (about $6.70)",'
    '"Expires: Sat 19 Dec 2026","Travel: 12 min by car · 60 min on foot","Before you go: '
    'Call the pharmacy and ask the pharmacist if this brand suits you"]}}'
)


class TestWhatTheScreenShows:
    """B#5: a card shows what search shows of the same box, written by code (R-AG7)."""

    def test_a_reserve_card_has_the_saving_the_fit_and_the_days_hours(self, scene: Scene) -> None:
        box = scene.stock(price_override_lbp=700_000)
        scene.tool("find_options", product_ids=[scene.augmentin])

        scene.tool("propose_reservation", listing_id=box, qty=2, pickup_day=TODAY, days_of_use=7)

        card = stored_card(scene)
        assert card["box"] == {
            "price_lbp": 1_400_000,
            "saving_lbp": 600_000,  # the public price is 1,000,000
            "expiry_date": (TODAY + DAY * 60).isoformat(),
            "days_of_use": 7,
            "hours_on_pickup_day": "08:00-21:00",
            "travel": {"car_min": 12, "walk_min": 60, "km": 4.2, "source": "road"},
        }
        # The price, the expiry and the trip are the box's: the screen's lines don't
        # say them twice.
        assert card["screen_lines"] == [
            ["Pharmacy", "Hamra Pharmacy, Beirut"],
            ["Quantity", "2 packs"],
            ["Pick up", "Tue 20 Oct"],
        ]

    def test_a_box_at_the_public_price_saves_nothing(self, scene: Scene) -> None:
        box = scene.stock(price_override_lbp=1_000_000)
        scene.tool("find_options", product_ids=[scene.augmentin])

        scene.tool("propose_reservation", listing_id=box, pickup_day=TODAY)

        assert stored_card(scene)["box"]["saving_lbp"] == 0

    def test_a_plan_card_has_its_total_its_saving_and_the_soonest_expiry(
        self, scene: Scene
    ) -> None:
        scene.stock(scene.augmentin, price_override_lbp=700_000, days_left=90)
        scene.stock(scene.concor, price_override_lbp=500_000, days_left=40)
        plan = scene.tool(
            "plan_basket",
            items=[
                {"product_id": scene.augmentin, "qty": 2, "days_of_use": 5},
                {"product_id": scene.concor, "days_of_use": 5},
            ],
        )["plans"][0]

        scene.tool("propose_plan", plan_id=plan["plan_id"])

        card = stored_card(scene)
        assert card["box"] == {
            "price_lbp": 1_900_000,
            "saving_lbp": 900_000,
            "expiry_date": (TODAY + DAY * 40).isoformat(),
            "days_of_use": 5,
            "hours_on_pickup_day": "08:00-21:00",
            "travel": None,
        }
        # B#31: the dollars as the website rounds them, one decimal.
        assert card["screen_lines"] == [
            ["AUGMENTIN 1G x 2", "1,400,000 LBP (about $15.6)"],
            ["CONCOR 5MG x 1", "500,000 LBP (about $5.6)"],
            ["Pick up", "Tue 20 Oct"],
        ]
        # The model's own copy is as it was.
        assert ["AUGMENTIN 1G x 2", "1,400,000 LBP (about $15.64)"] in card["lines"]

    def test_boxes_for_different_days_each_last_their_own(self, scene: Scene) -> None:
        scene.stock(scene.augmentin, price_override_lbp=700_000)
        scene.stock(scene.concor, price_override_lbp=500_000)
        plan = scene.tool(
            "plan_basket",
            items=[
                {"product_id": scene.augmentin, "days_of_use": 5},
                {"product_id": scene.concor, "days_of_use": 10},
            ],
        )["plans"][0]

        scene.tool("propose_plan", plan_id=plan["plan_id"])

        assert stored_card(scene)["box"]["days_of_use"] is None

    def test_another_brand_has_no_pickup_day_and_so_no_hours(
        self,
        scene: Scene,
        clavox: uuid.UUID,  # noqa: F811
    ) -> None:
        box = scene.stock(clavox, price_override_lbp=600_000)
        agreed(scene)
        found_as_another_brand(scene, clavox)

        scene.tool("show_other_brand", listing_id=box, instead_of_product_id=scene.augmentin)

        card = stored_card(scene)
        assert card["box"]["price_lbp"] == 600_000
        assert card["box"]["hours_on_pickup_day"] is None
        assert [label for label, _ in card["screen_lines"]] == [
            "Instead of",
            "It has",
            "Pharmacy",
            "Before you go",
        ]

    def test_the_trip_is_stored_as_minutes_for_the_website_to_word(self, scene: Scene) -> None:
        """A#37: the website writes "1 h 15 min by car" and leaves out a 6-hour walk."""
        scene.routing.minutes = 75
        box = scene.stock(price_override_lbp=700_000)
        scene.tool("find_options", product_ids=[scene.augmentin])

        scene.tool("propose_reservation", listing_id=box, pickup_day=TODAY)

        assert stored_card(scene)["box"]["travel"] == {
            "car_min": 75,
            "walk_min": 375,
            "km": 4.2,
            "source": "road",
        }

    def test_a_start_sourcing_card_names_the_strength_and_rounds_the_dollars(
        self, scene: Scene
    ) -> None:
        """B#31, and the strength the client asked for when the Ministry's name lacks it."""
        bare = scene.world.make.product(moph_name="CONCOR", search_name="concor", dosage_text="5mg")

        scene.tool(
            "prepare_request_summary",
            items=[{"product_id": bare, "max_price": {"amount": 10, "currency": "USD"}}],
            alternatives_ok=False,
        )

        card = stored_card(scene)
        assert card["screen_lines"][0] == [
            "CONCOR 5mg x 1",
            "for 1 day, up to 895,000 LBP (about $10.0)",
        ]
        assert card["lines"][0] == ["CONCOR x 1", "for 1 day, up to 895,000 LBP (about $10.00)"]

    def test_a_budget_card_rounds_the_dollars_as_the_website(self, scene: Scene) -> None:
        request, thread = scene.start_request(RequestLine(scene.augmentin, max_price_lbp=500_000))
        (item,) = scene.world.all("SELECT id FROM request_items WHERE request_id = :r", r=request)

        scene.tool(
            "propose_constraint_change",
            thread,
            request_id=request,
            item_id=item.id,
            max_price={"amount": 800_000, "currency": "LBP"},
        )

        lines = dict(stored_card(scene)["screen_lines"])
        assert (lines["Budget now"], lines["New budget"]) == (
            "500,000 LBP (about $5.6)",
            "800,000 LBP (about $8.9)",
        )
