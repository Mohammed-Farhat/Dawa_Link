"""Explicit monetary caps in client wording, independent of model-written notes."""

import re
from collections.abc import Sequence

from dawalink.agent.state import Money

_CAP = re.compile(
    r"\b(?:budget|maximum|max|under|up to|no more than|at most|mizaniyye\w*|"
    r"mi[sz]aniyy\w*|ta7t|taht)\b|ميزاني|سقف|حد أقصى|حد اقصى|أقل من|اقل من",
    re.I,
)
_SOFT = re.compile(r"\b(?:if possible|ideally|preferably|around|about)\b|إذا أمكن|اذا امكن", re.I)
_AMOUNT = re.compile(
    r"(?P<usd>\$)\s*(?P<dollars>\d+(?:\.\d+)?)|"
    r"(?P<amount>\d[\d,٬]*(?:\.\d+)?)\s*"
    r"(?P<scale>k\b|thousand\b|alf\b|ألف|الف)?\s*"
    r"(?P<currency>LBP\b|USD\b|liras?\b|l[il]\b|ليرة|ليره|دولار|\$)",
    re.I,
)


def explicit_budget(messages: Sequence[str]) -> Money | None:
    """Latest single, explicit hard cap with a currency; never parse a product price.

    Multiple amounts, soft targets and unclear currencies remain model/review work.
    A later clear budget revision replaces an earlier cap, including an increase.
    """
    chosen = None
    for text in messages:
        if not _CAP.search(text) or _SOFT.search(text):
            continue
        amounts = list(_AMOUNT.finditer(text))
        if len(amounts) != 1:
            continue
        match = amounts[0]
        amount = float((match["dollars"] or match["amount"]).replace(",", "").replace("٬", ""))
        if match["scale"]:
            amount *= 1000
        currency = (match["currency"] or "$").lower()
        if 0 < amount <= 1_000_000_000:
            chosen = Money(
                amount=amount, currency="USD" if currency in ("usd", "$", "دولار") else "LBP"
            )
    return chosen
