"""JSON logs on stdout, one object per line, for the API, the worker and the libraries they use."""

import logging
import sys
import traceback
from collections.abc import MutableMapping
from typing import Any

import psycopg
import structlog
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

_HANDLER_NAME = "dawalink-json"

# Errors whose own text repeats the values they were given: the database's ("Key
# (email)=(…) already exists", a statement's parameters) and a schema's ("input_value=…").
# A log is no place for an email, a phone number, a message or a client's location
# (docs/09 FS-13, FS-18), so these are logged by their kind only.
_CARRY_VALUES = (DBAPIError, psycopg.Error, ValidationError)


def _in_one_line(error: BaseException) -> str:
    if not isinstance(error, _CARRY_VALUES):
        return "".join(traceback.format_exception_only(error)).rstrip()
    said = [type(error).__name__]
    cause = getattr(error, "orig", error)
    if cause is not error:
        said.append(type(cause).__name__)
    state = getattr(cause, "sqlstate", None)
    if state:
        said.append(f"SQLSTATE {state}")
    return ": ".join(said) + " (its message is left out: it can hold what was sent)"


def _chain(error: BaseException) -> list[BaseException]:
    """The error and what caused it, the first cause first."""
    found: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in found:
        found.append(current)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return found[::-1]


def describe(error: BaseException) -> str:
    """Where an error happened and what kind it is: the stack of each error in the chain
    (files, lines, function names: never a value), then its one line."""
    parts: list[str] = []
    for link in _chain(error):
        parts.append("".join(traceback.format_tb(link.__traceback__)) + _in_one_line(link))
    return "\n\nthen:\n".join(parts)


def exception_without_values(
    _: Any, __: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Writes the error of `log.exception(...)` as `exception`, with `describe`."""
    given = event.pop("exc_info", None)
    error: BaseException | None
    if isinstance(given, BaseException):
        error = given
    elif isinstance(given, tuple):
        error = given[1]
    elif given:
        error = sys.exc_info()[1]
    else:
        error = None
    if error is not None:
        event["exception"] = describe(error)
    return event


def configure_logging(level: str) -> None:
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        # Library logs (uvicorn, SQLAlchemy, Alembic) get the same fields as ours.
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            exception_without_values,
            structlog.processors.JSONRenderer(),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    # Calling this twice replaces our handler and leaves anyone else's in place.
    root.handlers = [*(h for h in root.handlers if h.get_name() != _HANDLER_NAME), handler]
    root.setLevel(level)
    # uvicorn installs its own plain-text handlers; hand its messages to ours instead.
    # Its access log stays off: the request middleware already logs one line per request.
    for name in ("uvicorn", "uvicorn.error"):
        library_logger = logging.getLogger(name)
        library_logger.handlers = []
        library_logger.propagate = True
