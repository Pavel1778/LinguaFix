"""T9 typo correction through the daemon (Stage 3).

T9 is opt-in and runs only when layout detection found nothing, so these tests
pin both the correction itself and the fact that it stays out of the way when
disabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import Config  # noqa: E402
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
    switches: list[str] = field(default_factory=list)

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        self.switches.append(layout)
        return True

    def describe(self) -> str:
        return "backend=fake"


@dataclass
class FakeInjector:
    replacements: list[tuple[int, str, str]] = field(default_factory=list)

    def replace_text(self, backspace_count: int, new: str, layout: str) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True

    def describe(self) -> str:
        return "backend=fake"


_KEY_BY_CHAR = {" ": ("KEY_SPACE", False)}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    _KEY_BY_CHAR[_letter] = (f"KEY_{_letter.upper()}", False)


def _press(daemon: LinguaFixDaemon, text: str) -> None:
    for char in text:
        name, _shift = _KEY_BY_CHAR[char]
        daemon._handle_event(FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), 1))
        daemon._handle_event(FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), 0))


def _make_daemon(**kwargs: object) -> LinguaFixDaemon:
    options: dict[str, object] = {"stop_words": [], "analysis_timeout": 0.8}
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


def test_typo_is_corrected_when_enabled() -> None:
    daemon = _make_daemon(typo_correction=True)
    _press(daemon, "langauge")
    _press(daemon, " ")
    injector = _injector(daemon)
    assert injector.replacements == [(8, "language", "us")]


def test_typo_is_left_alone_when_disabled() -> None:
    daemon = _make_daemon(typo_correction=False)
    _press(daemon, "langauge")
    _press(daemon, " ")
    assert _injector(daemon).replacements == []


def test_correct_word_is_not_touched() -> None:
    daemon = _make_daemon(typo_correction=True)
    _press(daemon, "language")
    _press(daemon, " ")
    assert _injector(daemon).replacements == []


def test_layout_fix_takes_precedence_over_t9() -> None:
    # "ghbdtn" is a wrong-layout word, not a typo: the layout path must win and
    # the T9 path must never see it.
    daemon = _make_daemon(typo_correction=True)
    _press(daemon, "ghbdtn")
    _press(daemon, " ")
    injector = _injector(daemon)
    assert injector.replacements == [(6, "привет", "ru")]


def test_user_word_is_not_typo_corrected() -> None:
    daemon = _make_daemon(typo_correction=True, dictionary_custom_path="")
    daemon.detector.set_user_words(["langauge"])
    _press(daemon, "langauge")
    _press(daemon, " ")
    assert _injector(daemon).replacements == []


def test_corrector_is_cached_per_language() -> None:
    daemon = _make_daemon(typo_correction=True)
    _press(daemon, "langauge")
    _press(daemon, " ")
    first = daemon._typo_correctors["en"]
    _press(daemon, "progarm")
    _press(daemon, " ")
    assert daemon._typo_correctors["en"] is first
