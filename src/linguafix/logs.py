"""Read the daemon log for the ``linguafix logs`` command.

The daemon writes ``~/.local/state/linguafix/linguafix.log`` (see
:mod:`linguafix.logging_setup`), so that file is the canonical source even when
the daemon runs under systemd. This module is a thin reader over it; it never
touches the typed text, which is not in the log in the first place.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import state_dir
from .logging_setup import LOG_FILE_NAME

DEFAULT_LINES = 50


def log_file_path() -> Path:
    """Return the path of the daemon log file."""
    return state_dir() / LOG_FILE_NAME


def _matches_level(line: str, level: str | None) -> bool:
    """Return whether ``line`` carries the requested log level."""
    if not level:
        return True
    return f" {level.upper()} " in line or f"{level.upper()} " in line


def read_tail(path: Path, lines: int, level: str | None = None) -> list[str]:
    """Return the last ``lines`` matching log lines (optionally level-filtered)."""
    try:
        # The file is append-only and line-buffered; reading it whole is fine for
        # a rotating log capped at a few megabytes.
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    matched = [line for line in content if _matches_level(line, level)]
    return matched[-lines:]


def follow(path: Path, lines: int, level: str | None = None) -> int:
    """Stream the log with ``tail -f`` until interrupted. Returns an exit code."""
    try:
        process = subprocess.Popen(
            ["tail", "-f", "-n", str(lines), str(path)],
            stdout=subprocess.PIPE,
            text=True,
        )
    except OSError:
        return 1
    assert process.stdout is not None
    try:
        for line in process.stdout:
            if _matches_level(line, level):
                print(line, end="")
    except KeyboardInterrupt:
        pass
    finally:
        process.terminate()
        process.wait()
    return 0
