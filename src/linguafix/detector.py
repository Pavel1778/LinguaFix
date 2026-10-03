"""Language detection for typed text.

The detector combines three signals to decide which language a buffer of typed
text most likely belongs to:

1. The alphabet used by each word (Cyrillic versus Latin).
2. Membership in a small frequency vocabulary shipped with the package.
3. Bigram "plausibility" scores derived from those vocabularies.

It is deliberately lightweight: LinguaFix only needs to distinguish a couple of
layouts well enough to decide whether text should be converted, not to perform
general purpose language identification.
"""

from __future__ import annotations

import json
import logging
import math
import re
from importlib import resources
from typing import Any, Final

from .converter import LayoutConverter

logger = logging.getLogger(__name__)

CYRILLIC_RE: Final[re.Pattern[str]] = re.compile(r"[\u0400-\u04FF]")
LATIN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z]")
WORD_RE: Final[re.Pattern[str]] = re.compile(r"[\w']+", re.UNICODE)
TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9_]+", re.IGNORECASE)

# Minimum number of words required for a confident whole-buffer verdict.
MIN_WORDS_FOR_CONFIDENCE: Final[int] = 2
# A bigram that never appeared in the corpus still carries a small probability.
UNKNOWN_BIGRAM_PROBABILITY: Final[float] = 1e-7
# Minimum plausibility gain required before a conversion is applied.
MIN_IMPROVEMENT: Final[float] = 1.0


def _has_cyrillic(text: str) -> bool:
    """Return ``True`` if ``text`` contains at least one Cyrillic letter."""
    return bool(CYRILLIC_RE.search(text))


def _has_latin(text: str) -> bool:
    """Return ``True`` if ``text`` contains at least one Latin letter."""
    return bool(LATIN_RE.search(text))


def _alphabet_of(word: str) -> str:
    """Classify a word as ``cyrillic``, ``latin`` or ``other``."""
    if _has_cyrillic(word):
        return "cyrillic"
    if _has_latin(word):
        return "latin"
    return "other"


class LanguageDetector:
    """Detect the language of a buffer and decide whether it should be fixed.

    Args:
        converter: Optional :class:`~linguafix.converter.LayoutConverter`
            used to produce candidate conversions of the buffer. A default
            converter is created when none is supplied.
        stop_words: Optional iterable of stop words overriding the bundled list.
        min_word_length: Words shorter than this are ignored by detection.
    """

    def __init__(
        self,
        converter: LayoutConverter | None = None,
        stop_words: list[str] | None = None,
        min_word_length: int = 3,
    ) -> None:
        self.converter = converter or LayoutConverter()
        self.min_word_length = min_word_length
        self._stop_words = {word.lower() for word in (stop_words or [])}
        self._vocabularies: dict[str, set[str]] = {}
        self._bigrams: dict[str, dict[str, float]] = {}
        self._load_corpora()

    def _load_corpora(self) -> None:
        """Load bigram frequencies and vocabularies for every known language."""
        for language in ("ru", "en"):
            payload = self._read_corpus(language)
            self._vocabularies[language] = {str(w).lower() for w in payload.get("words", [])}
            self._bigrams[language] = {
                str(bg): float(freq) for bg, freq in payload.get("bigrams", {}).items()
            }

    @staticmethod
    def _read_corpus(language: str) -> dict[str, Any]:
        """Read ``ngrams_<language>.json`` returning an empty mapping on error."""
        try:
            text = (resources.files("linguafix") / "data" / f"ngrams_{language}.json").read_text(
                encoding="utf-8"
            )
            data: Any = json.loads(text)
        except (OSError, json.JSONDecodeError):
            logger.error("Could not load ngrams for %s", language, exc_info=True)
            return {}
        return data if isinstance(data, dict) else {}

    @property
    def stop_words(self) -> set[str]:
        """Return the set of active stop words (lower-cased)."""
        return set(self._stop_words)

    def set_stop_words(self, words: list[str]) -> None:
        """Replace the active stop-word set."""
        self._stop_words = {word.lower() for word in words}

    def is_stop_word(self, text: str) -> bool:
        """Return ``True`` if ``text`` contains any configured stop word.

        Args:
            text: Buffer to inspect.

        Returns:
            ``True`` when at least one stop word occurs as a whole token.
        """
        tokens = {match.group(0).lower() for match in TOKEN_RE.finditer(text)}
        if tokens & self._stop_words:
            return True
        return bool(self._stop_words & {text.strip().lower()})

    def _bigram_score(self, word: str, language: str) -> float:
        """Return the average log-probability of ``word`` in ``language``."""
        model = self._bigrams.get(language, {})
        if not model:
            return float("-inf")
        padded = "^" + word.lower() + "$"
        pairs = [padded[i : i + 2] for i in range(len(padded) - 1)]
        if not pairs:
            return float("-inf")
        total = 0.0
        for pair in pairs:
            probability = model.get(pair, UNKNOWN_BIGRAM_PROBABILITY)
            total += math.log(probability)
        return total / len(pairs)

    def _score_word(self, word: str) -> dict[str, float]:
        """Return a vote for each language for a single word."""
        lowered = word.lower()
        scores = {"ru": 0.0, "en": 0.0}
        alphabet = _alphabet_of(word)

        if alphabet == "cyrillic":
            scores["ru"] += 2.0
            scores["en"] -= 1.0
        elif alphabet == "latin":
            scores["en"] += 2.0
            scores["ru"] -= 1.0

        for language in scores:
            if lowered in self._vocabularies.get(language, set()):
                scores[language] += 3.0
            bigram = self._bigram_score(lowered, language)
            if bigram != float("-inf"):
                scores[language] += bigram

        return scores

    def detect(self, text: str) -> str | None:
        """Return the most likely language of ``text``.

        Args:
            text: Buffer of typed characters.

        Returns:
            ``"ru"``, ``"en"`` or ``None`` when the buffer is empty or the
            result is not confident enough.
        """
        words = [w for w in WORD_RE.findall(text) if len(w) >= self.min_word_length]
        if not words:
            return None

        totals = {"ru": 0.0, "en": 0.0}
        for word in words:
            scores = self._score_word(word)
            for language, value in scores.items():
                totals[language] += value

        if totals["ru"] == totals["en"]:
            return None

        best = max(totals, key=lambda language: totals[language])
        other = "en" if best == "ru" else "ru"
        # Require a positive margin for short buffers.
        margin = totals[best] - totals[other]
        if len(words) < MIN_WORDS_FOR_CONFIDENCE and margin < 1.0:
            return None
        return best

    def _layout_language(self, layout: str) -> str | None:
        """Map a layout identifier to a language family."""
        alphabet = self.converter.alphabet(layout)
        if alphabet == "cyrillic":
            return "ru"
        if alphabet == "latin":
            return "en"
        return None

    def _language_layout(self, language: str) -> str | None:
        """Return a layout identifier for a language family."""
        for layout in self.converter.available_layouts:
            if self._layout_language(layout) == language:
                return layout
        return None

    def _plausibility(self, text: str, language: str) -> float:
        """Score how plausible ``text`` is as words of ``language``.

        The score combines a vocabulary bonus with the average bigram
        log-probability of every sufficiently long word. Unknown bigrams are
        heavily penalised, which naturally rejects text written in the wrong
        script for the language.
        """
        vocabulary = self._vocabularies.get(language, set())
        total = 0.0
        for word in WORD_RE.findall(text):
            if len(word) < self.min_word_length:
                continue
            lowered = word.lower()
            if lowered in vocabulary:
                total += 3.0
            bigram = self._bigram_score(lowered, language)
            if bigram != float("-inf"):
                total += bigram
        return total

    def target_layout(self, buffer: str, current_layout: str) -> str | None:
        """Return the layout ``buffer`` should be converted to, if any.

        Every other known layout is tried as a conversion target and scored in
        its own language. A candidate wins only when it is clearly more
        plausible than the buffer as typed.

        Args:
            buffer: The typed text.
            current_layout: The layout that is currently active.

        Returns:
            A layout identifier to switch to, or ``None`` when no conversion
            is worthwhile.
        """
        stripped = buffer.strip()
        if not stripped or self.is_stop_word(stripped):
            return None

        words = [w for w in WORD_RE.findall(stripped) if len(w) >= self.min_word_length]
        if not words:
            return None

        current_language = self._layout_language(current_layout)
        current_score = self._plausibility(stripped, current_language) if current_language else 0.0

        best_layout: str | None = None
        best_score = current_score
        for layout in self.converter.available_layouts:
            if layout == current_layout:
                continue
            language = self._layout_language(layout)
            if language is None or language == current_language:
                continue
            converted = self.converter.convert(stripped, current_layout, layout)
            score = self._plausibility(converted, language)
            if score > best_score:
                best_score = score
                best_layout = layout

        if best_layout is None:
            return None
        if best_score - current_score < MIN_IMPROVEMENT:
            return None
        return best_layout

    def should_fix(self, buffer: str, current_layout: str | None = None) -> bool:
        """Decide whether ``buffer`` should be corrected.

        A buffer is a correction candidate when it mixes alphabets, or when the
        whole buffer becomes a clearly more plausible word of another language
        after conversion.

        Args:
            buffer: The typed text.
            current_layout: The layout that is currently active, used to avoid
                "correcting" text that is already fine.

        Returns:
            ``True`` if LinguaFix should rewrite the buffer.
        """
        stripped = buffer.strip()
        if not stripped or self.is_stop_word(stripped):
            return False

        if _has_cyrillic(stripped) and _has_latin(stripped):
            return True

        if current_layout is None:
            return self.detect(stripped) is not None
        return self.target_layout(stripped, current_layout) is not None

    def convert_buffer(self, buffer: str, from_layout: str, to_layout: str) -> str:
        """Convert ``buffer`` preserving layout via the internal converter."""
        return self.converter.convert(buffer, from_layout, to_layout)
