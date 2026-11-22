"""GET /health (docs/06 §6.1)."""

import asyncio
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Literal, cast

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import Engine

from dawalink.config import Settings
from dawalink.db.session import database_is_up
from dawalink.domain.numbers import HEALTH_DB_WAIT_S

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "down"]
    version: str


class DatabasePing:
    """Asks the database "are you there?" on a thread of its own (A#6).

    Not on the event loop, where a slow answer would hold up every request; and not on
    the threads the other endpoints share, which a burst of requests may all be using.
    One question at a time: callers that come while one is out wait for its answer, so a
    database that doesn't answer never piles up questions.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="health")
        self._lock = threading.Lock()
        self._asked: Future[bool] | None = None

    async def is_up(self, wait_s: float = HEALTH_DB_WAIT_S) -> bool:
        """Whether the database answered within `wait_s`."""
        with self._lock:
            if self._asked is None or self._asked.done():
                self._asked = self._thread.submit(database_is_up, self._engine)
            asked = self._asked
        try:
            # Shielded: a caller that stops waiting never cancels the others' question.
            return await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(asked)), wait_s)
        except TimeoutError:
            return False

    def shutdown(self) -> None:
        self._thread.shutdown(wait=False, cancel_futures=True)


# Runs on the event loop and reads the app's state directly: a dependency written as a
# plain function would wait for one of the threads the other endpoints share, which is
# what this check must never do (A#6). A database slower than HEALTH_DB_WAIT_S is "down".
# (Not in the docstring below: that one is the endpoint's description in the OpenAPI file.)
@router.get("/health")
async def health(request: Request) -> Health:
    """Always 200 while the process runs.

    The load balancer only needs to know the process is alive. If this answered 503 when the
    database is down, healthy API tasks would be killed instead of answering "try again" (FX-10).
    """
    settings = cast(Settings, request.app.state.settings)
    ping = cast(DatabasePing, request.app.state.database_ping)
    db_up = await ping.is_up()
    return Health(
        status="ok" if db_up else "degraded",
        db="ok" if db_up else "down",
        version=settings.app_version,
    )
