"""A word mixing Latin and Cyrillic is never rewritten as a unit (v0.2.8.1).

Reported as part of the "residual deformation" bug: a fast typist who switches
layout mid-word produces a token like ``ghbdtnпривет``. Converting that token as
one unit damages the half that was already correct (``ghйпривет``). The right
fix is to leave the token alone and let the separator between the two scripts
flush each half on its own boundary.
"""

from __future__ import annotations

import time

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import Config  # noqa: E402
from linguafix.converter import LayoutConverter  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector, _has_mixed_script_word  # noqa: E402

MIXED_WORDS = [
    "ghbdtnпривет",
    "приветhello",
    "helloПривет",
    "Руддщhello",
]
SEPARATE_SCRIPTS = [
    "ghbdtn привет",
    "привет hello",
    "hello Привет",
]


def _detector() -> LanguageDetector:
    return LanguageDetector(converter=LayoutConverter(), stop_words=[], min_word_length=3)


@pytest.mark.parametrize("text", MIXED_WORDS)
def test_single_mixed_token_is_detected(text: str) -> None:
    assert _has_mixed_script_word(text) is True


@pytest.mark.parametrize("text", SEPARATE_SCRIPTS)
def test_separate_scripts_are_not_mixed(text: str) -> None:
    assert _has_mixed_script_word(text) is False


@pytest.mark.parametrize("text", MIXED_WORDS)
def test_target_layout_refuses_a_mixed_token(text: str) -> None:
    assert _detector().target_layout(text, "us") is None
    assert _detector().target_layout(text, "ru") is None


@pytest.mark.parametrize("text", MIXED_WORDS)
def test_detect_refuses_a_mixed_token(text: str) -> None:
    assert _detector().detect(text) is None


@pytest.mark.parametrize("text", MIXED_WORDS)
def test_should_fix_is_false_for_a_mixed_token(text: str) -> None:
    assert _detector().should_fix(text, "us") is False
    assert _detector().should_fix(text, "ru") is False


@pytest.mark.parametrize("text", SEPARATE_SCRIPTS)
def test_should_fix_is_true_for_separate_scripts(text: str) -> None:
    # The whole buffer is wrong when each script sits in its own word.
    assert _detector().should_fix(text, "us") is True or _detector().should_fix(text, "ru") is True


class _FakeSwitcher:
    def __init__(self, current: str = "ru") -> None:
        self.current = current
        self.switches: list[str] = []

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        self.switches.append(layout)
        return True

    def describe(self) -> str:
        return "backend=fake"


class _FakeInjector:
    def __init__(self) -> None:
        self.replacements: list[tuple[int, str, str]] = []

    def can_type(self, char: str, layout: str) -> bool:
        return char == " "

    def replace_text(
        self, backspace_count: int, new: str, layout: str, boundary_char: str = ""
    ) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True

    def describe(self) -> str:
        return "backend=fake"


def _daemon() -> LinguaFixDaemon:
    config = Config(stop_words=[], analysis_timeout=0.8)
    detector = LanguageDetector(
        converter=LayoutConverter(),
        stop_words=[],
        min_word_length=config.min_word_length,
        confidence_threshold=config.confidence_threshold,
    )
    return LinguaFixDaemon(
        config, detector=detector, switcher=_FakeSwitcher("ru"), injector=_FakeInjector()
    )


def test_daemon_leaves_a_mixed_token_alone() -> None:
    daemon = _daemon()
    daemon.buffer = "ghbdtnпривет"
    daemon.last_key_time = time.time()
    daemon._process_buffer()
    injector = daemon.injector
    assert isinstance(injector, _FakeInjector)
    assert injector.replacements == []
