"""Logging configuration for LinguaFix.

Logs are written to ``~/.local/state/linguafix/linguafix.log`` with a rotating
handler (5 MB x 3 backups) and, optionally, to stderr for foreground runs.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import state_dir

LOG_FILE_NAME = "linguafix.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: str = "INFO",
    *,
    log_dir: Path | None = None,
    console: bool = False,
) -> Path:
    """Configure the root logger and return the log file path.

    Args:
        level: Logging level name (for example ``"INFO"``).
        log_dir: Override the directory used for the log file.
        console: When true, also log to stderr (used for ``--foreground``).

    Returns:
        The path of the log file that was configured.
    """
    directory = log_dir or state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_file = directory / LOG_FILE_NAME

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove pre-existing handlers so repeated calls stay idempotent.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    return log_file
