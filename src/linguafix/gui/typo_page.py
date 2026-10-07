"""T9 page: typo correction and punctuation cleanup, with a big master switch.

Both features are off by default -- a wrong correction is worse than none -- so
the page is built around one large on/off button (the same widget as the home
page) that turns the whole feature set on and off. The rows below it give finer
control. Every change is written through :class:`~linguafix.gui.state.GuiState`
and pushed to a running daemon, so the effect is immediate.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .prefs_base import BoundPreferencesPage  # noqa: E402
from .state import GuiState  # noqa: E402
from .widgets.big_toggle import STATE_OFF, STATE_ON, BigToggle  # noqa: E402


class TypoPage(BoundPreferencesPage):
    """A preferences page for typo correction and punctuation."""

    def __init__(
        self,
        state: GuiState,
        toast_overlay: Adw.ToastOverlay,
        on_saved: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(state, on_saved)
        self._toasts = toast_overlay

        self._toggle = BigToggle(on_toggle=self._on_toggle_clicked)
        toggle_group = Adw.PreferencesGroup()
        toggle_group.add(self._toggle)
        self.add(toggle_group)

        self._status = Gtk.Label(label="", xalign=0.5)
        self._status.add_css_class("dim-label")
        self._status.set_margin_bottom(12)
        status_group = Adw.PreferencesGroup()
        status_group.add(self._status)
        self.add(status_group)

        typo_group = Adw.PreferencesGroup(
            title="Опечатки",
            description="Исправлять одну опечатку в слове, только если вариант однозначен",
        )
        self._typo_switch = self.add_switch(typo_group, "Исправлять опечатки", "typo_correction")
        self.add_spin(
            typo_group,
            "Минимальная длина слова",
            "typo_min_word_length",
            lower=3,
            upper=10,
            step=1,
        )
        self.add_spin(
            typo_group,
            "Максимум правок",
            "typo_max_distance",
            lower=1,
            upper=2,
            step=1,
        )
        self.add(typo_group)

        punct_group = Adw.PreferencesGroup(
            title="Пунктуация",
            description="Правила, а не языковая модель: предсказуемо и без выдумок",
        )
        self._punct_switch = self.add_switch(
            punct_group, "Исправлять пунктуацию", "punctuation_correction"
        )
        self._dashes_switch = self.add_switch(
            punct_group, "Заменять -- на тире", "punctuation_dashes"
        )
        self._ellipsis_switch = self.add_switch(
            punct_group, "Заменять ... на многоточие", "punctuation_ellipsis"
        )
        self._quotes_switch = self.add_switch(
            punct_group, "Умные кавычки «» (кириллица)", "punctuation_smart_quotes"
        )
        self._spacing_switch = self.add_switch(
            punct_group, "Исправлять пробелы у знаков", "punctuation_fix_spacing"
        )
        self.add(punct_group)

        reset = Gtk.Button(label="Сбросить к дефолтным")
        reset.add_css_class("pill")
        reset.set_halign(Gtk.Align.CENTER)
        reset.connect("clicked", self._on_reset)
        reset_group = Adw.PreferencesGroup()
        reset_group.add(reset)
        self.add(reset_group)

        self._sync()

    def _on_toggle_clicked(self) -> None:
        enabled = not self._feature_on()
        self._config.typo_correction = enabled
        self._config.punctuation_correction = enabled
        self._config.validate()
        # ``_save`` persists the config and pushes it to a running daemon, so no
        # separate reload is needed here.
        self._save("Т9 включён" if enabled else "Т9 выключен")
        self._sync()

    def _feature_on(self) -> bool:
        return bool(self._config.typo_correction or self._config.punctuation_correction)

    def _on_reset(self, _button: Gtk.Button) -> None:
        self._config.typo_correction = False
        self._config.typo_max_distance = 1
        self._config.typo_min_word_length = 4
        self._config.punctuation_correction = False
        self._config.punctuation_dashes = True
        self._config.punctuation_ellipsis = True
        self._config.punctuation_smart_quotes = False
        self._config.punctuation_fix_spacing = True
        self._save("Настройки Т9 сброшены")
        self._sync()

    def _sync(self) -> None:
        """Reflect the current config in the button and the status line."""
        self._toggle.set_state(STATE_ON if self._feature_on() else STATE_OFF)
        typo = "вкл" if self._config.typo_correction else "выкл"
        punct = "вкл" if self._config.punctuation_correction else "выкл"
        self._status.set_label(f"Опечатки: {typo} · Пунктуация: {punct}")
        for row, field in (
            (self._typo_switch, "typo_correction"),
            (self._punct_switch, "punctuation_correction"),
            (self._dashes_switch, "punctuation_dashes"),
            (self._ellipsis_switch, "punctuation_ellipsis"),
            (self._quotes_switch, "punctuation_smart_quotes"),
            (self._spacing_switch, "punctuation_fix_spacing"),
        ):
            row.handler_block_by_func(self._on_switch)
            row.set_active(bool(getattr(self._config, field)))
            row.handler_unblock_by_func(self._on_switch)

    @property
    def toggle(self) -> BigToggle:
        """Expose the master switch for tests."""
        return self._toggle

    @property
    def status_label(self) -> Gtk.Label:
        """Expose the status label for tests."""
        return self._status
