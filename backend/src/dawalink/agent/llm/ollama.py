"""The local model, through Ollama: for development only (docs/07 §10, decision log T13).

It costs nothing and needs no network, so it is what a developer chats with while
building. It is a small model: it proves the plumbing, not the agent's quality, which is
measured on Claude models (docs/08).

Two things matter for a small local model:
- the **context length is set explicitly**. Ollama's default is small, and a prompt that
  doesn't fit is cut from the front without a word: the hard rules would be the first
  to go;
- **temperature 0**, so the same input gives the same answer while debugging.
"""

import json
import re
import uuid
from typing import Any

import httpx2

from dawalink.agent.llm.base import (
    AssistantTurn,
    LLMRejected,
    LLMUnavailable,
    ModelReply,
    Prompt,
    ToolCall,
    ToolResults,
    Usage,
    UserText,
)

DEFAULT_MODEL = "qwen2.5:7b"
# Tokens the model reads. A turn's prompt is about 6,000 to 9,000 tokens. This size
# still fits an 8 GB graphics card; a larger one spills to the CPU and is 15 times slower.
CONTEXT_TOKENS = 12_288
_TAGGED_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


class OllamaModel:
    def __init__(
        self,
        *,
        base_url: str,
        model: str = DEFAULT_MODEL,
        context_tokens: int = CONTEXT_TOKENS,
        client: httpx2.Client | None = None,
    ) -> None:
        self.name = model
        self._context_tokens = context_tokens
        self._client = client or httpx2.Client(base_url=base_url)

    def request(self, prompt: Prompt) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "system", "content": "\n\n".join(prompt.system)}]
        for message in prompt.messages:
            if isinstance(message, UserText):
                messages.append({"role": "user", "content": message.text})
            elif isinstance(message, AssistantTurn):
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.reply.text,
                        "tool_calls": [
                            {"function": {"name": call.name, "arguments": call.arguments}}
                            for call in message.reply.tool_calls
                        ],
                    }
                )
            else:
                assert isinstance(message, ToolResults)
                messages += [
                    {"role": "tool", "tool_name": result.name, "content": result.content}
                    for result in message.results
                ]
                if message.note:
                    messages.append({"role": "user", "content": message.note})
        return {
            "model": self.name,
            "messages": messages,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in prompt.tools
            ],
            "stream": False,
            "options": {"temperature": 0, "num_ctx": self._context_tokens},
        }

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        try:
            response = self._client.post("/api/chat", json=self.request(prompt), timeout=timeout_s)
        except httpx2.TransportError as error:
            # Not running, or too slow: the same as any provider being down (FX-5).
            raise LLMUnavailable(f"Ollama: {type(error).__name__}") from None
        if response.status_code >= 500:
            raise LLMUnavailable(f"Ollama answered {response.status_code}")
        if response.status_code >= 400:
            raise LLMRejected(f"Ollama answered {response.status_code}")
        body = response.json()
        message = body.get("message") or {}
        text = str(message.get("content") or "")
        calls = [_call(item.get("function") or {}) for item in message.get("tool_calls") or []]
        if not calls:
            # Some small models write the call into their text instead.
            tagged = _TAGGED_CALL.findall(text)
            calls = [_call(_json(found)) for found in tagged]
            if calls:
                text = _TAGGED_CALL.sub("", text).strip()
        return ModelReply(
            text=text,
            tool_calls=tuple(call for call in calls if call is not None),
            usage=Usage(
                input_tokens=int(body.get("prompt_eval_count") or 0),
                output_tokens=int(body.get("eval_count") or 0),
            ),
        )


def _json(text: str) -> dict[str, Any]:
    try:
        found = json.loads(text)
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def _call(function: dict[str, Any]) -> ToolCall | None:
    name = function.get("name")
    if not name:
        return None
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        arguments = _json(arguments)
    return ToolCall(
        id=f"call_{uuid.uuid4().hex[:12]}",
        name=str(name),
        arguments=arguments if isinstance(arguments, dict) else {},
    )
