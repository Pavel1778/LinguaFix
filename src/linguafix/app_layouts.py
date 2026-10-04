"""Per-app default layout (Stage 9).

Some applications are almost always used in one language: a terminal with
Russian, a chat with English, and so on. This remembers a preferred layout per
application and can switch to it when that application gains focus, so the
first word of a sentence is already in the right layout.

The mapping is owned by the user (``Config.app_layouts``); nothing is learned
automatically from typed text.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Final

logger = logging.getLogger(__name__)

# The focused application is re-probed at most this often; focus checks run on
# every word boundary, so this keeps the cost of the accessibility probes down.
POLL_INTERVAL: Final[float] = 0.35


def normalise_app(name: str) -> str:
    """Return the comparison key for an application name."""
    return name.strip().lower()


class AppLayoutManager:
    """Track the focused application and apply its preferred layout.

    Args:
        layouts: Mapping of application name to layout identifier.
        switch_layout: Callable that switches the active layout.
        probe: Callable returning the focused application name, or ``None``.
        enabled: Master switch for automatic switching.
    """

    def __init__(
        self,
        layouts: dict[str, str] | None = None,
        switch_layout: Callable[[str], bool] | None = None,
        probe: Callable[[], str | None] | None = None,
        enabled: bool = False,
    ) -> None:
        self.layouts = {normalise_app(k): v.lower() for k, v in (layouts or {}).items()}
        self._switch = switch_layout
        self._probe = probe
        self.enabled = enabled
        self._current: str | None = None
        self._last_check = float("-inf")

    def update(
        self, layouts: dict[str, str], *, enabled: bool, switch_layout: Callable[[str], bool]
    ) -> None:
        """Replace the mapping and callbacks after a config reload."""
        self.layouts = {normalise_app(k): v.lower() for k, v in layouts.items()}
        self.enabled = enabled
        self._switch = switch_layout
        self._current = None
        # Force a fresh probe on the next word boundary after a reload.
        self._last_check = float("-inf")

    def preferred_layout(self, app: str | None) -> str | None:
        """Return the preferred layout for ``app``, or ``None``."""
        if not app:
            return None
        return self.layouts.get(normalise_app(app))

    def maybe_apply(self, now: float) -> str | None:
        """Probe the focused app and switch to its layout when it changed.

        Returns the layout that was switched to, or ``None`` when nothing
        happened (feature off, no mapping, no change, or a failed probe).
        """
        if not self.enabled or not self.layouts or self._probe is None:
            return None
        if now - self._last_check < POLL_INTERVAL:
            return None
        self._last_check = now
        try:
            app = self._probe()
        except Exception:
            logger.debug("Focus probe failed", exc_info=True)
            return None
        if not app:
            return None
        key = normalise_app(app)
        if key == self._current:
            # Same application as last time: do not fight the user's manual
            # layout change.
            return None
        self._current = key
        layout = self.layouts.get(key)
        if layout is None or self._switch is None:
            return None
        if self._switch(layout):
            logger.debug("Switched to per-app layout for a focused application")
            return layout
        return None

    def describe(self) -> str:
        """Return a short human-readable summary of the mapping."""
        entries: Iterable[str] = (
            f"{app}->{layout}" for app, layout in sorted(self.layouts.items())
        )
        return ", ".join(entries) or "no per-app layouts"
