"""Centralized logging configuration for the agentic pipeline.

Provides consistent log format across all pipeline agents and stages.
Used by CLI and programmatic entrypoints.
"""

import logging
import sys
from pathlib import Path

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Marks a handler as installed by us, so a later call can remove exactly its own
# handlers and leave a host application's (or pytest's) alone.
_OWNED = "_forged_owned_handler"


def _release_own_handlers(root_logger: logging.Logger) -> None:
    """Detach and close handlers a previous `setup_logging` call installed.

    Without this the root logger accumulates: the course orchestrator calls
    setup_logging once per module, so module 0's file handler stayed attached and
    kept receiving module 1's records — the log of a crashed module was polluted
    by the module after it, and every log file stayed open for the whole run.
    """
    for handler in [h for h in root_logger.handlers if getattr(h, _OWNED, False)]:
        root_logger.removeHandler(handler)
        handler.close()


def _configure(
    handler: logging.Handler, level: int, formatter: logging.Formatter
) -> logging.Handler:
    """Apply level + format and tag the handler as ours."""
    handler.setLevel(level)
    handler.setFormatter(formatter)
    setattr(handler, _OWNED, True)
    return handler


def setup_logging(debug: bool = False, log_file: Path | None = None) -> None:
    """Configure logging for the agentic pipeline.

    Safe to call repeatedly: each call replaces the handlers installed by the
    previous one, so per-module reconfiguration does not stack.

    Args:
        debug: If True, set root logger to DEBUG; otherwise INFO
        log_file: Optional file path to write logs to (in addition to stdout)
    """
    level = logging.DEBUG if debug else logging.INFO

    root_logger = logging.getLogger()
    _release_own_handlers(root_logger)
    root_logger.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    root_logger.addHandler(_configure(logging.StreamHandler(sys.stderr), level, formatter))

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        root_logger.addHandler(_configure(file_handler, level, formatter))


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance by name (standard pattern)."""
    return logging.getLogger(name)
