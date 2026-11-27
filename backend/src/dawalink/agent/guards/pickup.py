"""Unambiguous pickup-day instructions in the current client message.

Relative dates are anchored to the turn's Beirut date. Older messages are not
reinterpreted against a newer clock; ambiguous wording stays with the model.
"""

import re
from datetime import date, timedelta

_DAY = re.compile(
    r"\b(?P<two>(?:the\s+)?day after tomorrow|ba3d\s*b[ou]kra)\b|"
    r"(?P<two_ar>بعد\s*(?:بكرا|بكرة|غد(?:\u0627\u064b?)?))|"
    r"\b(?P<one>tomorrow|b[ou]kra|bokra)\b|(?P<one_ar>بكرا|بكرة|غداً|غدا)|"
    r"\b(?P<zero>today|lyom|el\s*yom)\b|(?P<zero_ar>اليوم)",
    re.I,
)
_UNCERTAIN = re.compile(
    r"\b(?:if|maybe|perhaps|either|or|can|could|possible|not|no|la2|don't|cannot|can't|"
    r"mesh|mish|eza|iza|aw|by|before|until|abl|ما|لا|لن|لم)\b|"
    r"إذا|اذا|يمكن|ممكن|مش|ليس|قبل|؟|\?",
    re.I,
)
_INTENT = re.compile(
    r"\b(?:pickup|pick(?: it| them)? up|collect|reserve|need|want|"
    r"baddi|bade|badde|bdi)\b|بدي|استلم|أستلم",
    re.I,
)
_REPLACEMENT = re.compile(r"\s+(?:instead\s+of|بدل(?:اً)?(?:\s+من)?)\s+", re.I)
_COME = re.compile(r"\bبقدر\s+[اأإ]جي\b")
_REPLACEMENT_UNCERTAIN = re.compile(
    r"\b(?:ما|لا|لن|لم|أو|او)\b|\b(?:expir\w*|appointment)\b|صلاحية|موعد", re.I
)


def _replacement_assertion(text: str, days: list[re.Match[str]]) -> str | None:
    """Keep the new day in 'new instead of old', only for a firm pickup assertion."""
    if len(days) != 2 or not _REPLACEMENT.fullmatch(text[days[0].end() : days[1].start()]):
        return None
    assertion = text[: days[0].end()] + text[days[1].end() :]
    # A leading 'No,' rejects the previous date; 'no pickup' is still negation.
    assertion = re.sub(r"^\s*(?:no|لا)[,،]\s*", "", assertion, flags=re.I)
    # Affirmative ability is not a question ('Can I ...?') or a conditional ('if ...').
    assertion = re.sub(r"\bI\s+can\b", "I", assertion, flags=re.I)
    if _UNCERTAIN.search(assertion) or _REPLACEMENT_UNCERTAIN.search(assertion):
        return None
    return assertion


def explicit_pickup_day(text: str, today: date) -> date | None:
    # Correction markers start a new assertion: "bukra la2 lyom" means today.
    clauses = re.split(
        r"\b(?:actually|instead(?!\s+of\b))\b|(?<=\S)\s+(?:no|la2)\b|لا[،,]+\s*|"
        r"(?<=\S)\s+لا\s+(?=اليوم\b|بكرا\b|بكرة\b|غدا)",
        text,
        flags=re.I,
    )
    chosen = None
    for clause in clauses:
        matches = list(_DAY.finditer(clause))
        if not matches:
            continue
        chosen = None
        replacement = _replacement_assertion(clause, matches)
        if replacement is not None:
            clause = replacement
            matches = list(_DAY.finditer(clause))
        if _UNCERTAIN.search(clause) or len(matches) != 1:
            continue
        remainder = clause[: matches[0].start()] + clause[matches[0].end() :]
        pickup_intent = _INTENT.search(clause) or (replacement is not None and _COME.search(clause))
        if not pickup_intent and re.sub(r"\bplease\b|[\s,.;!]+", "", remainder, flags=re.I):
            continue
        kind = matches[0].lastgroup or ""
        offset = 2 if kind.startswith("two") else 1 if kind.startswith("one") else 0
        chosen = today + timedelta(days=offset)
    return chosen
