"""Thin wrapper around ``systemctl --user`` for the GUI.

Every call shells out to ``systemctl --user`` with ``check=False`` and a short
timeout. A missing ``systemctl`` (containers, minimal installs) or a hung bus
never raises: the function returns ``False`` so the GUI can show a friendly
message instead of a traceback. ``shell=True`` is never used.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Final

logger = logging.getLogger(__name__)

SERVICE: Final[str] = "linguafix.service"
COMMAND_TIMEOUT: Final[float] = 5.0


def _run(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run ``systemctl --user <args>`` returning ``None`` on any failure."""
    try:
        return subprocess.run(
            ["systemctl", "--user", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
    except FileNotFoundError:
        logger.info("systemctl is not available")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("systemctl %s timed out", args[0] if args else "")
        return None
    except OSError:
        logger.debug("systemctl call failed", exc_info=True)
        return None


def _ok(args: list[str]) -> bool:
    """Return ``True`` when the command ran and exited successfully."""
    result = _run(args)
    return result is not None and result.returncode == 0


def is_service_active() -> bool:
    """Return ``True`` when the daemon unit is running."""
    result = _run(["is-active", SERVICE])
    return result is not None and result.stdout.strip() == "active"


def is_service_enabled() -> bool:
    """Return ``True`` when the daemon unit is enabled for login."""
    result = _run(["is-enabled", SERVICE])
    return result is not None and result.stdout.strip() == "enabled"


def start_service() -> bool:
    """Start the daemon unit."""
    return _ok(["start", SERVICE])


def stop_service() -> bool:
    """Stop the daemon unit."""
    return _ok(["stop", SERVICE])


def enable_autostart() -> bool:
    """Enable the daemon unit for login."""
    return _ok(["enable", SERVICE])


def disable_autostart() -> bool:
    """Disable the daemon unit for login."""
    return _ok(["disable", SERVICE])


def reload_service() -> bool:
    """Ask the daemon to reload its configuration (``SIGHUP``)."""
    return _ok(["reload-or-restart", SERVICE])
