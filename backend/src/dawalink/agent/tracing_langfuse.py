"""Sending a turn's trace to Langfuse (docs/07 §9.1; docs/10 §4.3).

The trace is sent once, when the turn is over: an `agent_turn` with one child per step
(each model call, each tool call, the guards, the save). Langfuse's client batches and
sends in the background, so a turn never waits for it.

Each step's real duration is in its metadata (`duration_ms`): the client stamps a step
when it is recorded, not when it happened. The latencies used for the metrics come from
`agent_runs` and `agent_tool_calls` anyway.

**Masking**: everything a trace holds was already redacted. The client's `mask` hook
removes email, phone and coordinate patterns once more before anything leaves (TM-D9).

**Only our own steps are sent.** Langfuse's client listens to every library that reports
through OpenTelemetry, and Anthropic's library does: seen on the first real run
(2026-11-14), each model call also arrived as a separate `anthropic.messages.create`
entry. It held token counts and no text, but it counted every call's cost twice and it
was nothing we had chosen to send. `should_export_span` keeps to what `send` builds.
"""

from typing import Any

from langfuse import Langfuse
from langfuse.span_filter import is_langfuse_span

from dawalink.agent.guards.redact import redact
from dawalink.agent.tracing import Span, TurnTrace
from dawalink.domain.numbers import HTTP_TIMEOUT_S

_KINDS = {"generation": "generation", "tool": "tool", "span": "span"}


def mask(*, data: Any, **_: Any) -> Any:
    """Removes personal-detail patterns from anything about to be sent."""
    if isinstance(data, str):
        return redact(data).text
    if isinstance(data, dict):
        return {key: mask(data=value) for key, value in data.items()}
    if isinstance(data, list | tuple):
        return [mask(data=value) for value in data]
    return data


class LangfuseTracer:
    def __init__(self, *, public_key: str, secret_key: str, host: str, release: str) -> None:
        self._client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
            release=release,
            timeout=HTTP_TIMEOUT_S,
            mask=mask,
            should_export_span=is_langfuse_span,
        )

    def new_trace_id(self) -> str:
        return Langfuse.create_trace_id()

    def send(self, trace: TurnTrace) -> None:
        root = self._client.start_observation(
            trace_context={"trace_id": trace.trace_id},
            name="agent_turn",
            as_type="agent",
            metadata=trace.metadata,
        )
        try:
            for span in trace.spans:
                self._child(root, span)
            root.update(output=trace.output)
        finally:
            root.end()

    @staticmethod
    def _child(root: Any, span: Span) -> None:
        metadata = {
            **span.metadata,
            "started_s": round(span.started, 3),
            "duration_ms": int((span.ended - span.started) * 1000),
        }
        details: dict[str, Any] = {}
        if span.kind == "generation":
            details = {
                "model": span.metadata.get("model"),
                "usage_details": {
                    "input": int(span.metadata.get("input_tokens", 0)),
                    "output": int(span.metadata.get("output_tokens", 0)),
                },
                "cost_details": {"total": float(span.metadata.get("cost_usd", 0) or 0)},
            }
        child = root.start_observation(
            name=span.name,
            as_type=_KINDS.get(span.kind, "span"),
            input=span.input,
            output=span.output,
            metadata=metadata,
            level="ERROR" if span.metadata.get("error") else None,
            **details,
        )
        child.end()

    def flush(self) -> None:
        """Sends what is still waiting. Called when the process stops."""
        self._client.flush()
