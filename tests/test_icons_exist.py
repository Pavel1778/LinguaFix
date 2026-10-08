"""Every icon the GUI names must exist in the shipped Adwaita theme.

A wrong icon name does not raise: GTK silently falls back to a "broken image"
placeholder, so the button and its tabs simply look broken on a real desktop.
We therefore parse every ``icon_name=``/``new_from_icon_name(...)`` in the GUI
package and assert the name is present in the system icon theme.

Checked against the filesystem rather than a live ``Gtk.IconTheme`` so the test
runs without a display; it is skipped when the Adwaita theme is not installed.
"""

from __future__ import annotations

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


@pytest.mark.skipif(not _gi_available(), reason="GTK4 unavailable")
def test_the_power_glyph_is_the_one_adwaita_ships() -> None:
    # Regression: ``power-symbolic`` does not exist in Adwaita 48 and rendered
    # as a broken image; the real name is ``system-shutdown-symbolic``.
    from linguafix.gui.widgets.big_toggle import ICON_NAME

    assert ICON_NAME == "system-shutdown-symbolic"
