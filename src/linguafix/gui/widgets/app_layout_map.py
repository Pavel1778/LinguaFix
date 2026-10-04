"""Editable mapping of application name to a preferred keyboard layout."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402


class AppLayoutMap(Adw.PreferencesGroup):
    """A preferences group mapping an application to a layout.

    The caller owns persistence: changes are reported through ``on_change`` as
    a fresh ``{app: layout}`` mapping.
    """

    def __init__(
        self,
        title: str,
        description: str = "",
        mapping: dict[str, str] | None = None,
        on_change: Callable[[dict[str, str]], None] | None = None,
        on_detect: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__(title=title, description=description)
        self._on_change = on_change
        self._mapping: dict[str, str] = dict(mapping or {})
        self._on_detect = on_detect
        self._rows: list[Adw.ActionRow] = []

        self._app_entry = Adw.EntryRow(title="Имя процесса")
        if on_detect is not None:
            detect_button = Gtk.Button(label="Определить")
            detect_button.add_css_class("flat")
            detect_button.connect("clicked", self._on_detect_clicked)
            self._app_entry.add_suffix(detect_button)
        self.add(self._app_entry)

        self._layout_entry = Adw.EntryRow(title="Раскладка (например us или ru)")
        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.add_css_class("flat")
        add_button.set_tooltip_text("Добавить")
        add_button.connect("clicked", self._on_add)
        self._layout_entry.add_suffix(add_button)
        self._layout_entry.connect("entry-activated", lambda _row: self._on_add(None))
        self.add(self._layout_entry)

        self._render()

    def _render(self) -> None:
        for row in self._rows:
            self.remove(row)
        self._rows = []
        for app, layout in sorted(self._mapping.items()):
            row = Adw.ActionRow(title=app, subtitle=layout)
            remove = Gtk.Button(icon_name="user-trash-symbolic")
            remove.add_css_class("flat")
            remove.connect("clicked", self._on_remove, app)
            row.add_suffix(remove)
            self.add(row)
            self._rows.append(row)

    def _on_add(self, _button: Gtk.Button | None) -> None:
        app = self._app_entry.get_text().strip().lower()
        layout = self._layout_entry.get_text().strip().lower()
        if not app or not layout:
            return
        self._mapping[app] = layout
        self._app_entry.set_text("")
        self._layout_entry.set_text("")
        self._render()
        self._emit()

    def _on_remove(self, _button: Gtk.Button, app: str) -> None:
        if app in self._mapping:
            del self._mapping[app]
            self._render()
            self._emit()

    def _on_detect_clicked(self, _button: Gtk.Button) -> None:
        if self._on_detect is None:
            return
        name = self._on_detect()
        if name:
            self._app_entry.set_text(name)

    def _emit(self) -> None:
        if self._on_change is not None:
            self._on_change(dict(self._mapping))

    @property
    def mapping(self) -> dict[str, str]:
        """Return the current application-to-layout mapping."""
        return dict(self._mapping)
