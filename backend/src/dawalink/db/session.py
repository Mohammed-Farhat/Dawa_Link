"""The database engine and its timeouts."""

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from dawalink.domain.numbers import DB_CONNECT_TIMEOUT_S, DB_STATEMENT_TIMEOUT_S


def make_engine(database_url: str) -> Engine:
    """The app's engine: every statement is cut off after N-40, so nothing hangs (docs/09 P6).

    Waiting for a free connection is cut off too (FX-12): with the pool's default, a
    request would wait 30 seconds before failing.

    `hide_parameters`: an error of the database never carries the values of its statement.
    They would be written to the log with the error, and they can be an email, a phone
    number, a message's text or a client's location (docs/09 FS-13, FS-18).
    """
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_timeout=DB_CONNECT_TIMEOUT_S,
        hide_parameters=True,
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
