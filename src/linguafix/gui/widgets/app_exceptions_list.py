"""Editable list of per-application exceptions."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402


class AppExceptionsList(Adw.PreferencesGroup):
    """A preferences group listing application process names.

    The caller owns persistence: the widget reports the new list through
    ``on_change`` and rebuilds its rows from :meth:`set_apps`.
    """

    def __init__(
        self,
        title: str,
        description: str = "",
        apps: list[str] | None = None,
        on_change: Callable[[list[str]], None] | None = None,
        detect_label: str | None = None,
        on_detect: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__(title=title, description=description)
        self._on_change = on_change
        self._apps: list[str] = list(apps or [])
        self._on_detect = on_detect
        self._rows: list[Adw.ActionRow] = []

        entry = Adw.EntryRow(title="Имя процесса")
        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.add_css_class("flat")
        add_button.set_tooltip_text("Добавить")
        add_button.connect("clicked", self._on_add, entry)
        entry.add_suffix(add_button)
        if on_detect is not None:
            detect_button = Gtk.Button(label=detect_label or "Определить текущее приложение")
            detect_button.add_css_class("flat")
            detect_button.connect("clicked", self._on_detect_clicked, entry)
            entry.add_suffix(detect_button)
        self._entry = entry
        self.add(entry)

        self._list_group = Adw.PreferencesGroup()
        self._render()

    def _render(self) -> None:
        for row in self._rows:
            self.remove(row)
        self._rows = []
        for app in self._apps:
            row = Adw.ActionRow(title=app)
            remove = Gtk.Button(icon_name="user-trash-symbolic")
            remove.add_css_class("flat")
            remove.connect("clicked", self._on_remove, app)
            row.add_suffix(remove)
            self.add(row)
            self._rows.append(row)

    def _on_add(self, _button: Gtk.Button, entry: Adw.EntryRow) -> None:
        name = entry.get_text().strip()
        if not name or name in self._apps:
            return
        self._apps.append(name)
        entry.set_text("")
        self._render()
        self._emit()

    def _on_remove(self, _button: Gtk.Button, app: str) -> None:
        if app in self._apps:
            self._apps.remove(app)
            self._render()
            self._emit()

    def _on_detect_clicked(self, _button: Gtk.Button, entry: Adw.EntryRow) -> None:
        if self._on_detect is None:
            return
        name = self._on_detect()
        if name:
            entry.set_text(name)

    def _emit(self) -> None:
        if self._on_change is not None:
            self._on_change(list(self._apps))

    def set_apps(self, apps: list[str]) -> None:
        """Replace the whole list and redraw."""
        self._apps = list(apps)
        self._render()

    @property
    def apps(self) -> list[str]:
        """Return the current list of exceptions."""
        return list(self._apps)
