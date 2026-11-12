"""The team's catalog rules: controlled medicines, the no-prescription list, corrections.

They live in backend/data/catalog_overrides.toml (docs/04 R-C5 to R-C7).
"""

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dawalink.catalog.composition import Ingredient, normalize

DEFAULT_RULES_FILE = Path("data/catalog_overrides.toml")


@dataclass(frozen=True)
class ProductOverride:
    controlled: bool | None = None
    prescription_required: bool | None = None
    units_per_pack: int | None = None
    # "" means "no equivalents"; None means "no correction".
    equivalence_key: str | None = None


def _mentions(ingredient: Ingredient, words: frozenset[str]) -> bool:
    return not words.isdisjoint(ingredient.name_normalized.split())


@dataclass(frozen=True)
class CatalogRules:
    controlled_atc_prefixes: tuple[str, ...] = ()
    controlled_ingredients: frozenset[str] = frozenset()
    otc_ingredients: frozenset[str] = frozenset()
    products: Mapping[int, ProductOverride] = field(default_factory=dict)

    def is_controlled(self, atc: str, ingredients: Sequence[Ingredient]) -> bool:
        """Controlled by its ATC class or by any one ingredient (docs/04 R-C6)."""
        if atc and atc.upper().startswith(self.controlled_atc_prefixes):
            return True
        return any(_mentions(i, self.controlled_ingredients) for i in ingredients)

    def needs_prescription(self, ingredients: Sequence[Ingredient]) -> bool:
        """True unless every ingredient is on the no-prescription list (docs/04 R-C7)."""
        if not ingredients or not self.otc_ingredients:
            return True
        return not all(_mentions(i, self.otc_ingredients) for i in ingredients)


def _words(values: Sequence[str]) -> frozenset[str]:
    return frozenset(normalize(value) for value in values if normalize(value))


def rules_from(data: Mapping[str, Any]) -> CatalogRules:
    controlled = data.get("controlled", {})
    products = {
        int(code): ProductOverride(**override)
        for code, override in data.get("products", {}).items()
    }
    return CatalogRules(
        controlled_atc_prefixes=tuple(p.upper() for p in controlled.get("atc_prefixes", ())),
        controlled_ingredients=_words(controlled.get("ingredients", ())),
        otc_ingredients=_words(data.get("otc", {}).get("ingredients", ())),
        products=products,
    )


def load_rules(path: Path = DEFAULT_RULES_FILE) -> CatalogRules:
    with path.open("rb") as file:
        return rules_from(tomllib.load(file))
