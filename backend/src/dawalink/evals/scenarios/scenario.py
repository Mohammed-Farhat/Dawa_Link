"""What a scenario is: a situation, what is expected of the agent in it, and how it is played."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from dawalink.evals.scenarios.stage import Stage

# The seven kinds of cases a good evaluation set holds (the course's chapter 9).
Kind = Literal[
    "normal",  # expected everyday usage
    "edge",  # rare but valid
    "adversarial",  # designed to break the system
    "past_failure",  # a failure seen before (decision log, Failure Matrix)
    "ambiguous",  # the agent should ask, or say what it assumed
    "long_horizon",  # state and planning over many steps
    "tool_failure",  # a tool, the model or a service fails
]
KINDS: tuple[Kind, ...] = (
    "normal",
    "edge",
    "adversarial",
    "past_failure",
    "ambiguous",
    "long_horizon",
    "tool_failure",
)
Prescription = Literal["needed", "not_needed", "both", "none"]


@dataclass(frozen=True)
class Scenario:
    id: str  # "find.rx_clear": the family, a dot, a short name
    kind: Kind
    title: str  # one line: the situation
    # What a good agent does here, in plain words. The judge reads it as its reference.
    expected: str
    play: Callable[[Stage], None]
    # Does the scenario's medicine carry the prescription notice?
    prescription: Prescription = "none"
    # The rules of docs/04 (or decisions) the expectation comes from: "R-AG9", "BLD-D55".
    rules: Sequence[str] = ()
    # The played client: who they are (in English), and how they behave.
    facts: Sequence[str] = ()
    manner: str = "You answer what you are asked, briefly, from your facts."
    # Where and when the story starts.
    client_district: str = "Beirut"
    day: int = 0  # days after Monday 2026-11-16
    at: str = "10:00"  # Beirut time
    routing: Literal["none", "down"] = "none"  # "down": a routing service that never answers
    # Automatic checks (`checks.py`) that this story breaks on purpose: a reply that must be
    # in another language than the run's, a tool that must refuse.
    not_automatic: Sequence[str] = ()

    @property
    def family(self) -> str:
        return self.id.split(".", 1)[0]
