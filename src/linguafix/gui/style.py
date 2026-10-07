"""Load the bundled GUI stylesheet into the default GTK display.

The stylesheet lives in this package (``style.css``) and is shipped in the
wheel and the ``.deb`` via ``package-data``. Loading it is best-effort: a
missing file or a display that cannot be reached must never stop the GUI from
starting, it just means the button falls back to the plain theme.
"""

from __future__ import annotations

import logging
from importlib import resources

logger = logging.getLogger(__name__)

CSS_PACKAGE = "linguafix.gui"
CSS_FILE = "style.css"


def load_stylesheet() -> bool:
    """Apply the bundled stylesheet to the default display.

    Returns:
        ``True`` when the stylesheet was applied, ``False`` when GTK or the
        file is unavailable (logged, never raised).
    """
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gdk, Gtk
    except (ImportError, ValueError):
        logger.debug("GTK unavailable; skipping stylesheet", exc_info=True)
        return False

    try:
        css = (resources.files(CSS_PACKAGE) / CSS_FILE).read_text(encoding="utf-8")
    except (OSError, ModuleNotFoundError):
        logger.warning("GUI stylesheet %s is missing; using the plain theme", CSS_FILE)
        return False

    provider = Gtk.CssProvider()
    provider.load_from_string(css)
    display = Gdk.Display.get_default()
    if display is None:  # pragma: no cover - only without a display
        return False
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    return True
