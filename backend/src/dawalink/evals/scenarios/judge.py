"""A second model reads a finished scenario and scores what code can't check.

The course's chapter 9 calls this LLM-as-a-judge. How it is used here:
- **pointwise, with a reference**: the judge gets the situation, what a good agent does
  in it (`Scenario.expected`), the whole transcript with the agent's tool calls, and a
  written rubric; it gives a score of 1 to 5 on five criteria, each with its reason;
- **a different model than the agent's**, because a model prefers answers like its own;
- **never the last word on a fact**: whether a box was reserved, a tool was called or an
  order changed is read from the tables and the traces (`Stage.check`). The judge's
  scores are reported next to those checks, and a sample of its verdicts is read by a
  person (`08` §4).
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from dawalink.agent.llm.base import ChatModel, LLMError, Prompt, ToolSpec, UserText
from dawalink.evals.scenarios.client_model import IN_WORDS, Lang

CRITERIA = {
    "goal": (
        "Did the client get what they came for, as far as it was possible in this "
        "situation? When the right outcome is a refusal or a hand-over to a person, "
        "getting that, clearly and kindly, is the goal."
    ),
    "faithful": (
        "Is everything the assistant said true to what its tools returned and to what "
        "really happened? It must not claim an action nobody did (an ask to pharmacies, a "
        "watch, a hand-over), nor state a price, a pharmacy, a time or a stock it was not given."
    ),
    "follows_rules": (
        "Did it follow DawaLink's rules for this situation, as the expected behaviour "
        "states them (ask once then search, never medical advice, another brand only shown, "
        "nothing reserved without the client's tap, no special priority, and so on)?"
    ),
    "language": (
        "Is the reply in the client's own language and script, natural and easy to read "
        "for a Lebanese person on a phone, plain text, and no longer than it needs to be?"
    ),
    "path": (
        "Was the path sensible: the right tools in a sensible order, no pointless question "
        "or repeated call, the same thing never asked twice, earlier facts remembered, "
        "and a stop at the right moment?"
    ),
}
SCALE = (
    "1 = failed; 2 = major requirements missing; 3 = partially successful; "
    "4 = mostly successful, small flaws; 5 = fully successful."
)
LAYERS = (
    "model_decision",  # the model chose wrongly although it had what it needed
    "prompt",  # the instructions are missing, unclear or contradict the expectation
    "tool",  # a tool returned something wrong, incomplete or misleading
    "guard",  # a guard changed, blocked or let through a reply it should not have
    "memory",  # something said earlier was not available or not used
    "architecture",  # the turn's structure, limits or events made the right behaviour impossible
    "service_rule",  # the product's own rule produced the outcome
    "none",
)

RULES = f"""You are a strict evaluator of DawaLink's assistant, an AI agent that brings a \
client's need for a medicine to the right pharmacy in Lebanon. You read one finished \
scenario and score the assistant, never the client.

You are given: the situation, the behaviour a good assistant shows in it (your reference), \
and the transcript. The transcript has the client's messages, the assistant's replies with \
the cards shown under them, the assistant's tool calls with what each returned, and what \
the pharmacy, the team or the clock did.

Score each criterion from 1 to 5: {SCALE}

The criteria:
{chr(10).join(f"- {name}: {text}" for name, text in CRITERIA.items())}

How to judge:
- judge only what the transcript shows. A tool call's result is the truth the assistant had;
- a card is written by code and is correct by construction: judge the assistant's choice to \
show it and its words, not the card's text;
- when the reference and the transcript disagree, the assistant fell short; when the \
reference does not speak about something, don't punish it;
- a short reply that does the job is better than a long one;
- what the app, a pharmacy, the team or the clock did is the story's setting: judge how \
the assistant dealt with it, never the event itself;
- give a 5 only when you find nothing to improve on that criterion.

Then list the problems you found, each with the layer you think caused it:
{", ".join(LAYERS)}.
Say "none" when there is no problem. Call the `verdict` tool exactly once."""

TOOL = ToolSpec(
    "verdict",
    "Your scores for this scenario. One call, with every field.",
    {
        "type": "object",
        "properties": {
            **{
                f"{name}_score": {"type": "integer", "minimum": 1, "maximum": 5}
                for name in CRITERIA
            },
            **{
                f"{name}_why": {"type": "string", "description": "One or two sentences."}
                for name in CRITERIA
            },
            "problems": {
                "type": "array",
                "description": "Empty when you found no problem.",
                "items": {
                    "type": "object",
                    "properties": {
                        "what": {"type": "string"},
                        "layer": {"type": "string", "enum": list(LAYERS)},
                        "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": ["what", "layer", "severity"],
                },
            },
            "passed": {
                "type": "boolean",
                "description": "Would a careful product owner accept this conversation as it is?",
            },
        },
        "required": [
            *(f"{name}_score" for name in CRITERIA),
            *(f"{name}_why" for name in CRITERIA),
            "problems",
            "passed",
        ],
    },
)


@dataclass(frozen=True)
class Verdict:
    scores: Mapping[str, int]
    reasons: Mapping[str, str]
    problems: Sequence[Mapping[str, str]]
    passed: bool
    error: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        return {
            "scores": dict(self.scores),
            "reasons": dict(self.reasons),
            "problems": [dict(problem) for problem in self.problems],
            "passed": self.passed,
            "error": self.error,
        }


def render(transcript: Sequence[Mapping[str, Any]]) -> str:
    """The transcript as the judge reads it."""
    lines: list[str] = []
    for entry in transcript:
        who, text = entry["who"], entry.get("text") or ""
        if who == "trace":
            lines.append(f"  ({text})")
            for tool in entry.get("tools") or []:
                arguments = json.dumps(tool["arguments"], ensure_ascii=False, default=str)
                result = "ok" if tool["ok"] else "FAILED"
                lines.append(f"    tool {tool['name']}({arguments}) -> {result}: {tool['answer']}")
            continue
        lines.append(f"[{entry['at']}] {who.upper()}: {text}")
        for card in entry.get("cards") or []:
            lines.append(f"    [card] {card}")
        if entry.get("quick_replies"):
            lines.append(f"    [quick replies] {' / '.join(entry['quick_replies'])}")
    return "\n".join(lines)


def judge(
    model: ChatModel,
    *,
    title: str,
    kind: str,
    expected: str,
    lang: Lang,
    transcript: Sequence[Mapping[str, Any]],
    timeout_s: float = 120,
) -> Verdict:
    ask = (
        f"The situation ({kind}): {title}\n\n"
        f"The client writes in: {IN_WORDS[lang]}.\n\n"
        f"What a good assistant does here (your reference):\n{expected}\n\n"
        f"The transcript:\n{render(transcript)}"
    )
    prompt = Prompt(system=(RULES,), messages=(UserText(ask),), tools=(TOOL,))
    try:
        reply = model.complete(prompt, timeout_s=timeout_s)
    except LLMError as error:
        return Verdict({}, {}, (), False, error=f"{type(error).__name__}: {error}")
    for call in reply.tool_calls:
        if call.name != "verdict":
            continue
        given = call.arguments
        try:
            scores = {name: int(given[f"{name}_score"]) for name in CRITERIA}
        except (KeyError, TypeError, ValueError):
            break
        reasons = {name: str(given.get(f"{name}_why") or "") for name in CRITERIA}
        listed = given.get("problems") or []
        if isinstance(listed, str):
            # A list sent as its JSON text: read it, and count it as none if it is not one.
            try:
                listed = json.loads(listed)
            except ValueError:
                listed = []
        problems = [
            problem
            for problem in listed
            if isinstance(problem, dict) and problem.get("layer") != "none"
        ]
        accepted = given.get("passed")
        if isinstance(accepted, str):
            accepted = accepted.strip().lower() == "true"
        return Verdict(scores, reasons, problems, bool(accepted), raw=given)
    return Verdict({}, {}, (), False, error="the judge gave no usable verdict")
