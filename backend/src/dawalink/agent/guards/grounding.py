"""Conservative checks for action claims and comparisons of fresh option rows.

These checks cover explicit constructions, not general semantic truth. Unrecognized
paraphrases still require review. They never authorize a business action.
"""

import json
import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

_DONE = re.compile(
    r"\b(?:i(?:'ve)?|we(?:'ve)?|it is|it's|already|successfully)\s+"
    r"(?:reserved|booked|cancell?ed)\b|^\s*(?:reserved|booked|cancell?ed)\b|"
    r"حجزت|ألغيت|تم الحجز|تم الإلغاء|\b(?:7ajazt|7jazt|lghayt|lghit)\b",
    re.I,
)
_NEGATED = re.compile(
    r"\b(?:not|never|cannot|can't|haven't|hasn't|if|until)\b|ما |لم |لن |\bma\b", re.I
)
_METRICS = {
    "price": re.compile(r"cheapest|cheaper|lowest price|أرخص|ارخص|arkhas", re.I),
    "travel": re.compile(r"closest|nearest|shortest|quicker|faster|أقرب|اقرب|a2rab", re.I),
    "expiry": re.compile(
        r"latest expiry|latest expiration|expires? (?:the )?latest|أبعد صلاحية", re.I
    ),
}


def claims_completed(text: str) -> bool:
    """A proposed card cannot substantiate a claim that a tap already happened."""
    return any(_DONE.search(s) and not _NEGATED.search(s) for s in re.split(r"[.!?؟\n]+", text))


def comparison_errors(text: str, answers: Sequence[str], *, on_foot: bool = False) -> list[str]:
    """Validate explicit price/travel/expiry rankings against comparable fresh options.

    Only one product's options can be compared here; basket tradeoffs remain a manual
    review obligation. A claim without an identifiable subject is not proven.
    """
    errors = []
    if re.search(
        r"(?:closes?|b[ei]?tsakk[ae]r|بتسكر)[^.!?؟\n]{0,30}"
        r"\d+\s*(?:w|and)\s*(?:noss?|half)",
        text,
        re.I,
    ):
        errors.append(
            "Copy closing hours in numeric notation exactly as the tool gave them; "
            "do not paraphrase them as a spoken half-hour."
        )
    options: list[dict[str, Any]] = []
    for answer in answers:
        try:
            decoded = json.loads(answer)
        except (ValueError, TypeError):
            continue
        if isinstance(decoded, dict) and isinstance(decoded.get("options"), list):
            options = decoded["options"]  # Latest search supersedes earlier constraints.
    if not options:
        return errors
    products = {str(o.get("product_id")) for o in options}
    if len(products) != 1:
        return errors

    def value(option: dict[str, Any], metric: str) -> Decimal | None:
        if metric == "price":
            match = re.match(r"([\d,]+)\s*LBP", str(option.get("price", "")))
            return Decimal(match[1].replace(",", "")) if match else None
        if metric == "travel":
            minutes = option.get("travel", {}).get("walk_min" if on_foot else "car_min")
            return Decimal(str(minutes)) if minutes is not None else None
        return (
            Decimal(date.fromisoformat(str(option["expiry_date"])).toordinal())
            if option.get("expiry_date")
            else None
        )

    for sentence in re.split(r"(?<!\d)\.|\.(?!\d)|[!?؟\n]+", text):
        for metric, pattern in _METRICS.items():
            if not pattern.search(sentence):
                continue
            # Match the closest named pharmacy before the comparison; if the name
            # follows it, use the first following name. Never borrow a different row.
            at = pattern.search(sentence)
            assert at is not None
            named = []
            for option in options:
                name = option.get("pharmacy", {}).get("name", "")
                if name and name.casefold() in sentence.casefold():
                    pos = sentence.casefold().find(name.casefold())
                    named.append((pos, option))
            before = [(pos, o) for pos, o in named if pos < at.start()]
            subject = (
                max(before, key=lambda x: x[0])[1]
                if before
                else (min(named, key=lambda x: x[0])[1] if named else None)
            )
            values = [value(o, metric) for o in options]
            if subject is None or any(v is None for v in values):
                errors.append(f"Unsupported {metric} comparison; use exact tool facts instead.")
                continue
            actual = value(subject, metric)
            # A named cheaper-than comparison is pairwise; a superlative covers all.
            peers = (
                [value(o, metric) for _, o in named if o is not subject]
                if re.search(r"cheaper|quicker|faster", sentence, re.I)
                else []
            )
            candidates = peers or values
            if actual is None or any(
                actual < peer if metric == "expiry" else actual > peer
                for peer in candidates
                if peer is not None
            ):
                errors.append(f"The {metric} comparison contradicts the tool options.")
    return errors
