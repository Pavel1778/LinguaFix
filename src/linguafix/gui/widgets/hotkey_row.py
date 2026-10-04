"""A row that records a keyboard shortcut."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ...config import FORBIDDEN_HOTKEY_KEYS, normalise_hotkey  # noqa: E402

# GDK keyval names that differ from the names used in config.toml.
_KEYVAL_ALIASES: Final[dict[str, str]] = {
    "ESCAPE": "ESC",
    "RETURN": "ENTER",
    "KP_ENTER": "KPENTER",
    "SPACE": "SPACE",
    "TAB": "TAB",
    "BACKSPACE": "BACKSPACE",
    "CONTROL_L": "LEFTCTRL",
    "CONTROL_R": "RIGHTCTRL",
    "ALT_L": "LEFTALT",
    "ALT_R": "RIGHTALT",
    "SHIFT_L": "LEFTSHIFT",
    "SHIFT_R": "RIGHTSHIFT",
    "SUPER_L": "LEFTMETA",
    "SUPER_R": "RIGHTMETA",
    "PAUSE": "PAUSE",
}
_MODIFIER_KEYVALS: Final[frozenset[str]] = frozenset(
    {
        "CONTROL_L",
        "CONTROL_R",
        "ALT_L",
        "ALT_R",
        "SHIFT_L",
        "SHIFT_R",
        "SUPER_L",
        "SUPER_R",
        "META_L",
        "META_R",
        "ISO_LEVEL3_SHIFT",
    }
)


def keyval_to_hotkey(keyval: int, state: int) -> str | None:
    """Translate a GDK key press into a normalised hotkey string.

    Args:
        keyval: A ``Gdk`` keyval.
        state: The active ``Gdk.ModifierType`` flags.

    Returns:
        A normalised hotkey such as ``"CTRL+SHIFT+F12"``, the sentinel
        ``"__CLEAR__"`` for Backspace, or ``None`` when the press is only a
        modifier or otherwise unusable.
    """
    name = Gdk.keyval_name(keyval)
    if not name:
        return None
    raw = name.upper()
    if raw in _MODIFIER_KEYVALS:
        return None
    token = _KEYVAL_ALIASES.get(raw, raw)
    if token == "BACKSPACE":
        return "__CLEAR__"

    parts: list[str] = []
    if state & int(Gdk.ModifierType.CONTROL_MASK):
        parts.append("CTRL")
    if state & int(Gdk.ModifierType.ALT_MASK):
        parts.append("ALT")
    if state & int(Gdk.ModifierType.SHIFT_MASK):
        parts.append("SHIFT")
    if state & int(Gdk.ModifierType.SUPER_MASK):
        parts.append("META")
    parts.append(token)
    try:
        return normalise_hotkey("+".join(parts))
    except ValueError:
        return None


class HotkeyRow(Adw.ActionRow):
    """An :class:`Adw.ActionRow` that captures a shortcut when clicked."""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        value: str = "",
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(title=title, subtitle=subtitle)
        self._on_change = on_change
        self._recording = False
        self._value = value

        self._label = Gtk.Label(label=value or "Не задано")
        self._label.add_css_class("dim-label")
        self.add_suffix(self._label)

        button = Gtk.Button(label="Изменить")
        button.add_css_class("flat")
        button.connect("clicked", self._start_recording)
        self.add_suffix(button)

        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    @property
    def value(self) -> str:
        """Return the currently bound hotkey."""
        return self._value

    def _start_recording(self, _button: Gtk.Button) -> None:
        self._recording = True
        self._label.set_label("Нажмите комбинацию…")

    def _on_key_pressed(
        self, _controller: Gtk.EventControllerKey, keyval: int, _keycode: int, state: int
    ) -> bool:
        if not self._recording:
            return False
        name = Gdk.keyval_name(keyval)
        if name and name.upper() == "ESCAPE":
            self._recording = False
            self._label.set_label(self._value or "Не задано")
            return True

        result = keyval_to_hotkey(keyval, state)
        if result is None:
            return True
        if result == "__CLEAR__":
            self._apply("")
            return True
        self._apply(result)
        return True

    def _apply(self, value: str) -> None:
        self._recording = False
        self._value = value
        self._label.set_label(value or "Не задано")
        if self._on_change is not None:
            self._on_change(value)

    @staticmethod
    def forbidden_keys() -> frozenset[str]:
        """Return the keys that may never be bound."""
        return FORBIDDEN_HOTKEY_KEYS
