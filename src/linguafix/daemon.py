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
import json
import logging
import os
import re
import selectors
import signal
import subprocess
import threading
import time
import traceback
from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from .app_focus import get_active_app, get_focused_role
from .app_layouts import AppLayoutManager
from .config import Config, cache_dir, in_quiet_hours, snippets_path
from .converter import LayoutConverter
from .detector import LanguageDetector
from .dictionary import load_user_dictionary
from .injector import TextInjector
from .punctuation import PunctuationCorrector
from .selection_fix import SelectionFix
from .switcher import LayoutSwitcher
from .text_expander import TextExpander
from .tray import TrayIcon
from .typo import TypoCorrector

if TYPE_CHECKING:  # pragma: no cover - import used only for typing
    from evdev import InputDevice

logger = logging.getLogger(__name__)

LOCK_FILE_NAME: Final[str] = "daemon.lock"
# Metadata-only correction history written on SIGUSR2 for the GUI to read.
HISTORY_FILE_NAME: Final[str] = "history.json"
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
# Modifier keys that begin a chord and therefore abandon the word being typed:
# Ctrl+C, Alt+Tab and friends move or copy the text, so the buffer must not be
# corrected afterwards. Shift is excluded — it is part of normal typing.
_BUFFER_RESET_KEYS: Final[frozenset[str]] = frozenset(
    {"KEY_LEFTCTRL", "KEY_RIGHTCTRL", "KEY_LEFTALT", "KEY_RIGHTALT"}
)
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
# Upper bound on keys queued while a replacement runs. Generous enough for a
# fast burst, small enough that a stuck key cannot grow the queue without bound.
_MAX_DEFERRED_EVENTS: Final[int] = 50


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
            "selection_fix": self._parse_hotkey(config.selection_fix_hotkey),
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
        # original layout, backspace count, history id).
        self._undo_history: list[tuple[float, str, str, int, int]] = []
        # Recent corrections for the GUI "История" tab: metadata only, newest
        # last. ``id`` is an opaque handle the GUI passes back to undo; the
        # typed text is never stored here.
        self._fix_history: list[dict[str, object]] = []
        self._history_seq: int = 0
        # A once-a-minute cache of the quiet-hours verdict, so the check does not
        # call the clock on every keystroke.
        self._quiet_minute: int = -1
        self._quiet_now: bool = False
        # Task E: skip rules and the user dictionary.
        self._skip_regex = _compile_skip_regex(config.custom_skip_regex)
        self._excepted_apps = {app.lower() for app in config.exceptions_apps}
        self._last_word: str = ""
        self.detector.set_context_weight(config.context_weight if config.context_analysis else 0.0)
        self.detector.set_dictionary_size(config.dictionary_size)
        user_words = load_user_dictionary(config.dictionary_custom_path)
        if user_words:
            self.detector.set_user_words(user_words)
        # T9: one corrector per language, built lazily from the detector's
        # vocabulary the first time a typo is checked.
        self._typo_correctors: dict[str, TypoCorrector] = {}
        self._punctuation = PunctuationCorrector()
        # Text expansion (snippets). Loaded once here and re-loaded on reload.
        self._expander = TextExpander()
        self._load_snippets(config)
        # Selection fix converts the layout of text that is already selected.
        self.selection_fix = SelectionFix(converter=self.converter, injector=self.injector)
        # Per-app preferred layout: switch when the focused app changes.
        self.app_layout_manager = AppLayoutManager(
            layouts=config.app_layouts,
            switch_layout=self.switcher.switch_to,
            probe=get_active_app,
            enabled=config.app_layout_switch,
        )
        # Stage 13: the loop checks for updates at most once a day. The deadline
        # is kept in memory so the poll loop never touches the disk or network
        # until it is actually due. The in-flight flag stops a second check from
        # starting while the worker thread is still on the network.
        self._next_update_check: float = 0.0
        self._update_check_in_flight: bool = False
        self._update_thread: threading.Thread | None = None

        # The characters currently on screen for the word being typed. Derived
        # from ``_scancodes`` and kept in step with it (one char per printable
        # key). Kept as the detector's input; the scancode list is the source of
        # truth for how many Backspaces a fix must send.
        self.buffer: str = ""
        # The physical keys (evdev codes) that produced ``buffer``.
        self._scancodes: list[int] = []
        self.last_key_time: float = 0.0
        self._shift = False
        # Set while a Ctrl/Alt chord is held: the word typed before the chord is
        # suspended (dropped if the chord turns out not to be a hotkey) so that
        # ``Ctrl+C`` does not leave a stale word behind, while a Ctrl-based fix
        # hotkey such as ``CTRL+F12`` can still see it.
        self._suspended_buffer: tuple[str, list[int]] | None = None
        self._running = False
        self._reload_requested = False
        self._shutdown_requested = False
        self._undo_requested = False
        self._history_requested = False
        self._lock_handle: object | None = None
        # Key events that arrive while a replacement is in flight. The fix runs
        # on the event-loop thread, so keys typed during the settle pause would
        # otherwise be lost; instead they are queued and replayed once the
        # replacement finishes (see ``_process_buffer``).
        self._deferred_events: list[object] = []
        self._replaying_events = False
        # Set while ``_process_buffer_inner`` runs, so ``_handle_event`` defers
        # keys instead of processing them against a half-deleted screen.
        self._processing_buffer = False
        self._tray: TrayIcon | None = None
        # Guards ``buffer``/``last_key_time``/``_shift`` against the tray thread,
        # which may call ``_process_buffer`` (via ``_tray_fix``) concurrently with
        # the event loop. ``_lock`` serialises buffer processing so the same text
        # is never corrected twice.
        self._lock = threading.RLock()
        # Focused-role probe (AT-SPI). Injectable so tests can simulate a
        # password field without an accessibility bus.
        self._focused_role_probe: Callable[[], str | None] = get_focused_role

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
        if hasattr(signal, "SIGUSR2"):
            signal.signal(signal.SIGUSR2, self._handle_history)

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

    def _handle_history(self, _signum: int, _frame: object) -> None:
        # Only set a flag: writing the snapshot allocates and must run on the
        # event-loop thread, never inside the signal handler.
        logger.info("Received SIGUSR2; scheduling history snapshot")
        self._history_requested = True

    def _write_history_snapshot(self) -> None:
        """Write the metadata-only history snapshot for the GUI to read.

        The file holds only word *lengths*, layouts and timestamps; the typed
        text is never included. It is written atomically so the GUI never reads
        a half-written file.
        """
        path = cache_dir() / HISTORY_FILE_NAME
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"history": self.history_snapshot()}
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            logger.debug("Could not write the history snapshot", exc_info=True)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------
    def _handle_event(self, event: object) -> None:
        """Process a single evdev event, surviving any per-event failure.

        Args:
            event: An object exposing ``type``, ``code`` and ``value`` attributes.
        """
        # A replacement is running on this thread (it sleeps between the
        # Backspace batch and the new text). Queue the key instead of dropping
        # it; ``_process_buffer`` replays the queue once the fix is done.
        with self._lock:
            if self._processing_buffer and not self._replaying_events:
                if len(self._deferred_events) < _MAX_DEFERRED_EVENTS:
                    self._deferred_events.append(event)
                else:
                    logger.warning("Deferred key queue full; dropping an event")
                return
        try:
            self._handle_event_inner(event)
        except Exception as exc:  # the daemon must survive any per-event failure
            with self._lock:
                sensitive = self.buffer.strip()
            self._log_sanitized("Failed to handle a key event", exc, sensitive)

    def _replay_deferred_events(self) -> None:
        """Replay the keys that arrived while a replacement was in flight."""
        with self._lock:
            pending, self._deferred_events = self._deferred_events, []
            previous = self._replaying_events
            self._replaying_events = True
        try:
            for event in pending:
                self._handle_event(event)
        finally:
            # Restore rather than clear: a replayed key can itself trigger a fix,
            # whose own replay would otherwise drop the guard for the outer loop.
            with self._lock:
                self._replaying_events = previous

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
            if name in _BUFFER_RESET_KEYS:
                self._handle_chord_modifier(value)
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

        # A real key that is not a hotkey was pressed while Ctrl/Alt was held:
        # the chord was not a fix, so any suspended word is abandoned.
        if self._suspended_buffer is not None:
            self._drop_suspended_buffer()

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
                self._process_buffer(boundary=True, boundary_char=" ")
            else:
                self._reset_buffer()
            return

        if name in _ENTER_KEYS:
            if self.config.on_enter:
                self._process_buffer(boundary=True, boundary_char="\n")
            else:
                self._reset_buffer()
            return

        if name in _TAB_KEYS:
            if self.config.on_tab:
                self._process_buffer(boundary=True, boundary_char="\t")
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

    def _is_quiet_now(self) -> bool:
        """Return whether the quiet-hours window currently applies.

        The verdict is cached per wall-clock minute so the keystroke path does
        not read the clock (or parse the window) on every key.
        """
        if not self.config.quiet_hours_enabled:
            return False
        minute = int(time.time() // 60)
        if minute != self._quiet_minute:
            self._quiet_minute = minute
            now_minutes = time.localtime().tm_hour * 60 + time.localtime().tm_min
            self._quiet_now = in_quiet_hours(
                self.config.quiet_hours_start, self.config.quiet_hours_end, now_minutes
            )
        return self._quiet_now

    def _should_fix_buffer(self) -> bool:
        """Return whether the current mode and per-app rules allow a fix."""
        if self._is_quiet_now():
            # Quiet hours silence *automatic* correction only; an explicit fix
            # (double Shift) still goes through, because the user asked for it.
            logger.debug("Quiet hours active; skipping automatic correction")
            return False
        manual = self.config.mode == "manual"
        if not manual and not self._excepted_apps:
            return True

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
            # A Ctrl/Alt-based fix hotkey (``CTRL+F12``) suspended the word when
            # the modifier was pressed; put it back so the fix can see it.
            self._restore_suspended_buffer()
            self._process_buffer(force=True)
        elif action == "undo":
            self._undo_last_fix()
        elif action == "toggle_mode":
            self._cycle_mode()
        elif action == "reload":
            self.reload_config()
        elif action == "selection_fix":
            if self.config.selection_fix_enabled:
                self.selection_fix.convert_selection()

    def _load_snippets(self, config: Config) -> None:
        """(Re)load the snippet file named by ``config``, best-effort."""
        if not config.text_expander_enabled:
            return
        path = config.text_expander_snippets_path or str(snippets_path())
        self._expander.load(path)

    def _expand_snippet(self, buffer: str, current: str, backspace_count: int) -> bool:
        """Replace ``buffer`` with its snippet expansion. Return ``True`` on success."""
        match = self._expander.check(buffer)
        if match is None:
            return False
        trigger, expansion = match
        logger.info("Expanding snippet of length %d", len(trigger))
        if self.dry_run:
            logger.info("Dry run: skipping snippet expansion")
            return True
        if self._shutdown_requested:
            return False
        if self.injector.replace_text(backspace_count, expansion, current):
            self._record_undo(buffer, current, backspace_count, source=current, target=current)
            if self.config.notify_on_fix:
                self._notify()
        return True

    def _typo_correction(self, buffer: str, current: str) -> str | None:
        """Return a single-word typo correction for ``buffer``, or ``None``.

        Only a plain letter word in the language the user is typing is
        considered, and only when T9 is enabled. A taught word and any word with
        a structural separator are never touched, so a brand or a path cannot be
        "corrected" into a dictionary word.
        """
        if not self.config.typo_correction:
            return None
        word = buffer.strip()
        if len(word) < self.config.typo_min_word_length or not word.isalpha():
            return None
        if self.detector.is_user_word(word) or _INTERNAL_SEPARATOR_RE.search(word):
            return None
        language = self.detector.language_for_layout(current)
        if language is None:
            return None
        corrector = self._typo_correctors.get(language)
        if corrector is None:
            corrector = TypoCorrector(
                list(self.detector.vocabulary(language)),
                max_distance=self.config.typo_max_distance,
                min_length=self.config.typo_min_word_length,
            )
            self._typo_correctors[language] = corrector
        suggestion = corrector.suggest(word)
        if suggestion is None or suggestion == word:
            return None
        # Preserve the user's capitalisation (``Teh`` -> ``The``).
        if word[0].isupper():
            suggestion = suggestion[:1].upper() + suggestion[1:]
        return suggestion

    def _build_punctuation(self) -> PunctuationCorrector:
        """Build a corrector from the current config (rules are config-driven)."""
        cfg = self.config
        return PunctuationCorrector(
            dashes=cfg.punctuation_dashes,
            ellipsis=cfg.punctuation_ellipsis,
            smart_quotes=cfg.punctuation_smart_quotes,
            fix_spacing=cfg.punctuation_fix_spacing,
        )

    def _punctuation_correction(self, buffer: str, current: str) -> str | None:
        """Return a punctuation-cleaned buffer, or ``None`` when nothing changes.

        Punctuation is not buffered when ``on_punctuation`` consumes it, so this
        runs on the text as typed. Any replacement whose characters the active
        backend cannot type (the ``uinput`` backend cannot produce an em dash or
        an ellipsis) is refused wholesale rather than left half-applied.
        """
        if not self.config.punctuation_correction:
            return None
        corrected = self._punctuation.correct(buffer, current)
        if corrected == buffer:
            return None
        if not all(self.injector.can_type(char, current) for char in corrected):
            logger.debug("Punctuation replacement has an untypable character; skipping")
            return None
        return corrected

    def _record_undo(
        self,
        original: str,
        layout: str,
        backspace_count: int,
        *,
        source: str = "",
        target: str = "",
    ) -> int:
        """Remember a successful fix and return its history id.

        The undo tuple carries the history id so a later undo can mark exactly
        the row it restored. Only metadata (word length, layouts, timestamp) is
        kept for the GUI; the typed text lives solely in the in-memory undo
        tuple, never in the history list and never on disk.
        """
        now = time.monotonic()
        self._history_seq += 1
        entry_id = self._history_seq
        self._undo_history.append((now, original, layout, backspace_count, entry_id))
        self._undo_history = self._undo_history[-self.config.undo_history_depth :]
        self._fix_history.append(
            {
                "id": entry_id,
                "at": time.time(),
                "length": len(original.rstrip()),
                "source": source,
                "target": target,
                "undone": False,
            }
        )
        self._fix_history = self._fix_history[-self.config.history_size :]
        return entry_id

    def history_snapshot(self) -> list[dict[str, object]]:
        """Return the recent corrections as metadata-only dicts (newest first)."""
        return [dict(entry) for entry in reversed(self._fix_history)]

    def _mark_history_undone(self, entry_id: int | None) -> None:
        """Flag the history row linked to a restored fix."""
        if entry_id is None:
            return
        for entry in self._fix_history:
            if entry["id"] == entry_id:
                entry["undone"] = True
                return

    def _undo_last_fix(self, entry_id: int | None = None) -> bool:
        """Re-apply the text of the most recent fix within the undo window.

        Args:
            entry_id: When given, the history id the caller wants undone. Only
                the newest fix can be restored reliably, so a stale id is
                refused instead of silently undoing a different correction.

        Returns:
            ``True`` when a fix was restored (or the dry run would have).
        """
        if not self._undo_history:
            logger.info("Undo requested but nothing to undo")
            return False
        now = time.monotonic()
        # Drop entries that have aged out of the undo window.
        self._undo_history = [
            entry
            for entry in self._undo_history
            if now - entry[0] <= self.config.undo_window_seconds
        ]
        if not self._undo_history:
            logger.info("Undo requested but the window has expired")
            return False
        if entry_id is not None and self._undo_history[-1][4] != entry_id:
            logger.info("Undo requested for a stale history entry")
            return False
        _time, original, layout, backspace_count, linked_id = self._undo_history.pop()
        self._mark_history_undone(linked_id)
        if self.dry_run:
            logger.info("Dry run: skipping undo")
            return True
        current = self.switcher.get_current_layout()
        target = layout if layout else current
        self.switcher.switch_to(target)
        time.sleep(0.05)
        # The fixed text has the same length as the original word; deleting that
        # many characters and retyping the original restores the screen exactly.
        if not self.injector.replace_text(backspace_count, original, target):
            logger.warning("Undo failed to replace text")
            return False
        logger.info("Undid the last fix")
        if self.config.notify_on_fix:
            self._notify()
        return True

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

    def _handle_chord_modifier(self, value: int) -> None:
        """Suspend the buffer when Ctrl/Alt starts a chord.

        Pressing Ctrl/Alt begins a chord (``Ctrl+C``, ``Alt+Tab``): the word
        typed before it must not be corrected once the chord is over. The word is
        *suspended* rather than dropped, so a Ctrl-based fix hotkey such as
        ``CTRL+F12`` — and the ``CTRL+CTRL`` double tap — can still reach it. Any
        ordinary key pressed afterwards abandons it (see ``_drop_suspended``).
        """
        if value != 1:
            return
        with self._lock:
            if self._suspended_buffer is None and (self.buffer or self._scancodes):
                self._suspended_buffer = (self.buffer, list(self._scancodes))
                self.buffer = ""
                self._scancodes = []

    def _drop_suspended_buffer(self) -> None:
        """Discard a word suspended by a Ctrl/Alt chord that was not a hotkey."""
        with self._lock:
            self._suspended_buffer = None

    def _restore_suspended_buffer(self) -> None:
        """Put a suspended word back so a fix hotkey can process it."""
        with self._lock:
            if self._suspended_buffer is not None and not self.buffer:
                self.buffer, self._scancodes = self._suspended_buffer
                self._suspended_buffer = None

    def _reset_buffer(self) -> None:
        """Drop the current word without analysing it."""
        with self._lock:
            self.buffer = ""
            self._scancodes = []
            self._suspended_buffer = None

    def _process_buffer(
        self, *, force: bool = False, boundary: bool = False, boundary_char: str = ""
    ) -> None:
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
            boundary_char: The character the boundary key produced (``" "``,
                ``"\\n"`` or ``"\\t"``). It is already on screen right after the
                word; when the corrected text stays in the same layout the
                replacement consumes and retypes it, so it is not stranded in
                front of the corrected word (the ``рhello`` symptom).
        """
        # Capture the text so a traceback can be scrubbed of it before logging.
        with self._lock:
            sensitive = self.buffer.strip()
        with self._lock:
            self._processing_buffer = True
        try:
            self._process_buffer_inner(force=force, boundary=boundary, boundary_char=boundary_char)
        except Exception as exc:  # the daemon must survive any failure
            self._log_sanitized("Failed to process the buffer", exc, sensitive)
        finally:
            with self._lock:
                self._processing_buffer = False
            # Keys that arrived during the (slow) replacement were queued; apply
            # them now, against the corrected screen.
            self._replay_deferred_events()

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

    def _process_buffer_inner(
        self, *, force: bool = False, boundary: bool = False, boundary_char: str = ""
    ) -> None:
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
        # Per-app preferred layout: cheap when disabled, throttled otherwise.
        self.app_layout_manager.maybe_apply(time.monotonic())
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

        # Never rewrite what is typed into a password field. AT-SPI reports the
        # focused element's role; a positive "password" verdict skips the fix.
        # An unavailable/undetermined role returns None and correction proceeds
        # as before, so a missing accessibility bus does not disable the daemon.
        if self.config.password_guard:
            try:
                role = self._focused_role_probe()
            except Exception:
                logger.debug("Focused-role probe failed", exc_info=True)
                role = None
            if role == "password":
                logger.debug("Focused element is a password field; skipping")
                return

        # Text expansion runs before any layout analysis: a snippet trigger is
        # honoured verbatim and never converted to another layout. It is also
        # independent of the auto/manual mode.
        if self.config.text_expander_enabled and self._expand_snippet(
            buffer, self.switcher.get_current_layout(), backspace_count
        ):
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
            # Layout detection found nothing. A separate, opt-in step then looks
            # for a single-character typo in the language the user is typing;
            # that fix stays in the current layout.
            corrected = self._typo_correction(buffer, current)
            if corrected is not None:
                converted = corrected
                target = current
            else:
                # Neither layout detection nor typo correction applied. A final
                # opt-in pass fixes punctuation (dashes, ellipsis, spacing),
                # staying in the current layout and never touching letters.
                punctuated = self._punctuation_correction(buffer, current)
                if punctuated is None:
                    return
                converted = punctuated
                target = current
        else:
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

        # The word-boundary key (Space/Enter/Tab) that triggered the flush is
        # already on screen right after the word, so the on-screen text is
        # ``buffer + boundary_char``. A Space is the only boundary that is both
        # layout-invariant and reliably typable by every backend, so only a
        # Space is consumed and retyped: the replacement deletes one extra
        # character and types the corrected word followed by the Space again.
        # That is what stops the Space from being stranded in front of the word
        # (``hello`` -> ``рhello``). Enter/Tab keep their place after the
        # corrected text, because deleting them without being able to retype
        # them would silently drop the user's newline or tab.
        replacement = converted
        backspace_total = backspace_count
        if boundary_char == " " and self.injector.can_type(boundary_char, target):
            replacement = converted + boundary_char
            backspace_total = backspace_count + 1

        logger.debug(
            "Sending %d backspaces, then injecting %d chars into %s (boundary=%r)",
            backspace_total,
            len(replacement),
            target,
            boundary_char if backspace_total != backspace_count else "",
        )
        if self.injector.replace_text(backspace_total, replacement, target):
            # Record the *pre-fix* on-screen text so a later undo restores it
            # exactly, including the boundary that was consumed and retyped.
            self._record_undo(
                buffer + boundary_char, current, backspace_total, source=current, target=target
            )
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
        # The vocabularies may have changed, so any cached corrector is stale.
        self._typo_correctors.clear()
        self._punctuation = self._build_punctuation()
        self._load_snippets(new_config)
        self._skip_regex = _compile_skip_regex(new_config.custom_skip_regex)
        self._excepted_apps = {app.lower() for app in new_config.exceptions_apps}
        self.switcher.layouts = list(new_config.layouts)
        self._hotkeys = {
            "fix": self._parse_hotkey(new_config.hotkey_fix_last_word),
            "undo": self._parse_hotkey(new_config.hotkey_undo_last_fix),
            "toggle_mode": self._parse_hotkey(new_config.hotkey_toggle_mode),
            "reload": self._parse_hotkey(new_config.hotkey_reload_config),
            "selection_fix": self._parse_hotkey(new_config.selection_fix_hotkey),
        }
        self._double_tap_hotkeys = self._build_double_tap_hotkeys(new_config)
        self._last_modifier_tap.clear()
        self.app_layout_manager.update(
            new_config.app_layouts,
            enabled=new_config.app_layout_switch,
            switch_layout=self.switcher.switch_to,
        )
        if not new_config.update_check_enabled:
            self._next_update_check = 0.0
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

            if self._history_requested:
                self._history_requested = False
                self._write_history_snapshot()

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
            self._maybe_check_update()

    def _maybe_check_update(self) -> None:
        """Kick off the opt-in update check at most once a day (Stage 13).

        The HTTP request has a multi-second timeout and must never run on the
        event-loop thread: a slow network would freeze every keystroke for the
        duration. It runs on a daemon worker thread instead.
        """
        if not self.config.update_check_enabled:
            return
        if self._update_check_in_flight:
            return
        now = time.time()
        if now < self._next_update_check:
            return
        from .update_check import CHECK_INTERVAL_SECONDS

        # Throttle in memory; the loop runs every ``SELECT_TIMEOUT`` and must
        # not read the stamp file (or the network) on each iteration.
        self._next_update_check = now + CHECK_INTERVAL_SECONDS
        self._update_check_in_flight = True
        self._update_thread = threading.Thread(
            target=self._update_check_worker, name="linguafix-update", daemon=True
        )
        self._update_thread.start()

    def _update_check_worker(self) -> None:
        """Perform the network update check off the event loop (worker thread)."""
        from .update_check import check_for_update

        try:
            info = check_for_update()
        finally:
            self._update_check_in_flight = False
        if info is None or not info.update_available:
            return
        logger.info(
            "LinguaFix %s is available (running %s): %s",
            info.latest,
            info.current,
            info.url,
        )
        self._notify_update(info.latest)

    def _notify_update(self, latest: str) -> None:
        """Show a desktop notification about an available update.

        The text is built from the remote version tag only; no typed text or
        local configuration is involved.
        """
        try:
            subprocess.run(
                [
                    "notify-send",
                    "--app-name=LinguaFix",
                    "LinguaFix",
                    f"Доступна версия {latest}",
                ],
                check=False,
                capture_output=True,
                timeout=NOTIFY_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            logger.debug("notify-send failed", exc_info=True)

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
