"""High-confidence language cues; ambiguous short turns inherit conversation notes."""

import re

_REFERENCE = re.compile(
    r"\b(?:R|REQ|W|Q)-[A-Z0-9]{4,}\b|"
    r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
    re.I,
)

_ARABIZI = re.compile(
    r"\b(?:baddi|bade|badde|baddak|baddik|bdi|ana|ma|fi|fiyye|fiye|"
    r"bukra|bokra|lyom|halla2|hala2|shu|shou|3ande|3andi|3al|3a|"
    r"la2|eh|siyyara|sayyara|mashi|meshye|adde|addeh|kam|yom|nhar|"
    r"7akim|saydale|saydaliyye|mawjoud|elghi|kaza|bi|s2al|fik|kamen|hayda|hayde|3elbe|3elab)\b",
    re.I,
)


def looks_arabizi(text: str) -> bool:
    # Opaque references such as R-YEM2GH are identifiers, not language cues.
    text = _REFERENCE.sub("", text)
    return (
        bool(
            re.search(
                r"\b(?:baddi|badde|bade|baddak|baddik|hayda|hayde|mawjoud|elghi)\b", text, re.I
            )
        )
        or len(_ARABIZI.findall(text)) >= 2
        or bool(re.search(r"\b[a-z]+[2378][a-z]+\b", text, re.I))
    )


def language_of(text: str, noted: str | None = None) -> str | None:
    if len(re.findall(r"[ء-ي]", text)) > len(re.findall(r"[a-z]", text, re.I)):
        return "arabic"
    if looks_arabizi(text):
        return "arabizi"
    # Short corrections ("yes", "2 boxes") do not reset an established language.
    if (
        len(re.findall(r"[a-z]+", text, re.I)) >= 3
        and len(
            re.findall(
                r"\b(?:i|you|the|need|want|would|like|please|have|will|for|cancel|"
                r"without|their|another|order|no|more|than|only|"
                r"a|an|and|or|to|of|with|by|it|is|are|this|that|my|me|"
                r"can|could|do|does|not|show|print|every|all|above|before|after)\b",
                text,
                re.I,
            )
        )
        >= 2
    ):
        return "english"
    return noted
