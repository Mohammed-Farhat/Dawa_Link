"""The model adapters, the routing adapter and the setup, with no network at all.

Each adapter is proven by what it would send and by how it reads an answer: a fake HTTP
transport or a fake client stands in for the provider (docs/07 §10, §11; docs/09 FX-1 to
FX-5, FX-18). No test here can reach Anthropic, Ollama or OpenRouteService.
"""

import json
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from dawalink.agent.llm import (
    AssistantTurn,
    LLMRefused,
    LLMRejected,
    LLMUnavailable,
    ModelReply,
    Prompt,
    ToolCall,
    ToolResult,
    ToolResults,
    ToolSpec,
    Usage,
    UserText,
)
from dawalink.agent.llm.base import cost_usd
from dawalink.agent.llm.claude import ClaudeModel
from dawalink.agent.llm.ollama import OllamaModel
from dawalink.agent.setup import build_agent, build_model, build_routing, build_tracer
from dawalink.agent.tracing import NoTracer
from dawalink.config import ConfigError
from dawalink.domain.geo import Point
from dawalink.routing import OpenRouteService, RoutingError
from tests.conftest import make_settings

TOOL = ToolSpec("search_catalog", "Find medicines.", {"type": "object", "properties": {}})
PROMPT = Prompt(
    system=("the rules", "the mode", "the examples"),
    messages=(
        UserText("facts"),
        AssistantTurn(ModelReply("", (ToolCall("call_1", "search_catalog", {"query": "x"}),))),
        ToolResults((ToolResult("call_1", "search_catalog", '{"ok":true}'),)),
    ),
    tools=(TOOL,),
)


class FakeAnthropic:
    """Stands in for the Anthropic client: records the request, answers or raises."""

    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.sent: dict[str, Any] = {}
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **request: Any) -> Any:
        self.sent = request
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def claude(answer: Any) -> tuple[ClaudeModel, FakeAnthropic]:
    client = FakeAnthropic(answer)
    model = ClaudeModel(
        api_key="unused",
        model="claude-haiku-5-5",
        effort="medium",
        client=client,  # type: ignore[arg-type]
    )
    return model, client


def answer(*blocks: Any, stop_reason: str = "tool_use", **usage: int) -> Any:
    counted = {
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    return SimpleNamespace(
        content=list(blocks), stop_reason=stop_reason, usage=SimpleNamespace(**(counted | usage))
    )


def status_error(kind: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.test/v1/messages")
    response = httpx2.Response(status, request=request)
    return kind("secret prompt text", response=response, body=None)


class TestClaude:
    def test_what_is_sent(self) -> None:
        """docs/07 §10: no sampling settings, an explicit effort, no forced tool choice."""
        model, client = claude(answer())
        model.complete(PROMPT, timeout_s=12)

        sent = client.sent
        assert sent["model"] == "claude-haiku-5-5"
        assert sent["output_config"] == {"effort": "medium"}
        assert sent["timeout"] == 12
        assert not {"temperature", "top_p", "top_k", "tool_choice", "thinking"} & set(sent)
        # The fixed parts come first, and the last of them is where the cache ends.
        assert [part["text"] for part in sent["system"]] == [
            "the rules",
            "the mode",
            "the examples",
        ]
        assert [part.get("cache_control") for part in sent["system"]] == [
            None,
            None,
            {"type": "ephemeral"},
        ]
        assert sent["tools"] == [
            {
                "name": "search_catalog",
                "description": "Find medicines.",
                "input_schema": {"type": "object", "properties": {}},
            }
        ]
        user, assistant, results = sent["messages"]
        assert user == {"role": "user", "content": "facts"}
        assert assistant["content"] == [
            {"type": "tool_use", "id": "call_1", "name": "search_catalog", "input": {"query": "x"}}
        ]
        assert results["content"] == [
            {
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": '{"ok":true}',
                "is_error": False,
            }
        ]

    def test_a_note_of_ours_goes_after_the_tool_results_in_the_same_message(self) -> None:
        """FA-36: what was already sent in a turn is never changed, only added to."""
        model, _ = claude(answer())
        results = ToolResults(
            (ToolResult("call_1", "search_catalog", '{"ok":true}'),), note="Reply now."
        )

        sent = model.request(Prompt(PROMPT.system, (*PROMPT.messages[:2], results), PROMPT.tools))

        assert [block["type"] for block in sent["messages"][-1]["content"]] == [
            "tool_result",
            "text",
        ]
        assert sent["messages"][-1]["content"][-1] == {"type": "text", "text": "Reply now."}

    def test_an_answer_is_read_into_text_tool_calls_and_tokens(self) -> None:
        thinking = SimpleNamespace(type="thinking", thinking="")
        text = SimpleNamespace(type="text", text="Looking.")
        use = SimpleNamespace(
            type="tool_use", id="toolu_1", name="search_catalog", input={"query": "x"}
        )
        model, _ = claude(answer(thinking, text, use, input_tokens=40, cache_read_input_tokens=900))

        reply = model.complete(PROMPT, timeout_s=30)

        assert reply.text == "Looking."
        assert reply.tool_calls == (ToolCall("toolu_1", "search_catalog", {"query": "x"}),)
        assert reply.usage == Usage(input_tokens=940, output_tokens=20, cached_tokens=900)
        # The model's own blocks go back unchanged on the next call: thinking included.
        again = model.request(Prompt(PROMPT.system, (AssistantTurn(reply),), PROMPT.tools))
        assert again["messages"][0]["content"] == [thinking, text, use]

    def test_a_safety_refusal_is_its_own_failure(self) -> None:
        model, _ = claude(answer(stop_reason="refusal"))

        with pytest.raises(LLMRefused):
            model.complete(PROMPT, timeout_s=30)

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (status_error(anthropic.RateLimitError, 429), LLMUnavailable),
            (status_error(anthropic.InternalServerError, 500), LLMUnavailable),
            (status_error(anthropic.InternalServerError, 529), LLMUnavailable),
            (status_error(anthropic.AuthenticationError, 401), LLMRejected),
            (status_error(anthropic.BadRequestError, 400), LLMRejected),
            (status_error(anthropic.PermissionDeniedError, 403), LLMRejected),
        ],
    )
    def test_provider_errors_become_ours(
        self, error: anthropic.APIStatusError, expected: type[Exception]
    ) -> None:
        """FX-1, FX-3: what a retry can fix is told apart from what it can't."""
        model, _ = claude(error)

        with pytest.raises(expected) as caught:
            model.complete(PROMPT, timeout_s=30)

        # A provider's message can quote the request: it is never kept.
        assert "secret prompt text" not in str(caught.value)

    def test_a_timeout_is_unavailable(self) -> None:
        """FX-2."""
        request = httpx2.Request("POST", "https://api.anthropic.test/v1/messages")
        model, _ = claude(anthropic.APITimeoutError(request=request))

        with pytest.raises(LLMUnavailable):
            model.complete(PROMPT, timeout_s=30)


class TestCost:
    def test_a_turn_is_priced_from_its_tokens(self) -> None:
        used = Usage(
            input_tokens=11_000, output_tokens=500, cached_tokens=10_000, cache_write_tokens=0
        )

        # 1,000 plain + 10,000 cached at a tenth, at $0.10 per million; 500 out at $0.50.
        assert cost_usd("claude-haiku-5-5", used) == Decimal("0.000450")

    def test_a_model_without_a_price_is_free(self) -> None:
        assert cost_usd("qwen2.5:7b", Usage(input_tokens=9_000, output_tokens=900)) == 0


def ollama(handler: Any) -> OllamaModel:
    client = httpx2.Client(base_url="http://ollama.test", transport=httpx2.MockTransport(handler))
    return OllamaModel(base_url="http://ollama.test", client=client)


class TestOllama:
    def test_what_is_sent_and_what_comes_back(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen.update(json.loads(request.content))
            return httpx2.Response(
                200,
                json={
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "search_catalog", "arguments": {"query": "x"}}}
                        ],
                    },
                    "prompt_eval_count": 5000,
                    "eval_count": 30,
                },
            )

        reply = ollama(handler).complete(PROMPT, timeout_s=30)

        assert seen["model"] == "qwen2.5:7b"
        # The context length is always set: a prompt that doesn't fit is cut silently.
        assert seen["options"] == {"temperature": 0, "num_ctx": 12_288}
        assert seen["stream"] is False
        assert [message["role"] for message in seen["messages"]] == [
            "system",
            "user",
            "assistant",
            "tool",
        ]
        assert seen["messages"][0]["content"] == "the rules\n\nthe mode\n\nthe examples"
        assert seen["tools"][0]["function"]["name"] == "search_catalog"
        (call,) = reply.tool_calls
        assert (call.name, call.arguments) == ("search_catalog", {"query": "x"})
        assert reply.usage == Usage(input_tokens=5000, output_tokens=30)

    def test_a_call_written_into_the_text_is_still_a_call(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            text = (
                'ok <tool_call>{"name": "search_catalog", "arguments": {"query": "x"}}</tool_call>'
            )
            return httpx2.Response(200, json={"message": {"content": text}})

        reply = ollama(handler).complete(PROMPT, timeout_s=30)

        assert reply.text == "ok"
        assert reply.tool_calls[0].arguments == {"query": "x"}

    def test_ollama_not_running_is_unavailable(self) -> None:
        """FX-5."""

        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ConnectError("connection refused", request=request)

        with pytest.raises(LLMUnavailable):
            ollama(handler).complete(PROMPT, timeout_s=30)

    def test_an_unknown_model_is_rejected(self) -> None:
        with pytest.raises(LLMRejected):
            ollama(lambda _: httpx2.Response(404)).complete(PROMPT, timeout_s=30)


HAMRA = Point(Decimal("33.896"), Decimal("35.483"))
PHARMACY, OTHER = uuid.uuid4(), uuid.uuid4()
PINS = {
    PHARMACY: Point(Decimal("33.887"), Decimal("35.522")),
    OTHER: Point(Decimal("33.884"), Decimal("35.487")),
}


def routing(handler: Any) -> OpenRouteService:
    client = httpx2.Client(base_url="http://ors.test", transport=httpx2.MockTransport(handler))
    return OpenRouteService(api_key="the-key", base_url="http://ors.test", client=client)


class TestOpenRouteService:
    def test_one_call_gives_every_pair_in_minutes_and_km(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx2.Request) -> httpx2.Response:
            seen["path"] = request.url.path
            seen["key"] = request.headers["Authorization"]
            seen["body"] = json.loads(request.content)
            return httpx2.Response(
                200, json={"durations": [[372.4, 20.0]], "distances": [[4.6, 0.31]]}
            )

        times = routing(handler).road_times({"here": HAMRA}, PINS, "car")

        assert seen["path"] == "/v2/matrix/driving-car"
        assert seen["key"] == "the-key"
        # Longitude first, then latitude: the other way round fails silently.
        assert seen["body"]["locations"] == [[35.483, 33.896], [35.522, 33.887], [35.487, 33.884]]
        assert (seen["body"]["sources"], seen["body"]["destinations"]) == ([0], [1, 2])
        assert seen["body"]["metrics"] == ["duration", "distance"]
        assert seen["body"]["units"] == "km"
        # Whole minutes, never "0 min".
        assert times == {("here", PHARMACY): (6, 4.6), ("here", OTHER): (1, 0.31)}

    def test_walking_uses_the_walking_profile(self) -> None:
        paths = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            paths.append(request.url.path)
            return httpx2.Response(200, json={"durations": [[60, 60]], "distances": [[1, 1]]})

        routing(handler).road_times({"here": HAMRA}, PINS, "walk")

        assert paths == ["/v2/matrix/foot-walking"]

    def test_only_points_leave_the_system(self) -> None:
        """docs/10 §4.3: no account, conversation or request is named."""
        bodies = []

        def handler(request: httpx2.Request) -> httpx2.Response:
            bodies.append(request.content.decode() + str(request.url))
            return httpx2.Response(200, json={"durations": [[60, 60]], "distances": [[1, 1]]})

        routing(handler).road_times({"a-cache-cell": HAMRA}, PINS, "car")

        assert str(PHARMACY) not in bodies[0]
        assert "a-cache-cell" not in bodies[0]
        assert set(json.loads(bodies[0].split("http")[0])) == {
            "locations",
            "sources",
            "destinations",
            "metrics",
            "units",
        }

    def test_a_pair_with_no_road_is_left_out(self) -> None:
        def handler(_: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200, json={"durations": [[None, 120]], "distances": [[None, 2.0]]}
            )

        assert routing(handler).road_times({"here": HAMRA}, PINS, "car") == {
            ("here", OTHER): (2, 2.0)
        }

    @pytest.mark.parametrize("status", [403, 429, 500])
    def test_a_refusal_or_a_failure_raises(self, status: int) -> None:
        """FX-18: over the free quota, or down. The caller falls back to the estimate."""
        with pytest.raises(RoutingError):
            routing(lambda _: httpx2.Response(status)).road_times({"here": HAMRA}, PINS, "car")

    def test_a_timeout_raises_without_naming_a_place(self) -> None:
        def handler(request: httpx2.Request) -> httpx2.Response:
            raise httpx2.ReadTimeout("timed out reading 33.896,35.483", request=request)

        with pytest.raises(RoutingError) as caught:
            routing(handler).road_times({"here": HAMRA}, PINS, "car")

        assert "33.896" not in str(caught.value)


class TestSetup:
    """docs/07 §11: under `app_env = "test"` nothing real can be built."""

    def test_without_a_provider_the_assistant_is_off(self, tmp_path: Path) -> None:
        settings = make_settings("postgresql+psycopg://u@h/d", tmp_path)

        assert build_model(settings) is None
        assert build_agent(settings, None, None) is None  # type: ignore[arg-type]
        assert build_routing(settings) is None
        assert isinstance(build_tracer(settings), NoTracer)

    @pytest.mark.parametrize(
        "overrides",
        [
            {"llm_provider": "ollama"},
            {
                "llm_provider": "anthropic",
                "llm_model": "claude-haiku-5-5",
                "anthropic_api_key": "sk-test",
            },
        ],
    )
    def test_a_test_can_not_build_a_real_model(
        self, tmp_path: Path, overrides: dict[str, str]
    ) -> None:
        settings = make_settings("postgresql+psycopg://u@h/d", tmp_path, **overrides)

        with pytest.raises(ConfigError, match="real model"):
            build_model(settings)

    def test_a_test_can_not_build_a_real_routing_service_or_tracer(self, tmp_path: Path) -> None:
        settings = make_settings(
            "postgresql+psycopg://u@h/d",
            tmp_path,
            ors_api_key="key",
            langfuse_public_key="pk",
            langfuse_secret_key="sk",
        )

        with pytest.raises(ConfigError, match="routing"):
            build_routing(settings)
        with pytest.raises(ConfigError, match="tracer"):
            build_tracer(settings)

    def test_claude_needs_a_key_a_model_and_a_price(self, tmp_path: Path) -> None:
        def local(**overrides: str) -> Any:
            return make_settings(
                "postgresql+psycopg://u@h/d",
                tmp_path,
                app_env="local",
                llm_provider="anthropic",
                **overrides,
            )

        with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
            build_model(local(llm_model="claude-haiku-5-5"))
        with pytest.raises(ConfigError, match="LLM_MODEL"):
            build_model(local(anthropic_api_key="sk-test"))
        with pytest.raises(ConfigError, match="no price"):
            build_model(local(anthropic_api_key="sk-test", llm_model="claude-unknown"))
        model = build_model(local(anthropic_api_key="sk-test", llm_model="claude-haiku-5-5"))
        assert model is not None
        assert model.name == "claude-haiku-5-5"

    def test_keys_never_show_in_the_settings_text(self, tmp_path: Path) -> None:
        settings = make_settings(
            "postgresql+psycopg://u@h/d", tmp_path, anthropic_api_key="sk-very-secret"
        )

        assert "sk-very-secret" not in repr(settings)
        assert "sk-very-secret" not in str(settings.model_dump())
