"""Regression: truncation when the fix is triggered by Space/Enter.

The user typed ``hello`` while the Russian layout was active, so the keys
produced ``руддщ``; pressing Space then produced ``рhello`` instead of
``hello`` because the deletion raced the boundary key that was still being
processed by the compositor.

These tests pin the boundary-flush behaviour at the daemon level:

* the daemon waits ``trigger_settle_ms`` before deleting when — and only when —
  the flush came from a word-boundary key;
* the boundary key itself is never part of the word buffer;
* consecutive words flush independently.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import Config  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector  # noqa: E402
from linguafix.injector import TextInjector  # noqa: E402

EV_KEY = int(evdev.ecodes.EV_KEY)
BACKSPACE = int(evdev.ecodes.KEY_BACKSPACE)

# The physical US keys that produce "руддщ" while the Russian layout is active.
RU_WORD_KEYS = ["KEY_H", "KEY_E", "KEY_L", "KEY_L", "KEY_O"]


class RecordingUInput:
    """Stand-in for ``evdev.UInput`` recording every written event."""

    instances: ClassVar[list[RecordingUInput]] = []

    def __init__(self, capabilities: object, name: str = "linguafix") -> None:
        self.capabilities = capabilities
        self.name = name
        self.written: list[tuple[int, int, int]] = []
        self.synced = 0
        RecordingUInput.instances.append(self)

    def write(self, event_type: int, code: int, value: int) -> None:
        self.written.append((event_type, code, value))

    def syn(self) -> None:
        self.synced += 1

    def close(self) -> None:
        return None

    @property
    def presses(self) -> list[tuple[int, int, int]]:
        """Only the key-down events (value == 1)."""
        return [event for event in self.written if event[2] == 1]


class FakeSwitcher:
    backend = "fake"

    def __init__(self, current: str = "ru") -> None:
        self.current = current

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        return True

    def describe(self) -> str:
        return "backend=fake"


class FakeInjector:
    backend = "fake"

    def __init__(self) -> None:
        self.replacements: list[tuple[int, str, str]] = []

    def replace_text(self, backspace_count: int, new: str, layout: str) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True

    def describe(self) -> str:
        return "backend=fake"


def _press(daemon: LinguaFixDaemon, key_names: list[str]) -> None:
    for name in key_names:
        code = int(getattr(evdev.ecodes, name))
        daemon._handle_event(type("E", (), {"type": EV_KEY, "code": code, "value": 1})())
        daemon._handle_event(type("E", (), {"type": EV_KEY, "code": code, "value": 0})())


def _make_daemon(**kwargs: object) -> LinguaFixDaemon:
    options: dict[str, object] = {
        "analysis_timeout": 0.8,
        "stop_words": [],
        "trigger_settle_ms": 77,
    }
    options.update(kwargs)
    config = Config(**options)
    detector = LanguageDetector(converter=None, stop_words=[], min_word_length=3)
    return LinguaFixDaemon(
        config,
        detector=detector,
        switcher=FakeSwitcher("ru"),
        injector=FakeInjector(),
    )


def _injector(daemon: LinguaFixDaemon) -> FakeInjector:
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    return injector


# --- the exact batch at a boundary ------------------------------------------


def test_space_boundary_emits_five_backspaces_and_hello(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``руддщ`` + Space deletes all five keys and types ``hello``."""
    RecordingUInput.instances.clear()
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    monkeypatch.setattr(evdev, "UInput", RecordingUInput)
    monkeypatch.setattr("linguafix.injector.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("linguafix.daemon.time.sleep", lambda _seconds: None)

    daemon = LinguaFixDaemon(
        Config(analysis_timeout=0.8, stop_words=[], trigger_settle_ms=50),
        detector=LanguageDetector(converter=None, stop_words=[], min_word_length=3),
        switcher=FakeSwitcher("ru"),
    )
    _press(daemon, RU_WORD_KEYS)
    _press(daemon, ["KEY_SPACE"])

    assert len(RecordingUInput.instances) == 2
    backspace_device, text_device = RecordingUInput.instances
    # Exactly five Backspaces: the first character must not survive.
    assert backspace_device.presses == [(EV_KEY, BACKSPACE, 1)] * 5
    assert backspace_device.synced == 1
    assert text_device.synced == 1
    assert [code for _etype, code, _value in text_device.presses] == [
        int(evdev.ecodes.KEY_H),
        int(evdev.ecodes.KEY_E),
        int(evdev.ecodes.KEY_L),
        int(evdev.ecodes.KEY_L),
        int(evdev.ecodes.KEY_O),
    ]
    assert daemon.buffer == ""


def test_trigger_settle_waits_before_deleting(monkeypatch: pytest.MonkeyPatch) -> None:
    """A boundary flush sleeps ``trigger_settle_ms`` before the deletion."""
    sleeps: list[float] = []
    monkeypatch.setattr("linguafix.daemon.time.sleep", sleeps.append)

    daemon = _make_daemon(trigger_settle_ms=77)
    _press(daemon, RU_WORD_KEYS)
    _press(daemon, ["KEY_SPACE"])

    assert 0.077 in sleeps
    assert _injector(daemon).replacements == [(5, "hello", "us")]


def test_idle_flush_does_not_wait_trigger_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    """The idle fallback must not pay the boundary pause."""
    sleeps: list[float] = []
    monkeypatch.setattr("linguafix.daemon.time.sleep", sleeps.append)

    daemon = _make_daemon(trigger_settle_ms=77)
    daemon.buffer = "руддщ"
    daemon._scancodes = [int(getattr(evdev.ecodes, name)) for name in RU_WORD_KEYS]
    daemon._process_buffer()  # no boundary

    assert 0.077 not in sleeps
    assert _injector(daemon).replacements == [(5, "hello", "us")]


def test_zero_trigger_settle_does_not_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("linguafix.daemon.time.sleep", sleeps.append)

    daemon = _make_daemon(trigger_settle_ms=0)
    _press(daemon, RU_WORD_KEYS)
    _press(daemon, ["KEY_SPACE"])

    assert 0.077 not in sleeps
    assert _injector(daemon).replacements == [(5, "hello", "us")]


# --- the boundary key is not buffered ---------------------------------------


def test_space_is_not_part_of_the_buffer() -> None:
    daemon = _make_daemon()
    _press(daemon, RU_WORD_KEYS)
    _press(daemon, ["KEY_SPACE"])

    # The buffer is empty after the flush and never contained the Space key.
    assert daemon.buffer == ""
    assert daemon._scancodes == []


def test_enter_boundary_flushes_too(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("linguafix.daemon.time.sleep", sleeps.append)

    daemon = _make_daemon()
    _press(daemon, RU_WORD_KEYS)
    _press(daemon, ["KEY_ENTER"])

    assert 0.077 in sleeps
    assert _injector(daemon).replacements == [(5, "hello", "us")]


# --- consecutive words flush independently ----------------------------------


def test_consecutive_words_flush_independently() -> None:
    daemon = _make_daemon()
    injector = _injector(daemon)
    for _ in range(3):
        # Reset the layout so every word is again "Russian typed on US keys".
        daemon.switcher.current = "ru"
        _press(daemon, RU_WORD_KEYS)
        _press(daemon, ["KEY_SPACE"])
        assert daemon.buffer == ""

    assert injector.replacements == [(5, "hello", "us")] * 3
