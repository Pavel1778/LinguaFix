"""The LinguaFix background daemon.

The daemon listens to raw keyboard events from ``/dev/input/event*`` devices,
accumulates the characters that are typed into a buffer and, once the user
pauses, decides whether the buffer was typed in the wrong layout. When that is
the case it rewrites the text and switches the layout.

The main loop uses :mod:`selectors` rather than a blocking ``read_loop`` so it
can observe the idle timeout, handle signals and serve several keyboards at
once without spawning a thread per device.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import logging
import os
import selectors
import signal
import subprocess
import time
from typing import TYPE_CHECKING, Final

from .config import Config, cache_dir
from .converter import LayoutConverter
from .detector import LanguageDetector
from .injector import TextInjector
from .switcher import LayoutSwitcher
from .tray import TrayIcon

if TYPE_CHECKING:  # pragma: no cover - import used only for typing
    from evdev import InputDevice

logger = logging.getLogger(__name__)

LOCK_FILE_NAME: Final[str] = "daemon.lock"
SELECT_TIMEOUT: Final[float] = 0.25
NOTIFY_TIMEOUT: Final[float] = 3.0

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

# Keys that terminate the current buffer.
_BOUNDARY_KEYS: Final[frozenset[str]] = frozenset({"KEY_ENTER", "KEY_KPENTER", "KEY_TAB"})
_SHIFT_KEYS: Final[frozenset[str]] = frozenset({"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT", "KEY_CAPSLOCK"})


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
        )
        self.switcher = switcher or LayoutSwitcher(
            layouts=config.layouts,
            switch_method=config.switch_method,
        )
        self.injector = injector or TextInjector(
            converter=self.converter,
            backend=config.backend,
        )
        self._devices = devices
        self._code_to_pair, self._name_to_code = _load_ecodes()
        hotkey = config.hotkey.upper()
        if not hotkey.startswith("KEY_"):
            hotkey = f"KEY_{hotkey}"
        self._hotkey_code = self._name_to_code.get(hotkey)

        self.buffer: str = ""
        self.last_key_time: float = 0.0
        self._shift = False
        self._running = False
        self._reload_requested = False
        self._lock_handle: object | None = None
        self._tray: TrayIcon | None = None

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
            handle = open(lock_path, "w", encoding="utf-8")  # noqa: SIM115 - kept open
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle.write(str(os.getpid()))
            handle.flush()
        except OSError as exc:
            logger.error("Another LinguaFix instance is already running (%s)", exc)
            return False
        self._lock_handle = handle
        return True

    def release_lock(self) -> None:
        """Release the single-instance lock if held."""
        handle = self._lock_handle
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
            handle.close()  # type: ignore[attr-defined]
        except OSError:
            logger.debug("Could not release lock cleanly", exc_info=True)
        finally:
            self._lock_handle = None

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------
    def _install_signal_handlers(self) -> None:
        """Install SIGTERM/SIGINT/SIGHUP handlers."""
        signal.signal(signal.SIGTERM, self._handle_stop)
        signal.signal(signal.SIGINT, self._handle_stop)
        signal.signal(signal.SIGHUP, self._handle_reload)

    def _handle_stop(self, signum: int, _frame: object) -> None:
        logger.info("Received signal %s; shutting down", signum)
        self._running = False

    def _handle_reload(self, _signum: int, _frame: object) -> None:
        logger.info("Received SIGHUP; scheduling config reload")
        self._reload_requested = True

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------
    def _handle_event(self, event: object) -> None:
        """Process a single evdev event.

        Args:
            event: An object exposing ``type``, ``code`` and ``value`` attributes.
        """
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
            if name != "KEY_CAPSLOCK":
                self._shift = value in (1, 2)
            return

        if value == 0:  # key release
            return

        if self._hotkey_code is not None and code == self._hotkey_code:
            self._process_buffer()
            return

        if value == 2:  # auto-repeat: only backspace repeats meaningfully
            if name == "KEY_BACKSPACE":
                self._handle_backspace()
            return

        self.last_key_time = time.time()

        if name == "KEY_BACKSPACE":
            self._handle_backspace()
            return

        if name in _BOUNDARY_KEYS:
            self._process_buffer()
            return

        char = self._key_to_char(code)
        if char is not None:
            self.buffer += char

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
        """Remove the last character from the buffer."""
        if self.buffer:
            self.buffer = self.buffer[:-1]

    def _process_buffer(self) -> None:
        """Analyse the buffer and apply a correction when appropriate."""
        buffer = self.buffer.strip()
        self.buffer = ""
        if not buffer or len(buffer) < self.config.min_word_length:
            return

        if self.detector.is_stop_word(buffer):
            logger.debug("Buffer of length %d is a stop word; skipping", len(buffer))
            return

        current = self.switcher.get_current_layout()
        target = self.detector.target_layout(buffer, current)
        if target is None:
            return

        converted = self.converter.convert(buffer, current, target)
        if converted == buffer:
            return

        # Log metadata only: never write the typed text itself to disk, so the
        # log stays free of passwords and other sensitive input.
        logger.info("Fixing buffer of length %d (%s -> %s)", len(buffer), current, target)
        if self.dry_run:
            logger.info("Dry run: skipping layout switch and text replacement")
            return

        self.switcher.switch_to(target)
        time.sleep(0.05)
        if self.injector.replace_text(buffer, converted, target) and self.config.notify_on_fix:
            self._notify(converted)

    def _notify(self, text: str) -> None:
        """Show a desktop notification about a correction."""
        try:
            subprocess.run(
                ["notify-send", "--app-name=LinguaFix", "LinguaFix", f"Исправлено: {text}"],
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
        self.switcher.layouts = list(new_config.layouts)
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
            selector.close()
            for device in devices:
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
        if self.buffer:
            self._process_buffer()

    def status_text(self) -> str:
        """Return a one-line human-readable status string.

        Used by the tray icon and by tests; it contains no typed text.
        """
        layout = self.switcher.get_current_layout()
        state = "active" if self._running else "stopped"
        return f"LinguaFix: {state}, layout={layout}"

    def _loop(self, selector: selectors.BaseSelector) -> None:
        """Run the event loop until ``self._running`` becomes false."""
        while self._running:
            if self._reload_requested:
                self._reload_requested = False
                self.reload_config()

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
                    logger.debug("Device read error: %s", exc)
                    with contextlib.suppress(KeyError, ValueError):
                        selector.unregister(device.fd)

            if (
                self.buffer
                and self.last_key_time
                and time.time() - self.last_key_time > self.config.analysis_timeout
            ):
                self._process_buffer()

    def stop(self) -> None:
        """Request a graceful shutdown (useful for in-process tests)."""
        self._running = False

    @property
    def is_running(self) -> bool:
        """Return whether the daemon main loop is currently running."""
        return self._running
