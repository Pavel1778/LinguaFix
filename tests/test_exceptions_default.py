"""Default exceptions: terminals, IDEs and games.

LinguaFix ships a pre-filled "never touch" list, because in a terminal or an
editor the other layout is *not* more plausible — what is typed there is a
command or an identifier, not a word. A manual fix (double Shift) must still
work inside those applications.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import DEFAULT_EXCEPTION_APPS, Config  # noqa: E402
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


def make_daemon(monkeypatch: pytest.MonkeyPatch, app: str, **kwargs: object) -> LinguaFixDaemon:
    monkeypatch.setattr("linguafix.daemon.get_active_app", lambda: app)
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


def _injector(daemon: LinguaFixDaemon) -> FakeInjector:
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    return injector


def test_default_list_is_prefilled() -> None:
    config = Config()
    for app in ("gnome-terminal", "code", "steam", "jetbrains-idea"):
        assert app in config.exceptions_apps
    assert "gnome-terminal" in DEFAULT_EXCEPTION_APPS


@pytest.mark.parametrize("app", ["gnome-terminal", "code", "steam"])
def test_default_exception_app_skips_automatic_fix(
    monkeypatch: pytest.MonkeyPatch, app: str
) -> None:
    daemon = make_daemon(monkeypatch, app, mode="auto")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == []


def test_unlisted_app_still_fixes(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(monkeypatch, "firefox", mode="auto")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == [(7, "привет ", "ru")]


def test_manual_fix_works_inside_an_excepted_app(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(monkeypatch, "gnome-terminal", mode="auto")
    press(daemon, "ghbdtn")
    # The exception suppresses the automatic boundary flush, but an explicit
    # double Shift before a boundary still corrects the word.
    tap(daemon, "KEY_LEFTSHIFT")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTSHIFT")
    assert _injector(daemon).replacements == [(6, "привет", "ru")]
