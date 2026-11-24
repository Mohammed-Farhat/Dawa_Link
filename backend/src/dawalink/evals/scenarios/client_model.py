"""The client of a scenario, played by a model.

A scenario's first message is usually written by hand, in the three languages, so that
every language starts from the same words. What comes next can't be scripted: it depends
on what the agent asks. So a second model answers as the client, from a **brief**: the
facts about this person, and how they behave.

Unlike the played client of suite E7 (`evals/played_client.py`), this one has no fixed
list of three facts: the brief says whatever the scenario needs, and what the agent did
with it is checked from the tables and the traces, never from the playing model's word.

Everything in a brief is invented.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from dawalink.agent.llm.base import ChatModel, Prompt, ToolSpec, Usage, UserText

Lang = Literal["english", "arabizi", "arabic"]
LANGS: tuple[Lang, ...] = ("english", "arabizi", "arabic")
IN_WORDS: dict[Lang, str] = {
    "english": "English",
    "arabizi": (
        "Lebanese Arabizi: Lebanese Arabic written in Latin letters, with 2, 3, 5 and 7 "
        'as letters ("baddi", "3ande", "7abbe"). No Arabic script, no full English sentences'
    ),
    "arabic": "Lebanese Arabic, in Arabic script",
}
MAX_MESSAGE = 400

RULES = """You play a person in Lebanon who writes to DawaLink's assistant, a chat that \
finds pharmacies selling a medicine at a discount. You are the client, never the assistant.

How you write:
- like a real person on a phone: short, informal, small mistakes are fine;
- in the language given below, and only that one (a medicine's name stays as it is);
- one message at a time, at most 300 characters.

What you may say:
- only the facts given below. Never invent a medicine, a place, a name or a number;
- when the assistant asks something the facts answer, answer it from the facts;
- when it asks something the facts don't answer, say that you don't know or that anything \
is fine;
- never give a name, a phone number or an email, unless the facts tell you to;
- never ask a medical question, unless the facts tell you to;
- follow "How you behave" exactly: it says what kind of person you are in this chat.

Every time, call exactly one tool:
- write_message, with your next message;
- leave, when you have what you came for, when the assistant refuses to help, or when it \
keeps going in circles."""

TOOLS = (
    ToolSpec(
        "write_message",
        "Your next message to the assistant.",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The message, as you would type it."}
            },
            "required": ["text"],
        },
    ),
    ToolSpec(
        "leave",
        "Stop writing.",
        {"type": "object", "properties": {"why": {"type": "string"}}, "required": ["why"]},
    ),
)


@dataclass(frozen=True)
class Brief:
    """Who the played client is in this scenario."""

    facts: Sequence[str]  # in English; the playing model says them in its own language
    manner: str = "You answer what you are asked, briefly, from your facts."

    def text(self, lang: Lang) -> str:
        facts = "\n".join(f"- {fact}" for fact in self.facts)
        return (
            f"Your facts:\n{facts}\n\nHow you behave: {self.manner}\n\n"
            f"Your language: {IN_WORDS[lang]}."
        )


@dataclass(frozen=True)
class Line:
    who: Literal["you", "assistant", "team", "app"]
    text: str
    cards: Sequence[str] = ()  # what each card under the message says, in a line


@dataclass(frozen=True)
class Said:
    text: str
    left: bool = False
    why: str = ""
    usage: Usage = field(default_factory=Usage)


_WHO = {"you": "You", "assistant": "Assistant", "team": "DawaLink team (a person)", "app": "App"}


def prompt_for(brief: Brief, lang: Lang, so_far: Sequence[Line]) -> Prompt:
    if not so_far:
        ask = "The chat is empty. Write your first message."
    else:
        lines = []
        for line in so_far:
            cards = "".join(f"\n[card: {card}]" for card in line.cards)
            lines.append(f"{_WHO[line.who]}: {line.text}{cards}")
        ask = "The chat so far:\n\n" + "\n\n".join(lines) + "\n\nWrite your next message."
    return Prompt(system=(RULES, brief.text(lang)), messages=(UserText(ask),), tools=TOOLS)


def next_message(
    model: ChatModel, brief: Brief, lang: Lang, so_far: Sequence[Line], *, timeout_s: float = 60
) -> Said:
    """The client's next message. A reply with no tool call, or an empty message, is the
    client leaving."""
    reply = model.complete(prompt_for(brief, lang, so_far), timeout_s=timeout_s)
    for call in reply.tool_calls:
        text = str(call.arguments.get("text") or "").strip()
        if call.name == "write_message" and text:
            return Said(text[:MAX_MESSAGE], usage=reply.usage)
        if call.name == "leave":
            return Said("", left=True, why=str(call.arguments.get("why") or ""), usage=reply.usage)
        break
    return Said("", left=True, why="no message", usage=reply.usage)
