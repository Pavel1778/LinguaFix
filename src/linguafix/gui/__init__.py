"""GTK4 + libadwaita graphical interface for LinguaFix.

The GUI is a separate process: it talks to the daemon through ``systemctl
--user`` and the :mod:`linguafix.cli` helpers, never through in-process state.
If the GUI crashes the daemon keeps running, and if GTK is not installed the
rest of the application is unaffected.

:func:`main` is the ``linguafix gui`` entry point. It prints a friendly message
and returns 1 when the GTK stack is missing instead of raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MISSING_STACK_MESSAGE = (
    "Для графического интерфейса нужны GTK4 и libadwaita.\n"
    "Установите их командой:\n"
    "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1\n"
    "Демон и CLI работают без них."
)


def gtk_available() -> bool:
    """Return ``True`` when GTK4 and libadwaita can be imported."""
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Run the GTK application.

    Args:
        argv: Optional argument vector passed through to GTK.

    Returns:
        The process exit code. ``1`` when the GTK stack is unavailable.
    """
    if not gtk_available():
        print(MISSING_STACK_MESSAGE)
        return 1

    # The GUI is its own process: give it a logger (a dedicated gui.log) so a
    # failed start/stop or a missing daemon leaves a trace instead of vanishing.
    from ..logging_setup import GUI_LOG_FILE_NAME, setup_logging

    setup_logging(file_name=GUI_LOG_FILE_NAME)
    logger.debug("Starting LinguaFix GUI")

    from .app import LinguaFixApplication

    app = LinguaFixApplication()
    return int(app.run(argv or []))
