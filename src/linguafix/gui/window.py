"""Main application window: tabs for home, settings and advanced options."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from .about_page import build_about_window  # noqa: E402
from .advanced_page import AdvancedPage  # noqa: E402
from .home_page import HomePage  # noqa: E402
from .settings_page import SettingsPage  # noqa: E402
from .state import GuiState  # noqa: E402


class LinguaFixWindow(Adw.ApplicationWindow):
    """The top-level window with a ``ViewSwitcher`` header."""

    def __init__(self, state: GuiState, application: Adw.Application) -> None:
        super().__init__(application=application, title="LinguaFix")
        self.set_default_size(560, 720)
        self._state = state

        self._toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        self._toasts.set_child(toolbar)
        self.set_content(self._toasts)

        header = Adw.HeaderBar()
        self._stack = Adw.ViewStack()
        switcher = Adw.ViewSwitcher(stack=self._stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(switcher)

        menu = Gio.Menu()
        menu.append("О программе", "win.about")
        menu.append("Открыть config.toml", "win.open-config")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_button)
        toolbar.add_top_bar(header)

        self._home = HomePage(state, self._toasts)
        self._settings = SettingsPage(state, on_saved=self._on_saved)
        self._advanced = AdvancedPage(state, on_saved=self._on_saved)

        self._stack.add_titled(self._home, "home", "Главная")
        self._stack.add_titled(self._settings, "settings", "Настройки")
        # The advanced page is added to the switcher only when revealed, so the
        # basic settings stay uncluttered by default.
        self._advanced_visible = False
        toolbar.set_content(self._stack)

        self._install_actions()

    def _install_actions(self) -> None:
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

        open_config = Gio.SimpleAction.new("open-config", None)
        open_config.connect("activate", self._on_open_config)
        self.add_action(open_config)

        self._show_advanced_action = Gio.SimpleAction.new("show-advanced", None)
        self._show_advanced_action.connect("activate", self._on_show_advanced)
        self.add_action(self._show_advanced_action)
        self._settings.add(self._make_advanced_group())

    def _make_advanced_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        button = Gtk.Button(label="Показать продвинутые настройки")
        button.set_halign(Gtk.Align.CENTER)
        button.add_css_class("pill")
        button.connect("clicked", lambda _b: self._on_show_advanced(None, None))
        group.add(button)
        return group

    def _on_show_advanced(self, _action: object, _param: object) -> None:
        if not self._advanced_visible:
            self._stack.add_titled(self._advanced, "advanced", "Продвинутые")
            self._advanced_visible = True
        self._stack.set_visible_child_name("advanced")

    def _on_about(self, _action: object, _param: object) -> None:
        build_about_window(self).present(self)

    def _on_open_config(self, _action: object, _param: object) -> None:
        from ..config import config_path

        try:
            import subprocess

            subprocess.run(["xdg-open", str(config_path())], check=False, timeout=5)
        except (OSError, subprocess.SubprocessError):  # pragma: no cover - desktop only
            self._toasts.add_toast(Adw.Toast(title="Не удалось открыть config.toml"))

    def _on_saved(self, message: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=message, timeout=2))

    @property
    def stack(self) -> Adw.ViewStack:
        """Expose the view stack for tests."""
        return self._stack

    @property
    def home(self) -> HomePage:
        """Expose the home page for tests."""
        return self._home

    @property
    def settings_page(self) -> SettingsPage:
        """Expose the settings page for tests."""
        return self._settings
