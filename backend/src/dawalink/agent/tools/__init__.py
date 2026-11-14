"""The agent's tools: 6 that read, 6 that propose, 5 that act within bounds, and `reply`
(docs/07 §4, AG-D2).

There is no tool here that creates, accepts or cancels an order or a request, or that
changes stock, prices or priority (INV-11, INV-17). A test reads this list to prove it.
"""

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from dawalink.agent.llm import ToolSpec
from dawalink.agent.state import CaseNotes
from dawalink.agent.tools import act, propose, read
from dawalink.agent.tools.base import Tool, ToolError, ToolOutcome, Turn, run_tool
from dawalink.domain.vocabulary import AgentMode

ALL: tuple[Tool, ...] = (*read.TOOLS, *propose.TOOLS, *act.TOOLS)
REPLY = "reply"
MAX_REPLY_CHARS = 1_200
MAX_CARDS = 5
MAX_CHIPS = 4
MAX_CHIP_CHARS = 40


class Reply(BaseModel):
    """How every turn ends (docs/07 §4.5)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        min_length=1,
        max_length=MAX_REPLY_CHARS,
        description="What the client reads, in their language. Plain text: no links, no "
        "Markdown, no internal IDs or codes.",
    )
    proposal_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=MAX_CARDS,
        description="The cards to show, in order: proposal IDs from tools.",
    )
    quick_replies: list[Annotated[str, Field(min_length=1, max_length=MAX_CHIP_CHARS)]] = Field(
        default_factory=list,
        max_length=MAX_CHIPS,
        description="Short answers the client can tap; each only sends its text.",
    )
    case_notes: CaseNotes | None = Field(
        default=None, description="What to remember about this conversation."
    )


REPLY_SPEC = ToolSpec(
    REPLY,
    "Ends the turn: the message for the client, the cards to show, and what to remember. "
    "Every turn ends with exactly one reply.",
    Reply.model_json_schema(),
)


def for_mode(mode: AgentMode) -> dict[str, Tool]:
    """The tools a turn in this mode may call (docs/07 §2)."""
    return {tool.name: tool for tool in ALL if mode in tool.modes}


def specs(mode: AgentMode) -> tuple[ToolSpec, ...]:
    return (*(tool.spec() for tool in for_mode(mode).values()), REPLY_SPEC)


__all__ = [
    "ALL",
    "REPLY",
    "REPLY_SPEC",
    "Reply",
    "Tool",
    "ToolError",
    "ToolOutcome",
    "Turn",
    "for_mode",
    "run_tool",
    "specs",
]
