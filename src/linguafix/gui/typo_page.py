"""T9 page: typo correction and punctuation cleanup, each with its own mode.

Both features are off by default -- a wrong correction is worse than none -- so
the page leads with one large on/off button (the same widget as the home page)
that turns the whole feature set on and off. Each feature then has an
independent mode (off / manual / auto / hybrid) so a user can, for example,
keep automatic layout switching but make T9 hotkey-only. The rows below the mode
give finer control. Every change is written through
:class:`~linguafix.gui.state.GuiState` and pushed to a running daemon, so the
effect is immediate.
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

# Mode option order and their Russian labels, shared by both feature combos.
_MODE_OPTIONS = ["off", "manual", "auto", "hybrid"]
_MODE_LABELS = ["Выключено", "Ручной", "Авто", "Гибрид"]


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
            description="Исправлять опечатки только в неизвестном слове и только "
            "когда вариант однозначен",
        )
        self._typo_mode_combo = self.add_combo(
            typo_group,
            "Режим Т9",
            _MODE_OPTIONS,
            _MODE_LABELS,
            state.config.typo_mode,
            lambda mode: self._set_mode("typo", mode),
            subtitle="В ручном режиме T9 срабатывает только по хоткею",
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
            "Максимум правок (короткие слова)",
            "typo_max_distance",
            lower=1,
            upper=2,
            step=1,
        )
        self.add_spin(
            typo_group,
            "Максимум правок (слова от 6 символов)",
            "typo_max_distance_long",
            lower=1,
            upper=2,
            step=1,
        )
        self.add_spin(
            typo_group,
            "Порог длины «длинного» слова",
            "typo_long_word_threshold",
            lower=3,
            upper=20,
            step=1,
        )
        self.add_spin(
            typo_group,
            "Уверенность (отрыв лучшего варианта)",
            "typo_top1_ratio_strict",
            lower=1.0,
            upper=50.0,
            step=1.0,
            digits=1,
        )
        self.add(typo_group)

        punct_group = Adw.PreferencesGroup(
            title="Пунктуация",
            description="Правила, а не языковая модель: предсказуемо и без выдумок",
        )
        self._punct_mode_combo = self.add_combo(
            punct_group,
            "Режим пунктуации",
            _MODE_OPTIONS,
            _MODE_LABELS,
            state.config.punctuation_mode,
            lambda mode: self._set_mode("punctuation", mode),
            subtitle="В ручном режиме пунктуация срабатывает только по хоткею",
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

        examples = self._build_examples_group()
        examples_group = Adw.PreferencesGroup()
        examples_group.add(examples)
        self.add(examples_group)

        check = Gtk.Button(label="Проверить сейчас")
        check.add_css_class("pill")
        check.set_halign(Gtk.Align.CENTER)
        check.connect("clicked", self._on_check_clicked)
        check_group = Adw.PreferencesGroup()
        check_group.add(check)
        self.add(check_group)

        docs = Gtk.LinkButton.new_with_label(
            "https://github.com/Pavel1778/LinguaFix/blob/main/docs/ARCHITECTURE.md",
            "Документация Т9",
        )
        docs.set_halign(Gtk.Align.CENTER)
        docs_group = Adw.PreferencesGroup()
        docs_group.add(docs)
        self.add(docs_group)

        reset = Gtk.Button(label="Сбросить к дефолтным")
        reset.add_css_class("pill")
        reset.set_halign(Gtk.Align.CENTER)
        reset.connect("clicked", self._on_reset)
        reset_group = Adw.PreferencesGroup()
        reset_group.add(reset)
        self.add(reset_group)

        self._sync()

    def _build_examples_group(self) -> Adw.ExpanderRow:
        """A collapsible row listing ready-made examples."""
        row = Adw.ExpanderRow(
            title="Примеры",
            subtitle="Нажмите, чтобы посмотреть, как это работает",
        )
        for source, result in (
            ("првет", "привет"),
            ("программма", "программа"),
            ("текст--", "текст —"),
        ):
            item = Adw.ActionRow(title=f"{source} → {result}")
            row.add_row(item)
        return row

    def _on_switch(self, row: Adw.SwitchRow, _param: object, field: str) -> None:
        """Toggle a feature, keeping its independent mode in sync.

        The per-feature switch is a convenience over the mode: switching it on
        selects ``auto`` (unless a manual/hybrid mode was already chosen) and
        switching it off selects ``off``. This keeps the combo and the switch
        from ever disagreeing in the same session.
        """
        super()._on_switch(row, _param, field)
        feature = field.removesuffix("_correction")
        if field in ("typo_correction", "punctuation_correction"):
            enabled = bool(getattr(self._config, field))
            current = getattr(self._config, f"{feature}_mode")
            if enabled and current == "off":
                setattr(self._config, f"{feature}_mode", "auto")
            elif not enabled:
                setattr(self._config, f"{feature}_mode", "off")
            self._sync()

    def _set_mode(self, feature: str, mode: str) -> None:
        """Set a feature's independent mode and keep its boolean in sync."""
        setattr(self._config, f"{feature}_mode", mode)
        setattr(self._config, f"{feature}_correction", mode != "off")
        self._config.validate()
        label = {"typo": "Т9", "punctuation": "Пунктуация"}[feature]
        self._save(f"{label}: режим «{_MODE_LABELS[_MODE_OPTIONS.index(mode)]}»")
        self._sync()

    def _on_toggle_clicked(self) -> None:
        enabled = not self._feature_on()
        mode = "auto" if enabled else "off"
        self._config.typo_mode = mode
        self._config.punctuation_mode = mode
        # Keep the legacy booleans in step too: ``validate`` treats a ``True``
        # boolean with an ``off`` mode as "mode unset" and re-derives it from the
        # global mode, so clearing the mode alone would silently turn it back on.
        self._config.typo_correction = enabled
        self._config.punctuation_correction = enabled
        self._config.validate()
        # ``_save`` persists the config and pushes it to a running daemon, so no
        # separate reload is needed here.
        self._save("Т9 включён" if enabled else "Т9 выключен")
        self._sync()

    def _feature_on(self) -> bool:
        return bool(self._config.typo_mode != "off" or self._config.punctuation_mode != "off")

    def _on_check_clicked(self, _button: Gtk.Button) -> None:
        """Open a small dialog that previews T9 for one word."""
        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            heading="Проверить слово",
            body="Введите слово — покажем, что предложит Т9.",
        )
        entry = Gtk.Entry(placeholder_text="првет")
        entry.set_margin_top(6)
        entry.set_margin_bottom(6)
        dialog.set_extra_child(entry)
        dialog.add_response("close", "Закрыть")
        dialog.add_response("check", "Проверить")
        dialog.set_response_appearance("check", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("check")

        def _on_response(_dialog: Adw.MessageDialog, response: str) -> None:
            if response != "check":
                return
            suggestion = self.preview_suggestion(entry.get_text())
            result = (
                f"{entry.get_text()} → {suggestion}" if suggestion else "Нет уверенного варианта."
            )
            self._toasts.add_toast(Adw.Toast(title=result))

        dialog.connect("response", _on_response)
        dialog.present()

    def preview_suggestion(self, word: str) -> str | None:
        """Return what T9 would suggest for ``word``, or ``None``.

        Built lazily and only for the dialog, so page construction stays cheap.
        """
        word = word.strip()
        if len(word) < self._config.typo_min_word_length or not word.isalpha():
            return None
        from ..config import load_config
        from ..converter import LayoutConverter
        from ..detector import LanguageDetector
        from ..typo import TypoCorrector

        config = load_config()
        detector = LanguageDetector(
            converter=LayoutConverter(),
            stop_words=config.stop_words,
            min_word_length=config.min_word_length,
        )
        corrector = TypoCorrector(
            detector.ordered_vocabulary("ru"),
            max_distance=config.typo_max_distance,
            min_length=config.typo_min_word_length,
            long_word_threshold=config.typo_long_word_threshold,
            long_word_max_distance=config.typo_max_distance_long,
            top1_ratio_strict=config.typo_top1_ratio_strict,
        )
        suggestion = corrector.suggest(word)
        if suggestion is None or suggestion == word:
            return None
        if word[0].isupper():
            suggestion = suggestion[:1].upper() + suggestion[1:]
        return suggestion

    def _on_reset(self, _button: Gtk.Button) -> None:
        self._config.typo_mode = "off"
        self._config.typo_correction = False
        self._config.typo_max_distance = 1
        self._config.typo_max_distance_long = 2
        self._config.typo_min_word_length = 4
        self._config.punctuation_mode = "off"
        self._config.punctuation_correction = False
        self._config.punctuation_dashes = True
        self._config.punctuation_ellipsis = True
        self._config.punctuation_smart_quotes = False
        self._config.punctuation_fix_spacing = True
        self._config.validate()
        self._save("Настройки Т9 сброшены")
        self._sync()

    def _sync(self) -> None:
        """Reflect the current config in the button and the status line."""
        self._toggle.set_state(STATE_ON if self._feature_on() else STATE_OFF)
        typo = "вкл" if self._config.typo_mode != "off" else "выкл"
        punct = "вкл" if self._config.punctuation_mode != "off" else "выкл"
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
        self._sync_mode_combo(self._typo_mode_combo, self._config.typo_mode)
        self._sync_mode_combo(self._punct_mode_combo, self._config.punctuation_mode)

    def _sync_mode_combo(self, combo: Adw.ComboRow, mode: str) -> None:
        # ``_on_combo`` is inherited from ``BoundPreferencesPage``; blocking must
        # use the same *bound* method the signal was connected with, so the
        # helper is an instance method rather than referencing ``TypoPage``.
        combo.handler_block_by_func(self._on_combo)
        combo.set_selected(_MODE_OPTIONS.index(mode) if mode in _MODE_OPTIONS else 0)
        combo.handler_unblock_by_func(self._on_combo)

    @property
    def toggle(self) -> BigToggle:
        """Expose the master switch for tests."""
        return self._toggle

    @property
    def status_label(self) -> Gtk.Label:
        """Expose the status label for tests."""
        return self._status

    @property
    def typo_mode_combo(self) -> Adw.ComboRow:
        """Expose the T9 mode combo for tests."""
        return self._typo_mode_combo

    @property
    def punctuation_mode_combo(self) -> Adw.ComboRow:
        """Expose the punctuation mode combo for tests."""
        return self._punct_mode_combo
