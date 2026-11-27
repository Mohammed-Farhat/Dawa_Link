"""Explicit pharmacy scope, separate from the client's saved location.

Names are matched to our own area list, not geocoded or guessed. Ambiguous names
remain names: the existing area tool resolves or refuses them before searching.
"""

import re
from collections.abc import Sequence

from dawalink.agent.state import SearchArea, SearchScope
from dawalink.domain import places
from dawalink.domain.places import Place

_NEAREST = re.compile(
    r"\b(?:nearest|near\s+(?:me|my\s+home)|close\s+to\s+(?:me|my\s+home)|"
    r"a2rab|2arib\s+menni|(?:don't|do not)\s+know\s+where)\b|"
    r"الأقرب|الاقرب|أقرب|اقرب|قريب مني|ما بعرف وين",
    re.I,
)
_ANYWHERE = re.compile(
    r"\b(?:anywhere|any\s+(?:area|place)|just\s+(?:find|search|look)|"
    r"ayya?\s+ma?kan)\b|"
    r"أي مكان|اي مكان|أي منطقة|اي منطقة|وين ما كان|بس دور",
    re.I,
)
_QUESTION = re.compile(
    r"\bwhich\s+(?:area|town|district)\b|أي منطقة|اي منطقة|"
    r"\bwhere\b[^?\n]{0,100}\b(?:pharmac|pick|search|look)|"
    r"\bnearest\b[^?\n]{0,100}\banywhere\b|"
    r"وين[^؟\n]{0,100}(?:صيدلي|بدك|نفتش|ابحث)|"
    r"\b(?:wen|wein)\b[^?\n]{0,100}\b(?:saydal|bedak|baddak)|"
    r"\ba2rab\b[^?\n]{0,100}\b(?:makan|manti2a)",
    re.I,
)
_NEGATIVE = re.compile(r"\b(?:not|no|mish|mesh)\s*$|(?:مش|لا)\s*$", re.I)
_ORIGIN = re.compile(
    r"(?:\bi(?:\s+(?:am|live)|'m)|\bana|أنا|انا)\s*"
    r"(?:(?:currently|now)\s+)?(?:in|fi|bel|bi|ساكنة?|ب|في)?\s*$",
    re.I,
)
_IN = re.compile(r"(?:\b(?:in|within|fi|bel|bi)|في|بمنطقة)\s*$", re.I)
_CONNECTOR = re.compile(r"^\s*(?:or|and|أو|او|و|,)\s*$", re.I)
_BARE = re.compile(r"\b(?:only|please|or|and|in)\b|بس|فقط|أو|او|[\s,.;!]+", re.I)


def asks_scope(text: str) -> bool:
    return bool(_QUESTION.search(text))


def explicit_scope(text: str, known: Sequence[Place]) -> SearchScope | None:
    """None means no new scope assertion; it must not overwrite an established choice."""
    choices = [
        (m.start(), kind)
        for pattern, kind in ((_NEAREST, "nearest"), (_ANYWHERE, "anywhere"))
        for m in pattern.finditer(text)
        if not _NEGATIVE.search(text[max(0, m.start() - 16) : m.start()])
    ]
    tokens = list(re.finditer(r"[\w'-]+", text))
    aliases = {alias for place in known for alias in place.keys}
    matches: list[tuple[int, int, str, bool]] = []
    for index, token in enumerate(tokens):
        for length in range(min(4, len(tokens) - index), 0, -1):
            end = tokens[index + length - 1].end()
            raw = text[token.start() : end]
            prefixed = raw.startswith("ب") and places.key(raw[1:]) in aliases
            if places.key(raw) in aliases or prefixed:
                matches.append((token.start(), end, raw[1:] if prefixed else raw, prefixed))
                break
    # Keep the longest non-overlapping names (e.g. Ras Beirut, not also Beirut).
    named: list[tuple[int, int, str, bool]] = []
    for match in sorted(matches, key=lambda m: (m[0], -m[1])):
        if not named or match[0] >= named[-1][1]:
            named.append(match)
    remainder = text
    for start, end, _, _ in reversed(named):
        remainder = remainder[:start] + remainder[end:]
    bare = bool(named) and not _BARE.sub("", remainder)
    wanted: list[SearchArea] = []
    previous_end = 0
    for start, end, name, prefixed in named:
        prefix = text[:start]
        if _ORIGIN.search(prefix) or _NEGATIVE.search(prefix):
            continue
        if wanted and re.fullmatch(r"\s*(?:in|في)\s*", text[previous_end:start]):
            districts = [p.district for p in places.named(known, name) if p.whole_district]
            if len(set(districts)) == 1 and places.named(known, wanted[-1].place, districts[0]):
                wanted[-1].district = districts[0]
                previous_end = end
                continue
        if (
            bare
            or prefixed
            or _IN.search(prefix)
            or (wanted and _CONNECTOR.fullmatch(text[previous_end:start]))
        ):
            wanted.append(SearchArea(place=name))
            previous_end = end
    if wanted and len(wanted) <= 3:
        return SearchScope(kind="areas", areas=wanted)
    if choices:
        # The model cannot supply this field through case_notes.
        kind = max(choices)[1]
        return SearchScope(kind="nearest" if kind == "nearest" else "anywhere")
    unknown = re.search(r"(?:\bin|في|بمنطقة)\s+([^\W\d_][^,.!?؟\n]{1,59})", text, re.I)
    if unknown and not _ORIGIN.search(text[: unknown.start(1)]):
        name = unknown.group(1).strip()
        if not re.fullmatch(r"(?:one|two|three|seven|ten)\s+days?", name, re.I):
            return SearchScope(kind="areas", areas=[SearchArea(place=name)])
    return None
