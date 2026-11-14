"""A model that plays a script: for tests, where every turn must be the same and free.

Each step is what the model "says" next: a reply, an error to raise, or a function that
looks at the prompt first. Everything it was sent is kept in `seen`, so a test can check
what would have reached a real model.
"""

import itertools
import json
from collections.abc import Callable
from typing import Any

from dawalink.agent.llm.base import ModelReply, Prompt, ToolCall, Usage

Step = ModelReply | BaseException | Callable[[Prompt], ModelReply]
_ids = itertools.count(1)


def call(name: str, /, **arguments: Any) -> ModelReply:
    """The model calls one tool."""
    return calls((name, arguments))


def calls(*tool_calls: tuple[str, dict[str, Any]]) -> ModelReply:
    """The model calls several tools in one message."""
    return ModelReply(
        text="",
        tool_calls=tuple(
            ToolCall(id=f"call_{next(_ids)}", name=name, arguments=arguments)
            for name, arguments in tool_calls
        ),
        usage=Usage(input_tokens=100, output_tokens=20),
    )


def reply(text: str, /, **more: Any) -> ModelReply:
    """The model ends the turn with the `reply` tool."""
    return call("reply", text=text, **more)


def say(text: str) -> ModelReply:
    """The model answers in plain text, without calling `reply` (small models do)."""
    return ModelReply(text=text, usage=Usage(input_tokens=100, output_tokens=20))


class ScriptedModel:
    name = "scripted"

    def __init__(self, *steps: Step) -> None:
        self._steps = list(steps)
        self.seen: list[Prompt] = []

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        self.seen.append(prompt)
        if not self._steps:
            raise AssertionError("The script has no step left for this model call.")
        step = self._steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return step(prompt)
        return step

    @property
    def steps_left(self) -> int:
        return len(self._steps)

    def everything_sent(self) -> str:
        """All the text a real model would have received, in one string."""
        parts: list[str] = []
        for prompt in self.seen:
            parts.extend(prompt.system)
            parts.extend(json.dumps(tool.__dict__, default=str) for tool in prompt.tools)
            for message in prompt.messages:
                parts.append(json.dumps(_plain(message), default=str, ensure_ascii=False))
        return "\n".join(parts)


def _plain(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {name: _plain(getattr(value, name)) for name in value.__dataclass_fields__}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value
