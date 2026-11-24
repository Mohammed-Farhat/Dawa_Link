"""Things that fail on purpose, for the "tool failure" scenarios (the course's chapter 9:
"tests robustness when tools fail").

Three kinds, each as the real failure looks to the agent:
- a tool that crashes: the model gets `INTERNAL_ERROR`, exactly what `run_tool` returns
  when a tool raises;
- the model's provider down for some calls: `LLMUnavailable`, as a timeout or a 5xx;
- the routing service down: it raises, as OpenRouteService does on a timeout.

A tool fault is keyed by the play it belongs to (its own session factory) and the client it
is for. The simulated clients have the same ids in every scenario's database, so the client
alone would let scenarios that run side by side in one process see each other's faults.
"""

import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dawalink.agent import turn as turn_module
from dawalink.agent.llm.base import ChatModel, LLMUnavailable, ModelReply, Prompt
from dawalink.agent.tools import ToolError, ToolOutcome, Turn
from dawalink.agent.tools.base import Tool
from dawalink.domain.geo import Point
from dawalink.services.travel import Mode

Key = tuple[int, uuid.UUID]  # the play (its session factory's identity), the client


def key_of(sessions: object, client_id: uuid.UUID) -> Key:
    return (id(sessions), client_id)


@dataclass
class _ToolFault:
    tool: str
    left: int | None  # how many more calls fail; None: every call


_faults: dict[Key, list[_ToolFault]] = {}
_lock = threading.Lock()
_real_run_tool = turn_module.run_tool  # type: ignore[attr-defined]
_installed = False


def _run_tool(
    turn: Turn, tools: dict[str, Tool], name: str, arguments: dict[str, Any]
) -> ToolOutcome:
    with _lock:
        fault = next(
            (
                f
                for f in _faults.get(key_of(turn.sessions, turn.client_id), [])
                if f.tool == name and f.left != 0
            ),
            None,
        )
        if fault is not None and fault.left is not None:
            fault.left -= 1
    if fault is None:
        return _real_run_tool(turn, tools, name, arguments)
    return ToolOutcome(
        name,
        False,
        ToolError.INTERNAL_ERROR,
        {
            "ok": False,
            "error_code": ToolError.INTERNAL_ERROR.value,
            "hint": "This tool failed. Try something else.",
        },
        0,
    )


def install() -> None:
    """Puts the faulty door in front of the agent's tools, once per process. With no fault
    set for a client, a call goes straight to the real `run_tool`."""
    global _installed
    with _lock:
        if not _installed:
            turn_module.run_tool = _run_tool  # type: ignore[attr-defined]
            _installed = True


def break_tool(key: Key, tool: str, *, times: int | None) -> None:
    with _lock:
        _faults.setdefault(key, []).append(_ToolFault(tool, times))


def mend_tools(key: Key) -> None:
    with _lock:
        _faults.pop(key, None)


def mend_play(sessions: object) -> None:
    """Every fault of one play is gone: called when the play ends."""
    with _lock:
        for key in [key for key in _faults if key[0] == id(sessions)]:
            del _faults[key]


class FlakyModel:
    """A model that fails its next `fail_next` calls as an unreachable provider does."""

    def __init__(self, inner: ChatModel) -> None:
        self.name = inner.name
        self._inner = inner
        self.fail_next = 0
        self.failed = 0

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        if self.fail_next > 0:
            self.fail_next -= 1
            self.failed += 1
            raise LLMUnavailable("The provider didn't answer (a fault set by the scenario).")
        return self._inner.complete(prompt, timeout_s=timeout_s)


class DownRouting:
    """A routing service that never answers."""

    def __init__(self) -> None:
        self.calls = 0

    def road_times(
        self, origins: Mapping[str, Point], destinations: Mapping[uuid.UUID, Point], mode: Mode
    ) -> Mapping[tuple[str, uuid.UUID], tuple[int, float]]:
        self.calls += 1
        raise TimeoutError("The routing service didn't answer (a fault set by the scenario).")
