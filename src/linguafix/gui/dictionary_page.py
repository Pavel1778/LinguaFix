"""User-dictionary page: words that must never be corrected.

Brands, names and technical jargon are often absent from the bundled frequency
corpora, so the detector cannot know that a converted form (``муксуд`` ->
``vercel``) is the intended word. Teaching the word here makes the conversion a
known-good result: the detector then applies it instead of staying silent.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..dictionary import (  # noqa: E402
    load_user_dictionary,
    save_user_dictionary,
    user_dictionary_path,
)
from .prefs_base import BoundPreferencesPage  # noqa: E402
from .state import GuiState  # noqa: E402
from .widgets.dictionary_list import DictionaryList  # noqa: E402

logger = logging.getLogger(__name__)


class DictionaryPage(BoundPreferencesPage):
    """A preferences page for the user dictionary."""

    def __init__(self, state: GuiState, on_saved: Callable[[str], None] | None = None) -> None:
        super().__init__(state, on_saved)
        self._path = str(user_dictionary_path(self._config.dictionary_custom_path))

        self._dictionary = DictionaryList(
            "Мои слова",
            "Эти слова никогда не исправляются, а их конвертация считается верной "
            "(например, «муксуд» → «vercel»).",
            load_user_dictionary(self._config.dictionary_custom_path),
            on_change=self._on_words_changed,
        )
        self.add(self._dictionary)

        group = Adw.PreferencesGroup()
        self._status = Gtk.Label(label=f"Файл: {self._path}")
        self._status.set_xalign(0.0)
        self._status.add_css_class("dim-label")
        group.add(self._status)

        apply_button = Gtk.Button(label="Применить к демону")
        apply_button.add_css_class("pill")
        apply_button.set_halign(Gtk.Align.START)
        apply_button.set_tooltip_text("Перечитать словарь без перезапуска службы")
        apply_button.connect("clicked", self._on_apply)
        group.add(apply_button)
        self.add(group)

    def _on_words_changed(self, words: list[str]) -> None:
        save_user_dictionary(words, self._config.dictionary_custom_path)
        self._status.set_label(f"Слов: {len(words)} · Файл: {self._path}")

    def _on_apply(self, _button: Gtk.Button) -> None:
        if self._state.reload_config():
            if self._on_saved is not None:
                self._on_saved("Словарь применён")
        elif self._on_saved is not None:
            self._on_saved("Не удалось перечитать демон")

    @property
    def dictionary(self) -> DictionaryList:
        """Expose the dictionary widget for tests."""
        return self._dictionary
