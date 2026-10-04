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
from . import systemd_bridge

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
        """Persist the current configuration."""
        save_config(self.config)

    def set_mode(self, mode: str) -> None:
        """Set the working mode and persist it."""
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
        """Return ``True`` when the daemon unit is running."""
        return systemd_bridge.is_service_active()

    def is_autostart_enabled(self) -> bool:
        """Return ``True`` when the daemon unit is enabled for login."""
        return systemd_bridge.is_service_enabled()

    def start(self) -> bool:
        """Start the daemon."""
        return systemd_bridge.start_service()

    def stop(self) -> bool:
        """Stop the daemon."""
        return systemd_bridge.stop_service()

    def set_autostart(self, enabled: bool) -> bool:
        """Enable or disable autostart and return whether it succeeded."""
        return systemd_bridge.enable_autostart() if enabled else systemd_bridge.disable_autostart()

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
