"""Home page: the big on/off toggle and at-a-glance status."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .state import MODE_LABELS, GuiState  # noqa: E402
from .widgets.big_toggle import STATE_BUSY, STATE_OFF, STATE_ON, BigToggle, BusyPoller  # noqa: E402
from .widgets.mode_switcher import ModeSwitcher  # noqa: E402
from .widgets.status_row import StatusRow  # noqa: E402

REFRESH_MS = 1500


class HomePage(Gtk.Box):
    """Main tab of the LinguaFix window."""

    def __init__(self, state: GuiState, toast_overlay: Adw.ToastOverlay) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        self._state = state
        self._toasts = toast_overlay

        self._toggle = BigToggle(on_toggle=self._on_toggle_clicked)
        self.append(self._toggle)

        self._status = StatusRow()
        self.append(self._status)

        self.append(self._section_label("Режим работы"))
        self._mode = ModeSwitcher(on_change=self._on_mode_changed)
        self._mode.set_mode(state.config.mode)
        self.append(self._mode)

        self.append(Gtk.Separator())
        self._autostart = Adw.SwitchRow(
            title="Запускать при входе в систему",
            subtitle="Демон будет активироваться автоматически",
        )
        self._autostart.connect("notify::active", self._on_autostart_toggled)
        group = Adw.PreferencesGroup()
        group.add(self._autostart)
        self.append(group)

        self.refresh()
        GLib.timeout_add(REFRESH_MS, self._refresh_tick)

    @staticmethod
    def _section_label(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0.0)
        label.add_css_class("title-4")
        return label

    # --- actions ----------------------------------------------------------
    def _on_toggle_clicked(self) -> None:
        if self._state.is_active():
            self._toggle.set_busy()
            self._state.stop()
            BusyPoller(lambda: not self._state.is_active(), self.refresh).start()
        else:
            self._toggle.set_busy()
            self._state.start()
            BusyPoller(self._state.is_active, self.refresh).start()

    def _on_mode_changed(self, mode: str) -> None:
        self._state.set_mode(mode)
        self._toast(f"Режим изменён на {MODE_LABELS.get(mode, mode)}")

    def _on_autostart_toggled(self, row: Adw.SwitchRow, _param: object) -> None:
        enabled = row.get_active()
        if enabled == self._state.is_autostart_enabled():
            return
        ok = self._state.set_autostart(enabled)
        self._toast(
            "Автозагрузка включена" if enabled else "Автозагрузка выключена",
            ok=ok,
        )

    def _toast(self, text: str, *, ok: bool = True) -> None:
        message = text if ok else f"{text} (не удалось)"
        self._toasts.add_toast(Adw.Toast(title=message, timeout=2))

    # --- refresh ----------------------------------------------------------
    def _refresh_tick(self) -> bool:
        self.refresh()
        return True

    def refresh(self) -> None:
        """Re-read the daemon state and update every widget."""
        active = self._state.is_active()
        layout = self._state.current_layout()
        self._toggle.set_state(STATE_ON if active else STATE_OFF, layout)
        self._status.update(
            layout=layout,
            backend=self._state.config.backend,
            mode=MODE_LABELS.get(self._state.config.mode, self._state.config.mode),
            seconds_since_fix=self._state.seconds_since_last_fix(),
        )
        self._mode.set_mode(self._state.config.mode)
        # Update the autostart switch without re-triggering the handler.
        self._autostart.handler_block_by_func(self._on_autostart_toggled)
        self._autostart.set_active(self._state.is_autostart_enabled())
        self._autostart.handler_unblock_by_func(self._on_autostart_toggled)

    @property
    def toggle(self) -> BigToggle:
        """Expose the toggle for tests."""
        return self._toggle

    @property
    def mode_switcher(self) -> ModeSwitcher:
        """Expose the mode switcher for tests."""
        return self._mode

    @property
    def autostart_row(self) -> Adw.SwitchRow:
        """Expose the autostart switch for tests."""
        return self._autostart


__all__ = ["STATE_BUSY", "HomePage"]
