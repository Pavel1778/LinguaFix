"""Every icon the GUI names must exist in the shipped Adwaita theme.

A wrong icon name does not raise: GTK silently falls back to a "broken image"
placeholder, so the button and its tabs simply look broken on a real desktop.
We therefore parse every ``icon_name=``/``new_from_icon_name(...)`` in the GUI
package and assert the name is present in the system icon theme.

Checked against the filesystem rather than a live ``Gtk.IconTheme`` so the test
runs without a display; it is skipped when the Adwaita theme is not installed.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

GUI_DIR = Path(__file__).resolve().parent.parent / "src" / "linguafix" / "gui"

# ``icon_name="foo-symbolic"`` and ``Gtk.Image.new_from_icon_name("foo")``.
_ICON_PATTERNS = [
    re.compile(r'icon_name\s*=\s*"([^"]+)"'),
    re.compile(r'new_from_icon_name\(\s*"([^"]+)"'),
    re.compile(r'ICON_NAME\s*=\s*"([^"]+)"'),
]
_ICON_THEME_DIRS = [
    Path("/usr/share/icons/Adwaita"),
    Path("/usr/share/icons/hicolor"),
]


def _collect_icon_names() -> set[str]:
    names: set[str] = set()
    for path in GUI_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in _ICON_PATTERNS:
            names.update(pattern.findall(text))
    return names


def _theme_installed() -> bool:
    return any(directory.is_dir() for directory in _ICON_THEME_DIRS)


def _icon_present(name: str) -> bool:
    for directory in _ICON_THEME_DIRS:
        if not directory.is_dir():
            continue
        for suffix in (".svg", ".png"):
            if next(directory.rglob(f"{name}{suffix}"), None) is not None:
                return True
    return False


def _gi_available() -> bool:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


@pytest.mark.skipif(not _theme_installed(), reason="no system icon theme installed")
def test_every_gui_icon_name_exists() -> None:
    names = _collect_icon_names()
    assert names, "no icon names found in the GUI package (parser out of date?)"
    missing = sorted(name for name in names if not _icon_present(name))
    assert not missing, f"GUI references icons absent from the theme: {missing}"


@pytest.mark.skipif(not _theme_installed(), reason="no system icon theme installed")
def test_every_tab_icon_name_exists() -> None:
    """The view-stack tab icons (``window.TAB_ICONS``) must exist in the theme.

    A tab icon that the theme lacks renders as a broken-image placeholder; the
    mapping is imported directly so this catches a value the regex parser above
    would miss inside a dict literal. GTK is required to import the window
    module, so the test is skipped when it is unavailable.
    """
    if not _gi_available():
        pytest.skip("GTK4 unavailable")
    from linguafix.gui.window import TAB_ICONS

    assert TAB_ICONS, "no tab icons defined"
    missing = sorted(name for name in TAB_ICONS.values() if not _icon_present(name))
    assert not missing, f"tab icons absent from the theme: {missing}"


@pytest.mark.skipif(not _gi_available(), reason="GTK4 unavailable")
def test_the_power_glyph_is_the_one_adwaita_ships() -> None:
    # Regression: ``power-symbolic`` does not exist in Adwaita 48 and rendered
    # as a broken image; the real name is ``system-shutdown-symbolic``.
    from linguafix.gui.widgets.big_toggle import ICON_NAME

    assert ICON_NAME == "system-shutdown-symbolic"


def test_big_toggle_falls_back_to_drawn_glyph(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the theme lacks the icon name, the button draws the glyph itself.

    A user theme that does not inherit Adwaita made ``new_from_icon_name`` show
    a broken-image placeholder; the fallback guarantees a real power symbol.
    Needs a display, like the other GUI tests (CI runs them under ``xvfb-run``).
    """
    if not _gi_available() or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("GTK4 or display unavailable")
    from linguafix.gui.widgets import big_toggle

    monkeypatch.setattr(big_toggle, "theme_has_icon", lambda *a, **k: False)
    button = big_toggle.BigToggle()
    assert isinstance(button._icon, big_toggle.PowerGlyph)
