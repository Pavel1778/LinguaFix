"""Stage 1.1: a Ctrl/Alt chord abandons the word being typed.

Typing ``ghbdtn`` then pressing Ctrl+C must not leave the word in the buffer to
be corrected by the next Space. The word is *suspended* while Ctrl/Alt is held so
that a Ctrl-based fix hotkey (``CTRL+F12``) or the ``CTRL+CTRL`` double tap can
still reach it; any ordinary key that is not a hotkey drops it for good.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import Config  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector  # noqa: E402

EV_KEY = evdev.ecodes.EV_KEY

_KEYS = {"g": "KEY_G", "h": "KEY_H", "b": "KEY_B", "d": "KEY_D", "t": "KEY_T", "n": "KEY_N"}


@dataclass
class FakeEvent:
    type: int
    code: int
    value: int


@dataclass
class FakeSwitcher:
    current: str = "us"
    backend: str = "fake"

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        return True


@dataclass
class FakeInjector:
    replacements: list[tuple[int, str, str]] = field(default_factory=list)
    backend: str = "fake"

    def can_type(self, char: str, layout: str) -> bool:
        # Mirror the uinput backend: only Space is layout-invariant and typed.
        return char == " "

    def replace_text(
        self, backspace_count: int, new: str, layout: str, boundary_char: str = ""
    ) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True


def make_event(name: str, value: int = 1) -> FakeEvent:
    return FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), value)


def press(daemon: LinguaFixDaemon, text: str) -> None:
    for char in text:
        name = _KEYS[char]
        daemon._handle_event(make_event(name, 1))
        daemon._handle_event(make_event(name, 0))


def make_daemon(**kwargs: object) -> LinguaFixDaemon:
    options: dict[str, object] = {"analysis_timeout": 0.8, "stop_words": []}
    options.update(kwargs)
    config = Config(**options)
    detector = LanguageDetector(
        converter=None, stop_words=config.stop_words, min_word_length=config.min_word_length
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


@pytest.mark.parametrize(
    "modifier", ["KEY_LEFTCTRL", "KEY_RIGHTCTRL", "KEY_LEFTALT", "KEY_RIGHTALT"]
)
def test_ctrl_or_alt_clears_the_buffer(modifier: str) -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    assert daemon.buffer == "ghbdtn"
    daemon._handle_event(make_event(modifier, 1))
    assert daemon.buffer == ""
    # A following Space must not analyse the abandoned word.
    daemon._handle_event(make_event("KEY_SPACE", 1))
    assert _injector(daemon).replacements == []


def test_ctrl_chord_does_not_fix_the_previous_word() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    # Ctrl+C — a copy chord, not a hotkey.
    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    daemon._handle_event(make_event("KEY_C", 1))
    daemon._handle_event(make_event("KEY_C", 0))
    daemon._handle_event(make_event("KEY_LEFTCTRL", 0))
    daemon._handle_event(make_event("KEY_SPACE", 1))
    assert _injector(daemon).replacements == []


def test_ctrl_based_fix_hotkey_still_sees_the_word() -> None:
    daemon = make_daemon(hotkey_fix_last_word="CTRL+F12")
    press(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    daemon._handle_event(make_event("KEY_F12", 1))
    assert _injector(daemon).replacements == [(6, "привет", "ru")]


def test_double_ctrl_still_sees_the_word() -> None:
    daemon = make_daemon(hotkey_fix_last_word="CTRL+CTRL")
    press(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    daemon._handle_event(make_event("KEY_LEFTCTRL", 0))
    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    daemon._handle_event(make_event("KEY_LEFTCTRL", 0))
    assert _injector(daemon).replacements == [(6, "привет", "ru")]


def test_shift_does_not_clear_the_buffer() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_LEFTSHIFT", 1))
    daemon._handle_event(make_event("KEY_LEFTSHIFT", 0))
    assert daemon.buffer == "ghbdtn"
