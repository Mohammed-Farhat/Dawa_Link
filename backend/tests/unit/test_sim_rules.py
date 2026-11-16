"""B1, the policy with no AI (docs/08 E2): what its rules decide from a prompt.

The prompts here are written by hand, in the shape `agent/context.py` gives them. The
engine tests (`tests/services/test_sim_engine.py`) run the same rules on real prompts.
"""

import json
from typing import Any

import pytest

from dawalink.agent import context
from dawalink.agent.llm import AssistantTurn, ModelReply, Prompt, ToolCall, ToolResult, ToolResults
from dawalink.agent.llm import UserText as Text
from dawalink.agent.llm.base import ToolSpec
from dawalink.domain.vocabulary import TurnTrigger
from dawalink.sim.contenders import rules
from dawalink.sim.contenders.ablations import Without
from dawalink.sim.contenders.rules import RulesModel, next_step, read

SUBMITTED = context._WHAT_NOW[TurnTrigger.REQUEST_SUBMITTED]
CLIENT_WROTE = context._WHAT_NOW[TurnTrigger.CLIENT_MESSAGE]
SOMETHING_CHANGED = context._WHAT_NOW[TurnTrigger.DECISION_EVENT]
ONE_HOUR_LEFT = context._WHAT_NOW[TurnTrigger.WINDOW_CHECK]


def item(n: int, state: str = "SEARCHING", **values: Any) -> dict[str, Any]:
    made: dict[str, Any] = {
        "item_id": f"item-{n}",
        "product_id": f"product-{n}",
        "product": f"Medicine {n}",
        "qty": values.get("qty", 1),
        "qty_secured": values.get("secured", 0),
        "days_of_use": values.get("days", 7),
        "state": state,
        "waiting": {
            "claim_id": values.get("claim"),
            "watching": values.get("claim") is not None,
            "asked_pharmacies": values.get("asked", 0),
            "open_offer_count": values.get("offers", 0),
        },
    }
    if "max_price" in values:
        made["max_price"] = values["max_price"]
    return made


def block(
    *items: dict[str, Any],
    lines: tuple[str, ...] = ("[1] event: request_submitted: the client started this request",),
    what_now: str = SUBMITTED,
    other_brands: bool = False,
    state: str = "OPEN",
    remembered: dict[str, Any] | None = None,
) -> str:
    request = {
        "request_id": "request-1",
        "ref": "Q-TEST01",
        "state": state,
        "alternatives_ok": other_brands,
        "ends_display": "Mon 16:00",
        "minutes_left": 300,
        "items": list(items),
    }
    return "\n".join(
        [
            "## Now",
            "Mon 16 Nov 2026, 10:00 (Beirut time).",
            "Request hours (08:00-20:00): open.",
            "Upcoming days (copy a pickup_day from here, never work out a date): "
            "Mon 16 Nov = 2026-11-16 (today), Tue 17 Nov = 2026-11-17, Wed 18 Nov = 2026-11-18",
            "",
            "## Client",
            "Account status: ACTIVE. Location: shared for this conversation. Home area: Beirut.",
            "",
            "## What you remember (case state)",
            json.dumps(remembered or {}),
            "",
            "## This request",
            json.dumps(request),
            "",
            "## The conversation so far (oldest first)",
            *lines,
            "",
            "## What to do now",
            what_now,
        ]
    )


def prompt(text: str, *done: tuple[str, dict[str, Any], dict[str, Any]]) -> Prompt:
    """The prompt after these tool calls of the turn: (name, arguments, result)."""
    messages: list[Any] = [Text(text)]
    for number, (name, arguments, result) in enumerate(done):
        call = ToolCall(f"call-{number}", name, arguments)
        messages.append(AssistantTurn(ModelReply("", (call,))))
        failed = result.get("ok") is False
        messages.append(ToolResults((ToolResult(call.id, name, json.dumps(result), failed),)))
    return Prompt(system=("",), messages=tuple(messages), tools=())


def decide(text: str, *done: tuple[str, dict[str, Any], dict[str, Any]]) -> rules.Step:
    return next_step(read(prompt(text, *done)))


def plan(plan_id: str, car_min: int, total: str, *missing: str, groups: int = 1) -> dict[str, Any]:
    return {
        "plan_id": plan_id,
        "groups": [{"group_index": index} for index in range(groups)],
        "route": {"total_car_min": car_min},
        "total": total,
        "missing": [{"product_id": product, "qty_missing": 1} for product in missing],
    }


def plans(*found: dict[str, Any], unplannable: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "plans": list(found),
        "unplannable": [{"product_id": product, "qty_missing": 1} for product in unplannable],
    }


class TestReadingThePrompt:
    def test_it_knows_every_reason_a_turn_runs(self) -> None:
        """If the wording in `agent/context.py` changes, the rules must follow."""
        known = {
            trigger.value: read(prompt(block(item(1), what_now=sentence))).trigger
            for trigger, sentence in context._WHAT_NOW.items()
        }

        assert known == {name: name for name in known}
        assert set(known) == set(rules.TRIGGERS.values())

    def test_it_reads_the_facts_it_needs(self) -> None:
        text = block(
            item(1),
            lines=(
                "[1] event: request_submitted: the client started this request",
                "[2] client: l arkhas iza btrid",
                '[3] you: I found some of your medicines. (cards: abc "Plan" [open])',
                "[4] client: bas bukra b2dar",
                "[5] event: not_available: the pharmacy marked order R-1 not available",
            ),
            remembered={"preference": "nearest"},
        )

        view = read(prompt(text, ("plan_basket", {"items": []}, plans())))

        assert view.days == ("2026-11-16", "2026-11-17", "2026-11-18")
        assert view.client_lines == ("l arkhas iza btrid", "bas bukra b2dar")
        assert view.fresh_client_lines == ("bas bukra b2dar",)
        assert [event.split(":")[0] for event in view.fresh_events] == ["not_available"]
        assert (view.done[0].name, view.done[0].ok, view.calls_left) == ("plan_basket", True, 5)


class TestKeywords:
    def test_the_words_of_the_evaluation_plan_are_recognised(self) -> None:
        said = {
            "cheapest option please": "cheapest",
            "bade l rkhis": "cheapest",
            "ma 3ande siyyara": "walkable",
            "I don't have a car": "walkable",
            "shi 2arib menne": "nearest",
            "bade mishwar wa7ad": "fewest_trips",
            "الأرخص إذا بتريد": "cheapest",
        }

        for words, meaning in said.items():
            view = read(prompt(block(item(1), lines=(f"[2] client: {words}",))))
            assert rules.preference_of(view) == meaning, words

    def test_what_no_keyword_matches_is_not_understood(self) -> None:
        """The point of this contender: "evenings only" needs understanding."""
        view = read(prompt(block(item(1), lines=("[2] client: Evenings only for me",))))

        assert rules.preference_of(view) is None
        assert rules.pickup_day_of(view) is None

    def test_no_car_beats_cheap_and_the_newest_message_wins(self) -> None:
        both = read(prompt(block(item(1), lines=("[2] client: cheap, and I have no car",))))
        later = read(
            prompt(block(item(1), lines=("[2] client: no car", "[4] client: the cheapest")))
        )

        assert rules.preference_of(both) == "walkable"
        assert rules.preference_of(later) == "cheapest"

    def test_tomorrow_becomes_the_second_upcoming_day(self) -> None:
        view = read(prompt(block(item(1), lines=("[2] client: ما بقدر روح اليوم، بكرا",))))

        assert rules.pickup_day_of(view) == "2026-11-17"
        assert rules.writes_arabic(view) is True


class TestSourcing:
    def test_first_it_plans_what_is_being_searched(self) -> None:
        text = block(
            item(1, qty=2, max_price="716,000 LBP (about $8.00)"),
            item(2, "SECURED", secured=1),
            item(3, "WAITING", claim="claim-3", asked=1),
            lines=("[1] event: request_submitted: started", "[2] client: bas bukra, w l arkhas"),
        )

        assert decide(text) == (
            "plan_basket",
            {
                "items": [
                    {
                        "product_id": "product-1",
                        "qty": 2,
                        "days_of_use": 7,
                        "max_price": {"amount": 716000, "currency": "LBP"},
                    }
                ],
                "pickup_day": "2026-11-17",
                "preference": "cheapest",
            },
        )

    def test_without_a_preference_the_shortest_drive_wins_then_the_price(self) -> None:
        text = block(item(1), item(2))
        found = plans(
            plan("far", 30, "500,000 LBP"),
            plan("near-dear", 10, "900,000 LBP"),
            plan("near-cheap", 10, "700,000 LBP"),
            plan("nearest-but-incomplete", 5, "300,000 LBP", "product-2"),
        )

        step = decide(text, ("plan_basket", {}, found))

        assert step == ("propose_plan", {"plan_id": "near-cheap"})

    def test_with_a_stated_preference_the_planners_first_plan_is_shown(self) -> None:
        text = block(item(1), lines=("[2] client: l arkhas iza btrid",))
        found = plans(plan("cheapest", 40, "300,000 LBP"), plan("nearest", 5, "900,000 LBP"))

        assert decide(text, ("plan_basket", {}, found)) == ("propose_plan", {"plan_id": "cheapest"})

    def test_what_no_plan_covers_waits_and_pharmacies_are_asked(self) -> None:
        text = block(item(1), item(2))
        found = plans(plan("p", 10, "500,000 LBP", "product-2"))
        so_far: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
            ("plan_basket", {}, found),
            ("propose_plan", {"plan_id": "p"}, {"proposals": [{"proposal_id": "card-1"}]}),
        ]

        waits = decide(text, *so_far)
        so_far.append(("open_claim", {"request_item_id": "item-2"}, {"claim_id": "claim-2"}))
        asks = decide(text, *so_far)
        so_far.append(("request_early_release", {"claim_id": "claim-2"}, {"asked": 2}))
        says = decide(text, *so_far)

        assert waits == ("open_claim", {"request_item_id": "item-2"})
        assert asks == ("request_early_release", {"claim_id": "claim-2"})
        assert says[0] == "reply"
        assert says[1]["proposal_ids"] == ["card-1"]
        assert "watching for new stock" in says[1]["text"]
        assert "asked pharmacies" in says[1]["text"]

    def test_nothing_listed_at_all_everything_waits(self) -> None:
        text = block(item(1))
        nothing = plans(unplannable=("product-1",))

        assert decide(text, ("plan_basket", {}, nothing)) == (
            "open_claim",
            {"request_item_id": "item-1"},
        )

    def test_a_medicine_that_waits_with_no_ask_running_is_asked_about_again(self) -> None:
        """After "no pharmacy released stock", the same steps run again (docs/08 E2)."""
        text = block(
            item(1, "WAITING", claim="claim-1"),
            item(2, "WAITING", claim="claim-2", asked=2),
            item(3, "WAITING", claim="claim-3", offers=1),
            what_now=SOMETHING_CHANGED,
        )

        assert decide(text) == ("request_early_release", {"claim_id": "claim-1"})

    def test_a_card_waiting_for_a_tap_is_left_alone_until_the_client_writes(self) -> None:
        waiting_for_a_tap = (item(1, "PROPOSED"),)
        quiet = block(*waiting_for_a_tap, what_now=SOMETHING_CHANGED)
        wrote = block(
            *waiting_for_a_tap,
            lines=('[2] you: I found it. (cards: c "Plan" [open])', "[3] client: no car"),
            what_now=CLIENT_WROTE,
        )

        assert decide(quiet)[0] == "reply"
        assert decide(wrote)[0] == "plan_basket"
        assert decide(wrote)[1]["preference"] == "walkable"

    def test_more_work_than_one_turn_may_do_comes_back_later(self) -> None:
        """Six tool calls a turn (N-34): the last one schedules the rest."""
        five = [item(n) for n in range(1, 6)]
        text = block(*five)
        so_far: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
            ("plan_basket", {}, plans(unplannable=tuple(f"product-{n}" for n in range(1, 6))))
        ]
        taken = []
        while (step := decide(text, *so_far))[0] != "reply":
            taken.append(step[0])
            result = {"claim_id": f"claim-{len(so_far)}"} if step[0] == "open_claim" else {}
            so_far.append((step[0], step[1], result))

        assert taken == ["open_claim"] * 4 + ["schedule_followup"]
        assert len(so_far) == rules.CALLS_PER_TURN

    def test_a_refused_tool_is_not_called_again(self) -> None:
        text = block(item(1))
        refused = {"ok": False, "error_code": "NOT_IN_REQUEST_HOURS", "hint": "..."}

        step = decide(text, ("plan_basket", {}, refused))
        then = decide(
            text,
            ("plan_basket", {}, refused),
            ("open_claim", {"request_item_id": "item-1"}, refused),
        )

        assert step == ("open_claim", {"request_item_id": "item-1"})
        assert then[0] == "reply"

    def test_a_closed_request_gets_one_sentence(self) -> None:
        step = decide(block(item(1, "UNAVAILABLE"), state="CLOSED"))

        assert step == ("reply", {"text": "This request is closed."})


OTHERS: dict[str, Any] = {"products": [{"id": "brand-a"}, {"id": "brand-b"}]}
OPTIONS: dict[str, Any] = {
    "options": [
        {"listing_id": "box-own", "product": "Medicine 1", "is_alternative": False},
        {
            "listing_id": "box-a",
            "product": "Brand A",
            "is_alternative": True,
            "available": 2,
            "pickup_days_allowed": ["2026-11-16", "2026-11-17"],
        },
    ]
}


class TestOtherBrands:
    def test_at_the_window_check_a_client_who_never_agreed_is_asked_first(self) -> None:
        text = block(item(1, "WAITING", claim="c"), what_now=ONE_HOUR_LEFT)
        ask = ("propose_constraint_change", {"request_id": "request-1", "show_other_brands": True})

        first = decide(text)
        then = decide(text, (*ask, {"proposal_id": "card-9"}))

        assert first == ask
        assert then[0] == "reply"
        assert then[1]["proposal_ids"] == ["card-9"]

    def test_a_client_who_agreed_is_shown_another_brand_in_three_steps(self) -> None:
        text = block(item(1, "PROPOSED"), what_now=ONE_HOUR_LEFT, other_brands=True)
        so_far: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        taken = []
        results: dict[str, dict[str, Any]] = {
            "get_equivalents": OTHERS,
            "find_options": OPTIONS,
            "show_other_brand": {"proposal_id": "card-brand"},
        }
        while (step := decide(text, *so_far))[0] != "reply":
            taken.append(step)
            so_far.append((step[0], step[1], results[step[0]]))

        assert [name for name, _ in taken] == [
            "get_equivalents",
            "find_options",
            "show_other_brand",
        ]
        assert taken[1][1]["product_ids"] == ["product-1", "brand-a", "brand-b"]
        assert taken[2][1] == {
            "listing_id": "box-a",
            "instead_of_product_id": "product-1",
            "days_of_use": 7,
        }
        assert step[1]["proposal_ids"] == ["card-brand"]
        assert "ask the pharmacist first" in step[1]["text"]

    def test_the_clients_yes_is_acted_on_at_once(self) -> None:
        text = block(
            item(1, "WAITING", claim="c"),
            lines=(
                '[4] you: One hour is left. (cards: c "Tell you about other brands?" [used])',
                "[5] event: constraints_changed: the client now wants to hear about other brands",
            ),
            what_now=SOMETHING_CHANGED,
            other_brands=True,
        )

        assert decide(text) == ("get_equivalents", {"product_id": "product-1"})

    def test_no_other_brand_exists_and_the_client_is_told(self) -> None:
        text = block(item(1, "WAITING", claim="c"), what_now=ONE_HOUR_LEFT, other_brands=True)

        step = decide(text, ("get_equivalents", {"product_id": "product-1"}, {"products": []}))

        assert step[0] == "reply"
        assert "no other brand" in step[1]["text"]

    def test_a_brand_is_reserved_only_when_the_client_names_it_in_a_message(self) -> None:
        """R-C10: the card to reserve another brand comes after the client asks for it."""
        asks = "[6] client: I asked the pharmacist and it's fine. Please reserve Brand A for me"
        text = block(item(1, "WAITING", claim="c", qty=3), lines=(asks,), what_now=CLIENT_WROTE)
        looked_up: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
            ("get_equivalents", {"product_id": "product-1"}, OTHERS),
            ("find_options", {"product_ids": ["product-1", "brand-a", "brand-b"]}, OPTIONS),
        ]

        assert decide(text) == ("get_equivalents", {"product_id": "product-1"})
        assert decide(text, *looked_up) == (
            "propose_reservation",
            {
                "listing_id": "box-a",
                "qty": 2,
                "pickup_day": "2026-11-16",
                "days_of_use": 7,
                "client_asked_for_this_brand": True,
            },
        )

    def test_a_brand_it_can_not_find_is_not_reserved(self) -> None:
        asks = "[6] client: please reserve Some Other Brand for me"
        text = block(item(1, "WAITING", claim="c"), lines=(asks,), what_now=CLIENT_WROTE)

        step = decide(
            text,
            ("get_equivalents", {"product_id": "product-1"}, OTHERS),
            ("find_options", {"product_ids": ["product-1", "brand-a"]}, OPTIONS),
        )

        assert step[0] == "reply"
        assert "couldn't find that brand" in step[1]["text"]


class TestTheModel:
    def test_it_answers_like_a_model_with_one_tool_call(self) -> None:
        model = RulesModel()

        first = model.complete(prompt(block(item(1))), timeout_s=1)
        second = model.complete(prompt(block(item(1))), timeout_s=1)

        assert (model.name, first.text) == ("rules", "")
        assert [call.name for call in first.tool_calls] == ["plan_basket"]
        assert first.tool_calls[0].id != second.tool_calls[0].id

    def test_it_replies_in_the_script_the_client_wrote_in(self) -> None:
        text = block(
            item(1, "WAITING", claim="c", asked=2),
            lines=("[2] client: شي قريب مني",),
            what_now=CLIENT_WROTE,
        )

        name, arguments = decide(text)

        assert name == "reply"
        assert arguments["text"] == rules.TEXTS["waiting"][1]
        assert arguments["case_notes"] == {"preference": "nearest"}


class Recorder:
    """A model that notes which tools it was offered and always says the same thing."""

    name = "recorder"

    def __init__(self) -> None:
        self.offered: list[list[str]] = []

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        self.offered.append([tool.name for tool in prompt.tools])
        return ModelReply("", (ToolCall("r1", "reply", {"text": "From the model."}),))


def offering(*names: str, what_now: str = SUBMITTED) -> Prompt:
    tools = tuple(ToolSpec(name, "", {}) for name in names)
    return Prompt(system=("",), messages=(Text(block(item(1), what_now=what_now)),), tools=tools)


class TestTheAgentWithOneAbilityLess:
    """docs/08 E3: the same agent, with one tool hidden or one kind of turn left unanswered."""

    TOOLS = ("plan_basket", "propose_plan", "find_options", "request_early_release", "reply")

    def test_without_early_release_the_model_is_not_offered_that_tool(self) -> None:
        inner = Recorder()

        Without(inner, "early_release").complete(offering(*self.TOOLS), timeout_s=1)

        assert inner.offered == [["plan_basket", "propose_plan", "find_options", "reply"]]

    def test_without_planning_it_must_go_medicine_by_medicine(self) -> None:
        inner = Recorder()

        Without(inner, "planning").complete(offering(*self.TOOLS), timeout_s=1)

        assert inner.offered == [["find_options", "request_early_release", "reply"]]

    def test_without_replanning_an_event_is_only_acknowledged(self) -> None:
        inner = Recorder()
        deaf = Without(inner, "replanning")
        event = context._WHAT_NOW[TurnTrigger.DECISION_EVENT]
        window = context._WHAT_NOW[TurnTrigger.WINDOW_CHECK]

        on_event = deaf.complete(offering(*self.TOOLS, what_now=event), timeout_s=1)
        first_turn = deaf.complete(offering(*self.TOOLS), timeout_s=1)
        last_chance = deaf.complete(offering(*self.TOOLS, what_now=window), timeout_s=1)

        assert on_event.tool_calls[0].arguments == {"text": "Noted. I'll keep you posted."}
        assert first_turn.tool_calls[0].arguments == {"text": "From the model."}
        assert last_chance.tool_calls[0].arguments == {"text": "From the model."}
        assert len(inner.offered) == 2  # the model was never asked about the event

    def test_an_unknown_ability_is_refused(self) -> None:
        with pytest.raises(ValueError, match="one of"):
            Without(Recorder(), "tapping")


def decide_asking(text: str, *done: tuple[str, dict[str, Any], dict[str, Any]]) -> rules.Step:
    return next_step(read(prompt(text, *done), asks_first=True))


QUESTION = rules.TEXTS["ask_first"][0]


class TestThePolicyThatAsksFirst:
    """`rules_asking` (decision log BLD-D28): the same rules behind one question."""

    def test_a_new_request_gets_the_question_and_nothing_else(self) -> None:
        name, arguments = decide_asking(block(item(1)))

        assert name == "reply"
        assert arguments == {"text": QUESTION}

    def test_the_frozen_policy_still_plans_at_once(self) -> None:
        assert decide(block(item(1)))[0] == "plan_basket"
        assert RulesModel().name == "rules"
        assert RulesModel(asks_first=True).name == "rules_asking"

    def test_until_the_client_answers_it_asks_again(self) -> None:
        text = block(
            item(1),
            lines=("[1] event: request_submitted: started", f"[2] you: {QUESTION}"),
            what_now=ONE_HOUR_LEFT,
        )

        assert decide_asking(text) == ("reply", {"text": QUESTION})

    def test_a_driver_who_comes_today_gets_the_plain_plan(self) -> None:
        text = block(
            item(1),
            lines=(
                "[1] event: request_submitted: started",
                f"[2] you: {QUESTION}",
                "[3] client: I have a car. Today is fine",
            ),
            what_now=CLIENT_WROTE,
        )

        assert decide_asking(text) == (
            "plan_basket",
            {"items": [{"product_id": "product-1", "qty": 1, "days_of_use": 7}]},
        )

    def test_no_car_and_tomorrow_are_read_from_the_answer(self) -> None:
        text = block(
            item(1),
            lines=(
                "[1] event: request_submitted: started",
                f"[2] you: {QUESTION}",
                "[3] client: I don't have a car. I can only go tomorrow",
            ),
            what_now=CLIENT_WROTE,
        )

        name, arguments = decide_asking(text)

        assert name == "plan_basket"
        assert (arguments["preference"], arguments["pickup_day"]) == ("walkable", "2026-11-17")

    def test_the_answer_is_remembered_when_the_question_is_no_longer_shown(self) -> None:
        text = block(
            item(1, "WAITING", claim="c", asked=2),
            lines=("[40] event: early_release_closed: nothing",),
            what_now=SOMETHING_CHANGED,
            remembered={"situation_notes": ["answered"]},
        )

        name, arguments = decide_asking(text)

        assert name == "reply"
        assert arguments["text"] != QUESTION
        assert arguments["case_notes"] == {"situation_notes": ["answered"]}
