"""State machines as data: which change is allowed, and who may make it (docs/04 §3, §7)."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class Actor(StrEnum):
    CLIENT = "CLIENT"
    PHARMACY = "PHARMACY"
    ADMIN = "ADMIN"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"


class TransitionNotAllowed(Exception):
    def __init__(self, machine: str, current: str, target: str, actor: Actor) -> None:
        super().__init__(f"{machine}: {actor} can't move {current} to {target}")
        self.machine = machine
        self.current = current
        self.target = target
        self.actor = actor


@dataclass(frozen=True)
class StateMachine[S: StrEnum]:
    name: str
    transitions: Mapping[tuple[S, S], frozenset[Actor]]

    def allows(self, current: S, target: S, actor: Actor) -> bool:
        return actor in self.transitions.get((current, target), frozenset())

    def check(self, current: S, target: S, actor: Actor) -> None:
        if not self.allows(current, target, actor):
            raise TransitionNotAllowed(self.name, current, target, actor)

    def is_terminal(self, state: S) -> bool:
        return all(current != state for current, _ in self.transitions)

    def actors(self) -> frozenset[Actor]:
        return frozenset().union(*self.transitions.values())


def by(*actors: Actor) -> frozenset[Actor]:
    return frozenset(actors)
