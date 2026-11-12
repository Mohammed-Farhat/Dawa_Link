"""What a medicine contains, and when two products are "the same medicine" (docs/04 R-C5).

Everything here errs on the side of NOT matching: a wrong "same medicine, another brand"
could hurt someone, a missed one only hides an option. So:
- an ingredient keeps its salt ("amlodipine besylate" is not merged with "amlodipine");
- a strength must be fully readable, or the product has no equivalents at all;
- only coating variants of a tablet or capsule share a form group. Modified-release,
  gastro-resistant, dispersible and every other form stay apart;
- the ATC code must be the same too, which keeps different uses apart (eye and ear drops,
  a mouth gel and a skin gel, two kinds of insulin).
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

# One ingredient is "name - strength"; several are separated by ", ". A name may itself
# contain a comma ("Fibrinogen, human"), so the split is on the " - " that ends each name.
_SEGMENT = re.compile(r"\s*(?P<name>.+?)\s+-\s+(?P<strength>[^,]*?)\s*(?:,\s+|$)")
_SIMPLE_STRENGTH = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[a-zµ%]+)")
_READABLE_STRENGTH = re.compile(r"[0-9a-zµ%./() +-]+")
# Mass units are brought to milligrams, so "1g" and "1000mg" are the same strength.
_TO_MG = {"g": Decimal(1000), "mg": Decimal(1), "mcg": Decimal("0.001"), "µg": Decimal("0.001")}

_MODIFIED_RELEASE = ("prolonged", "extended", "modified", "sustained", "controlled", "retard")
_GASTRO_RESISTANT = ("enteric", "gastro", "delayed")
_OTHER_TABLETS = ("orodispersible", "dispersible", "chewable", "effervescent", "sublingual")
_OTHER_CAPSULES = ("inhalation", "vaginal", "rectal")
# Words that only describe a tablet's or capsule's coating or shape (docs/04 R-C5).
_COATING_WORDS = frozenset(
    {"tablet", "tablets", "caplet", "capsule", "capsules", "film", "coated", "scored", "sugar"}
    | {"hard", "soft", "gelatin", "gelatine", "divisible", "breakable"}
)


def normalize(text: str) -> str:
    """Lowercase letters and digits separated by single spaces: for search and for matching."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()


@dataclass(frozen=True)
class Ingredient:
    name: str
    name_normalized: str
    strength_text: str | None
    # Set only for a plain strength such as "500mg" or "0.45%".
    strength_value: Decimal | None
    strength_unit: str | None
    # The strength as it enters the equivalence key, or None when it can't be trusted.
    strength_key: str | None


def _strength(text: str) -> tuple[Decimal | None, str | None, str | None]:
    """(value, unit, key) for a strength as the Ministry writes it."""
    compact = text.lower().replace(" ", "")
    if not compact or not re.search(r"\d", compact) or not _READABLE_STRENGTH.fullmatch(compact):
        # Empty, or it holds a character that was lost on the way ("?2.5Lf"): not readable.
        return None, None, None
    simple = _SIMPLE_STRENGTH.fullmatch(compact)
    if simple is None:
        # A concentration or a compound strength ("250mg/5ml"): kept exactly as written.
        return None, None, compact
    value, unit = Decimal(simple["value"]), simple["unit"]
    if unit in _TO_MG:
        value, unit = value * _TO_MG[unit], "mg"
    value = value.normalize()
    return value, unit, f"{value:f}{unit}"


def parse_ingredients(text: str | None) -> list[Ingredient]:
    """The ingredients of "Candesartan cilexetil - 8mg, Amlodipine - 5mg".

    Text that doesn't follow the pattern comes back as one ingredient with no strength,
    which gives the product no equivalents.
    """
    text = (text or "").strip()
    if not text:
        return []
    found: list[Ingredient] = []
    position = 0
    for match in _SEGMENT.finditer(text):
        if match.start() != position:
            break
        position = match.end()
        name = match["name"].strip()
        value, unit, key = _strength(match["strength"])
        found.append(Ingredient(name, normalize(name), match["strength"] or None, value, unit, key))
    if position != len(text) or not all(i.name_normalized[:1].isalpha() for i in found):
        return [Ingredient(text, normalize(text), None, None, None, None)]
    return found


def form_group(form_text: str | None) -> str | None:
    """Which forms count as "the same form" (docs/04 R-C5).

    Plain, coated and scored tablets (and caplets) are one group; hard and soft capsules
    are one group. Every other form is a group of its own.
    """
    form = normalize(form_text or "")
    if not form:
        return None
    words = form.split()
    kind = (
        "tablet"
        if words[0] in ("tablet", "tablets", "caplet")
        else "capsule"
        if words[0] in ("capsule", "capsules")
        else None
    )
    if kind is None:
        return form.replace(" ", "_")
    if any(word.startswith(_MODIFIED_RELEASE) for word in words):
        return f"{kind}_mr"
    if any(word.startswith(_GASTRO_RESISTANT) for word in words):
        return f"{kind}_gr"
    special = _OTHER_TABLETS if kind == "tablet" else _OTHER_CAPSULES
    for word in words:
        if word in special:
            return f"{kind}_{word}"
    if set(words) <= _COATING_WORDS:
        return kind
    # Something else is said about it ("tablet vaginal"): it stays a form of its own.
    return form.replace(" ", "_")


def equivalence_key(
    ingredients: list[Ingredient], group: str | None, atc_code: str | None
) -> str | None:
    """Same key = same ingredients, strengths, form group and ATC code. None = no equivalents.

    The ATC code is part of the key because many forms don't say what they are for: "drops"
    may be for the eye or the ear, a "gel" for the mouth or the skin. The ATC code does.
    """
    atc = (atc_code or "").strip().upper()
    if not ingredients or group is None or not atc:
        return None
    if any(i.strength_key is None or not i.name_normalized for i in ingredients):
        return None
    parts = sorted(f"{i.name_normalized}={i.strength_key}" for i in ingredients)
    if len(set(parts)) != len(parts):
        return None
    return " + ".join(parts) + " | " + group + " | " + atc
