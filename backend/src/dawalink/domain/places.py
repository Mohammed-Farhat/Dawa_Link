"""Finding the area a client named: "Hamra", "el hamra", "الحمرا" (docs/04 R-S2).

A client who doesn't share their phone's location can say where they are. The agent passes
the name to code; code looks it up in our own list of areas and uses that area's centre.
The model never sees a coordinate, and no outside service receives what the client typed.

A name is accepted only when it is the same as a listed one once both are simplified
(`key`). Anything less is returned as "close", and the agent or the client chooses: a
wrong area would send the client to the wrong pharmacy without anyone noticing.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

# The Arabic article as people write it in Latin letters ("el Hamra", "Ras en Nabaa").
_ARTICLES = frozenset({"el", "al", "l", "ed", "er", "es", "ech", "en", "et", "ez"})
_ARABIC_ARTICLE = "ال"
# Letters that are written in more than one way.
_SAME_ARABIC_LETTER = str.maketrans(
    {
        "\N{ARABIC LETTER ALEF WITH HAMZA ABOVE}": "\N{ARABIC LETTER ALEF}",
        "\N{ARABIC LETTER ALEF WITH HAMZA BELOW}": "\N{ARABIC LETTER ALEF}",
        "\N{ARABIC LETTER ALEF WITH MADDA ABOVE}": "\N{ARABIC LETTER ALEF}",
        "\N{ARABIC LETTER TEH MARBUTA}": "\N{ARABIC LETTER HEH}",
        "\N{ARABIC LETTER ALEF MAKSURA}": "\N{ARABIC LETTER YEH}",
    }
)
_NOT_A_LETTER = re.compile(r"[\W_]+")

CLOSE_ENOUGH = 0.6  # how alike two names must be to be suggested
MAX_SUGGESTIONS = 5


@dataclass(frozen=True)
class Place:
    """One listed area with every way it is written."""

    id: int
    name: str
    district: str
    other_names: tuple[str, ...] = ()
    # True for a row that stands for a whole district ("Chouf"): its centre is a rough start.
    whole_district: bool = False

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(key(name) for name in (self.name, *self.other_names)) - {""}


def key(text: str) -> str:
    """A name without case, accents, spaces, hyphens or the article: what is compared."""
    plain = "".join(
        letter
        for letter in unicodedata.normalize("NFKD", text.translate(_SAME_ARABIC_LETTER))
        if not unicodedata.combining(letter)
    )
    words = []
    for word in _NOT_A_LETTER.sub(" ", plain.lower()).split():
        if word in _ARTICLES:
            continue
        if word.startswith(_ARABIC_ARTICLE) and len(word) > len(_ARABIC_ARTICLE) + 1:
            word = word[len(_ARABIC_ARTICLE) :]
        words.append(word)
    return "".join(words)


def named(places: Iterable[Place], text: str, district: str | None = None) -> list[Place]:
    """The places written exactly like `text`, in `district` only when one is given."""
    wanted = key(text)
    if not wanted:
        return []
    found = [place for place in places if wanted in place.keys]
    if district is not None and key(district):
        found = [place for place in found if key(place.district) == key(district)]
    return sorted(found, key=lambda place: (place.whole_district, place.name, place.district))


def close(places: Sequence[Place], text: str) -> list[Place]:
    """Places whose name looks like `text`, the most alike first. Suggestions, never a match."""
    wanted = key(text)
    if not wanted:
        return []
    scored = []
    for place in places:
        best = max(SequenceMatcher(None, wanted, other).ratio() for other in place.keys)
        if best >= CLOSE_ENOUGH:
            scored.append((-best, place.name, place.district, place))
    return [place for *_, place in sorted(scored)[:MAX_SUGGESTIONS]]
