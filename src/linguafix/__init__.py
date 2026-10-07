"""LinguaFix — automatic keyboard layout switcher for Debian GNOME.

The package provides a background daemon that reads raw keyboard events via
``evdev``, detects when text was typed in the wrong layout and transparently
fixes it by replacing the text and switching the active layout.

The project is inspired by Caramba Switcher for Windows.
"""

from __future__ import annotations

__version__ = "0.2.1"
__all__ = ["__version__"]
