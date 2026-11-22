"""The Ministry's list of medicines sold without a prescription (docs/04 R-C7).

The Ministry of Public Health publishes a "National OTC Medicines List" as a PDF. It names
registered products one by one: each row holds the product's code and registration number,
the same two columns as the price list. A catalog product loses the prescription notice only
when the list names that very product: the same code **and** the same registration number,
**and** the catalog's name agrees with the list row's words. Never by its ingredients, ATC
class or name alone, because the list names packs and forms (a cream may be on it while the
injection of the same substance is not), and a code alone is sometimes reused by another
product.

Reading the PDF's text is defensive. A row is read only when its code, registration number
and B/G column stand together on one line; anything that looks like a row but can't be read
that way is skipped and counted, never repaired. Keeping the notice is the safe failure.

Why the name is checked too: the text of a PDF wraps its cells over several lines, and two
fragments of different rows could, in some layout, read as a code and a registration number.
The name check doesn't depend on the layout: such a false pair would also have to belong to
a catalog product whose name stands in the list row it was read from. A row's words are the
lines since the previous row, plus what stands before the code on its own line: the brand
when it wrapped onto the lines above, but also the end of the previous row (its ingredient,
agent and maker). That looseness can only keep a mark that the exact pair already gave.

This module never imports the PDF library at the top: the import command reads the pairs
file only, and the running app must not load `pypdf`.
"""

import csv
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from dawalink.catalog.moph import CatalogRow

OTC_LIST_FILE = "otc_list.csv"
_COLUMNS = ["code", "registration_number", "row_text"]
# The table's header, repeated at the top of every page.
_HEADER = re.compile(r"^\s*Brand name\s+Strength\s+Presentation\s+Form\s+Code\s+Registration")
_BRAND_OR_GENERIC = re.compile(r"(?<!\S)[BG](?!\S)")
_CODE = re.compile(r"\d{3,5}")
# As the Ministry writes it: digits, then optionally "/" and the year's digits ("12345/1").
_REGISTRATION = re.compile(r"\d{3,7}(?:/\d{1,4})?")
# A word of a name: letters and digits, any alphabet ("LIQUI-GELS" is two words).
_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class OtcEntry:
    code: int
    registration_number: str
    # The list row's words before its code: its brand, strength, presentation and form.
    row_text: str


@dataclass(frozen=True)
class OtcList:
    entries: tuple[OtcEntry, ...]
    skipped: int

    @property
    def pairs(self) -> frozenset[tuple[int, str]]:
        return frozenset((e.code, e.registration_number) for e in self.entries)


@dataclass(frozen=True)
class OtcMarks:
    listed: int
    marked: int
    # A pair the catalog has, under a name the list row doesn't hold: left without the mark.
    name_differs: int
    not_in_catalog: int
    # A listed code that the catalog has under another registration number. Not a matter of
    # how the number is written: the catalog may give that code to another product (even an
    # injectable), or the list's row may repeat another row's registration number. Either
    # way the product is left with the notice, which is why both keys must match.
    code_with_another_registration: int


def _pair_before(tokens: list[str]) -> tuple[int, str] | None:
    """The code and registration number just before a B/G token, when they read plainly."""
    if len(tokens) < 2 or not _CODE.fullmatch(tokens[-2]):
        return None
    if not _REGISTRATION.fullmatch(tokens[-1]):
        return None
    # Before the code stands the form, or nothing when the form wrapped onto the line above.
    # A bare number there means a column is missing, so which number is the code is a guess.
    if len(tokens) > 2 and tokens[-3].isdigit():
        return None
    return int(tokens[-2]), tokens[-1]


def _looks_like_a_row(tokens: list[str]) -> bool:
    """A number just before a B/G token: a row, even if it can't be read (a missing column,
    a space inside the registration number, the code wrapped onto the line above)."""
    return any(_CODE.fullmatch(t) or _REGISTRATION.fullmatch(t) for t in tokens[-3:])


def _code_may_have_wrapped(tokens: list[str], line_above: str) -> bool:
    """A pair that opens its line, under a line that ends in a bare number: that number may be
    the row's code, and this line's two numbers a registration number with a space inside."""
    words_above = line_above.split()
    return len(tokens) == 2 and bool(words_above) and words_above[-1].isdigit()


def pairs_from_text(text: str) -> OtcList:
    """The list's rows (code, registration number and words), and how many were skipped."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if _HEADER.match(line)), None)
    if start is None:
        raise ValueError("The OTC list's table header was not found: its layout has changed.")
    entries: list[OtcEntry] = []
    skipped = 0
    row_start = start + 1  # the first line of the row being read
    for i in range(start, len(lines)):
        line = lines[i]
        if _HEADER.match(line):
            row_start = i + 1
            continue
        # A row starts on a line of its own, so a line holds one row at most.
        befores = [line[: t.start()].split() for t in _BRAND_OR_GENERIC.finditer(line)]
        found = next(((p, b) for b in befores if (p := _pair_before(b)) is not None), None)
        line_above = lines[i - 1] if i > row_start else ""
        if found is not None and not _code_may_have_wrapped(found[1], line_above):
            (code, registration), before = found
            row_text = " ".join([*lines[row_start:i], *before[:-2]])
            entries.append(OtcEntry(code, registration, " ".join(row_text.split())))
            row_start = i + 1
        elif found is not None or any(_looks_like_a_row(before) for before in befores):
            skipped += 1
            row_start = i + 1
    return OtcList(tuple(entries), skipped)


def read_otc_pdf(path: Path) -> OtcList:
    from pypdf import PdfReader  # only the laptop command needs it, never the app

    reader = PdfReader(str(path))
    return pairs_from_text("\n".join(page.extract_text() or "" for page in reader.pages))


def write_otc_list(path: Path, entries: Iterable[OtcEntry]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(_COLUMNS)
        for e in sorted(entries, key=lambda e: (e.code, e.registration_number, e.row_text)):
            writer.writerow([e.code, e.registration_number, e.row_text])


def read_otc_list(path: Path) -> tuple[OtcEntry, ...]:
    with path.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != _COLUMNS:
            # A file of an earlier version has no row text to check names against.
            raise ValueError(f"{path.name} has an old layout: run dawalink.ops.fetch_otc_list.")
        return tuple(
            OtcEntry(int(row["code"]), row["registration_number"], row["row_text"])
            for row in reader
        )


def _words(text: str) -> set[str]:
    return {word.upper() for word in _WORD.findall(text)}


def _name_word(name: str) -> str | None:
    """The first word of a catalog name that holds a letter: the brand's word."""
    return next((w.upper() for w in _WORD.findall(name) if any(c.isalpha() for c in w)), None)


def mark_otc(
    rows: Iterable[CatalogRow], entries: Iterable[OtcEntry]
) -> tuple[list[CatalogRow], OtcMarks]:
    """The catalog's rows, each marked when the list names it: code, registration number and
    a name the list row holds."""
    words_by_pair: dict[tuple[int, str], set[str]] = defaultdict(set)
    for e in entries:
        words_by_pair[(e.code, e.registration_number)] |= _words(e.row_text)
    marked_rows: list[CatalogRow] = []
    found: set[tuple[int, str]] = set()
    name_differs = 0
    for row in rows:
        pair = (row.code, row.registration_number)
        listed = False
        if pair in words_by_pair:
            found.add(pair)
            listed = _name_word(row.name) in words_by_pair[pair]
            name_differs += not listed
        marked_rows.append(replace(row, otc_listed=listed))
    codes_in_catalog = {row.code for row in marked_rows}
    missing = words_by_pair.keys() - found
    return marked_rows, OtcMarks(
        listed=len(words_by_pair),
        marked=sum(row.otc_listed for row in marked_rows),
        name_differs=name_differs,
        not_in_catalog=len(missing),
        code_with_another_registration=sum(code in codes_in_catalog for code, _ in missing),
    )
