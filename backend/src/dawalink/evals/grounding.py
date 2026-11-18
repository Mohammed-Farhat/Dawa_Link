"""Did the reply invent a price or a pharmacy? (docs/09 FA-9)

The agent never works anything out: every price and every pharmacy it names was handed to
it by a tool in the same turn. So a figure followed by a currency, or a pharmacy's name,
that no tool answer of the turn holds was made up.

**A rule of thumb**, like the other automatic checks of the evaluation: a total the model
added up itself is reported too. What it reports is read by hand.
"""

import re
from collections.abc import Sequence

# A number as a price is written: digits, with "," or "." between them ("600,000", "6.70").
_AMOUNT = r"\d+(?:[.,]\d+)*"
# A number and a currency after it ("600,000 LBP", "6.70 USD"), or a dollar sign before or
# after it ("$6.70", "3.68$").
PRICE = re.compile(
    rf"({_AMOUNT})\s*(?:LBP|L\.?L\.?|ل\.?ل\.?|ليرة|USD|dollars?|\$)|\$\s*({_AMOUNT})",
    re.IGNORECASE,
)
# "Hamra Pharmacy", "Beirut Pharmacy 2": the capitalised words before the word. In a
# sentence the words before the name are capitalised too ("Ou Beirut Pharmacy 2"), so what
# is checked is whether the words nearest to "Pharmacy" are a name some tool gave.
NAMED_BEFORE = re.compile(r"((?:[A-Z][\w'\-]*\s+){1,4})Pharmacy\b")
# "Pharmacie du Cèdre": the name after the word.
NAMED_AFTER = re.compile(
    r"\bPharmac(?:ie|y)\s+((?:(?:d[eu]|des|la|le|l'|el|al)\s*)?[A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){0,2})"
)
# "صيدلية الحمرا": a name starts with the article. "صيدلية مناسبة" is any pharmacy.
NAMED_IN_ARABIC = re.compile(r"صيدلية\s+(ال[ء-ي]+)")
# Arabic words with the article that describe a pharmacy and name none.
_ANY_PHARMACY = {
    "القريبة",
    "الأقرب",
    "الاقرب",
    "المناسبة",
    "التالية",
    "الأولى",
    "الثانية",
    "الثالثة",
    "اللي",
    "التي",
    "الي",
}


# The digits of Arabic script and of Persian, and their separators, as the Latin ones: a
# reply in Arabic writes the tool's "450,000" with its own digits.
_LATIN_DIGITS = str.maketrans(
    "".join(chr(code) for code in (*range(0x660, 0x66A), *range(0x6F0, 0x6FA)))
    + chr(0x66C)
    + chr(0x66B),
    "0123456789" * 2 + ",.",
)
# Words that stand before "Pharmacy" without being a name.
_NOT_A_NAME = {"the", "a", "this", "that", "your", "each", "every", "any", "which", "one"}


def _plain(text: str) -> str:
    return text.translate(_LATIN_DIGITS)


def _digits(amount: str) -> str:
    return re.sub(r"\D", "", amount)


def _numbers_in(text: str) -> set[str]:
    """Every number of a text, as its digits: "600,000" and 600000 are the same."""
    return {_digits(found) for found in re.findall(_AMOUNT, text)}


def _pharmacies_nobody_named(reply: str, heard: str) -> list[str]:
    found: list[str] = []
    for match in NAMED_BEFORE.finditer(reply):
        words = match.group(1).split()
        if words[-1].lower() in _NOT_A_NAME:
            continue  # "The Pharmacy closes at five."
        # "Ou Beirut Pharmacy": is "Beirut Pharmacy" known? Then "Ou" is the sentence's.
        known = any(
            f"{' '.join(words[start:])} pharmacy".lower() in heard for start in range(len(words))
        )
        if not known:
            found.append(f"{words[-1]} Pharmacy")
    for match in NAMED_AFTER.finditer(reply):
        if match.group(0).lower() not in heard:
            found.append(match.group(0))
    for match in NAMED_IN_ARABIC.finditer(reply):
        if match.group(1) not in _ANY_PHARMACY and match.group(0) not in heard:
            found.append(match.group(0))
    return found


def invented(reply: str, answers: Sequence[str], client_said: Sequence[str] = ()) -> list[str]:
    """The prices and pharmacy names of `reply` that no tool answer holds.

    A figure the client wrote themselves (a budget: "within your 500,000 LBP") is theirs,
    not the agent's invention.
    """
    reply = _plain(reply)
    heard = _plain(" ".join(answers)).lower()
    known_numbers = _numbers_in(heard) | _numbers_in(_plain(" ".join(client_said)))
    prices = [
        match.group(0).strip()
        for match in PRICE.finditer(reply)
        if _digits(match.group(1) or match.group(2)) not in known_numbers
    ]
    return prices + _pharmacies_nobody_named(reply, heard)


def names_a_price_or_a_pharmacy(reply: str) -> bool:
    reply = _plain(reply)
    return bool(
        PRICE.search(reply)
        or NAMED_BEFORE.search(reply)
        or NAMED_AFTER.search(reply)
        or NAMED_IN_ARABIC.search(reply)
    )
