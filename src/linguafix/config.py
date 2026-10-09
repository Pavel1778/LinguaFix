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
# Adaptive idle timeout: the effective timeout follows the user's typing speed
# (a fast typist wants a short backstop, a slow one needs a longer one) and is
# clamped to this range. ``analysis_timeout`` is the neutral base value.
DEFAULT_ANALYSIS_TIMEOUT_ADAPTIVE: Final[bool] = True
MIN_ANALYSIS_TIMEOUT: Final[float] = 0.3
MAX_ANALYSIS_TIMEOUT: Final[float] = 2.0
# Average inter-key interval (seconds) at which the timeout is nudged up/down.
FAST_TYPING_INTERVAL: Final[float] = 0.5
SLOW_TYPING_INTERVAL: Final[float] = 1.0
DEFAULT_MIN_WORD_LENGTH: Final[int] = 3
DEFAULT_MAX_BUFFER_SIZE: Final[int] = 200
DEFAULT_BACKSPACE_SETTLE_MS: Final[int] = 120
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
# Terminals and code editors are exactly the applications where "the other
# layout is more plausible" is wrong: what is typed there are commands and
# identifiers, not words. Pre-filling the list keeps the daemon quiet where a
# correction would annoy. Edit it in the GUI (Продвинутые → Исключения).
DEFAULT_EXCEPTION_APPS: Final[tuple[str, ...]] = (
    "gnome-terminal",
    "kgx",
    "konsole",
    "kitty",
    "alacritty",
    "xterm",
    "code",
    "codium",
    "sublime_text",
    # GNOME Text Editor replaced gedit as the default text editor (gedit is not
    # installed on Debian 13 / GNOME 48). The probe reduces an app id to its
    # last dot component and lower-cases it, so ``org.gnome.TextEditor`` is
    # matched as ``texteditor``.
    "texteditor",
    "jetbrains-idea",
    "idea",
    "pycharm",
    "webstorm",
    "clion",
    "goland",
    "steam",
    "lutris",
    "wine",
)
# Number of recent corrections kept for the GUI "История" tab. Metadata only,
# never the typed text, and never written to disk.
DEFAULT_HISTORY_SIZE: Final[int] = 20
# Plausibility guard: when the text typed in the *current* layout already looks
# like real words, it is left alone even if another layout scores higher. The
# floor is an average bigram log-probability; below it a word looks like noise
# (``руддщ`` scores ~-11, a real but rare word such as ``нот`` ~-4.6).
DEFAULT_PLAUSIBILITY_FLOOR: Final[float] = -7.0
# A run of consonants longer than this is a strong "not a word" signal.
DEFAULT_MAX_CONSECUTIVE_CONSONANTS: Final[int] = 6
DEFAULT_MIN_VOWEL_RATIO: Final[float] = 0.15
# T9 typo correction. Off by default: a wrong correction is worse than none, so
# the user opts in. Only a single edit is accepted for a short word; a word of
# at least ``DEFAULT_TYPO_LONG_WORD_THRESHOLD`` characters may use two edits,
# but only when the best candidate clearly beats the runner-up by frequency.
DEFAULT_TYPO_MAX_DISTANCE: Final[int] = 1
DEFAULT_TYPO_MIN_WORD_LENGTH: Final[int] = 4
DEFAULT_TYPO_MAX_DISTANCE_LONG: Final[int] = 2
DEFAULT_TYPO_LONG_WORD_THRESHOLD: Final[int] = 6
# Minimum frequency ratio (best / runner-up) before a two-edit fix is applied.
# Kept modest on purpose: even ``прветт`` -> ``привет`` only beats ``проект``
# by ~25x in the corpus, so a 100x bar would reject that flagship example.
DEFAULT_TYPO_TOP1_RATIO_STRICT: Final[float] = 10.0
# Seconds during which the same word is not typo-corrected again. The daemon
# may see the same on-screen word twice (a boundary flush then a late idle
# flush), and re-correcting it would rewrite already-correct text.
DEFAULT_TYPO_DEBOUNCE_SECONDS: Final[float] = 5.0
# T9 mode is independent of the global ``mode``: a user may want automatic
# layout switching but manual (hotkey-only) typo correction, or the reverse.
# ``off`` disables T9 entirely; ``auto``/``hybrid`` correct on a word boundary;
# ``manual`` corrects only on the explicit hotkey. ``typo_correction`` is the
# legacy boolean and is derived from this mode (``mode != "off"``).
DEFAULT_TYPO_MODE: Final[str] = "off"
# Punctuation cleanup has its own mode for the same reason. Off by default:
# rewriting punctuation inside code, formulas or URLs does more harm than good.
DEFAULT_PUNCTUATION_MODE: Final[str] = "off"
# The per-feature modes share the global mode vocabulary plus ``off``.
VALID_FEATURE_MODES: Final[tuple[str, ...]] = ("auto", "manual", "hybrid", "off")
# Default hotkeys for the manual T9 / punctuation actions.
DEFAULT_TYPO_HOTKEY: Final[str] = "CTRL+SHIFT+F"
DEFAULT_PUNCTUATION_HOTKEY: Final[str] = "CTRL+SHIFT+P"
# The pre-0.2.8 T9 mode migrates from the legacy ``typo_correction`` boolean
# (and, in ``manual``, from the now-removed ``typo_in_manual`` opt-in).
#
# Punctuation sub-flags. They stay on so that switching the punctuation mode on
# is useful out of the box.
DEFAULT_PUNCTUATION_DASHES: Final[bool] = True
DEFAULT_PUNCTUATION_ELLIPSIS: Final[bool] = True
DEFAULT_PUNCTUATION_SMART_QUOTES: Final[bool] = False
DEFAULT_PUNCTUATION_FIX_SPACING: Final[bool] = True
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
# A stuck pre-0.2.8 value: an old build (or a copy of an old default) left
# ``hotkey_undo_last_fix = "CTRL+CTRL"`` in the user's config, which is a
# double-tap binding no key map uses for undo. It migrates to the real default.
LEGACY_UNDO_HOTKEY: Final[str] = "CTRL+CTRL"
# Manual reverse-conversion hotkey: type ``привет`` -> press it -> ``ghbdtn``.
DEFAULT_TOGGLE_LAYOUT_HOTKEY: Final[str] = "CTRL+SHIFT+T"
# Maximum gap between the two taps of a double-tap hotkey. The default is
# generous (2 s) on purpose: at typing speed two Shift presses made while
# capitalising or reaching for the modifier can fall well inside a short
# window, and each false match deletes and retypes text. A deliberate double
# tap is still far below two seconds, so a real one never misses.
DEFAULT_DOUBLE_TAP_MS: Final[int] = 2000
# Accepted range for ``hotkey_double_tap_ms``. The upper bound is wide enough
# for a user who wants a longer manual-fix window (the request was 2-3 s).
MIN_DOUBLE_TAP_MS: Final[int] = 100
MAX_DOUBLE_TAP_MS: Final[int] = 3000
# The pre-0.2.8 double-tap window. 300 ms is too short: two Shift presses made
# while capitalising can fall outside it and a deliberate double tap is easy to
# miss. A config still on the old value migrates to the wider default.
LEGACY_DOUBLE_TAP_MS: Final[int] = 300
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


def _derive_feature_mode(enabled: bool, global_mode: str) -> str:
    """Return the per-feature mode implied by a legacy boolean and global mode.

    ``off`` when the feature was disabled; ``manual`` when it was enabled and
    the global mode is manual (preserving the old "hotkey only" behaviour);
    otherwise the global mode itself.
    """
    if not enabled:
        return "off"
    if global_mode == "manual":
        return "manual"
    if global_mode in VALID_FEATURE_MODES:
        return global_mode
    return "auto"


_HHMM_RE: Final[re.Pattern[str]] = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _validate_hhmm(value: str, field: str) -> str:
    """Return ``value`` when it is a valid ``HH:MM`` 24-hour time, else raise."""
    text = str(value).strip()
    if not _HHMM_RE.match(text):
        raise ValueError(f"{field} must be a HH:MM time, got {value!r}")
    return text


def _minutes(hhmm: str) -> int:
    """Return the minutes-since-midnight for a validated ``HH:MM`` string."""
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def in_quiet_hours(start: str, end: str, now_minutes: int) -> bool:
    """Return whether ``now_minutes`` falls in the ``[start, end)`` quiet window.

    The window may wrap past midnight (``22:00`` → ``08:00``), which is the
    common case; equal start and end means "never quiet".
    """
    start_m = _minutes(start)
    end_m = _minutes(end)
    if start_m == end_m:
        return False
    if start_m < end_m:
        return start_m <= now_minutes < end_m
    return now_minutes >= start_m or now_minutes < end_m


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
    "typo": "typo_",
    "t9": "typo_",
    "punctuation": "punctuation_",
    "expander": "text_expander_",
    "selection": "selection_fix_",
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


def snippets_path() -> Path:
    """Return the default path to ``snippets.toml``."""
    return config_dir() / "snippets.toml"


def state_dir() -> Path:
    """Return the directory for logs and other persistent state."""
    return _xdg_dir("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP_NAME


def cache_dir() -> Path:
    """Return the directory for cache and lock files."""
    return _xdg_dir("XDG_CACHE_HOME", Path.home() / ".cache") / APP_NAME


def data_dir() -> Path:
    """Return the filesystem path of the bundled ``data`` package."""
    return Path(str(resources.files("linguafix") / "data"))


def _round_float(value: float, digits: int = 6) -> float:
    """Round ``value`` for storage to shed binary representation noise.

    A float from a GUI slider can arrive as ``0.7000000000000001``; writing that
    back to ``config.toml`` is ugly and unstable. Rounding is applied *before*
    validation so the stored value is exactly what the bound check saw.
    """
    return round(value, digits)


def _normalise_categories(values: object) -> list[str]:
    """Coerce ``installed_dict_categories`` to a de-duplicated slug list.

    Slugs are lower-cased and trimmed; ``base`` is always present so the general
    frequency list is never accidentally disabled. Order is preserved so the
    user's listing stays stable.
    """
    if isinstance(values, str):
        raw_items: list[object] = [values]
    elif isinstance(values, (list, tuple)):
        raw_items = list(values)
    else:
        raw_items = []
    categories: list[str] = []
    for item in raw_items:
        slug = str(item).strip().lower()
        if slug and slug not in categories:
            categories.append(slug)
    if "base" not in categories:
        categories.insert(0, "base")
    return categories


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
    analysis_timeout_adaptive: bool = DEFAULT_ANALYSIS_TIMEOUT_ADAPTIVE
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
    # Manual reverse conversion: force the last word (even a correct one) into
    # the other layout, e.g. ``привет`` -> ``ghbdtn``. No detector involved.
    hotkey_toggle_layout_last_word: str = DEFAULT_TOGGLE_LAYOUT_HOTKEY
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
    password_guard: bool = True
    plausibility_floor: float = DEFAULT_PLAUSIBILITY_FLOOR
    max_consecutive_consonants: int = DEFAULT_MAX_CONSECUTIVE_CONSONANTS
    min_vowel_ratio: float = DEFAULT_MIN_VOWEL_RATIO
    custom_skip_regex: str = ""
    exceptions_apps: list[str] = field(default_factory=lambda: list(DEFAULT_EXCEPTION_APPS))
    exceptions_force_in_manual: list[str] = field(default_factory=list)
    dictionary_size: int = DEFAULT_DICTIONARY_SIZE
    dictionary_custom_path: str = ""
    # Optional directory of extended dictionaries, one ``<lang>.txt`` per
    # language. Words from these files are added to the detector's vocabulary
    # (membership only, so n-gram scoring is unchanged), raising recall for
    # languages without a big bundled corpus. Empty by default: nothing is
    # loaded unless the user runs ``linguafix dict download``/``import-file``.
    extended_dictionary_dir: str = ""
    # Thematic (professional) dictionary categories the user has installed with
    # ``linguafix dict install <category>``. ``base`` is the general frequency
    # list shipped in the package; extra slugs add a domain vocabulary on top of
    # it. Only category slugs are stored here -- never any typed text.
    installed_dict_categories: list[str] = field(default_factory=lambda: ["base"])
    history_size: int = DEFAULT_HISTORY_SIZE
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "08:00"

    # --- Task F: T9 typo correction ----------------------------------------
    # ``typo_mode`` is the source of truth (auto/manual/hybrid/off).
    # ``typo_correction`` is the legacy on/off boolean: it is kept in sync as
    # ``typo_mode != "off"`` so old configs, the CLI and any external reader
    # keep working. New code must read ``typo_mode``.
    typo_mode: str = DEFAULT_TYPO_MODE
    typo_correction: bool = False
    typo_max_distance: int = DEFAULT_TYPO_MAX_DISTANCE
    typo_min_word_length: int = DEFAULT_TYPO_MIN_WORD_LENGTH
    typo_max_distance_long: int = DEFAULT_TYPO_MAX_DISTANCE_LONG
    typo_long_word_threshold: int = DEFAULT_TYPO_LONG_WORD_THRESHOLD
    typo_top1_ratio_strict: float = DEFAULT_TYPO_TOP1_RATIO_STRICT
    typo_debounce_seconds: float = DEFAULT_TYPO_DEBOUNCE_SECONDS
    typo_hotkey: str = DEFAULT_TYPO_HOTKEY

    # --- punctuation cleanup ----------------------------------------------
    # Same pattern as T9: ``punctuation_mode`` is authoritative and
    # ``punctuation_correction`` mirrors ``punctuation_mode != "off"``.
    punctuation_mode: str = DEFAULT_PUNCTUATION_MODE
    punctuation_correction: bool = False
    punctuation_hotkey: str = DEFAULT_PUNCTUATION_HOTKEY
    punctuation_dashes: bool = DEFAULT_PUNCTUATION_DASHES
    punctuation_ellipsis: bool = DEFAULT_PUNCTUATION_ELLIPSIS
    punctuation_smart_quotes: bool = DEFAULT_PUNCTUATION_SMART_QUOTES
    punctuation_fix_spacing: bool = DEFAULT_PUNCTUATION_FIX_SPACING

    # --- Stage 7: text expansion (snippets) --------------------------------
    text_expander_enabled: bool = False
    text_expander_snippets_path: str = ""

    # --- Stage 8: selection fix --------------------------------------------
    selection_fix_enabled: bool = True
    selection_fix_hotkey: str = "CTRL+SHIFT+L"

    # --- Stage 9: per-app default layout -----------------------------------
    # Maps an application name (as reported by app_focus) to the layout that
    # should be active when it gains focus, e.g. {"kitty": "ru"}.
    app_layouts: dict[str, str] = field(default_factory=dict)
    app_layout_switch: bool = False

    # --- Stage 13: opt-in update check -------------------------------------
    # The only feature that uses the network; off by default.
    update_check_enabled: bool = False

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Normalise and validate field values in place.

        Raises:
            ValueError: If a value cannot be coerced into a valid one.
        """
        self.analysis_timeout = _round_float(float(self.analysis_timeout))
        if self.analysis_timeout <= 0:
            raise ValueError("analysis_timeout must be positive")
        self.analysis_timeout_adaptive = bool(self.analysis_timeout_adaptive)

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
        # An old install could carry the pre-0.2.8 undo default ``CTRL+CTRL``
        # (a leftover, not a deliberate binding — no key map uses it for undo).
        # Migrate it to ``SHIFT+BACKSPACE`` and say so once, so the log explains
        # why the hotkey changed. A deliberate choice of any other value stands.
        if self.hotkey_undo_last_fix == LEGACY_UNDO_HOTKEY:
            logger.info(
                "Migrating hotkey_undo_last_fix %s -> %s (old default)",
                LEGACY_UNDO_HOTKEY,
                DEFAULT_UNDO_HOTKEY,
            )
            self.hotkey_undo_last_fix = DEFAULT_UNDO_HOTKEY
        self.hotkey_toggle_mode = normalise_hotkey(self.hotkey_toggle_mode)
        self.hotkey_reload_config = normalise_hotkey(self.hotkey_reload_config)
        self.hotkey_toggle_layout_last_word = normalise_hotkey(self.hotkey_toggle_layout_last_word)

        self.hotkey_double_tap_ms = int(self.hotkey_double_tap_ms)
        # The pre-0.2.8 default of 300 ms is too short to reliably catch a
        # deliberate double tap; a config still on it migrates to the wider
        # default. Any other value is a deliberate choice and is kept.
        if self.hotkey_double_tap_ms == LEGACY_DOUBLE_TAP_MS:
            logger.info(
                "Migrating hotkey_double_tap_ms %d -> %d (old default)",
                LEGACY_DOUBLE_TAP_MS,
                DEFAULT_DOUBLE_TAP_MS,
            )
            self.hotkey_double_tap_ms = DEFAULT_DOUBLE_TAP_MS
        if not MIN_DOUBLE_TAP_MS <= self.hotkey_double_tap_ms <= MAX_DOUBLE_TAP_MS:
            raise ValueError(
                f"hotkey_double_tap_ms must be between {MIN_DOUBLE_TAP_MS} and {MAX_DOUBLE_TAP_MS}"
            )

        self.undo_window_seconds = int(self.undo_window_seconds)
        if not 3 <= self.undo_window_seconds <= 60:
            raise ValueError("undo_window_seconds must be between 3 and 60")
        self.undo_history_depth = int(self.undo_history_depth)
        if not 1 <= self.undo_history_depth <= 10:
            raise ValueError("undo_history_depth must be between 1 and 10")

        # --- detector / context / exceptions / dictionaries ----------------
        self.confidence_threshold = _round_float(float(self.confidence_threshold))
        if not 0.5 <= self.confidence_threshold <= 0.95:
            raise ValueError("confidence_threshold must be between 0.5 and 0.95")
        self.context_analysis = bool(self.context_analysis)
        self.context_weight = _round_float(float(self.context_weight))
        if not 0.0 <= self.context_weight <= 1.0:
            raise ValueError("context_weight must be between 0 and 1")
        self.ignore_all_caps = bool(self.ignore_all_caps)
        self.ignore_with_digits = bool(self.ignore_with_digits)
        self.ignore_emails_urls = bool(self.ignore_emails_urls)
        self.plausibility_check = bool(self.plausibility_check)
        self.structural_boundaries = bool(self.structural_boundaries)
        self.identifier_guard = bool(self.identifier_guard)
        self.password_guard = bool(self.password_guard)
        self.plausibility_floor = _round_float(float(self.plausibility_floor))
        self.max_consecutive_consonants = int(self.max_consecutive_consonants)
        if self.max_consecutive_consonants < 2:
            raise ValueError("max_consecutive_consonants must be >= 2")
        self.min_vowel_ratio = _round_float(float(self.min_vowel_ratio))
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
        # ``gedit`` was dropped from the default exception list in 0.2.8: it is
        # not installed on Debian 13 / GNOME 48, where GNOME Text Editor
        # (``org.gnome.TextEditor`` -> ``texteditor``) took its place. A config
        # still carrying the old default entry is upgraded, so the text editor
        # is actually excepted; an entry the user added on top of the default is
        # kept.
        if "gedit" in self.exceptions_apps and "texteditor" not in self.exceptions_apps:
            logger.info("Migrating exceptions_apps: gedit -> texteditor")
            self.exceptions_apps = [
                "texteditor" if app == "gedit" else app for app in self.exceptions_apps
            ]
        self.exceptions_force_in_manual = [
            str(app).strip() for app in self.exceptions_force_in_manual if str(app).strip()
        ]

        self.dictionary_size = int(self.dictionary_size)
        if self.dictionary_size not in VALID_DICTIONARY_SIZES:
            raise ValueError(f"dictionary_size must be one of {VALID_DICTIONARY_SIZES}")
        self.dictionary_custom_path = str(self.dictionary_custom_path)
        self.extended_dictionary_dir = str(self.extended_dictionary_dir).strip()
        self.installed_dict_categories = _normalise_categories(self.installed_dict_categories)

        self.history_size = int(self.history_size)
        if not 1 <= self.history_size <= 100:
            raise ValueError("history_size must be between 1 and 100")
        self.quiet_hours_enabled = bool(self.quiet_hours_enabled)
        self.quiet_hours_start = _validate_hhmm(self.quiet_hours_start, "quiet_hours_start")
        self.quiet_hours_end = _validate_hhmm(self.quiet_hours_end, "quiet_hours_end")

        # --- T9 typo correction --------------------------------------------
        self.typo_mode = str(self.typo_mode).lower()
        if self.typo_mode not in VALID_FEATURE_MODES:
            raise ValueError(f"typo_mode must be one of {VALID_FEATURE_MODES}")
        # ``typo_mode`` is authoritative; the legacy boolean is derived from it
        # so the rest of the code may read either field. When a caller sets only
        # the legacy boolean (``Config(typo_correction=True)``, or the GUI
        # toggling it), the mode is reconstructed from the global mode so the
        # setting still takes effect. Legacy files are handled in
        # :meth:`from_dict`, before validation.
        if self.typo_correction and self.typo_mode == "off":
            self.typo_mode = _derive_feature_mode(True, self.mode)
        self.typo_correction = self.typo_mode != "off"
        self.typo_hotkey = normalise_hotkey(self.typo_hotkey)
        self.typo_max_distance = int(self.typo_max_distance)
        if self.typo_max_distance not in (1, 2):
            raise ValueError("typo_max_distance must be 1 or 2")
        self.typo_min_word_length = int(self.typo_min_word_length)
        if self.typo_min_word_length < 3:
            raise ValueError("typo_min_word_length must be >= 3")
        self.typo_max_distance_long = int(self.typo_max_distance_long)
        if self.typo_max_distance_long not in (1, 2):
            raise ValueError("typo_max_distance_long must be 1 or 2")
        self.typo_long_word_threshold = int(self.typo_long_word_threshold)
        if self.typo_long_word_threshold < self.typo_min_word_length:
            raise ValueError("typo_long_word_threshold must be >= typo_min_word_length")
        self.typo_top1_ratio_strict = _round_float(float(self.typo_top1_ratio_strict))
        if self.typo_top1_ratio_strict < 1.0:
            raise ValueError("typo_top1_ratio_strict must be >= 1.0")
        self.typo_debounce_seconds = _round_float(float(self.typo_debounce_seconds))
        if self.typo_debounce_seconds < 0:
            raise ValueError("typo_debounce_seconds must be >= 0")

        # --- punctuation cleanup -------------------------------------------
        self.punctuation_mode = str(self.punctuation_mode).lower()
        if self.punctuation_mode not in VALID_FEATURE_MODES:
            raise ValueError(f"punctuation_mode must be one of {VALID_FEATURE_MODES}")
        # Mirror of the T9 reconciliation above: ``punctuation_mode`` is
        # authoritative and the legacy boolean follows it.
        if self.punctuation_correction and self.punctuation_mode == "off":
            self.punctuation_mode = _derive_feature_mode(True, self.mode)
        self.punctuation_correction = self.punctuation_mode != "off"
        self.punctuation_hotkey = normalise_hotkey(self.punctuation_hotkey)
        self.punctuation_dashes = bool(self.punctuation_dashes)
        self.punctuation_ellipsis = bool(self.punctuation_ellipsis)
        self.punctuation_smart_quotes = bool(self.punctuation_smart_quotes)
        self.punctuation_fix_spacing = bool(self.punctuation_fix_spacing)

        # --- Stage 7: text expansion ---------------------------------------
        self.text_expander_enabled = bool(self.text_expander_enabled)
        self.text_expander_snippets_path = str(self.text_expander_snippets_path)

        # --- Stage 8: selection fix ----------------------------------------
        self.selection_fix_enabled = bool(self.selection_fix_enabled)
        self.selection_fix_hotkey = str(self.selection_fix_hotkey).upper()

        # --- Stage 9: per-app default layout -------------------------------
        self.app_layouts = {
            str(app).strip().lower(): str(layout).strip().lower()
            for app, layout in (self.app_layouts or {}).items()
            if str(app).strip() and str(layout).strip()
        }
        self.app_layout_switch = bool(self.app_layout_switch)

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
        flat = _flatten_sections(data)
        for key, value in flat.items():
            if key in known:
                filtered[key] = value
                continue
            # A section prefix may not fit every key (``[notifications]
            # sound_on_fix``): fall back to the bare key when it is a field.
            for prefix in ("hotkey_", "undo_", "notify_", "log_", "exceptions_", "dictionary_"):
                if key.startswith(prefix) and key[len(prefix) :] in known:
                    filtered[key[len(prefix) :]] = value
                    break
        cls._migrate_feature_modes(flat, filtered)
        try:
            return cls(**filtered)
        except (TypeError, ValueError) as exc:
            # One bad value must not reset the whole file. Drop only the keys
            # that fail validation and keep the rest, so a hand-edited typo (or
            # a value from a newer version) cannot silently wipe the user's
            # settings back to defaults.
            logger.warning("Invalid configuration value (%s); dropping invalid keys", exc)
            return cls(**cls._drop_invalid(filtered))

    @classmethod
    def _migrate_feature_modes(cls, flat: dict[str, Any], filtered: dict[str, Any]) -> None:
        """Derive the per-feature modes from a legacy config's booleans.

        A file written before the independent modes has ``typo_correction``
        (and/or ``punctuation_correction``) but no ``*_mode``. The mode is
        derived so the previous behaviour is preserved:

        * the boolean off -> the feature's mode is ``off``;
        * the boolean on and the global ``mode`` is ``manual`` -> the feature's
          mode is ``manual`` (hotkey-only, matching the old opt-in);
        * the boolean on otherwise -> the feature's mode equals the global
          ``mode``.

        An explicit ``*_mode`` in the file always wins, so re-reading a file the
        new code wrote is a no-op.
        """
        global_mode = str(flat.get("mode", "auto")).lower()
        if global_mode not in VALID_MODES:
            global_mode = "auto"
        for feature in ("typo", "punctuation"):
            if f"{feature}_mode" in filtered:
                continue
            if f"{feature}_correction" not in filtered:
                continue
            filtered[f"{feature}_mode"] = _derive_feature_mode(
                bool(filtered[f"{feature}_correction"]), global_mode
            )

    @classmethod
    def _drop_invalid(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Return ``values`` with the keys that fail validation removed.

        Each dropped key is logged by name, so a setting that silently reverts
        to its default (``typo_correction = false`` after a hand edit) can be
        traced to the exact offending value.
        """
        subset = dict(values)
        while subset:
            try:
                cls(**subset)
                break
            except (TypeError, ValueError):
                removed = False
                for key in list(subset):
                    trial = {k: v for k, v in subset.items() if k != key}
                    try:
                        cls(**trial)
                    except (TypeError, ValueError):
                        continue
                    logger.warning(
                        "Dropping invalid configuration key %r (value %r); keeping the rest",
                        key,
                        subset[key],
                    )
                    del subset[key]
                    removed = True
                    break
                if not removed:
                    # No single key is the culprit (a cross-field conflict);
                    # give up on the values rather than guess.
                    logger.warning(
                        "Configuration has a cross-field conflict; falling back to defaults"
                    )
                    return {}
        return subset

    def to_dict(self) -> dict[str, Any]:
        """Return a plain ``dict`` representation suitable for TOML dumping.

        The per-feature mode and its legacy boolean are reconciled here as well
        as in :meth:`validate`, so a config whose boolean was set directly (the
        GUI toggling ``typo_correction``) still dumps a consistent pair and
        never persists an enabled feature as ``*_mode = "off"``.
        """
        data = asdict(self)
        for feature in ("typo", "punctuation"):
            mode = data[f"{feature}_mode"]
            if bool(data[f"{feature}_correction"]) and mode == "off":
                mode = _derive_feature_mode(True, data["mode"])
            data[f"{feature}_mode"] = mode
            data[f"{feature}_correction"] = mode != "off"
        return data


def _write_default(path: Path, config: Config) -> None:
    """Write ``config`` to ``path`` atomically, creating parent directories.

    A temporary file in the same directory is written first and then
    ``os.replace``d over the target, so a crash or a full disk can never leave a
    half-written config behind (which ``load_config`` would then treat as
    corrupt and back up).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = tomli_w.dumps(config.to_dict())
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _migrations_for(data: dict[str, Any], config: Config) -> list[tuple[str, Any, Any]]:
    """Return ``(field, old, new)`` for every value a load migrated.

    A field is compared in its *flattened* form, the same shape
    :meth:`Config.from_dict` sees, so a value grouped under ``[hotkeys]`` or
    written as a section-prefixed key is recognised. A field the file does not
    mention is a default (not a migration) and is skipped, which keeps a
    hand-written config from being rewritten just because it omits fields.
    """
    flat = _flatten_sections(data)
    changes: list[tuple[str, Any, Any]] = []
    for key, value in config.to_dict().items():
        if key not in flat:
            # A missing independent-mode key that the load derived from a legacy
            # boolean is a migration worth persisting, even though the file
            # never mentioned it.
            if key in ("typo_mode", "punctuation_mode"):
                feature = key.removesuffix("_mode")
                if f"{feature}_correction" in flat:
                    changes.append((key, "(derived)", value))
            continue
        old = flat[key]
        if old != value:
            changes.append((key, old, value))
    return changes


def _migrate_to_file(target: Path, raw: dict[str, Any], config: Config) -> None:
    """Rewrite ``target`` when loading ``raw`` changed any field value.

    Migrations (legacy hotkey defaults, ``analysis_timeout`` rounding, the
    ``gedit`` -> ``texteditor`` exception) are applied in memory by
    :meth:`Config.validate`. Without this the file keeps the old values, so
    ``linguafix config show`` and the next start both see stale settings while
    the running daemon uses the migrated ones — the reported bug.
    """
    changes = _migrations_for(raw, config)
    if not changes:
        return
    try:
        _write_default(target, config)
    except OSError:
        logger.warning("Could not persist migrated configuration to %s", target, exc_info=True)
        return
    logger.info(
        "Config: migrated and saved to %s: %s",
        target,
        ", ".join(f"{field} {old!r} -> {new!r}" for field, old, new in sorted(changes)),
    )


def load_config(path: Path | None = None, *, persist_migrations: bool = True) -> Config:
    """Load the configuration, creating a default file when missing.

    A corrupted file is moved aside (``config.toml.corrupt-<timestamp>``) and
    defaults are returned instead of raising.

    When a value is migrated in memory (a legacy default replaced, a float
    rounded), the migrated config is written back to ``path`` so the file and
    the running daemon never disagree (``config show`` reads the file).

    Args:
        path: Optional explicit path, defaults to :func:`config_path`.
        persist_migrations: Write the migrated config back to disk. ``False``
            is for callers that must not touch the file (the ``config migrate
            --dry-run`` preview and tests that inspect migration in memory).

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

    config = Config.from_dict(data)
    if persist_migrations:
        _migrate_to_file(target, data, config)
    return config


def preview_migrations(path: Path | None = None) -> list[tuple[str, Any, Any]]:
    """Return ``(field, old, new)`` for every value a load would migrate.

    Reads the file and applies migrations in memory without writing anything,
    so ``linguafix config migrate --dry-run`` can show exactly what a real load
    would save.
    """
    target = path or config_path()
    if not target.exists():
        return []
    try:
        data = tomllib.loads(target.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []
    return _migrations_for(data, Config.from_dict(data))


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
