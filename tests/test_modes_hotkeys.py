"""Working modes, hotkey engine and undo.

These tests drive the real event-handling and buffer-processing paths with a
fake keyboard, switcher and injector, so the mode gating, the hotkey matcher and
the undo history are exercised without touching the kernel or the system bus.
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


_KEY_BY_CHAR = {
    " ": ("KEY_SPACE", False),
}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    _KEY_BY_CHAR[_letter] = (f"KEY_{_letter.upper()}", False)
    _KEY_BY_CHAR[_letter.upper()] = (f"KEY_{_letter.upper()}", True)


def make_event(name: str, value: int = 1) -> FakeEvent:
    return FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), value)


def tap(daemon: LinguaFixDaemon, name: str) -> None:
    daemon._handle_event(make_event(name, 1))
    daemon._handle_event(make_event(name, 0))


def press(daemon: LinguaFixDaemon, text: str) -> None:
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


# --- modes ------------------------------------------------------------------


def test_auto_mode_fixes_automatically() -> None:
    daemon = make_daemon(mode="auto")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == [(7, "привет ", "ru")]


def test_manual_mode_skips_automatic_fix() -> None:
    daemon = make_daemon(mode="manual")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == []
    assert daemon.buffer == ""


def test_manual_mode_forces_fix_for_listed_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("linguafix.daemon.get_active_app", lambda: "myeditor")
    daemon = make_daemon(mode="manual", exceptions_force_in_manual=["myeditor"])
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == [(7, "привет ", "ru")]


def test_manual_mode_ignores_unlisted_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("linguafix.daemon.get_active_app", lambda: "firefox")
    daemon = make_daemon(mode="manual", exceptions_force_in_manual=["kitty"])
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == []


def test_hybrid_mode_fixes_automatically() -> None:
    daemon = make_daemon(mode="hybrid")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == [(7, "привет ", "ru")]


def test_hotkey_forces_fix_in_manual_mode() -> None:
    daemon = make_daemon(mode="manual", hotkey_fix_last_word="PAUSE")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_PAUSE")
    assert _injector(daemon).replacements == [(6, "привет", "ru")]


def test_toggle_mode_hotkey_cycles_and_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[str] = []
    monkeypatch.setattr("linguafix.config.save_config", lambda cfg: saved.append(cfg.mode))
    daemon = make_daemon(mode="auto", hotkey_toggle_mode="CTRL+M")
    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    tap(daemon, "KEY_M")
    assert daemon.config.mode == "hybrid"
    daemon._handle_event(make_event("KEY_LEFTCTRL", 0))

    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    tap(daemon, "KEY_M")
    assert daemon.config.mode == "manual"
    daemon._handle_event(make_event("KEY_LEFTCTRL", 0))

    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    tap(daemon, "KEY_M")
    assert daemon.config.mode == "auto"
    assert saved == ["hybrid", "manual", "auto"]


def test_hotkey_requires_exact_modifiers() -> None:
    daemon = make_daemon(hotkey_fix_last_word="CTRL+F12")
    press(daemon, "ghbdtn")
    # Plain F12 (no Ctrl) must not trigger the hotkey.
    tap(daemon, "KEY_F12")
    assert _injector(daemon).replacements == []
    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    tap(daemon, "KEY_F12")
    assert _injector(daemon).replacements == [(6, "привет", "ru")]
    daemon._handle_event(make_event("KEY_LEFTCTRL", 0))


def test_hotkeys_disabled_ignores_bindings() -> None:
    daemon = make_daemon(mode="manual", hotkeys_enabled=False, hotkey_fix_last_word="PAUSE")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_PAUSE")
    assert _injector(daemon).replacements == []


# --- undo -------------------------------------------------------------------


def test_undo_restores_the_original_text() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    injector = _injector(daemon)
    assert injector.replacements == [(7, "привет ", "ru")]

    daemon._undo_last_fix()
    # Six characters replaced again, this time back to the original.
    assert injector.replacements[1] == (7, "ghbdtn ", "us")


def test_undo_hotkey_triggers_restore() -> None:
    daemon = make_daemon(hotkey_undo_last_fix="CTRL+Z")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    daemon._handle_event(make_event("KEY_LEFTCTRL", 1))
    tap(daemon, "KEY_Z")
    injector = _injector(daemon)
    assert injector.replacements[-1] == (7, "ghbdtn ", "us")


def test_undo_without_history_is_noop() -> None:
    daemon = make_daemon()
    daemon._undo_last_fix()
    assert _injector(daemon).replacements == []


def test_undo_window_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(undo_window_seconds=3)
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    # Age the recorded entry beyond the undo window.
    daemon._undo_history = [
        (time.monotonic() - 100, entry[1], entry[2], entry[3], entry[4])
        for entry in daemon._undo_history
    ]
    daemon._undo_last_fix()
    assert len(_injector(daemon).replacements) == 1


def test_undo_signal_sets_flag() -> None:
    daemon = make_daemon()
    daemon._handle_undo(10, None)
    assert daemon._undo_requested is True


def test_undo_history_depth_is_bounded() -> None:
    daemon = make_daemon(undo_history_depth=1)
    daemon._record_undo("first", "us", 5)
    daemon._record_undo("second", "us", 6)
    assert len(daemon._undo_history) == 1
    assert daemon._undo_history[0][1] == "second"


def test_reload_config_refreshes_hotkeys(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(hotkey_fix_last_word="PAUSE")
    new_config = Config(hotkey_fix_last_word="F9")
    monkeypatch.setattr("linguafix.config.load_config", lambda: new_config)
    daemon.reload_config()
    assert daemon.config.hotkey_fix_last_word == "F9"
    assert daemon._hotkeys["fix"] is not None
    assert daemon._hotkeys["fix"][1] == int(evdev.ecodes.KEY_F9)
