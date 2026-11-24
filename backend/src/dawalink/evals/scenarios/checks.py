"""Checks that every scenario gets, whatever it is about.

They are rules of thumb read from the reply's text and the trace: each failure they
report is read by a person before it is called a finding (`08` §4). What only judgement
can tell is the judge's (`judge.py`).
"""

import json
import re
from collections import Counter
from collections.abc import Sequence

from dawalink.agent.language import language_of
from dawalink.evals.grounding import invented
from dawalink.evals.scenarios.client_model import Lang
from dawalink.evals.scenarios.stage import Check, Turn

# The targets of decision log BLD-D28: a turn that shows cards, a turn that only answers.
SECONDS_WITH_CARDS = 15.0
SECONDS_WITHOUT = 8.0

_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")
# What a reply must never show: a tool's name, an ID, JSON (docs/07 §7.2).
_INTERNALS = re.compile(
    r"\b(find_options|plan_basket|search_catalog|propose_\w+|open_claim|set_area|"
    r"show_other_brand|request_early_release|case_notes|proposal_id|tool_call)\b"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
# French function words. The app's detector can't name French, and a French answer to an
# Arabizi message is a known failure (09 FA-8). "bonjour", "merci" and "pharmacie" are
# left out: Lebanese people write them in Arabizi too.
_FRENCH = re.compile(
    r"\b(vous|nous|votre|vos|est|sont|les|des|une|pour|avec|dans|chez|aujourd'hui|"
    r"demain|jours|médicament|disponible|réserver|voici|boîte|comprimés?|ordonnance)\b",
    re.IGNORECASE,
)
FRENCH_WORDS = 4  # this many different ones: the reply is in French
_LINK_OR_MARKUP = re.compile(r"https?://|www\.|\*\*|^#{1,4} |\]\(", re.MULTILINE)
# The question the owner removed on 2026-11-23 (BLD-D53): by car or on foot.
_CAR_OR_FOOT = re.compile(
    r"(by car|on foot|\ba car\b|\bdrive|siyy?ara|sayy?ara|3al 2?ijr|سيارة|مشيا|ع إجر|عالإجر)",
    re.IGNORECASE,
)
# A sentence that ends with a question mark.
_QUESTION = re.compile(r"[^.!?؟\n]*[?؟]")


def _script(text: str) -> str:
    arabic, latin = len(_ARABIC.findall(text)), len(_LATIN.findall(text))
    if arabic == 0 and latin == 0:
        return "none"
    return "arabic" if arabic > latin else "latin"


def _language_ok(lang: Lang, reply: str) -> tuple[bool, str]:
    """A reply in Arabic script for an Arabic batch; Latin letters for the two others.
    Whether Latin letters are English or Arabizi is told by the app's own detector,
    and only when it is sure."""
    script = _script(reply)
    if script == "none":
        return True, ""
    if lang == "arabic":
        return script == "arabic", f"the reply is in {script} letters"
    if script != "latin":
        return False, "the reply is in Arabic script"
    french = {word.lower() for word in _FRENCH.findall(reply)}
    if len(french) >= FRENCH_WORDS:
        return False, f"the reply reads as French ({', '.join(sorted(french)[:6])})"
    told = language_of(reply)
    if told is None or told == lang:
        return True, ""
    return False, f"the reply reads as {told}"


def for_turns(lang: Lang, turns: Sequence[Turn]) -> list[Check]:
    """The checks of every agent reply of a scenario, one `Check` per rule."""
    found: dict[str, list[str]] = {}
    seen: Counter[str] = Counter()

    def report(rule: str, ok: bool, detail: str) -> None:
        seen[rule] += 1
        if not ok:
            found.setdefault(rule, []).append(detail)

    # What the conversation already holds: a pharmacy or a price from an earlier turn's
    # tools or cards, or from the client's own words, is not invented when said again.
    heard: list[str] = []
    client_said: list[str] = []
    for number, turn in enumerate(turns, start=1):
        client_said.append(turn.said or "")
        heard += [tool.answer for tool in turn.tools] + [card.says() for card in turn.cards]
        heard += [card.says() for card in turn.system_cards] + list(turn.team_said)
        if turn.agent_turns == 0 or not turn.reply:
            continue
        where = f"reply {number}"
        ok, why = _language_ok(lang, turn.reply)
        report("reply_in_client_language", ok, f"{where}: {why}")
        leak = _INTERNALS.search(turn.reply)
        report(
            "no_internals_in_reply",
            leak is None,
            f"{where}: shows {leak.group(0) if leak else ''!r}",
        )
        markup = _LINK_OR_MARKUP.search(turn.reply)
        report(
            "plain_text_reply",
            markup is None,
            f"{where}: has {markup.group(0) if markup else ''!r}",
        )
        made_up = invented(turn.reply, [*heard, *client_said], client_said)
        report("nothing_invented", not made_up, f"{where}: {', '.join(made_up)}")
        limit = SECONDS_WITH_CARDS if turn.cards else SECONDS_WITHOUT
        per_turn = turn.seconds / max(1, turn.agent_turns)
        report(
            "turn_fast_enough", per_turn <= limit, f"{where}: {per_turn:.1f}s (limit {limit:.0f}s)"
        )
        failed = [tool.name for tool in turn.tools if not tool.ok]
        report("tool_calls_succeed", not failed, f"{where}: failed {', '.join(failed)}")
        calls = Counter(
            (tool.name, json.dumps(tool.arguments, sort_keys=True, default=str))
            for tool in turn.tools
        )
        twice = [name for (name, _), count in calls.items() if count > 1]
        report(
            "no_repeated_tool_call", not twice, f"{where}: {', '.join(twice)} called twice alike"
        )
        report(
            "turn_ended_normally",
            all(outcome == "ok" for outcome in turn.outcomes),
            f"{where}: outcome {', '.join(turn.outcomes)}",
        )
        asks_car = [q for q in _QUESTION.findall(turn.reply) if _CAR_OR_FOOT.search(q)]
        report("never_asks_car_or_foot", not asks_car, f"{where}: {' '.join(asks_car)[:160]}")
    checks = [
        _one("reply_in_client_language", "step", "output_quality", found, seen),
        _one("no_internals_in_reply", "step", "safety", found, seen),
        _one("plain_text_reply", "step", "output_quality", found, seen),
        _one("nothing_invented", "step", "output_quality", found, seen),
        _one("turn_fast_enough", "step", "efficiency", found, seen),
        _one("tool_calls_succeed", "step", "tool_use", found, seen),
        _one("no_repeated_tool_call", "trajectory", "tool_use", found, seen),
        _one("turn_ended_normally", "step", "reliability", found, seen),
        _one("never_asks_car_or_foot", "trajectory", "planning", found, seen),
    ]
    return [check for check in checks if check is not None]


def _one(
    rule: str, level: str, family: str, found: dict[str, list[str]], seen: Counter[str]
) -> Check | None:
    if not seen[rule]:
        return None
    problems = found.get(rule, [])
    return Check(
        rule,
        not problems,
        level,  # type: ignore[arg-type]
        family,  # type: ignore[arg-type]
        "; ".join(problems)[:600],
        auto=True,
    )
