"""Word-boundary triggers: Space/Enter flush the buffer immediately.

These tests drive the real ``_handle_event`` path with a fake keyboard and a
fake injector, so they exercise the daemon's buffering and trigger logic without
touching the kernel. They cover the "real-time" behaviour the user asked for:
pressing Space ends the word and the correction happens in the same keystroke,
not after an idle pause.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import Config  # noqa: E402
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
    backend: str = "fake"

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
    backend: str = "fake"

    def can_type(self, char: str, layout: str) -> bool:
        # Mirror the uinput backend: only Space is layout-invariant and typed.
        return char == " "

    def replace_text(
        self, backspace_count: int, new: str, layout: str, boundary_char: str = ""
    ) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True

    def describe(self) -> str:
        return "backend=fake"


# Physical US keys for every character used across the tests.
_KEY_BY_CHAR = {
    ".": ("KEY_DOT", False),
    "@": ("KEY_2", True),
    " ": ("KEY_SPACE", False),
    "1": ("KEY_1", False),
    "2": ("KEY_2", False),
    "3": ("KEY_3", False),
    "4": ("KEY_4", False),
}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    _KEY_BY_CHAR[_letter] = (f"KEY_{_letter.upper()}", False)
    _KEY_BY_CHAR[_letter.upper()] = (f"KEY_{_letter.upper()}", True)


def make_event(name: str, value: int = 1) -> FakeEvent:
    return FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), value)


def press(daemon: LinguaFixDaemon, text: str) -> None:
    """Press (and release) the physical keys that produce ``text`` on a US layout."""
    for char in text:
        name, shift = _KEY_BY_CHAR[char]
        if shift:
            daemon._handle_event(make_event("KEY_LEFTSHIFT", 1))
        daemon._handle_event(make_event(name, 1))
        daemon._handle_event(make_event(name, 0))
        if shift:
            daemon._handle_event(make_event("KEY_LEFTSHIFT", 0))


def make_daemon(**kwargs: object) -> LinguaFixDaemon:
    options: dict[str, object] = {"analysis_timeout": 0.8, "stop_words": ["password"]}
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


# --- Space and Enter flush immediately --------------------------------------


def test_space_triggers_fix_and_clears_buffer() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    assert daemon.buffer == "ghbdtn"
    press(daemon, " ")
    # The fix ran inside the same Space keystroke, without any idle wait.
    assert _injector(daemon).replacements == [(7, "привет ", "ru")]
    assert daemon.buffer == ""


def test_enter_triggers_fix_and_clears_buffer() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_ENTER", 1))
    assert _injector(daemon).replacements == [(6, "привет", "ru")]
    assert daemon.buffer == ""


def test_space_without_buffer_is_noop() -> None:
    daemon = make_daemon()
    press(daemon, " ")
    assert _injector(daemon).replacements == []
    assert daemon.buffer == ""


def test_short_word_is_not_corrected() -> None:
    daemon = make_daemon()
    press(daemon, "ab")
    press(daemon, " ")
    assert _injector(daemon).replacements == []
    assert daemon.buffer == ""


def test_three_words_are_three_independent_fixes() -> None:
    daemon = make_daemon()
    switcher = daemon.switcher
    assert isinstance(switcher, FakeSwitcher)
    # Each word is typed on the US layout (the switcher is reset between words,
    # as if the user toggled the OS layout back): every word is its own fix.
    for typed, _expected in [("ghbdtn", "привет"), ("ljv", "дом"), ("rfr", "как")]:
        switcher.current = "us"
        press(daemon, typed)
        press(daemon, " ")

    injector = _injector(daemon)
    assert [new for _count, new, _layout in injector.replacements] == [
        "привет ",
        "дом ",
        "как ",
    ]
    assert daemon.buffer == ""


# --- false-positive guards --------------------------------------------------


def test_email_is_not_corrected() -> None:
    daemon = make_daemon()
    press(daemon, "test@example.com")
    press(daemon, " ")
    assert _injector(daemon).replacements == []


def test_decimal_number_is_not_corrected() -> None:
    daemon = make_daemon()
    press(daemon, "3.14")
    press(daemon, " ")
    assert _injector(daemon).replacements == []


def test_domain_is_not_corrected() -> None:
    daemon = make_daemon()
    press(daemon, "github.com")
    press(daemon, " ")
    assert _injector(daemon).replacements == []


def test_stop_word_is_not_corrected() -> None:
    daemon = make_daemon()
    press(daemon, "password")
    press(daemon, " ")
    assert _injector(daemon).replacements == []


# --- fallback idle timeout --------------------------------------------------


def test_idle_timeout_flushes_without_separator() -> None:
    daemon = make_daemon(analysis_timeout=0.05)
    press(daemon, "ghbdtn")
    # No separator was typed; the fallback timer must flush the word.
    daemon.last_key_time = time.time() - 1.0
    daemon._flush_if_idle()
    assert _injector(daemon).replacements == [(6, "привет", "ru")]
    assert daemon.buffer == ""


def test_idle_timeout_does_not_flush_a_fresh_buffer() -> None:
    daemon = make_daemon(analysis_timeout=10.0)
    press(daemon, "ghbdtn")
    daemon._flush_if_idle()
    assert _injector(daemon).replacements == []
    assert daemon.buffer == "ghbdtn"


# --- configurable boundaries ------------------------------------------------


def test_space_trigger_can_be_disabled() -> None:
    daemon = make_daemon(on_space=False)
    press(daemon, "ghbdtn")
    press(daemon, " ")
    assert _injector(daemon).replacements == []
    # The buffer was reset at the boundary, not analysed.
    assert daemon.buffer == ""


def test_enter_trigger_can_be_disabled() -> None:
    daemon = make_daemon(on_enter=False)
    press(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_ENTER", 1))
    assert _injector(daemon).replacements == []
    assert daemon.buffer == ""


def test_tab_trigger_off_by_default() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_TAB", 1))
    assert _injector(daemon).replacements == []
    assert daemon.buffer == ""


def test_tab_trigger_can_be_enabled() -> None:
    daemon = make_daemon(on_tab=True)
    press(daemon, "ghbdtn")
    daemon._handle_event(make_event("KEY_TAB", 1))
    assert _injector(daemon).replacements == [(6, "привет", "ru")]
    assert daemon.buffer == ""


def test_punctuation_trigger_off_by_default() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    press(daemon, ".")
    # The dot stays part of the buffer and is not a boundary when disabled.
    assert _injector(daemon).replacements == []
    assert daemon.buffer == "ghbdtn."


def test_punctuation_trigger_can_be_enabled() -> None:
    daemon = make_daemon(on_punctuation=True)
    press(daemon, "ghbdtn")
    press(daemon, ".")
    assert _injector(daemon).replacements == [(6, "привет", "ru")]
    assert daemon.buffer == ""


def test_punctuation_outside_the_configured_set_is_not_a_boundary() -> None:
    daemon = make_daemon(on_punctuation=True, punctuation_chars=",")
    press(daemon, "ghbdtn")
    press(daemon, ".")
    assert _injector(daemon).replacements == []
    assert daemon.buffer == "ghbdtn."
