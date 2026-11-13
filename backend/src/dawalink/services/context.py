"""One transaction of work, with the app clock's time (docs/05 §6, docs/04 R-T11).

A service never commits and never reads a clock: it gets a `Tx`. Work that must wait for
the commit (matching, which takes its own locks) is deferred and run right after it.
"""

from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime

import structlog
from sqlalchemy.orm import Session, sessionmaker

from dawalink.domain.clock import Clock, beirut_date

log = structlog.get_logger(__name__)


@dataclass
class Tx:
    session: Session
    # The app clock's time when this transaction started. Every deadline is computed from it.
    now: datetime
    _deferred: dict[Hashable, Callable[["Tx"], None]] = field(default_factory=dict)

    @property
    def today(self) -> date:
        """The Beirut date: what "days left" and pickup days are counted from."""
        return beirut_date(self.now)

    def defer(self, key: Hashable, action: Callable[["Tx"], None]) -> None:
        """Run `action` in its own transaction after this one commits. One per key."""
        self._deferred.setdefault(key, action)

    def take_deferred(self) -> list[Callable[["Tx"], None]]:
        actions = list(self._deferred.values())
        self._deferred.clear()
        return actions


@contextmanager
def unit_of_work(sessions: sessionmaker[Session], clock: Clock) -> Iterator[Tx]:
    """Commit on success, roll back on any error, then run what was deferred.

    Each deferred action gets a fresh transaction, so it never runs while this one's row
    locks are held. The main work is already committed by then, so a deferred action that
    fails is logged and the rest still run: the caller's work succeeded. The clock check
    looks for the same follow-up work on every pass (the matching sweep, requests whose
    medicines are all settled, early-release requests with no ask left), so it is done
    a few seconds later.
    """
    pending: list[Callable[[Tx], None]] = []
    with sessions() as session:
        tx = Tx(session, clock.now())
        try:
            yield tx
            session.commit()
        except BaseException:
            session.rollback()
            raise
        pending = tx.take_deferred()
    while pending:
        action = pending.pop(0)
        with sessions() as session:
            tx = Tx(session, clock.now())
            try:
                action(tx)
                session.commit()
            except Exception:
                session.rollback()
                log.exception("deferred_action_failed")
                continue
            except BaseException:
                session.rollback()
                raise
            pending.extend(tx.take_deferred())
