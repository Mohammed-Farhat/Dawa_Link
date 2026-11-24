"""Finding medicines in the catalog (docs/04 R-C5, R-C6; the agent's `search_catalog`).

Controlled medicines are never returned, by any path (INV-6).
"""

import re
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Row, func, select, text

from dawalink.catalog.composition import normalize
from dawalink.db.models import CatalogImport, Product
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError
from dawalink.services.paging import count_rows

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


# Words a person adds to a medicine's name that say its form, and the words the catalog's
# form column uses for it. "Adol 500 caplets" is a search for Adol: the catalog keeps the
# form in a column of its own, so taken as part of the name the word hid the medicine.
_TABLET, _CAPSULE, _LIQUID = ("tablet",), ("capsule",), ("syrup", "suspension", "elixir")
_INJECTED, _SUPPOSITORY = ("injectable", "injection"), ("suppository",)
FORM_WORDS: Mapping[str, tuple[str, ...]] = {
    **dict.fromkeys(("tablet", "tablets", "tab", "tabs"), _TABLET),
    **dict.fromkeys(("caplet", "caplets"), ("caplet",)),
    **dict.fromkeys(("capsule", "capsules", "caps"), _CAPSULE),
    **dict.fromkeys(("pill", "pills"), ("tablet", "caplet", "capsule")),
    **dict.fromkeys(("syrup", "sirop"), _LIQUID),
    **dict.fromkeys(("drop", "drops"), ("drops",)),
    **dict.fromkeys(("suppository", "suppositories", "supp"), _SUPPOSITORY),
    **dict.fromkeys(("injection", "injections", "ampoule", "ampoules", "ampule"), _INJECTED),
    **dict.fromkeys(("sachet", "sachets"), ("powder", "granules")),
    **dict.fromkeys(("patch", "patches"), ("patch",)),
    "inhaler": ("inhalation", "inhaler", "aerosol"),
    "gel": ("gel", "emulgel"),
    **{
        word: (word,)
        for word in ("suspension", "cream", "ointment", "spray", "chewable", "effervescent")
    },
    **{word: (word,) for word in ("solution", "lotion", "powder")},
}
# A unit written apart from its number ("10 mg"): it says nothing about which medicine.
UNIT_WORDS = frozenset({"mg", "mcg", "g", "gm", "gr", "ml", "iu"})
MIN_BARE_NAME = 4
# The strength and the form are ranked in Python, after this cut: it must hold every
# product of one ingredient ("paracetamol syrup"), or the syrups could be cut first.
MAX_SCORED = 500


def search_products(tx: Tx, query: str, *, limit: int = 8) -> ProductSearch:
    """Medicines whose name or ingredient looks like the query, best first.

    Spelling mistakes are tolerated ("ogmentin"). A strength in the query ("1g", "500")
    doesn't take part in the name match: it only moves the products with that strength up.

    A form or a unit in the query ("caplets", "syrup", "mg") is read both ways: the name is
    matched with it and without it, and the better match counts. So "Adol 500 caplets"
    finds Adol, and a name that really holds the word ("... syrup") still matches whole.
    The form then moves the products of that form up. Among equally good matches, the
    name closest to the query as a whole comes first, not the first in the alphabet.
    """
    words = normalize(query[:MAX_QUERY_LENGTH]).split()
    named = [word for word in words if not word[0].isdigit()]
    strengths = [word for word in words if word[0].isdigit()]
    name = " ".join(named)
    if not name:
        return ProductSearch([], [])
    forms = [FORM_WORDS[word] for word in named if word in FORM_WORDS]
    bare = " ".join(w for w in named if w not in FORM_WORDS and w not in UNIT_WORDS)
    if len(bare.replace(" ", "")) < MIN_BARE_NAME:
        # Two or three letters alone look like every name that starts with them
        # ("fe drops" is not Fenofibrate): such a name keeps its other words.
        bare = name

    rows = tx.session.execute(
        text(
            """
            SELECT p.id,
                   GREATEST(
                     word_similarity(:q, p.search_name),
                     word_similarity(:b, p.search_name),
                     COALESCE((SELECT max(GREATEST(word_similarity(:q, pi.name_normalized),
                                                   word_similarity(:b, pi.name_normalized)))
                               FROM product_ingredients pi WHERE pi.product_id = p.id), 0)
                   ) AS score,
                   similarity(:b, p.search_name) AS near
            FROM products p
            WHERE NOT p.controlled
              AND (:q <% p.search_name
                   OR :b <% p.search_name
                   OR p.search_name % :q
                   OR p.search_name % :b
                   OR EXISTS (SELECT 1 FROM product_ingredients pi
                              WHERE pi.product_id = p.id
                                AND (:q <% pi.name_normalized OR :b <% pi.name_normalized)))
            ORDER BY score DESC, near DESC, p.moph_name, p.moph_code
            LIMIT :most
            """
        ),
        {"q": name, "b": bare, "most": MAX_SCORED},
    ).all()
    scores = {product_id: float(score) for product_id, score, _ in rows}
    near = {product_id: float(closeness) for product_id, _, closeness in rows}
    products = list(tx.session.execute(select(Product).where(Product.id.in_(scores))).scalars())

    def has_the_strength(product: Product) -> bool:
        said = re.sub(r"[^a-z0-9.]", "", (product.dosage_text or "").lower())
        return all(strength in said for strength in strengths)

    def has_the_form(product: Product) -> bool:
        said = set(normalize(f"{product.form_text or ''} {product.moph_name}").split())
        return all(said.intersection(form) for form in forms)

    products.sort(
        key=lambda p: (
            not has_the_strength(p),
            -scores[p.id],
            not has_the_form(p),
            -near[p.id],
            p.moph_name,
            p.moph_code,
        )
    )
    confident = [p for p in products if scores[p.id] >= CONFIDENT]
    if confident:
        return ProductSearch([ref(p) for p in confident[:limit]], [])
    suggestions = list(dict.fromkeys(p.moph_name for p in products))[:3]
    return ProductSearch([], suggestions)


@dataclass(frozen=True)
class NameSearch:
    """What the search page shows for a typed name: every medicine that matches, not a
    list to choose from first."""

    products: list[Product]  # best match first
    # Nothing is written exactly like the query: these are the closest names, and the
    # page says so before it shows them.
    closest: bool
    # The products that matched by an ingredient, not by their own name.
    by_ingredient: frozenset[uuid.UUID]
    # Other names that look like the query, to offer as "Did you mean…?".
    did_you_mean: list[str]


# A brand word this close to a misspelled query is taken as what the client meant
# ("pandol" and "panadol": 0.5), and the page says which name it shows.
CLOSE_WORD = 0.4
MAX_NAME_MATCHES = 40


SHORT = 3


def find_by_name(tx: Tx, query: str, *, among: Sequence[uuid.UUID] | None = None) -> NameSearch:
    """Every medicine a typed name stands for (CS-6).

    `among`: only these products are looked at. The search page itself asks
    `find_in_stock`, which looks at the whole catalog first (review B#1); the last
    searches ask this one, to keep only a name the catalog knows.

    One or two letters are the start of a name's word ("p": Panadol, Plavix), never a
    guess at a spelling: two letters look like too many names.

    "panadol" is all the Panadols; "pandol" is taken as the closest brand word, and the
    result says it is a closest match. A strength in the query moves the products that
    have it up. It is the search page's own function: the agent's `search_catalog` keeps
    `search_products`, whose answers the evaluation is measured on.
    """
    name, strengths = _name_and_strengths(query)
    if not name or among == []:
        return NameSearch([], False, frozenset(), [])
    if len(name) < SHORT:
        return _starting_with(tx, name, among)
    rows = _scored(tx, name, among)
    if not rows:
        return NameSearch([], False, frozenset(), [])

    confident = {row.id: row for row in rows if _is_confident(row)}
    closest = False
    if confident:
        chosen = confident
        # Other brand words that look like the query ("brofen" finds ibuprofen by its
        # letters; Brufen is offered next to it).
        others = [row for row in rows if row.id not in confident and row.by_word >= CLOSE_WORD]
    else:
        near = [row for row in rows if row.by_word >= CLOSE_WORD]
        if not near:
            names = sorted(rows, key=lambda row: -max(row.by_name, row.by_word))
            return NameSearch([], False, frozenset(), _first_names(tx, [r.id for r in names]))
        best = _best(near)
        chosen = {row.id: row for row in near if row.closest_word == best.closest_word}
        # Everything else that looked a little like the query is offered by name.
        others = [row for row in rows if row.id not in chosen]
        closest = True
    return _answer(tx, name, strengths, chosen, others, closest=closest)


def find_in_stock(tx: Tx, query: str, stocked: Collection[uuid.UUID]) -> NameSearch:
    """What a typed name stands for on the search page: **the medicine it names, in stock,
    or nothing** (CS-6; R-S4, INV-26).

    The whole catalog is asked first. When the words name a medicine ("concor" is
    Concor), only that medicine is shown, and with none on a shelf the answer is empty:
    the page says that no pharmacy has it and offers the assistant. It is never "the
    closest name in stock", which would call a correct name a misspelling and lead the
    client to another brand (B-Cor) with [Reserve] and no "ask the pharmacist first"
    (review B#1). Another brand is shown only by the assistant (BLD-D17).

    Only when the catalog knows no medicine by the words is the closest name in stock
    offered, and said to be the closest ("pandol": the Panadols). Even then, never
    another brand of what the words most likely mean, nor as a "Did you mean…?".

    One or two letters are the start of a name's word among the medicines in stock, as
    in `find_by_name`.
    """
    name, strengths = _name_and_strengths(query)
    in_stock = set(stocked)
    if not name or not in_stock:
        return NameSearch([], False, frozenset(), [])
    if len(name) < SHORT:
        return _starting_with(tx, name, list(in_stock))
    rows = _scored(tx, name, None)

    confident = {row.id: row for row in rows if _is_confident(row)}
    if confident:
        chosen = {
            product_id: row for product_id, row in confident.items() if product_id in in_stock
        }
        if not chosen:
            return NameSearch([], False, frozenset(), [])
        another_brand = _another_brand_of(list(confident.values()))
        others = [
            row
            for row in rows
            if row.id in in_stock
            and row.id not in chosen
            and row.by_word >= CLOSE_WORD
            and not another_brand(row)
        ]
        return _answer(tx, name, strengths, chosen, others, closest=False)

    # No medicine has this name: the words are taken as a misspelling. What they most
    # likely mean is the closest brand word of the whole catalog, in stock or not.
    near = [row for row in rows if row.by_word >= CLOSE_WORD]
    another_brand = _another_brand_of(
        [row for row in near if row.closest_word == _best(near).closest_word] if near else []
    )
    shelf = [row for row in rows if row.id in in_stock and not another_brand(row)]
    near_shelf = [row for row in shelf if row.by_word >= CLOSE_WORD]
    if not near_shelf:
        names = sorted(shelf, key=lambda row: -max(row.by_name, row.by_word))
        return NameSearch([], False, frozenset(), _first_names(tx, [r.id for r in names]))
    best = _best(near_shelf)
    chosen = {row.id: row for row in near_shelf if row.closest_word == best.closest_word}
    others = [row for row in shelf if row.id not in chosen]
    return _answer(tx, name, strengths, chosen, others, closest=True)


def _name_and_strengths(query: str) -> tuple[str, list[str]]:
    """The words of a typed name, and the strengths in it ("panadol 500": "500")."""
    words = normalize(query[:MAX_QUERY_LENGTH]).split()
    name = " ".join(word for word in words if not word[0].isdigit())
    return name, [word for word in words if word[0].isdigit()]


def _is_confident(row: Row[Any]) -> bool:
    return bool(max(row.by_name, row.by_ingredient) >= CONFIDENT)


def _best(rows: Sequence[Row[Any]]) -> Row[Any]:
    """The row whose brand word is closest to the query."""
    return max(rows, key=lambda row: (row.by_word, row.closest_word))


def _another_brand_of(meant: Sequence[Row[Any]]) -> Callable[[Row[Any]], bool]:
    """Whether a row is another brand of one of these medicines: the same equivalence key
    under another name (R-C10). The same name is the same medicine, whoever makes it (Q38)."""
    keys = {row.equivalence_key for row in meant if row.equivalence_key is not None}
    names = {row.search_name for row in meant}
    return lambda row: row.equivalence_key in keys and row.search_name not in names


def _starting_with(tx: Tx, name: str, among: Sequence[uuid.UUID] | None) -> NameSearch:
    """One or two letters: the medicines with a word that starts with them."""
    scope = "AND p.id = ANY(:among)" if among is not None else ""
    limits = {"among": list(among)} if among is not None else {}
    starts = tx.session.execute(
        text(
            f"""
            SELECT p.id FROM products p
            WHERE NOT p.controlled {scope}
              AND (p.search_name LIKE :start ESCAPE '!' OR p.search_name LIKE :word ESCAPE '!')
            -- A name that begins with the letters comes before one that has them in a
            -- later word: "p" is Panadol before "Micardis Plus".
            ORDER BY (p.search_name LIKE :start ESCAPE '!') DESC, p.moph_name, p.moph_code
            LIMIT :most
            """
        ),
        {
            "start": _like(name) + "%",
            "word": "% " + _like(name) + "%",
            "most": MAX_NAME_MATCHES,
            **limits,
        },
    ).scalars()
    ids = list(starts)
    found = {
        p.id: p for p in tx.session.execute(select(Product).where(Product.id.in_(ids))).scalars()
    }
    return NameSearch([found[i] for i in ids if i in found], False, frozenset(), [])


def _scored(tx: Tx, name: str, among: Sequence[uuid.UUID] | None) -> Sequence[Row[Any]]:
    """The products the words look like, with how much: by their name, by an ingredient,
    by their closest word. Never a controlled one (INV-6)."""
    scope = "AND p.id = ANY(:among)" if among is not None else ""
    limits = {"among": list(among)} if among is not None else {}
    return tx.session.execute(
        text(
            f"""
            SELECT p.id, p.equivalence_key, p.search_name,
                   word_similarity(:q, p.search_name) AS by_name,
                   COALESCE((SELECT max(word_similarity(:q, pi.name_normalized))
                             FROM product_ingredients pi WHERE pi.product_id = p.id), 0)
                     AS by_ingredient,
                   (SELECT max(similarity(:q, word))
                    FROM unnest(string_to_array(p.search_name, ' ')) AS word) AS by_word,
                   (SELECT word FROM unnest(string_to_array(p.search_name, ' ')) AS word
                    ORDER BY similarity(:q, word) DESC, word LIMIT 1) AS closest_word
            FROM products p
            WHERE NOT p.controlled {scope}
              AND (:q <% p.search_name
                   OR p.search_name % :q
                   OR p.search_name LIKE :start ESCAPE '!'
                   OR p.search_name LIKE :word ESCAPE '!'
                   OR EXISTS (SELECT 1 FROM product_ingredients pi
                              WHERE pi.product_id = p.id AND :q <% pi.name_normalized))
            """
        ),
        {"q": name, "start": _like(name) + "%", "word": "% " + _like(name) + "%", **limits},
    ).all()


def _answer(
    tx: Tx,
    name: str,
    strengths: Sequence[str],
    chosen: Mapping[uuid.UUID, Row[Any]],
    others: Sequence[Row[Any]],
    *,
    closest: bool,
) -> NameSearch:
    """The chosen medicines, best first, and the other names to offer."""
    products = list(tx.session.execute(select(Product).where(Product.id.in_(chosen))).scalars())

    def has_the_strength(product: Product) -> bool:
        said = re.sub(r"[^a-z0-9.]", "", (product.dosage_text or "").lower())
        return all(strength in said for strength in strengths)

    def score(product: Product) -> float:
        row = chosen[product.id]
        return float(max(row.by_name, row.by_ingredient, row.by_word))

    products.sort(key=lambda p: (not has_the_strength(p), -score(p), p.moph_name, p.moph_code))
    shown = products[:MAX_NAME_MATCHES]
    # "Exactly like the query": some shown name has a word that starts with what was typed.
    first = name.split()[0]
    if not closest and not any(
        word.startswith(first) for p in shown for word in (p.search_name or "").split()
    ):
        closest = all(chosen[p.id].by_name >= chosen[p.id].by_ingredient for p in shown)
    return NameSearch(
        products=shown,
        closest=closest,
        by_ingredient=frozenset(
            p.id for p in shown if chosen[p.id].by_ingredient > chosen[p.id].by_name
        ),
        did_you_mean=_first_names(
            tx, [row.id for row in sorted(others, key=lambda row: -row.by_word)]
        ),
    )


def _like(words: str) -> str:
    """The words as themselves inside a LIKE pattern: `%` and `_` mean nothing here."""
    return words.replace("!", "!!").replace("%", "!%").replace("_", "!_")


def _first_names(tx: Tx, product_ids: Sequence[uuid.UUID], *, limit: int = 3) -> list[str]:
    """The names of these products, in their order, each once."""
    if not product_ids:
        return []
    names = dict(
        tx.session.execute(
            select(Product.id, Product.moph_name).where(Product.id.in_(product_ids[:30]))
        ).all()
    )
    return list(dict.fromkeys(names[i] for i in product_ids[:30] if i in names))[:limit]


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


def admin_products(
    tx: Tx, query: str, *, offset: int = 0, limit: int = 50
) -> tuple[list[Product], int]:
    """The catalog as an admin reads it (AS-9): every product, **the controlled ones
    included**, which nobody else ever sees (R-C6). Read-only: the catalog changes by the
    import script and the team's override files.

    Returns a page of it and how many products the same text matches (numbered pages)."""
    statement = select(Product)
    wanted = normalize(query)
    if query.strip() and not wanted:
        # Typed, but no letter or digit in it ("%", "_"): that names no product. Without
        # this it would list the whole catalog, as an empty search does.
        return [], 0
    if wanted:
        statement = statement.where(Product.search_name.contains(wanted, autoescape=True))
    page = list(
        tx.session.execute(
            statement.order_by(Product.moph_name, Product.moph_code).offset(offset).limit(limit)
        ).scalars()
    )
    return page, count_rows(tx, statement)


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
