"""Tiny hand-made days played through the engine, with the search baseline and with the
policy that has no AI (docs/08 E2).

Three pharmacies and a few clients in Beirut, an invented medicine, and the real services
underneath. Each test is one situation a simulated day is made of.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any

import pytest

from dawalink.agent.llm import ModelReply, Prompt, ToolCall
from dawalink.agent.prompts import PROMPT_VERSION
from dawalink.sim import client as sim_client
from dawalink.sim import engine, measure, save
from dawalink.sim import world as sim_world
from dawalink.sim.contenders import rules
from dawalink.sim.contenders.rules import RulesModel
from dawalink.sim.contenders.search_baseline import SearchBaseline
from dawalink.sim.contenders.with_requests import WithRequests
from dawalink.sim.engine import Contender, Sim
from dawalink.sim.measure import NeedResult
from dawalink.sim.params import Params
from dawalink.sim.scenario import Arrival, Line, Need, Scenario
from dawalink.sim.world import SimClient, SimPharmacy
from dawalink.sim.world import World as SimWorld
from tests.db.factories import NOW, TODAY
from tests.services.conftest import World

OPEN_LATE, CLOSES_AT_17 = 2, 4  # indexes of `sim_world.SCHEDULES`
# The clock of the tests starts at 10:00 in Beirut, on a Tuesday.
# No box is gone by chance: a test that wants one says so.
DAY = Params(day=TODAY, last_request=time(11, 0), tick=timedelta(minutes=30), not_available=0.0)


def pharmacy(n: int, *, schedule: int = OPEN_LATE, lat: float = 33.896) -> SimPharmacy:
    return SimPharmacy(
        n=n, district="Beirut", lat=lat, lon=35.483, schedule=schedule, pickup_days=2
    )


def client(n: int, **situation: Any) -> SimClient:
    values: dict[str, Any] = {"has_car": True, "free": "any", "language": "english"}
    return SimClient(
        n=n, district="Beirut", lat=33.896, lon=35.483, preference=None, **(values | situation)
    )


@dataclass
class Town:
    """A small simulated world inside the test's transaction."""

    world: World
    land: SimWorld
    medicine: uuid.UUID
    brand: uuid.UUID | None = None  # another brand of the medicine, when a test makes one

    def stock(
        self,
        pharmacy_n: int,
        units: int = 2,
        days_left: int = 60,
        product: uuid.UUID | None = None,
    ) -> uuid.UUID:
        place = next(p for p in self.land.pharmacies if p.n == pharmacy_n)
        return self.world.make.item(  # type: ignore[no-any-return]
            pharmacy_id=place.id,
            product_id=product or self.medicine,
            days_left=days_left,
            qty_on_hand=units,
        )

    def another_brand(self) -> uuid.UUID:
        """Gives the medicine a second brand: the same composition, another name."""
        key = "testamol=5mg | tablet | T01"
        with self.world.as_owner():
            self.world.connection.exec_driver_sql(
                "UPDATE products SET equivalence_key = %s WHERE id = %s", (key, self.medicine)
            )
        self.brand = self.world.make.product(equivalence_key=key)
        return self.brand

    def need(self, client_n: int, *, qty: int = 1, minutes: int = 5, **more: Any) -> Need:
        who = next(c for c in self.land.clients if c.n == client_n)
        values: dict[str, Any] = {
            "hears_other_brands": False,
            "pickup_in_days": 0,
            "says": None,
            "later": None,
        }
        return Need(
            n=client_n,
            at=NOW + timedelta(minutes=minutes),
            client=who,
            lines=(Line(self.medicine, qty, days_of_use=5, budget_share=None),),
            **(values | more),
        )

    def play(
        self,
        *needs: Need,
        arrivals: tuple[Arrival, ...] = (),
        params: Params = DAY,
        contender: Contender | None = None,
    ) -> tuple[Sim, list[NeedResult]]:
        products = [self.medicine, *([self.brand] if self.brand else [])]
        sim = Sim(
            seed=1,
            params=params,
            world=self.land,
            scenario=Scenario(needs, arrivals),
            sessions=self.world.sessions(),
            clock=self.world.clock,
            prices=dict.fromkeys(products, 1_000_000),
            medicine_of=dict.fromkeys(products, f"medicine:{self.medicine}"),
            # A product's id is new in every test: chance is drawn from its place here.
            code_of={product: place for place, product in enumerate(products, start=1)},
        )
        engine.play(sim, contender or SearchBaseline())
        self.world.session.expire_all()
        return sim, measure.results(sim)

    def orders(self) -> list[Any]:
        return self.world.all("SELECT * FROM orders ORDER BY reserved_at, created_at")

    def thread(self) -> list[tuple[str, str]]:
        """What was written in the request threads: `(who, text)`, oldest first."""
        rows = self.world.all(
            "SELECT author, text_redacted FROM chat_messages WHERE kind = 'text' ORDER BY id"
        )
        return [(row.author, row.text_redacted) for row in rows]


@pytest.fixture
def town(world: World) -> Town:
    land = SimWorld(
        # 1 and 5 are where the clients are; 2 is a kilometre north; 9 is ten kilometres north.
        pharmacies=(
            pharmacy(1),
            pharmacy(2, lat=33.905),
            pharmacy(5, schedule=CLOSES_AT_17),
            pharmacy(9, lat=33.99),
            pharmacy(8, lat=34.40),  # another city: more than 30 minutes by car
        ),
        clients=(client(1), client(2), client(3, free="after_18"), client(4, has_car=False)),
    )
    medicine = world.make.product()
    with world.as_owner():
        sim_world.populate(world.connection, land, seed=1, now=NOW, stock=False)
    return Town(world, land, medicine)


class TestASimulatedDay:
    def test_a_need_is_searched_reserved_and_picked_up(self, town: Town) -> None:
        town.stock(1)

        sim, (result,) = town.play(town.need(1))

        (order,) = town.orders()
        (decision,) = sim.decisions.values()
        assert (order.state, order.source, order.qty_picked_up) == ("PICKED_UP", "search", 1)
        assert (result.units_wanted, result.units_secured, result.fulfilled) == (1, 1, True)
        assert (result.minutes_to_secure, result.taps, result.no_shows) == (0, 1, 0)
        assert (decision.works, decision.pharmacy_n, decision.other_brand) == (True, 1, False)
        assert result.boxes_that_dont_last == 0

    def test_two_units_can_come_from_two_pharmacies(self, town: Town) -> None:
        town.stock(1, units=1)
        town.stock(2, units=1)

        _, (result,) = town.play(town.need(1, qty=2))

        assert {order.pharmacy_id for order in town.orders()} == {
            town.land.pharmacies[0].id,
            town.land.pharmacies[1].id,
        }
        assert (result.units_secured, result.reservations) == (2, 2)

    def test_a_box_that_was_already_gone_is_searched_for_once_more_and_no_more(
        self, town: Town
    ) -> None:
        """B0 searches once more after "not available" (docs/08 E2). Here every box is gone."""
        town.stock(1, units=1)
        town.stock(2, units=1)

        _, (result,) = town.play(town.need(1), params=DAY.but(not_available=1.0))

        assert [order.state for order in town.orders()] == ["NOT_AVAILABLE", "NOT_AVAILABLE"]
        assert (result.units_secured, result.fulfilled) == (0, False)
        assert town.world.all("SELECT 1 FROM claims") == []  # the second search sets no watch

    def test_nothing_listed_then_a_new_box_becomes_an_offer_the_client_accepts(
        self, town: Town
    ) -> None:
        new_box = Arrival(
            at=NOW + timedelta(minutes=40),
            pharmacy_n=1,
            product_id=town.medicine,
            days_left=90,
            units=1,
        )

        _, (result,) = town.play(
            town.need(1), arrivals=(new_box,), params=DAY.but(accepts_offer=1.0)
        )

        (order,) = town.orders()
        (watch,) = town.world.all("SELECT kind, source, state FROM claims")
        assert tuple(watch) == ("WATCH", "search", "FULFILLED")
        assert (order.source, order.state) == ("watch", "PICKED_UP")
        assert result.units_secured == 1
        assert 40 <= (result.minutes_to_secure or 0) <= 80

    def test_an_offer_the_client_doesnt_want_goes_back(self, town: Town) -> None:
        new_box = Arrival(NOW + timedelta(minutes=40), 1, town.medicine, days_left=90, units=1)

        _, (result,) = town.play(
            town.need(1), arrivals=(new_box,), params=DAY.but(accepts_offer=0.0)
        )

        assert [order.state for order in town.orders()] == ["OFFER_DECLINED"]
        assert result.units_secured == 0

    def test_first_come_first_served_between_two_clients(self, town: Town) -> None:
        """R-PRI, played: one box, two clients, the earlier one gets it."""
        town.stock(1, units=1)

        _, (first, second) = town.play(town.need(1, minutes=5), town.need(2, minutes=6))

        assert (first.units_secured, second.units_secured) == (1, 0)

    def test_a_client_only_reserves_where_they_can_really_go(self, town: Town) -> None:
        """The careful person of B0 knows their own free hours: they finish work at 18:00."""
        town.stock(5)  # the nearest, but closed when this client is free
        town.stock(2)

        sim, (result,) = town.play(town.need(3))

        (decision,) = sim.decisions.values()
        assert (decision.pharmacy_n, decision.works) == (2, True)
        assert (result.units_secured, result.cant_work, result.extra_minutes) == (1, 0, 0)

    def test_a_box_that_doesnt_last_the_days_of_use_is_never_reserved(self, town: Town) -> None:
        """R-F1: 5 days of use, a box that expires in 2."""
        town.stock(1, days_left=2)

        _, (result,) = town.play(town.need(1))

        assert town.orders() == []
        assert (result.units_secured, result.boxes_that_dont_last) == (0, 0)


class TestTheDaysSummary:
    def test_fulfillment_is_units_secured_over_units_wanted(self, town: Town) -> None:
        town.stock(1, units=1)

        _, needs = town.play(town.need(1, qty=2), town.need(2, minutes=30))

        summary = measure.summary(needs)
        assert (summary["units_wanted"], summary["units_secured"]) == (3, 1)
        assert summary["fulfillment"] == round(1 / 3, 4)
        assert summary["needs_fulfilled"] == 0.0
        assert summary["boxes_that_dont_last"] == 0

    def test_a_day_of_the_past_is_not_used(self) -> None:
        assert date(2026, 11, 16).weekday() == 0  # the simulated day is a Monday


def no_ai() -> WithRequests:
    return WithRequests("rules", RulesModel())


def sure(**changes: Any) -> Params:
    """A day where every simulated person does the likely thing."""
    return DAY.but(taps_card=1.0, accepts_offer=1.0, **changes)


class TestTheNoAiPolicy:
    """B1: each need is a sourcing request, worked by fixed rules through the agent's own
    runtime (turns, tools, guards, records)."""

    def test_a_request_is_planned_shown_tapped_and_picked_up(self, town: Town) -> None:
        town.stock(1)

        sim, (result,) = town.play(town.need(1), contender=no_ai(), params=sure())

        (order,) = town.orders()
        request = town.world.one("SELECT state, outcome FROM sourcing_requests")
        turns = measure.turns(sim)
        assert (order.state, order.source) == ("PICKED_UP", "request")
        assert tuple(request) == ("CLOSED", "FULFILLED")
        assert (result.units_secured, result.taps, result.messages) == (1, 2, 0)
        # The rules never need a correction or a fixed text: a run with one is not B1.
        assert (turns["turns"], turns["turns_not_ok"], turns["turns_with_a_guard"]) == (1, 0, 0)
        assert turns["tool_errors"] == 0

    def test_what_nobody_lists_is_asked_for_and_a_pharmacy_releases_it(self, town: Town) -> None:
        """The box is 200 days from expiry: private, but a pharmacy may release it (R-E)."""
        town.stock(1, days_left=200)

        sim, (result,) = town.play(
            town.need(1), contender=no_ai(), params=sure(answers_ask=1.0, accepts_ask=1.0)
        )

        (order,) = town.orders()
        (ask,) = town.world.all("SELECT state FROM early_release_asks")
        assert (ask.state, order.source, order.state) == ("ACCEPTED", "early_release", "PICKED_UP")
        assert order.price_snapshot_lbp == 750_000  # 25% under the public price
        assert result.units_secured == 1
        assert measure.turns(sim)["turns_not_ok"] == 0

    def test_a_pharmacy_that_keeps_its_box_leaves_the_client_without(self, town: Town) -> None:
        town.stock(1, days_left=200)

        _, (result,) = town.play(
            town.need(1), contender=no_ai(), params=sure(answers_ask=1.0, accepts_ask=0.0)
        )

        asks = town.world.all("SELECT state, decline_reason FROM early_release_asks")
        request = town.world.one("SELECT state, outcome FROM sourcing_requests")
        assert [tuple(ask) for ask in asks] == [("DECLINED", "keeping_it")]
        assert tuple(request) == ("CLOSED", "UNFULFILLED")
        assert result.units_secured == 0

    def test_a_client_who_can_only_go_tomorrow_says_so_and_is_understood(
        self, town: Town, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A keyword the rules know ("tomorrow"): the next card is for the next day."""
        monkeypatch.setitem(
            sim_client.WORDS["only_tomorrow"], "english", ("I can only go tomorrow",)
        )
        town.stock(1)

        _sim, (result,) = town.play(
            town.need(1, pickup_in_days=1), contender=no_ai(), params=sure()
        )

        (order,) = town.orders()
        assert ("client", "I can only go tomorrow") in town.thread()
        assert (order.state, order.pickup_day) == ("RESERVED", TODAY + timedelta(days=1))
        assert (result.units_secured, result.messages) == (1, 1)
        assert (result.unusable_cards, result.unusable_after_told) == (1, 0)

    def test_words_no_keyword_knows_are_not_understood(
        self, town: Town, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same client, other words: the rules show the same day again. This is what a
        language model is for, and what the comparison with the agent measures."""
        monkeypatch.setitem(
            sim_client.WORDS["only_tomorrow"], "english", ("I can't make it today",)
        )
        town.stock(1)

        _, (result,) = town.play(town.need(1, pickup_in_days=1), contender=no_ai(), params=sure())

        assert town.orders() == []
        assert (result.units_secured, result.messages) == (0, 1)  # they say it once
        assert (result.unusable_cards, result.unusable_after_told) == (2, 1)

    def test_a_client_without_a_car_never_taps_a_pharmacy_too_far_to_walk_to(
        self, town: Town
    ) -> None:
        town.stock(9)  # the only box is ten kilometres away

        _, (result,) = town.play(town.need(4), contender=no_ai(), params=sure())

        assert town.orders() == []
        assert [who for who, _ in town.thread()].count("client") == 1
        assert result.unusable_cards >= 1

    def test_another_brand_is_shown_at_the_last_hour_and_reserved_when_the_client_asks(
        self, town: Town
    ) -> None:
        """R-C10 (BLD-D17), played to the end: nothing of the medicine itself, another brand
        nearby. The client is shown it, asks for it in their own message, and only then
        gets a card to reserve it."""
        brand = town.another_brand()
        town.stock(1, product=brand)

        sim, (result,) = town.play(
            town.need(1, hears_other_brands=True),
            contender=no_ai(),
            # One hour is left when the brand is shown: this client answers quickly.
            params=sure(
                other_brand_reserve=1.0, tick=timedelta(minutes=5), react_after_min=(5, 10)
            ),
        )

        (order,) = town.orders()
        kinds = [
            row.kind for row in town.world.all("SELECT kind FROM proposals ORDER BY created_at")
        ]
        asked = [text for who, text in town.thread() if who == "client"]
        assert kinds == ["other_brand", "reserve"]
        assert len(asked) == 1
        assert asked[0].startswith("I asked the pharmacist")
        assert (order.product_id, order.state) == (brand, "PICKED_UP")
        assert (result.units_secured, result.other_brand_units) == (1, 1)
        assert measure.turns(sim)["turns_not_ok"] == 0

    def test_a_client_who_never_agreed_is_asked_before_any_brand_is_shown(self, town: Town) -> None:
        brand = town.another_brand()
        town.stock(1, product=brand)

        town.play(
            town.need(1, hears_other_brands=False),
            contender=no_ai(),
            params=sure(
                other_brand_reserve=0.0,
                other_brand_keep_looking=0.0,
                tick=timedelta(minutes=5),
                react_after_min=(5, 10),
            ),
        )

        kinds = [
            row.kind for row in town.world.all("SELECT kind FROM proposals ORDER BY created_at")
        ]
        said = [text for who, text in town.thread() if who == "client"]
        assert kinds == ["constraint_change", "other_brand"]
        assert said == ["Ok, thank you"]
        assert town.orders() == []


class OnlyLooking:
    """A stand-in for a language model: whatever happens, it says it is looking."""

    name = "only-looking"

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        return ModelReply(text="", tool_calls=(ToolCall("t1", "reply", {"text": "I'm looking."}),))


class TestTheAgentsSeat:
    """A (docs/08 E2): the same contender as the no-AI policy, with a model in the seat."""

    def test_any_model_can_sit_there_and_the_day_is_saved(self, town: Town, tmp_path: Path) -> None:
        town.stock(1)
        seat = WithRequests("agent", OnlyLooking(), tracer=save.FileTracer(tmp_path))

        sim, results = town.play(town.need(1), contender=seat, params=sure())
        save.write(
            tmp_path,
            contender="agent",
            model="only-looking",
            seed=1,
            params=sure(),
            summary=measure.summary(results),
            needs=measure.as_rows(results),
            said=save.threads(sim),
            more={"turns": measure.turns(sim)},
        )

        def lines(name: str) -> list[dict[str, Any]]:
            text = (tmp_path / name).read_text(encoding="utf-8")
            return [json.loads(line) for line in text.splitlines()]

        turns, threads, needs = lines("turns.jsonl"), lines("threads.jsonl"), lines("needs.jsonl")
        config = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
        summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
        assert results[0].units_secured == 0  # it never showed a card
        assert turns
        assert all(turn["output"]["text"] == "I'm looking." for turn in turns)
        assert {"generation"} <= {span["kind"] for turn in turns for span in turn["spans"]}
        assert ("agent", "I'm looking.") in [(row["author"], row["text"]) for row in threads]
        assert len(needs) == 1
        assert (config["model"], config["prompt_version"]) == ("only-looking", PROMPT_VERSION)
        assert summary["turns"]["turns"] == len(turns)
        # What is saved is what the model saw: never where anybody is (INV-24).
        everything = "".join(file.read_text(encoding="utf-8") for file in tmp_path.iterdir())
        assert "33.89" not in everything
        assert "35.48" not in everything


class TestRoomForEarlyRelease:
    def test_a_private_box_nearby_is_room_and_a_listed_or_distant_one_is_not(
        self, town: Town
    ) -> None:
        """What the simulated world leaves for the agent's asks, whoever plays the day."""
        town.stock(1, units=1, days_left=200)  # private, in the early-release zone, nearby
        town.stock(8, units=5, days_left=200)  # the same, but more than 30 minutes away
        town.stock(2, units=1, days_left=300)  # too far from its expiry to be asked for

        sim, _ = town.play(town.need(1, qty=2), town.need(2, minutes=10))

        assert measure.room_for_early_release(sim) == {
            "units_missing": 3,
            # The one nearby box could go to either client, never to both; here each client
            # is counted on their own, so it is an upper bound.
            "early_release_could_serve": 2,
        }


class TestTheSameDayForEveryone:
    def test_the_same_box_is_gone_for_both_contenders(self, town: Town) -> None:
        """A chance outcome belongs to the box and the client, never to who reserved it."""
        gone = DAY.but(not_available=1.0, taps_card=1.0)
        town.stock(1, units=1)

        town.play(town.need(1), contender=SearchBaseline(), params=gone)
        town.play(town.need(2), contender=no_ai(), params=gone)

        assert [order.state for order in town.orders()] == ["NOT_AVAILABLE"]


class AsksFirst:
    """A stand-in model that asks two things and proposes nothing."""

    name = "asks-first"

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        text = "Do you have a car, or will you go on foot? And which day will you come?"
        return ModelReply(text="", tool_calls=(ToolCall("t1", "reply", {"text": text}),))


class TestTheNoAiPolicyThatAsksFirst:
    """`rules_asking` (decision log BLD-D28): one fixed question, then B1's rules."""

    def test_it_asks_waits_for_the_answer_and_then_plans(self, town: Town) -> None:
        town.stock(1)
        asking = WithRequests("rules_asking", RulesModel(asks_first=True))

        sim, (result,) = town.play(town.need(1), contender=asking, params=sure())

        (order,) = town.orders()
        said = town.thread()
        turns = measure.turns(sim)
        assert order.state == "PICKED_UP"
        assert [who for who, _ in said[:2]] == ["agent", "client"]
        assert said[0][1] in rules.TEXTS["ask_first"]
        assert (result.units_secured, result.messages) == (1, 1)
        # Its own note of the answer is one the runtime accepts: no correction, no fixed text.
        assert (turns["turns"], turns["turns_not_ok"], turns["turns_with_a_guard"]) == (2, 0, 0)


class TestAClientAnswersAQuestion:
    """Decision log BLD-D27 (the owner, 2026-11-15): a client who is asked something about
    their request answers it."""

    def test_asked_about_the_car_and_the_day_the_client_says_the_truth(self, town: Town) -> None:
        town.stock(1)
        tomorrow = town.need(1, pickup_in_days=1)

        town.play(tomorrow, contender=WithRequests("agent", AsksFirst()), params=sure())

        written = [text for who, text in town.thread() if who == "client"]
        who = tomorrow.client
        said_car = sim_client.WORDS["has_car" if who.has_car else "no_car"][who.language]
        said_day = sim_client.WORDS["only_tomorrow"][who.language]
        # One message holds the whole answer, so the agent reads it in one turn.
        assert any(
            any(car in text for car in said_car) and any(day in text for day in said_day)
            for text in written
        )
        # It answers each question once, and not for ever.
        assert len(written) <= sim_client.MAX_ANSWERS

    def test_an_answer_comes_within_minutes_and_a_tap_takes_longer(self, town: Town) -> None:
        """The owner, 2026-11-15 (build plan Q35): someone who was just asked something in
        a chat answers within 1 to 3 minutes; tapping a card keeps its 5 to 30."""
        town.stock(1)
        sim, _ = town.play(town.need(1), params=DAY)

        answers = {sim.client_answers("answer", n, 1) for n in range(200)}
        taps = {sim.client_waits("card", n, 1) for n in range(200)}

        assert answers == {1, 2, 3}
        assert (min(taps), max(taps)) == (5, 30)

    def test_what_is_asked_is_read_from_a_few_words(self) -> None:
        lands = sim_world.load()
        driver = next(c for c in lands.clients if c.has_car and c.free == "any")
        walker = next(c for c in lands.clients if not c.has_car and c.free == "after_18")

        def need_of(client: SimClient, pickup_in_days: int) -> Need:
            return Need(
                n=1,
                at=NOW,
                client=client,
                lines=(),
                hears_other_brands=False,
                pickup_in_days=pickup_in_days,
                says=None,
                later=None,
            )

        answers = sim_client.answers_to
        assert answers("Do you have a car, or will you go on foot?", need_of(driver, 0)) == [
            "has_car"
        ]
        assert answers("3andak siyyara aw mashi?", need_of(walker, 0)) == ["no_car"]
        assert answers("Which day will you pick up?", need_of(driver, 1)) == ["only_tomorrow"]
        assert answers("أي يوم بدك تمرّ؟", need_of(driver, 0)) == ["today_ok"]
        assert answers("What time are you free?", need_of(walker, 0)) == ["after_18"]
        assert answers("What time are you free?", need_of(driver, 0)) == ["any_time"]
        # Not a question, or a question about something else: nothing to answer.
        assert answers("Your car trip takes 10 minutes.", need_of(driver, 0)) == []
        assert answers("Shall I show you other brands?", need_of(driver, 0)) == []
        # A word of the day in a sentence that tells, next to a question about something else.
        told = "Concor is reserved for today. Shall I keep looking for the rest?"
        assert answers(told, need_of(driver, 0)) == []
        listed = "Two questions:\n1. Will you go by car or on foot?\n2. Which day: today?"
        assert answers(listed, need_of(walker, 1)) == ["only_tomorrow", "no_car"]
