"""Editable list of user-dictionary words (brands, names, jargon).

The widget is a thin view over a list of words: the caller owns persistence
(the user dictionary file) and reports changes through ``on_change``. It also
exposes the raw import/export helpers so the file dialogs stay optional and the
word handling can be tested without a display.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402


def parse_words(text: str) -> list[str]:
    """Split ``text`` into words, dropping blanks, comments and duplicates."""
    words: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        word = raw.strip()
        if not word or word.startswith("#"):
            continue
        lowered = word.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        words.append(word)
    return words


class DictionaryList(Adw.PreferencesGroup):
    """A preferences group listing the words the daemon must never correct."""

    def __init__(
        self,
        title: str,
        description: str = "",
        words: list[str] | None = None,
        on_change: Callable[[list[str]], None] | None = None,
    ) -> None:
        super().__init__(title=title, description=description)
        self._on_change = on_change
        self._words: list[str] = list(words or [])
        self._filter = ""
        self._rows: list[Adw.ActionRow] = []

        entry = Adw.EntryRow(title="Добавить слово (бренд, имя, техножаргон)")
        add_button = Gtk.Button(icon_name="list-add-symbolic")
        add_button.add_css_class("flat")
        add_button.set_tooltip_text("Добавить")
        add_button.connect("clicked", self._on_add, entry)
        entry.add_suffix(add_button)
        entry.connect("entry-activated", self._on_entry_activated, entry)
        self._entry = entry
        self.add(entry)

        search = Gtk.SearchEntry()
        search.set_placeholder_text("Поиск по словарю")
        search.connect("search-changed", self._on_search_changed)
        self._search = search
        self.add(search)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        import_button = Gtk.Button(label="Загрузить из файла")
        import_button.add_css_class("flat")
        import_button.connect("clicked", self._on_import_clicked)
        export_button = Gtk.Button(label="Экспорт")
        export_button.add_css_class("flat")
        export_button.connect("clicked", self._on_export_clicked)
        buttons.append(import_button)
        buttons.append(export_button)
        self.add(buttons)

        self._list_group = Adw.PreferencesGroup()
        self.add(self._list_group)
        self._render()

    # --- rendering --------------------------------------------------------
    def _render(self) -> None:
        for row in self._rows:
            self._list_group.remove(row)
        self._rows = []
        needle = self._filter.lower()
        for word in self._words:
            if needle and needle not in word.lower():
                continue
            row = Adw.ActionRow(title=word)
            remove = Gtk.Button(icon_name="user-trash-symbolic")
            remove.add_css_class("flat")
            remove.set_tooltip_text("Удалить")
            remove.connect("clicked", self._on_remove, word)
            row.add_suffix(remove)
            self._list_group.add(row)
            self._rows.append(row)

    # --- editing ----------------------------------------------------------
    def _on_add(self, _button: Gtk.Button, entry: Adw.EntryRow) -> None:
        self.add_word(entry.get_text())
        entry.set_text("")

    def _on_entry_activated(self, entry: Adw.EntryRow, _entry: Adw.EntryRow) -> None:
        self.add_word(entry.get_text())
        entry.set_text("")

    def add_word(self, word: str) -> bool:
        """Add ``word`` if it is new; return whether the list changed."""
        cleaned = word.strip()
        if not cleaned or cleaned.lower() in {w.lower() for w in self._words}:
            return False
        self._words.append(cleaned)
        self._render()
        self._emit()
        return True

    def _on_remove(self, _button: Gtk.Button, word: str) -> None:
        if word in self._words:
            self._words.remove(word)
            self._render()
            self._emit()

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._filter = entry.get_text().strip()
        self._render()

    # --- import / export --------------------------------------------------
    def import_words(self, path: str) -> int:
        """Merge the words in ``path`` into the list; return how many were new."""
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError:
            return 0
        added = 0
        for word in parse_words(text):
            if self.add_word(word):
                added += 1
        return added

    def export_words(self, path: str) -> bool:
        """Write the current words to ``path``, one per line."""
        try:
            Path(path).write_text("\n".join(self._words) + ("\n" if self._words else ""), "utf-8")
        except OSError:
            return False
        return True

    def _on_import_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Загрузить словарь")
        dialog.open(None, None, self._on_import_done)

    def _on_import_done(self, dialog: Gtk.FileDialog, result: object) -> None:
        try:
            file = dialog.open_finish(result)
        except Exception:
            return
        path = file.get_path() if file is not None else None
        if path:
            self.import_words(path)

    def _on_export_clicked(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileDialog(title="Экспорт словаря", initial_name="dictionary.txt")
        dialog.save(None, None, self._on_export_done)

    def _on_export_done(self, dialog: Gtk.FileDialog, result: object) -> None:
        try:
            file = dialog.save_finish(result)
        except Exception:
            return
        path = file.get_path() if file is not None else None
        if path:
            self.export_words(path)

    # --- accessors --------------------------------------------------------
    def _emit(self) -> None:
        if self._on_change is not None:
            self._on_change(list(self._words))

    def set_words(self, words: list[str]) -> None:
        """Replace the whole list and redraw."""
        self._words = list(words)
        self._render()

    @property
    def words(self) -> list[str]:
        """Return the current words."""
        return list(self._words)

    @property
    def entry(self) -> Adw.EntryRow:
        """Expose the add entry for tests."""
        return self._entry

    @property
    def search(self) -> Gtk.SearchEntry:
        """Expose the search entry for tests."""
        return self._search
