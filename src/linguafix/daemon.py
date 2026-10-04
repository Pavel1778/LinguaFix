"""The LinguaFix background daemon.

The daemon listens to raw keyboard events from ``/dev/input/event*`` devices and
tracks the word currently being typed as a sequence of *physical keys*
(evdev scancodes), together with the characters those keys produced. When the
user presses a word boundary — Space or Enter by default — the word is analysed
immediately; when it was typed in the wrong layout it is rewritten and the
layout is switched.

Tracking physical keys instead of a free-form string is what makes the
replacement reliable: the number of Backspaces always equals the number of keys
the user actually pressed, so the deletion cannot drift from what is on screen
even when the user types very fast. A character buffer can desynchronise from
the screen (a key the daemon did not process in time) and leave a stray first
character behind, the ``рhello`` symptom.

The main loop uses :mod:`selectors` rather than a blocking ``read_loop`` so it
can observe the idle fallback timeout, handle signals and serve several
keyboards at once without spawning a thread per device.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import logging
import os
import re
import selectors
import signal
import subprocess
import threading
import time
import traceback
from typing import TYPE_CHECKING, Final

from .config import Config, cache_dir
from .converter import LayoutConverter
from .detector import LanguageDetector
from .dictionary import load_user_dictionary
from .injector import TextInjector
from .switcher import LayoutSwitcher
from .tray import TrayIcon

if TYPE_CHECKING:  # pragma: no cover - import used only for typing
    from evdev import InputDevice

logger = logging.getLogger(__name__)

LOCK_FILE_NAME: Final[str] = "daemon.lock"
SELECT_TIMEOUT: Final[float] = 0.25
NOTIFY_TIMEOUT: Final[float] = 3.0
# Pause between keyboard re-discovery attempts after the last device vanished.
DEVICE_RESCAN_DELAY: Final[float] = 2.0

# evdev key name -> (unshifted US character, shifted US character).
_US_KEY_NAMES: Final[dict[str, tuple[str, str]]] = {
    "KEY_GRAVE": ("`", "~"),
    "KEY_1": ("1", "!"),
    "KEY_2": ("2", "@"),
    "KEY_3": ("3", "#"),
    "KEY_4": ("4", "$"),
    "KEY_5": ("5", "%"),
    "KEY_6": ("6", "^"),
    "KEY_7": ("7", "&"),
    "KEY_8": ("8", "*"),
    "KEY_9": ("9", "("),
    "KEY_0": ("0", ")"),
    "KEY_MINUS": ("-", "_"),
    "KEY_EQUAL": ("=", "+"),
    "KEY_Q": ("q", "Q"),
    "KEY_W": ("w", "W"),
    "KEY_E": ("e", "E"),
    "KEY_R": ("r", "R"),
    "KEY_T": ("t", "T"),
    "KEY_Y": ("y", "Y"),
    "KEY_U": ("u", "U"),
    "KEY_I": ("i", "I"),
    "KEY_O": ("o", "O"),
    "KEY_P": ("p", "P"),
    "KEY_LEFTBRACE": ("[", "{"),
    "KEY_RIGHTBRACE": ("]", "}"),
    "KEY_BACKSLASH": ("\\", "|"),
    "KEY_A": ("a", "A"),
    "KEY_S": ("s", "S"),
    "KEY_D": ("d", "D"),
    "KEY_F": ("f", "F"),
    "KEY_G": ("g", "G"),
    "KEY_H": ("h", "H"),
    "KEY_J": ("j", "J"),
    "KEY_K": ("k", "K"),
    "KEY_L": ("l", "L"),
    "KEY_SEMICOLON": (";", ":"),
    "KEY_APOSTROPHE": ("'", '"'),
    "KEY_Z": ("z", "Z"),
    "KEY_X": ("x", "X"),
    "KEY_C": ("c", "C"),
    "KEY_V": ("v", "V"),
    "KEY_B": ("b", "B"),
    "KEY_N": ("n", "N"),
    "KEY_M": ("m", "M"),
    "KEY_COMMA": (",", "<"),
    "KEY_DOT": (".", ">"),
    "KEY_SLASH": ("/", "?"),
    "KEY_SPACE": (" ", " "),
}

# A word character followed by a separator and another word character marks the
# buffer as part of a larger token (URL, e-mail, path, file name, version or
# hyphenated identifier) that must never be rewritten, however implausible the
# detector finds it. The separators are the ones that join sub-tokens in
# practice; a trailing punctuation mark is not included, so a word the user
# ended with "." can still be corrected.
_INTERNAL_SEPARATOR_RE: Final[re.Pattern[str]] = re.compile(r"\w[.@/\\:_-]\w")

# Keys that terminate the current buffer and are driven by config flags.
_ENTER_KEYS: Final[frozenset[str]] = frozenset({"KEY_ENTER", "KEY_KPENTER"})
_TAB_KEYS: Final[frozenset[str]] = frozenset({"KEY_TAB"})
# Caps Lock is tracked as a shift-like key (it produces capitals) but is not a
# double-tap modifier: it latches, so there is no press/release "tap".
_SHIFT_KEYS: Final[frozenset[str]] = frozenset({"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"})

# Physical modifier keys mapped to a canonical family. A hotkey like
# ``CTRL+SHIFT+F12`` matches when exactly these families are held.
_MODIFIER_FAMILIES: Final[dict[str, str]] = {
    "KEY_LEFTCTRL": "ctrl",
    "KEY_RIGHTCTRL": "ctrl",
    "KEY_LEFTALT": "alt",
    "KEY_RIGHTALT": "alt",
    "KEY_LEFTSHIFT": "shift",
    "KEY_RIGHTSHIFT": "shift",
    "KEY_LEFTMETA": "super",
    "KEY_RIGHTMETA": "super",
}
# Config-side modifier spellings accepted in a hotkey string.
_MODIFIER_ALIASES: Final[dict[str, str]] = {
    "CTRL": "ctrl",
    "CONTROL": "ctrl",
    "ALT": "alt",
    "SHIFT": "shift",
    "SUPER": "super",
    "WIN": "super",
    "META": "super",
}
# Cycle order used by the ``toggle_mode`` hotkey.
_MODE_CYCLE: Final[tuple[str, ...]] = ("auto", "hybrid", "manual")
# Modifier families that may be used as a double-tap hotkey. ``SHIFT+SHIFT``
# means "tap the shift family twice within ``hotkey_double_tap_ms``"; it works
# on every keyboard, unlike the old ``PAUSE`` default.
_DOUBLE_TAP_MODIFIERS: Final[frozenset[str]] = frozenset({"shift", "ctrl", "alt"})
# Keys that carry no printable character but that we must not treat as a
# continuation of the current word either (arrow keys, Delete, Home, …). A key
# in this set ends the word without flushing it.
_WORD_BREAKERS: Final[frozenset[str]] = frozenset(
    {
        "KEY_UP",
        "KEY_DOWN",
        "KEY_LEFT",
        "KEY_RIGHT",
        "KEY_HOME",
        "KEY_END",
        "KEY_PAGEUP",
        "KEY_PAGEDOWN",
        "KEY_DELETE",
        "KEY_INSERT",
        "KEY_ESC",
    }
)


def _compile_skip_regex(pattern: str) -> re.Pattern[str] | None:
    """Compile the user's skip regex, ignoring an invalid one with a warning."""
    if not pattern.strip():
        return None
    try:
        return re.compile(pattern)
    except re.error:
        logger.warning("Invalid custom_skip_regex; ignoring it")
        return None


def _load_ecodes() -> tuple[dict[int, tuple[str, str]], dict[str, int]]:
    """Build keycode lookup tables from evdev, tolerating a missing evdev."""
    try:
        import evdev
    except ImportError:  # pragma: no cover - evdev is a runtime dependency
        return {}, {}
    code_to_pair: dict[int, tuple[str, str]] = {}
    name_to_code: dict[str, int] = {}
    for name, pair in _US_KEY_NAMES.items():
        code = getattr(evdev.ecodes, name, None)
        if code is not None:
            code_to_pair[int(code)] = pair
            name_to_code[name] = int(code)
    return code_to_pair, name_to_code


class LinguaFixDaemon:
    """Read keyboard events, detect wrong layouts and fix the typed text.

    Args:
        config: Runtime configuration.
        detector: Optional detector override (mainly for tests).
        switcher: Optional layout switcher override.
        injector: Optional text injector override.
        devices: Optional iterable of already-open input devices. When omitted
            the daemon discovers keyboards on its own.
    """

    def __init__(
        self,
        config: Config,
        *,
        detector: LanguageDetector | None = None,
        switcher: LayoutSwitcher | None = None,
        injector: TextInjector | None = None,
        devices: list[InputDevice] | None = None,  # type: ignore[type-arg]
        dry_run: bool = False,
    ) -> None:
        self.config = config
        self.dry_run = dry_run
        self.converter = LayoutConverter()
        self.detector = detector or LanguageDetector(
            converter=self.converter,
            stop_words=config.stop_words,
            min_word_length=config.min_word_length,
            confidence_threshold=config.confidence_threshold,
            languages=tuple(config.languages),
            plausibility_check=config.plausibility_check,
            structural_boundaries=config.structural_boundaries,
            identifier_guard=config.identifier_guard,
            plausibility_floor=config.plausibility_floor,
            max_consecutive_consonants=config.max_consecutive_consonants,
            min_vowel_ratio=config.min_vowel_ratio,
        )
        self.switcher = switcher or LayoutSwitcher(
            layouts=config.layouts,
            switch_method=config.switch_method,
        )
        self.injector = injector or TextInjector(
            converter=self.converter,
            backend=config.backend,
            settle_ms=config.backspace_settle_ms,
        )
        self._devices = devices
        self._code_to_pair, self._name_to_code = _load_ecodes()
        self._hotkeys: dict[str, tuple[frozenset[str], int] | None] = {
            "fix": self._parse_hotkey(config.hotkey_fix_last_word),
            "undo": self._parse_hotkey(config.hotkey_undo_last_fix),
            "toggle_mode": self._parse_hotkey(config.hotkey_toggle_mode),
            "reload": self._parse_hotkey(config.hotkey_reload_config),
        }
        # Modifier families currently held down, used to match hotkeys.
        self._held_modifiers: set[str] = set()
        # Double-tap hotkeys (``SHIFT+SHIFT`` -> ``fix``): modifier family to
        # action. They are matched separately because a modifier key never
        # reaches the single-key matcher above.
        self._double_tap_hotkeys: dict[str, str] = self._build_double_tap_hotkeys(config)
        # Time of the last tap of each modifier family, for double-tap detection.
        self._last_modifier_tap: dict[str, float] = {}
        # Successful fixes eligible for undo: (monotonic time, original text,
        # original layout, backspace count).
        self._undo_history: list[tuple[float, str, str, int]] = []
        # Task E: skip rules and the user dictionary.
        self._skip_regex = _compile_skip_regex(config.custom_skip_regex)
        self._excepted_apps = {app.lower() for app in config.exceptions_apps}
        self._last_word: str = ""
        self.detector.set_context_weight(config.context_weight if config.context_analysis else 0.0)
        self.detector.set_dictionary_size(config.dictionary_size)
        user_words = load_user_dictionary(config.dictionary_custom_path)
        if user_words:
            self.detector.set_user_words(user_words)

        # The characters currently on screen for the word being typed. Derived
        # from ``_scancodes`` and kept in step with it (one char per printable
        # key). Kept as the detector's input; the scancode list is the source of
        # truth for how many Backspaces a fix must send.
        self.buffer: str = ""
        # The physical keys (evdev codes) that produced ``buffer``.
        self._scancodes: list[int] = []
        self.last_key_time: float = 0.0
        self._shift = False
        self._running = False
        self._reload_requested = False
        self._shutdown_requested = False
        self._undo_requested = False
        self._lock_handle: object | None = None
        self._tray: TrayIcon | None = None
        # Guards ``buffer``/``last_key_time``/``_shift`` against the tray thread,
        # which may call ``_process_buffer`` (via ``_tray_fix``) concurrently with
        # the event loop. ``_lock`` serialises buffer processing so the same text
        # is never corrected twice.
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------
    def discover_devices(self) -> list[InputDevice]:  # type: ignore[type-arg]
        """Return a list of keyboard-like input devices.

        Devices are considered keyboards when they expose letter keys. The
        daemon's own virtual ``uinput`` device is skipped to avoid feedback
        loops.
        """
        try:
            import evdev
        except ImportError:  # pragma: no cover
            logger.error("evdev is not installed; cannot read keyboard events")
            return []

        found: list[InputDevice] = []  # type: ignore[type-arg]
        letter_codes = {self._name_to_code.get(name) for name in ("KEY_A", "KEY_Z", "KEY_Q")}
        for path in evdev.list_devices():
            try:
                device = evdev.InputDevice(path)
            except (OSError, PermissionError) as exc:
                logger.debug("Cannot open %s: %s", path, exc)
                continue
            name = (device.name or "").lower()
            if "linguafix" in name or "uinput" in name:
                device.close()
                continue
            capabilities = device.capabilities().get(evdev.ecodes.EV_KEY, [])
            if letter_codes.intersection(int(code) for code in capabilities):
                found.append(device)
                logger.info("Using keyboard device: %s (%s)", device.path, device.name)
            else:
                device.close()
        return found

    # ------------------------------------------------------------------
    # Single instance handling
    # ------------------------------------------------------------------
    def acquire_lock(self) -> bool:
        """Try to acquire the single-instance lock.

        Returns:
            ``True`` when the lock was acquired, ``False`` when another daemon
            instance already holds it.
        """
        directory = cache_dir()
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = directory / LOCK_FILE_NAME
        try:
            # Open without truncating and take the lock first: truncating before
            # the flock would wipe the PID of the instance that already holds it.
            handle = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115 - kept open
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
        except OSError as exc:
            logger.error("Another LinguaFix instance is already running (%s)", exc)
            return False
        self._lock_handle = handle
        return True

    def release_lock(self) -> None:
        """Release the single-instance lock if held.

        The lock file is also removed, but only while it still names this
        process: if a new daemon already acquired the lock and rewrote the file,
        deleting it would break that instance.
        """
        handle = self._lock_handle
        if handle is None:
            return
        pid = str(os.getpid())
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
            handle.close()  # type: ignore[attr-defined]
        except OSError:
            logger.debug("Could not release lock cleanly", exc_info=True)
        finally:
            self._lock_handle = None
        try:
            path = cache_dir() / LOCK_FILE_NAME
            if path.read_text(encoding="utf-8").strip() == pid:
                path.unlink()
        except OSError:
            logger.debug("Could not remove lock file", exc_info=True)

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------
    def _install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT/SIGHUP handlers."""
        signal.signal(signal.SIGTERM, self._handle_stop)
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGHUP, self._handle_reload)
        if hasattr(signal, "SIGUSR1"):
            signal.signal(signal.SIGUSR1, self._handle_undo)

    def _handle_stop(self, signum: int, _frame: object) -> None:
        # Only set flags here: the handler may run between any two bytecodes, so
        # it must not call anything that allocates or locks.
        logger.info("Received signal %s; shutting down", signum)
        self._shutdown_requested = True
        self._running = False

    def _handle_reload(self, _signum: int, _frame: object) -> None:
        logger.info("Received SIGHUP; scheduling config reload")
        self._reload_requested = True

    def _handle_undo(self, _signum: int, _frame: object) -> None:
        # Only set a flag: the undo touches the injector and must run on the
        # event-loop thread, never inside the signal handler.
        logger.info("Received SIGUSR1; scheduling undo")
        self._undo_requested = True

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------
    def _handle_event(self, event: object) -> None:
        """Process a single evdev event, surviving any per-event failure.

        Args:
            event: An object exposing ``type``, ``code`` and ``value`` attributes.
        """
        try:
            self._handle_event_inner(event)
        except Exception as exc:  # the daemon must survive any per-event failure
            with self._lock:
                sensitive = self.buffer.strip()
            self._log_sanitized("Failed to handle a key event", exc, sensitive)

    def _handle_event_inner(self, event: object) -> None:
        """Inner implementation of :meth:`_handle_event`."""
        try:
            import evdev
        except ImportError:  # pragma: no cover
            return

        if getattr(event, "type", None) != evdev.ecodes.EV_KEY:
            return

        code = int(getattr(event, "code", -1))
        value = int(getattr(event, "value", 0))
        name = self._code_to_name(code)

        if name in _SHIFT_KEYS:
            # Shift both produces capitals and may be the fix hotkey (a double
            # tap of the same modifier), so it is handled by the modifier path.
            self._handle_modifier(name, value)
            with self._lock:
                self._shift = value in (1, 2)
            return

        # Track modifier state for hotkey matching (press and release), and
        # detect a double tap of the same modifier (the fix hotkey default).
        if name in _MODIFIER_FAMILIES:
            self._handle_modifier(name, value)
            return

        if value != 0:
            # A real key was pressed between two modifier taps, so the modifier
            # was part of a chord or a capital letter, not a double-tap hotkey.
            self._last_modifier_tap.clear()

        if value == 0:  # key release
            return

        if self.config.hotkeys_enabled and value == 1:
            action = self._match_hotkey(code)
            if action is not None:
                self._run_hotkey(action)
                return

        if value == 2:  # auto-repeat: only backspace repeats meaningfully
            if name == "KEY_BACKSPACE":
                self._handle_backspace()
            return

        if name == "KEY_BACKSPACE":
            self._handle_backspace()
            return

        if name in _WORD_BREAKERS:
            # A navigation key ends the current word without a correction: the
            # caret is about to move, so a rewrite would target the wrong text.
            self._reset_buffer()
            return

        if name == "KEY_SPACE":
            if self.config.on_space:
                self._process_buffer(boundary=True)
            else:
                self._reset_buffer()
            return

        if name in _ENTER_KEYS:
            if self.config.on_enter:
                self._process_buffer(boundary=True)
            else:
                self._reset_buffer()
            return

        if name in _TAB_KEYS:
            if self.config.on_tab:
                self._process_buffer(boundary=True)
            else:
                self._reset_buffer()
            return

        char = self._key_to_char(code)
        if char is None:
            return

        if self.config.on_punctuation and char in self.config.punctuation_chars:
            # A punctuation boundary ends the word. The character itself is not
            # buffered: it is not part of the word and must not be deleted.
            self._process_buffer(boundary=True)
            return

        with self._lock:
            self.buffer += char
            self._scancodes.append(code)
            self.last_key_time = time.time()
            overflow = len(self._scancodes) > self.config.max_buffer_size
        # A held key (auto-repeat) or a paste-like burst can grow the buffer
        # without bound; analyse and clear it instead of waiting for the idle
        # timeout so memory stays bounded.
        if overflow:
            logger.info("Buffer exceeded %d chars; analysing early", self.config.max_buffer_size)
            self._process_buffer()

    def _code_to_name(self, code: int) -> str:
        """Return the evdev key name for ``code`` (or an empty string)."""
        try:
            import evdev
        except ImportError:  # pragma: no cover
            return ""
        name = evdev.ecodes.KEY.get(code)
        if isinstance(name, (list, tuple)):  # some codes map to several names
            return str(name[0])
        return str(name) if name is not None else ""

    def _resolve_hotkey(self, value: str) -> int | None:
        """Return the evdev code for the key part of ``value`` (or ``None``).

        Hotkeys may use any evdev key (``F12``, ``PAUSE``, ``M``), not only the
        printable US keys tracked for typing, so the full evdev table is
        consulted as a fallback.
        """
        key = value.rsplit("+", 1)[-1] if value else ""
        if not key:
            return None
        if not key.startswith("KEY_"):
            key = f"KEY_{key}"
        code = self._name_to_code.get(key)
        if code is not None:
            return code
        try:
            import evdev
        except ImportError:  # pragma: no cover - evdev is a runtime dependency
            return None
        resolved = getattr(evdev.ecodes, key, None)
        return int(resolved) if isinstance(resolved, int) else None

    def _parse_hotkey(self, value: str) -> tuple[frozenset[str], int] | None:
        """Split a hotkey string into ``(modifier_families, key_code)``.

        A pure modifier double tap (``SHIFT+SHIFT``) has no key code and is
        handled by :meth:`_build_double_tap_hotkeys` instead, so it returns
        ``None`` here.
        """
        if not value:
            return None
        parts = [part for part in value.upper().split("+") if part]
        if not parts:
            return None
        if self._double_tap_family(value) is not None:
            return None
        code = self._resolve_hotkey(parts[-1])
        if code is None:
            return None
        families = {_MODIFIER_ALIASES[part] for part in parts[:-1] if part in _MODIFIER_ALIASES}
        return frozenset(families), code

    @staticmethod
    def _double_tap_family(value: str) -> str | None:
        """Return the modifier family for a double-tap hotkey, or ``None``.

        ``"SHIFT+SHIFT"`` (and ``"CTRL+CTRL"`` / ``"ALT+ALT"``) is a double tap
        of the same modifier. Mixed forms such as ``"SHIFT+CTRL"`` are not
        double taps and are left to the single-key matcher.
        """
        parts = [part for part in value.upper().split("+") if part]
        if len(parts) != 2 or parts[0] != parts[1]:
            return None
        family = _MODIFIER_ALIASES.get(parts[0])
        if family in _DOUBLE_TAP_MODIFIERS:
            return family
        return None

    def _build_double_tap_hotkeys(self, config: Config) -> dict[str, str]:
        """Map each configured double-tap modifier family to its action."""
        bindings: dict[str, str] = {}
        for action, value in (
            ("fix", config.hotkey_fix_last_word),
            ("undo", config.hotkey_undo_last_fix),
            ("toggle_mode", config.hotkey_toggle_mode),
            ("reload", config.hotkey_reload_config),
        ):
            family = self._double_tap_family(value)
            if family is not None:
                bindings[family] = action
        return bindings

    def _handle_modifier(self, name: str, value: int) -> None:
        """Track modifier state and fire a double-tap hotkey when matched."""
        family = _MODIFIER_FAMILIES.get(name)
        if family is None:
            return
        if value in (1, 2):
            self._held_modifiers.add(family)
        elif value == 0:
            self._held_modifiers.discard(family)

        if value != 1:
            return
        if not self.config.hotkeys_enabled:
            return

        # A tap only counts when no *other* modifier family is held. Otherwise
        # ``Ctrl`` + ``Shift`` + ``Shift`` would look like a double tap of Shift
        # and fire a fix, even though the user was forming a chord. Any other
        # held family cancels a pending tap.
        if self._held_modifiers - {family}:
            self._last_modifier_tap.clear()
            return

        action = self._double_tap_hotkeys.get(family)
        if action is None:
            # This family is not a double-tap hotkey, but pressing it is still a
            # key press and must cancel a pending tap of another family.
            self._last_modifier_tap.clear()
            return
        now = time.monotonic()
        window = self.config.hotkey_double_tap_ms / 1000.0
        last = self._last_modifier_tap.get(family)
        if last is not None and now - last <= window:
            # Consume the tap so a third press does not fire again immediately.
            self._last_modifier_tap.pop(family, None)
            logger.debug("Double tap of %s matched hotkey %s", family, action)
            self._run_hotkey(action)
        else:
            # Re-arm: replace any previously armed family so only the most
            # recent tap can complete a double tap.
            self._last_modifier_tap = {family: now}

    def _match_hotkey(self, code: int) -> str | None:
        """Return the action whose hotkey matches, or ``None``."""
        if not self.config.hotkeys_enabled:
            return None
        for action, parsed in self._hotkeys.items():
            if parsed is None:
                continue
            families, key_code = parsed
            if code == key_code and families == self._held_modifiers:
                return action
        return None

    def _should_fix_buffer(self) -> bool:
        """Return whether the current mode and per-app rules allow a fix."""
        manual = self.config.mode == "manual"
        if not manual and not self._excepted_apps:
            return True

        from .app_focus import get_active_app

        try:
            app = get_active_app()
        except Exception:
            logger.debug("Active-app probe failed", exc_info=True)
            app = None
        if app and app.lower() in self._excepted_apps:
            # The user listed the application as "never touch": skip even in
            # auto/hybrid mode.
            logger.debug("App %s is on the exception list; skipping", app)
            return False
        if manual:
            if not app:
                return False
            return app.lower() in {name.lower() for name in self.config.exceptions_force_in_manual}
        return True

    def _cycle_mode(self) -> None:
        """Advance to the next working mode and persist it."""
        try:
            index = _MODE_CYCLE.index(self.config.mode)
        except ValueError:
            index = 0
        self.config.mode = _MODE_CYCLE[(index + 1) % len(_MODE_CYCLE)]
        logger.info("Mode toggled to %s", self.config.mode)
        self._persist_config()

    def _persist_config(self) -> None:
        """Write the current configuration back to disk, best-effort."""
        try:
            from .config import save_config

            save_config(self.config)
        except Exception:
            logger.debug("Could not persist configuration", exc_info=True)

    def _run_hotkey(self, action: str) -> None:
        """Execute the action bound to a hotkey."""
        logger.info("Hotkey action: %s", action)
        if action == "fix":
            self._process_buffer(force=True)
        elif action == "undo":
            self._undo_last_fix()
        elif action == "toggle_mode":
            self._cycle_mode()
        elif action == "reload":
            self.reload_config()

    def _record_undo(self, original: str, layout: str, backspace_count: int) -> None:
        """Remember a successful fix so it can be undone shortly afterwards."""
        now = time.monotonic()
        self._undo_history.append((now, original, layout, backspace_count))
        self._undo_history = self._undo_history[-self.config.undo_history_depth :]

    def _undo_last_fix(self) -> None:
        """Re-apply the text of the most recent fix within the undo window."""
        if not self._undo_history:
            logger.info("Undo requested but nothing to undo")
            return
        now = time.monotonic()
        # Drop entries that have aged out of the undo window.
        self._undo_history = [
            entry
            for entry in self._undo_history
            if now - entry[0] <= self.config.undo_window_seconds
        ]
        if not self._undo_history:
            logger.info("Undo requested but the window has expired")
            return
        _time, original, layout, backspace_count = self._undo_history.pop()
        if self.dry_run:
            logger.info("Dry run: skipping undo")
            return
        current = self.switcher.get_current_layout()
        target = layout if layout else current
        self.switcher.switch_to(target)
        time.sleep(0.05)
        # The fixed text has the same length as the original word; deleting that
        # many characters and retyping the original restores the screen exactly.
        if not self.injector.replace_text(backspace_count, original, target):
            logger.warning("Undo failed to replace text")
            return
        logger.info("Undid the last fix")
        if self.config.notify_on_fix:
            self._notify()

    def _key_to_char(self, code: int) -> str | None:
        """Translate a keycode into the character for the active layout."""
        pair = self._code_to_pair.get(code)
        if pair is None:
            return None
        canonical = pair[1] if self._shift else pair[0]
        current = self.switcher.get_current_layout()
        layout_map = self.converter._forward.get(current)
        if layout_map is not None:
            return layout_map.get(canonical, canonical)
        return canonical

    def _handle_backspace(self) -> None:
        """Remove the last character (and its physical key) from the buffer."""
        with self._lock:
            if self.buffer:
                self.buffer = self.buffer[:-1]
            if self._scancodes:
                self._scancodes.pop()

    def _reset_buffer(self) -> None:
        """Drop the current word without analysing it."""
        with self._lock:
            self.buffer = ""
            self._scancodes = []

    def _process_buffer(self, *, force: bool = False, boundary: bool = False) -> None:
        """Analyse the buffer, never letting an error escape.

        A failure in the detector, converter, switcher or injector must not kill
        the daemon: it is logged and the loop continues.

        Args:
            force: When ``True`` the working mode is ignored (the user asked for
                the fix explicitly through a hotkey).
            boundary: When ``True`` the flush was triggered by a word-boundary
                key (Space/Enter/Tab). The daemon then waits
                ``trigger_settle_ms`` before deleting, so the boundary key is
                processed by the application first.
        """
        # Capture the text so a traceback can be scrubbed of it before logging.
        with self._lock:
            sensitive = self.buffer.strip()
        try:
            self._process_buffer_inner(force=force, boundary=boundary)
        except Exception as exc:  # the daemon must survive any failure
            self._log_sanitized("Failed to process the buffer", exc, sensitive)

    @staticmethod
    def _log_sanitized(message: str, exc: BaseException, sensitive: str) -> None:
        """Log an exception traceback with any typed text redacted.

        Standard tracebacks do not include local variables, so the only way the
        buffer can reach the log is through an exception *message* that embeds
        it. Redacting the buffer (and its stripped form) from the formatted
        traceback closes that hole while keeping the traceback for debugging.
        """
        formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        for needle in {sensitive, sensitive.strip()}:
            if needle:
                formatted = formatted.replace(needle, "<redacted>")
        logger.error("%s\n%s", message, formatted.rstrip())

    def _process_buffer_inner(self, *, force: bool = False, boundary: bool = False) -> None:
        """Analyse the current word and apply a correction when appropriate."""
        # Snapshot and clear the buffer under the lock, then release it before
        # the (slow) switch/inject so typing during a fix is never lost. Holding
        # the lock for the whole fix would stall the event loop and drop keys.
        with self._lock:
            buffer = self.buffer.strip()
            # The number of Backspaces equals the number of physical keys, not
            # the number of characters in ``buffer``: that is what keeps the
            # deletion in lock-step with the screen even under fast typing.
            backspace_count = len(self._scancodes)
            self.buffer = ""
            self._scancodes = []
        if boundary:
            logger.debug(
                "Boundary flush: trigger=%s scancodes=%d buffer_len=%d",
                "space/enter/tab",
                backspace_count,
                len(buffer),
            )
        if not buffer or len(buffer) < self.config.min_word_length:
            return

        if self.detector.is_stop_word(buffer):
            logger.debug("Buffer of length %d is a stop word; skipping", len(buffer))
            return

        # In manual mode nothing is corrected unless the user forces it (hotkey)
        # or the focused application is on the force list. Clearing the buffer
        # above means the decision never leaves stale text behind.
        if not force and not self._should_fix_buffer():
            logger.debug("Mode %s: skipping automatic correction", self.config.mode)
            return

        if self.config.ignore_all_caps and buffer.isupper():
            logger.debug("Buffer is all caps; skipping")
            return

        if self.config.ignore_with_digits and any(char.isdigit() for char in buffer):
            logger.debug("Buffer contains digits; skipping")
            return

        neighbor = self._last_word or None
        current = self.switcher.get_current_layout()
        target = self.detector.target_layout(buffer, current, neighbor)
        if target is None:
            return

        converted = self.converter.convert(buffer, current, target)
        if converted == buffer:
            return

        if self.config.ignore_emails_urls and _INTERNAL_SEPARATOR_RE.search(buffer):
            # A URL, e-mail, path, file name or hyphenated identifier. Rewriting
            # it would corrupt a token that is intentionally not a word, even
            # when the detector finds the other layout more plausible.
            logger.debug("Buffer contains an internal separator; skipping")
            return

        if self._skip_regex is not None and self._skip_regex.search(buffer):
            logger.debug("Buffer matches custom_skip_regex; skipping")
            return

        self._last_word = buffer

        # Log metadata only: never write the typed text itself to disk, so the
        # log stays free of passwords and other sensitive input.
        logger.info("Fixing buffer of length %d (%s -> %s)", len(buffer), current, target)
        if self.dry_run:
            logger.info("Dry run: skipping layout switch and text replacement")
            return

        # If a shutdown was already requested, do not begin: the whole fix must
        # be all-or-nothing. Once we start, we finish it, because the injector
        # emits backspaces and the new text as one atomic batch, so a SIGTERM
        # arriving mid-fix cannot leave truncated text.
        if self._shutdown_requested:
            logger.info("Shutdown requested; skipping replacement")
            return

        # When the flush came from a word-boundary key (Space/Enter/Tab), that
        # key is still being processed by the compositor. Deleting immediately
        # races it: Chromium/Electron coalesce the fast synthetic Backspaces and
        # the first character survives (``руддщ `` -> ``рhello``). A short pause
        # lets the boundary settle first. The idle fallback and an explicit
        # hotkey do not need it.
        if boundary and self.config.trigger_settle_ms > 0:
            logger.debug("Trigger settle: waiting %d ms", self.config.trigger_settle_ms)
            time.sleep(self.config.trigger_settle_ms / 1000.0)

        self.switcher.switch_to(target)
        time.sleep(0.05)
        logger.debug(
            "Sending %d backspaces, then injecting %d chars into %s",
            backspace_count,
            len(converted),
            target,
        )
        if self.injector.replace_text(backspace_count, converted, target):
            # The fixed text has the same length as the original, so recording
            # the original lets a later undo restore the screen exactly.
            self._record_undo(buffer, current, backspace_count)
            logger.debug("Flush complete, buffer cleared")
            if self.config.notify_on_fix:
                self._notify()

    def _notify(self) -> None:
        """Show a desktop notification about a correction."""
        # The notification text is a *fixed* label. The typed text is never put
        # into the argv of any subprocess, so it cannot leak through ``ps``,
        # ``/proc`` or the journal.
        try:
            subprocess.run(
                ["notify-send", "--app-name=LinguaFix", "LinguaFix", "Раскладка исправлена"],
                check=False,
                capture_output=True,
                timeout=NOTIFY_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            logger.debug("notify-send failed", exc_info=True)

    def reload_config(self) -> None:
        """Reload the configuration file in place."""
        from .config import load_config

        try:
            new_config = load_config()
        except Exception:
            logger.error("Failed to reload configuration", exc_info=True)
            return
        self.config = new_config
        self.detector.set_stop_words(new_config.stop_words)
        self.detector.min_word_length = new_config.min_word_length
        self.detector.set_confidence_threshold(new_config.confidence_threshold)
        self.detector.set_languages(tuple(new_config.languages))
        self.detector.plausibility_check = new_config.plausibility_check
        self.detector.structural_boundaries = new_config.structural_boundaries
        self.detector.identifier_guard = new_config.identifier_guard
        self.detector.plausibility_floor = new_config.plausibility_floor
        self.detector.max_consecutive_consonants = new_config.max_consecutive_consonants
        self.detector.min_vowel_ratio = new_config.min_vowel_ratio
        self.detector.set_context_weight(
            new_config.context_weight if new_config.context_analysis else 0.0
        )
        self.detector.set_dictionary_size(new_config.dictionary_size)
        # Always re-read the user dictionary: the reload hotkey is also how a
        # user picks up words they just added to the file.
        self.detector.set_user_words(load_user_dictionary(new_config.dictionary_custom_path))
        self._skip_regex = _compile_skip_regex(new_config.custom_skip_regex)
        self._excepted_apps = {app.lower() for app in new_config.exceptions_apps}
        self.switcher.layouts = list(new_config.layouts)
        self._hotkeys = {
            "fix": self._parse_hotkey(new_config.hotkey_fix_last_word),
            "undo": self._parse_hotkey(new_config.hotkey_undo_last_fix),
            "toggle_mode": self._parse_hotkey(new_config.hotkey_toggle_mode),
            "reload": self._parse_hotkey(new_config.hotkey_reload_config),
        }
        self._double_tap_hotkeys = self._build_double_tap_hotkeys(new_config)
        self._last_modifier_tap.clear()
        logger.info("Configuration reloaded")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------
    def run(self) -> int:
        """Run the daemon until a stop signal is received.

        Returns:
            A process exit code (``0`` on clean shutdown).
        """
        if not self.acquire_lock():
            return 1

        self._install_signal_handlers()
        logger.info(
            "LinguaFix starting: session=%s switcher=%s injector=%s%s",
            getattr(self.switcher, "session_type", "") or "unknown",
            getattr(self.switcher, "backend", "?"),
            getattr(self.injector, "backend", "?"),
            " dry-run=on" if self.dry_run else "",
        )
        devices = self._devices if self._devices is not None else self.discover_devices()
        if not devices:
            logger.error("No keyboard devices found; check /dev/input permissions")
            self.release_lock()
            return 2

        self._running = True
        selector = selectors.DefaultSelector()
        for device in devices:
            try:
                selector.register(device.fd, selectors.EVENT_READ, device)
            except (OSError, ValueError) as exc:
                logger.debug("Cannot register %s: %s", device, exc)

        logger.info(
            "LinguaFix started (%d device(s), %s, %s%s)",
            len(devices),
            self.switcher.describe(),
            self.injector.describe(),
            ", dry-run" if self.dry_run else "",
        )
        self._start_tray()
        try:
            self._loop(selector)
        finally:
            # Close the initial devices and any picked up by a re-discovery pass,
            # so a keyboard reconnected during the run is not leaked.
            open_devices = {id(device): device for device in devices}
            for key in selector.get_map().values():
                open_devices[id(key.data)] = key.data
            selector.close()
            for device in open_devices.values():
                with contextlib.suppress(OSError):
                    device.close()
            self._stop_tray()
            self.release_lock()
        logger.info("LinguaFix stopped")
        return 0

    def _start_tray(self) -> None:
        """Start the optional tray icon when enabled in the configuration."""
        if not self.config.tray_enabled:
            return
        tray = TrayIcon(
            on_status=self.status_text,
            on_fix=self._tray_fix,
            on_quit=self.stop,
        )
        if tray.start():
            self._tray = tray

    def _stop_tray(self) -> None:
        """Stop the tray icon if it is running."""
        if self._tray is not None:
            self._tray.stop()
            self._tray = None

    def _tray_fix(self) -> None:
        """Tray callback: analyse the current buffer immediately."""
        with self._lock:
            has_buffer = bool(self.buffer)
        if has_buffer:
            self._process_buffer()

    def status_text(self) -> str:
        """Return a one-line human-readable status string.

        Used by the tray icon and by tests; it contains no typed text.
        """
        layout = self.switcher.get_current_layout()
        state = "active" if self._running else "stopped"
        return f"LinguaFix: {state}, layout={layout}, mode={self.config.mode}"

    def _loop(self, selector: selectors.BaseSelector) -> None:
        """Run the event loop until ``self._running`` becomes false."""
        registered = len(selector.get_map())
        while self._running:
            if self._reload_requested:
                self._reload_requested = False
                self.reload_config()

            if self._undo_requested:
                self._undo_requested = False
                self._undo_last_fix()

            if registered == 0:
                # Every keyboard disappeared (for example a USB keyboard was
                # unplugged). Retry discovery instead of spinning: systemd's
                # ``Restart=always`` would also restart us, but recovering in
                # place keeps the single-instance lock and avoids a restart
                # storm. The device path is rediscovered, never cached.
                logger.warning("No keyboard devices remain; attempting to reconnect")
                time.sleep(DEVICE_RESCAN_DELAY)
                for device in self.discover_devices():
                    try:
                        selector.register(device.fd, selectors.EVENT_READ, device)
                        registered += 1
                    except (OSError, ValueError) as exc:
                        logger.debug("Cannot re-register %s: %s", device, exc)
                        with contextlib.suppress(OSError):
                            device.close()
                continue

            try:
                ready = selector.select(SELECT_TIMEOUT)
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                logger.error("select() failed: %s", exc)
                break

            for key, _mask in ready:
                device = key.data
                try:
                    for event in device.read():
                        self._handle_event(event)
                except OSError as exc:
                    logger.warning("Device read error (device removed?): %s", exc)
                    with contextlib.suppress(KeyError, ValueError):
                        selector.unregister(device.fd)
                        registered -= 1
                    with contextlib.suppress(OSError):
                        device.close()

            self._flush_if_idle()

    def _flush_if_idle(self) -> None:
        """Flush the buffer when it has been idle past the fallback timeout.

        Word-boundary keys already flush the buffer the moment the user ends a
        word, so this only catches words typed without a separator (a long URL
        or a compound word) and is intentionally short.
        """
        if (
            self.buffer
            and self.last_key_time
            and time.time() - self.last_key_time > self.config.analysis_timeout
        ):
            self._process_buffer()

    def stop(self) -> None:
        """Request a graceful shutdown (useful for in-process tests)."""
        self._shutdown_requested = True
        self._running = False

    @property
    def is_running(self) -> bool:
        """Return whether the daemon main loop is currently running."""
        return self._running
