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
    r"mesh|mish|eza|iza|aw|by|before|until|abl)\b|إذا|اذا|يمكن|ممكن|مش|ليس|قبل|؟|\?",
    re.I,
)
_INTENT = re.compile(
    r"\b(?:pickup|pick(?: it| them)? up|collect|reserve|need|want|"
    r"baddi|bade|badde|bdi)\b|بدي|استلم|أستلم",
    re.I,
)


def explicit_pickup_day(text: str, today: date) -> date | None:
    # Correction markers start a new assertion: "bukra la2 lyom" means today.
    clauses = re.split(
        r"\b(?:actually|instead)\b|(?<=\S)\s+(?:no|la2)\b|لا[،,\s]+", text, flags=re.I
    )
    chosen = None
    for clause in clauses:
        matches = list(_DAY.finditer(clause))
        if not matches:
            continue
        chosen = None
        if _UNCERTAIN.search(clause) or len(matches) != 1:
            continue
        remainder = clause[: matches[0].start()] + clause[matches[0].end() :]
        if not _INTENT.search(clause) and re.sub(
            r"\bplease\b|[\s,.;!]+", "", remainder, flags=re.I
        ):
            continue
        kind = matches[0].lastgroup or ""
        offset = 2 if kind.startswith("two") else 1 if kind.startswith("one") else 0
        chosen = today + timedelta(days=offset)
    return chosen
