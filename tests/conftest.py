"""Shared pytest fixtures for the LinguaFix test-suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from linguafix.converter import LayoutConverter
from linguafix.detector import LanguageDetector

# Minimal stop-word list used across tests.
STOP_WORDS = ["password", "login", "token", "secret", "sudo"]

# The system PyGObject lives outside the virtualenv on Debian; make it visible
# so the GUI modules import when the tests run from the project venv.
_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
if os.path.isdir(_DIST_PACKAGES) and _DIST_PACKAGES not in sys.path:
    sys.path.append(_DIST_PACKAGES)


def _gtk_usable() -> bool:
    """Return ``True`` when GTK can be imported and a display is reachable.

    GTK aborts the process (SIGSEGV) when it is initialised without a display,
    so the GUI tests are skipped unless ``DISPLAY`` or ``WAYLAND_DISPLAY`` is
    set (the CI/dev setup uses ``xvfb-run``).
    """
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


def _gtk_stack_importable() -> bool:
    """Return ``True`` when the GTK modules can be imported (no display needed)."""
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


requires_gtk = pytest.mark.skipif(
    not _gtk_usable(), reason="GTK4/libadwaita or display unavailable"
)
requires_gtk_stack = pytest.mark.skipif(
    not _gtk_stack_importable(), reason="GTK4/libadwaita unavailable"
)


@pytest.fixture
def converter() -> LayoutConverter:
    """Return a converter backed by the bundled layout definitions."""
    return LayoutConverter()


@pytest.fixture
def detector(converter: LayoutConverter) -> LanguageDetector:
    """Return a detector using the bundled corpora and test stop words."""
    return LanguageDetector(converter=converter, stop_words=STOP_WORDS, min_word_length=3)


@pytest.fixture
def tmp_config_path(tmp_path: Path) -> Path:
    """Return a temporary path for a config file."""
    return tmp_path / "linguafix" / "config.toml"
