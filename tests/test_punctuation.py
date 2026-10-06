"""T9 punctuation clean-up: the rule engine and its daemon integration.

The punctuation pass is opt-in and never changes a word, so these tests pin both
the deterministic rules and the fact that the pass stays out of the way when
disabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from linguafix.config import Config
from linguafix.punctuation import PunctuationProcessor


@pytest.fixture
def processor() -> PunctuationProcessor:
    return PunctuationProcessor()


def test_double_hyphen_becomes_em_dash(processor: PunctuationProcessor) -> None:
    assert processor.process("текст--", "ru") == "текст—"


def test_single_hyphen_is_left_alone(processor: PunctuationProcessor) -> None:
    assert processor.process("кое-как", "ru") == "кое-как"


def test_three_dots_become_ellipsis(processor: PunctuationProcessor) -> None:
    assert processor.process("текст ...", "ru") == "текст…"


def test_space_before_comma_is_removed(processor: PunctuationProcessor) -> None:
    assert processor.process("текст ,", "ru") == "текст,"


def test_missing_space_after_comma_is_added(processor: PunctuationProcessor) -> None:
    assert processor.process("текст,далее", "ru") == "текст, далее"


def test_double_space_becomes_single(processor: PunctuationProcessor) -> None:
    assert processor.process("текст  слово", "ru") == "текст слово"


def test_space_after_comma_before_digit_is_left_alone() -> None:
    # "1, 2" must not become "1,2": the rule only inserts a space, never removes.
    assert PunctuationProcessor().process("1, 2", "ru") == "1, 2"


def test_smart_quotes_only_in_cyrillic_layout() -> None:
    smart = PunctuationProcessor(smart_quotes=True)
    assert smart.process('"цитата"', "ru") == "«цитата»"
    assert smart.process('"quote"', "en") == '"quote"'


def test_auto_capitalize_is_opt_in() -> None:
    assert PunctuationProcessor().process("привет", "ru") == "привет"
    assert PunctuationProcessor(auto_capitalize=True).process("привет", "ru") == "Привет"


def test_auto_period_is_opt_in_and_skips_existing_marks() -> None:
    auto = PunctuationProcessor(auto_period=True)
    assert auto.process("привет", "ru") == "привет."
    assert auto.process("привет!", "ru") == "привет!"
    assert PunctuationProcessor().process("привет", "ru") == "привет"


def test_empty_fragment_is_returned_unchanged(processor: PunctuationProcessor) -> None:
    assert processor.process("", "ru") == ""


def test_all_rules_off_returns_text_unchanged() -> None:
    off = PunctuationProcessor(
        replace_dashes=False,
        replace_ellipsis=False,
        smart_quotes=False,
        fix_spacing=False,
        auto_capitalize=False,
        auto_period=False,
    )
    assert off.process("текст-- ...", "ru") == "текст-- ..."


# ---------------------------------------------------------------------------
# Daemon integration
# ---------------------------------------------------------------------------

evdev = pytest.importorskip("evdev")

from linguafix.converter import LayoutConverter  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector  # noqa: E402

EV_KEY = evdev.ecodes.EV_KEY


@dataclass
class FakeEvent:
    type: int
    code: int
    value: int


@dataclass
class FakeSwitcher:
    current: str = "us"

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        return True

    def describe(self) -> str:
        return "backend=fake"


@dataclass
class FakeInjector:
    replacements: list[tuple[int, str, str]] = field(default_factory=list)

    def can_type(self, char: str, layout: str) -> bool:
        return char in " .,!?-—…"

    def replace_text(
        self, backspace_count: int, new: str, layout: str, boundary_char: str = ""
    ) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True

    def describe(self) -> str:
        return "backend=fake"


# US scancodes for the characters the tests type. Only the keys used are mapped.
_KEY_BY_CHAR = {
    " ": "KEY_SPACE",
    ".": "KEY_DOT",
    ",": "KEY_COMMA",
    "-": "KEY_MINUS",
    "a": "KEY_A",
    "b": "KEY_B",
    "c": "KEY_C",
    "d": "KEY_D",
    "e": "KEY_E",
    "f": "KEY_F",
    "g": "KEY_G",
    "h": "KEY_H",
    "i": "KEY_I",
    "j": "KEY_J",
    "k": "KEY_K",
    "l": "KEY_L",
    "m": "KEY_M",
    "n": "KEY_N",
    "o": "KEY_O",
    "p": "KEY_P",
    "q": "KEY_Q",
    "r": "KEY_R",
    "s": "KEY_S",
    "t": "KEY_T",
    "u": "KEY_U",
    "v": "KEY_V",
    "w": "KEY_W",
    "x": "KEY_X",
    "y": "KEY_Y",
    "z": "KEY_Z",
}


def _press(daemon: LinguaFixDaemon, text: str) -> None:
    for char in text:
        name = _KEY_BY_CHAR[char]
        daemon._handle_event(FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), 1))
        daemon._handle_event(FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), 0))


def _make_daemon(**kwargs: object) -> LinguaFixDaemon:
    options: dict[str, object] = {
        "stop_words": [],
        "analysis_timeout": 0.8,
        "on_punctuation": True,
        "punctuation_chars": ".,-",
    }
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
        switcher=FakeSwitcher("us"),
        injector=FakeInjector(),
    )


def _injector(daemon: LinguaFixDaemon) -> FakeInjector:
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    return injector


def _idle(daemon: LinguaFixDaemon) -> None:
    """Force the idle flush without sleeping."""
    daemon.last_key_time = 0.0
    daemon._punctuation_time = 1.0  # truthy, but far in the past
    daemon._flush_if_idle()


def test_punctuation_disabled_leaves_run_alone() -> None:
    daemon = _make_daemon(punctuation_enabled=False)
    _press(daemon, "test...")
    _idle(daemon)
    assert _injector(daemon).replacements == []


def test_ellipsis_run_is_cleaned_on_idle() -> None:
    daemon = _make_daemon(punctuation_enabled=True)
    _press(daemon, "test...")
    _idle(daemon)
    # Three dots typed -> one ellipsis: three backspaces, then the single char.
    assert _injector(daemon).replacements == [(3, "…", "us")]


def test_run_is_cleaned_when_the_next_word_starts() -> None:
    daemon = _make_daemon(punctuation_enabled=True)
    _press(daemon, "test--")
    _press(daemon, "d")
    # The run is rewritten as soon as the next real character arrives.
    assert _injector(daemon).replacements == [(2, "—", "us")]


def test_run_before_a_space_is_dropped_not_rewritten() -> None:
    daemon = _make_daemon(punctuation_enabled=True)
    _press(daemon, "test--")
    _press(daemon, " ")
    # A space after the run means the run is a deliberate pause, not a dash.
    assert _injector(daemon).replacements == []


def test_single_dot_is_left_alone() -> None:
    daemon = _make_daemon(punctuation_enabled=True)
    _press(daemon, "test.")
    _idle(daemon)
    assert _injector(daemon).replacements == []


def test_punctuation_does_not_touch_the_word() -> None:
    # A wrong-layout word still goes through the layout path; the punctuation
    # pass must never rewrite the word itself.
    daemon = _make_daemon(punctuation_enabled=True)
    _press(daemon, "ghbdtn")
    _press(daemon, ".")
    # "ghbdtn." is a layout fix (the dot is punctuation and not part of the
    # word); the punctuation run is a single dot and is left alone.
    assert _injector(daemon).replacements == [(6, "привет", "ru")]
