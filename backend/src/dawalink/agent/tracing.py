"""One trace per turn (docs/07 §9.1, AG-D14; docs/09 FX-6).

A turn collects what happened in a `TurnTrace`: its spans, their timings, and the
already-redacted text. When the turn is over, the trace is handed to a `Tracer`.

Tracing is best-effort (FM-D3): a tracer that fails is logged and forgotten, and the turn
is never affected. The numbers that matter are also in `agent_runs` and
`agent_tool_calls`, which don't depend on it.
"""

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

log = structlog.get_logger(__name__)


@dataclass
class Span:
    name: str
    kind: str = "span"  # "span", "generation" or "tool"
    started: float = 0.0  # seconds since the turn began
    ended: float = 0.0
    input: Any = None
    output: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnTrace:
    """Everything a trace of one turn holds. Nothing in it is unredacted (INV-10)."""

    trace_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    output: Any = None
    _zero: float = field(default_factory=time.monotonic)

    @contextmanager
    def span(self, name: str, kind: str = "span", **metadata: Any) -> Iterator[Span]:
        """Times a step of the turn. It is recorded even if the step raises."""
        current = Span(name, kind, started=time.monotonic() - self._zero, metadata=dict(metadata))
        try:
            yield current
        finally:
            current.ended = time.monotonic() - self._zero
            self.spans.append(current)


class Tracer(Protocol):
    def new_trace_id(self) -> str: ...

    def send(self, trace: TurnTrace) -> None:
        """Hands a finished trace over. May raise; the caller doesn't care."""
        ...


class NoTracer:
    """No keys are set: turns are recorded in our own tables only."""

    def new_trace_id(self) -> str:
        return uuid.uuid4().hex

    def send(self, trace: TurnTrace) -> None:
        return None


def send_safely(tracer: Tracer, trace: TurnTrace) -> bool:
    """Sends the trace; a failure is counted in the log and nothing else happens (FX-6)."""
    try:
        tracer.send(trace)
    except Exception as error:
        log.warning("trace_dropped", trace_id=trace.trace_id, error=type(error).__name__)
        return False
    return True
