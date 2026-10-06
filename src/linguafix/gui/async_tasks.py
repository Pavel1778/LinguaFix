"""Run blocking work off the GTK main thread.

Every daemon control call (``systemctl``, ``g3kb-switch``, a focus probe) is a
subprocess that can block for its whole timeout. Calling one directly from a
signal handler freezes the UI: GNOME shows "Приложение не отвечает" and the
window stops repainting. This helper runs such work in a worker thread and
delivers the result back to the main thread through ``GLib.idle_add``, which is
the only thread-safe way to touch widgets.

The worker uses a ``concurrent.futures`` pool rather than ``Gio.Subprocess`` so
the same code path works for any callable — including the pure-Python daemon
helpers — and so the tests can drive it without a real subprocess.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

T = TypeVar("T")

# A single worker is enough: the calls are short and serialized by the user's
# own clicks. More threads would only let two systemctl calls race each other.
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="linguafix-gui")


def run_async(
    work: Callable[[], T],
    on_done: Callable[[T], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> None:
    """Run ``work`` in a worker thread and deliver its result on the main loop.

    Args:
        work: The blocking callable to run off the main thread.
        on_done: Called on the GTK main thread with ``work``'s return value.
        on_error: Called on the GTK main thread when ``work`` raises; when
            omitted the exception is swallowed (the UI keeps its last state).

    Returns:
        ``None``. The callbacks fire later, on the main loop.
    """

    def _deliver(future: Any) -> None:
        try:
            result = future.result()
        except BaseException as exc:
            if on_error is not None:
                GLib.idle_add(on_error, exc)
            return
        if on_done is not None:
            GLib.idle_add(on_done, result)

    _EXECUTOR.submit(work).add_done_callback(_deliver)


__all__ = ["run_async"]
