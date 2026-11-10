"""GET /health (docs/06 §6.1)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Engine

from dawalink.api.deps import get_engine, get_settings
from dawalink.config import Settings
from dawalink.db.session import database_is_up

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    db: Literal["ok", "down"]
    version: str


@router.get("/health")
def health(
    settings: Annotated[Settings, Depends(get_settings)],
    engine: Annotated[Engine, Depends(get_engine)],
) -> Health:
    """Always 200 while the process runs.

    The load balancer only needs to know the process is alive. If this answered 503 when the
    database is down, healthy API tasks would be killed instead of answering "try again" (FX-10).
    """
    db_up = database_is_up(engine)
    return Health(
        status="ok" if db_up else "degraded",
        db="ok" if db_up else "down",
        version=settings.app_version,
    )
