"""Main application window: tabs for home, settings and advanced options."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GObject, Gtk  # noqa: E402

from .about_page import build_about_window  # noqa: E402
from .advanced_page import AdvancedPage  # noqa: E402
from .dictionary_page import DictionaryPage  # noqa: E402
from .history_page import HistoryPage  # noqa: E402
from .home_page import HomePage  # noqa: E402
from .settings_page import SettingsPage  # noqa: E402
from .state import GuiState  # noqa: E402
from .typo_page import TypoPage  # noqa: E402


def _scrollable(page: Gtk.Widget) -> Gtk.ScrolledWindow:
    """Wrap a plain page so overflow scrolls instead of breaking the layout.

    ``Adw.PreferencesPage`` already scrolls; the plain ``Gtk.Box`` pages
    (home, history) do not, so without this their content would overflow and
    squash when the window is made smaller.
    """
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_child(page)
    return scroll


class LinguaFixWindow(Adw.ApplicationWindow):
    """The top-level window with a responsive ``ViewSwitcher`` header."""

    def __init__(self, state: GuiState, application: Adw.Application) -> None:
        super().__init__(application=application, title="LinguaFix")
        self.set_default_size(640, 760)
        self.set_size_request(360, 480)
        self._state = state

        self._toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        self._toasts.set_child(toolbar)
        self.set_content(self._toasts)

        header = Adw.HeaderBar()
        self._stack = Adw.ViewStack()
        # Let each page dictate the stack's *height* so a tall page cannot force
        # a huge natural size that then refuses to shrink (the "window resizes
        # itself and breaks" symptom). Width stays homogeneous so the header
        # switcher labels do not jump.
        self._stack.set_property("vhomogeneous", False)
        # A title switcher shows the tabs in the header while there is room and
        # collapses them to the window title when there is not; the bar below
        # carries the full labels in that narrow case. ``title-visible`` is the
        # single source of truth for the bottom bar's ``reveal``: a second writer
        # (a manual width handler) fought this binding and made the bar flicker.
        self._switcher_title = Adw.ViewSwitcherTitle(stack=self._stack)
        header.set_title_widget(self._switcher_title)

        menu = Gio.Menu()
        menu.append("О программе", "win.about")
        menu.append("Открыть config.toml", "win.open-config")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_button)
        toolbar.add_top_bar(header)

        self._switcher_bar = Adw.ViewSwitcherBar(stack=self._stack)
        self._switcher_title.bind_property(
            "title-visible",
            self._switcher_bar,
            "reveal",
            GObject.BindingFlags.SYNC_CREATE,
        )
        toolbar.add_bottom_bar(self._switcher_bar)

        self._home = HomePage(state, self._toasts)
        self._settings = SettingsPage(state, on_saved=self._on_saved)
        self._dictionary = DictionaryPage(state, on_saved=self._on_saved)
        self._typo = TypoPage(state, self._toasts, on_saved=self._on_saved)
        self._history = HistoryPage(state, self._toasts)
        self._advanced = AdvancedPage(state, on_saved=self._on_saved)

        self._stack.add_titled(_scrollable(self._home), "home", "Главная")
        self._stack.add_titled(self._settings, "settings", "Настройки")
        self._stack.add_titled(self._dictionary, "dictionary", "Словарь")
        self._stack.add_titled(self._typo, "typo", "Т9")
        self._stack.add_titled(_scrollable(self._history), "history", "История")
        # The advanced page is created once, here, so the stack is never
        # restructured at runtime (adding a page later changed the homogeneous
        # width and made the switcher bar churn). It is simply hidden from the
        # switcher until the user reveals it, keeping the basic settings clean.
        self._advanced_page = self._stack.add_titled(self._advanced, "advanced", "Продвинутые")
        self._advanced_page.set_visible(False)
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
        # The page already exists in the stack; only reveal it in the switcher
        # and switch to it, so no runtime restructuring is needed.
        self._advanced_page.set_visible(True)
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
    def switcher_bar(self) -> Adw.ViewSwitcherBar:
        """Expose the narrow-window switcher for tests."""
        return self._switcher_bar

    @property
    def home(self) -> HomePage:
        """Expose the home page for tests."""
        return self._home

    @property
    def settings_page(self) -> SettingsPage:
        """Expose the settings page for tests."""
        return self._settings

    @property
    def dictionary_page(self) -> DictionaryPage:
        """Expose the dictionary page for tests."""
        return self._dictionary

    @property
    def typo_page(self) -> TypoPage:
        """Expose the typo-correction page for tests."""
        return self._typo

    @property
    def advanced_page(self) -> Adw.ViewStackPage:
        """Expose the advanced stack page (for reveal/resize tests)."""
        return self._advanced_page

    @property
    def history_page(self) -> HistoryPage:
        """Expose the history page for tests."""
        return self._history
