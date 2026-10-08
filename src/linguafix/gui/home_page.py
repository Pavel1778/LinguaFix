"""Home page: the big on/off toggle and at-a-glance status."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .async_utils import run_in_background  # noqa: E402
from .state import MODE_LABELS, GuiState  # noqa: E402
from .widgets.big_toggle import STATE_BUSY, STATE_OFF, STATE_ON, BigToggle  # noqa: E402
from .widgets.mode_switcher import ModeSwitcher  # noqa: E402
from .widgets.status_row import StatusRow  # noqa: E402

REFRESH_MS = 1500
# A start can take up to START_TIMEOUT (5 s) for systemd plus another 5 s for the
# detached-spawn fallback before daemon_control.start() gives up. The reconcile
# window must outlast that, or the button flips back to OFF while the start is
# still in flight -- the "spinner for a moment, then inactive" bug.
RECONCILE_MS = 250
RECONCILE_ATTEMPTS = 40


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

        # ``refresh`` runs on a timer and on every toggle, so it must never block:
        # the probes behind it (systemctl, g3kb-switch, the focused-app query) are
        # subprocesses and D-Bus calls with multi-second timeouts, and running one
        # on the main thread is what made GNOME report "приложение не отвечает".
        self._refreshing = False
        self._refresh_pending = False
        self._reconcile_want: bool | None = None
        self.refresh()
        GLib.timeout_add(REFRESH_MS, self._refresh_tick)
        # Refresh the moment the page is shown again: the poll below is paused
        # while the page is hidden, so returning to it must not show stale state.
        self.connect("map", lambda _widget: self.refresh())

    @staticmethod
    def _section_label(text: str) -> Gtk.Label:
        label = Gtk.Label(label=text, xalign=0.0)
        label.add_css_class("title-4")
        return label

    # --- actions ----------------------------------------------------------
    def _on_toggle_clicked(self) -> None:
        # Derive the target from the button's own (last-applied) state rather than
        # probing the daemon here: a probe can take seconds, and the whole point
        # is that the click never blocks the main thread. The periodic refresh
        # keeps the button in sync with the real state.
        want_active = self._toggle.state != STATE_ON
        self._toggle.set_busy()
        self._reconcile_want = want_active
        # Start/stop runs on a worker thread; the click returns at once with the
        # spinner showing. The daemon state is then reconciled by polling rather
        # than trusting the return value, because systemd can report success
        # before ``is-active`` flips.
        run_in_background(self._start_or_stop, self._on_toggle_done, want_active)
        self._poll_state(want_active, 0)

    def _start_or_stop(self, want_active: bool) -> bool:
        return self._state.start() if want_active else self._state.stop()

    def _on_toggle_done(self, ok: object) -> None:
        if not ok:
            reason = self._state.last_error()
            message = (
                f"Не удалось переключить демон: {reason}"
                if reason
                else "Не удалось переключить демон"
            )
            self._toast(message, ok=False)

    def _poll_state(self, want_active: bool, attempt: int) -> None:
        """Check the daemon state off the main thread, then redraw when it matches."""
        if self._reconcile_want != want_active:
            return
        if attempt >= RECONCILE_ATTEMPTS:
            self._reconcile_want = None
            self.refresh()
            return
        run_in_background(
            self._state.is_active,
            on_done=lambda active: self._on_polled(active, want_active, attempt),
        )

    def _on_polled(self, active: object, want_active: bool, attempt: int) -> None:
        if self._reconcile_want != want_active:
            return
        if bool(active) == want_active:
            self._reconcile_want = None
            self.refresh()
        else:
            GLib.timeout_add(RECONCILE_MS, self._poll_state, want_active, attempt + 1)

    def _on_mode_changed(self, mode: str) -> None:
        self._state.set_mode(mode)
        self._toast(f"Режим изменён на {MODE_LABELS.get(mode, mode)}")

    def _on_undo_clicked(self, _button: Gtk.Button) -> None:
        """Ask the daemon to undo its last fix without touching app history."""
        if self._state.undo_last_fix():
            self._toast("Последнее исправление отменено")
        else:
            self._toast("Демон не запущен", ok=False)

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
        # Only poll while the page is visible. A hidden page that kept probing
        # ran systemctl/g3kb-switch/D-Bus every second and a half for nothing.
        if self.get_mapped():
            self.refresh()
        return True

    def refresh(self) -> None:
        """Re-read the daemon state off the main thread, then update widgets."""
        if self._refreshing:
            self._refresh_pending = True
            return
        self._refreshing = True
        run_in_background(self._collect_status, on_done=self._apply_status)

    def _collect_status(self) -> dict[str, object]:
        """Gather every probe result on a worker thread (never on the main loop)."""
        app = None
        try:
            from ..app_focus import get_active_app
        except ImportError:  # pragma: no cover - defensive
            get_active_app = None  # type: ignore[assignment]
        if get_active_app is not None:
            try:
                app = get_active_app()
            except Exception:  # pragma: no cover - defensive
                app = None
        return {
            "active": self._state.is_active(),
            "layout": self._state.current_layout(),
            "autostart": self._state.is_autostart_enabled(),
            "quiet": self._state.in_quiet_hours(),
            "app": app,
        }

    def _apply_status(self, data: object) -> None:
        self._refreshing = False
        if isinstance(data, dict):
            active = bool(data.get("active"))
            layout = str(data.get("layout") or "")
            self._toggle.set_state(STATE_ON if active else STATE_OFF, layout)
            self._status.update(
                layout=layout,
                backend=self._state.config.backend,
                mode=MODE_LABELS.get(self._state.config.mode, self._state.config.mode),
                seconds_since_fix=self._state.seconds_since_last_fix(),
            )
            self._pause.set_label(self._pause_reason(bool(data.get("quiet")), data.get("app")))
            self._pause.set_visible(bool(self._pause.get_label()))
            self._mode.set_mode(self._state.config.mode)
            # Update the autostart switch without re-triggering the handler.
            self._autostart.handler_block_by_func(self._on_autostart_toggled)
            self._autostart.set_active(bool(data.get("autostart")))
            self._autostart.handler_unblock_by_func(self._on_autostart_toggled)
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()

    @staticmethod
    def _pause_reason(quiet: bool, app: object) -> str:
        """Return why automatic correction is paused, or an empty string.

        Quiet hours win over an app exception: it is the reason the user is more
        likely to be surprised by.
        """
        if quiet:
            return "Автопереключение приостановлено: тихие часы"
        if isinstance(app, str) and app:
            return f"Автопереключение приостановлено (приложение «{app}»)"
        return ""

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
