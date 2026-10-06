"""The GUI must never block its main loop on a slow daemon probe (P0).

Before this change ``HomePage.refresh`` called ``subprocess.run`` for
``systemctl is-active``, ``g3kb-switch -p`` and ``systemctl is-enabled`` on the
GTK main thread, each with a multi-second timeout. A hung systemd or
g3kb-switch froze the whole window ("Приложение не отвечает"). These tests make
the status collector block for seconds and assert that the main loop keeps
turning while the collector runs on a worker thread.

The probe is proven to be off-thread by scheduling a main-loop timeout: a
blocked main loop cannot fire it.
"""

from __future__ import annotations

import time

import pytest

pytest.importorskip("gi")


def _gtk_usable() -> bool:
    import os

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
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


def _spin(seconds: float) -> None:
    """Turn the default main loop for ``seconds``."""
    import gi

    gi.require_version("GLib", "2.0")
    from gi.repository import GLib

    context = GLib.MainContext.default()
    deadline = time.time() + seconds
    while time.time() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.002)


def _wait_for_worker_idle() -> None:
    """Let the shared worker thread finish any task from a previous test."""
    from linguafix.gui.async_tasks import _EXECUTOR

    _EXECUTOR.submit(lambda: None).result(timeout=5)


def _state_with_slow_collector(delay: float) -> object:
    from linguafix.config import Config
    from linguafix.gui.state import GuiState, StatusSnapshot

    state = GuiState(config=Config(dictionary_custom_path=""))

    def slow_collect() -> StatusSnapshot:
        # Stands in for three blocking subprocess calls with multi-second
        # timeouts, which is exactly what froze the window before.
        time.sleep(delay)
        return StatusSnapshot(active=True, layout="ru", autostart=True)

    state._collect_status = slow_collect  # type: ignore[method-assign]
    return state


def test_slow_probe_does_not_block_the_main_loop() -> None:
    """A collector that blocks for seconds must not freeze the main loop."""
    import gi

    gi.require_version("Adw", "1")
    gi.require_version("GLib", "2.0")
    from gi.repository import Adw, GLib

    from linguafix.gui.home_page import HomePage

    _wait_for_worker_idle()
    state = _state_with_slow_collector(delay=1.0)
    page = HomePage(state, Adw.ToastOverlay())  # type: ignore[arg-type]
    page.refresh()
    assert page._probe_in_flight is True

    # A main-loop timeout can only fire if the loop is still turning. With the
    # probe blocking the main thread it would never fire.
    fired: list[bool] = []
    GLib.timeout_add(50, lambda: (fired.append(True), False)[1])
    _spin(0.5)
    assert fired, "main loop did not run while the probe was in flight"
    assert page._probe_in_flight is True


def test_slow_probe_result_is_applied_after_it_completes() -> None:
    """The snapshot is applied once the worker finishes, not before."""
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    from linguafix.gui.home_page import HomePage
    from linguafix.gui.widgets.big_toggle import STATE_ON

    _wait_for_worker_idle()
    state = _state_with_slow_collector(delay=0.3)
    page = HomePage(state, Adw.ToastOverlay())  # type: ignore[arg-type]
    page.refresh()
    _spin(1.0)
    assert page.toggle.state == STATE_ON
    assert page._probe_in_flight is False
