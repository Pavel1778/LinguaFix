"""Punctuation cleanup: the rule engine and its daemon integration.

Punctuation is opt-in and rule-based, so these tests pin each rule, the layout
gate on smart quotes, and the fact that a replacement the text backend cannot
type (an em dash under ``uinput``) is refused rather than half-applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import Config  # noqa: E402
from linguafix.converter import LayoutConverter  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector  # noqa: E402
from linguafix.punctuation import PunctuationCorrector  # noqa: E402


def test_empty_string_is_returned_unchanged() -> None:
    assert PunctuationCorrector().correct("") == ""


def test_dashes_replaced() -> None:
    c = PunctuationCorrector()
    assert c.correct("текст--") == "текст\u2014"
    assert c.correct("a---b") == "a\u2014b"


def test_ellipsis_replaced() -> None:
    c = PunctuationCorrector()
    assert c.correct("текст...") == "текст\u2026"
    assert c.correct("и....") == "и\u2026"


def test_spacing_cleanup() -> None:
    c = PunctuationCorrector()
    assert c.correct("текст ,") == "текст,"
    assert c.correct("текст,далее") == "текст, далее"
    assert c.correct("текст  слово") == "текст слово"
    assert c.correct("что ?") == "что?"


def test_smart_quotes_only_for_cyrillic() -> None:
    c = PunctuationCorrector(smart_quotes=True)
    assert c.correct('"цитата"', "ru") == "\u00abцитата\u00bb"
    assert c.correct('"цитата"', "uk") == "\u00abцитата\u00bb"
    # A Latin layout keeps straight quotes.
    assert c.correct('"quote"', "us") == '"quote"'
    assert c.correct('"quote"', "en") == '"quote"'


def test_disabled_flags_leave_text_alone() -> None:
    c = PunctuationCorrector(dashes=False, ellipsis=False, fix_spacing=False)
    assert c.correct("текст--") == "текст--"
    assert c.correct("текст...") == "текст..."
    assert c.correct("текст ,") == "текст ,"


def test_nothing_to_do_returns_same_text() -> None:
    c = PunctuationCorrector()
    assert c.correct("привет") == "привет"
    assert c.correct("hello world") == "hello world"


# --- daemon integration --------------------------------------------------


@dataclass
class FakeSwitcher:
    current: str = "ru"

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        return True

    def describe(self) -> str:
        return "backend=fake"


@dataclass
class FakeInjector:
    # Characters the backend cannot produce (a real uinput backend has no key
    # for an em dash or an ellipsis; letters are always typable).
    untypable: str = ""
    replacements: list[tuple[int, str, str]] = field(default_factory=list)

    def can_type(self, char: str, layout: str) -> bool:
        return char not in self.untypable

    def replace_text(self, backspace_count: int, new: str, layout: str, **_kw: object) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True

    def describe(self) -> str:
        return "backend=fake"


def _make_daemon(untypable: str = "", **kwargs: object) -> LinguaFixDaemon:
    options: dict[str, object] = {"stop_words": [], "min_word_length": 1}
    options.update(kwargs)
    config = Config(**options)
    detector = LanguageDetector(
        converter=LayoutConverter(),
        stop_words=config.stop_words,
        min_word_length=config.min_word_length,
        confidence_threshold=config.confidence_threshold,
    )
    return LinguaFixDaemon(
        config,
        detector=detector,
        switcher=FakeSwitcher("ru"),
        injector=FakeInjector(untypable=untypable),
    )


def test_punctuation_correction_disabled_returns_none() -> None:
    daemon = _make_daemon(punctuation_correction=False)
    assert daemon._punctuation_correction("текст--", "ru") is None


def test_punctuation_correction_applies_when_enabled() -> None:
    daemon = _make_daemon(punctuation_correction=True)
    assert daemon._punctuation_correction("текст--", "ru") == "текст\u2014"
    assert daemon._punctuation_correction("текст...", "ru") == "текст\u2026"
    assert daemon._punctuation_correction("текст ,", "ru") == "текст,"


def test_punctuation_correction_no_change_returns_none() -> None:
    daemon = _make_daemon(punctuation_correction=True)
    assert daemon._punctuation_correction("привет", "ru") is None


def test_punctuation_correction_refuses_untypable_char() -> None:
    # An em dash the backend cannot type must not be substituted half-way.
    daemon = _make_daemon(untypable="\u2014", punctuation_correction=True)
    assert daemon._punctuation_correction("текст--", "ru") is None


def test_build_punctuation_reads_config() -> None:
    daemon = _make_daemon(punctuation_correction=True, punctuation_smart_quotes=True)
    corrector = daemon._build_punctuation()
    assert corrector.smart_quotes is True
    assert corrector.dashes is True
