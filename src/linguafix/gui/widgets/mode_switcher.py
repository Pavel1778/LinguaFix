"""Segmented auto/manual/hybrid mode switch."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

from ..state import MODE_LABELS  # noqa: E402

MODES = ("auto", "manual", "hybrid")


class ModeSwitcher(Gtk.Box):
    """A three-button segmented control for the working mode.

    Emits the selected mode through ``on_change``; the window persists it.
    """

    def __init__(self, on_change: Callable[[str], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.set_halign(Gtk.Align.CENTER)
        self.add_css_class("linked")
        self._on_change = on_change
        self._buttons: dict[str, Gtk.ToggleButton] = {}
        self._current = "auto"

        first: Gtk.ToggleButton | None = None
        for mode in MODES:
            button = Gtk.ToggleButton(label=MODE_LABELS[mode])
            button.connect("toggled", self._on_toggled, mode)
            if first is None:
                first = button
            else:
                button.set_group(first)
            self._buttons[mode] = button
            self.append(button)
        self.set_mode("auto", notify=False)

    def _on_toggled(self, button: Gtk.ToggleButton, mode: str) -> None:
        if not button.get_active() or mode == self._current:
            return
        self._current = mode
        if self._on_change is not None:
            self._on_change(mode)

    def set_mode(self, mode: str, *, notify: bool = False) -> None:
        """Select ``mode`` without emitting a change unless ``notify`` is set."""
        if mode not in self._buttons:
            return
        previous = self._on_change
        if not notify:
            self._on_change = None
        self._buttons[mode].set_active(True)
        self._current = mode
        self._on_change = previous

    @property
    def mode(self) -> str:
        """Return the currently selected mode."""
        return self._current
