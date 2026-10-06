"""Run blocking probes off the GTK main thread.

Every daemon probe in the GUI -- ``systemctl``, ``g3kb-switch``, ``xprop`` and
the GNOME/AT-SPI D-Bus calls -- is a subprocess or a blocking IPC round-trip
with a timeout of up to five seconds. Running one on the GTK main thread freezes
the whole window for that long, which is exactly what makes GNOME show
"приложение не отвечает". These helpers hand a call to a worker thread and
deliver its result back on the main thread through ``GLib.idle_add``, so the UI
keeps painting while the probe runs.

Nothing here ever touches typed text; the callables are daemon probes only.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any, TypeVar

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _deliver(callback: Callable[[Any], None], value: Any) -> bool:
    """Run ``callback`` on the main thread; return ``False`` to stop the source."""
    try:
        callback(value)
    except Exception:  # pragma: no cover - a widget may be gone by now
        logger.debug("Async result callback failed", exc_info=True)
    return False


def run_in_background(
    fn: Callable[..., T],
    on_done: Callable[[T], None],
    *args: Any,
    **kwargs: Any,
) -> None:
    """Call ``fn(*args, **kwargs)`` on a worker thread, then ``on_done`` on main.

    ``on_done`` always runs on the GTK main thread (via ``GLib.idle_add``), so it
    may touch widgets directly. A failure inside ``fn`` is logged and delivered as
    ``None`` rather than crashing the worker.
    """

    def worker() -> None:
        try:
            value: Any = fn(*args, **kwargs)
        except Exception:
            logger.debug("Background probe failed", exc_info=True)
            value = None
        GLib.idle_add(_deliver, on_done, value)

    threading.Thread(target=worker, name="linguafix-gui-probe", daemon=True).start()
