"""The database engine and its timeouts."""

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from dawalink.domain.numbers import DB_CONNECT_TIMEOUT_S, DB_STATEMENT_TIMEOUT_S


def make_engine(database_url: str) -> Engine:
    """The app's engine: every statement is cut off after N-40, so nothing hangs (docs/09 P6)."""
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": DB_CONNECT_TIMEOUT_S,
            "options": f"-c statement_timeout={DB_STATEMENT_TIMEOUT_S * 1000}",
        },
    )


def database_is_up(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True
