"""From a medicine as a person names it to the products of the local catalog (docs/08 §2.1).

A gold label says `{"name": "concor", "strength": "5mg"}`. This module finds the catalog
products that fit, so a suite can check that the agent searched or proposed one of them.

The match is deliberately strict and simple, and it shares nothing with the agent's own
catalog search: the name must be the product's whole name ("concor" is not "concor plus"),
the strength its strength as the catalog writes it, the form a word of its form. A label
that fits no product is a mistake in the label, and the validator says so.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from dawalink.catalog.composition import normalize
from dawalink.db.models import Product
from dawalink.evals.datasets import Match, UCase

# More products than this for one label means the label is too loose to score with.
MAX_PRODUCTS_PER_LABEL = 12


def _compact(text: str | None) -> str:
    return "".join((text or "").lower().split())


@dataclass(frozen=True)
class CatalogNames:
    """The names of the catalog, read once for a whole run."""

    rows: tuple[tuple[uuid.UUID, str, str, str], ...]  # id, name, strength, form

    @classmethod
    def load(cls, session: Session) -> "CatalogNames":
        found = session.execute(
            select(Product.id, Product.search_name, Product.dosage_text, Product.form_text).where(
                Product.controlled.is_(False)
            )
        )
        return cls(
            tuple(
                (product_id, name, _compact(strength), (form or "").lower())
                for product_id, name, strength, form in found
            )
        )

    def products_for(self, match: Match) -> list[uuid.UUID]:
        """Every product that is a right answer for this label."""
        name = normalize(match.name)
        strength = _compact(match.strength)
        form = (match.form or "").lower()
        return [
            product_id
            for product_id, product_name, product_strength, product_form in self.rows
            if product_name == name
            and (not strength or product_strength == strength)
            and (not form or form in product_form)
        ]


def problems(catalog: CatalogNames, cases: Iterable[UCase]) -> list[str]:
    """Labels that fit no product of this catalog, or too many to be a label."""
    found = []
    for case in cases:
        for item in case.gold.items:
            count = len(catalog.products_for(item.match))
            if count == 0:
                found.append(f"{case.id}: no product is named {item.match.model_dump_json()}")
            elif count > MAX_PRODUCTS_PER_LABEL:
                found.append(f"{case.id}: {count} products fit {item.match.model_dump_json()}")
    return found
