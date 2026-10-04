"""Advanced settings page, hidden behind a button on the main window."""

from __future__ import annotations

import re
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..config import DEFAULT_FIX_HOTKEY, DEFAULT_UNDO_HOTKEY, config_path  # noqa: E402
from .prefs_base import BoundPreferencesPage  # noqa: E402
from .state import GuiState  # noqa: E402
from .widgets.app_exceptions_list import AppExceptionsList  # noqa: E402
from .widgets.hotkey_row import HotkeyRow  # noqa: E402

DICTIONARY_OPTIONS = ("1000", "5000", "10000")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class AdvancedPage(BoundPreferencesPage):
    """Detector, trigger, injection, exception, dictionary and log settings."""

    def __init__(self, state: GuiState, on_saved: Callable[[str], None] | None = None) -> None:
        super().__init__(state, on_saved)
        self._build_detector_group()
        self._build_triggers_group()
        self._build_injection_group()
        self._build_exceptions_group()
        self._build_dictionary_group()
        self._build_hotkeys_group()
        self._build_notifications_group()
        self._build_logs_group()

    # --- detector ---------------------------------------------------------
    def _build_detector_group(self) -> None:
        group = Adw.PreferencesGroup(title="Детектор")
        self.add_spin(
            group, "Минимальная длина слова", "min_word_length", lower=1, upper=10, step=1
        )
        self.add_spin(
            group,
            "Порог уверенности",
            "confidence_threshold",
            lower=0.5,
            upper=0.95,
            step=0.05,
            digits=2,
        )
        self.add_switch(group, "Контекстный анализ", "context_analysis")
        self.add_spin(
            group,
            "Вес контекста",
            "context_weight",
            lower=0.0,
            upper=1.0,
            step=0.05,
            digits=2,
        )
        self.add_switch(group, "Не трогать СЛОВА_КАПСОМ", "ignore_all_caps")
        self.add_switch(group, "Не трогать слова с цифрами", "ignore_with_digits")
        self.add_switch(group, "Не трогать email и URL", "ignore_emails_urls")
        self._regex_entry = self.add_entry(
            group,
            "Свой regex-пропуск",
            "custom_skip_regex",
            on_changed=self._validate_regex,
        )
        self.add(group)

    def _validate_regex(self, value: str) -> bool:
        if not value:
            return True
        try:
            re.compile(value)
        except re.error:
            self._regex_entry.add_css_class("error")
            if self._on_saved is not None:
                self._on_saved("Некорректное регулярное выражение")
            return False
        self._regex_entry.remove_css_class("error")
        return True

    # --- triggers ---------------------------------------------------------
    def _build_triggers_group(self) -> None:
        group = Adw.PreferencesGroup(title="Триггеры")
        self.add_switch(group, "По пробелу", "on_space")
        self.add_switch(group, "По Enter", "on_enter")
        self.add_switch(group, "По Tab", "on_tab")
        self.add_switch(group, "По знакам препинания", "on_punctuation")
        self.add_entry(group, "Символы-разделители", "punctuation_chars")
        self.add_spin(
            group,
            "Таймаут анализа, с",
            "analysis_timeout",
            lower=0.3,
            upper=3.0,
            step=0.1,
            digits=1,
        )
        self.add_spin(
            group,
            "Пауза после Backspace, мс",
            "backspace_settle_ms",
            lower=0,
            upper=200,
            step=5,
        )
        self.add_spin(
            group,
            "Пауза после триггера (пробел/Enter), мс",
            "trigger_settle_ms",
            lower=0,
            upper=200,
            step=5,
        )
        self.add(group)

    # --- injection --------------------------------------------------------
    def _build_injection_group(self) -> None:
        group = Adw.PreferencesGroup(title="Инъекция")
        self.add_spin(
            group, "Максимальный размер буфера", "max_buffer_size", lower=50, upper=1000, step=10
        )
        self.add_spin(
            group, "Глубина истории отмены", "undo_history_depth", lower=1, upper=10, step=1
        )
        self.add_spin(group, "Окно отмены, с", "undo_window_seconds", lower=3, upper=60, step=1)
        self.add(group)

    # --- exceptions -------------------------------------------------------
    def _build_exceptions_group(self) -> None:
        self._exceptions = AppExceptionsList(
            "Исключения приложений",
            "В этих приложениях автокоррекция отключена",
            self._config.exceptions_apps,
            on_change=self._on_exceptions_changed,
            on_detect=self._detect_current_app,
        )
        self.add(self._exceptions)
        self._force_manual = AppExceptionsList(
            "Исправлять даже в ручном режиме",
            "Эти приложения исправляются автоматически в режиме «Ручной»",
            self._config.exceptions_force_in_manual,
            on_change=self._on_force_manual_changed,
        )
        self.add(self._force_manual)

    def _on_exceptions_changed(self, apps: list[str]) -> None:
        self._config.exceptions_apps = apps
        self._save("Исключения сохранены")

    def _on_force_manual_changed(self, apps: list[str]) -> None:
        self._config.exceptions_force_in_manual = apps
        self._save("Исключения сохранены")

    @staticmethod
    def _detect_current_app() -> str | None:
        """Best-effort active-window process name via GNOME Shell's D-Bus."""
        try:
            from ..app_focus import get_active_app
        except ImportError:  # pragma: no cover - defensive
            return None
        return get_active_app()

    # --- dictionaries -----------------------------------------------------
    def _build_dictionary_group(self) -> None:
        group = Adw.PreferencesGroup(title="Словари")
        self.add_combo(
            group,
            "Размер словаря",
            list(DICTIONARY_OPTIONS),
            [f"{size} слов" for size in DICTIONARY_OPTIONS],
            str(self._config.dictionary_size),
            self._on_dictionary_size,
        )
        self.add_entry(group, "Свой словарь (путь)", "dictionary_custom_path")
        self.add(group)

    def _on_dictionary_size(self, value: str) -> None:
        self._config.dictionary_size = int(value)
        self._save("Словарь сохранён")

    # --- hotkeys ----------------------------------------------------------
    def _build_hotkeys_group(self) -> None:
        group = Adw.PreferencesGroup(title="Хоткеи")
        self._toggle_row = HotkeyRow(
            "Переключить режим",
            "",
            self._config.hotkey_toggle_mode,
            on_change=self._make_hotkey_handler("hotkey_toggle_mode"),
        )
        group.add(self._toggle_row)
        self._reload_row = HotkeyRow(
            "Перечитать конфигурацию",
            "",
            self._config.hotkey_reload_config,
            on_change=self._make_hotkey_handler("hotkey_reload_config"),
        )
        group.add(self._reload_row)
        self.add_switch(group, "Не передавать хоткей в приложение", "hotkey_swallow")
        reset = Gtk.Button(label="Сбросить к дефолтным")
        reset.connect("clicked", self._on_reset_hotkeys)
        reset.set_halign(Gtk.Align.START)
        reset.add_css_class("flat")
        group.add(reset)
        self.add(group)

    def _make_hotkey_handler(self, field: str) -> Callable[[str], None]:
        def handler(value: str) -> None:
            setattr(self._config, field, value)
            self._save("Хоткей сохранён")

        return handler

    def _on_reset_hotkeys(self, _button: Gtk.Button) -> None:
        # The fix/undo rows live on the Settings page, so only the two rows on
        # this page are redrawn here; the config fields are all reset.
        self._config.hotkey_fix_last_word = DEFAULT_FIX_HOTKEY
        self._config.hotkey_undo_last_fix = DEFAULT_UNDO_HOTKEY
        self._config.hotkey_toggle_mode = ""
        self._config.hotkey_reload_config = "CTRL+SHIFT+R"
        self._config.hotkey = DEFAULT_FIX_HOTKEY
        self._toggle_row.set_value("")
        self._reload_row.set_value("CTRL+SHIFT+R")
        self._save("Хоткеи сброшены")

    # --- notifications ----------------------------------------------------
    def _build_notifications_group(self) -> None:
        group = Adw.PreferencesGroup(title="Уведомления")
        self.add_switch(group, "Уведомлять об исправлении", "notify_on_fix")
        self.add_switch(group, "Уведомлять об ошибке", "notify_on_error")
        self.add_switch(group, "Звук при исправлении", "sound_on_fix")
        self.add_switch(group, "Иконка в трее", "tray_enabled")
        self.add(group)

    # --- logs -------------------------------------------------------------
    def _build_logs_group(self) -> None:
        group = Adw.PreferencesGroup(title="Логи")
        self.add_combo(
            group,
            "Уровень логирования",
            list(LOG_LEVELS),
            list(LOG_LEVELS),
            self._config.log_level,
            self._on_log_level,
        )
        self.add_spin(group, "Ротация, МБ", "log_rotation_mb", lower=1, upper=50, step=1)
        open_button = Gtk.Button(label="Открыть config.toml")
        open_button.connect("clicked", self._on_open_config)
        open_button.set_halign(Gtk.Align.START)
        open_button.add_css_class("flat")
        group.add(open_button)
        self.add(group)

    def _on_log_level(self, value: str) -> None:
        self._config.log_level = value
        self._save("Уровень логирования сохранён")

    @staticmethod
    def _on_open_config(_button: Gtk.Button) -> None:
        path = config_path()
        try:
            import subprocess

            subprocess.run(["xdg-open", str(path)], check=False, timeout=5)
        except (OSError, subprocess.SubprocessError):  # pragma: no cover - desktop only
            pass
