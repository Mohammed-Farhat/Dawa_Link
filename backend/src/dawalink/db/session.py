"""The database engine and its timeouts."""

from typing import Literal

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

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
    return database_answer(engine) == "up"


# What PostgreSQL says when it answers and refuses the login itself: a wrong password, a
# login or a database that doesn't exist, a network it won't take. Waiting won't change
# any of them. A refusal at connection time carries no SQLSTATE in psycopg (libpq gives
# only the server's text), so the text is read; the server writes it in English unless
# lc_messages says otherwise (RDS's default is English). Anything else, "the database
# system is starting up" or "too many connections" included, is worth waiting for.
_LOGIN_REFUSALS = ("password authentication failed", "does not exist", "pg_hba.conf")


def database_answer(engine: Engine) -> Literal["up", "no_answer", "login_refused"]:
    """Whether the database works, doesn't answer (yet), or answered and refused the login."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as error:
        said = str(error.orig).lower()
        return "login_refused" if any(phrase in said for phrase in _LOGIN_REFUSALS) else "no_answer"
    except SQLAlchemyError:
        return "no_answer"
    return "up"
