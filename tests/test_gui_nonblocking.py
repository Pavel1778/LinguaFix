"""The GUI must never block its main thread on a daemon probe.

Every probe behind the home page (``systemctl``, ``g3kb-switch``, the focused-app
query) is a subprocess or a D-Bus round-trip with a multi-second timeout. When
one ran on the GTK main thread the whole window froze and GNOME reported
"приложение не отвечает". These tests replace the probes with a slow stand-in
and assert the calling code returns immediately, i.e. the work happened on a
worker thread rather than inline.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from linguafix.config import Config

_DIST_PACKAGES = "/usr/lib/python3/dist-packages"
if os.path.isdir(_DIST_PACKAGES) and _DIST_PACKAGES not in sys.path:
    sys.path.append(_DIST_PACKAGES)


def _gtk_usable() -> bool:
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _gtk_usable(), reason="GTK4/libadwaita or display unavailable")

SLOW = 0.5  # seconds a fake probe "takes"


def _pump_until(event: threading.Event, timeout: float = 2.0) -> None:
    """Iterate the default GLib context until ``event`` is set (or timeout).

    ``run_in_background`` delivers through ``GLib.idle_add``, which only runs
    when a main loop iterates; the real app has one, the test pumps it by hand.
    """
    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    deadline = time.monotonic() + timeout
    while not event.is_set() and time.monotonic() < deadline:
        GLib.MainContext.default().iteration(False)
        time.sleep(0.005)


@pytest.fixture
def gui_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from linguafix.gui import state as state_module
    from linguafix.gui.state import GuiState

    config = Config()
    monkeypatch.setattr(state_module, "load_config", lambda: config)
    monkeypatch.setattr(state_module, "save_config", lambda _cfg, _path=None: tmp_path)
    return GuiState(config=config)


class _Toasts:
    def add_toast(self, _t: object) -> None:
        pass


def test_refresh_returns_before_probes_finish(
    gui_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``refresh`` must return at once even when the probes are slow."""
    import gi

    import linguafix.app_focus as app_focus

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from linguafix.gui.home_page import HomePage

    started = threading.Event()

    def slow_probe() -> bool:
        started.set()
        time.sleep(SLOW)
        return True

    monkeypatch.setattr(app_focus, "get_active_app", lambda: None)
    monkeypatch.setattr(gui_state, "is_active", slow_probe)
    monkeypatch.setattr(gui_state, "current_layout", lambda: "us")
    monkeypatch.setattr(gui_state, "is_autostart_enabled", lambda: False)

    page = HomePage(gui_state, Adw.ToastOverlay())
    start = time.monotonic()
    page.refresh()  # a second, explicit refresh
    elapsed = time.monotonic() - start
    # The call returned immediately, so the slow probe is still in flight.
    assert elapsed < SLOW / 2, f"refresh blocked for {elapsed:.2f}s"
    assert started.wait(2.0), "the probe never started on a worker thread"


def test_toggle_click_returns_immediately(gui_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Clicking the big button must not wait for a slow start/stop."""
    import gi

    import linguafix.app_focus as app_focus

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from linguafix.gui.home_page import HomePage
    from linguafix.gui.widgets.big_toggle import STATE_BUSY

    monkeypatch.setattr(app_focus, "get_active_app", lambda: None)
    monkeypatch.setattr(gui_state, "is_active", lambda: False)
    monkeypatch.setattr(gui_state, "current_layout", lambda: "")
    monkeypatch.setattr(gui_state, "is_autostart_enabled", lambda: False)
    monkeypatch.setattr(gui_state, "start", lambda: time.sleep(SLOW) or True)

    page = HomePage(gui_state, Adw.ToastOverlay())
    start = time.monotonic()
    page._on_toggle_clicked()
    elapsed = time.monotonic() - start
    assert elapsed < SLOW / 2, f"click blocked for {elapsed:.2f}s"
    assert page.toggle.state == STATE_BUSY


def test_async_helper_delivers_on_main_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """``run_in_background`` calls its callback and never raises on failure."""
    import gi

    gi.require_version("GLib", "2.0")

    from linguafix.gui.async_utils import run_in_background

    results: list[Any] = []
    done = threading.Event()

    def callback(value: Any) -> None:
        results.append(value)
        done.set()

    run_in_background(lambda: 41 + 1, callback)
    _pump_until(done)
    assert results == [42]

    # A raising callable is delivered as ``None`` instead of crashing.
    done2 = threading.Event()
    results2: list[Any] = []

    def callback2(value: Any) -> None:
        results2.append(value)
        done2.set()

    def boom() -> None:
        raise RuntimeError("nope")

    run_in_background(boom, callback2)
    _pump_until(done2)
    assert results2 == [None]
