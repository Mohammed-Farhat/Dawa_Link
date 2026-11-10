"""Order and request numbers such as `R-7K3Q2F` (docs/05 §1, docs/10 TM-D4).

They're random, so nobody can guess someone else's, and their alphabet has no look-alike
characters (no 0/O, no 1/I), so they're easy to read out at a pharmacy counter.
"""

import secrets
from collections.abc import Callable, Sequence
from typing import Literal

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
LENGTH = 6

RefPrefix = Literal["R", "Q"]  # R = order, Q = sourcing request


def new_ref(prefix: RefPrefix, choose: Callable[[Sequence[str]], str] = secrets.choice) -> str:
    """A fresh number. The caller regenerates it in the rare case it already exists."""
    return f"{prefix}-" + "".join(choose(ALPHABET) for _ in range(LENGTH))


def normalize_ref(text: str, prefix: RefPrefix) -> str | None:
    """What a person typed, as a proper number: case and the dash don't matter.

    Returns None when it can't be one of our numbers.
    """
    compact = text.strip().upper().replace("-", "").replace(" ", "")
    body = compact.removeprefix(prefix)
    if compact == body or len(body) != LENGTH or any(char not in ALPHABET for char in body):
        return None
    return f"{prefix}-{body}"
