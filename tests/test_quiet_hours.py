"""Quiet hours: silence automatic correction inside a daily time window."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import Config, in_quiet_hours  # noqa: E402
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


def make_event(name: str, value: int = 1) -> FakeEvent:
    return FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), value)


def press(daemon: LinguaFixDaemon, text: str) -> None:
    for char in text:
        name, _ = _KEY_BY_CHAR[char]
        daemon._handle_event(make_event(name, 1))
        daemon._handle_event(make_event(name, 0))


def tap(daemon: LinguaFixDaemon, name: str) -> None:
    daemon._handle_event(make_event(name, 1))
    daemon._handle_event(make_event(name, 0))


def make_daemon(**kwargs: object) -> LinguaFixDaemon:
    config = Config(stop_words=["password"], **kwargs)
    detector = LanguageDetector(
        converter=LayoutConverter(),
        stop_words=config.stop_words,
        min_word_length=config.min_word_length,
    )
    return LinguaFixDaemon(
        config,
        detector=detector,
        switcher=FakeSwitcher("us"),
        injector=FakeInjector(),
    )


@pytest.mark.parametrize(
    "start,end,now,expected",
    [
        ("22:00", "08:00", 23 * 60, True),  # late night, wraps midnight
        ("22:00", "08:00", 3 * 60, True),  # early morning
        ("22:00", "08:00", 12 * 60, False),  # midday
        ("22:00", "08:00", 22 * 60, True),  # start is inclusive
        ("22:00", "08:00", 8 * 60, False),  # end is exclusive
        ("09:00", "17:00", 12 * 60, True),  # same-day window
        ("09:00", "17:00", 8 * 60, False),
        ("00:00", "00:00", 12 * 60, False),  # equal bounds = never
    ],
)
def test_in_quiet_hours_window(start: str, end: str, now: int, expected: bool) -> None:
    assert in_quiet_hours(start, end, now) is expected


def test_quiet_hours_suppress_automatic_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(
        quiet_hours_enabled=True, quiet_hours_start="22:00", quiet_hours_end="08:00"
    )
    monkeypatch.setattr(daemon, "_is_quiet_now", lambda: True)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    assert injector.replacements == []


def test_quiet_hours_do_not_block_manual_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(quiet_hours_enabled=True)
    monkeypatch.setattr(daemon, "_is_quiet_now", lambda: True)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_LEFTSHIFT")
    tap(daemon, "KEY_LEFTSHIFT")
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    assert injector.replacements == [(6, "привет", "ru")]


def test_quiet_hours_disabled_fixes_normally() -> None:
    daemon = make_daemon(quiet_hours_enabled=False)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    assert injector.replacements == [(7, "привет ", "ru")]


def test_invalid_quiet_hours_time_is_rejected() -> None:
    with pytest.raises(ValueError):
        Config(quiet_hours_start="25:00").validate()
    with pytest.raises(ValueError):
        Config(quiet_hours_end="8:00").validate()
