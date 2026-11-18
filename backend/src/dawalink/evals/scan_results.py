"""Nothing personal in the results we publish (docs/09 FS-13, FS-18; docs/10 TH-50):
python -m dawalink.evals.scan_results

Every run of the evaluation saves what the agent was sent and what it answered, and the
repository is public. The runs use invented clients, and whatever a client typed is cleaned
before it is stored. This reads every saved file once more and looks for what must never
be there: an email address, a phone number, a pair of coordinates.

It is the same three patterns the app itself removes (`agent/guards/redact.py`), applied
to what is left once identifiers and plain numbers are set aside: an ID or a price can
look like a phone number.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from dawalink.agent.guards.redact import COORDINATES, EMAIL, PHONE

RESULTS = Path("../eval/results")
READ = {".jsonl", ".json", ".md", ".csv", ".txt"}

# What looks like a phone number and is not one.
_NOT_TEXT = (
    # an ID of ours, and a plan's short ID
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE),
    re.compile(r"plan-[0-9a-f]{6,}-\d+", re.IGNORECASE),
    # the first characters of a card's ID, as the agent writes it in its own notes
    re.compile(r"\b(?:card|proposal)\s+[0-9a-f]{8}\b", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE),
    # a number field of a saved row: `"price_lbp_shown":76719000`, also inside a string
    re.compile(r'\\*"[a-z_]+\\*":\s*-?\d+(?:\.\d+)?'),
)
PATTERNS = {"an email address": EMAIL, "a phone number": PHONE, "coordinates": COORDINATES}


@dataclass(frozen=True)
class Found:
    file: Path
    what: str
    text: str
    around: str


def scan_text(text: str) -> list[tuple[str, str, str]]:
    """`(what, the match, the text around it)` for everything personal in `text`."""
    for not_text in _NOT_TEXT:
        text = not_text.sub(" ", text)
    return [
        (what, match.group(0), text[max(0, match.start() - 40) : match.end() + 20])
        for what, pattern in PATTERNS.items()
        for match in pattern.finditer(text)
    ]


def scan(folder: Path) -> tuple[int, list[Found]]:
    """How many files were read, and what was found in them."""
    files = [path for path in sorted(folder.rglob("*")) if path.is_file() and path.suffix in READ]
    found = [
        Found(path, what, text, " ".join(around.split()))
        for path in files
        for what, text, around in scan_text(path.read_text(encoding="utf-8", errors="replace"))
    ]
    return len(files), found


def main() -> None:
    read, found = scan(RESULTS)
    print(f"{read} files of saved results read: ", end="")
    if not found:
        print("no email address, phone number or coordinates in them")
        return
    print(f"{len(found)} to look at")
    for one in found[:40]:
        print(f"  {one.what} in {one.file}: ...{one.around}...")
    sys.exit(1)


if __name__ == "__main__":
    main()
