"""Double-tap modifier hotkeys (the default ``SHIFT+SHIFT`` fix trigger).

These tests drive the real event handler with a fake keyboard, so the modifier
tracking, the double-tap window and the "single tap does nothing" guarantee are
all exercised without the kernel.
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


def tap(daemon: LinguaFixDaemon, name: str) -> None:
    daemon._handle_event(make_event(name, 1))
    daemon._handle_event(make_event(name, 0))


def press(daemon: LinguaFixDaemon, text: str) -> None:
    for char in text:
        tap(daemon, f"KEY_{char.upper()}")


def make_daemon(**kwargs: object) -> LinguaFixDaemon:
    options: dict[str, object] = {"stop_words": ["password"]}
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


def test_default_fix_hotkey_is_double_shift() -> None:
    assert Config().hotkey_fix_last_word == "SHIFT+SHIFT"


def test_double_shift_within_window_fixes() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_LEFTSHIFT")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTSHIFT")
    assert _injector(daemon).replacements == [(6, "привет", "ru")]


def test_double_shift_mixed_sides_fixes() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_LEFTSHIFT")
    time.sleep(0.02)
    tap(daemon, "KEY_RIGHTSHIFT")
    assert _injector(daemon).replacements == [(6, "привет", "ru")]


def test_double_shift_too_slow_does_not_fix() -> None:
    daemon = make_daemon(hotkey_double_tap_ms=100)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_LEFTSHIFT")
    time.sleep(0.25)
    tap(daemon, "KEY_LEFTSHIFT")
    assert _injector(daemon).replacements == []


def test_single_shift_does_not_fix() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_LEFTSHIFT")
    assert _injector(daemon).replacements == []


def test_capital_between_shifts_does_not_fix() -> None:
    # A capital letter uses Shift, so the two Shift presses are not a double tap.
    daemon = make_daemon()
    tap(daemon, "KEY_LEFTSHIFT")
    tap(daemon, "KEY_G")
    tap(daemon, "KEY_LEFTSHIFT")
    assert _injector(daemon).replacements == []


def test_double_ctrl_hotkey_fixes() -> None:
    daemon = make_daemon(hotkey_fix_last_word="CTRL+CTRL")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_LEFTCTRL")
    time.sleep(0.02)
    tap(daemon, "KEY_RIGHTCTRL")
    assert _injector(daemon).replacements == [(6, "привет", "ru")]


def test_double_alt_hotkey_fixes() -> None:
    daemon = make_daemon(hotkey_fix_last_word="ALT+ALT")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_LEFTALT")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTALT")
    assert _injector(daemon).replacements == [(6, "привет", "ru")]


def test_hotkeys_disabled_ignores_double_tap() -> None:
    daemon = make_daemon(hotkeys_enabled=False)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_LEFTSHIFT")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTSHIFT")
    assert _injector(daemon).replacements == []


def test_capslock_is_not_a_double_tap_modifier() -> None:
    daemon = make_daemon(hotkey_fix_last_word="SHIFT+SHIFT")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_CAPSLOCK")
    tap(daemon, "KEY_CAPSLOCK")
    assert _injector(daemon).replacements == []


def test_reload_config_refreshes_double_tap_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(hotkey_fix_last_word="SHIFT+SHIFT")
    assert daemon._double_tap_hotkeys == {"shift": "fix"}

    new_config = Config(hotkey_fix_last_word="CTRL+CTRL")
    monkeypatch.setattr("linguafix.config.load_config", lambda: new_config)
    daemon.reload_config()
    assert daemon._double_tap_hotkeys == {"ctrl": "fix"}
    assert daemon._hotkeys["fix"] is None


# --- chords must not be mistaken for a double tap ---------------------------


def hold(daemon: LinguaFixDaemon, name: str) -> None:
    daemon._handle_event(make_event(name, 1))


def release(daemon: LinguaFixDaemon, name: str) -> None:
    daemon._handle_event(make_event(name, 0))


def test_ctrl_shift_shift_does_not_fix() -> None:
    """Holding Ctrl while tapping Shift twice is a chord, not a double tap."""
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    hold(daemon, "KEY_LEFTCTRL")
    tap(daemon, "KEY_LEFTSHIFT")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTSHIFT")
    release(daemon, "KEY_LEFTCTRL")
    assert _injector(daemon).replacements == []


def test_alt_shift_shift_does_not_fix() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    hold(daemon, "KEY_LEFTALT")
    tap(daemon, "KEY_LEFTSHIFT")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTSHIFT")
    release(daemon, "KEY_LEFTALT")
    assert _injector(daemon).replacements == []


def test_shift_ctrl_ctrl_does_not_fix() -> None:
    """The same rule holds for the other double-tap families."""
    daemon = make_daemon(hotkey_fix_last_word="CTRL+CTRL")
    press(daemon, "ghbdtn")
    hold(daemon, "KEY_LEFTSHIFT")
    tap(daemon, "KEY_LEFTCTRL")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTCTRL")
    release(daemon, "KEY_LEFTSHIFT")
    assert _injector(daemon).replacements == []


def test_other_modifier_between_shifts_cancels() -> None:
    """A different modifier between two Shift taps cancels the double tap."""
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_LEFTSHIFT")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTCTRL")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTSHIFT")
    assert _injector(daemon).replacements == []


def test_super_between_shifts_cancels() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_LEFTSHIFT")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTMETA")
    time.sleep(0.02)
    tap(daemon, "KEY_LEFTSHIFT")
    assert _injector(daemon).replacements == []
