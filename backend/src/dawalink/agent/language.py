"""Which language a client wrote in, decided by code (the owner's finding, 2026-11-22).

Until this module the model chose the reply's language alone, and answered "hello" in
Arabizi. Now code reads the client's message and tells the model which language it is in
(`agent/context.py`), and the reply guard checks the answer (`guards/output.py`).

Three answers, the three the assistant is built for (D8): Arabic script, Arabizi (Lebanese
Arabic in Latin letters) and English. `None` means "can't tell": a message of one or two
letters, a medicine's name alone, or another language such as French. The model then
keeps the language it noted earlier, and starts in English.

Arabizi is recognised by words, never by a digit alone: "B12", "D3" and "omega3" are
medicine names, and "500mg" is a strength.
"""

import re
from typing import Literal

Language = Literal["arabic", "arabizi", "english"]

_ARABIC_LETTER = re.compile(r"[؀-ۿ]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")
_WORD = re.compile(r"[A-Za-z0-9']+")

# Words that are Lebanese Arabic and not English or French: one of them decides. A word
# that is also an English word or a common name ("fi", "law", "bel", "abel") is left out.
_ARABIZI_WORDS = frozenset(
    {
        # wanting, greeting
        *("baddi", "badde", "bade", "bedde", "beddi", "bdi", "bde", "baddak", "baddik", "badna"),
        *("shu", "shou", "chou", "sho", "kifak", "kifik", "kifkon", "marhaba", "mar7aba"),
        *("ahla", "ahlan", "yalla", "sama7t", "sama7te", "shukran", "shokran", "yislamo"),
        *("yeslamo", "3afwan", "aywa", "la2", "la2a", "mish", "mafi", "ktir", "kteer"),
        *("shwai", "shway", "hayda", "hayde", "haydi", "hal2", "halla2", "hala2", "2ana"),
        # having, place, time
        *("3ande", "3andi", "3endi", "3andak", "3andik", "3anna", "3am", "3al", "3a", "3ala"),
        *("3an", "ma3", "ma3e", "ma3i", "ma3ak", "fiye", "fiyye", "fik", "fiki"),
        *("lyom", "lyoum", "elyom", "bukra", "bokra", "boukra", "ba3d", "ba3ed", "2abel"),
        *("wein", "wayn", "addeh", "addesh", "2addeh", "2addesh", "emta", "aymta"),
        *("jem3a", "jom3a", "shaher", "shahr", "yom", "youm", "yomen", "ayyam"),
        # medicine, pharmacy, getting there
        *("dawa", "dawe", "dwa", "dawa2", "dwa2", "saydaliyye", "saydaliye", "sydalieh"),
        *("saydale", "khod", "jeeb", "dawwer", "dawwir", "la2ili", "la2eele", "7abbe"),
        *("7abbet", "7abbten", "3elbe", "3elbet", "siyyara", "sayyara", "mashi", "meshi"),
        *("bil", "rijl", "ijr"),
    }
)

# Short Arabic words that English also has, or nearly ("ana", "fi", "bel"): one alone
# says nothing, two in a message do ("ana bel Hamra").
_SOFT_WORDS = frozenset(
    {"ana", "bel", "fi", "eh", "ay", "kam", "wen", "bas", "shi", "hon", "hek", "kel", "kif", "mn"}
)

# One of these is enough to call a message English: "hello", "please", "tomorrow".
_ENGLISH_ALONE = frozenset(
    {
        *("hello", "hi", "hey", "thanks", "thank", "please", "today", "tomorrow", "tonight"),
        *("morning", "evening", "afternoon", "anywhere", "nearest", "cheapest", "medicine"),
        *("pharmacy", "pharmacies", "reserve", "search", "understand", "available"),
    }
)
# Small English words: two of them in a message make it English ("i want panadol").
_ENGLISH_WORDS = frozenset(
    {
        *("i", "i'm", "im", "the", "a", "an", "is", "are", "am", "do", "does", "did", "not"),
        *("dont", "don't", "need", "want", "have", "has", "can", "could", "would", "will"),
        *("for", "of", "in", "on", "at", "to", "my", "me", "you", "u", "it", "this", "that"),
        *("any", "and", "or", "with", "how", "what", "where", "when", "which", "there", "one"),
        *("find", "looking", "days", "day", "week", "by", "car", "foot", "near", "yes", "no"),
        *("two", "three", "box", "boxes", "tablets", "mind", "know"),
    }
)

# A digit standing for a letter inside a word: "ma3loum", "sa3a", "la2anno", "7abibi".
# Not a trailing digit ("B12", "omega3") and not a number before a unit ("500mg").
_DIGIT_INSIDE = re.compile(r"[a-z]+[23579][a-z]+")
_DIGIT_FIRST = re.compile(r"[237][a-z]{3,}")

_FRENCH = re.compile(
    r"\b(?:bonjour|bonsoir|je|vous|nous|est|les|des|une|pour|avec|merci|besoin|"
    r"médicament|medicament|pharmacie|ordonnance|jours?)\b",
    re.IGNORECASE,
)


def _arabizi_marks(text: str) -> int:
    """How many words of the text are Arabizi: listed words, and words spelled with a digit."""
    marks = soft = 0
    for word in _WORD.findall(text.lower()):
        if word in _ARABIZI_WORDS or _DIGIT_INSIDE.fullmatch(word) or _DIGIT_FIRST.fullmatch(word):
            marks += 1
        elif word in _SOFT_WORDS:
            soft += 1
    # Two small words together count as one Arabizi word.
    return marks + soft // 2


def looks_arabizi(text: str, *, at_least: int = 1) -> bool:
    """Is this Lebanese Arabic in Latin letters? `at_least`: how many Arabizi words it
    takes. One is enough for a client's short message; a reply is judged on more, because
    it may quote a word of the client's."""
    return _arabizi_marks(text) >= at_least


def language_of(text: str | None) -> Language | None:
    """The language a message is written in, or None when that can't be told."""
    if not text:
        return None
    arabic = len(_ARABIC_LETTER.findall(text))
    latin = len(_LATIN_LETTER.findall(text))
    if arabic > latin:
        return "arabic"
    if latin < 3:
        return None  # "h", "ok", a number: not enough to tell
    if looks_arabizi(text):
        return "arabizi"
    if len(_FRENCH.findall(text)) >= 2:
        return None  # another language: left to the model (D8)
    # English only on evidence: a medicine's name, a place or a short Arabizi answer with
    # no listed word ("concor 5", "hamra", "tlet iyyam") says nothing, and the language
    # noted earlier must stand (found by review, 2026-11-23).
    words = [word.lower() for word in _WORD.findall(text)]
    if any(word in _ENGLISH_ALONE for word in words):
        return "english"
    if sum(word in _ENGLISH_WORDS for word in words) >= 2:
        return "english"
    return None


NAMES = {"arabic": "Arabic script", "arabizi": "Arabizi", "english": "English"}
