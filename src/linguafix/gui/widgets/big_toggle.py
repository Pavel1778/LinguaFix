"""The VPN-style big on/off button on the home page."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

STATE_OFF = "off"
STATE_ON = "on"
STATE_BUSY = "busy"

# The power glyph from the Adwaita icon theme, as in the GNOME quick-settings
# power button: a thin symbolic symbol, never a coloured pictogram.
ICON_NAME = "power-symbolic"


class BigToggle(Gtk.Box):
    """A large circular button that turns the daemon on and off.

    The widget is deliberately dumb: it reports clicks through ``on_toggle`` and
    renders whatever state the window sets with :meth:`set_state`. That keeps
    the GTK code free of subprocess calls and easy to test.

    The look (white circle, soft halo, grey glyph that turns accent-coloured
    when active) lives in ``gui/style.css`` and uses the libadwaita named
    colours, so it follows the light/dark theme without hard-coded values.
    """

    def __init__(self, on_toggle: Callable[[], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_halign(Gtk.Align.CENTER)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self._on_toggle = on_toggle
        self._state = STATE_OFF
        self._layout = ""

        self._button = Gtk.Button()
        self._button.add_css_class("circular")
        self._button.add_css_class("big-toggle")
        self._button.set_size_request(160, 160)
        self._button.set_halign(Gtk.Align.CENTER)
        self._button.set_accessible_role(Gtk.AccessibleRole.TOGGLE_BUTTON)
        self._button.connect("clicked", self._on_clicked)

        self._icon = Gtk.Image.new_from_icon_name(ICON_NAME)
        self._icon.set_pixel_size(64)
        self._spinner = Gtk.Spinner()
        self._spinner.set_size_request(64, 64)

        self._button.set_child(self._icon)
        self.append(self._button)

        self._caption = Gtk.Label(label="Не активно")
        self._caption.add_css_class("title-2")
        self.append(self._caption)

        self._hint = Gtk.Label(label="Нажмите, чтобы включить LinguaFix")
        self._hint.add_css_class("dim-label")
        self.append(self._hint)

        self._sync_motion_preference()
        self.set_state(STATE_OFF)

    @property
    def state(self) -> str:
        """Return the current widget state (``off``/``on``/``busy``)."""
        return self._state

    @property
    def icon_name(self) -> str:
        """Return the icon name used for the power glyph."""
        return ICON_NAME

    def _sync_motion_preference(self) -> None:
        """Drop the transitions when the system asks for reduced motion."""
        settings = Gtk.Settings.get_default()
        animations = True
        if settings is not None:
            animations = bool(settings.get_property("gtk-enable-animations"))
        if animations:
            self._button.remove_css_class("reduce-motion")
        else:
            self._button.add_css_class("reduce-motion")

    def _on_clicked(self, _button: Gtk.Button) -> None:
        if self._state == STATE_BUSY:
            return
        if self._on_toggle is not None:
            self._on_toggle()

    def _set_accessible_label(self, label: str) -> None:
        self._button.update_property([Gtk.AccessibleProperty.LABEL], [label])

    def set_state(self, state: str, layout: str = "") -> None:
        """Render ``state`` and, when on, the active ``layout``."""
        self._state = state
        self._layout = layout
        self._button.remove_css_class("active-state")
        self._button.remove_css_class("busy-state")

        if state == STATE_ON:
            self._button.set_child(self._icon)
            self._button.add_css_class("active-state")
            self._caption.set_label(f"Активно · раскладка: {layout}" if layout else "Активно")
            self._hint.set_label("Нажмите, чтобы выключить LinguaFix")
            self._set_accessible_label("Выключить LinguaFix")
        elif state == STATE_BUSY:
            self._button.set_child(self._spinner)
            self._button.add_css_class("busy-state")
            self._spinner.start()
            self._caption.set_label("Переключаю…")
            self._hint.set_label("Подождите")
            self._set_accessible_label("LinguaFix переключается")
        else:
            self._button.set_child(self._icon)
            self._caption.set_label("Не активно")
            self._hint.set_label("Нажмите, чтобы включить LinguaFix")
            self._set_accessible_label("Включить LinguaFix")

    def set_busy(self) -> None:
        """Show the in-progress spinner state."""
        self.set_state(STATE_BUSY)


class BusyPoller:
    """Poll a condition until it holds, then run a callback.

    Used after start/stop so the UI reflects the daemon state within a couple of
    seconds without blocking the GTK main loop.
    """

    def __init__(
        self,
        condition: Callable[[], bool],
        on_ready: Callable[[], None],
        *,
        interval_ms: int = 250,
        attempts: int = 8,
    ) -> None:
        self._condition = condition
        self._on_ready = on_ready
        self._interval_ms = interval_ms
        self._remaining = attempts

    def start(self) -> None:
        """Begin polling."""
        GLib.timeout_add(self._interval_ms, self._tick)

    def _tick(self) -> bool:
        if self._condition() or self._remaining <= 0:
            self._on_ready()
            return False
        self._remaining -= 1
        return True
