"""Home page: the big on/off toggle and at-a-glance status."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .state import MODE_LABELS, GuiState, StatusSnapshot  # noqa: E402
from .widgets.big_toggle import STATE_BUSY, STATE_OFF, STATE_ON, BigToggle  # noqa: E402
from .widgets.mode_switcher import ModeSwitcher  # noqa: E402
from .widgets.status_row import StatusRow  # noqa: E402

REFRESH_MS = 1500


class HomePage(Gtk.Box):
    """Main tab of the LinguaFix window.

    Every daemon probe is asynchronous. The page never calls ``systemctl`` or
    ``g3kb-switch`` on the GTK main thread: a slow probe used to freeze the
    whole window ("Приложение не отвечает"). Instead the page schedules a probe
    and repaints when its result arrives.
    """

    def __init__(self, state: GuiState, toast_overlay: Adw.ToastOverlay) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        self._state = state
        self._toasts = toast_overlay
        # Last known daemon/autostart state, so a click can compute the desired
        # target without a blocking read.
        self._last_active = False
        self._last_autostart = False
        # Guards against queueing a new status probe every 1.5 s while a slow
        # one (systemctl + g3kb-switch) is still running on the worker thread.
        self._probe_in_flight = False
        # True while an autostart enable/disable is in flight. A snapshot taken
        # before the write landed must not overwrite the value the user just
        # chose, or a quick second toggle would be compared against stale state.
        self._autostart_pending = False

        self._toggle = BigToggle(on_toggle=self._on_toggle_clicked)
        self.append(self._toggle)

        self._status = StatusRow()
        self.append(self._status)

        # A single line that explains why automatic correction is currently
        # paused (an excepted app or quiet hours). Hidden when nothing pauses it.
        self._pause = Gtk.Label(label="", xalign=0.5)
        self._pause.add_css_class("dim-label")
        self._pause.set_wrap(True)
        self._pause.set_visible(False)
        self.append(self._pause)

        self.append(self._section_label("Режим работы"))
        self._mode = ModeSwitcher(on_change=self._on_mode_changed)
        self._mode.set_mode(state.config.mode)
        self.append(self._mode)

        self._undo_button = Gtk.Button(label="Отменить последнее исправление")
        self._undo_button.add_css_class("pill")
        self._undo_button.set_halign(Gtk.Align.CENTER)
        self._undo_button.connect("clicked", self._on_undo_clicked)
        self.append(self._undo_button)

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
        want_active = not self._last_active
        self._toggle.set_busy()
        self._state.probe_toggle(
            want_active,
            lambda ok: self._on_toggle_done(want_active, ok),
            lambda _exc: self._on_toggle_done(want_active, False),
        )

    def _on_toggle_done(self, want_active: bool, ok: bool) -> None:
        if not ok:
            self._toast("Не удалось переключить демон", ok=False)
        # Poll until the daemon state matches the request. Polling (rather than
        # trusting the return value) is what makes the button reliable: systemd
        # start/stop can return before ``is-active`` flips.
        self._reconcile(want_active, attempt=0)

    def _reconcile(self, want_active: bool, attempt: int) -> None:
        """Poll the daemon state until it matches ``want_active``, then redraw."""

        def _check(active: bool) -> None:
            if active == want_active or attempt >= 12:
                self.refresh()
            else:
                GLib.timeout_add(150, self._reconcile, want_active, attempt + 1)

        self._state.probe_is_active(_check)

    def _on_mode_changed(self, mode: str) -> None:
        self._state.set_mode(mode)
        self._toast(f"Режим изменён на {MODE_LABELS.get(mode, mode)}")

    def _on_undo_clicked(self, _button: Gtk.Button) -> None:
        """Ask the daemon to undo its last fix without touching app history."""
        self._state.probe_undo(
            lambda ok: self._toast(
                "Последнее исправление отменено" if ok else "Демон не запущен",
                ok=ok,
            )
        )

    def _on_autostart_toggled(self, row: Adw.SwitchRow, _param: object) -> None:
        enabled = row.get_active()
        if enabled == self._last_autostart:
            return
        # Reflect the new value immediately and ignore snapshots until the write
        # lands, so a quick second toggle is not compared against stale state.
        self._last_autostart = enabled
        self._autostart_pending = True
        self._state.probe_set_autostart(enabled, lambda ok: self._on_autostart_done(enabled, ok))

    def _on_autostart_done(self, enabled: bool, ok: bool) -> None:
        self._autostart_pending = False
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
        """Schedule a status probe; widgets update when the result arrives."""
        if not self._probe_in_flight:
            self._probe_in_flight = True
            self._state.probe_status_snapshot(self._on_snapshot_ready)
        self._refresh_pause()

    def _on_snapshot_ready(self, snap: StatusSnapshot) -> None:
        self._probe_in_flight = False
        self._apply_snapshot(snap)

    def _apply_snapshot(self, snap: StatusSnapshot) -> None:
        self._last_active = snap.active
        self._toggle.set_state(STATE_ON if snap.active else STATE_OFF, snap.layout)
        self._status.update(
            layout=snap.layout,
            backend=self._state.config.backend,
            mode=MODE_LABELS.get(self._state.config.mode, self._state.config.mode),
            seconds_since_fix=self._state.seconds_since_last_fix(),
        )
        self._mode.set_mode(self._state.config.mode)
        # Do not clobber the autostart switch while an enable/disable is still
        # in flight: the snapshot may predate the write.
        if not self._autostart_pending:
            self._last_autostart = snap.autostart
            self._autostart.handler_block_by_func(self._on_autostart_toggled)
            self._autostart.set_active(snap.autostart)
            self._autostart.handler_unblock_by_func(self._on_autostart_toggled)

    def _refresh_pause(self) -> None:
        """Show why automatic correction is paused, if it is.

        Quiet hours win over an app exception: it is the reason the user is more
        likely to be surprised by. The active-app probe runs off the main thread
        and is best-effort; when it cannot tell, no exception line is shown.
        """
        if self._state.in_quiet_hours():
            self._set_pause(
                f"Автопереключение приостановлено: тихие часы "
                f"({self._state.config.quiet_hours_start}–{self._state.config.quiet_hours_end})"
            )
            return
        self._state.probe_current_app_excepted(
            lambda app: self._set_pause(
                f"Автопереключение приостановлено (приложение «{app}»)" if app else ""
            )
        )

    def _set_pause(self, reason: str) -> None:
        self._pause.set_label(reason)
        self._pause.set_visible(bool(reason))

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
