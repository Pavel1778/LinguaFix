"""Text expansion (snippets).

A snippet turns a short trigger typed at a word boundary into longer text:
``!!email`` becomes ``user@example.com``. Expansion is checked *before* layout
detection, so a trigger is honoured as-is and never "corrected" into another
layout. Off by default: it only runs when ``text_expander_enabled`` is set.

The snippets live in a TOML file (``~/.config/linguafix/snippets.toml`` by
default) with a single ``[snippets]`` table mapping trigger to expansion:

.. code-block:: toml

    [snippets]
    "!!email" = "user@example.com"
    "!!shrug" = "¯\\_(ツ)_/¯"
    "!!date" = "{date}"

``{date}`` and ``{time}`` are substituted at expansion time.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Final

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib

logger = logging.getLogger(__name__)

# Placeholders substituted at expansion time.
_DATE_TOKEN: Final[str] = "{date}"
_TIME_TOKEN: Final[str] = "{time}"


class TextExpander:
    """Map short triggers to longer expansions, loaded from a TOML file."""

    def __init__(self, snippets: dict[str, str] | None = None) -> None:
        self._snippets: dict[str, str] = dict(snippets or {})

    @property
    def snippets(self) -> dict[str, str]:
        """Return a copy of the loaded snippets."""
        return dict(self._snippets)

    def load(self, path: str | Path) -> None:
        """Load snippets from ``path``.

        A missing or malformed file leaves the current snippets untouched and
        logs the problem; the daemon must keep running.
        """
        target = Path(path).expanduser()
        try:
            raw = target.read_bytes()
            data = tomllib.loads(raw.decode("utf-8"))
        except FileNotFoundError:
            logger.debug("Snippets file %s not found", target)
            return
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            logger.warning("Could not read snippets from %s: %s", target, exc)
            return
        table = data.get("snippets", {})
        if not isinstance(table, dict):
            logger.warning("snippets.toml has no [snippets] table; ignoring")
            return
        self._snippets = {str(key): str(value) for key, value in table.items()}

    def check(self, buffer: str) -> tuple[str, str] | None:
        """Return ``(trigger, expansion)`` when ``buffer`` is a snippet.

        The match is exact and case-sensitive. Placeholders are resolved here,
        so the returned expansion is ready to inject.
        """
        expansion = self._snippets.get(buffer)
        if expansion is None:
            return None
        return buffer, self._resolve(expansion)

    @staticmethod
    def _resolve(expansion: str) -> str:
        now = datetime.now()
        return expansion.replace(_DATE_TOKEN, now.strftime("%Y-%m-%d")).replace(
            _TIME_TOKEN, now.strftime("%H:%M")
        )
