"""One turn, end to end, on a scripted model.

Docs/07 §3 and §8; docs/09 FA-1 to FA-5, FA-15, FA-16, FX-1 to FX-3.
"""

from typing import Any

from dawalink.agent.llm import LLMUnavailable, ToolResults, UserText
from dawalink.agent.llm.scripted import call, calls, reply, say
from dawalink.agent.turn import Status
from tests.agent.conftest import Scene


def results_of(scene: Scene, position: int = -1) -> list[dict[str, Any]]:
    """The tool results the model was sent in one of its calls (by default, the last)."""
    import json

    message = scene.model.seen[position].messages[-1]
    assert isinstance(message, ToolResults)
    return [json.loads(result.content) for result in message.results]


class TestAPlainTurn:
    def test_a_reply_is_saved_with_the_runs_numbers(self, scene: Scene) -> None:
        """docs/07 §3.1: the message, the run and the lease, in one save."""
        result = scene.turn(reply("Which strength do you need?", quick_replies=["1 g", "625 mg"]))

        assert (result.status, result.outcome) == (Status.DONE, "ok")
        client_message, agent_message = scene.messages()
        assert (client_message.author, agent_message.author) == ("client", "agent")
        assert agent_message.text_redacted == "Which strength do you need?"
        assert agent_message.quick_replies == ["1 g", "625 mg"]
        assert agent_message.agent_run_id == result.run_id
        run = scene.run(result)
        assert (run.mode, run.trigger, run.outcome) == ("assistant", "client_message", "ok")
        assert (run.model, run.prompt_version) == ("scripted", "v1.1")
        assert (run.llm_calls, run.tool_calls, run.tokens_in, run.tokens_out) == (1, 0, 100, 20)
        assert run.ended_at is not None
        assert run.langfuse_trace_id
        conversation = scene.conversation()
        assert (conversation.turn_lease_until, conversation.turn_owner) == (None, None)

    def test_the_model_is_given_the_facts_and_the_tools_of_its_mode(self, scene: Scene) -> None:
        scene.turn(reply("Hello"))

        prompt = scene.model.seen[0]
        names = {tool.name for tool in prompt.tools}
        assert {"search_catalog", "find_options", "create_watch", "reply"} <= names
        assert not {"open_claim", "schedule_followup", "propose_remove_item"} & names
        assert "Hard rules" in prompt.system[0]
        assert "Mode: assistant" in prompt.system[1]
        block = prompt.messages[0]
        assert isinstance(block, UserText)
        assert "client: I need Augmentin" in block.text
        assert "2026-10-20 (today)" in block.text
        assert "The client wrote the last message" in block.text

    def test_a_tool_is_run_and_its_result_goes_back_to_the_model(self, scene: Scene) -> None:
        result = scene.turn(call("search_catalog", query="augmentin"), reply("Found it."))

        (found,) = results_of(scene)
        assert found["ok"] is True
        assert [product["name"] for product in found["products"]] == ["AUGMENTIN 1G"]
        assert scene.tool_calls(result) == [("search_catalog", True, None)]
        assert scene.run(result).llm_calls == 2

    def test_what_the_agent_notes_is_remembered_next_turn(self, scene: Scene) -> None:
        """docs/07 §6.2: the case state is the only memory between turns."""
        scene.turn(
            reply(
                "Ok",
                case_notes={
                    "language": "arabizi",
                    "situation_notes": ["no car"],
                    "add_note": "call me on 70 123 456",
                },
            )
        )
        scene.turn(reply("Hello again"), text="marhaba")

        block = scene.model.seen[0].messages[0]
        assert isinstance(block, UserText)
        assert '"language": "arabizi"' in block.text
        assert "no car" in block.text
        assert "70 123 456" not in block.text  # a note is redacted like any other text
        assert "[2] you: Ok" in block.text


class TestWhatTheModelMayGetWrong:
    def test_plain_text_instead_of_reply_is_accepted(self, scene: Scene) -> None:
        """FA-4, docs/07 §4.5: small models answer in text."""
        result = scene.turn(say("Which strength?"))

        assert (result.status, result.text, result.proposal_ids) == (
            Status.DONE,
            "Which strength?",
            (),
        )

    def test_an_empty_answer_becomes_our_neutral_text(self, scene: Scene) -> None:
        """FA-4."""
        result = scene.turn(say("   "))

        assert result.text == "Sorry, I couldn't answer that. Could you say it another way?"
        assert scene.run(result).guardrails == ["no_reply"]

    def test_an_unknown_tool_gets_an_error_the_model_can_read(self, scene: Scene) -> None:
        """FA-1."""
        result = scene.turn(call("reserve_now", listing="x"), reply("Sorry."))

        (answer,) = results_of(scene)
        assert (answer["ok"], answer["error_code"]) == (False, "UNKNOWN_TOOL")
        assert scene.tool_calls(result) == [("reserve_now", False, "UNKNOWN_TOOL")]
        assert scene.run(result).tool_errors == 1

    def test_a_tool_of_the_other_mode_does_not_exist_here(self, scene: Scene) -> None:
        """docs/07 §2: a chat turn can't open a request's claim."""
        scene.turn(call("schedule_followup", in_minutes=30), reply("Ok"))

        assert results_of(scene)[0]["error_code"] == "UNKNOWN_TOOL"

    def test_wrong_arguments_are_refused_without_echoing_them(self, scene: Scene) -> None:
        """FA-2."""
        scene.turn(call("search_catalog", query="", limit=999, extra="x"), reply("Ok"))

        (answer,) = results_of(scene)
        assert answer["error_code"] == "INVALID_ARGUMENTS"
        assert {p["argument"] for p in answer["details"]["problems"]} == {"query", "limit", "extra"}

    def test_after_six_tool_calls_only_reply_is_left(self, scene: Scene) -> None:
        """FA-3, N-17."""
        search = call("search_catalog", query="augmentin")
        result = scene.turn(*[search] * 6, search, reply("Here you go."))

        assert scene.run(result).tool_calls == 6
        assert [tool.name for tool in scene.model.seen[6].tools] == ["reply"]
        assert results_of(scene)[0]["error_code"] == "TOOL_LIMIT_REACHED"
        assert result.text == "Here you go."

    def test_a_model_that_never_replies_is_stopped(self, scene: Scene) -> None:
        """N-34: eight model calls, then our own words."""
        search = call("search_catalog", query="augmentin")
        result = scene.turn(*[search] * 8)

        assert result.status is Status.DONE
        assert result.text == "Sorry, I couldn't answer that. Could you say it another way?"
        run = scene.run(result)
        assert (run.llm_calls, run.tool_calls, run.guardrails) == (8, 6, ["no_reply"])

    def test_several_tool_calls_in_one_message_each_get_a_result(self, scene: Scene) -> None:
        scene.turn(
            calls(
                ("search_catalog", {"query": "augmentin"}), ("search_catalog", {"query": "concor"})
            ),
            reply("Both found."),
        )

        first, second = results_of(scene)
        assert first["products"][0]["name"] == "AUGMENTIN 1G"
        assert second["products"][0]["name"] == "CONCOR 5MG"

    def test_a_reply_with_wrong_fields_can_be_corrected(self, scene: Scene) -> None:
        result = scene.turn(reply("Hi", quick_replies=["x" * 41]), reply("Hi"))

        assert result.text == "Hi"
        assert results_of(scene)[0]["error_code"] == "INVALID_ARGUMENTS"


class TestWhenTheModelFails:
    def test_two_retries_then_the_reply(self, scene: Scene) -> None:
        """FX-2, FX-3, N-36."""
        down = LLMUnavailable("429")
        result = scene.turn(down, down, reply("Back."))

        assert (result.status, result.text) == (Status.DONE, "Back.")
        assert scene.run(result).retries == 2

    def test_a_model_that_stays_down_ends_the_turn_and_keeps_the_message(
        self, scene: Scene
    ) -> None:
        """FX-1: the client's message is kept, nothing else is written."""
        down = LLMUnavailable("connection refused")
        result = scene.turn(down, down, down)

        assert (result.status, result.outcome) == (Status.UNAVAILABLE, "fallback")
        assert [message.author for message in scene.messages()] == ["client"]
        run = scene.run(result)
        assert (run.outcome, run.retries, run.llm_calls) == ("fallback", 2, 0)
        assert scene.conversation().turn_lease_until is None

    def test_a_busy_conversation_is_left_alone(self, scene: Scene) -> None:
        """FA-15, R-AG2."""
        from dawalink.services import conversations

        conversations.take_lease(scene.world.tx(), scene.chat, "another-turn")
        result = scene.turn(reply("Hello"))

        assert result.status is Status.BUSY
        assert scene.model.seen == []
        assert scene.conversation().turn_owner == "another-turn"

    def test_a_turn_that_outlived_its_lease_saves_nothing(self, scene: Scene) -> None:
        """FA-16: the lease ran out during a long turn, so the save is refused."""

        def slow(_: Any) -> Any:
            scene.world.later(minutes=3)
            return reply("Too late.")

        result = scene.turn(slow)

        assert result.status is Status.LEASE_LOST
        assert [message.author for message in scene.messages()] == ["client"]
        assert scene.run(result).outcome == "error"
