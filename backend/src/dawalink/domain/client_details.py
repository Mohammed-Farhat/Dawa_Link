"""The shape of what a client says about themselves (docs/04 SM-2, decision log BLD-D40).

Plain rules, no database: a name's part, and a birth date. Nothing here decides anything
about a client; DawaLink has no rule that reads an age.
"""

import unicodedata
from datetime import date

NAME_PART_MAX = 40
OLDEST_YEARS = 120
_NAME_PUNCTUATION = " '-."


def clean_name_part(value: str | None, *, required: bool) -> str | None:
    """One part of a person's name: letters of any alphabet, spaces and ' - .

    An empty optional part is None. Raises ValueError with a sentence for the form.
    """
    name = " ".join((value or "").split())
    if not name:
        if required:
            raise ValueError("Enter a name.")
        return None
    if len(name) > NAME_PART_MAX:
        raise ValueError(f"A name has at most {NAME_PART_MAX} characters.")
    for char in name:
        if char in _NAME_PUNCTUATION:
            continue
        # L: letters, M: the marks Arabic and accents are written with.
        if unicodedata.category(char)[0] not in "LM":
            raise ValueError("A name is made of letters, spaces and ' - .")
    if not any(unicodedata.category(char)[0] == "L" for char in name):
        raise ValueError("A name needs at least one letter.")
    return name


def whole_name(first: str, middle: str | None, last: str) -> str:
    """The name as one line, the way emails and the admins' contact view show it."""
    return " ".join(part for part in (first, middle, last) if part)


def check_birth_date(born: date, today: date) -> None:
    """A birth date is a real past day, within a human life. Raises ValueError."""
    if born > today:
        raise ValueError("A birth date can't be in the future.")
    if born.year < today.year - OLDEST_YEARS:
        raise ValueError("Check the year of this birth date.")
