"""What a turn sends to a model and gets back, whichever model it is."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    """A tool as the model sees it: a name, what it is for, and its arguments' JSON schema."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    # What the model passed. It is checked by the tool, never trusted.
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Usage:
    """Tokens of one call. `input_tokens` counts everything read, cached or not."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0  # read from the provider's prompt cache (cheaper)
    cache_write_tokens: int = 0  # written to it (a little dearer)


@dataclass(frozen=True)
class ModelReply:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    # The provider's own form of this reply. It is sent back unchanged on the next call of
    # the same turn, because some models need their own reasoning blocks returned as given.
    raw: Any = None


@dataclass(frozen=True)
class UserText:
    text: str


@dataclass(frozen=True)
class AssistantTurn:
    reply: ModelReply


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    name: str
    content: str  # compact JSON
    is_error: bool = False


@dataclass(frozen=True)
class ToolResults:
    """Every tool call of the model's last message gets its result here, in one message."""

    results: tuple[ToolResult, ...]


Message = UserText | AssistantTurn | ToolResults


@dataclass(frozen=True)
class Prompt:
    # The parts that never change within a prompt version, first: a provider may cache them.
    system: tuple[str, ...]
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...]


class LLMError(Exception):
    """A model call that failed. `retryable` says whether trying again can help."""

    retryable = False


class LLMUnavailable(LLMError):
    """A timeout, a connection error, a 429 or a 5xx (docs/09 FX-1 to FX-3)."""

    retryable = True


class LLMRejected(LLMError):
    """The provider refused the call itself: a bad key, a bad request, no credit left."""


class LLMRefused(LLMError):
    """The model's safety system declined to answer (`stop_reason: "refusal"`)."""


class ChatModel(Protocol):
    name: str

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        """One call. Raises an `LLMError`; never retries by itself."""
        ...


# USD per million tokens: (input, output). Docs/02 §10 lists the candidates.
_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
    "claude-sonnet-5-5": (Decimal("2"), Decimal("10")),
    "claude-opus-5-5": (Decimal("4"), Decimal("20")),
}
_CACHE_READ = Decimal("0.1")  # a cached token costs a tenth of an input token
_CACHE_WRITE = Decimal("1.25")
_MILLION = Decimal(1_000_000)


def cost_usd(model: str, usage: Usage) -> Decimal:
    """What one call cost. A model with no price here (the local one, the scripted one) is free."""
    prices = _PRICES.get(model)
    if prices is None:
        return Decimal(0)
    per_input, per_output = prices
    plain = usage.input_tokens - usage.cached_tokens - usage.cache_write_tokens
    cost = (
        max(plain, 0) * per_input
        + usage.cached_tokens * per_input * _CACHE_READ
        + usage.cache_write_tokens * per_input * _CACHE_WRITE
        + usage.output_tokens * per_output
    ) / _MILLION
    return cost.quantize(Decimal("0.000001"))


def has_price(model: str) -> bool:
    return model in _PRICES
