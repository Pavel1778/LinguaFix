"""Text replacement backends.

LinguaFix rewrites already-typed text by sending the right number of
``Backspace`` key presses followed by the corrected text. Three backends are
supported, tried in order of preference:

* ``uinput`` creates a virtual kernel keyboard and emits real key events. It is
  layout-aware: characters are translated into physical keys using the target
  layout so the compositor produces the intended glyphs.
* ``wtype`` uses the Wayland virtual-keyboard protocol and types literal text.
* ``xdotool`` types literal text under X11.

Backends are selected automatically based on availability unless the user pins
one through the configuration.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from typing import Any, Final

from .converter import LayoutConverter

logger = logging.getLogger(__name__)

BACKEND_UINPUT: Final[str] = "uinput"
BACKEND_WTYPE: Final[str] = "wtype"
BACKEND_XDOTOOL: Final[str] = "xdotool"
BACKEND_NONE: Final[str] = "none"

COMMAND_TIMEOUT: Final[float] = 10.0
BACKSPACE_DELAY: Final[float] = 0.005
# Delay after a layout switch before typing, to let the compositor settle.
SETTLE_DELAY: Final[float] = 0.05

# Canonical US character -> (evdev key name, requires shift).
_BASE_KEYS: Final[dict[str, str]] = {
    "`": "KEY_GRAVE",
    "1": "KEY_1",
    "2": "KEY_2",
    "3": "KEY_3",
    "4": "KEY_4",
    "5": "KEY_5",
    "6": "KEY_6",
    "7": "KEY_7",
    "8": "KEY_8",
    "9": "KEY_9",
    "0": "KEY_0",
    "-": "KEY_MINUS",
    "=": "KEY_EQUAL",
    "q": "KEY_Q",
    "w": "KEY_W",
    "e": "KEY_E",
    "r": "KEY_R",
    "t": "KEY_T",
    "y": "KEY_Y",
    "u": "KEY_U",
    "i": "KEY_I",
    "o": "KEY_O",
    "p": "KEY_P",
    "[": "KEY_LEFTBRACE",
    "]": "KEY_RIGHTBRACE",
    "\\": "KEY_BACKSLASH",
    "a": "KEY_A",
    "s": "KEY_S",
    "d": "KEY_D",
    "f": "KEY_F",
    "g": "KEY_G",
    "h": "KEY_H",
    "j": "KEY_J",
    "k": "KEY_K",
    "l": "KEY_L",
    ";": "KEY_SEMICOLON",
    "'": "KEY_APOSTROPHE",
    "z": "KEY_Z",
    "x": "KEY_X",
    "c": "KEY_C",
    "v": "KEY_V",
    "b": "KEY_B",
    "n": "KEY_N",
    "m": "KEY_M",
    ",": "KEY_COMMA",
    ".": "KEY_DOT",
    "/": "KEY_SLASH",
    " ": "KEY_SPACE",
}

# Canonical shifted character -> matching unshifted character.
_SHIFT_PAIRS: Final[dict[str, str]] = {
    "~": "`",
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    _SHIFT_PAIRS[_letter.upper()] = _letter


def _run(command: list[str], timeout: float = COMMAND_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run ``command`` without a shell, returning the completed process."""
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


class TextInjector:
    """Replace typed text using the best available backend.

    Args:
        converter: Converter used to translate characters into physical keys
            for the ``uinput`` backend.
        backend: One of ``"auto"``, ``"uinput"``, ``"wtype"`` or ``"xdotool"``.
        session_type: Override for ``XDG_SESSION_TYPE`` (used in tests).
    """

    def __init__(
        self,
        converter: LayoutConverter | None = None,
        backend: str = "auto",
        session_type: str | None = None,
    ) -> None:
        import os

        self.converter = converter or LayoutConverter()
        self.session_type = (session_type or os.environ.get("XDG_SESSION_TYPE", "")).lower()
        self._requested_backend = backend
        self._backend = self._resolve_backend(backend)

    def _uinput_available(self) -> bool:
        """Return ``True`` when a writable ``/dev/uinput`` exists."""
        import os

        return os.access("/dev/uinput", os.W_OK)

    def _resolve_backend(self, backend: str) -> str:
        """Choose a concrete backend honouring availability and the request."""
        if backend == BACKEND_UINPUT:
            return BACKEND_UINPUT if self._uinput_available() else BACKEND_NONE
        if backend == BACKEND_WTYPE:
            return BACKEND_WTYPE if _which(BACKEND_WTYPE) else BACKEND_NONE
        if backend == BACKEND_XDOTOOL:
            return BACKEND_XDOTOOL if _which(BACKEND_XDOTOOL) else BACKEND_NONE
        # auto
        if self._uinput_available():
            return BACKEND_UINPUT
        if _which(BACKEND_WTYPE):
            return BACKEND_WTYPE
        if _which(BACKEND_XDOTOOL):
            return BACKEND_XDOTOOL
        return BACKEND_NONE

    @property
    def backend(self) -> str:
        """Return the name of the active backend."""
        return self._backend

    def replace_text(self, old: str, new: str, layout: str) -> bool:
        """Delete ``old`` and type ``new``.

        Args:
            old: The text currently on screen that must be removed.
            new: The corrected text to type.
            layout: The layout that will be active while typing ``new``.

        Returns:
            ``True`` when the replacement succeeded.
        """
        if self._backend == BACKEND_NONE:
            logger.error("No text injection backend available")
            return False

        # The uinput backend emits the backspaces and the new text as one atomic
        # batch (all events written, then a single ``syn``). That closes the
        # crash window in which the daemon had deleted the old text but not yet
        # typed the replacement, which would leave the user with truncated text.
        if self._backend == BACKEND_UINPUT:
            return self._uinput_batch(len(old), new, layout)

        if not self._send_backspaces(len(old)):
            logger.warning("Failed to send backspaces; aborting replacement")
            return False

        time.sleep(SETTLE_DELAY)
        return self._type_text(new, layout)

    def _send_backspaces(self, count: int) -> bool:
        """Send ``count`` backspace presses."""
        if count <= 0:
            return True
        command = [self._backend, "key", "BackSpace"]
        for _ in range(count):
            result = _run(command)
            if result.returncode != 0:
                return False
            time.sleep(BACKSPACE_DELAY)
        return True

    def _type_text(self, text: str, layout: str) -> bool:
        """Type ``text`` using the active backend."""
        if self._backend == BACKEND_UINPUT:
            return self._type_uinput(text, layout)
        if self._backend == BACKEND_WTYPE:
            result = _run([BACKEND_WTYPE, "-s", "0", "-d", "0", text])
            return result.returncode == 0
        if self._backend == BACKEND_XDOTOOL:
            result = _run([BACKEND_XDOTOOL, "type", "--clearmodifiers", text])
            return result.returncode == 0
        return False

    def _char_to_key(self, char: str, layout: str) -> tuple[str, bool] | None:
        """Resolve ``char`` to a physical key and shift state for ``layout``.

        Args:
            char: A character that should be produced.
            layout: Layout in which the character will be typed.

        Returns:
            A ``(key_name, shift)`` tuple, or ``None`` when the character cannot
            be produced in the given layout.
        """
        reverse = self.converter._reverse.get(layout)
        canonical = char
        if reverse is not None and char in reverse:
            canonical = reverse[char]

        if canonical in _BASE_KEYS:
            return _BASE_KEYS[canonical], False
        base = _SHIFT_PAIRS.get(canonical)
        if base is not None and base in _BASE_KEYS:
            return _BASE_KEYS[base], True
        return None

    def _uinput_tap(self, key_name: str, *, count: int = 1, delay: float = 0.0) -> bool:
        """Tap ``key_name`` ``count`` times through a virtual keyboard."""
        try:
            import evdev
        except ImportError:
            logger.error("uinput backend requested but evdev is missing")
            return False

        key_code = getattr(evdev.ecodes, key_name, None)
        if key_code is None:
            logger.error("Unknown key %s", key_name)
            return False

        shift_code = evdev.ecodes.KEY_LEFTSHIFT
        ev_key = evdev.ecodes.EV_KEY
        try:
            device = self._open_uinput(evdev, {key_code, shift_code})
            try:
                for _ in range(count):
                    device.write(ev_key, key_code, 1)
                    device.write(ev_key, key_code, 0)
                    device.syn()
                    if delay:
                        time.sleep(delay)
            finally:
                self._close_uinput(device)
        except (OSError, PermissionError, ValueError):
            logger.error("Could not create uinput device", exc_info=True)
            return False
        return True

    def _resolve_uinput_keys(
        self, text: str, layout: str
    ) -> tuple[list[tuple[int, bool]], set[int]] | None:
        """Resolve ``text`` into ``(keycode, shift)`` pairs and a key set.

        Returns ``None`` when a character cannot be produced in ``layout``.

        The second element is the set of *key codes* (plain integers from
        ``evdev.ecodes``) that the virtual keyboard must be able to emit. Key
        codes are never taken from ``uinput.KEY_*``: on Debian 13 those
        constants are ``(event_type, code)`` tuples, and older releases expose
        them under a different module layout altogether.
        """
        import evdev

        codes: set[int] = {int(evdev.ecodes.KEY_LEFTSHIFT), int(evdev.ecodes.KEY_BACKSPACE)}
        resolved: list[tuple[int, bool]] = []
        for char in text:
            key = self._char_to_key(char, layout)
            if key is None:
                # Do not log the character itself; it may be sensitive input.
                logger.warning("Cannot type a character in layout %s via uinput", layout)
                return None
            name, shift = key
            code = getattr(evdev.ecodes, name, None)
            if code is None:
                return None
            codes.add(int(code))
            resolved.append((int(code), shift))
        return resolved, codes

    @staticmethod
    def _open_uinput(evdev: Any, key_codes: set[int]) -> Any:
        """Open a virtual keyboard able to emit ``key_codes``.

        Uses ``evdev.UInput`` (a hard dependency, available in Debian 12 and
        13) rather than ``uinput.UInput``: the ``uinput`` package changed its
        API between releases (``Device``/``emit`` versus ``UInput``/``write``)
        and its ``KEY_*`` constants are tuples, which makes it an unreliable
        dependency here.
        """
        capabilities = {int(evdev.ecodes.EV_KEY): sorted(int(code) for code in key_codes)}
        return evdev.UInput(capabilities, name="linguafix")

    @staticmethod
    def _close_uinput(device: Any) -> None:
        """Close ``device``, tolerating backends that only implement ``close``."""
        try:
            device.close()
        except AttributeError:
            destroy = getattr(device, "destroy", None)
            if destroy is not None:
                destroy()

    def _type_uinput(self, text: str, layout: str) -> bool:
        """Type ``text`` through a virtual kernel keyboard."""
        try:
            import evdev
        except ImportError:
            logger.error("uinput backend requested but evdev is missing")
            return False

        resolved_bundle = self._resolve_uinput_keys(text, layout)
        if resolved_bundle is None:
            return False
        resolved, codes = resolved_bundle
        shift_code = int(evdev.ecodes.KEY_LEFTSHIFT)
        ev_key = evdev.ecodes.EV_KEY

        try:
            device = self._open_uinput(evdev, codes)
            try:
                for code, shift in resolved:
                    if shift:
                        device.write(ev_key, shift_code, 1)
                    device.write(ev_key, code, 1)
                    device.write(ev_key, code, 0)
                    if shift:
                        device.write(ev_key, shift_code, 0)
                    device.syn()
            finally:
                self._close_uinput(device)
        except (OSError, PermissionError, ValueError):
            logger.error("Could not create uinput device", exc_info=True)
            return False
        return True

    def _uinput_batch(self, backspace_count: int, text: str, layout: str) -> bool:
        """Delete ``backspace_count`` chars and type ``text`` as one batch.

        All key events are written to the virtual keyboard and flushed with a
        single ``syn``. The kernel delivers the whole batch together, so a
        crash cannot leave the text half-deleted.
        """
        try:
            import evdev
        except ImportError:
            logger.error("uinput backend requested but evdev is missing")
            return False

        resolved_bundle = self._resolve_uinput_keys(text, layout)
        if resolved_bundle is None:
            return False
        resolved, codes = resolved_bundle

        shift_code = int(evdev.ecodes.KEY_LEFTSHIFT)
        backspace_code = int(evdev.ecodes.KEY_BACKSPACE)
        ev_key = evdev.ecodes.EV_KEY

        try:
            device = self._open_uinput(evdev, codes)
            try:
                for _ in range(backspace_count):
                    device.write(ev_key, backspace_code, 1)
                    device.write(ev_key, backspace_code, 0)
                for code, shift in resolved:
                    if shift:
                        device.write(ev_key, shift_code, 1)
                    device.write(ev_key, code, 1)
                    device.write(ev_key, code, 0)
                    if shift:
                        device.write(ev_key, shift_code, 0)
                device.syn()
            finally:
                self._close_uinput(device)
        except (OSError, PermissionError, ValueError):
            logger.error("Could not create uinput device", exc_info=True)
            return False
        return True

    def describe(self) -> str:
        """Return a human readable description of the injector state."""
        return f"backend={self._backend} session={self.session_type or 'unknown'}"
