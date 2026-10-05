"""Control a LinguaFix daemon however it was launched.

A daemon can be started two ways: as a ``systemd --user`` service, or as a plain
detached process from ``linguafix start``. The GUI must see and control both;
otherwise a daemon started from a terminal is invisible to the big toggle and
cannot be stopped from the app. This module presents one interface over the two:
it prefers the systemd unit when it is enabled, and falls back to the PID lock
file that *every* daemon writes (the systemd unit writes it too, because it runs
the same ``linguafix start --foreground`` command).

The lock file is the single source of truth for "is a daemon alive": it is
created under ``XDG_CACHE_HOME`` and released on exit, and it works without
systemd at all (containers, minimal installs, manual runs).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final

from .config import cache_dir
from .daemon import HISTORY_FILE_NAME

logger = logging.getLogger(__name__)

LOCK_FILE_NAME: Final[str] = "daemon.lock"
SERVICE: Final[str] = "linguafix.service"
START_TIMEOUT: Final[float] = 5.0
STOP_GRACE: Final[float] = 3.0
POLL_INTERVAL: Final[float] = 0.1
SYSTEMCTL_TIMEOUT: Final[float] = 5.0


def lock_path() -> Path:
    """Return the path of the daemon PID lock file."""
    return cache_dir() / LOCK_FILE_NAME


def pid_alive(pid: int) -> bool:
    """Return ``True`` when a process with ``pid`` exists and has not exited.

    A *zombie* process (exited but not yet reaped by its parent) still answers
    ``os.kill(pid, 0)``, so the signal probe alone reports a dead daemon as
    alive. That is the "toggle works every other time" failure: the GUI spawns
    the daemon as a child, the daemon exits, the GUI has not reaped it yet, and
    the ON/OFF button keeps reading the stale state. We therefore also consult
    ``/proc`` and treat a zombie as gone.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # A live process owned by another user: we cannot inspect it, assume alive.
        return True
    return not _is_zombie(pid)


def _is_zombie(pid: int) -> bool:
    """Return ``True`` when ``pid`` is a zombie (exited, not yet reaped)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    # Format: ``pid (comm) state ...``; ``comm`` may contain spaces and
    # parentheses, so split after the last ')'.
    close = stat.rfind(")")
    if close == -1:
        return False
    fields = stat[close + 1 :].split()
    return bool(fields) and fields[0] == "Z"


def read_pid() -> int | None:
    """Return the PID in the lock file when that process is still alive.

    A lock file left behind by a crashed daemon is removed (best effort) so a
    later ``start`` does not trip over it. The unlink only happens when the file
    still names the dead pid, so a fresh daemon that has just rewritten the lock
    is never affected.
    """
    try:
        raw = lock_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    pid = int(raw)
    if pid_alive(pid):
        return pid
    try:
        if lock_path().read_text(encoding="utf-8").strip() == raw:
            lock_path().unlink()
    except OSError:
        logger.debug("Could not remove stale lock file", exc_info=True)
    return None


def systemctl_available() -> bool:
    """Return ``True`` when ``systemctl`` is on PATH."""
    return shutil.which("systemctl") is not None


def _systemctl(
    args: list[str], timeout: float = SYSTEMCTL_TIMEOUT
) -> subprocess.CompletedProcess[str] | None:
    """Run ``systemctl --user <args>`` returning ``None`` on any failure."""
    if not systemctl_available():
        return None
    try:
        return subprocess.run(
            ["systemctl", "--user", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("systemctl %s failed: %s", args, exc)
        return None


def systemd_active() -> bool:
    """Return ``True`` when the systemd user unit is active."""
    result = _systemctl(["is-active", SERVICE])
    return result is not None and result.stdout.strip() == "active"


def systemd_enabled() -> bool:
    """Return ``True`` when the systemd user unit is enabled for login."""
    result = _systemctl(["is-enabled", SERVICE])
    return result is not None and result.stdout.strip() == "enabled"


def is_running() -> bool:
    """Return ``True`` when a daemon is running, however it was started."""
    return read_pid() is not None or systemd_active()


def _wait_until(predicate: Callable[[], bool], timeout: float) -> bool:
    """Poll ``predicate`` every :data:`POLL_INTERVAL` until it holds or times out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(POLL_INTERVAL)
    return predicate()


def spawn_detached(dry_run: bool = False) -> None:
    """Start a detached daemon process, logging any failure.

    Prefers the installed ``linguafix`` launcher over ``sys.executable -m``
    because the launcher sets ``PYTHONPATH`` for the packaged layout; spawning
    ``python3 -m linguafix`` directly would fail to import the package in a
    ``.deb`` install when the GUI was not itself started through the launcher.
    """
    launcher = shutil.which("linguafix")
    command = (
        [launcher, "start", "--foreground"]
        if launcher
        else [sys.executable, "-m", "linguafix", "start", "--foreground"]
    )
    if dry_run:
        command.append("--dry-run")
    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        logger.error("Could not spawn the daemon", exc_info=True)


def start(dry_run: bool = False) -> bool:
    """Start the daemon and return whether it came up.

    Prefers the systemd unit when it is enabled so the service keeps its
    restart-on-failure semantics; otherwise spawns a detached process. Either
    way the daemon writes the PID lock file, which is what the GUI polls.
    """
    if is_running():
        return True
    if systemd_enabled():
        _systemctl(["start", SERVICE])
        if _wait_until(lambda: read_pid() is not None or systemd_active(), START_TIMEOUT):
            return True
    spawn_detached(dry_run=dry_run)
    if not _wait_until(lambda: read_pid() is not None, START_TIMEOUT):
        return False
    # The lock appears before the daemon checks for devices, so confirm it is
    # still alive a moment later; otherwise a daemon that died instantly (no
    # keyboard devices) would be reported as a successful start.
    time.sleep(0.3)
    return read_pid() is not None


def _kill_pid(pid: int, sig: int) -> bool:
    """Send ``sig`` to ``pid``; return ``True`` when it was delivered or gone."""
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return True
    except OSError:
        logger.debug("kill(%d, %s) failed", pid, sig, exc_info=True)
        return False
    return True


def stop() -> bool:
    """Stop the daemon, however it was started."""
    # Stop the unit first when it is the manager: systemd would otherwise
    # restart a process killed out from under it (``Restart=always``).
    if systemd_active():
        _systemctl(["stop", SERVICE])
    pid = read_pid()
    if pid is not None:
        _kill_pid(pid, signal.SIGTERM)
        if not _wait_until(lambda: not pid_alive(pid), STOP_GRACE):
            logger.warning("Daemon %d ignored SIGTERM; escalating to SIGKILL", pid)
            _kill_pid(pid, signal.SIGKILL)
            _wait_until(lambda: not pid_alive(pid), STOP_GRACE)
    return not is_running()


def restart() -> bool:
    """Restart the daemon (used after a configuration change)."""
    if not is_running():
        return start()
    was_service = systemd_enabled()
    stop()
    if was_service:
        _systemctl(["start", SERVICE])
        return _wait_until(lambda: read_pid() is not None or systemd_active(), START_TIMEOUT)
    spawn_detached()
    return _wait_until(lambda: read_pid() is not None, START_TIMEOUT)


def reload_config() -> bool:
    """Ask the daemon to reload its configuration.

    Prefers ``SIGHUP`` to the running process (works for a manual or service
    daemon alike); falls back to ``systemctl reload-or-restart``.
    """
    pid = read_pid()
    if pid is not None:
        return _kill_pid(pid, signal.SIGHUP)
    result = _systemctl(["reload-or-restart", SERVICE])
    return result is not None and result.returncode == 0


def undo_last_fix() -> bool:
    """Ask the running daemon to undo its most recent correction.

    Returns ``False`` when no daemon is running. This is the reliable undo path
    the GUI button uses: it does not depend on the application's own undo
    history, which groups a correction differently from one app to the next.
    """
    pid = read_pid()
    if pid is None:
        return False
    return _kill_pid(pid, signal.SIGUSR1)


def request_history() -> bool:
    """Ask the running daemon to refresh its metadata-only history snapshot.

    The daemon answers asynchronously by writing ``history.json`` into the cache
    directory (see :func:`read_history`). Returns ``False`` when no daemon is
    running.
    """
    pid = read_pid()
    if pid is None:
        return False
    if not hasattr(signal, "SIGUSR2"):  # pragma: no cover - POSIX always has it
        return False
    return _kill_pid(pid, signal.SIGUSR2)


def read_history() -> list[dict[str, object]]:
    """Return the daemon's recent corrections as metadata-only dicts.

    Reads the snapshot the daemon wrote on :func:`request_history`. The file
    contains word *lengths*, layouts and timestamps only; the typed text is
    never present. A missing or malformed file yields an empty list.
    """
    path = cache_dir() / HISTORY_FILE_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    history = payload.get("history") if isinstance(payload, dict) else None
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def enable_autostart() -> bool:
    """Enable the systemd unit for login."""
    result = _systemctl(["enable", SERVICE])
    return result is not None and result.returncode == 0


def disable_autostart() -> bool:
    """Disable the systemd unit for login."""
    result = _systemctl(["disable", SERVICE])
    return result is not None and result.returncode == 0


def autostart_enabled() -> bool:
    """Return ``True`` when the daemon will start at login.

    Either the systemd unit is enabled or the XDG autostart entry exists, so the
    GUI reflects both install paths.
    """
    if systemd_enabled():
        return True
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return (base / "autostart" / "linguafix.desktop").exists()
