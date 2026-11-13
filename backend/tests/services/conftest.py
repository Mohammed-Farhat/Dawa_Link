"""Setup for the service tests.

Each test gets a `World`: one database transaction that is rolled back at the end, and a
clock the test controls. The services run **as the app login**, exactly as they will in
the API and the worker, so a missing privilege fails here and not later in Docker. Only
the builders (`world.make`) run as the owner, because the app can't write the catalog.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Self

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from dawalink.db.roles import APP, RETENTION
from dawalink.domain.clock import ManualClock
from dawalink.services import email
from dawalink.services.clock_check import ClockTasks
from dawalink.services.context import Tx
from dawalink.services.email import EmailSender
from tests.conftest import DatabaseUrls
from tests.db import factories
from tests.db.factories import NOW


class _RetentionSession(Session):
    """A session that works as the retention login, then gives the app login back."""

    def __enter__(self) -> Self:
        assert isinstance(self.bind, Connection)
        self.bind.execute(text(f'SET ROLE "{RETENTION}"'))
        return super().__enter__()

    def __exit__(self, *error: Any) -> None:
        super().__exit__(*error)
        assert isinstance(self.bind, Connection)
        self.bind.execute(text(f'SET ROLE "{APP}"'))


class _Builders:
    """`world.make.item(...)` runs the builder of that name as the tables' owner."""

    def __init__(self, world: "World") -> None:
        self._world = world

    def __getattr__(self, name: str) -> Any:
        builder = getattr(factories, name)

        def build(*args: Any, **values: Any) -> Any:
            with self._world.as_owner():
                return builder(self._world.connection, *args, **values)

        return build


@dataclass
class World:
    connection: Connection
    session: Session
    clock: ManualClock

    @property
    def make(self) -> _Builders:
        return _Builders(self)

    @contextmanager
    def as_owner(self) -> Iterator[None]:
        self.session.flush()
        self.connection.execute(text("RESET ROLE"))
        try:
            yield
        finally:
            self.connection.execute(text(f'SET ROLE "{APP}"'))
            # Rows written behind the session's back must be read again.
            self.session.expire_all()

    def tx(self) -> Tx:
        """A unit of work at the clock's current time."""
        return Tx(self.session, self.clock.now())

    def settle(self, tx: Tx) -> None:
        """What `unit_of_work` does after a commit: run the deferred work, each in a new Tx."""
        self.session.flush()
        pending = tx.take_deferred()
        while pending:
            later = self.tx()
            pending.pop(0)(later)
            self.session.flush()
            pending.extend(later.take_deferred())

    def sessions(self) -> sessionmaker[Session]:
        """Sessions for code that opens its own transactions: they stay inside this test's."""
        self.session.flush()
        return sessionmaker(
            bind=self.connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )

    def clock_tasks(
        self, *, mailer: EmailSender | None = None, retention: bool = True
    ) -> ClockTasks:
        """The worker's tasks, running inside this test's transaction and on its clock.

        The purge runs as the retention login, as it does in the worker.
        """
        sessions = self.sessions()
        retention_sessions: sessionmaker[Session] = sessionmaker(
            bind=self.connection,
            class_=_RetentionSession,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        return ClockTasks(
            sessions,
            self.clock,
            mailer=mailer,
            retention_sessions=retention_sessions if retention else None,
        )

    def later(self, **by: float) -> None:
        """Move the app clock forward: `world.later(hours=2)`."""
        self.clock.advance(timedelta(**by))

    def one(self, statement: str, **values: Any) -> Any:
        """The single row a query returns, read through the session's connection."""
        self.session.flush()
        return self.connection.execute(text(statement), values).one()

    def all(self, statement: str, **values: Any) -> list[Any]:
        self.session.flush()
        return list(self.connection.execute(text(statement), values).all())

    def audit_actions(self, entity_id: uuid.UUID) -> list[str]:
        """The audit events of one entity, oldest first (INV-13)."""
        rows = self.all(
            "SELECT action FROM audit_events WHERE entity_id = :id ORDER BY id", id=entity_id
        )
        return [row.action for row in rows]

    def notifications(self, user_id: uuid.UUID) -> list[str]:
        rows = self.all(
            "SELECT type FROM notifications WHERE user_id = :id ORDER BY id", id=user_id
        )
        return [row.type for row in rows]


# INV-2: an item's reserved units are the units its open orders hold.
STOCK_OFF = (
    "SELECT ii.id FROM inventory_items ii "
    "LEFT JOIN orders o ON o.inventory_item_id = ii.id AND o.state IN ('OFFERED', 'RESERVED') "
    "GROUP BY ii.id HAVING ii.qty_reserved <> COALESCE(SUM(o.qty_locked), 0)"
)
# INV-18, for open requests: an item's secured units are its reserved or picked-up units,
# and it is SECURED exactly when they cover its quantity.
REQUESTS_OFF = (
    "SELECT ri.id FROM request_items ri "
    "JOIN sourcing_requests r ON r.id = ri.request_id AND r.state = 'OPEN' "
    "LEFT JOIN orders o ON o.request_item_id = ri.id AND o.state IN ('RESERVED', 'PICKED_UP') "
    "GROUP BY ri.id, ri.qty, ri.qty_secured, ri.state "
    "HAVING ri.qty_secured <> COALESCE(SUM(CASE WHEN o.state = 'RESERVED' THEN o.qty_locked "
    "                                         ELSE o.qty_picked_up END), 0) "
    "    OR (ri.state = 'SECURED') <> (ri.qty_secured >= ri.qty)"
)


def _check_what_the_test_left(connection: Connection, session: Session, strict: bool) -> None:
    """Whatever a test was testing, what it leaves behind must be sound.

    - every email it queued has a complete subject;
    - the stock and the requests still add up (INV-2, INV-18), unless the test built rows
      by hand that were never meant to (`@pytest.mark.rows_by_hand`).
    """
    try:
        session.flush()
        queued = connection.execute(text("SELECT template, params FROM email_outbox")).all()
        stock_off = connection.execute(text(STOCK_OFF)).all()
        requests_off = connection.execute(text(REQUESTS_OFF)).all()
    except DBAPIError:
        return  # the test left its transaction broken on purpose
    for template, params in queued:
        assert not email.missing_fields(template, params), (template, params)
    if strict:
        assert stock_off == [], "INV-2: reserved units differ from the open orders' units"
        assert requests_off == [], "INV-18: a request item's secured units don't add up"


@pytest.fixture
def world(urls: DatabaseUrls, request: pytest.FixtureRequest) -> Iterator[World]:
    # The master login: it may become the app login and go back, which the owner can't.
    engine = create_engine(urls.admin)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    connection.execute(text(f'SET ROLE "{APP}"'))
    try:
        yield World(connection, session, ManualClock(NOW))
        strict = request.node.get_closest_marker("rows_by_hand") is None
        _check_what_the_test_left(connection, session, strict)
    finally:
        session.close()
        transaction.rollback()
        connection.execute(text("RESET ROLE"))
        connection.close()
        engine.dispose()
