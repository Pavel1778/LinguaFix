"""Character-level conversion between keyboard layouts.

The converter maps text typed in one layout to the text that would have been
produced by the same physical key presses in another layout. It relies on the
bundled ``layouts.json`` file which stores, for every layout, a mapping from
canonical US characters (physical key position plus shift state) to the
character produced by that layout.
"""

from __future__ import annotations

import json
import logging
from importlib import resources
from typing import Final

logger = logging.getLogger(__name__)

DEFAULT_LAYOUT_FILE: Final[str] = "layouts.json"


class LayoutConverter:
    """Convert text between keyboard layouts using position-based maps.

    Args:
        layouts_file: Optional path to a layout definition JSON file. When not
            provided, the file bundled with the package is used.
    """

    def __init__(self, layouts_file: str | None = None) -> None:
        self._layouts: dict[str, dict[str, object]] = {}
        self._forward: dict[str, dict[str, str]] = {}
        self._reverse: dict[str, dict[str, str]] = {}
        self._load(layouts_file)

    def _load(self, layouts_file: str | None) -> None:
        """Load layout definitions and build forward/reverse maps."""
        try:
            if layouts_file is None:
                text = (resources.files("linguafix") / "data" / DEFAULT_LAYOUT_FILE).read_text(
                    encoding="utf-8"
                )
            else:
                with open(layouts_file, encoding="utf-8") as handle:
                    text = handle.read()
            payload = json.loads(text)
        except (OSError, json.JSONDecodeError):
            logger.error("Could not load layout definitions", exc_info=True)
            payload = {"layouts": {}}

        layouts = payload.get("layouts", {})
        for name, definition in layouts.items():
            char_map = definition.get("map", {})
            if not isinstance(char_map, dict):
                continue
            clean = {str(key): str(value) for key, value in char_map.items()}
            self._layouts[str(name)] = definition
            self._forward[str(name)] = clean
            # Reverse map: character produced in this layout -> canonical US char.
            reverse: dict[str, str] = {}
            for canonical, produced in clean.items():
                reverse.setdefault(produced, canonical)
            self._reverse[str(name)] = reverse

    @property
    def available_layouts(self) -> list[str]:
        """Return the list of layout identifiers known to the converter."""
        return list(self._layouts)

    def alphabet(self, layout: str) -> str:
        """Return the alphabet family of ``layout`` (``latin``/``cyrillic``)."""
        definition = self._layouts.get(layout, {})
        return str(definition.get("alphabet", "latin"))

    def convert(self, text: str, from_layout: str, to_layout: str) -> str:
        """Convert ``text`` from one layout to another.

        Characters that have no mapping in the source layout are copied
        unchanged, so mixed strings survive a round trip as far as possible.

        Args:
            text: The text to convert.
            from_layout: Source layout identifier (for example ``"us"``).
            to_layout: Target layout identifier (for example ``"ru"``).

        Returns:
            The converted text. When either layout is unknown the input is
            returned unchanged.

        Examples:
            >>> LayoutConverter().convert("ghbdtn", "us", "ru")
            'привет'
        """
        if from_layout == to_layout:
            return text

        forward = self._forward.get(from_layout)
        target = self._forward.get(to_layout)
        reverse = self._reverse.get(from_layout)
        if forward is None or target is None or reverse is None:
            logger.debug("Unknown layout pair %s -> %s", from_layout, to_layout)
            return text

        result: list[str] = []
        for char in text:
            canonical = reverse.get(char, char)
            result.append(target.get(canonical, char))
        return "".join(result)
