"""Shared GUI state: config access and daemon status helpers.

The GUI never writes TOML by hand. It loads a :class:`~linguafix.config.Config`,
mutates the dataclass and calls :func:`~linguafix.config.save_config`, so all
validation and defaults stay in one place.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import Final

from ..config import Config, load_config, save_config
from ..daemon_control import (
    autostart_enabled as daemon_autostart_enabled,
    disable_autostart as daemon_disable_autostart,
    enable_autostart as daemon_enable_autostart,
    is_running as daemon_is_running,
    last_error as daemon_last_error,
    read_history as daemon_read_history,
    reload_config as daemon_reload_config,
    request_history as daemon_request_history,
    restart as daemon_restart,
    start as daemon_start,
    stop as daemon_stop,
    undo_last_fix as daemon_undo_last_fix,
)

logger = logging.getLogger(__name__)

STATUS_TIMEOUT: Final[float] = 3.0
MODE_LABELS: Final[dict[str, str]] = {
    "auto": "Авто",
    "manual": "Ручной",
    "hybrid": "Гибрид",
}
LANGUAGE_LABELS: Final[dict[str, str]] = {
    "en": "English",
    "ru": "Русский",
    "uk": "Українська",
    "de": "Deutsch",
    "fr": "Français",
}


@dataclass
class GuiState:
    """Mutable state shared by the GUI pages.

    Attributes:
        config: The configuration loaded from disk (kept in sync on save).
        last_fix_at: Monotonic timestamp of the last observed correction, used
            to render "N seconds ago" on the home page.
    """

    config: Config = field(default_factory=load_config)
    last_fix_at: float | None = None

    def reload(self) -> Config:
        """Reload the configuration from disk."""
        self.config = load_config()
        return self.config

    def save(self) -> None:
        """Persist the current configuration and apply it to a running daemon.

        A running daemon keeps its own copy of the configuration, so writing the
        file alone would only take effect after a restart. Every save therefore
        asks a live daemon to reload, not just :meth:`set_mode`: otherwise a
        switch flipped in the GUI (typo correction, a trigger, a guard) is
        written to disk but never reaches the daemon, and the feature silently
        does nothing. The reload is best-effort and never blocks a save.
        """
        save_config(self.config)
        if daemon_is_running():
            daemon_reload_config()

    def set_mode(self, mode: str) -> None:
        """Set the working mode and apply it to a running daemon.

        :meth:`save` already pushes the new configuration to a live daemon, so
        the mode is live immediately without a separate reload.
        """
        self.config.mode = mode
        self.config.validate()
        self.save()

    def set_languages(self, languages: list[str]) -> None:
        """Replace the enabled languages and persist them."""
        self.config.languages = list(languages)
        self.config.validate()
        self.save()

    # --- daemon status ----------------------------------------------------
    def is_active(self) -> bool:
        """Return ``True`` when a daemon is running, however it was started."""
        return daemon_is_running()

    def is_autostart_enabled(self) -> bool:
        """Return ``True`` when the daemon will start at login."""
        return daemon_autostart_enabled()

    def start(self) -> bool:
        """Start the daemon."""
        return daemon_start()

    def last_error(self) -> str | None:
        """Return the reason the last start attempt failed, if any."""
        return daemon_last_error()

    def stop(self) -> bool:
        """Stop the daemon."""
        return daemon_stop()

    def restart(self) -> bool:
        """Restart the daemon."""
        return daemon_restart()

    def reload_config(self) -> bool:
        """Ask the running daemon to reload its configuration."""
        return daemon_reload_config()

    def undo_last_fix(self, entry_id: int | None = None) -> bool:
        """Ask the running daemon to undo its most recent correction.

        ``entry_id`` is accepted for API symmetry with the history tab; the
        daemon only ever undoes the newest fix, so a stale id is refused there.
        """
        return daemon_undo_last_fix()

    def read_history(self) -> list[dict[str, object]]:
        """Ask the daemon to refresh its history and return the snapshot.

        Falls back to the last snapshot when no daemon is running. Every entry
        is metadata only (word length, layouts, timestamp, undone flag).
        """
        daemon_request_history()
        return daemon_read_history()

    def in_quiet_hours(self) -> bool:
        """Return whether the quiet-hours window currently applies."""
        if not self.config.quiet_hours_enabled:
            return False
        from ..config import in_quiet_hours

        now = time.localtime()
        return in_quiet_hours(
            self.config.quiet_hours_start,
            self.config.quiet_hours_end,
            now.tm_hour * 60 + now.tm_min,
        )

    def is_app_excepted(self, app: str | None) -> bool:
        """Return whether ``app`` is on the never-touch exception list."""
        if not app:
            return False
        return app.lower() in {name.lower() for name in self.config.exceptions_apps}

    def set_autostart(self, enabled: bool) -> bool:
        """Enable or disable autostart and return whether it succeeded."""
        return daemon_enable_autostart() if enabled else daemon_disable_autostart()

    def current_layout(self) -> str:
        """Return the active keyboard layout, or an empty string."""
        try:
            result = subprocess.run(
                ["g3kb-switch", "-p"],
                check=False,
                capture_output=True,
                text=True,
                timeout=STATUS_TIMEOUT,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return ""
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def seconds_since_last_fix(self) -> int | None:
        """Return whole seconds since the last fix, or ``None``."""
        if self.last_fix_at is None:
            return None
        return int(time.monotonic() - self.last_fix_at)

    def status_summary(self) -> str:
        """Return a short human-readable status line."""
        layout = self.current_layout() or "—"
        mode = MODE_LABELS.get(self.config.mode, self.config.mode)
        return f"Раскладка: {layout} · Режим: {mode}"
