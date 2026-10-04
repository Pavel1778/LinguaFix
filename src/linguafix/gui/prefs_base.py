"""Shared base for the settings pages.

Provides small helpers that bind GTK rows to :class:`~linguafix.config.Config`
fields and persist through :class:`~linguafix.gui.state.GuiState`. Keeping the
binding in one place means the pages contain only layout, and every write goes
through the same validated ``save_config`` path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .state import GuiState  # noqa: E402


class BoundPreferencesPage(Adw.PreferencesPage):
    """Base class with field-binding helpers."""

    def __init__(self, state: GuiState, on_saved: Callable[[str], None] | None = None) -> None:
        super().__init__()
        self._state = state
        self._on_saved = on_saved
        self._config = state.config

    def _save(self, message: str) -> None:
        try:
            self._state.save()
        except ValueError:
            return
        if self._on_saved is not None:
            self._on_saved(message)

    def add_switch(
        self, group: Adw.PreferencesGroup, title: str, field: str, subtitle: str = ""
    ) -> Adw.SwitchRow:
        """Add a switch bound to a boolean field."""
        row = Adw.SwitchRow(title=title, subtitle=subtitle)
        row.set_active(bool(getattr(self._config, field)))
        row.connect("notify::active", self._on_switch, field)
        group.add(row)
        return row

    def _on_switch(self, row: Adw.SwitchRow, _param: object, field: str) -> None:
        setattr(self._config, field, row.get_active())
        self._save("Настройки сохранены")

    def add_spin(
        self,
        group: Adw.PreferencesGroup,
        title: str,
        field: str,
        *,
        lower: float,
        upper: float,
        step: float,
        digits: int = 0,
        subtitle: str = "",
    ) -> Adw.SpinRow:
        """Add a spin button bound to a numeric field."""
        adjustment = Gtk.Adjustment(
            value=float(getattr(self._config, field)),
            lower=lower,
            upper=upper,
            step_increment=step,
        )
        row = Adw.SpinRow(title=title, subtitle=subtitle, adjustment=adjustment, digits=digits)
        row.connect("notify::value", self._on_spin, field)
        group.add(row)
        return row

    def _on_spin(self, row: Adw.SpinRow, _param: object, field: str) -> None:
        value: Any = row.get_value()
        current = getattr(self._config, field)
        setattr(self._config, field, int(value) if isinstance(current, int) else float(value))
        self._save("Настройки сохранены")

    def add_combo(
        self,
        group: Adw.PreferencesGroup,
        title: str,
        options: list[str],
        labels: list[str],
        current: str,
        on_selected: Callable[[str], None],
        subtitle: str = "",
    ) -> Adw.ComboRow:
        """Add a combo row over ``options`` with display ``labels``."""
        row = Adw.ComboRow(title=title, subtitle=subtitle, model=Gtk.StringList.new(labels))
        if current in options:
            row.set_selected(options.index(current))
        row.connect("notify::selected", self._on_combo, options, on_selected)
        group.add(row)
        return row

    def _on_combo(
        self,
        row: Adw.ComboRow,
        _param: object,
        options: list[str],
        on_selected: Callable[[str], None],
    ) -> None:
        index = row.get_selected()
        if 0 <= index < len(options):
            on_selected(options[index])

    def add_entry(
        self,
        group: Adw.PreferencesGroup,
        title: str,
        field: str,
        *,
        subtitle: str = "",
        on_changed: Callable[[str], bool] | None = None,
    ) -> Adw.EntryRow:
        """Add a text entry bound to a string field.

        ``on_changed`` may validate the value and return ``False`` to reject it
        (for example an invalid regular expression); the field is then not
        written.
        """
        row = Adw.EntryRow(title=title)
        row.set_text(str(getattr(self._config, field)))
        row.connect("changed", self._on_entry, field, on_changed)
        group.add(row)
        return row

    def _on_entry(
        self,
        row: Adw.EntryRow,
        field: str,
        on_changed: Callable[[str], bool] | None,
    ) -> None:
        value = row.get_text()
        if on_changed is not None and not on_changed(value):
            return
        setattr(self._config, field, value)
        self._save("Настройки сохранены")
