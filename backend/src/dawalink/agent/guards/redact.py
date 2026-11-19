"""Removing personal details (docs/07 §7.1, INV-10, INV-24).

Applied to every client message **before it is stored and before the model sees it**, and
again to everything a trace would hold. Two kinds of things are removed:
- the account's own name, email and phone, in the forms people type them;
- anything that looks like an email address, a Lebanese phone number or map coordinates,
  whoever it belongs to.
"""

import re
from dataclasses import dataclass
from datetime import date

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")

_SEP = r"[\s.\-]?"
# +961 / 00961 / 961, then the number without its leading zero.
_INTERNATIONAL = rf"(?:\+|00)?961{_SEP}\d{{1,2}}{_SEP}\d{{3}}{_SEP}\d{{3}}"
# Mobile numbers as written inside Lebanon: 03 xxx xxx, 70/71/76/78/79/81 xxx xxx.
_MOBILE = rf"(?:0?3|70|71|76|78|79|81){_SEP}\d{{3}}{_SEP}\d{{3}}"
# Landlines: 01, 04, 05, 06, 07, 08, 09 and six digits.
_LANDLINE = rf"0[1456789]{_SEP}\d{{3}}{_SEP}\d{{3}}"
# A number followed by a currency is a price, not a phone ("70000000 LBP").
_NOT_A_PRICE = r"(?!\s*(?:lbp|ll\b|l\.l|lira|liras|usd|dollars?|\$|ليرة|دولار))"
PHONE = re.compile(
    rf"(?<![\d.,])(?:{_INTERNATIONAL}|{_MOBILE}|{_LANDLINE})(?![\d])(?![.,]\d){_NOT_A_PRICE}",
    re.IGNORECASE,
)
# Two decimal numbers with three or more decimals, as map coordinates are written.
COORDINATES = re.compile(r"-?\d{1,3}\.\d{3,}\s*[,;/ ]\s*-?\d{1,3}\.\d{3,}")

# Arabic-Indic and Persian digits are matched as the digits they are.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

NAME, EMAIL_MARK, PHONE_MARK, LOCATION = "[name]", "[email]", "[phone]", "[location]"
BIRTH_DATE = "[date of birth]"
_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


@dataclass(frozen=True)
class Identity:
    """The account's own personal details. They are read by code and never leave it."""

    full_name: str
    email: str
    phone: str | None = None
    # A client's date of birth (decision log BLD-D40). No rule reads it; it is here only
    # to be removed from what the client types.
    birth_date: date | None = None


@dataclass(frozen=True)
class Redacted:
    text: str
    count: int


def _own_name(identity: Identity) -> re.Pattern[str] | None:
    """The full name with any spacing, and each of its parts as a whole word."""
    parts = [part for part in re.split(r"\s+", identity.full_name.strip()) if part]
    if not parts:
        return None
    whole = r"\s+".join(re.escape(part) for part in parts)
    singles = [re.escape(part) for part in parts if len(part) >= 3]
    return re.compile(
        r"(?<!\w)(?:" + "|".join([whole, *singles]) + r")(?!\w)", re.IGNORECASE | re.UNICODE
    )


def _own_phone(identity: Identity) -> re.Pattern[str] | None:
    """The account's phone however it is typed: with +961, 00961 or 0, and any separators."""
    digits = re.sub(r"\D", "", (identity.phone or "").translate(_DIGITS))
    for prefix in ("00961", "961", "0"):
        if digits.startswith(prefix):
            digits = digits[len(prefix) :]
            break
    if len(digits) < 6:
        return None
    spaced = _SEP.join(digits)
    return re.compile(rf"(?<!\d)(?:(?:\+|00)?961{_SEP}|0)?{spaced}(?!\d)")


def _own_birth_date(identity: Identity) -> re.Pattern[str] | None:
    """The account's date of birth as people write one: 17/05/1990, 17-5-1990, 1990-05-17,
    17 May 1990, May 17, 1990. Only this date: other dates are what a chat is about."""
    born = identity.birth_date
    if born is None:
        return None
    day, month, year = rf"0?{born.day}", rf"0?{born.month}", str(born.year)
    name = _MONTHS[born.month - 1]
    word = rf"(?:{name}|{name[:3]})\.?"
    gap = r"[\s./-]+"
    forms = [
        rf"{day}{gap}{month}{gap}{year}",
        rf"{year}{gap}{month}{gap}{day}",
        rf"{day}(?:st|nd|rd|th)?{gap}{word}{gap}{year}",
        rf"{word}{gap}{day}(?:st|nd|rd|th)?,?{gap}{year}",
    ]
    return re.compile(r"(?<!\d)(?:" + "|".join(forms) + r")(?!\d)", re.IGNORECASE)


def redact(text: str, identity: Identity | None = None) -> Redacted:
    """`text` without personal details, and how many were removed."""
    count = 0

    def swap(pattern: re.Pattern[str] | None, mark: str, current: str) -> str:
        nonlocal count
        if pattern is None:
            return current
        # Digits are compared in their Western form, but the text keeps its own letters:
        # the translation is one character for one, so positions are the same.
        spans = [match.span() for match in pattern.finditer(current.translate(_DIGITS))]
        for start, end in reversed(spans):
            current = current[:start] + mark + current[end:]
        count += len(spans)
        return current

    result = swap(EMAIL, EMAIL_MARK, text)
    if identity is not None:
        # Before the phone patterns: a date's digits must not be read as part of a number.
        result = swap(_own_birth_date(identity), BIRTH_DATE, result)
        result = swap(_own_phone(identity), PHONE_MARK, result)
    result = swap(COORDINATES, LOCATION, result)
    result = swap(PHONE, PHONE_MARK, result)
    if identity is not None:
        result = swap(_own_name(identity), NAME, result)
    return Redacted(result, count)


def has_personal_details(text: str) -> bool:
    """An email, a phone number or coordinates: what a reply must never contain."""
    plain = text.translate(_DIGITS)
    return bool(EMAIL.search(plain) or PHONE.search(plain) or COORDINATES.search(plain))
