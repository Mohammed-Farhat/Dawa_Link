"""The app clock: real time, plus the demo offset in demo mode (docs/04 R-T11, R-DEMO).

Everything that needs the time asks this clock, so moving it forward in a demo makes
offers expire, windows end and no-shows happen, with no other change.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert as upsert

from dawalink.db.models import AppState
from dawalink.domain.clock import Clock, SystemClock
from dawalink.domain.state_machine import Actor
from dawalink.services import audit
from dawalink.services.context import Tx
from dawalink.services.errors import Code, ServiceError

OFFSET_KEY = "demo_clock_offset_seconds"


class AppClock:
    """Real time. In demo mode, real time plus the offset an admin has added."""

    def __init__(self, engine: Engine, *, demo_mode: bool, real: Clock | None = None) -> None:
        self._engine = engine
        self._demo_mode = demo_mode
        self._real = real or SystemClock()

    def now(self) -> datetime:
        if not self._demo_mode:
            return self._real.now()
        with self._engine.connect() as connection:
            offset = connection.execute(
                select(AppState.value).where(AppState.key == OFFSET_KEY)
            ).scalar()
        return self._real.now() + timedelta(seconds=int(offset or 0))


def demo_offset(tx: Tx) -> timedelta:
    offset = tx.session.execute(select(AppState.value).where(AppState.key == OFFSET_KEY)).scalar()
    return timedelta(seconds=int(offset or 0))


def advance_demo_clock(
    tx: Tx, admin_id: uuid.UUID, by: timedelta, *, demo_mode: bool, reason: str
) -> timedelta:
    """An admin moves the app clock forward. Demo mode only; every advance is audited."""
    if not demo_mode:
        raise ServiceError(Code.NOT_FOUND, "The demo clock is off.")
    if by <= timedelta(0):
        raise ServiceError(Code.VALIDATION_ERROR, "The clock only moves forward.")
    before = demo_offset(tx)
    after = before + by
    statement = upsert(AppState).values(key=OFFSET_KEY, value=int(after.total_seconds()))
    tx.session.execute(
        statement.on_conflict_do_update(
            index_elements=[AppState.key], set_={"value": statement.excluded.value}
        )
    )
    audit.record(
        tx,
        Actor.ADMIN,
        "clock.advance",
        "app_state",
        None,
        actor_id=admin_id,
        before={"offset_seconds": int(before.total_seconds())},
        after={"offset_seconds": int(after.total_seconds())},
        reason=reason,
    )
    return after
