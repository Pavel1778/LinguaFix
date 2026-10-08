"""The VPN-style big on/off button on the home page."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

logger = logging.getLogger(__name__)

STATE_OFF = "off"
STATE_ON = "on"
STATE_BUSY = "busy"

# The power glyph from the Adwaita icon theme, as in the GNOME quick-settings
# power button: a thin symbolic symbol, never a coloured pictogram.
# ``system-shutdown-symbolic`` is the name Adwaita actually ships (verified
# against adwaita-icon-theme 48); ``power-symbolic`` does not exist and rendered
# as a "broken image" placeholder.
ICON_NAME = "system-shutdown-symbolic"


def theme_has_icon(icon_name: str = ICON_NAME) -> bool:
    """Return whether the active icon theme can resolve ``icon_name``.

    Returns ``True`` when the check cannot be made (no display, no GTK), so the
    caller keeps the theme icon rather than swapping in the fallback for an
    environment we could not inspect.
    """
    try:
        from gi.repository import Gdk, Gtk  # local import: optional dependency

        display = Gdk.Display.get_default()
        if display is None:
            return True
        return bool(Gtk.IconTheme.get_for_display(display).has_icon(icon_name))
    except (ImportError, ValueError, AttributeError):  # pragma: no cover - no display
        return True


class PowerGlyph(Gtk.DrawingArea):
    """A theme-independent power glyph, drawn with Cairo.

    Used only when the icon theme cannot resolve :data:`ICON_NAME` (for example
    a user theme that does not inherit Adwaita). Drawing the glyph ourselves
    guarantees the button is never a "broken image" placeholder, and reading the
    widget colour keeps it in step with the light/dark theme.
    """

    def __init__(self, size: int = 64) -> None:
        super().__init__()
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_draw_func(self._draw)

    def _draw(self, _area: Gtk.DrawingArea, cr: Any, width: int, height: int) -> None:
        import math

        red = green = blue = 0.5
        alpha = 1.0
        color = self.get_color()
        if color is not None:
            red, green, blue, alpha = color.red, color.green, color.blue, color.alpha
        cr.set_source_rgba(red, green, blue, alpha)
        cx, cy = width / 2.0, height / 2.0
        # A ring with a gap at the top (the classic power symbol), plus the
        # vertical bar through the gap.
        radius = min(width, height) * 0.32
        cr.set_line_width(max(1.0, min(width, height) * 0.09))
        cr.set_line_cap(1)  # cairo.LINE_CAP_ROUND
        gap = math.radians(38)
        start = -math.pi / 2 + gap
        end = -math.pi / 2 - gap + 2 * math.pi
        cr.arc(cx, cy, radius, start, end)
        cr.stroke()
        cr.move_to(cx, cy - radius * 1.35)
        cr.line_to(cx, cy - radius * 0.15)
        cr.stroke()


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

        self._icon = self._build_icon()
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

    def _build_icon(self) -> Gtk.Widget:
        """Return the theme icon, or a drawn fallback when the theme lacks it."""
        if theme_has_icon(ICON_NAME):
            image = Gtk.Image.new_from_icon_name(ICON_NAME)
            image.set_pixel_size(64)
            return image
        logger.info("Icon theme has no %s; using the drawn power glyph", ICON_NAME)
        return PowerGlyph(64)

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
