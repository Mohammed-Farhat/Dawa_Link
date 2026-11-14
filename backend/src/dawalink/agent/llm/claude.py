"""Claude, through Anthropic's API: the model of the evaluation and the demo (docs/07 §10).

What is particular to Claude models is kept here:
- **no sampling settings**: the API rejects `temperature`, `top_p` and `top_k`;
- **`effort` is always sent**, because its default differs from one model to another;
- **thinking is left to the model** (adaptive); its blocks are sent back unchanged on the
  next call of the same turn, as the API requires;
- **no forced tool choice**: the newer models reject it. "Only `reply` is left" is done by
  giving the model only that tool;
- a reply can stop with **`stop_reason: "refusal"`** when a safety classifier declines.

The SDK's own retries are off: the turn decides when a retry is worth it (N-36).
"""

from typing import Any, Literal

import anthropic

from dawalink.agent.llm.base import (
    AssistantTurn,
    LLMRefused,
    LLMRejected,
    LLMUnavailable,
    ModelReply,
    Prompt,
    ToolCall,
    ToolResults,
    Usage,
    UserText,
)

Effort = Literal["low", "medium", "high"]
# Room for the model's thinking and its reply. A reply itself is at most 1,200 characters.
MAX_OUTPUT_TOKENS = 8_000


class ClaudeModel:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        effort: Effort,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.name = model
        self._effort = effort
        self._client = client or anthropic.Anthropic(api_key=api_key, max_retries=0)

    def request(self, prompt: Prompt) -> dict[str, Any]:
        """Exactly what is sent. Kept apart so a test can check it without any network."""
        system: list[dict[str, Any]] = [{"type": "text", "text": part} for part in prompt.system]
        if system:
            # Everything up to here never changes within a prompt version: the tools and
            # the fixed prompt parts are read from the cache on every later call.
            system[-1]["cache_control"] = {"type": "ephemeral"}
        return {
            "model": self.name,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
                for tool in prompt.tools
            ],
            "messages": [self._message(message) for message in prompt.messages],
            "output_config": {"effort": self._effort},
        }

    @staticmethod
    def _message(message: Any) -> dict[str, Any]:
        if isinstance(message, UserText):
            return {"role": "user", "content": message.text}
        if isinstance(message, ToolResults):
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": result.call_id,
                        "content": result.content,
                        "is_error": result.is_error,
                    }
                    for result in message.results
                ],
            }
        assert isinstance(message, AssistantTurn)
        if message.reply.raw is not None:
            # The model's own blocks, unchanged: its thinking blocks must come back as given.
            return {"role": "assistant", "content": message.reply.raw}
        blocks: list[dict[str, Any]] = []
        if message.reply.text:
            blocks.append({"type": "text", "text": message.reply.text})
        blocks += [
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
            for call in message.reply.tool_calls
        ]
        return {"role": "assistant", "content": blocks}

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        try:
            response = self._client.messages.create(**self.request(prompt), timeout=timeout_s)
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as error:
            raise LLMUnavailable(type(error).__name__) from None
        except anthropic.APIStatusError as error:
            # Only the status and the error's type are kept: a provider's message can
            # quote the request, and a request is never written to a log.
            reason = f"{type(error).__name__} ({error.status_code})"
            if error.status_code in (408, 409, 429) or error.status_code >= 500:
                raise LLMUnavailable(reason) from None
            raise LLMRejected(reason) from None
        if response.stop_reason == "refusal":
            raise LLMRefused("the model declined to answer")
        text = "".join(block.text for block in response.content if block.type == "text")
        calls = tuple(
            ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {}))
            for block in response.content
            if block.type == "tool_use"
        )
        used = response.usage
        cached = used.cache_read_input_tokens or 0
        written = used.cache_creation_input_tokens or 0
        return ModelReply(
            text=text,
            tool_calls=calls,
            usage=Usage(
                input_tokens=used.input_tokens + cached + written,
                output_tokens=used.output_tokens,
                cached_tokens=cached,
                cache_write_tokens=written,
            ),
            raw=response.content,
        )
