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

# Which language each known layout types. Latin layouts share the same physical
# positions, so their corpora are interchangeable; the mapping keeps detection
# honest for Cyrillic layouts (``ru`` and ``uk`` share an alphabet family but
# are distinct languages).
LAYOUT_LANGUAGES: Final[dict[str, str]] = {
    "us": "en",
    "gb": "en",
    "de": "de",
    "fr": "fr",
    "ru": "ru",
    "uk": "uk",
}
# Reverse lookup used to pick a layout for a language family.
LAYOUTS_BY_LANGUAGE: Final[dict[str, tuple[str, ...]]] = {
    "en": ("us", "gb"),
    "de": ("de",),
    "fr": ("fr",),
    "ru": ("ru",),
    "uk": ("uk",),
}

# Languages whose corpora are loaded when the caller does not specify any.
# Only the two most common ones are on by default: enabling every shipped
# language makes the Latin layouts ambiguous, so ``uk``/``de``/``fr`` are opt-in
# through ``Config.languages``.
DEFAULT_DETECTOR_LANGUAGES: Final[tuple[str, ...]] = ("en", "ru")

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
        confidence_threshold: Minimum plausibility margin before a conversion
            is applied. Higher values make the detector more conservative.
        languages: Languages that have bundled corpora and may be targeted.
    """

    def __init__(
        self,
        converter: LayoutConverter | None = None,
        stop_words: list[str] | None = None,
        min_word_length: int = 3,
        confidence_threshold: float = 0.6,
        languages: tuple[str, ...] | None = None,
        dictionary_size: int = 0,
        user_words: list[str] | None = None,
    ) -> None:
        self.converter = converter or LayoutConverter()
        self.min_word_length = min_word_length
        self.confidence_threshold = confidence_threshold
        # How much a neighbouring word may nudge the verdict (0 disables it).
        self.context_weight = 0.0
        self._languages = languages
        self._dictionary_size = dictionary_size
        self._user_words = {word.lower() for word in (user_words or []) if word.strip()}
        self._stop_words = {word.lower() for word in (stop_words or [])}
        self._vocabularies: dict[str, set[str]] = {}
        self._bigrams: dict[str, dict[str, float]] = {}
        self._load_corpora()

    def _load_corpora(self) -> None:
        """Load bigram frequencies and vocabularies for every known language."""
        candidates = (
            list(self._languages)
            if self._languages is not None
            else list(DEFAULT_DETECTOR_LANGUAGES)
        )
        for language in candidates:
            payload = self._read_corpus(language)
            vocabulary = {str(w).lower() for w in payload.get("words", [])}
            bigrams = {str(bg): float(freq) for bg, freq in payload.get("bigrams", {}).items()}
            if not vocabulary and not bigrams:
                # A layout whose language has no bundled corpus yet (for example
                # ``de`` before its dictionary ships) must not be a conversion
                # target: an empty model scores every candidate as 0.0 and would
                # win by accident.
                logger.debug("No corpus for language %s; skipping it", language)
                continue
            if self._dictionary_size > 0:
                # ``dictionary_size`` trades memory for recall. The bundled
                # lists are already sorted by frequency, so truncation keeps the
                # most common words.
                vocabulary = set(sorted(vocabulary)[: self._dictionary_size])
            self._vocabularies[language] = vocabulary
            self._bigrams[language] = bigrams

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

    def set_confidence_threshold(self, threshold: float) -> None:
        """Update the minimum confidence required to apply a conversion."""
        self.confidence_threshold = threshold

    def set_languages(self, languages: tuple[str, ...]) -> None:
        """Reload the corpora for ``languages`` (used when config changes)."""
        if tuple(languages) == self._languages:
            return
        self._languages = tuple(languages)
        self._vocabularies = {}
        self._bigrams = {}
        self._load_corpora()

    def set_context_weight(self, weight: float) -> None:
        """Update how much a neighbouring word may influence the verdict."""
        self.context_weight = weight

    def set_dictionary_size(self, size: int) -> None:
        """Update the vocabulary cap and reload the corpora."""
        if size == self._dictionary_size:
            return
        self._dictionary_size = size
        self._vocabularies = {}
        self._bigrams = {}
        self._load_corpora()

    def set_user_words(self, words: list[str]) -> None:
        """Replace the user dictionary and reload the corpora."""
        self._user_words = {word.lower() for word in words if word.strip()}
        self._vocabularies = {}
        self._bigrams = {}
        self._load_corpora()

    @property
    def user_words(self) -> list[str]:
        """Return the user dictionary (lower-cased, sorted)."""
        return sorted(self._user_words)

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
        scores = dict.fromkeys(self._vocabularies, 0.0)
        alphabet = _alphabet_of(word)

        for language in scores:
            family = self._language_family(language)
            if (family == "cyrillic" and alphabet == "cyrillic") or (
                family == "latin" and alphabet == "latin"
            ):
                scores[language] += 2.0
            elif alphabet != "other":
                scores[language] -= 1.0

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

        totals = dict.fromkeys(self._vocabularies, 0.0)
        for word in words:
            scores = self._score_word(word)
            for language, value in scores.items():
                totals[language] += value

        if not totals:
            return None
        ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            return None

        best, best_score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else float("-inf")
        # Require a positive margin for short buffers.
        margin = best_score - runner_up
        if len(words) < MIN_WORDS_FOR_CONFIDENCE and margin < 1.0:
            return None
        return best

    def _detect_strong_context(self, text: str) -> str | None:
        """Return the language of a neighbouring word, or ``None``.

        Used as weak context: a word with only one candidate language is good
        evidence, an ambiguous one is ignored.
        """
        stripped = text.strip()
        if not stripped:
            return None
        return self.detect(stripped)

    def _language_family(self, language: str) -> str | None:
        """Map a language identifier to the alphabet family of its layout."""
        layout = self._language_layout(language)
        if layout is None:
            return None
        return self.converter.alphabet(layout)

    def _layout_language(self, layout: str) -> str | None:
        """Map a layout identifier to the language it types."""
        mapped = LAYOUT_LANGUAGES.get(layout)
        if mapped is not None:
            return mapped
        alphabet = self.converter.alphabet(layout)
        if alphabet == "cyrillic":
            return "ru"
        if alphabet == "latin":
            return "en"
        return None

    def _language_layout(self, language: str) -> str | None:
        """Return a layout identifier that types ``language``."""
        if language in LAYOUTS_BY_LANGUAGE:
            for layout in self.converter.available_layouts:
                if layout in LAYOUTS_BY_LANGUAGE[language]:
                    return layout
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

    def target_layout(
        self, buffer: str, current_layout: str, neighbor: str | None = None
    ) -> str | None:
        """Return the layout ``buffer`` should be converted to, if any.

        Every other known layout is tried as a conversion target and scored in
        its own language. A candidate wins only when it is clearly more
        plausible than the buffer as typed.

        Args:
            buffer: The typed text.
            current_layout: The layout that is currently active.
            neighbor: Optional preceding word used as weak context. When set and
                :attr:`context_weight` is positive it nudges the verdict toward
                the language of the neighbouring word.

        Returns:
            A layout identifier to switch to, or ``None`` when no conversion
            is worthwhile.
        """
        stripped = buffer.strip()
        if not stripped or self.is_stop_word(stripped):
            return None

        # A word the user explicitly taught is correct, in any layout: never
        # rewrite it. This is an absolute override, stronger than stop words.
        if stripped.lower() in self._user_words:
            return None

        words = [w for w in WORD_RE.findall(stripped) if len(w) >= self.min_word_length]
        if not words:
            return None

        # A buffer that mixes scripts is always wrong: part of it was typed on
        # the wrong layout. Rewrite it into the layout of the majority script,
        # which is the one the user most likely intended.
        if _has_cyrillic(stripped) and _has_latin(stripped):
            cyrillic = sum(1 for char in stripped if CYRILLIC_RE.match(char))
            latin = sum(1 for char in stripped if LATIN_RE.match(char))
            family = "cyrillic" if cyrillic >= latin else "latin"
            target_language = "ru" if family == "cyrillic" else "en"
            candidate = self._language_layout(target_language)
            if candidate is not None and candidate != current_layout:
                return candidate

        current_language = self._layout_language(current_layout)
        current_score = self._plausibility(stripped, current_language) if current_language else 0.0
        neighbor_language = self._detect_strong_context(neighbor) if neighbor else None

        best_layout: str | None = None
        best_score = current_score
        best_language = current_language
        for layout in self.converter.available_layouts:
            if layout == current_layout:
                continue
            language = self._layout_language(layout)
            if language is None or language not in self._vocabularies:
                # Without a corpus the candidate scores 0.0 for everything and
                # would win purely because the current text scores negative.
                continue
            # A candidate in the same alphabet family (for example ``ru`` ->
            # ``uk``, or ``de`` -> ``en``) is allowed: the physical positions are
            # identical for Latin layouts, so a German word typed on US can be
            # recognised as English. The language model still has to win.
            converted = self.converter.convert(stripped, current_layout, layout)
            score = self._plausibility(converted, language)
            if (
                neighbor_language is not None
                and self.context_weight > 0.0
                and language == neighbor_language
            ):
                # A neighbouring word is weak evidence, so it only ever *adds*
                # to a candidate; it can never push the current layout below
                # zero or override the absolute improvement check below.
                score += self.context_weight
            if score > best_score:
                best_score = score
                best_layout = layout
                best_language = language

        if best_layout is None:
            return None
        improvement = best_score - current_score
        # ``confidence_threshold`` raises the bar above the absolute minimum so
        # the user can make detection more conservative. It is deliberately
        # additive rather than a ratio: both scores can be negative for a word
        # that is not in either vocabulary, and a ratio would reject exactly the
        # wrong-layout words the detector exists to catch.
        if improvement < MIN_IMPROVEMENT + self.confidence_threshold:
            return None
        # Guard against a same-alphabet target that merely re-labels the text
        # without changing it (``de`` -> ``en`` leaves letters untouched).
        if (
            best_language == current_language
            and self.converter.convert(stripped, current_layout, best_layout) == stripped
        ):
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
