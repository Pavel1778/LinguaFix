"""Tests for :mod:`linguafix.detector`."""

from __future__ import annotations

import pytest

from linguafix.converter import LayoutConverter
from linguafix.detector import LanguageDetector

# --- detect() ---------------------------------------------------------------

RU_SAMPLES = [
    "привет",
    "мир",
    "как дела",
    "спасибо большое",
    "программа работает",
    "текст на русском языке",
    "привет мир как дела",
]

EN_SAMPLES = [
    "hello",
    "world",
    "the quick brown fox",
    "hello world",
    "program works",
    "this is english text",
    "keyboard layout",
]

# Latin text typed while a Russian layout is active: still Latin letters.
WRONG_LAYOUT_LATIN = ["ghbdtn", "Ghbdtn", "hello", "vbh", "rfr"]

UNKNOWN_SAMPLES = ["", "   ", "kt", "z", "42", "!!!", "a"]


@pytest.mark.parametrize("text", RU_SAMPLES)
def test_detect_russian(detector: LanguageDetector, text: str) -> None:
    assert detector.detect(text) == "ru"


@pytest.mark.parametrize("text", EN_SAMPLES)
def test_detect_english(detector: LanguageDetector, text: str) -> None:
    assert detector.detect(text) == "en"


@pytest.mark.parametrize("text", WRONG_LAYOUT_LATIN)
def test_detect_latin_script_is_english(detector: LanguageDetector, text: str) -> None:
    assert detector.detect(text) == "en"


@pytest.mark.parametrize("text", UNKNOWN_SAMPLES)
def test_detect_returns_none_for_ambiguous(detector: LanguageDetector, text: str) -> None:
    assert detector.detect(text) is None


def test_detect_mixed_prefers_dominant(detector: LanguageDetector) -> None:
    assert detector.detect("приветhello") == "ru"


def test_detect_short_words_ignored(detector: LanguageDetector) -> None:
    detector.min_word_length = 5
    assert detector.detect("мир") is None
    assert detector.detect("cat") is None


# --- target_layout() --------------------------------------------------------


@pytest.mark.parametrize(
    ("buffer", "current", "expected"),
    [
        ("ghbdtn", "us", "ru"),
        ("ghbdtn", "ru", "us"),
        ("привет", "us", "ru"),
        ("Руддщ", "ru", "us"),
        ("hello", "ru", "us"),
        ("привет мир", "us", "ru"),
        ("hello world", "ru", "us"),
        ("ghbdtn vbh", "us", "ru"),
        ("Руддщ цщкл", "ru", "us"),
    ],
)
def test_target_layout_converts(
    detector: LanguageDetector, buffer: str, current: str, expected: str
) -> None:
    assert detector.target_layout(buffer, current) == expected


@pytest.mark.parametrize(
    ("buffer", "current"),
    [
        ("привет", "ru"),
        ("hello", "us"),
        ("the quick brown fox", "us"),
        ("password", "us"),
        ("hello world", "us"),
    ],
)
def test_target_layout_no_change_needed(
    detector: LanguageDetector, buffer: str, current: str
) -> None:
    assert detector.target_layout(buffer, current) is None


def test_target_layout_respects_stop_words(detector: LanguageDetector) -> None:
    assert detector.target_layout("ghbdtn", "us") == "ru"
    detector.set_stop_words(["ghbdtn"])
    assert detector.target_layout("ghbdtn", "us") is None


def test_target_layout_empty_buffer(detector: LanguageDetector) -> None:
    assert detector.target_layout("", "us") is None
    assert detector.target_layout("   ", "us") is None


# --- should_fix() -----------------------------------------------------------


def test_should_fix_true_for_wrong_layout(detector: LanguageDetector) -> None:
    assert detector.should_fix("ghbdtn", "us") is True
    assert detector.should_fix("Руддщ", "ru") is True


def test_should_fix_false_for_correct_layout(detector: LanguageDetector) -> None:
    assert detector.should_fix("привет", "ru") is False
    assert detector.should_fix("hello", "us") is False


def test_should_fix_true_for_mixed_alphabets(detector: LanguageDetector) -> None:
    assert detector.should_fix("приветhello", "ru") is True
    assert detector.should_fix("helloПривет", "us") is True


def test_should_fix_false_for_stop_word(detector: LanguageDetector) -> None:
    assert detector.should_fix("password", "ru") is False
    assert detector.should_fix("my token", "ru") is False


def test_should_fix_without_layout_uses_detection(detector: LanguageDetector) -> None:
    assert detector.should_fix("привет") is True
    assert detector.should_fix("") is False


# --- stop words -------------------------------------------------------------


def test_is_stop_word_positive(detector: LanguageDetector) -> None:
    assert detector.is_stop_word("password") is True
    assert detector.is_stop_word("my password is secret") is True
    assert detector.is_stop_word("LOGIN") is True
    assert detector.is_stop_word("sudo") is True


def test_is_stop_word_negative(detector: LanguageDetector) -> None:
    assert detector.is_stop_word("hello") is False
    assert detector.is_stop_word("привет") is False
    assert detector.is_stop_word("") is False


def test_stop_words_property(detector: LanguageDetector) -> None:
    assert "password" in detector.stop_words
    detector.set_stop_words(["foo"])
    assert detector.stop_words == {"foo"}


# --- misc -------------------------------------------------------------------


def test_convert_buffer_delegates(detector: LanguageDetector) -> None:
    assert detector.convert_buffer("ghbdtn", "us", "ru") == "привет"


def test_custom_min_word_length(converter: LayoutConverter) -> None:
    detector = LanguageDetector(converter=converter, stop_words=[], min_word_length=7)
    assert detector.detect("привет") is None
    assert detector.detect("привет мир") is None
    assert detector.detect("приветствую мир") == "ru"
