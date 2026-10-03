"""Optional AppIndicator tray icon.

The tray is a convenience feature only. When ``AppIndicator3`` (provided by
``gir1.2-appindicator3-0.1``) is not installed the module logs an informational
message and the daemon keeps running without an icon.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

APP_ID = "linguafix"
ICON_NAME = "linguafix"


class TrayIcon:
    """A minimal AppIndicator icon with a status menu.

    Args:
        on_fix: Callback invoked by the "Fix now" menu entry.
        on_settings: Callback invoked by the "Settings" menu entry.
        on_quit: Callback invoked by the "Quit" menu entry.
    """

    def __init__(
        self,
        *,
        on_fix: Callable[[], None] | None = None,
        on_settings: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        self.on_fix = on_fix
        self.on_settings = on_settings
        self.on_quit = on_quit
        self._indicator: object | None = None

    @staticmethod
    def available() -> bool:
        """Return ``True`` when the GTK/AppIndicator stack can be imported."""
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3, Gtk  # noqa: F401
        except (ImportError, ValueError):
            return False
        return True

    def start(self) -> bool:
        """Create and show the tray icon.

        Returns:
            ``True`` when the icon was created, ``False`` when the required
            libraries are missing.
        """
        if not self.available():
            logger.info("AppIndicator3 is not available; tray icon disabled")
            return False

        try:
            import gi

            gi.require_version("Gtk", "3.0")
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3, Gtk

            indicator = AppIndicator3.Indicator.new(
                APP_ID,
                ICON_NAME,
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
            indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            indicator.set_menu(self._build_menu(Gtk))
            self._indicator = indicator
            logger.info("Tray icon started")
            return True
        except Exception:
            logger.warning("Failed to start tray icon", exc_info=True)
            return False

    def _build_menu(self, gtk_module: object) -> object:
        """Build the tray context menu."""
        menu = gtk_module.Menu()  # type: ignore[attr-defined]
        entries = [
            ("Статус: активен", None),
            ("Исправить сейчас", self.on_fix),
            ("Настройки", self.on_settings),
            ("Выход", self.on_quit),
        ]
        for label, callback in entries:
            item = gtk_module.MenuItem(label=label)  # type: ignore[attr-defined]
            if callback is not None:
                item.connect("activate", lambda _item, cb=callback: cb())
            else:
                item.set_sensitive(False)
            menu.append(item)
        menu.show_all()
        return menu

    def stop(self) -> None:
        """Hide the tray icon."""
        if self._indicator is not None:
            try:
                import gi

                gi.require_version("AppIndicator3", "0.1")
                from gi.repository import AppIndicator3

                self._indicator.set_status(  # type: ignore[attr-defined]
                    AppIndicator3.IndicatorStatus.PASSIVE
                )
            except Exception:
                logger.debug("Failed to stop tray icon", exc_info=True)
            self._indicator = None
