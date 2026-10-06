"""Shared GUI state: config access and daemon status helpers.

The GUI never writes TOML by hand. It loads a :class:`~linguafix.config.Config`,
mutates the dataclass and calls :func:`~linguafix.config.save_config`, so all
validation and defaults stay in one place.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from ..config import Config, load_config, save_config
from ..daemon_control import (
    autostart_enabled as daemon_autostart_enabled,
    disable_autostart as daemon_disable_autostart,
    enable_autostart as daemon_enable_autostart,
    is_running as daemon_is_running,
    read_history as daemon_read_history,
    reload_config as daemon_reload_config,
    request_history as daemon_request_history,
    restart as daemon_restart,
    start as daemon_start,
    stop as daemon_stop,
    undo_last_fix as daemon_undo_last_fix,
)
from .async_tasks import run_async

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
class StatusSnapshot:
    """A consistent set of daemon probes gathered on a worker thread.

    The home page renders one snapshot at a time so the toggle, the status row
    and the autostart switch never disagree while a probe is in flight.
    """

    active: bool = False
    layout: str = ""
    autostart: bool = False


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
        """Persist the current configuration."""
        save_config(self.config)

    def set_mode(self, mode: str) -> None:
        """Set the working mode, persist it and apply it to a running daemon.

        A running daemon keeps its own copy of the configuration, so writing the
        file alone would only take effect after a restart. When a daemon is up
        we also ask it to reload, so the new mode is live immediately.
        """
        self.config.mode = mode
        self.config.validate()
        self.save()
        if daemon_is_running():
            daemon_reload_config()

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

    # --- non-blocking probes ---------------------------------------------
    # Every method below runs a blocking callable (a subprocess or a D-Bus
    # round trip) in a worker thread and returns the result on the main loop.
    # The GUI never calls the synchronous variants from a signal handler,
    # because a slow ``systemctl`` or ``g3kb-switch`` would freeze the window
    # (the "Приложение не отвечает" hang).
    def probe_is_active(self, on_done: Callable[[bool], None]) -> None:
        """Deliver the daemon's running state asynchronously."""
        run_async(daemon_is_running, on_done, lambda _exc: on_done(False))

    def probe_layout(self, on_done: Callable[[str], None]) -> None:
        """Deliver the current keyboard layout asynchronously."""
        run_async(self.current_layout, on_done, lambda _exc: on_done(""))

    def probe_autostart(self, on_done: Callable[[bool], None]) -> None:
        """Deliver the autostart state asynchronously."""
        run_async(daemon_autostart_enabled, on_done, lambda _exc: on_done(False))

    def probe_active_app(self, on_done: Callable[[str | None], None]) -> None:
        """Deliver the focused application's short name asynchronously."""
        try:
            from ..app_focus import get_active_app
        except ImportError:  # pragma: no cover - defensive
            on_done(None)
            return
        run_async(get_active_app, on_done, lambda _exc: on_done(None))

    def probe_toggle(
        self,
        want_active: bool,
        on_done: Callable[[bool], None],
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        """Start or stop the daemon off the main thread, then report success.

        ``on_done`` receives the start/stop return value; the caller still polls
        :meth:`probe_is_active` afterwards, because systemd can report success
        before ``is-active`` flips.
        """
        work = self.start if want_active else self.stop
        run_async(work, on_done, on_error)

    def probe_undo(self, on_done: Callable[[bool], None]) -> None:
        """Ask the daemon to undo its last fix, off the main thread."""
        run_async(self.undo_last_fix, on_done, lambda _exc: on_done(False))

    def probe_set_autostart(self, enabled: bool, on_done: Callable[[bool], None]) -> None:
        """Enable or disable autostart, off the main thread."""
        run_async(lambda: self.set_autostart(enabled), on_done, lambda _exc: on_done(False))

    def probe_status_snapshot(self, on_done: Callable[[StatusSnapshot], None]) -> None:
        """Gather active/layout/autostart in one worker pass and deliver them.

        All three probes run on the same worker thread, so the UI updates once
        with a consistent snapshot instead of three times with partial state.
        """
        run_async(self._collect_status, on_done, lambda _exc: on_done(StatusSnapshot()))

    def _collect_status(self) -> StatusSnapshot:
        return StatusSnapshot(
            active=daemon_is_running(),
            layout=self.current_layout(),
            autostart=daemon_autostart_enabled(),
        )

    def probe_current_app_excepted(self, on_done: Callable[[str | None], None]) -> None:
        """Deliver the focused app name only when it is on the exception list."""

        def _check(app: str | None) -> None:
            on_done(app if self.is_app_excepted(app) else None)

        self.probe_active_app(_check)

    def status_summary(self) -> str:
        """Return a short human-readable status line."""
        layout = self.current_layout() or "—"
        mode = MODE_LABELS.get(self.config.mode, self.config.mode)
        return f"Раскладка: {layout} · Режим: {mode}"
