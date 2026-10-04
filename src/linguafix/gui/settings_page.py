"""Basic settings page (always visible)."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from ..config import SUPPORTED_LANGUAGES  # noqa: E402
from .prefs_base import BoundPreferencesPage  # noqa: E402
from .state import LANGUAGE_LABELS, MODE_LABELS, GuiState  # noqa: E402
from .widgets.hotkey_row import HotkeyRow  # noqa: E402

MODE_ORDER = ("auto", "manual", "hybrid")


class SettingsPage(BoundPreferencesPage):
    """The default settings tab: mode, hotkeys, languages and notifications."""

    def __init__(self, state: GuiState, on_saved: Callable[[str], None] | None = None) -> None:
        super().__init__(state, on_saved)
        self._build_mode_group()
        self._build_hotkeys_group()
        self._build_languages_group()
        self._build_notifications_group()

    # --- groups -----------------------------------------------------------
    def _build_mode_group(self) -> None:
        group = Adw.PreferencesGroup(title="Основные")
        self.add_combo(
            group,
            "Режим работы",
            list(MODE_ORDER),
            [MODE_LABELS[m] for m in MODE_ORDER],
            self._config.mode,
            self._on_mode_selected,
            subtitle="Авто исправляет сразу, ручной — только по хоткею",
        )
        self.add(group)

    def _on_mode_selected(self, mode: str) -> None:
        self._config.mode = mode
        self._save(f"Режим изменён на {MODE_LABELS.get(mode, mode)}")

    def _build_hotkeys_group(self) -> None:
        group = Adw.PreferencesGroup(
            title="Хоткеи",
            description="Нажмите «Изменить», затем нужную комбинацию. Esc — отмена.",
        )
        self.add_switch(group, "Хоткеи включены", "hotkeys_enabled")
        self._hotkey_fix = HotkeyRow(
            "Исправить последнее слово",
            "Двойной Shift по умолчанию. Нажмите «Изменить» и дважды нажмите "
            "нужный модификатор (Shift/Ctrl/Alt) или задайте комбинацию.",
            self._config.hotkey_fix_last_word,
            on_change=self._make_hotkey_handler("hotkey_fix_last_word"),
        )
        group.add(self._hotkey_fix)
        self._hotkey_undo = HotkeyRow(
            "Отменить последнее исправление",
            "Работает только в режиме «Гибрид»",
            self._config.hotkey_undo_last_fix,
            on_change=self._make_hotkey_handler("hotkey_undo_last_fix"),
        )
        group.add(self._hotkey_undo)
        self.add(group)

    def _make_hotkey_handler(self, field: str) -> Callable[[str], None]:
        def handler(value: str) -> None:
            setattr(self._config, field, value)
            self._save("Хоткей сохранён")

        return handler

    def _build_languages_group(self) -> None:
        group = Adw.PreferencesGroup(
            title="Языки",
            description="Какие раскладки LinguaFix должен распознавать",
        )
        self._language_rows: dict[str, Adw.SwitchRow] = {}
        for lang in SUPPORTED_LANGUAGES:
            row = Adw.SwitchRow(title=LANGUAGE_LABELS.get(lang, lang))
            row.set_active(lang in self._config.languages)
            row.connect("notify::active", self._on_language, lang)
            group.add(row)
            self._language_rows[lang] = row
        self.add(group)

    def _on_language(self, row: Adw.SwitchRow, _param: object, lang: str) -> None:
        active = row.get_active()
        languages = [lang_ for lang_ in self._config.languages if lang_ != lang]
        if active:
            languages.append(lang)
        self._config.languages = languages
        try:
            self._config.validate()
        except ValueError:
            # Never leave the user with zero languages enabled.
            row.set_active(lang in self._state.config.languages)
            return
        self._state.save()
        if self._on_saved is not None:
            self._on_saved("Языки сохранены")

    def _build_notifications_group(self) -> None:
        group = Adw.PreferencesGroup(title="Уведомления и тайминги")
        self.add_switch(group, "Уведомления при исправлении", "notify_on_fix")
        self.add_spin(
            group,
            "Таймаут анализа, с",
            "analysis_timeout",
            lower=0.3,
            upper=3.0,
            step=0.1,
            digits=1,
        )
        self.add(group)

    @property
    def language_rows(self) -> dict[str, Adw.SwitchRow]:
        """Expose the language switches for tests."""
        return self._language_rows
