"""Ground pharmacy outreach claims in newly created requests."""

import json
import re
from collections.abc import Sequence
from typing import cast

_CONTACT_ACTION = re.compile(
    r"\b(?:asked|contacted|notified|messaged)\b|سألت|سالت|طلبت|تواصلت|راسلت|"
    r"\b(?:sa2alt|se2elt|ba3att|b3att|twasalt)\b",
    re.I,
)
_PHARMACY_CONTACT = re.compile(r"\bpharmac(?:y|ies)\b|صيدلي(?:ة|ات)|\bsaydal\w*\b", re.I)
_EXTRA_CONTACT = re.compile(
    r"\b(?:(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?"
    r"(?:more|additional|new)\s+pharmac(?:y|ies)\b|\banother pharmacy\b|"
    r"صيدلي(?:ة|ات)[^.!?؟\n]{0,20}(?:إضافي|اضافي|جديد)|"
    r"\bsaydal\w*\s+(?:zyede|ziyede|jded|jdad)\b",
    re.I,
)
_AGAIN_CONTACT = re.compile(r"\bagain\b|مجدداً|مجددًا|مرة (?:ثانية|تانية)", re.I)
_CONTACT_NEGATED = re.compile(
    r"\b(?:no|not|never|haven['\u2019]t|hasn['\u2019]t|cannot|can['\u2019]t|if)\b|"
    r"\b(?:ما|لم|لن|لا)\b|\bma\b",
    re.I,
)


def pharmacy_contact_errors(text: str, answers: Sequence[str]) -> list[str]:
    """New-contact claims need newly created asks, not a reused request's total."""
    newly_asked = 0
    for answer in answers:
        try:
            result = json.loads(answer)
        except (ValueError, TypeError):
            continue
        if not isinstance(result, dict):
            continue
        counts = [result.get(k) for k in ("asked", "newly_asked", "already_asked")]
        if not all(type(n) is int and n >= 0 for n in counts):
            continue
        total, created, reused = cast(list[int], counts)
        if total == created + reused:
            newly_asked += created
    words = {
        word: number
        for number, word in enumerate(
            ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
        )
    }
    for sentence in re.split(r"[.!?؟;\n]+", text):
        if re.match(r"\s*(?:have|has|did|were|was|هل)\b", sentence, re.I):
            continue  # A question about outreach is not a claim it happened.
        action = _CONTACT_ACTION.search(sentence)
        if action is None:
            continue
        extra = _EXTRA_CONTACT.search(sentence)
        again = _AGAIN_CONTACT.search(sentence)
        if extra is None and not (
            again and (_PHARMACY_CONTACT.search(sentence) or re.search(r"\bthem\b|معهم", sentence))
        ):
            continue
        end = max(action.end(), extra.end() if extra else again.end() if again else 0)
        if _CONTACT_NEGATED.search(sentence[:end]):
            continue
        count_text = extra.group("count") if extra else None
        count = (
            int(count_text)
            if count_text and count_text.isdecimal()
            else words.get(count_text or "", 1)
        )
        if newly_asked < count:
            return [
                f"Only {newly_asked} new pharmacy requests were created in this turn. "
                "Do not claim more/additional pharmacies were contacted or contacted again "
                "unless newly_asked supports it. Report already_asked as existing contacts."
            ]
    return []
