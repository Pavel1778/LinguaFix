"""Configuration handling for LinguaFix.

Configuration is stored as TOML in ``~/.config/linguafix/config.toml``. The
module provides a :class:`Config` dataclass together with :func:`load_config`
and :func:`save_config` helpers. When the file does not exist it is created
with sensible defaults; when it is corrupted it is backed up and defaults are
used so that the daemon never crashes because of a bad config file.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any, Final

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib

import tomli_w

logger = logging.getLogger(__name__)

APP_NAME: Final[str] = "linguafix"
DEFAULT_ANALYSIS_TIMEOUT: Final[float] = 1.5
DEFAULT_MIN_WORD_LENGTH: Final[int] = 3
VALID_BACKENDS: Final[tuple[str, ...]] = ("auto", "uinput", "wtype", "xdotool")
VALID_SWITCH_METHODS: Final[tuple[str, ...]] = ("auto", "g3kb-switch", "setxkbmap")
VALID_LOG_LEVELS: Final[tuple[str, ...]] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _xdg_dir(env_var: str, fallback: Path) -> Path:
    """Return an XDG base directory honouring ``env_var`` when set."""
    value = os.environ.get(env_var)
    if value:
        return Path(value).expanduser()
    return fallback


def config_dir() -> Path:
    """Return the directory holding the user configuration file."""
    return _xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config") / APP_NAME


def config_path() -> Path:
    """Return the full path to ``config.toml``."""
    return config_dir() / "config.toml"


def state_dir() -> Path:
    """Return the directory for logs and other persistent state."""
    return _xdg_dir("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_NAME


def cache_dir() -> Path:
    """Return the directory for cache and lock files."""
    return _xdg_dir("XDG_CACHE_HOME", Path.home() / ".cache") / APP_NAME


def data_dir() -> Path:
    """Return the filesystem path of the bundled ``data`` package."""
    return Path(str(resources.files("linguafix") / "data"))


def load_default_stop_words() -> list[str]:
    """Load the bundled stop-word list, returning an empty list on failure."""
    try:
        raw = (data_dir() / "stop_words.txt").read_text(encoding="utf-8")
    except OSError:
        logger.warning("Bundled stop_words.txt could not be read", exc_info=True)
        return []
    return [
        line.strip().lower()
        for line in raw.splitlines()
        if line.strip() and not line.startswith("#")
    ]


@dataclass
class Config:
    """Runtime configuration of the LinguaFix daemon.

    Attributes:
        analysis_timeout: Seconds of inactivity before the buffer is analysed.
        min_word_length: Words shorter than this are never auto-corrected.
        stop_words: Tokens that disable automatic correction (passwords, etc.).
        layouts: Ordered list of layouts, primary first (for example ``["us", "ru"]``).
        backend: Text injection backend, one of :data:`VALID_BACKENDS`.
        switch_method: Layout switching method, one of :data:`VALID_SWITCH_METHODS`.
        notify_on_fix: Whether to show a desktop notification on every fix.
        tray_enabled: Whether to try to show an AppIndicator tray icon.
        hotkey: evdev key name used for manual correction.
        log_level: Logging verbosity, one of :data:`VALID_LOG_LEVELS`.
    """

    analysis_timeout: float = DEFAULT_ANALYSIS_TIMEOUT
    min_word_length: int = DEFAULT_MIN_WORD_LENGTH
    stop_words: list[str] = field(default_factory=load_default_stop_words)
    layouts: list[str] = field(default_factory=lambda: ["us", "ru"])
    backend: str = "auto"
    switch_method: str = "auto"
    notify_on_fix: bool = False
    tray_enabled: bool = True
    hotkey: str = "PAUSE"
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Normalise and validate field values in place.

        Raises:
            ValueError: If a value cannot be coerced into a valid one.
        """
        self.analysis_timeout = float(self.analysis_timeout)
        if self.analysis_timeout <= 0:
            raise ValueError("analysis_timeout must be positive")

        self.min_word_length = int(self.min_word_length)
        if self.min_word_length < 1:
            raise ValueError("min_word_length must be >= 1")

        if not self.layouts:
            raise ValueError("layouts must contain at least one layout")
        self.layouts = [str(layout).lower() for layout in self.layouts]

        self.backend = str(self.backend).lower()
        if self.backend not in VALID_BACKENDS:
            raise ValueError(f"backend must be one of {VALID_BACKENDS}")

        self.switch_method = str(self.switch_method).lower()
        if self.switch_method not in VALID_SWITCH_METHODS:
            raise ValueError(f"switch_method must be one of {VALID_SWITCH_METHODS}")

        self.log_level = str(self.log_level).upper()
        if self.log_level not in VALID_LOG_LEVELS:
            raise ValueError(f"log_level must be one of {VALID_LOG_LEVELS}")

        self.stop_words = [str(word).lower() for word in self.stop_words]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        """Build a :class:`Config` from a mapping, ignoring unknown keys.

        Args:
            data: Mapping loaded from a TOML file.

        Returns:
            A validated :class:`Config` instance.
        """
        known = set(cls.__dataclass_fields__)
        filtered = {key: value for key, value in data.items() if key in known}
        try:
            return cls(**filtered)
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid configuration value (%s); falling back to defaults", exc)
            return cls()

    def to_dict(self) -> dict[str, Any]:
        """Return a plain ``dict`` representation suitable for TOML dumping."""
        return asdict(self)


def _write_default(path: Path, config: Config) -> None:
    """Write ``config`` to ``path`` creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomli_w.dumps(config.to_dict()), encoding="utf-8")


def load_config(path: Path | None = None) -> Config:
    """Load the configuration, creating a default file when missing.

    A corrupted file is moved aside (``config.toml.corrupt-<timestamp>``) and
    defaults are returned instead of raising.

    Args:
        path: Optional explicit path, defaults to :func:`config_path`.

    Returns:
        A validated :class:`Config` instance.
    """
    target = path or config_path()
    if not target.exists():
        config = Config()
        try:
            _write_default(target, config)
        except OSError:
            logger.warning("Could not create default config at %s", target, exc_info=True)
        return config

    try:
        raw = target.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        logger.error("Failed to parse %s: %s", target, exc)
        backup = target.with_suffix(f".toml.corrupt-{datetime.now():%Y%m%d%H%M%S}")
        try:
            shutil.copy2(target, backup)
            logger.warning("Corrupted config backed up to %s", backup)
        except OSError:
            logger.warning("Could not back up corrupted config", exc_info=True)
        return Config()

    return Config.from_dict(data)


def save_config(config: Config, path: Path | None = None) -> Path:
    """Persist ``config`` to disk.

    Args:
        config: The configuration to save.
        path: Optional explicit path, defaults to :func:`config_path`.

    Returns:
        The path the configuration was written to.
    """
    target = path or config_path()
    _write_default(target, config)
    logger.debug("Configuration saved to %s", target)
    return target
