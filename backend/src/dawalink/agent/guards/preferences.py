"""High-confidence client instructions that model-written notes must not override."""

import re
from collections.abc import Sequence

_DIRECTIVE = re.compile(
    r"\b(?:want|need|prefer|choose|pick|recommend|show|badd[ie]|bed[di]+)\b|بدي|أريد|اريد|اختار",
    re.I,
)
_NEAREST = re.compile(r"\bnearest\b(?!\s+expiry)|\ba[2q]rab\b|أقرب|اقرب", re.I)
_CHEAPEST = re.compile(r"\bcheapest\b|\bar(?:kh|5|2)as\b|أرخص|ارخص", re.I)
_NEGATED = re.compile(r"\b(?:not|don't|do not|isn't|is not|mesh|mish)\b|مش|ليس", re.I)


def explicit_preference(messages: Sequence[str]) -> str | None:
    """Latest unambiguous directive; questions/comparisons do not change a preference.

    Deliberately narrow: ambiguous or negated requests remain the model's job.
    Reading client history keeps a preference across clarification-only replies.
    """
    chosen = None
    for text in re.split(r"[\n,.!?;]|\b(?:but|instead|rather)\b", "\n".join(messages), flags=re.I):
        if _NEGATED.search(text):
            if _NEAREST.search(text) or _CHEAPEST.search(text):
                chosen = "unspecified"
            continue
        matches = [
            name
            for name, pattern in (("nearest", _NEAREST), ("cheapest", _CHEAPEST))
            if pattern.search(text)
        ]
        if len(matches) != 1:
            continue
        if _DIRECTIVE.search(text) or re.fullmatch(
            r"\s*(?:nearest|cheapest)(?:\s+(?:pharmacy|option))?\s*(?:please)?[.!]?\s*",
            text,
            re.I,
        ):
            chosen = matches[0]
    return chosen
