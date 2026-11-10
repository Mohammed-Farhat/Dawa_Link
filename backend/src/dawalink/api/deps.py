"""What endpoints can ask for: the settings and the database engine of this app."""

from typing import cast

from fastapi import Request
from sqlalchemy import Engine

from dawalink.config import Settings


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_engine(request: Request) -> Engine:
    return cast(Engine, request.app.state.engine)
