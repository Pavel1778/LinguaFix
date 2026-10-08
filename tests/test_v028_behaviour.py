"""Behaviour added for v0.2.8: late double Shift, T9 parity, toggle layout.

Each test drives the real daemon with a fake keyboard and injector, so the
event handling, buffer/memory bookkeeping and the injector contract are all
exercised without a kernel device.
"""

from __future__ import annotations

import time
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


@dataclass
class FakeInjector:
    replacements: list[tuple[int, str, str]] = field(default_factory=list)
    backend: str = "fake"

    def can_type(self, char: str, layout: str) -> bool:
        return char == " "

    def replace_text(
        self, backspace_count: int, new: str, layout: str, boundary_char: str = ""
    ) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True


_KEY_BY_CHAR = {" ": ("KEY_SPACE", False)}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    _KEY_BY_CHAR[_letter] = (f"KEY_{_letter.upper()}", False)


def _key_name(char: str) -> str:
    return _KEY_BY_CHAR[char][0]


def tap(daemon: LinguaFixDaemon, name: str) -> None:
    daemon._handle_event(FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), 1))
    daemon._handle_event(FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), 0))


def press(daemon: LinguaFixDaemon, text: str) -> None:
    for char in text:
        tap(daemon, _key_name(char))


def make_daemon(**kwargs: object) -> LinguaFixDaemon:
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


# --- Task 5: a late double Shift reaches the just-flushed word -------------


def test_double_shift_after_space_fixes_in_manual_mode() -> None:
    """Manual mode: Space flushes without correcting, double Shift then fixes.

    This is the "double Shift does nothing after Space" complaint — the word is
    no longer in the live buffer, but the daemon remembers it.
    """
    daemon = make_daemon(mode="manual")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")  # boundary consumes the word, manual mode skips
    assert _injector(daemon).replacements == []
    assert daemon._last_flushed_word == "ghbdtn"

    tap(daemon, "KEY_LEFTSHIFT")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTSHIFT")
    assert _injector(daemon).replacements == [(6, "привет", "ru")]


def test_double_shift_after_auto_fix_does_not_revert() -> None:
    """When the boundary already fixed the word, a late double Shift is a noop."""
    daemon = make_daemon(mode="auto")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == [(7, "привет ", "ru")]
    assert daemon._last_flushed_corrected is True

    tap(daemon, "KEY_LEFTSHIFT")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTSHIFT")
    # No second replacement: the word on screen is already correct.
    assert _injector(daemon).replacements == [(7, "привет ", "ru")]


# --- Task 9: T9 runs in the daemon path parity with the CLI ----------------


def test_typo_correction_runs_in_daemon_path() -> None:
    daemon = make_daemon(typo_correction=True)
    press(daemon, "langauge")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == [(9, "language ", "us")]


# --- Feature A: manual reverse conversion of the last word ----------------


def test_toggle_layout_of_live_buffer() -> None:
    """Ctrl+Shift+T forces ``привет`` -> ``ghbdtn`` even though it is correct."""
    daemon = make_daemon()
    switch = daemon.switcher
    assert isinstance(switch, FakeSwitcher)
    switch.current = "ru"
    press(daemon, "ghbdtn")  # on a ru layout these keys type "привет"
    daemon._run_hotkey("toggle_layout")
    assert _injector(daemon).replacements == [(6, "ghbdtn", "us")]


def test_toggle_layout_uses_last_flushed_word() -> None:
    daemon = make_daemon()
    switch = daemon.switcher
    assert isinstance(switch, FakeSwitcher)
    switch.current = "ru"
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")  # buffer cleared, memory keeps the word
    daemon._run_hotkey("toggle_layout")
    assert _injector(daemon).replacements == [(6, "ghbdtn", "us")]


def test_toggle_layout_with_nothing_does_nothing() -> None:
    daemon = make_daemon()
    daemon._run_hotkey("toggle_layout")
    assert _injector(daemon).replacements == []


def test_toggle_layout_hotkey_is_registered() -> None:
    daemon = make_daemon()
    assert daemon._hotkeys["toggle_layout"] is not None
