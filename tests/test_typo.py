"""Tests for the T9 typo corrector (:mod:`linguafix.typo`)."""

from __future__ import annotations

import pytest

from linguafix.typo import (
    DEFAULT_LONG_WORD_THRESHOLD,
    DEFAULT_MAX_DISTANCE,
    DEFAULT_MAX_DISTANCE_LONG,
    DEFAULT_TOP1_RATIO_STRICT,
    TypoCorrector,
    bounded_damerau_levenshtein,
)

VOCAB = ["the", "world", "program", "language", "receive", "hello", "test", "work"]


# --- distance ---------------------------------------------------------------


def test_distance_identity_is_zero() -> None:
    assert bounded_damerau_levenshtein("hello", "hello", 2) == 0


def test_distance_substitution_insertion_deletion() -> None:
    assert bounded_damerau_levenshtein("wrold", "world", 1) == 1  # substitution
    assert bounded_damerau_levenshtein("helo", "hello", 1) == 1  # insertion
    assert bounded_damerau_levenshtein("helloo", "hello", 1) == 1  # deletion


def test_distance_transposition_counts_as_one() -> None:
    assert bounded_damerau_levenshtein("teh", "the", 1) == 1
    assert bounded_damerau_levenshtein("recieve", "receive", 1) == 1


def test_distance_is_capped() -> None:
    # The true distance is far above the cap, so the capped value is returned.
    assert bounded_damerau_levenshtein("cat", "elephant", 1) == 2
    assert bounded_damerau_levenshtein("", "word", 1) == 2


# --- corrector --------------------------------------------------------------


def test_corrects_a_clear_single_typo() -> None:
    corrector = TypoCorrector(VOCAB)
    assert corrector.suggest("wrold") == "world"
    assert corrector.suggest("progarm") == "program"
    assert corrector.suggest("langauge") == "language"


def test_leaves_a_correct_word_alone() -> None:
    corrector = TypoCorrector(VOCAB)
    for word in ("hello", "world", "program"):
        assert corrector.suggest(word) is None


def test_leaves_a_short_word_alone() -> None:
    corrector = TypoCorrector(VOCAB, min_length=4)
    # "teh" is a transposition of "the" but shorter than the minimum.
    assert corrector.suggest("teh") is None


def test_leaves_a_hopeless_word_alone() -> None:
    corrector = TypoCorrector(VOCAB)
    assert corrector.suggest("zzzzz") is None


def test_ambiguous_typo_is_not_corrected() -> None:
    # "wold" is one edit from both "world" and (via a substitution) no other
    # word; add a tie to prove the ambiguity guard.
    corrector = TypoCorrector(["world", "would"])
    assert corrector.suggest("wold") is None


def test_non_letter_word_is_ignored() -> None:
    corrector = TypoCorrector(VOCAB)
    assert corrector.suggest("w0rld") is None
    assert corrector.suggest("wor-ld") is None


def test_default_distance_is_one() -> None:
    assert DEFAULT_MAX_DISTANCE == 1


# --- long words: two edits --------------------------------------------------


def test_long_word_accepts_two_edits() -> None:
    # "lenguege" differs from "language" in two positions (distance 2) and is the
    # only near candidate, so the long-word rule accepts it.
    corrector = TypoCorrector(VOCAB, long_word_max_distance=2)
    assert corrector.suggest("lenguege") == "language"


def test_short_word_rejects_two_edits() -> None:
    # "axxd" is two edits from "abcd" but the word is shorter than the long-word
    # threshold, so only one edit is allowed and nothing is corrected.
    corrector = TypoCorrector(
        ["abcd"], min_length=4, long_word_threshold=6, long_word_max_distance=2
    )
    assert corrector.suggest("axxd") is None


def test_two_edit_tie_is_left_alone() -> None:
    # "abcdzzg" is two edits from both candidates, which sit one rank apart, so
    # the frequency margin is too small to pick a winner.
    corrector = TypoCorrector(
        ["abcdefg", "abcdxfg"], long_word_max_distance=2, top1_ratio_strict=10
    )
    assert corrector.suggest("abcdzzg") is None


def test_two_edit_clear_winner_is_accepted() -> None:
    # Same shape, but the runner-up is hundreds of ranks behind, so the best
    # candidate clears the ratio guard.
    vocab = ["abcdefg", *[f"w{i:05d}" for i in range(500)], "abcdxfg"]
    corrector = TypoCorrector(vocab, long_word_max_distance=2, top1_ratio_strict=10)
    assert corrector.suggest("abcdzzg") == "abcdefg"


def test_long_word_threshold_and_distance_defaults() -> None:
    assert DEFAULT_MAX_DISTANCE_LONG == 2
    assert DEFAULT_LONG_WORD_THRESHOLD == 6
    assert DEFAULT_TOP1_RATIO_STRICT >= 1.0


def test_corpus_two_edit_typo_is_corrected() -> None:
    from linguafix.converter import LayoutConverter
    from linguafix.detector import LanguageDetector

    detector = LanguageDetector(LayoutConverter())
    corrector = TypoCorrector(detector.ordered_vocabulary("ru"), min_length=4)
    # Two edits, long word, clear frequency winner.
    assert corrector.suggest("прветт") == "привет"


def test_corpus_short_two_edit_typo_is_refused() -> None:
    from linguafix.converter import LayoutConverter
    from linguafix.detector import LanguageDetector

    detector = LanguageDetector(LayoutConverter())
    corrector = TypoCorrector(detector.ordered_vocabulary("ru"), min_length=4)
    # "првт" is two edits from many short words; too short for the long rule.
    assert corrector.suggest("првт") is None


def test_corpus_used_by_the_detector_finds_a_real_typo() -> None:
    from linguafix.converter import LayoutConverter
    from linguafix.detector import LanguageDetector

    detector = LanguageDetector(LayoutConverter())
    corrector = TypoCorrector(list(detector.vocabulary("en")))
    assert corrector.suggest("langauge") == "language"
    assert corrector.suggest("progarm") == "program"


@pytest.mark.parametrize("word", ["wrold", "progarm"])
def test_correction_is_case_insensitive(word: str) -> None:
    corrector = TypoCorrector(VOCAB)
    assert corrector.suggest(word.upper()) in {"world", "program"}
