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
import re
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
# Fallback idle timeout for words typed without a separator (a long URL or a
# compound word). Word-boundary keys flush the buffer immediately, so this is
# only the backstop and can be short.
DEFAULT_ANALYSIS_TIMEOUT: Final[float] = 0.8
DEFAULT_MIN_WORD_LENGTH: Final[int] = 3
DEFAULT_MAX_BUFFER_SIZE: Final[int] = 200
DEFAULT_BACKSPACE_SETTLE_MS: Final[int] = 50
# Pause after a word-boundary key (Space/Enter/Tab) before the deletion is sent.
# The boundary key that triggered the flush is still being processed by the
# compositor when the daemon starts erasing; without this pause Chromium and
# Electron coalesce the fast synthetic Backspaces and the first character
# survives (``руддщ `` -> ``рhello``). Only applies to a boundary flush, never
# to the idle fallback or an explicit hotkey.
DEFAULT_TRIGGER_SETTLE_MS: Final[int] = 50
DEFAULT_PUNCTUATION_CHARS: Final[str] = ".!?,;:"
DEFAULT_CONFIDENCE_THRESHOLD: Final[float] = 0.6
DEFAULT_CONTEXT_WEIGHT: Final[float] = 0.3
DEFAULT_UNDO_WINDOW_SECONDS: Final[int] = 10
DEFAULT_UNDO_HISTORY_DEPTH: Final[int] = 3
DEFAULT_DICTIONARY_SIZE: Final[int] = 5000
DEFAULT_LOG_ROTATION_MB: Final[int] = 5
# Plausibility guard: when the text typed in the *current* layout already looks
# like real words, it is left alone even if another layout scores higher. The
# floor is an average bigram log-probability; below it a word looks like noise
# (``руддщ`` scores ~-11, a real but rare word such as ``нот`` ~-4.6).
DEFAULT_PLAUSIBILITY_FLOOR: Final[float] = -7.0
# A run of consonants longer than this is a strong "not a word" signal.
DEFAULT_MAX_CONSECUTIVE_CONSONANTS: Final[int] = 6
DEFAULT_MIN_VOWEL_RATIO: Final[float] = 0.15
# The manual-fix hotkey default. A double tap of the same modifier works on
# every keyboard, unlike the previous ``PAUSE`` default (many laptops have no
# Pause key). ``SHIFT+SHIFT`` is the double-tap of the shift family.
DEFAULT_FIX_HOTKEY: Final[str] = "SHIFT+SHIFT"
# The pre-1.0 manual-fix default. Kept so an unmodified old config migrates to
# the double-tap default instead of staying on a key many laptops lack.
LEGACY_FIX_HOTKEY: Final[str] = "PAUSE"
# The undo hotkey default. ``CTRL+Z`` collides with the application's own undo,
# so the daemon uses ``SHIFT+BACKSPACE`` instead.
DEFAULT_UNDO_HOTKEY: Final[str] = "SHIFT+BACKSPACE"
# Maximum gap between the two taps of a double-tap hotkey.
DEFAULT_DOUBLE_TAP_MS: Final[int] = 300
VALID_BACKENDS: Final[tuple[str, ...]] = ("auto", "uinput", "wtype", "xdotool")
VALID_SWITCH_METHODS: Final[tuple[str, ...]] = ("auto", "g3kb-switch", "setxkbmap")
VALID_LOG_LEVELS: Final[tuple[str, ...]] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
VALID_MODES: Final[tuple[str, ...]] = ("auto", "manual", "hybrid")
VALID_DICTIONARY_SIZES: Final[tuple[int, ...]] = (1000, 5000, 10000)
# The languages LinguaFix ships layouts and dictionaries for.
SUPPORTED_LANGUAGES: Final[tuple[str, ...]] = ("en", "ru", "uk", "de", "fr")
DEFAULT_LANGUAGES: Final[tuple[str, ...]] = ("en", "ru")
# Keys that may never be bound as a hotkey: they are the word boundaries and
# would make the daemon unusable if swallowed.
FORBIDDEN_HOTKEY_KEYS: Final[frozenset[str]] = frozenset(
    {"ESC", "ESCAPE", "ENTER", "RETURN", "KPENTER", "SPACE", "TAB"}
)
_HOTKEY_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z0-9+_]+$")


def normalise_hotkey(value: str) -> str:
    """Normalise a hotkey string to ``MOD+MOD+KEY`` upper-case form.

    Accepts ``"PAUSE"``, ``"CTRL+SHIFT+F12"`` and ``"RIGHTCTRL+RIGHTALT"``.
    Empty strings are allowed and mean "unbound".

    Raises:
        ValueError: If the value is malformed or uses a forbidden key.
    """
    text = str(value).strip().upper()
    if not text:
        return ""
    if not _HOTKEY_TOKEN_RE.match(text):
        raise ValueError(f"invalid hotkey {value!r}")
    parts = [part for part in text.split("+") if part]
    if not parts:
        return ""
    key = parts[-1]
    if key in FORBIDDEN_HOTKEY_KEYS:
        raise ValueError(f"hotkey key {key!r} is not allowed")
    if len(parts) > 4:
        raise ValueError(f"too many modifiers in hotkey {value!r}")
    return "+".join(parts)


# Maps a nested TOML table to the prefix its keys gain when flattened. Keys that
# already start with the prefix are left untouched, so ``[trigger] on_space``
# and a flat ``on_space`` behave identically.
_SECTION_PREFIXES: Final[dict[str, str]] = {
    "trigger": "",
    "timing": "",
    "hotkeys": "hotkey_",
    "undo": "undo_",
    "notifications": "notify_",
    "logs": "log_",
    "log": "log_",
    "detector": "",
    "exceptions": "exceptions_",
    "dictionary": "dictionary_",
    "dictionaries": "dictionary_",
    "apps": "exceptions_",
}


def _flatten_sections(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten known TOML tables into their field-name form.

    Unknown keys and unknown tables are passed through unchanged so
    :meth:`Config.from_dict` can ignore them as before.
    """
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict) and key in _SECTION_PREFIXES:
            prefix = _SECTION_PREFIXES[key]
            for sub_key, sub_value in value.items():
                name = str(sub_key)
                if prefix and name.startswith(prefix):
                    flat[name] = sub_value
                else:
                    flat[f"{prefix}{name}"] = sub_value
        else:
            flat[key] = value
    return flat


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
        analysis_timeout: Fallback seconds of inactivity before a buffer without
            a word boundary is analysed. Space/Enter/Tab flush it immediately.
        min_word_length: Words shorter than this are never auto-corrected.
        max_buffer_size: Upper bound on the keystroke buffer; when exceeded the
            buffer is analysed and cleared early so memory stays bounded.
        stop_words: Tokens that disable automatic correction (passwords, etc.).
        layouts: Ordered list of layouts, primary first (for example ``["us", "ru"]``).
        backend: Text injection backend, one of :data:`VALID_BACKENDS`.
        switch_method: Layout switching method, one of :data:`VALID_SWITCH_METHODS`.
        notify_on_fix: Whether to show a desktop notification on every fix.
        tray_enabled: Whether to try to show an AppIndicator tray icon.
        hotkey: evdev key name used for manual correction.
        log_level: Logging verbosity, one of :data:`VALID_LOG_LEVELS`.
        on_space: Flush the buffer when Space is pressed (main trigger).
        on_enter: Flush the buffer when Enter is pressed.
        on_tab: Flush the buffer when Tab is pressed.
        on_punctuation: Flush the buffer when a punctuation key is pressed.
        punctuation_chars: Characters that act as a boundary when
            ``on_punctuation`` is enabled.
        backspace_settle_ms: Milliseconds to wait after the Backspace batch and
            before typing the replacement. Chromium/Electron applications
            process Backspace asynchronously, so a small pause avoids the race
            that otherwise leaves the first character behind (``рhello``).
        trigger_settle_ms: Milliseconds to wait after a word-boundary flush
            (Space/Enter/Tab) before the deletion is sent, so the boundary key
            itself is processed by the application first.
    """

    analysis_timeout: float = DEFAULT_ANALYSIS_TIMEOUT
    min_word_length: int = DEFAULT_MIN_WORD_LENGTH
    max_buffer_size: int = DEFAULT_MAX_BUFFER_SIZE
    stop_words: list[str] = field(default_factory=load_default_stop_words)
    layouts: list[str] = field(default_factory=lambda: ["us", "ru"])
    languages: list[str] = field(default_factory=lambda: list(DEFAULT_LANGUAGES))
    backend: str = "auto"
    switch_method: str = "auto"
    notify_on_fix: bool = False
    notify_on_error: bool = False
    sound_on_fix: bool = False
    tray_enabled: bool = True
    hotkey: str = DEFAULT_FIX_HOTKEY
    log_level: str = "INFO"
    log_rotation_mb: int = DEFAULT_LOG_ROTATION_MB
    on_space: bool = True
    on_enter: bool = True
    on_tab: bool = False
    on_punctuation: bool = False
    punctuation_chars: str = DEFAULT_PUNCTUATION_CHARS
    backspace_settle_ms: int = DEFAULT_BACKSPACE_SETTLE_MS
    trigger_settle_ms: int = DEFAULT_TRIGGER_SETTLE_MS

    # --- Task D: modes and hotkeys -----------------------------------------
    mode: str = "auto"
    hotkeys_enabled: bool = True
    hotkey_fix_last_word: str = DEFAULT_FIX_HOTKEY
    hotkey_undo_last_fix: str = DEFAULT_UNDO_HOTKEY
    hotkey_toggle_mode: str = ""
    hotkey_reload_config: str = "CTRL+SHIFT+R"
    hotkey_swallow: bool = True
    hotkey_double_tap_ms: int = DEFAULT_DOUBLE_TAP_MS
    undo_window_seconds: int = DEFAULT_UNDO_WINDOW_SECONDS
    undo_history_depth: int = DEFAULT_UNDO_HISTORY_DEPTH

    # --- Task E: detector tuning, context, exceptions, dictionaries --------
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    context_analysis: bool = True
    context_weight: float = DEFAULT_CONTEXT_WEIGHT
    ignore_all_caps: bool = False
    ignore_with_digits: bool = False
    ignore_emails_urls: bool = True
    plausibility_check: bool = True
    structural_boundaries: bool = True
    identifier_guard: bool = True
    plausibility_floor: float = DEFAULT_PLAUSIBILITY_FLOOR
    max_consecutive_consonants: int = DEFAULT_MAX_CONSECUTIVE_CONSONANTS
    min_vowel_ratio: float = DEFAULT_MIN_VOWEL_RATIO
    custom_skip_regex: str = ""
    exceptions_apps: list[str] = field(default_factory=list)
    exceptions_force_in_manual: list[str] = field(default_factory=list)
    dictionary_size: int = DEFAULT_DICTIONARY_SIZE
    dictionary_custom_path: str = ""

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

        self.max_buffer_size = int(self.max_buffer_size)
        if self.max_buffer_size < 1:
            raise ValueError("max_buffer_size must be >= 1")

        if not self.layouts:
            raise ValueError("layouts must contain at least one layout")
        self.layouts = [str(layout).lower() for layout in self.layouts]

        self.languages = [str(lang).lower() for lang in self.languages]
        unknown = [lang for lang in self.languages if lang not in SUPPORTED_LANGUAGES]
        if unknown:
            raise ValueError(f"unsupported languages: {unknown}")
        if not self.languages:
            raise ValueError("languages must contain at least one language")

        self.backend = str(self.backend).lower()
        if self.backend not in VALID_BACKENDS:
            raise ValueError(f"backend must be one of {VALID_BACKENDS}")

        self.switch_method = str(self.switch_method).lower()
        if self.switch_method not in VALID_SWITCH_METHODS:
            raise ValueError(f"switch_method must be one of {VALID_SWITCH_METHODS}")

        self.log_level = str(self.log_level).upper()
        if self.log_level not in VALID_LOG_LEVELS:
            raise ValueError(f"log_level must be one of {VALID_LOG_LEVELS}")

        self.log_rotation_mb = int(self.log_rotation_mb)
        if not 1 <= self.log_rotation_mb <= 50:
            raise ValueError("log_rotation_mb must be between 1 and 50")

        self.on_space = bool(self.on_space)
        self.on_enter = bool(self.on_enter)
        self.on_tab = bool(self.on_tab)
        self.on_punctuation = bool(self.on_punctuation)
        self.punctuation_chars = str(self.punctuation_chars)

        self.backspace_settle_ms = int(self.backspace_settle_ms)
        if not 0 <= self.backspace_settle_ms <= 200:
            raise ValueError("backspace_settle_ms must be between 0 and 200")

        self.trigger_settle_ms = int(self.trigger_settle_ms)
        if not 0 <= self.trigger_settle_ms <= 200:
            raise ValueError("trigger_settle_ms must be between 0 and 200")

        # --- modes and hotkeys ---------------------------------------------
        self.mode = str(self.mode).lower()
        if self.mode not in VALID_MODES:
            raise ValueError(f"mode must be one of {VALID_MODES}")

        self.hotkeys_enabled = bool(self.hotkeys_enabled)
        self.hotkey_swallow = bool(self.hotkey_swallow)
        # ``hotkey`` is the legacy name for the manual-fix hotkey; keep the two in
        # sync so old config files and the new GUI agree. A config written before
        # the double-tap default carries ``hotkey = "PAUSE"`` *and*
        # ``hotkey_fix_last_word = "PAUSE"``; that pair means "old default", so it
        # migrates to ``SHIFT+SHIFT``. Any other legacy value only wins when the
        # new field was left at its default, so an explicit
        # ``hotkey_fix_last_word`` always takes precedence.
        legacy = normalise_hotkey(self.hotkey)
        self.hotkey = legacy
        old_default_pair = (
            legacy == LEGACY_FIX_HOTKEY and self.hotkey_fix_last_word == LEGACY_FIX_HOTKEY
        )
        if not self.hotkey_fix_last_word or (
            self.hotkey_fix_last_word == DEFAULT_FIX_HOTKEY
            and legacy not in ("", DEFAULT_FIX_HOTKEY)
        ):
            self.hotkey_fix_last_word = legacy
        if old_default_pair:
            self.hotkey_fix_last_word = DEFAULT_FIX_HOTKEY
            self.hotkey = DEFAULT_FIX_HOTKEY
        self.hotkey_fix_last_word = normalise_hotkey(self.hotkey_fix_last_word)
        self.hotkey_undo_last_fix = normalise_hotkey(self.hotkey_undo_last_fix)
        self.hotkey_toggle_mode = normalise_hotkey(self.hotkey_toggle_mode)
        self.hotkey_reload_config = normalise_hotkey(self.hotkey_reload_config)

        self.hotkey_double_tap_ms = int(self.hotkey_double_tap_ms)
        if not 100 <= self.hotkey_double_tap_ms <= 1000:
            raise ValueError("hotkey_double_tap_ms must be between 100 and 1000")

        self.undo_window_seconds = int(self.undo_window_seconds)
        if not 3 <= self.undo_window_seconds <= 60:
            raise ValueError("undo_window_seconds must be between 3 and 60")
        self.undo_history_depth = int(self.undo_history_depth)
        if not 1 <= self.undo_history_depth <= 10:
            raise ValueError("undo_history_depth must be between 1 and 10")

        # --- detector / context / exceptions / dictionaries ----------------
        self.confidence_threshold = float(self.confidence_threshold)
        if not 0.5 <= self.confidence_threshold <= 0.95:
            raise ValueError("confidence_threshold must be between 0.5 and 0.95")
        self.context_analysis = bool(self.context_analysis)
        self.context_weight = float(self.context_weight)
        if not 0.0 <= self.context_weight <= 1.0:
            raise ValueError("context_weight must be between 0 and 1")
        self.ignore_all_caps = bool(self.ignore_all_caps)
        self.ignore_with_digits = bool(self.ignore_with_digits)
        self.ignore_emails_urls = bool(self.ignore_emails_urls)
        self.plausibility_check = bool(self.plausibility_check)
        self.structural_boundaries = bool(self.structural_boundaries)
        self.identifier_guard = bool(self.identifier_guard)
        self.plausibility_floor = float(self.plausibility_floor)
        self.max_consecutive_consonants = int(self.max_consecutive_consonants)
        if self.max_consecutive_consonants < 2:
            raise ValueError("max_consecutive_consonants must be >= 2")
        self.min_vowel_ratio = float(self.min_vowel_ratio)
        if not 0.0 <= self.min_vowel_ratio < 1.0:
            raise ValueError("min_vowel_ratio must be between 0 and 1")
        self.custom_skip_regex = str(self.custom_skip_regex)
        if self.custom_skip_regex:
            try:
                re.compile(self.custom_skip_regex)
            except re.error as exc:
                raise ValueError(f"custom_skip_regex is not a valid regex: {exc}") from exc

        self.exceptions_apps = [
            str(app).strip() for app in self.exceptions_apps if str(app).strip()
        ]
        self.exceptions_force_in_manual = [
            str(app).strip() for app in self.exceptions_force_in_manual if str(app).strip()
        ]

        self.dictionary_size = int(self.dictionary_size)
        if self.dictionary_size not in VALID_DICTIONARY_SIZES:
            raise ValueError(f"dictionary_size must be one of {VALID_DICTIONARY_SIZES}")
        self.dictionary_custom_path = str(self.dictionary_custom_path)

        self.stop_words = [str(word).lower() for word in self.stop_words]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        """Build a :class:`Config` from a mapping, ignoring unknown keys.

        Flat keys are accepted directly. Nested TOML tables (``[trigger]``,
        ``[timing]``, ``[hotkeys]``, ``[detector]``, ``[exceptions]``,
        ``[notifications]``, ``[logs]``, ``[dictionary]``, ``[undo]``) are
        flattened into their field names so a hand-written config keeps working.

        Args:
            data: Mapping loaded from a TOML file.

        Returns:
            A validated :class:`Config` instance.
        """
        known = set(cls.__dataclass_fields__)
        filtered: dict[str, Any] = {}
        for key, value in _flatten_sections(data).items():
            if key in known:
                filtered[key] = value
                continue
            # A section prefix may not fit every key (``[notifications]
            # sound_on_fix``): fall back to the bare key when it is a field.
            for prefix in ("hotkey_", "undo_", "notify_", "log_", "exceptions_", "dictionary_"):
                if key.startswith(prefix) and key[len(prefix) :] in known:
                    filtered[key[len(prefix) :]] = value
                    break
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
