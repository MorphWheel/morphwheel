"""Logging for the GUI process: one rotating file per user, plus helpers for latency budgets.

Only the GUI process writes the log file. Worker processes must not attach file handlers, because
two processes rotating the same file collide on Windows. They forward their records to the GUI
instead (sprint S3).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "morphwheel"
LOG_FILE_NAME = "morphwheel.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 4  # 5 files x 1 MB in total (phase-4 §5)

_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(processName)s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_HANDLER_MARK = "_morphwheel_handler"


def setup_logging(log_dir: Path, *, level: int = logging.INFO, console: bool = False) -> Path:
    """Attach Morphwheel's handlers to the ``morphwheel`` logger and return the log file path.

    Calling it again replaces the handlers it added before, so tests and restarts stay idempotent.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILE_NAME

    logger = logging.getLogger(LOGGER_NAME)
    for handler in [h for h in logger.handlers if getattr(h, _HANDLER_MARK, False)]:
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_FORMAT, _DATE_FORMAT)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8", delay=True
        )
    ]
    if console:
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(formatter)
        setattr(handler, _HANDLER_MARK, True)
        logger.addHandler(handler)

    logger.setLevel(level)
    logger.propagate = False
    return log_file


def elapsed_ms(start_ns: int) -> float:
    """Milliseconds since ``start_ns``, a ``time.perf_counter_ns()`` reading."""
    return (time.perf_counter_ns() - start_ns) / 1_000_000


@contextmanager
def timed(logger: logging.Logger, label: str, budget_ms: float | None = None) -> Iterator[None]:
    """Log how long the block took, as a warning if it exceeded ``budget_ms``.

    Used for the latency budgets in phase-2 §4: a drop handler under 5 ms, the wheel shown within
    50 ms, and so on.
    """
    start = time.perf_counter_ns()
    try:
        yield
    finally:
        ms = elapsed_ms(start)
        if budget_ms is not None and ms > budget_ms:
            logger.warning("%s took %.2f ms (budget %.0f ms)", label, ms, budget_ms)
        else:
            logger.debug("%s took %.2f ms", label, ms)
