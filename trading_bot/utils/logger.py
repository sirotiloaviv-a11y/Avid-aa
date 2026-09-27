"""Logging to ``logs/bot.log`` (rotated) and the console, timestamps in UTC."""

from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s.%(msecs)03dZ | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
ROOT_LOGGER = "trading_bot"


class _UtcFormatter(logging.Formatter):
    converter = time.gmtime


def setup_logging(
    log_dir: Path,
    level: str = "INFO",
    *,
    filename: str = "bot.log",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 10,
    console: bool = True,
) -> logging.Logger:
    """Configure the ``trading_bot`` logger. Safe to call more than once."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(ROOT_LOGGER)
    logger.setLevel(level.upper())
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = _UtcFormatter(LOG_FORMAT, DATE_FORMAT)
    file_handler = RotatingFileHandler(
        log_dir / filename, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    # Anything that escapes the main loop still lands in bot.log.
    def _log_uncaught(exc_type: type[BaseException], exc: BaseException, tb: object) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)  # type: ignore[arg-type]
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc, tb))  # type: ignore[arg-type]

    sys.excepthook = _log_uncaught
    return logger


def get_logger(name: str) -> logging.Logger:
    """Child of the ``trading_bot`` logger, e.g. ``get_logger(__name__)``."""
    if name == ROOT_LOGGER or name.startswith(ROOT_LOGGER + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")
