"""Regression: no text deformation under fast, uninterrupted typing.

The user reported deformed output such as ``ahow re you`` (for ``how are you``)
or ``gрпривет ивет привет`` (for repeated ``ghbdtn``). The corruption is a race
between the asynchronous Backspace batch and the next keystroke: if a spurious
double-Shift fix fires mid-word, the deletion count is no longer the count of
characters the user actually typed.

These tests drive the real daemon against a small *screen model* — a fake
injector that applies the Backspace count to a text buffer and appends the
replacement, and a fake evdev stream that appends the on-screen character for
every key press according to the current layout. The screen model is what makes
the assertion meaningful: it verifies the *rendered text*, not the individual
replacement calls.
"""

from __future__ import annotations

import time

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import Config  # noqa: E402
from linguafix.converter import LayoutConverter  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector  # noqa: E402

EV_KEY = evdev.ecodes.EV_KEY


class ScreenSwitcher:
    """A switcher whose ``switch_to`` can make the user type during the fix."""

    backend = "fake"

    def __init__(self, current: str = "us") -> None:
        self.current = current
        self.switches: list[str] = []
        self.on_switch: object = None

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        self.switches.append(layout)
        callback = self.on_switch
        if callable(callback):
            callback()
        return True

    def describe(self) -> str:
        return "backend=fake"


class Screen:
    """A minimal model of the text on screen.

    ``key`` appends the character a physical key produces in the *current*
    layout; the injector edits the same string. The two together let a test
    assert the rendered text after a burst of input.
    """

    def __init__(self, converter: LayoutConverter, switcher: ScreenSwitcher) -> None:
        self.converter = converter
        self.switcher = switcher
        self.text = ""

    def key(self, name: str) -> None:
        char = _KEY_TO_CHAR[name]
        self.text += self.converter.convert(char, "us", self.switcher.current)


class ScreenInjector:
    """Applies replacements to a :class:`Screen` instead of the kernel."""

    backend = "fake"

    def __init__(self, screen: Screen) -> None:
        self.screen = screen
        self.replacements: list[tuple[int, str, str]] = []

    def can_type(self, char: str, layout: str) -> bool:
        # Mirror the uinput backend: only Space is layout-invariant and typed.
        return char == " "

    def replace_text(
        self, backspace_count: int, new: str, layout: str, boundary_char: str = ""
    ) -> bool:
        text = self.screen.text
        self.screen.text = text[:-backspace_count] if backspace_count else text
        self.screen.text += new
        self.replacements.append((backspace_count, new, layout))
        return True

    def describe(self) -> str:
        return "backend=fake"


_KEY_TO_CHAR = {
    "KEY_A": "a",
    "KEY_B": "b",
    "KEY_C": "c",
    "KEY_D": "d",
    "KEY_E": "e",
    "KEY_F": "f",
    "KEY_G": "g",
    "KEY_H": "h",
    "KEY_I": "i",
    "KEY_J": "j",
    "KEY_K": "k",
    "KEY_L": "l",
    "KEY_M": "m",
    "KEY_N": "n",
    "KEY_O": "o",
    "KEY_P": "p",
    "KEY_Q": "q",
    "KEY_R": "r",
    "KEY_S": "s",
    "KEY_T": "t",
    "KEY_U": "u",
    "KEY_V": "v",
    "KEY_W": "w",
    "KEY_X": "x",
    "KEY_Y": "y",
    "KEY_Z": "z",
    "KEY_SPACE": " ",
}


def make_event(name: str, value: int = 1) -> object:
    return type(
        "E", (), {"type": EV_KEY, "code": int(getattr(evdev.ecodes, name)), "value": value}
    )()


class Harness:
    def __init__(self, **config_kwargs: object) -> None:
        self.converter = LayoutConverter()
        options: dict[str, object] = {
            "stop_words": [],
            "trigger_settle_ms": 0,
            "backspace_settle_ms": 0,
        }
        options.update(config_kwargs)
        self.config = Config(**options)
        self.detector = LanguageDetector(
            converter=self.converter,
            stop_words=[],
            min_word_length=self.config.min_word_length,
        )
        self.switcher = ScreenSwitcher("us")
        self.screen = Screen(self.converter, self.switcher)
        self.injector = ScreenInjector(self.screen)
        self.daemon = LinguaFixDaemon(
            self.config,
            detector=self.detector,
            switcher=self.switcher,
            injector=self.injector,
        )

    def type(self, text: str, interval: float = 0.0) -> None:
        """Type ``text`` on a US layout, one physical key per character."""
        for char in text:
            name = _CHAR_TO_KEY[char]
            self.screen.key(name)
            self.daemon._handle_event(make_event(name, 1))
            self.daemon._handle_event(make_event(name, 0))
            if interval:
                time.sleep(interval)


_CHAR_TO_KEY = {char: name for name, char in _KEY_TO_CHAR.items() if len(char) == 1}


def test_repeated_word_is_not_deformed() -> None:
    """``ghbdtn`` three times must render ``привет привет привет`` exactly."""
    h = Harness()
    for _ in range(3):
        h.type("ghbdtn ")
    assert h.screen.text == "привет привет привет "


def test_ten_words_under_fast_typing_stay_intact() -> None:
    """Ten words typed with a 30 ms gap must not lose or add a character."""
    h = Harness()
    for _ in range(10):
        h.type("ghbdtn", interval=0.03)
        h.type(" ", interval=0.03)
    assert h.screen.text == "привет " * 10


def test_typing_during_a_fix_is_replayed_not_lost() -> None:
    """Keys pressed while a replacement runs are replayed, not dropped.

    Two letters are typed from inside ``switch_to`` (i.e. mid-fix). They must
    survive on screen, in order, after the corrected word.
    """
    h = Harness()
    typed: list[str] = []

    def during_fix() -> None:
        if typed:
            return
        typed.append("yes")
        h.type("gh")

    h.switcher.on_switch = during_fix
    h.type("ghbdtn ")
    assert typed == ["yes"]
    # The corrected word, then the two deferred letters.
    assert h.screen.text == "ghпривет "
    # The deferred letters are in the buffer for the next boundary.
    assert h.daemon.buffer == "пр"


def test_no_phantom_fix_without_a_hotkey() -> None:
    """A plain word must be corrected once, by the Space trigger only."""
    h = Harness()
    h.type("ghbdtn ")
    assert h.injector.replacements == [(7, "привет ", "ru")]
