"""Light punctuation clean-up ("T9 with punctuation").

This is a rule engine, not a language model: every rule is deterministic and
opt-in. It only touches punctuation and spacing, never the words themselves, so
it can never corrupt a word the way an over-eager spell-checker would. When the
whole feature is disabled (the default) the daemon never calls into here and the
typed text is untouched.

The processor works on a text fragment. The daemon feeds it the word plus the
trailing punctuation run it accumulated, so ``текст--`` becomes ``текст—`` and
``текст ...`` becomes ``текст…``. Auto-capitalisation and the sentence-final
period are deliberately the last rules and off by default: guessing where a
sentence begins is the one thing that most often looks wrong.
"""

from __future__ import annotations

import re

# A run of two or more dots becomes a single ellipsis character. Three is the
# typographic norm; ``..`` and ``....`` are normalised to it too.
_ELLIPSIS_RE = re.compile(r"\.{2,}")
# A double hyphen is an em dash. A single hyphen is left alone (it is a hyphen,
# a minus sign or part of an identifier).
_DASH_RE = re.compile(r"--")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?…—])")
_MULTISPACE_RE = re.compile(r" {2,}")
_SPACE_AFTER_PUNCT_RE = re.compile(r"([,;:])(?=[^\s\d])")
_QUOTED_RE = re.compile(r'"([^"\n]+)"')


class PunctuationProcessor:
    """Apply a fixed set of punctuation and spacing rules to a fragment."""

    def __init__(
        self,
        *,
        replace_dashes: bool = True,
        replace_ellipsis: bool = True,
        smart_quotes: bool = False,
        fix_spacing: bool = True,
        auto_capitalize: bool = False,
        auto_period: bool = False,
    ) -> None:
        self.replace_dashes = replace_dashes
        self.replace_ellipsis = replace_ellipsis
        self.smart_quotes = smart_quotes
        self.fix_spacing = fix_spacing
        self.auto_capitalize = auto_capitalize
        self.auto_period = auto_period

    def process(self, text: str, layout: str = "") -> str:
        """Return ``text`` with the enabled punctuation rules applied.

        Args:
            text: The fragment to clean up.
            layout: The active layout code. Russian (``ru``/``uk``) uses guillemets
                for smart quotes; other layouts keep the straight quotes.

        Returns:
            The transformed text. It equals ``text`` when no rule applies, so a
            caller can compare and skip the replacement.
        """
        if not text:
            return text
        result = text
        if self.replace_ellipsis:
            result = _ELLIPSIS_RE.sub("…", result)
        if self.replace_dashes:
            result = self._replace_dashes(result)
        if self.smart_quotes:
            result = self._apply_quotes(result, layout)
        if self.fix_spacing:
            result = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", result)
            result = _SPACE_AFTER_PUNCT_RE.sub(r"\1 ", result)
            result = _MULTISPACE_RE.sub(" ", result)
        if self.auto_capitalize:
            result = self._capitalize(result)
        if self.auto_period:
            result = self._add_period(result)
        return result

    @staticmethod
    def _replace_dashes(text: str) -> str:
        """Turn a double hyphen into an em dash, keeping the surrounding space."""
        if "--" not in text:
            return text
        return _DASH_RE.sub("—", text)

    @staticmethod
    def _apply_quotes(text: str, layout: str) -> str:
        """Convert straight double quotes to guillemets in Cyrillic layouts."""
        if layout not in ("ru", "uk"):
            return text
        return _QUOTED_RE.sub(r"«\1»", text)

    @staticmethod
    def _capitalize(text: str) -> str:
        """Upper-case the first letter without touching the rest."""
        for index, char in enumerate(text):
            if char.isalpha():
                return text[:index] + char.upper() + text[index + 1 :]
        return text

    @staticmethod
    def _add_period(text: str) -> str:
        """Append a period when the fragment ends in a bare word."""
        if not text or text[-1] in ".!?…,;:—":
            return text
        return text + "."


__all__ = ["PunctuationProcessor"]
