"""Additional languages: uk, de and fr layouts and corpora."""

from __future__ import annotations

import pytest

from linguafix.converter import LayoutConverter
from linguafix.detector import LanguageDetector


def test_converter_knows_new_layouts() -> None:
    converter = LayoutConverter()
    for layout in ("uk", "fr"):
        assert layout in converter.available_layouts
    assert converter.alphabet("uk") == "cyrillic"
    assert converter.alphabet("fr") == "latin"


def test_ukrainian_conversion() -> None:
    converter = LayoutConverter()
    # Ukrainian "і" is on the US "s" key, unlike Russian "ы".
    assert converter.convert("s", "us", "uk") == "і"
    # Ukrainian "ї"/"є"/"ґ" replace Russian "ъ"/"э"/"\\".
    assert converter.convert("]", "us", "uk") == "ї"
    assert converter.convert("'", "us", "uk") == "є"


def test_french_conversion() -> None:
    converter = LayoutConverter()
    # AZERTY swaps A/Q, Z/W and M/; relative to QWERTY.
    assert converter.convert("a", "us", "fr") == "q"
    assert converter.convert("q", "us", "fr") == "a"
    assert converter.convert(";", "us", "fr") == "m"


def test_detector_loads_selected_languages() -> None:
    detector = LanguageDetector(LayoutConverter(), languages=("en", "ru", "uk", "fr"))
    assert set(detector._vocabularies) == {"en", "ru", "uk", "fr"}


def test_detector_ignores_missing_corpus() -> None:
    # ``xx`` has no bundled corpus, so it must not become a conversion target.
    detector = LanguageDetector(LayoutConverter(), languages=("en", "xx"))
    assert "xx" not in detector._vocabularies
    assert "en" in detector._vocabularies


def test_ukrainian_word_detected_when_enabled() -> None:
    detector = LanguageDetector(LayoutConverter(), languages=("en", "ru", "uk"))
    assert detector.detect("привіт") == "uk"
    assert detector.detect("дякую") == "uk"


def test_default_detector_stays_two_languages() -> None:
    detector = LanguageDetector(LayoutConverter())
    assert set(detector._vocabularies) == {"en", "ru"}


@pytest.mark.parametrize("word", ["ghbdtn", "vbh", "rfr"])
def test_default_detection_unchanged_by_new_corpora(word: str) -> None:
    # Adding corpora for other languages must not change the en/ru default.
    detector = LanguageDetector(LayoutConverter())
    assert detector.detect(word) == "en"
