"""A compact status line shown under the big toggle."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402


class StatusRow(Gtk.Box):
    """Show layout, backend, mode and time since the last fix.

    All values are metadata only; the widget never receives typed text.
    """

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_halign(Gtk.Align.CENTER)

        self._layout = self._make_label("Раскладка: —")
        self._backend = self._make_label("Backend: —")
        self._mode = self._make_label("Режим: Авто")
        self._last_fix = self._make_label("Последнее исправление: —")

        for label in (self._layout, self._backend, self._mode, self._last_fix):
            self.append(label)

    @staticmethod
    def _make_label(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.add_css_class("dim-label")
        label.set_halign(Gtk.Align.CENTER)
        return label

    def update(
        self,
        *,
        layout: str = "",
        backend: str = "",
        mode: str = "",
        seconds_since_fix: int | None = None,
    ) -> None:
        """Refresh every field. Empty values render as an em dash."""
        self._layout.set_label(f"Раскладка: {layout or '—'}")
        self._backend.set_label(f"Backend: {backend or 'g3kb-switch + uinput'}")
        self._mode.set_label(f"Режим: {mode or 'Авто'}")
        if seconds_since_fix is None:
            self._last_fix.set_label("Последнее исправление: —")
        else:
            self._last_fix.set_label(f"Последнее исправление: {seconds_since_fix} с назад")
