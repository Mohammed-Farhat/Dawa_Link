"""JSON logs on stdout, one object per line, for the API, the worker and the libraries they use."""

import logging
import sys

import structlog

_HANDLER_NAME = "dawalink-json"


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
            structlog.processors.format_exc_info,
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
