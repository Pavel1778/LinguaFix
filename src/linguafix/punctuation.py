"""Opt-in punctuation cleanup for a finished word.

Off by default. This is a small, fixed rule engine -- never a language model --
so it is predictable and cheap. It only ever rewrites punctuation, never
letters, and a caller may additionally veto any replacement whose characters the
text backend cannot type (the ``uinput`` backend can only produce characters it
has a physical key for, so an em dash or an ellipsis is left alone there).

The rules are deliberately few. Automatic comma insertion, sentence
capitalisation and similar heuristics are not attempted: they are wrong often
enough to be worse than doing nothing.
"""

from __future__ import annotations

import re

# A run of two or more hyphens becomes an em dash; three or more dots an
# ellipsis. Straight quotes become guillemets only in a Cyrillic layout.
_DASH_RE = re.compile(r"-{2,}")
_ELLIPSIS_RE = re.compile(r"\.{3,}")
_QUOTED_RE = re.compile(r'"([^"]*)"')
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+([,.!?;:])")
_SPACE_AFTER_PUNCT_RE = re.compile(r"([,;:!?])(?=[^\s])")
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")


class PunctuationCorrector:
    """Apply a fixed set of punctuation cleanups to a finished token."""

    def __init__(
        self,
        *,
        dashes: bool = True,
        ellipsis: bool = True,
        smart_quotes: bool = False,
        fix_spacing: bool = True,
    ) -> None:
        self.dashes = dashes
        self.ellipsis = ellipsis
        self.smart_quotes = smart_quotes
        self.fix_spacing = fix_spacing

    def correct(self, text: str, layout: str = "") -> str:
        """Return ``text`` with the enabled cleanups applied.

        Args:
            text: The finished token, as typed.
            layout: The active layout; guillemets are only applied for a
                Cyrillic layout (``ru``/``uk``).
        """
        if not text:
            return text
        result = text
        if self.dashes:
            result = _DASH_RE.sub("\u2014", result)
        if self.ellipsis:
            result = _ELLIPSIS_RE.sub("\u2026", result)
        if self.smart_quotes and layout.lower().startswith(("ru", "uk")):
            result = _QUOTED_RE.sub("\u00ab\\1\u00bb", result)
        if self.fix_spacing:
            result = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", result)
            result = _SPACE_AFTER_PUNCT_RE.sub(r"\1 ", result)
            result = _MULTISPACE_RE.sub(" ", result)
        return result
