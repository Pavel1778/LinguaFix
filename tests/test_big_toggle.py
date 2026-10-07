"""Tests for the big on/off button and the bundled stylesheet.

GTK aborts without a display, so these tests are skipped unless one is
available (CI runs them under ``xvfb-run``).
"""

from __future__ import annotations

import os
import sys

import pytest

from linguafix.config import Config

_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
if os.path.isdir(_DIST_PACKAGES) and _DIST_PACKAGES not in sys.path:
    sys.path.append(_DIST_PACKAGES)


def _gtk_usable() -> bool:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _gtk_usable(), reason="GTK4/libadwaita or display unavailable")


def test_button_builds_with_power_glyph() -> None:
    from linguafix.gui.widgets.big_toggle import BigToggle

    button = BigToggle()
    assert button.icon_name == "power-symbolic"
    assert button.state == "off"


def test_click_reports_toggle() -> None:
    from linguafix.gui.widgets.big_toggle import BigToggle

    clicks: list[bool] = []
    button = BigToggle(on_toggle=lambda: clicks.append(True))
    button._button.emit("clicked")
    assert clicks == [True]


def test_click_ignored_while_busy() -> None:
    from linguafix.gui.widgets.big_toggle import BigToggle

    clicks: list[bool] = []
    button = BigToggle(on_toggle=lambda: clicks.append(True))
    button.set_busy()
    button._button.emit("clicked")
    assert clicks == []


def test_accessible_role_is_toggle_button() -> None:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    from linguafix.gui.widgets.big_toggle import BigToggle

    button = BigToggle()
    assert button._button.get_accessible_role() == Gtk.AccessibleRole.TOGGLE_BUTTON


def test_state_classes_and_labels() -> None:
    from linguafix.gui.widgets.big_toggle import STATE_ON, BigToggle

    button = BigToggle()
    button.set_state(STATE_ON, layout="ru")
    assert button._button.has_css_class("active-state")
    assert "раскладка: ru" in button._caption.get_label()
    button.set_state("off")
    assert not button._button.has_css_class("active-state")


def test_reduce_motion_class_follows_settings() -> None:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    from linguafix.gui.widgets.big_toggle import BigToggle

    settings = Gtk.Settings.get_default()
    if settings is None:
        pytest.skip("no GTK settings")
    settings.set_property("gtk-enable-animations", False)
    button = BigToggle()
    assert button._button.has_css_class("reduce-motion")
    settings.set_property("gtk-enable-animations", True)
    button2 = BigToggle()
    assert not button2._button.has_css_class("reduce-motion")


def test_stylesheet_loads() -> None:
    from linguafix.gui.style import load_stylesheet

    assert load_stylesheet() is True


def test_stylesheet_parses_without_errors() -> None:
    """GTK reports CSS syntax errors via a signal, not an exception."""
    import gi

    gi.require_version("Gtk", "4.0")
    from importlib import resources

    from gi.repository import Gtk

    css = (resources.files("linguafix.gui") / "style.css").read_text(encoding="utf-8")
    errors: list[object] = []
    provider = Gtk.CssProvider()
    provider.connect("parsing-error", lambda _p, section, error: errors.append(error))
    provider.load_from_string(css)
    assert errors == []


def test_stylesheet_file_is_packaged() -> None:
    """The CSS must be importable as package data (wheel and .deb)."""
    from importlib import resources

    css = (resources.files("linguafix.gui") / "style.css").read_text(encoding="utf-8")
    assert ".big-toggle" in css
    assert "power" not in css  # the glyph is set in code, not CSS


def test_config_default_typo_off() -> None:
    """T9 stays opt-in: the button must not silently enable it."""
    assert Config().typo_correction is False
