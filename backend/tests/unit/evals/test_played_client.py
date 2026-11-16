"""The played client of suite E7 and the scoring of its conversations (docs/08 E7).

No model is called here: a stand-in returns what a playing model would.
"""

from datetime import date
from typing import Any

from dawalink.agent.llm import ModelReply, Prompt, ToolCall
from dawalink.evals.datasets import UCase
from dawalink.evals.played_client import (
    FACTS,
    STYLES,
    Line,
    Persona,
    next_message,
    personas,
    prompt_for,
)
from dawalink.evals.score_conversations import Exchange, score
from dawalink.evals.score_understanding import Answer, Seen, ToolUse

TODAY = date(2026, 11, 16)
CONCOR = "concor-5"


def case(number: int = 1, **gold: Any) -> UCase:
    reading: dict[str, Any] = {
        "intent": "find",
        "items": [{"match": {"name": "concor", "strength": "5mg"}, "qty": 2}],
        "expected": "propose_options",
    }
    return UCase.model_validate(
        {
            "id": f"U-{number:04d}",
            "lang": "arabizi",
            "category": "clear",
            "text": "baddi concor 5",
            "gold": reading | gold,
            "author": "test",
        }
    )


def persona(style: str = "bare", opens: tuple[str, ...] = (), **gold: Any) -> Persona:
    the_case = case(**gold)
    truth = Answer(on_foot=True, pickup_in_days=1, days_of_use=10)
    return Persona(the_case, truth, style, opens)  # type: ignore[arg-type]


class Plays:
    """A playing model that returns one prepared tool call."""

    name = "plays"

    def __init__(self, tool: str, **arguments: Any) -> None:
        self.call = ToolCall("c1", tool, arguments)
        self.seen: list[Prompt] = []

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        self.seen.append(prompt)
        return ModelReply(text="", tool_calls=(self.call,))


class TestPersonas:
    def test_only_cases_the_agent_can_serve_become_personas_with_the_styles_in_turn(
        self,
    ) -> None:
        vague = case(9, must_ask=["strength"], expected="ask")
        people = personas([case(n) for n in range(1, 9)] + [vague])

        assert [p.style for p in people] == [*STYLES, *STYLES]
        assert people[0].opens_with == FACTS  # everything at once
        assert people[2].opens_with == people[3].opens_with == ()  # only the medicine
        # "Half" is one fact or two, and not the same ones every time.
        assert people[1].opens_with == ("transport", "day")
        assert people[5].opens_with == ("day",)

    def test_the_truth_comes_from_the_cases_labels(self) -> None:
        (walker,) = personas([case(situation=["no_car"], pickup_in_days=2, days_of_use=30)])

        assert walker.truth == Answer(on_foot=True, pickup_in_days=2, days_of_use=30)
        facts = walker.facts()
        assert "concor 5mg, 2 boxes" in facts
        assert "on foot, you have no car" in facts
        assert "the day after tomorrow" in facts
        assert "30 days" in facts


class TestThePlayingModel:
    def test_the_brief_holds_the_facts_the_style_and_the_language(self) -> None:
        half = persona("half", ("day",), budget={"amount": 10, "currency": "USD"})

        prompt = prompt_for(half, [])

        rules, brief = prompt.system
        assert "never the assistant" in rules
        assert "only this about you: the day you will come" in brief
        assert "names every medicine" in rules
        assert "10 USD" in brief
        assert "Arabizi" in brief
        assert prompt.messages[0].text == "The chat is empty. Write your first message."  # type: ignore[union-attr]
        assert [tool.name for tool in prompt.tools] == ["write_message", "leave"]

    def test_the_chat_so_far_is_read_back_with_the_cards_shown(self) -> None:
        lines = [Line("you", "baddi concor"), Line("assistant", "Here it is.", cards=2)]

        text = prompt_for(persona(), lines).messages[0].text  # type: ignore[union-attr]

        assert "You: baddi concor" in text
        assert "Assistant: Here it is.\n[the assistant showed 2 card(s) to reserve]" in text

    def test_a_message_comes_with_the_facts_it_states(self) -> None:
        model = Plays("write_message", text=" mashi, bukra ", says=["day", "weather", "transport"])

        said = next_message(model, persona(), [Line("assistant", "Car or on foot? Which day?")])

        assert (said.text, said.says, said.left) == ("mashi, bukra", ("transport", "day"), False)

    def test_the_first_message_states_only_what_the_persona_opens_with(self) -> None:
        """Seen on the first run: "transport" reported for a message that named a medicine."""
        model = Plays("write_message", text="baddi concor 5", says=["transport", "day"])

        assert next_message(model, persona("bare"), []).says == ()
        assert next_message(model, persona("half", ("day",)), []).says == ("day",)

    def test_leaving_or_saying_nothing_ends_the_conversation(self) -> None:
        assert next_message(Plays("leave", why="it refused"), persona(), []).left is True
        assert next_message(Plays("write_message", text="  ", says=[]), persona(), []).left is True


def find(**more: Any) -> ToolUse:
    return ToolUse("find_options", {"product_ids": [CONCOR], **more})


def checked(who: Persona, *exchanges: Exchange) -> dict[str, bool | None]:
    return score(who, exchanges, products=[[CONCOR]], today=TODAY)


class TestScoring:
    ASKS = Seen("3andak siyyara aw mashi? ayya yom? la kam yom?")
    FINDS = Seen(
        "Pharmacy A.",
        [find(pickup_day="2026-11-17", days_of_use=10, sort="walkable")],
        cards=("reserve",),
    )

    def test_asking_then_searching_with_the_truth_passes_everything(self) -> None:
        result = checked(
            persona(),
            Exchange("baddi concor 5", (), self.ASKS),
            Exchange("mashi, bukra, 10 ayyam", FACTS, self.FINDS),
        )

        assert result == {
            "gets_cards": True,
            "right_medicine": True,
            "searches_with_the_truth": True,
            "waits_until_told": True,
            "asks_again": False,
            "first_message_is_enough": None,  # only for a client who says everything
        }

    def test_a_search_before_everything_was_said_is_not_waiting(self) -> None:
        result = checked(
            persona("half", ("day",)),
            Exchange("baddi concor 5 bukra", ("day",), self.FINDS),
        )

        assert result["waits_until_told"] is False
        assert result["gets_cards"] is True

    def test_asking_for_what_the_client_already_said_is_asking_again(self) -> None:
        again = Seen("Which day will you come? For how many days?")

        result = checked(
            persona("half", ("day",)),
            Exchange("baddi concor 5 bukra, mashi", ("transport", "day"), again),
        )

        assert result["asks_again"] is True
        assert result["gets_cards"] is False
        assert result["waits_until_told"] is None  # it never searched

    def test_a_search_with_another_day_or_medicine_fails_its_check(self) -> None:
        wrong_day = Seen(
            "Pharmacy A.",
            [find(pickup_day="2026-11-16", days_of_use=10, sort="walkable")],
            cards=("reserve",),
        )
        other = Seen("Pharmacy A.", [ToolUse("find_options", {"product_ids": ["other"]})])

        assert (
            checked(persona(), Exchange("…", FACTS, wrong_day))["searches_with_the_truth"] is False
        )
        assert checked(persona(), Exchange("…", FACTS, other))["right_medicine"] is False

    def test_a_client_who_says_everything_should_get_cards_at_once(self) -> None:
        everything = persona("all_at_once", FACTS)

        at_once = checked(everything, Exchange("…", FACTS, self.FINDS))
        asked = checked(
            everything, Exchange("…", FACTS, self.ASKS), Exchange("…", FACTS, self.FINDS)
        )

        assert at_once["first_message_is_enough"] is True
        assert asked["first_message_is_enough"] is False
        assert asked["asks_again"] is True
