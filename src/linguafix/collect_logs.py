"""Collect diagnostic information into a single tarball for issue reports.

The bundle is meant to be attached to a bug report. It contains only metadata:
the ``doctor`` output, the configuration file, the tail of the daemon log, the
user journal, environment details, device permissions and the versions of the
relevant packages. The daemon never writes typed text to its log, so no typed
content or credentials are included.
"""

from __future__ import annotations

import collections
import logging
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from . import __version__
from .config import Config, config_path, load_config, state_dir
from .doctor import collect_checks, render

logger = logging.getLogger(__name__)

BUNDLE_PREFIX = "linguafix-logs"
LOG_FILE_NAME = "linguafix.log"
LOG_TAIL_LINES = 200
JOURNAL_LINES = 200
COMMAND_TIMEOUT = 10.0
MAX_SECTION_BYTES = 2 * 1024 * 1024

DOCTOR_TXT = "doctor.txt"
CONFIG_TOML = "config.toml"
DAEMON_LOG = "daemon.log"
JOURNAL_TXT = "journal.txt"
ENV_TXT = "env.txt"
DEVICES_TXT = "devices.txt"
PACKAGES_TXT = "packages.txt"
README_TXT = "README.txt"

README_TEXT = """LinguaFix diagnostic bundle
===========================

This archive is attached to a bug report. It contains no typed text and no
credentials:

  doctor.txt    output of `linguafix doctor`
  config.toml   a copy of your LinguaFix configuration
  daemon.log    the last lines of the LinguaFix log
  journal.txt   the last lines of the user journal for the service
  env.txt       session type, desktop, GNOME version, groups, kernel
  devices.txt   permissions on /dev/input/event* and /dev/uinput
  packages.txt  versions of the related packages

Please attach this file to the relevant GitHub issue.
"""


def _run(argv: list[str], *, timeout: float = COMMAND_TIMEOUT) -> str:
    """Run ``argv`` and return its combined output, never raising."""
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            timeout=timeout,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"<failed to run {argv[0]}: {exc}>\n"
    output = (result.stdout or "") + (result.stderr or "")
    return output[:MAX_SECTION_BYTES]


def _tail(path: Path, lines: int) -> str:
    """Return the last ``lines`` lines of ``path`` or a notice if absent."""
    if not path.exists():
        return f"<{path} does not exist>\n"
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            tail = collections.deque(handle, maxlen=lines)
    except OSError as exc:
        return f"<could not read {path}: {exc}>\n"
    return "".join(tail)


def doctor_text(config: Config | None = None) -> str:
    """Return the ``doctor`` report as text."""
    results = collect_checks(config)
    return "LinguaFix doctor\n" + "=" * 40 + "\n" + render(results) + "\n"


def config_text() -> str:
    """Return a copy of the configuration file or a notice."""
    path = config_path()
    if not path.exists():
        return f"<{path} does not exist>\n"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"<could not read {path}: {exc}>\n"


def journal_text() -> str:
    """Return the tail of the user journal for the service."""
    return _run(
        [
            "journalctl",
            "--user",
            "-u",
            "linguafix.service",
            "-n",
            str(JOURNAL_LINES),
            "--no-pager",
        ]
    )


def env_text() -> str:
    """Return environment and platform details."""
    lines = [
        f"linguafix: {__version__}",
        f"python: {sys.version.split()[0]} ({sys.executable})",
        f"platform: {platform.platform()}",
        f"kernel: {platform.release()}",
        f"XDG_SESSION_TYPE: {os.environ.get('XDG_SESSION_TYPE', '<unset>')}",
        f"XDG_CURRENT_DESKTOP: {os.environ.get('XDG_CURRENT_DESKTOP', '<unset>')}",
        f"XDG_SESSION_DESKTOP: {os.environ.get('XDG_SESSION_DESKTOP', '<unset>')}",
        f"WAYLAND_DISPLAY: {os.environ.get('WAYLAND_DISPLAY', '<unset>')}",
        f"DISPLAY: {os.environ.get('DISPLAY', '<unset>')}",
        f"groups: {_run(['id', '-nG']).strip()}",
        "--- gnome-shell ---",
        _run(["gnome-shell", "--version"]).strip(),
        "--- lsb_release ---",
        _run(["lsb_release", "-a"]).strip(),
    ]
    return "\n".join(lines) + "\n"


def devices_text() -> str:
    """Return permissions on the relevant device nodes."""
    sections: list[str] = []
    for pattern in ("/dev/input/event*", "/dev/uinput"):
        sections.append(f"--- {pattern} ---")
        listing = _run(["bash", "-c", f"ls -l {pattern} 2>&1"])
        sections.append(listing.rstrip() or "<none>")
    sections.append("--- /dev/input ---")
    sections.append(_run(["bash", "-c", "ls -l /dev/input 2>&1"]).rstrip() or "<none>")
    return "\n".join(sections) + "\n"


def packages_text() -> str:
    """Return versions of the related packages."""
    output = _run(
        [
            "bash",
            "-c",
            "dpkg -l 2>/dev/null | grep -E 'evdev|uinput|wtype|xdotool|g3kb|appindicator|tomli'",
        ]
    )
    return output.rstrip() + "\n" if output.strip() else "<no matching packages>\n"


def _write_section(directory: Path, name: str, content: str) -> None:
    """Write one bundle member, truncating oversized content."""
    (directory / name).write_text(content[:MAX_SECTION_BYTES], encoding="utf-8")


def collect_logs(
    output_dir: Path | None = None,
    *,
    config: Config | None = None,
) -> Path:
    """Build a diagnostic tarball and return its path.

    Args:
        output_dir: Directory for the archive (defaults to the home directory).
        config: Optional configuration override for the ``doctor`` report.

    Returns:
        The path of the created ``.tar.gz`` archive.

    Raises:
        OSError: If the archive cannot be written.
    """
    cfg = config or load_config()
    destination = output_dir or Path.home()
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    archive_path = destination / f"{BUNDLE_PREFIX}-{timestamp}.tar.gz"

    sections = {
        README_TXT: README_TEXT,
        DOCTOR_TXT: doctor_text(cfg),
        CONFIG_TOML: config_text(),
        DAEMON_LOG: _tail(state_dir() / LOG_FILE_NAME, LOG_TAIL_LINES),
        JOURNAL_TXT: journal_text(),
        ENV_TXT: env_text(),
        DEVICES_TXT: devices_text(),
        PACKAGES_TXT: packages_text(),
    }

    with tempfile.TemporaryDirectory(prefix="linguafix-collect-") as tmp:
        staging = Path(tmp)
        for name, content in sections.items():
            _write_section(staging, name, content)
        with tarfile.open(archive_path, "w:gz") as tar:
            for name in sections:
                tar.add(staging / name, arcname=name)

    logger.info("Wrote diagnostic bundle with %d sections to %s", len(sections), archive_path)
    return archive_path
