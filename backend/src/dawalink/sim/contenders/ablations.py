"""The agent with one ability taken away (docs/08 E3).

Each variant is a wrapper around the model: the app, its tools and its rules are exactly
what they are for the full agent, so the only thing that changes is what the model can
do or is asked to do.
- **without early release:** the model isn't offered `request_early_release`;
- **without planning:** it isn't offered `plan_basket` nor `propose_plan`, so it searches
  and proposes medicine by medicine;
- **without re-planning:** when an event wakes it (a box marked not available, an ask
  that brought nothing, a card that failed), it only acknowledges. The first turn, the
  client's own messages and the window check are answered as usual.

How much the day loses with each one gone is what that ability is worth.
"""

from dataclasses import dataclass, replace

from dawalink.agent.llm import ChatModel, ModelReply, Prompt, ToolCall
from dawalink.sim.contenders.rules import read

VARIANTS = ("early_release", "planning", "replanning")
HIDDEN: dict[str, frozenset[str]] = {
    "early_release": frozenset({"request_early_release"}),
    "planning": frozenset({"plan_basket", "propose_plan"}),
}
NOTED = "Noted. I'll keep you posted."


@dataclass
class Without:
    """`model`, without one ability."""

    model: ChatModel
    ability: str

    def __post_init__(self) -> None:
        if self.ability not in VARIANTS:
            raise ValueError(f"an ablation is one of {VARIANTS}")
        self.name = self.model.name

    def complete(self, prompt: Prompt, *, timeout_s: float) -> ModelReply:
        if self.ability == "replanning":
            if read(prompt).trigger == "decision_event":
                reply = ToolCall("ablation-reply", "reply", {"text": NOTED})
                return ModelReply(text="", tool_calls=(reply,))
            return self.model.complete(prompt, timeout_s=timeout_s)
        hidden = HIDDEN[self.ability]
        offered = tuple(tool for tool in prompt.tools if tool.name not in hidden)
        return self.model.complete(replace(prompt, tools=offered), timeout_s=timeout_s)
