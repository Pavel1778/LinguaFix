"""Best-effort detection of the focused application.

Used for per-application exceptions (skip correction in terminals and IDEs) and
by the GUI's "detect current app" button. Every probe is optional: when nothing
can determine the focused window the function returns ``None`` and callers fall
back to normal behaviour. Nothing here ever reads window contents or typed text.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from typing import Final

logger = logging.getLogger(__name__)

PROBE_TIMEOUT: Final[float] = 2.0


def _strip_desktop_suffix(app_id: str) -> str:
    """Return the process-like name from a desktop app id."""
    name = app_id.strip()
    if name.endswith(".desktop"):
        name = name[: -len(".desktop")]
    return name.rsplit(".", 1)[-1] if "." in name else name


def _gnome_introspect() -> str | None:
    """Ask GNOME Shell's Introspect D-Bus interface for the focused window."""
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        result = bus.call_sync(
            "org.gnome.Shell",
            "/org/gnome/Shell/Introspect",
            "org.gnome.Shell.Introspect",
            "GetWindows",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            500,
            None,
        )
        payload = result.unpack()[0]
        for window in payload.values():
            if window.get("is-focused") or window.get("has-focus"):
                app_id = window.get("app-id") or ""
                if app_id:
                    return _strip_desktop_suffix(app_id)
    except Exception:
        logger.debug("GNOME Introspect probe failed", exc_info=True)
    return None


def _atspi() -> str | None:
    """Ask AT-SPI for the focused application's toolkit name."""
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        desktop = Atspi.get_desktop(0)
        for i in range(desktop.get_child_count()):
            app = desktop.get_child_at_index(i)
            if app is None:
                continue
            try:
                if app.get_state_set().contains(Atspi.StateType.ACTIVE):
                    return _strip_desktop_suffix(str(app.get_name() or ""))
            except Exception:
                continue
    except Exception:
        logger.debug("AT-SPI probe failed", exc_info=True)
    return None


def _xprop() -> str | None:
    """Fall back to ``xprop`` for the active X11 window's class."""
    try:
        result = subprocess.run(
            ["xprop", "-root", "_NET_ACTIVE_WINDOW"],
            check=False,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or "window id" not in result.stdout:
        return None
    window_id = result.stdout.strip().rsplit(" ", 1)[-1]
    try:
        wm_class = subprocess.run(
            ["xprop", "-id", window_id, "WM_CLASS"],
            check=False,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if wm_class.returncode != 0:
        return None
    # WM_CLASS(STRING) = "instance", "Class"
    parts = [part.strip().strip('"') for part in wm_class.stdout.split("=", 1)[-1].split(",")]
    for part in parts:
        if part:
            return _strip_desktop_suffix(part).lower()
    return None


_PROBES: Final[tuple[Callable[[], str | None], ...]] = (_gnome_introspect, _atspi, _xprop)


def get_active_app() -> str | None:
    """Return the focused application's short name, or ``None``.

    The value is a process-ish name such as ``"gnome-terminal"`` or ``"code"``
    and never any typed text.
    """
    for probe in _PROBES:
        try:
            name = probe()
        except Exception:
            logger.debug("Focus probe %s raised", probe.__name__, exc_info=True)
            continue
        if name:
            return name
    return None
