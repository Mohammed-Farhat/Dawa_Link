"""A client played by a model, for the conversation suite (docs/08 E7; the owner, 2026-11-15).

The scripted clients of E1 and E2 answer in fixed sentences. A person doesn't: one says
everything in the first message, another names the medicine and nothing else, a third
answers one question of three. Here a second model writes the client's messages, from a
**persona**: an invented person with a need, the truth about themselves, and a way of
telling it.

What keeps the suite measurable although the client's words are free:
- the persona's truth is fixed (from a case's labels), so code knows what a right search is;
- the playing model reports, with each message, which of the three facts the message
  states (`says`). Code then knows what the agent had been told at every turn, and can
  check that it searched only once it knew, and never asked for something twice. That
  report is the playing model's own: `score_conversations.py` says what follows from that.

Everything here is invented. No name, phone number or place of a real person is ever in
a persona.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from dawalink.agent.llm.base import ChatModel, Prompt, ToolSpec, Usage, UserText
from dawalink.evals.datasets import UCase
from dawalink.evals.score_understanding import Answer, answer_of, proposes

Fact = Literal["transport", "day", "days"]
FACTS: tuple[Fact, ...] = get_args(Fact)
Style = Literal["all_at_once", "half", "bare", "one_at_a_time"]
STYLES: tuple[Style, ...] = get_args(Style)

HOW_THEY_TELL: dict[Style, str] = {
    "all_at_once": (
        "Your first message says everything: the medicine, how you get to a pharmacy, the "
        "day you will come and for how many days you will take it."
    ),
    "half": (
        "Your first message says what you need and only this about you: {opens}. You say "
        "the rest only when the assistant asks for it."
    ),
    "bare": (
        "Your first message says only what you need. When the assistant asks you things, "
        "you answer all of them in one message."
    ),
    "one_at_a_time": (
        "Your first message says only what you need. You are distracted: when the assistant "
        "asks several things in one message, you answer only the first of them, and "
        "nothing else in that message."
    ),
}
IN_WORDS: dict[Fact, str] = {
    "transport": "how you get to a pharmacy",
    "day": "the day you will come",
    "days": "for how many days you will take the medicine",
}
LANGUAGES = {
    "english": "English",
    "arabic": "Lebanese Arabic, in Arabic script",
    "arabizi": "Lebanese Arabizi: Lebanese Arabic in Latin letters, with 3, 7 and 2 as letters",
    "mixed": "a mix of Lebanese Arabizi and English, as people text in Lebanon",
}
DAYS = ("today", "tomorrow", "the day after tomorrow")
MAX_MESSAGE = 300

RULES = """You play a person in Lebanon who needs a medicine and writes to DawaLink's \
assistant, a chat that finds pharmacies selling it at a discount. You are the client, \
never the assistant.

How you write:
- like a real person on a phone: short, informal, small mistakes are fine;
- in the language given below, and only that one;
- one message at a time, at most 300 characters;
- your first message names every medicine of your facts, with its strength.

What you may say:
- only the facts given below. Never invent a medicine, a place, a name or a number;
- never give a name, a phone number or an email;
- never ask a medical question (doses, side effects, what to take);
- your location is already shared with the app: if the assistant asks where you are, \
say that it is shared;
- if the assistant asks something the facts don't answer, say you don't know.

Every time, call exactly one tool:
- write_message, with your next message, and in `says` the facts that THIS message \
states (transport, day, days): only what the words of this message really say;
- leave, when the assistant refuses to help or keeps going in circles."""

TOOLS = (
    ToolSpec(
        "write_message",
        "Your next message to the assistant.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The message, as you would type it."},
                "says": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(FACTS)},
                    "description": "Which of your three facts this message states.",
                },
            },
            "required": ["text", "says"],
        },
    ),
    ToolSpec(
        "leave",
        "Stop writing: the assistant can't or won't help.",
        {
            "type": "object",
            "properties": {"why": {"type": "string"}},
            "required": ["why"],
        },
    ),
)


@dataclass(frozen=True)
class Persona:
    """An invented client: what they need, the truth about them, and how they tell it."""

    case: UCase
    truth: Answer
    style: Style
    opens_with: tuple[Fact, ...]  # the facts of the first message

    @property
    def id(self) -> str:
        return f"{self.case.id}:{self.style}"

    def facts(self) -> str:
        gold = self.case.gold
        need = "; ".join(
            " ".join(
                part
                for part in (item.match.name, item.match.strength, item.match.form)
                if part is not None
            )
            + f", {item.qty} box{'es' if item.qty > 1 else ''}"
            for item in gold.items
        )
        lines = [
            f"- You need: {need}.",
            "- How you get to a pharmacy: "
            + ("on foot, you have no car." if self.truth.on_foot else "by car."),
        ]
        lines.append(f"- The day you will come: {DAYS[self.truth.pickup_in_days]}.")
        lines.append(f"- You will take it for {self.truth.days_of_use} days.")
        if gold.budget is not None:
            lines.append(
                f"- You can't pay more than {gold.budget.amount:g} {gold.budget.currency} "
                "(say it in your first message)."
            )
        if gold.free_after_hour is not None:
            lines.append(f"- You are free only after {gold.free_after_hour}:00.")
        if gold.free_before_hour is not None:
            lines.append(f"- You are free only before {gold.free_before_hour}:00.")
        return "\n".join(lines)

    def brief(self) -> str:
        opens = " and ".join(IN_WORDS[fact] for fact in self.opens_with)
        return (
            f"Your facts:\n{self.facts()}\n\n"
            f"How you tell it: {HOW_THEY_TELL[self.style].format(opens=opens)}\n\n"
            f"Your language: {LANGUAGES[self.case.lang]}.\n"
            f'An example of how someone like you writes: "{self.case.text}"'
        )


def personas(cases: Sequence[UCase]) -> list[Persona]:
    """One persona per case the agent can serve, the styles in turn. The same cases give
    the same personas in every run."""
    found: list[Persona] = []
    for case in cases:
        if not proposes(case.gold):
            continue
        style = STYLES[len(found) % len(STYLES)]
        number = len(found) // len(STYLES)
        opens: tuple[Fact, ...] = ()
        if style == "all_at_once":
            opens = FACTS
        elif style == "half":
            # One fact, or two: which ones turns with the persona's number.
            first = FACTS[number % 3]
            opens = (first,) if number % 2 else (first, FACTS[(number + 1) % 3])
        found.append(Persona(case, answer_of(case.gold), style, opens))
    return found


@dataclass(frozen=True)
class Line:
    """One line of a conversation, as the playing model reads it back."""

    who: Literal["you", "assistant"]
    text: str
    cards: int = 0


@dataclass(frozen=True)
class Said:
    """What the playing model did: a message with the facts it states, or it left."""

    text: str
    says: tuple[Fact, ...] = ()
    left: bool = False
    usage: Usage = field(default_factory=Usage)


def prompt_for(persona: Persona, so_far: Sequence[Line]) -> Prompt:
    if not so_far:
        ask = "The chat is empty. Write your first message."
    else:
        lines = []
        for line in so_far:
            who = "You" if line.who == "you" else "Assistant"
            shown = (
                f"\n[the assistant showed {line.cards} card(s) to reserve]" if line.cards else ""
            )
            lines.append(f"{who}: {line.text}{shown}")
        ask = "The chat so far:\n\n" + "\n\n".join(lines) + "\n\nWrite your next message."
    return Prompt(system=(RULES, persona.brief()), messages=(UserText(ask),), tools=TOOLS)


def _facts(raw: Any) -> tuple[Fact, ...]:
    said = raw if isinstance(raw, list) else []
    return tuple(fact for fact in FACTS if fact in said)


def next_message(
    model: ChatModel, persona: Persona, so_far: Sequence[Line], *, timeout_s: float = 60
) -> Said:
    """The client's next message. A reply that is no tool call, or an empty message, is
    the client leaving: the conversation ends there and is counted as such."""
    reply = model.complete(prompt_for(persona, so_far), timeout_s=timeout_s)
    for call in reply.tool_calls:
        text = str(call.arguments.get("text") or "").strip()
        if call.name == "write_message" and text:
            says = _facts(call.arguments.get("says"))
            if not so_far:
                # The first message's facts are the persona's to choose, not the model's
                # to report: the first run had "transport" reported for a bare medicine name.
                says = tuple(fact for fact in says if fact in persona.opens_with)
            return Said(text[:MAX_MESSAGE], says, usage=reply.usage)
        break
    return Said("", left=True, usage=reply.usage)
