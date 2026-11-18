"""Finding medicines in the catalog (docs/04 R-C5, R-C6; the agent's `search_catalog`).

Controlled medicines are never returned, by any path (INV-6).
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select, text

from dawalink.catalog.composition import normalize
from dawalink.db.models import CatalogImport, Product
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

# Below this score a match is a guess: the client is asked "did you mean…?".
CONFIDENT = 0.6
MAX_QUERY_LENGTH = 100


@dataclass(frozen=True)
class ProductRef:
    """A medicine as the client and the agent see it."""

    id: uuid.UUID
    name: str
    strength: str | None
    form: str | None
    pack: str | None
    prescription_required: bool
    public_price_lbp: int
    equivalence_key: str | None
    # The Ministry's own number for the product: what a pharmacy's stock file may carry
    # to say which pack it means. The agent's tools don't pass it on.
    code: int


@dataclass(frozen=True)
class ProductSearch:
    products: list[ProductRef]
    # Close names to offer when nothing matched well ("Did you mean Augmentin?").
    did_you_mean: list[str]


def ref(product: Product) -> ProductRef:
    return ProductRef(
        id=product.id,
        name=product.moph_name,
        strength=product.dosage_text,
        form=product.form_text,
        pack=product.presentation_text,
        prescription_required=product.prescription_required,
        public_price_lbp=product.public_price_lbp,
        equivalence_key=product.equivalence_key,
        code=product.moph_code,
    )


def allowed_product(tx: Tx, product_id: uuid.UUID) -> Product:
    """The product, or a refusal: unknown, or controlled (R-C6)."""
    product = tx.session.get(Product, product_id)
    if product is None:
        raise ServiceError(Code.NOT_FOUND, "Unknown medicine.")
    if product.controlled:
        raise ServiceError(Code.PRODUCT_NOT_ALLOWED, "Not available on DawaLink.")
    return product


def search_products(tx: Tx, query: str, *, limit: int = 8) -> ProductSearch:
    """Medicines whose name or ingredient looks like the query, best first.

    Spelling mistakes are tolerated ("ogmentin"). A strength in the query ("1g", "500")
    doesn't take part in the name match: it only moves the products with that strength up.
    """
    words = normalize(query[:MAX_QUERY_LENGTH]).split()
    name = " ".join(word for word in words if not word[0].isdigit())
    strengths = [word for word in words if word[0].isdigit()]
    if not name:
        return ProductSearch([], [])

    rows = tx.session.execute(
        text(
            """
            SELECT p.id,
                   GREATEST(
                     word_similarity(:q, p.search_name),
                     COALESCE((SELECT max(word_similarity(:q, pi.name_normalized))
                               FROM product_ingredients pi WHERE pi.product_id = p.id), 0)
                   ) AS score
            FROM products p
            WHERE NOT p.controlled
              AND (:q <% p.search_name
                   OR p.search_name % :q
                   OR EXISTS (SELECT 1 FROM product_ingredients pi
                              WHERE pi.product_id = p.id AND :q <% pi.name_normalized))
            ORDER BY score DESC, p.moph_name, p.moph_code
            LIMIT 60
            """
        ),
        {"q": name},
    ).all()
    scores = {product_id: float(score) for product_id, score in rows}
    products = list(tx.session.execute(select(Product).where(Product.id.in_(scores))).scalars())

    def has_the_strength(product: Product) -> bool:
        said = re.sub(r"[^a-z0-9.]", "", (product.dosage_text or "").lower())
        return all(strength in said for strength in strengths)

    products.sort(key=lambda p: (not has_the_strength(p), -scores[p.id], p.moph_name, p.moph_code))
    confident = [p for p in products if scores[p.id] >= CONFIDENT]
    if confident:
        return ProductSearch([ref(p) for p in confident[:limit]], [])
    suggestions = list(dict.fromkeys(p.moph_name for p in products))[:3]
    return ProductSearch([], suggestions)


def equivalents(tx: Tx, product_id: uuid.UUID) -> list[ProductRef]:
    """Other brands of the same medicine: the same equivalence key, nothing looser (R-C5)."""
    product = allowed_product(tx, product_id)
    if product.equivalence_key is None:
        return []
    others = tx.session.execute(
        select(Product)
        .where(
            Product.equivalence_key == product.equivalence_key,
            Product.id != product.id,
            Product.controlled.is_(False),
        )
        .order_by(Product.public_price_lbp, Product.moph_name)
    ).scalars()
    return [ref(other) for other in others]


def medicine_group(product: Product) -> str:
    """What "the same medicine" means for limits and matching.

    A product with no equivalence key is a group of its own, so it is never lumped with
    every other product that has none.
    """
    return product.equivalence_key or f"product:{product.id}"


def same_brand(tx: Tx, product_id: uuid.UUID) -> set[uuid.UUID]:
    """The catalog rows that are "what the client asked for" when they name this product:
    itself, and every row of the same medicine with the same name.

    The Ministry lists one name several times: another box size, another registration,
    and for generics named after their ingredient, another maker. The owner's rule
    (2026-11-15, build plan Q38): "same name same medicine". A client who writes the name
    asked for no company, so every box that carries that name is theirs to reserve. A
    different name is another brand (R-C10).
    """
    product = tx.session.get_one(Product, product_id)
    if product.equivalence_key is None:
        return {product.id}
    rows = tx.session.execute(
        select(Product.id).where(
            Product.equivalence_key == product.equivalence_key,
            Product.search_name == product.search_name,
        )
    ).scalars()
    return {product.id, *rows}


def products_in_group(tx: Tx, product: Product, *, with_equivalents: bool) -> Sequence[uuid.UUID]:
    """The product itself, plus its equivalents when the client allowed alternatives."""
    if not with_equivalents:
        return [product.id]
    return [product.id, *(other.id for other in equivalents(tx, product.id))]


def admin_products(tx: Tx, query: str, *, offset: int = 0, limit: int = 50) -> list[Product]:
    """The catalog as an admin reads it (AS-9): every product, **the controlled ones
    included**, which nobody else ever sees (R-C6). Read-only: the catalog changes by the
    import script and the team's override files."""
    statement = select(Product)
    wanted = normalize(query)
    if query.strip() and not wanted:
        # Typed, but no letter or digit in it ("%", "_"): that names no product. Without
        # this it would list the whole catalog, as an empty search does.
        return []
    if wanted:
        statement = statement.where(Product.search_name.contains(wanted, autoescape=True))
    return list(
        tx.session.execute(
            statement.order_by(Product.moph_name, Product.moph_code).offset(offset).limit(limit)
        ).scalars()
    )


def group_sizes(tx: Tx, keys: Sequence[str]) -> dict[str, int]:
    """How many products share each "same medicine" key (R-C5)."""
    if not keys:
        return {}
    return {
        str(key): int(count)
        for key, count in tx.session.execute(
            select(Product.equivalence_key, func.count())
            .where(Product.equivalence_key.in_(keys))
            .group_by(Product.equivalence_key)
        )
    }


def imports(tx: Tx) -> list[CatalogImport]:
    return list(
        tx.session.execute(
            select(CatalogImport).order_by(CatalogImport.imported_at.desc())
        ).scalars()
    )
