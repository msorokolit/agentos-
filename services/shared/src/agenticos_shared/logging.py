"""Structured logging configuration using structlog.

Call :func:`configure_logging` once at process startup. After that, use
``structlog.get_logger(__name__)`` everywhere.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    """Configure stdlib + structlog with sane defaults.

    Args:
        level: Minimum log level (e.g., ``INFO``, ``DEBUG``).
        json: If True, emit JSON; otherwise emit human-friendly console output.
    """

    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    if json:
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Convenience wrapper around ``structlog.get_logger``."""

    return structlog.get_logger(name) if name else structlog.get_logger()
