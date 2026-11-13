"""Setup for the race tests: real connections, real commits, two things at the same moment.

The service tests run inside one transaction, so they can't show what happens when two
people act at once. These tests use a throwaway database and the real logins: the app
login for the services, the retention login for the purge.

`arena.together(a, b, hold="orders")` makes the race certain instead of lucky. It locks
the named table, starts both actions, waits until the database reports both of them
blocked, and only then lets go: the two transactions are open at the same time, every time.
"""

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session, sessionmaker

from dawalink.db.roles import APP
from dawalink.db.session import make_engine
from dawalink.domain.clock import ManualClock
from dawalink.services.context import Tx, unit_of_work
from tests.conftest import DatabaseUrls, prepare_database, run_as_admin
from tests.db import factories
from tests.db.factories import NOW

DATABASE = "dawalink_race_test"
PATIENCE_S = 4.0  # under the app's statement timeout (N-40), so a stuck test fails clearly


class _Builders:
    """`arena.make.item(...)` runs the builder of that name as the owner, and commits."""

    def __init__(self, owner: Engine) -> None:
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        builder = getattr(factories, name)

        def build(*args: Any, **values: Any) -> Any:
            with self._owner.begin() as connection:
                return builder(connection, *args, **values)

        return build


@dataclass
class Arena:
    urls: DatabaseUrls
    owner: Engine
    admin: Engine
    sessions: sessionmaker[Session]
    clock: ManualClock

    @property
    def make(self) -> _Builders:
        return _Builders(self.owner)

    def run[T](self, action: Callable[[Tx], T]) -> T:
        """One action in its own committed transaction, with its deferred work, as in the API."""
        clock = getattr(action, "clock", self.clock)
        with unit_of_work(self.sessions, clock) as tx:
            return action(tx)

    def when[T](self, moment: datetime, action: Callable[[Tx], T]) -> Callable[[Tx], T]:
        """The same action, run at its own time: the clock check a second after a tap."""

        def at_that_moment(tx: Tx) -> T:
            return action(tx)

        at_that_moment.clock = ManualClock(moment)  # type: ignore[attr-defined]
        return at_that_moment

    def together(self, *actions: Callable[[Tx], Any], hold: str) -> list[Any]:
        """Runs the actions at the same moment. Each result is what it returned, or its error."""
        results: list[Any] = [None] * len(actions)

        def work(position: int, action: Callable[[Tx], Any]) -> None:
            try:
                results[position] = self.run(action)
            except Exception as error:
                results[position] = error

        threads = [
            threading.Thread(target=work, args=(position, action))
            for position, action in enumerate(actions)
        ]
        with self.owner.connect() as blocker:
            blocker.execute(text(f"LOCK TABLE {hold} IN ACCESS EXCLUSIVE MODE"))
            for thread in threads:
                thread.start()
            self._wait_until_blocked(len(actions))
            blocker.commit()
        for thread in threads:
            thread.join(timeout=PATIENCE_S * 3)
            assert not thread.is_alive(), "an action never finished"
        return results

    def _wait_until_blocked(self, how_many: int) -> None:
        give_up = time.monotonic() + PATIENCE_S
        with self.admin.connect() as connection:
            while time.monotonic() < give_up:
                blocked = connection.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                        "AND usename = :app AND wait_event_type = 'Lock'"
                    ),
                    {"app": APP},
                ).scalar_one()
                if blocked >= how_many:
                    return
                time.sleep(0.02)
        raise AssertionError(f"only {blocked} of {how_many} actions reached the lock")

    def one(self, statement: str, **values: Any) -> Any:
        with self.owner.connect() as connection:
            return connection.execute(text(statement), values).one()

    def all(self, statement: str, **values: Any) -> list[Any]:
        with self.owner.connect() as connection:
            return list(connection.execute(text(statement), values).all())

    def write(self, statement: str, **values: Any) -> None:
        with self.owner.begin() as connection:
            connection.execute(text(statement), values)


@pytest.fixture(scope="module")
def arena(development_urls: DatabaseUrls) -> Iterator[Arena]:
    urls = development_urls.on(DATABASE)
    run_as_admin(
        urls,
        f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)',
        f'CREATE DATABASE "{DATABASE}"',
    )
    engines: list[Engine] = []
    try:
        prepare_database(urls)
        owner = create_engine(urls.migrator)
        admin = create_engine(
            make_url(urls.admin), isolation_level="AUTOCOMMIT", pool_pre_ping=True
        )
        app = make_engine(urls.app)
        engines += [owner, admin, app]
        yield Arena(urls, owner, admin, sessionmaker(app, expire_on_commit=False), ManualClock(NOW))
    finally:
        for engine in engines:
            engine.dispose()
        run_as_admin(urls, f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)')


@pytest.fixture(autouse=True)
def _books_balance(arena: Arena) -> Iterator[None]:
    """After every race, whoever won: the stock and the requests still add up."""
    yield
    # INV-1 is a database constraint. INV-2: reserved units are the open orders' units.
    assert not arena.all(
        "SELECT ii.id FROM inventory_items ii "
        "LEFT JOIN orders o ON o.inventory_item_id = ii.id AND o.state IN ('OFFERED', 'RESERVED') "
        "GROUP BY ii.id HAVING ii.qty_reserved <> COALESCE(SUM(o.qty_locked), 0)"
    )
    # INV-20: a claim never holds more units than it asked for.
    assert not arena.all(
        "SELECT c.id FROM claims c JOIN orders o ON o.claim_id = c.id AND o.state = 'RESERVED' "
        "GROUP BY c.id, c.qty HAVING SUM(o.qty_locked) > c.qty"
    )
