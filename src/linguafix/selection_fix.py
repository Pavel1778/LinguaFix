"""Selection fix: convert the layout of an already-selected piece of text.

Bound to a hotkey (``CTRL+SHIFT+L`` by default), this copies the current
selection, converts it from one keyboard layout to the other, pastes the
result back and restores the clipboard. It is for text that is already on
screen, which the daemon cannot reach through its keystroke buffer.

The whole flow is best-effort: every external step (``wl-paste``/``xclip``,
``wl-copy``/``xclip``, the virtual keyboard) may be unavailable, in which case
the operation is a no-op rather than an error.
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import Final

from .converter import LayoutConverter
from .injector import TextInjector

logger = logging.getLogger(__name__)

COMMAND_TIMEOUT: Final[float] = 2.0
# Time allowed for the target application to service the synthetic Ctrl+C
# before the clipboard is read.
CLIPBOARD_SETTLE: Final[float] = 0.1

_COPY_COMBO: Final[list[str]] = ["KEY_LEFTCTRL", "KEY_C"]
_PASTE_COMBO: Final[list[str]] = ["KEY_LEFTCTRL", "KEY_V"]


def _which(program: str) -> str | None:
    import shutil

    return shutil.which(program)


class SelectionFix:
    """Convert the layout of the currently selected text.

    Args:
        converter: Layout converter used to translate the selection.
        injector: Injector used to send the Ctrl+C / Ctrl+V shortcuts.
        session_type: Override for ``XDG_SESSION_TYPE`` (used in tests).
    """

    def __init__(
        self,
        converter: LayoutConverter | None = None,
        injector: TextInjector | None = None,
        session_type: str | None = None,
    ) -> None:
        import os

        self.converter = converter or LayoutConverter()
        self.injector = injector
        self.session_type = (session_type or os.environ.get("XDG_SESSION_TYPE", "")).lower()

    # --- clipboard backends -------------------------------------------------
    def _read_command(self) -> list[str] | None:
        if self.session_type == "wayland" and _which("wl-paste"):
            return ["wl-paste", "--no-newline"]
        if _which("xclip"):
            return ["xclip", "-selection", "clipboard", "-o"]
        if _which("wl-paste"):
            return ["wl-paste", "--no-newline"]
        return None

    def _write_command(self) -> list[str] | None:
        if self.session_type == "wayland" and _which("wl-copy"):
            return ["wl-copy"]
        if _which("xclip"):
            return ["xclip", "-selection", "clipboard"]
        if _which("wl-copy"):
            return ["wl-copy"]
        return None

    def _read_clipboard(self) -> str | None:
        command = self._read_command()
        if command is None:
            return None
        try:
            result = subprocess.run(
                command, check=False, capture_output=True, text=True, timeout=COMMAND_TIMEOUT
            )
        except (OSError, subprocess.SubprocessError):
            logger.debug("Clipboard read failed", exc_info=True)
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    def _write_clipboard(self, text: str) -> bool:
        command = self._write_command()
        if command is None:
            return False
        try:
            result = subprocess.run(
                command,
                input=text,
                check=False,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            logger.debug("Clipboard write failed", exc_info=True)
            return False
        return result.returncode == 0

    # --- the operation ------------------------------------------------------
    def convert_selection(self) -> bool:
        """Convert the current selection's layout. Return ``True`` on success."""
        if self.injector is None:
            logger.debug("Selection fix has no injector")
            return False
        if not self.injector.tap_combo(_COPY_COMBO):
            logger.debug("Selection fix: Ctrl+C not available")
            return False
        time.sleep(CLIPBOARD_SETTLE)
        original = self._read_clipboard()
        if not original:
            logger.debug("Selection fix: empty or unreadable clipboard")
            return False
        converted = self._convert(original)
        if converted is None or converted == original:
            logger.debug("Selection fix: no layout change for the selection")
            return False
        if not self._write_clipboard(converted):
            logger.debug("Selection fix: could not write the converted clipboard")
            return False
        if not self.injector.tap_combo(_PASTE_COMBO):
            logger.debug("Selection fix: Ctrl+V not available")
            return False
        time.sleep(CLIPBOARD_SETTLE)
        # Restore whatever the user had on the clipboard before.
        self._write_clipboard(original)
        logger.info("Selection fix applied")
        return True

    def _convert(self, text: str) -> str | None:
        """Convert ``text`` from the wrong layout to the right one."""
        for source, target in (("us", "ru"), ("ru", "us")):
            candidate = self.converter.convert(text, source, target)
            if candidate and candidate != text:
                return candidate
        return None
