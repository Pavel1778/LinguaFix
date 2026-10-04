"""Keyboard layout switching.

Two backends are supported:

* ``g3kb-switch`` talks to GNOME Shell over D-Bus and works on both Wayland and
  X11 sessions. It is the preferred backend.
* ``setxkbmap`` is the X11 fallback and is unavailable under a pure Wayland
  session.

The active layout is cached for a short period to avoid spawning a process for
every key press.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from typing import Final

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT: Final[float] = 2.0
CACHE_TTL: Final[float] = 1.0
BACKEND_G3KB: Final[str] = "g3kb-switch"
BACKEND_SETXKBMAP: Final[str] = "setxkbmap"
BACKEND_NONE: Final[str] = "none"


def _run(command: list[str], timeout: float = COMMAND_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run ``command`` safely and return the completed process.

    Args:
        command: Argument vector, executed without a shell.
        timeout: Maximum runtime in seconds.

    Returns:
        The completed process; ``returncode`` is ``-1`` when the command could
        not be executed or timed out.
    """
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("Command %s failed: %s", command, exc)
        return subprocess.CompletedProcess(command, -1, "", str(exc))


def _which(program: str) -> str | None:
    """Return the resolved path of ``program`` if available."""
    return shutil.which(program)


class LayoutSwitcher:
    """Read and change the active keyboard layout.

    Args:
        layouts: Ordered list of layout identifiers as configured by the user.
            The order must match the order in which the layouts are registered
            in the desktop environment, because ``g3kb-switch`` addresses them
            by index.
        switch_method: One of ``"auto"``, ``"g3kb-switch"`` or ``"setxkbmap"``.
        session_type: Override for ``XDG_SESSION_TYPE`` (used in tests).
    """

    def __init__(
        self,
        layouts: list[str] | None = None,
        switch_method: str = "auto",
        session_type: str | None = None,
    ) -> None:
        self.layouts = [layout.lower() for layout in (layouts or ["us", "ru"])]
        self.session_type = (session_type or os.environ.get("XDG_SESSION_TYPE", "")).lower()
        self._requested_method = switch_method
        self._backend = self._resolve_backend(switch_method)
        self._cache_value: str | None = None
        self._cache_time: float = 0.0

    def _resolve_backend(self, switch_method: str) -> str:
        """Choose a concrete backend honouring availability and the request."""
        if switch_method == BACKEND_G3KB:
            return BACKEND_G3KB if _which(BACKEND_G3KB) else BACKEND_NONE
        if switch_method == BACKEND_SETXKBMAP:
            return BACKEND_SETXKBMAP if _which(BACKEND_SETXKBMAP) else BACKEND_NONE
        # auto
        if _which(BACKEND_G3KB):
            return BACKEND_G3KB
        if self.session_type != "wayland" and _which(BACKEND_SETXKBMAP):
            return BACKEND_SETXKBMAP
        return BACKEND_NONE

    @property
    def backend(self) -> str:
        """Return the name of the active backend."""
        return self._backend

    def _index_to_layout(self, value: str) -> str | None:
        """Translate a backend value (index or name) into a layout id."""
        value = value.strip()
        if not value:
            return None
        if value.isdigit():
            index = int(value)
            if 0 <= index < len(self.layouts):
                return self.layouts[index]
            return None
        lowered = value.lower()
        for layout in self.layouts:
            if lowered == layout or lowered.startswith(layout):
                return layout
        return None

    def _query_g3kb(self) -> str | None:
        """Query the current layout through ``g3kb-switch``."""
        result = _run([BACKEND_G3KB, "-p"])
        if result.returncode != 0:
            return None
        return self._index_to_layout(result.stdout.strip())

    def _query_setxkbmap(self) -> str | None:
        """Query the current layout through ``setxkbmap -query``."""
        result = _run([BACKEND_SETXKBMAP, "-query"])
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            if line.lower().startswith("layout:"):
                value = line.split(":", 1)[1].strip()
                first = value.split(",")[0].strip()
                return self._index_to_layout(first)
        return None

    def get_current_layout(self, *, force: bool = False) -> str:
        """Return the currently active layout.

        Args:
            force: When true, bypass the cache and query the backend again.

        Returns:
            A layout identifier, or the first configured layout when the layout
            cannot be determined.
        """
        now = time.monotonic()
        if not force and self._cache_value is not None and now - self._cache_time < CACHE_TTL:
            return self._cache_value

        value: str | None = None
        if self._backend == BACKEND_G3KB:
            value = self._query_g3kb()
        elif self._backend == BACKEND_SETXKBMAP:
            value = self._query_setxkbmap()

        if value is None:
            value = self.layouts[0] if self.layouts else "us"
        self._cache_value = value
        self._cache_time = now
        return value

    def _g3kb_set(self, target: str) -> subprocess.CompletedProcess[str]:
        """Invoke ``g3kb-switch -s`` with ``target`` (name or index)."""
        argv = [BACKEND_G3KB, "-s", target]
        # Log the exact argv at DEBUG so a failing switch can be reproduced.
        logger.debug("Switching layout: %s", argv)
        return _run(argv)

    def switch_to(self, layout: str) -> bool:
        """Switch to ``layout``.

        Args:
            layout: The target layout identifier.

        Returns:
            ``True`` when the switch command succeeded, ``False`` otherwise.
        """
        layout = layout.lower()
        if layout not in self.layouts:
            logger.warning("Layout %s is not configured", layout)
            return False

        success = False
        if self._backend == BACKEND_G3KB:
            success = self._switch_g3kb(layout)
        elif self._backend == BACKEND_SETXKBMAP:
            logger.debug("Switching layout: %s", [BACKEND_SETXKBMAP, layout])
            result = _run([BACKEND_SETXKBMAP, layout])
            success = result.returncode == 0
        else:
            logger.warning("No layout backend available; cannot switch to %s", layout)
            return False

        if success:
            self._cache_value = layout
            self._cache_time = time.monotonic()
        else:
            logger.error("Failed to switch layout to %s via %s", layout, self._backend)
        return success

    def _switch_g3kb(self, layout: str) -> bool:
        """Switch to ``layout`` through ``g3kb-switch``.

        ``g3kb-switch -s`` accepts either the layout name (for example ``ru``)
        or its numeric group index. The name is tried first and the index is
        used as a fallback, because some builds match the D-Bus layout id
        exactly while others only resolve the index. A zero exit status is
        authoritative: ``g3kb-switch`` prints diagnostics to stderr on a
        non-fatal path, so stderr is deliberately not inspected.
        """
        result = self._g3kb_set(layout)
        if result.returncode == 0:
            return True
        logger.debug(
            "g3kb-switch -s %s failed (rc=%s): %s",
            layout,
            result.returncode,
            (result.stderr or "").strip(),
        )
        index = str(self.layouts.index(layout))
        fallback = self._g3kb_set(index)
        return fallback.returncode == 0

    def describe(self) -> str:
        """Return a human readable description of the switcher state."""
        return f"backend={self._backend} session={self.session_type or 'unknown'}"
