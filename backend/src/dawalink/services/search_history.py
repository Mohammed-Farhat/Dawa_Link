"""A client's last searches (docs/03 CS-6; the owner, 2026-11-18, decision log BLD-D42).

What a person searched says something about their health. So: only the client reads
their own list, nothing here is ever sent to the LLM, a pharmacy or an admin, and the
daily clean-up removes what is older than 30 days.

**Only a medicine's name is kept:** the words must have the plain shape of a name, and
the catalog must know a medicine they stand for. A phone number, an email or a sentence
typed in the box by mistake is left out, and so is the name of a controlled medicine,
which the catalog search never returns.
"""

import uuid

from sqlalchemy import delete, func, select

from dawalink.catalog.composition import normalize
from dawalink.db.models import SearchHistory
from dawalink.domain.numbers import SEARCH_HISTORY_KEPT, SEARCH_HISTORY_SHOWN
from dawalink.services import catalog
from dawalink.services.context import Tx

MAX_CHARS = 60


def _as_kept(text: str) -> str | None:
    """The words as they are kept: letters, digits and single spaces. None for anything
    that is not a name to search again (too short, too long, or made of symbols)."""
    words = " ".join(text.split())
    if not 2 <= len(words) <= MAX_CHARS:
        return None
    if not all(char.isalnum() or char in " .-'" for char in words):
        return None
    return words if normalize(words) else None


def record(tx: Tx, client_id: uuid.UUID, text: str) -> bool:
    """Puts this name at the top of the client's searches. The same name again moves it
    up, it isn't listed twice. Returns whether it was kept."""
    words = _as_kept(text)
    if words is None:
        return False
    # The catalog must know a medicine by these words (a misspelled name finds its
    # closest one, as on the search page). Anything else is not a search to keep.
    if not catalog.find_by_name(tx, words).products:
        return False
    tx.session.execute(
        delete(SearchHistory).where(
            SearchHistory.client_id == client_id, func.lower(SearchHistory.query) == words.lower()
        )
    )
    tx.session.add(SearchHistory(client_id=client_id, query=words, searched_at=tx.now))
    tx.session.flush()
    # Only the newest are kept: a list nobody can scroll through has no use.
    old = tx.session.execute(
        select(SearchHistory.id)
        .where(SearchHistory.client_id == client_id)
        .order_by(SearchHistory.searched_at.desc(), SearchHistory.id.desc())
        .offset(SEARCH_HISTORY_KEPT)
    ).scalars()
    stale = list(old)
    if stale:
        tx.session.execute(delete(SearchHistory).where(SearchHistory.id.in_(stale)))
    return True


def recent(tx: Tx, client_id: uuid.UUID) -> list[str]:
    """The client's last searches, the newest first."""
    rows = tx.session.execute(
        select(SearchHistory.query)
        .where(SearchHistory.client_id == client_id)
        .order_by(SearchHistory.searched_at.desc(), SearchHistory.id.desc())
        .limit(SEARCH_HISTORY_SHOWN)
    ).scalars()
    return list(rows)


def clear(tx: Tx, client_id: uuid.UUID) -> int:
    """[Clear]: every search of this client is deleted. Returns how many."""
    done = tx.session.execute(delete(SearchHistory).where(SearchHistory.client_id == client_id))
    return int(done.rowcount or 0)  # type: ignore[attr-defined]
