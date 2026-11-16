"""What a pharmacy types about itself, checked (docs/03 PS-1, docs/10 TH-59, TM-D2).

These are the first words a stranger types that other people will read: clients see the
name, the address and the phone number, and the name reaches the AI once an admin has
approved it. So each field has a plain shape, and anything else is refused here, before
an admin ever looks.

Every function returns the value as it is stored, or raises `ValueError` with a sentence
the form can show.
"""

import re
import unicodedata

NAME_MIN, NAME_MAX = 2, 60
ADDRESS_MIN, ADDRESS_MAX = 5, 200
LICENSE_MIN, LICENSE_MAX = 2, 20
BATCH_MAX = 30

# Lebanon with a margin: a pin outside it is a slip of the hand, or not a pharmacy here.
LEBANON_LAT = (33.0, 34.75)
LEBANON_LON = (35.05, 36.7)

COUNTRY_CODE = "961"

_PLAIN_PUNCTUATION = " '-.&"
_ADDRESS_PUNCTUATION = _PLAIN_PUNCTUATION + ",/()#"
_LICENSE = re.compile(r"[A-Z0-9][A-Z0-9/-]*")
_BATCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ./_-]*")


def _plain_text(value: str, allowed_punctuation: str) -> bool:
    """Letters of any alphabet (accents and Arabic included), digits and a few marks.
    No line breaks, no symbols, no emoji: nothing a name or an address needs."""
    for char in value:
        if char in allowed_punctuation:
            continue
        kind = unicodedata.category(char)
        # L: letters, M: the marks Arabic and accents are written with, Nd: digits.
        if not (kind[0] in "LM" or kind == "Nd"):
            return False
    return True


def _one_line(value: str) -> str:
    return " ".join(value.split())


def clean_name(value: str) -> str:
    name = _one_line(value)
    if not NAME_MIN <= len(name) <= NAME_MAX:
        raise ValueError(f"A name has {NAME_MIN} to {NAME_MAX} characters.")
    if not _plain_text(name, _PLAIN_PUNCTUATION):
        raise ValueError("A name is made of letters, digits, spaces and ' - . &")
    return name


def clean_address(value: str) -> str:
    address = _one_line(value)
    if not ADDRESS_MIN <= len(address) <= ADDRESS_MAX:
        raise ValueError(f"An address has {ADDRESS_MIN} to {ADDRESS_MAX} characters.")
    if not _plain_text(address, _ADDRESS_PUNCTUATION):
        raise ValueError("An address is made of letters, digits, spaces and , . - / ( ) #")
    return address


def clean_license(value: str) -> str:
    """Stored in capitals without spaces, so "ph 1234" and "PH1234" are one licence.

    The Order of Pharmacists publishes no format we could check against, so only the
    shape is checked: an admin compares the number with the licence itself.
    """
    license_number = "".join(value.split()).upper()
    if not LICENSE_MIN <= len(license_number) <= LICENSE_MAX or not _LICENSE.fullmatch(
        license_number
    ):
        raise ValueError(
            f"A licence number has {LICENSE_MIN} to {LICENSE_MAX} letters and digits "
            "(- and / are allowed)."
        )
    return license_number


def clean_phone(value: str) -> str:
    """A Lebanese phone number, stored as `+961` and its 7 or 8 digits (TH-59).

    "03 123 456", "+961 3 123 456", "009613123456" and "70123456" are all accepted, and
    the first three are one number. Only the shape is checked: the website shows the
    number as a dial link it builds itself, and an admin approves it with the pharmacy.
    """
    if not re.fullmatch(r"[0-9 +()./-]+", value.strip()):
        raise ValueError("A phone number is made of digits.")
    digits = re.sub(r"\D", "", value)
    if value.strip().startswith("+") or digits.startswith("00"):
        digits = digits.removeprefix("00")
        if not digits.startswith(COUNTRY_CODE):
            raise ValueError("The phone number must be a Lebanese one (+961).")
        digits = digits.removeprefix(COUNTRY_CODE)
    digits = digits.removeprefix("0")  # the 0 written before a number inside Lebanon
    if len(digits) not in (7, 8) or digits.startswith("0"):
        raise ValueError("A Lebanese phone number has 7 or 8 digits after +961.")
    return f"+{COUNTRY_CODE}{digits}"


def check_pin(lat: float, lon: float) -> None:
    if not (LEBANON_LAT[0] <= lat <= LEBANON_LAT[1] and LEBANON_LON[0] <= lon <= LEBANON_LON[1]):
        raise ValueError("Put the pin on your pharmacy, in Lebanon.")


def clean_batch(value: str) -> str:
    """A batch number as printed on the box: letters, digits and a few marks. It is shown
    only to the pharmacy itself: never to a client, never to the AI (R-AG8)."""
    batch = _one_line(value)
    if not batch or len(batch) > BATCH_MAX or not _BATCH.fullmatch(batch):
        raise ValueError(
            f"A batch is up to {BATCH_MAX} letters and digits (space . / _ - are allowed)."
        )
    return batch
