"""Did the reply invent a price or a pharmacy? (docs/09 FA-9)

The agent never works anything out: every price and every pharmacy it names was handed to
it by a tool in the same turn. So a figure followed by a currency, or a pharmacy's name,
that no tool answer of the turn holds was made up.

**A rule of thumb**, like the other automatic checks of the evaluation: a total the model
added up itself is reported too. What it reports is read by hand.
"""

import json
import re
from collections.abc import Sequence
from decimal import Decimal

# A number as a price is written: digits, with "," or "." between them ("600,000", "6.70").
_AMOUNT = r"\d+(?:[.,]\d+)*"
# A number and a currency after it ("600,000 LBP", "6.70 USD"), or a dollar sign before or
# after it ("$6.70", "3.68$").
PRICE = re.compile(
    rf"({_AMOUNT})\s*(?:LBP|L\.?L\.?|ل\.?ل\.?|ليرة|USD|dollars?|دولار|\$)|\$\s*({_AMOUNT})",
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

    def money(amount: str, currency: str) -> tuple[Decimal, str]:
        # Three trailing digits are a thousands group; one/two are decimals.
        parts = re.split(r"[.,]", amount)
        number = "".join(parts)
        if len(parts) > 1 and len(parts[-1]) in (1, 2):
            number = "".join(parts[:-1]) + "." + parts[-1]
        return Decimal(number), currency

    def currencies(text: str) -> set[tuple[Decimal, str]]:
        return {
            money(
                m.group(1) or m.group(2),
                "USD" if re.search(r"\$|USD|dollar|دولار", m.group(), re.I) else "LBP",
            )
            for m in PRICE.finditer(_plain(text))
        }

    facts: list[tuple[set[tuple[Decimal, str]], str, str]] = []

    def prices_in(value: object, product: str = "", pharmacy: str = "") -> set[tuple[Decimal, str]]:
        if isinstance(value, dict):
            named = value.get("product") or value.get("product_name")
            if isinstance(named, dict):
                named = named.get("name")
            if not named and ("strength" in value or "pack" in value):
                named = value.get("name")
            product = str(named) if isinstance(named, str) else product
            shop = value.get("pharmacy") or value.get("pharmacy_name")
            if isinstance(shop, dict):
                shop = shop.get("name")
            pharmacy = str(shop) if isinstance(shop, str) else pharmacy
            # plan_basket puts the total on the plan, while its pharmacy is inside
            # groups. Attribute a basket total only when it has exactly one group.
            groups = value.get("groups")
            if isinstance(groups, list) and len(groups) == 1 and isinstance(groups[0], dict):
                group_shop = groups[0].get("pharmacy")
                if isinstance(group_shop, dict) and isinstance(group_shop.get("name"), str):
                    pharmacy = group_shop["name"]
            # The guarded proposal tools return Preview(title, lines), rather than
            # FindOptions' structured option rows. Keep those price associations too.
            title, lines = value.get("title"), value.get("lines")
            if isinstance(title, str) and isinstance(lines, list):
                if " at " in title:
                    product, _, pharmacy = title.rpartition(" at ")
                elif group := re.fullmatch(r"(.+) · \d+ medicines?", title):
                    pharmacy = group.group(1)
                for line in lines:
                    if isinstance(line, list) and len(line) == 2:
                        line = ": ".join(str(part) for part in line)
                    if not isinstance(line, str):
                        continue
                    item = re.match(r"(.+) x \d+: (.+)", line)
                    facts.append((currencies(line), item.group(1) if item else product, pharmacy))
            own: set[tuple[Decimal, str]] = set()
            nested: set[tuple[Decimal, str]] = set()
            for key, part in value.items():
                if isinstance(part, dict | list):
                    nested |= prices_in(part, product, pharmacy)
                else:
                    own |= currencies(str(part))
                    if isinstance(part, int | float) and re.search(r"price|total|cost", key):
                        currency = "USD" if "usd" in key else "LBP" if "lbp" in key else None
                        if currency:
                            own.add((Decimal(str(part)), currency))
            if own:
                facts.append((own, product, pharmacy))
            return own | nested
        if isinstance(value, list):
            return set().union(*(prices_in(v, product, pharmacy) for v in value))
        return currencies(str(value))

    known_numbers: set[tuple[Decimal, str]] = set()
    for answer in answers:
        try:
            known_numbers.update(prices_in(json.loads(answer)))
        except (ValueError, TypeError):
            known_numbers.update(prices_in(answer))
    budgets = currencies(" ".join(client_said))
    known_numbers |= budgets

    def supported(match: re.Match[str]) -> bool:
        price = next(iter(currencies(match.group())))
        if price not in known_numbers:
            return False
        # Associate a price with the nearest named entities in its sentence/bullet.
        start = max(reply.rfind("\n", 0, match.start()), reply.rfind(". ", 0, match.start())) + 1
        end = reply.find("\n", match.end())
        sentence_end = reply.find(". ", match.end())
        if sentence_end >= 0 and (end < 0 or sentence_end < end):
            end = sentence_end
        clause = reply[start : end if end >= 0 else len(reply)].lower()
        offset = match.start() - start

        def nearest(names: set[str]) -> str:
            positions = [(clause.rfind(n.lower(), 0, offset), n) for n in names if n]
            before = [(pos, n) for pos, n in positions if pos >= 0]
            if before:
                return max(before)[1]
            after = [(clause.find(n.lower(), offset), n) for n in names if n]
            found = [(pos, n) for pos, n in after if pos >= 0]
            return min(found)[1] if found else ""

        product = nearest({p for _, p, _ in facts})
        pharmacy = nearest({p for _, _, p in facts})
        if not product and not pharmacy:
            return True  # Unattributed money still needs manual factuality review.
        return any(
            price in prices and (not product or p == product) and (not pharmacy or shop == pharmacy)
            for prices, p, shop in facts
        ) or (price in budgets and bool(re.search(r"budget|limit|within|ميزاني", clause)))

    prices = [match.group(0).strip() for match in PRICE.finditer(reply) if not supported(match)]
    return prices + _pharmacies_nobody_named(reply, heard)


def names_a_price_or_a_pharmacy(reply: str) -> bool:
    reply = _plain(reply)
    return bool(
        PRICE.search(reply)
        or NAMED_BEFORE.search(reply)
        or NAMED_AFTER.search(reply)
        or NAMED_IN_ARABIC.search(reply)
    )
