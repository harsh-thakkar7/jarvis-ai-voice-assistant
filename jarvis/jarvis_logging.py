"""Centralized logging for the JARVIS AI assistant.

This module replaces scattered ``print()`` diagnostics with proper,
configurable logging. It provides:

- One-time configuration via :func:`setup_logging`
- Per-module loggers via :func:`get_logger`
- Dual output: colored-free console (HH:MM:SS timestamps) and a rotating
  ``jarvis.log`` file (5 MB x 3 backups)
- Suppression of noisy third-party library loggers
- Specialized helpers for skill execution, API calls, errors, and
  performance tracking

Usage::

    from jarvis_logging import setup_logging, get_logger

    setup_logging()
    logger = get_logger(__name__)
    logger.info("JARVIS online")

Only the Python standard library is used (``logging`` and
``logging.handlers``); all handlers are thread-safe.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import time
from pathlib import Path
from typing import Any, Final, Optional

__all__ = [
    "setup_logging",
    "get_logger",
    "log_skill",
    "log_api",
    "log_error",
    "log_performance",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Directory where ``jarvis.log`` lives. Defaults to the directory that
#: contains this module so logs stay with the project regardless of CWD.
LOG_DIR: Final[Path] = Path(__file__).resolve().parent

#: Name of the main rotating log file.
LOG_FILE: Final[str] = "jarvis.log"

#: Maximum size of the log file before rotation (5 MB).
MAX_BYTES: Final[int] = 5 * 1024 * 1024

#: Number of rotated backup files to keep.
BACKUP_COUNT: Final[int] = 3

#: Format used for console output (short timestamp, name, message).
CONSOLE_FORMAT: Final[str] = "[%(asctime)s] %(name)s: %(message)s"

#: Verbose format used for the log file.
FILE_FORMAT: Final[str] = "%(asctime)s %(levelname)s %(name)s %(message)s"

#: Date format for console output (HH:MM:SS).
CONSOLE_DATE_FORMAT: Final[str] = "%H:%M:%S"

#: Full date format for file output.
FILE_DATE_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"

#: Third-party loggers that are far too chatty at INFO level.
NOISY_LOGGERS: Final[tuple[str, ...]] = (
    "urllib3",
    "urllib3.connectionpool",
    "requests",
    "requests.packages.urllib3",
    "selenium",
    "websockets",
    "asyncio",
    "PIL",
    "matplotlib",
    "werkzeug",
)

#: Level applied to noisy library loggers.
NOISY_LEVEL: Final[int] = logging.WARNING

#: Name of the dedicated skill-execution logger.
SKILL_LOGGER_NAME: Final[str] = "jarvis.skills"

#: Name of the dedicated API-call logger.
API_LOGGER_NAME: Final[str] = "jarvis.api"

#: Name of the dedicated error-tracking logger.
ERROR_LOGGER_NAME: Final[str] = "jarvis.errors"

#: Name of the dedicated performance logger.
PERFORMANCE_LOGGER_NAME: Final[str] = "jarvis.performance"

# Module-level guard so repeated ``setup_logging()`` calls do not stack
# duplicate handlers on the root logger.
_configured: bool = False


# ---------------------------------------------------------------------------
# Core setup
# ---------------------------------------------------------------------------

def setup_logging(level: int = logging.INFO) -> None:
    """Configure JARVIS logging exactly once.

    Attaches a stream handler (console) and a rotating file handler
    (``jarvis.log``) to the root logger, and silences noisy third-party
    libraries. Safe to call multiple times; only the first call has an
    effect unless handlers have been cleared externally.

    Args:
        level: Logging level for the root logger and all attached
            handlers (e.g. ``logging.DEBUG``, ``logging.INFO``).
            Defaults to ``logging.INFO``.
    """
    global _configured

    root = logging.getLogger()

    # Idempotency: never attach duplicate handlers.
    if _configured:
        root.setLevel(level)
        return

    root.setLevel(level)

    # --- Console handler -------------------------------------------------
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(
        logging.Formatter(fmt=CONSOLE_FORMAT, datefmt=CONSOLE_DATE_FORMAT)
    )
    root.addHandler(console_handler)

    # --- Rotating file handler -------------------------------------------
    file_handler = logging.handlers.RotatingFileHandler(
        filename=str(LOG_DIR / LOG_FILE),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # file captures everything >= DEBUG
    file_handler.setFormatter(
        logging.Formatter(fmt=FILE_FORMAT, datefmt=FILE_DATE_FORMAT)
    )
    root.addHandler(file_handler)

    # --- Quiet noisy third-party loggers ---------------------------------
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(NOISY_LEVEL)

    # Mark configured and avoid double-logging through propagating children.
    _configured = True
    logging.captureWarnings(True)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger configured for JARVIS.

    Ensures logging is set up before returning the logger, so callers can
    simply do ``logger = get_logger(__name__)`` without worrying about
    initialization order.

    Args:
        name: Logger name, conventionally ``__name__`` of the calling
            module.

    Returns:
        A ``logging.Logger`` instance writing through the root handlers.
    """
    if not _configured:
        setup_logging()
    return logging.getLogger(name)


# ---------------------------------------------------------------------------
# Special-purpose loggers
# ---------------------------------------------------------------------------

def log_skill(skill_name: str, cmd: str, result: str) -> None:
    """Log a skill execution event for later auditing/debugging.

    Args:
        skill_name: Human-readable name of the skill that ran
            (e.g. ``"weather"``).
        cmd: The raw command or trigger text issued to the skill.
        result: Short description of the outcome (success message,
            error summary, etc.).
    """
    get_logger(SKILL_LOGGER_NAME).info(
        "skill=%r cmd=%r result=%r", skill_name, cmd, result
    )


def log_api(method: str, url: str, status: Optional[int], duration: float) -> None:
    """Log an outbound API call.

    Args:
        method: HTTP method (e.g. ``"GET"``, ``"POST"``).
        url: The request URL.
        status: HTTP status code returned, or ``None`` if the request
            failed before receiving a response.
        duration: Round-trip duration in seconds.
    """
    logger = get_logger(API_LOGGER_NAME)
    msg = "%s %s -> status=%s in %.3fs"
    args: tuple[Any, ...] = (method, url, status, duration)
    if status is None or status >= 400:
        logger.warning(msg, *args)
    else:
        logger.info(msg, *args)


def log_error(error: BaseException | str, context: str = "") -> None:
    """Log an error together with surrounding context.

    Args:
        error: The exception object (traceback included automatically)
            or a plain error string.
        context: Free-form description of what JARVIS was doing when the
            error occurred (e.g. ``"while loading skills"``).
    """
    logger = get_logger(ERROR_LOGGER_NAME)
    prefix = f"[{context}] " if context else ""
    if isinstance(error, BaseException):
        logger.exception("%s%s", prefix, error)
    else:
        logger.error("%s%s", prefix, error)


def log_performance(operation: str, duration: float) -> None:
    """Log how long an operation took.

    Args:
        operation: Identifier of the measured operation
            (e.g. ``"skill_dispatch"``).
        duration: Elapsed time in seconds. Values of 1 s or more are
            logged at WARNING to make slow paths stand out.
    """
    logger = get_logger(PERFORMANCE_LOGGER_NAME)
    if duration >= 1.0:
        logger.warning("%s took %.3fs", operation, duration)
    else:
        logger.info("%s took %.3fs", operation, duration)


# Convenience timing helper kept stdlib-only (no external deps).
class Timer:
    """Context manager measuring wall-clock duration of a code block.

    Example::

        with Timer("brain.think") as t:
            response = brain.process(text)
        # Automatically emits: log_performance("brain.think", elapsed)
    """

    def __init__(self, operation: str) -> None:
        self.operation: str = operation
        self.duration: float = 0.0

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.duration = time.perf_counter() - self._start
        log_performance(self.operation, self.duration)


if __name__ == "__main__":
    # Smoke test: python jarvis_logging.py
    setup_logging(logging.DEBUG)
    demo = get_logger(__name__)
    demo.debug("debug message")
    demo.info("JARVIS logging module operational")
    log_skill("greet", "hello jarvis", "responded with greeting")
    log_api("GET", "https://api.example.com/data", 200, 0.123)
    try:
        raise ValueError("demo failure")
    except ValueError as exc:
        log_error(exc, context="smoke test")
    log_performance("smoke_test", 0.042)
