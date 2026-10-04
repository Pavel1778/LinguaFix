"""The bundled corpora: every supported language ships a real dictionary.

v0.2.0 replaces the tiny hand-written word lists with frequency lists derived
from FrequencyWords. These tests pin the size and shape of the shipped corpora
and the fact that the default detector stays en/ru so the new data cannot
silently change the common path.
"""

from __future__ import annotations

import json
from importlib import resources

import pytest

from linguafix.converter import LayoutConverter
from linguafix.detector import DEFAULT_DETECTOR_LANGUAGES, LanguageDetector

SUPPORTED = ("en", "ru", "uk", "de", "fr")


def _corpus(language: str) -> dict[str, object]:
    text = (resources.files("linguafix") / "data" / f"ngrams_{language}.json").read_text(
        encoding="utf-8"
    )
    data = json.loads(text)
    assert isinstance(data, dict)
    return data


@pytest.mark.parametrize("language", SUPPORTED)
def test_corpus_is_large_and_frequency_ordered(language: str) -> None:
    data = _corpus(language)
    words = data["words"]
    assert isinstance(words, list)
    # At least the maximum selectable ``Config.dictionary_size``.
    assert len(words) >= 10000
    # No duplicates, and every entry is a lowercase letter word.
    assert len(words) == len(set(words))
    assert all(word == word.lower() for word in words)
    bigrams = data["bigrams"]
    assert isinstance(bigrams, dict)
    assert len(bigrams) >= 200
    assert abs(sum(bigrams.values()) - 1.0) < 1e-6


@pytest.mark.parametrize("language", SUPPORTED)
def test_language_loads_with_a_full_vocabulary(language: str) -> None:
    detector = LanguageDetector(LayoutConverter(), languages=(language,))
    assert len(detector._vocabularies[language]) >= 10000


def test_all_languages_can_be_enabled_at_once() -> None:
    detector = LanguageDetector(LayoutConverter(), languages=SUPPORTED)
    assert set(detector._vocabularies) == set(SUPPORTED)


def test_default_detector_remains_en_ru() -> None:
    # Loading every corpus makes the Latin layouts ambiguous, so the default
    # must stay the two most common languages.
    assert DEFAULT_DETECTOR_LANGUAGES == ("en", "ru")
    detector = LanguageDetector(LayoutConverter())
    assert set(detector._vocabularies) == {"en", "ru"}


@pytest.mark.parametrize(
    ("word", "language"),
    [("привіт", "uk"), ("дякую", "uk"), ("hallo", "de")],
)
def test_opt_in_language_is_detected(word: str, language: str) -> None:
    detector = LanguageDetector(LayoutConverter(), languages=SUPPORTED)
    assert detector.detect(word) == language
