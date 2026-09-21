"""Structured logging setup, shared by the whole service.

Every log record includes a `manufacturer` and `job_id` field (when available)
so sync activity can be filtered per-run. We use the stdlib `logging` module
with a plain formatter that renders those extra fields inline instead of a
third-party structured logging library, since the service has no log
aggregation backend configured yet.
"""
from __future__ import annotations

import logging
import sys

from core.config import settings

_CONFIGURED = False


class ContextFilter(logging.Filter):
    """Ensures `manufacturer` and `job_id` always exist on the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "manufacturer"):
            record.manufacturer = "-"
        if not hasattr(record, "job_id"):
            record.job_id = "-"
        return True


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s [%(manufacturer)s job=%(job_id)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    root.handlers = [handler]

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
