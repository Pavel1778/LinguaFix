"""The user dictionary validates converted words (brands, names, jargon).

A brand such as ``vercel`` is absent from the bundled frequency corpora, so the
detector cannot score it. When the user teaches it, the *converted* form
(``муксуд`` -> ``vercel``) becomes a known-good result and the correction fires.
"""

from __future__ import annotations

from pathlib import Path

from linguafix import dictionary
from linguafix.converter import LayoutConverter
from linguafix.detector import LanguageDetector


def make_detector(user_words: list[str] | None = None) -> LanguageDetector:
    return LanguageDetector(LayoutConverter(), user_words=user_words)


def test_brand_is_rewritten_when_taught() -> None:
    detector = make_detector(["vercel"])
    assert detector.target_layout("муксуд", "ru") == "us"
    assert detector.should_fix("муксуд", "ru") is True


def test_brand_is_not_rewritten_when_unknown() -> None:
    detector = make_detector([])
    assert detector.target_layout("муксуд", "ru") is None
    assert detector.should_fix("муксуд", "ru") is False


def test_taught_typed_word_is_never_rewritten() -> None:
    # The typed form being in the dictionary is an absolute override: the word
    # is left exactly as typed.
    detector = make_detector(["ghbdtn"])
    assert detector.target_layout("ghbdtn", "us") is None
    assert detector.should_fix("ghbdtn", "us") is False


def test_taught_word_only_matches_its_own_conversion() -> None:
    # Teaching a *different* brand must not turn "муксуд" into a correction.
    detector = make_detector(["невектор"])
    assert detector.target_layout("муксуд", "ru") is None


def test_user_word_property_is_sorted_and_lowercased() -> None:
    detector = make_detector(["Vercel", "кот"])
    assert detector.user_words == ["vercel", "кот"]


def test_detector_picks_up_words_from_the_dictionary_file(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    dictionary.add_user_word("vercel", str(path))
    detector = make_detector(dictionary.load_user_dictionary(str(path)))
    assert detector.target_layout("муксуд", "ru") == "us"
