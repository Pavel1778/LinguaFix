"""Settings backup group: export/import the whole configuration (Stage 11)."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402


class BackupGroup(Adw.PreferencesGroup):
    """A preferences group with buttons to export and import a backup.

    The caller owns the actual file I/O through the ``on_export`` /
    ``on_import`` callbacks, so the widget stays display-free and testable.
    """

    def __init__(
        self,
        title: str = "Резервная копия",
        description: str = "Настройки, словарь и сниппеты одним файлом",
        on_export: Callable[[str], bool] | None = None,
        on_import: Callable[[str], bool] | None = None,
        on_notify: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(title=title, description=description)
        self._on_export = on_export
        self._on_import = on_import
        self._on_notify = on_notify

        row = Adw.ActionRow(title="Экспорт / импорт настроек")
        export_button = Gtk.Button(label="Экспорт")
        export_button.add_css_class("flat")
        export_button.connect("clicked", self._on_export_clicked)
        import_button = Gtk.Button(label="Импорт")
        import_button.add_css_class("flat")
        import_button.connect("clicked", self._on_import_clicked)
        row.add_suffix(export_button)
        row.add_suffix(import_button)
        self.add(row)

    def _notify(self, message: str) -> None:
        if self._on_notify is not None:
            self._on_notify(message)

    def _on_export_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Сохранить настройки", initial_name="linguafix-backup.json")
        dialog.save(None, None, self._on_export_done)

    def _on_export_done(self, dialog: Gtk.FileDialog, result: object) -> None:
        try:
            file = dialog.save_finish(result)
        except Exception:
            return
        path = file.get_path() if file is not None else None
        if not path or self._on_export is None:
            return
        self._notify("Настройки сохранены" if self._on_export(path) else "Не удалось сохранить")

    def _on_import_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Восстановить настройки")
        dialog.open(None, None, self._on_import_done)

    def _on_import_done(self, dialog: Gtk.FileDialog, result: object) -> None:
        try:
            file = dialog.open_finish(result)
        except Exception:
            return
        path = file.get_path() if file is not None else None
        if not path or self._on_import is None:
            return
        self._notify(
            "Настройки восстановлены" if self._on_import(path) else "Не удалось восстановить"
        )
