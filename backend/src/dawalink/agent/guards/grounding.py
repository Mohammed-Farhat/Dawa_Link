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
    "travel": re.compile(r"closest|closer|nearest|shortest|quicker|faster|أقرب|اقرب|a2rab", re.I),
    "expiry": re.compile(
        r"latest expiry|latest expiration|expires? (?:the )?latest|أبعد صلاحية", re.I
    ),
}
_GLOBAL_SAME_PRICE = re.compile(
    r"\b(?:every|all) pharmac(?:y|ies)[^.!?\n]{0,80}(?:same price|price is the same)|"
    r"\b(?:price|cheapest) is (?:the )?same everywhere\b",
    re.I,
)
_PEER = re.compile(r"\b(?:than|men|mn|من)\b", re.I)
_PRONOUN = re.compile(r"\b(?:it|this|that|hayda|hayde|hiyye|hiyyi|huwe|هيدا|هذا|هذه|هي)\b", re.I)
_SEARCH_INTENT = re.compile(r"\b(?:to|will|can|let me)\s+(?:find|search|look for)\b", re.I)
_GLOBAL_STOCK_COUNT = re.compile(
    r"\b(?:all|only)\s+(\d+|one|two|three|four|five)\s+pharmac(?:y|ies)\s+"
    r"(?:(?:that\s+)?have\b|with\s+(?:it|stock)\b)",
    re.I,
)


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
    total_found: int | None = None
    for answer in answers:
        try:
            decoded = json.loads(answer)
        except (ValueError, TypeError):
            continue
        if isinstance(decoded, dict) and isinstance(decoded.get("options"), list):
            options = decoded["options"]  # Latest search supersedes earlier constraints.
            total_found = decoded.get("total_found")
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

    if _GLOBAL_SAME_PRICE.search(text):
        prices = {value(option, "price") for option in options}
        if len(prices - {None}) > 1:
            errors.append(
                "The claim that every pharmacy has the same price contradicts the options."
            )
        elif total_found is None or total_found > len(options) or None in prices:
            errors.append(
                "The tool did not establish every pharmacy's price. Limit the equal-price "
                "claim to the returned options instead of saying everywhere."
            )
    for counted in _GLOBAL_STOCK_COUNT.finditer(text):
        words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        reported = words.get(counted[1].lower())
        if reported is None:
            reported = int(counted[1])
        if total_found is None or reported != total_found:
            errors.append(
                "The claimed total number of pharmacies with stock is not established by the tool."
            )

    for paragraph in re.split(r"\n\s*\n|\n(?=\s*(?:[-*•]|\d+[.)])\s+)", text):
        previous: dict[str, Any] | None = None
        for sentence in re.split(r"(?<!\d)\.|\.(?!\d)|(?<=[!?؟\n])", paragraph):
            if re.match(r"\s*(?:[-*•]|\d+[.)])\s+", sentence):
                previous = None  # A new list item must not inherit the preceding subject.
            named = []
            for option in options:
                name = option.get("pharmacy", {}).get("name", "")
                if name and name.casefold() in sentence.casefold():
                    named.append((sentence.casefold().find(name.casefold()), option))
            resolved_subject = None
            for metric, pattern in _METRICS.items():
                at = pattern.search(sentence)
                if at is None:
                    continue
                if metric == "price" and _GLOBAL_SAME_PRICE.search(sentence):
                    continue  # Equal-price scope was checked above.
                if (
                    "?" in sentence
                    or "؟" in sentence
                    or _SEARCH_INTENT.search(sentence[: at.start()])
                ):
                    continue
                if metric == "travel" and re.match(
                    r"\s+spelling\s+match", sentence[at.end() :], re.I
                ):
                    continue
                peer_names = [
                    (pos, o)
                    for pos, o in named
                    if pos > at.end() and _PEER.search(sentence[at.end() : pos])
                ]
                subjects = [(pos, o) for pos, o in named if (pos, o) not in peer_names]
                before = [(pos, o) for pos, o in subjects if pos < at.start()]
                subject = (
                    max(before, key=lambda x: x[0])[1]
                    if before
                    else (min(subjects, key=lambda x: x[0])[1] if subjects else None)
                )
                if subject is None and _PRONOUN.search(sentence):
                    subject = previous
                if subject is not None:
                    resolved_subject = subject
                scope = options
                explicit_scope = False
                # Explicit geographic qualifiers define a subset. Never invent what
                # "nearby" means, or compare Beirut-only prices with another district.
                for option in options:
                    area = option.get("pharmacy", {}).get("area")
                    if area and re.search(
                        r"\b(?:in|bi|fi)\s+" + re.escape(area) + r"\b", sentence, re.I
                    ):
                        scope = [o for o in options if o.get("pharmacy", {}).get("area") == area]
                        explicit_scope = True
                        break
                if not explicit_scope and re.search(
                    r"nearby|open all day|that (?:is|are)", sentence, re.I
                ):
                    errors.append(
                        f"Unresolved {metric} comparison: qualified option subset needs review."
                    )
                    continue
                values = [value(o, metric) for o in scope]
                if subject is None or not values or any(v is None for v in values):
                    errors.append(
                        f"Unresolved {metric} comparison: evidence association incomplete."
                    )
                    continue
                actual = value(subject, metric)
                pairwise = bool(
                    peer_names or re.search(r"cheaper|closer|quicker|faster", sentence, re.I)
                )
                peers = [value(o, metric) for _, o in named if o is not subject] if pairwise else []
                if pairwise and not peers:
                    errors.append(f"Unresolved {metric} comparison: no explicit comparison peer.")
                    continue
                candidates = peers or values
                if actual is None or any(
                    actual < peer
                    if metric == "expiry"
                    else (actual >= peer if pairwise else actual > peer)
                    for peer in candidates
                    if peer is not None
                ):
                    errors.append(f"The {metric} comparison contradicts the tool options.")
            # Named peers don't replace a pronoun's established subject.
            unique_names = {o.get("pharmacy", {}).get("name") for _, o in named}
            if resolved_subject is not None:
                previous = resolved_subject
            elif len(unique_names) == 1:
                if not _PEER.search(sentence[: named[0][0]]):
                    previous = named[0][1]
            elif named:
                previous = None  # A pronoun after multiple pharmacies is ambiguous.
    return errors
