"""structlog JSON logging (plan §10.2, P1-01).

Standard fields: ``job``, ``cinemaId``, ``phase``, ``url_path``, ``status``, ``durationMs``.
Only URL **paths** are logged, never query strings or full URLs.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast
from urllib.parse import urlsplit

import structlog
from structlog.typing import FilteringBoundLogger


def configure_logging(level: str = "INFO") -> None:
    """JSON lines on stdout, one event per line, with an ISO UTC timestamp."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(**bound: Any) -> FilteringBoundLogger:
    return cast(FilteringBoundLogger, structlog.get_logger().bind(**bound))


def url_path(url: str) -> str:
    """The path of ``url`` only (no scheme, host or query) for logs."""
    return urlsplit(url).path or "/"
