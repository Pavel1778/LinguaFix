"""History page: the last corrections, shown as metadata only.

The daemon keeps a short in-memory ring of recent corrections so the user can
see what LinguaFix changed and undo the last one. The list never holds the typed
text: a row shows the word *length*, the layouts and how long ago the fix was.
The most recent correction gets an "Отменить" button, which asks the daemon to
restore the pre-fix text (the daemon refuses to undo anything but the newest).
"""

from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .async_utils import run_in_background  # noqa: E402
from .state import GuiState  # noqa: E402

REFRESH_MS = 2000
MAX_ROWS = 20


def format_age(seconds: float) -> str:
    """Return a short Russian "N ago" label for ``seconds``."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} с назад"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} мин назад"
    hours = minutes // 60
    return f"{hours} ч назад"


class HistoryPage(Gtk.Box):
    """Main-tab-style page listing the recent corrections."""

    def __init__(self, state: GuiState, toast_overlay: Adw.ToastOverlay) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)
        self._state = state
        self._toasts = toast_overlay
        self._rows: list[Gtk.Widget] = []
        self._refreshing = False
        self._refresh_pending = False

        heading = Gtk.Label(label="История исправлений", xalign=0.0)
        heading.add_css_class("title-2")
        self.append(heading)

        privacy = Gtk.Label(
            label="Хранятся только метаданные: длина слова, языки и время. "
            "Сам набранный текст не сохраняется нигде.",
            xalign=0.0,
            wrap=True,
        )
        privacy.add_css_class("dim-label")
        self.append(privacy)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.add_css_class("boxed-list")
        self.append(self._list)

        self._empty = Gtk.Label(label="Пока нет исправлений.", xalign=0.5)
        self._empty.add_css_class("dim-label")
        self.append(self._empty)

        self.refresh()
        GLib.timeout_add(REFRESH_MS, self._tick)

    def _tick(self) -> bool:
        self.refresh()
        return True

    def refresh(self) -> None:
        """Rebuild the list from the daemon snapshot, fetched off the main thread.

        ``read_history`` sends a signal to the daemon and reads a file back; doing
        that on the GTK main thread would stall the window, so it runs on a worker.
        """
        if self._refreshing:
            self._refresh_pending = True
            return
        self._refreshing = True
        run_in_background(self._read_history_safe, on_done=self._apply_history)

    def _read_history_safe(self) -> list[dict[str, object]]:
        try:
            return self._state.read_history()
        except Exception:  # pragma: no cover - defensive, never break the UI
            return []

    def _apply_history(self, data: object) -> None:
        self._refreshing = False
        entries = data if isinstance(data, list) else []
        for row in self._rows:
            self._list.remove(row)
        self._rows.clear()
        entries = entries[:MAX_ROWS]
        self._empty.set_visible(not entries)
        self._list.set_visible(bool(entries))
        now = time.time()
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            self._list.append(self._make_row(entry, now, is_latest=index == 0))
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh()

    def _make_row(self, entry: dict[str, object], now: float, *, is_latest: bool) -> Gtk.Widget:
        length = entry.get("length", 0)
        source = str(entry.get("source") or "")
        target = str(entry.get("target") or "")
        undone = bool(entry.get("undone"))
        at = entry.get("at")
        age = format_age(now - float(at)) if isinstance(at, (int, float)) else "—"

        layouts = f"{source} → {target}" if source and target else "смена раскладки"
        title = f"{length} симв. · {layouts}"
        if undone:
            title = f"↩ {title}"

        row = Adw.ActionRow(title=title, subtitle=age)
        row.set_activatable(False)
        if is_latest and not undone:
            button = Gtk.Button(label="Отменить")
            button.add_css_class("flat")
            button.set_valign(Gtk.Align.CENTER)
            button.connect("clicked", self._on_undo_clicked, entry.get("id"))
            row.add_suffix(button)
        return row

    def _on_undo_clicked(self, _button: Gtk.Button, entry_id: object) -> None:
        ok = self._state.undo_last_fix(int(entry_id) if isinstance(entry_id, int) else None)
        self._toast("Последнее исправление отменено" if ok else "Отменить не удалось", ok=ok)
        self.refresh()

    def _toast(self, text: str, *, ok: bool = True) -> None:
        message = text if ok else f"{text} (не удалось)"
        self._toasts.add_toast(Adw.Toast(title=message, timeout=2))
