"""Integration tests for the daemon using fake evdev devices and injectors.

The tests exercise the real event-handling logic of
:class:`linguafix.daemon.LinguaFixDaemon`; only the operating-system boundary
(``evdev`` devices, the layout switcher and the text injector) is replaced with
lightweight fakes so the suite runs on a headless CI machine.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import Config  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector  # noqa: E402

EV_KEY = evdev.ecodes.EV_KEY


@dataclass
class FakeEvent:
    """A minimal stand-in for :class:`evdev.InputEvent`."""

    type: int
    code: int
    value: int


@dataclass
class FakeDevice:
    """A fake input device backed by a pipe so ``select`` can observe it."""

    events: list[FakeEvent] = field(default_factory=list)
    name: str = "Fake Keyboard"
    _read_fd: int = field(init=False)
    _write_fd: int = field(init=False)
    closed: bool = False

    def __post_init__(self) -> None:
        self._read_fd, self._write_fd = os.pipe()
        self.fd = self._read_fd

    def read(self) -> list[FakeEvent]:
        events, self.events = self.events, []
        return events

    def trigger(self) -> None:
        """Make the device readable for ``select``."""
        os.write(self._write_fd, b"x")

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            os.close(self._read_fd)
            os.close(self._write_fd)

    def capabilities(self) -> dict[int, list[int]]:
        return {EV_KEY: [evdev.ecodes.KEY_A, evdev.ecodes.KEY_Z]}


class FakeSwitcher:
    """Records layout switches and reports a configurable current layout."""

    def __init__(self, current: str = "us", layouts: list[str] | None = None) -> None:
        self.current = current
        self.layouts = layouts or ["us", "ru"]
        self.switches: list[str] = []
        self.backend = "fake"

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.switches.append(layout)
        self.current = layout
        return True

    def describe(self) -> str:
        return "backend=fake"


class FakeInjector:
    """Records text replacements instead of touching the kernel."""

    def __init__(self) -> None:
        self.replacements: list[tuple[int, str, str]] = []
        self.backend = "fake"

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


def make_key_event(name: str, value: int = 1) -> FakeEvent:
    """Create a key event for the evdev key called ``name``."""
    return FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), value)


def type_text(text: str) -> list[FakeEvent]:
    """Return press/release events that type ``text`` on a US layout."""
    name_by_char = {
        v[0]: k
        for k, v in {
            "KEY_G": ("g", "G"),
            "KEY_H": ("h", "H"),
            "KEY_B": ("b", "B"),
            "KEY_D": ("d", "D"),
            "KEY_T": ("t", "T"),
            "KEY_N": ("n", "N"),
            "KEY_A": ("a", "A"),
            "KEY_E": ("e", "E"),
            "KEY_L": ("l", "L"),
            "KEY_O": ("o", "O"),
            "KEY_SPACE": (" ", " "),
        }.items()
    }
    events: list[FakeEvent] = []
    for char in text:
        key = name_by_char.get(char)
        if key is None:
            continue
        events.append(make_key_event(key, 1))
        events.append(make_key_event(key, 0))
    return events


@pytest.fixture
def daemon() -> LinguaFixDaemon:
    """Return a daemon wired to fakes with a short analysis timeout."""
    config = Config(analysis_timeout=0.1, stop_words=["password"], notify_on_fix=False)
    detector = LanguageDetector(
        converter=None, stop_words=config.stop_words, min_word_length=config.min_word_length
    )
    return LinguaFixDaemon(
        config,
        detector=detector,
        switcher=FakeSwitcher("us"),
        injector=FakeInjector(),
    )


# --- event handling ---------------------------------------------------------


def test_buffer_accumulates_letters(daemon: LinguaFixDaemon) -> None:
    for event in type_text("ghbdtn"):
        daemon._handle_event(event)
    assert daemon.buffer == "ghbdtn"


def test_backspace_removes_last_char(daemon: LinguaFixDaemon) -> None:
    for event in type_text("ghb"):
        daemon._handle_event(event)
    daemon._handle_event(make_key_event("KEY_BACKSPACE", 1))
    assert daemon.buffer == "gh"


def test_backspace_on_empty_buffer_is_safe(daemon: LinguaFixDaemon) -> None:
    daemon._handle_event(make_key_event("KEY_BACKSPACE", 1))
    assert daemon.buffer == ""


def test_enter_flushes_buffer(daemon: LinguaFixDaemon) -> None:
    for event in type_text("ghbdtn"):
        daemon._handle_event(event)
    daemon._handle_event(make_key_event("KEY_ENTER", 1))
    assert daemon.buffer == ""
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    assert injector.replacements == [(6, "привет", "ru")]


def test_shift_produces_uppercase(daemon: LinguaFixDaemon) -> None:
    daemon._handle_event(make_key_event("KEY_LEFTSHIFT", 1))
    daemon._handle_event(make_key_event("KEY_G", 1))
    daemon._handle_event(make_key_event("KEY_LEFTSHIFT", 0))
    assert daemon.buffer == "G"


def test_auto_repeat_is_ignored_for_letters(daemon: LinguaFixDaemon) -> None:
    daemon._handle_event(make_key_event("KEY_G", 1))
    daemon._handle_event(make_key_event("KEY_G", 2))
    assert daemon.buffer == "g"


def test_mixed_script_word_is_left_alone(daemon: LinguaFixDaemon) -> None:
    # A single token mixing both scripts cannot be repaired as a unit; the
    # separator between the two halves flushes each of them instead.
    daemon.buffer = "приветhello"
    daemon.last_key_time = time.time()
    daemon._process_buffer()
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    assert injector.replacements == []


def test_mixed_script_words_are_fixed(daemon: LinguaFixDaemon) -> None:
    # Scripts in separate words: the whole buffer can be converted as a unit.
    daemon.buffer = "привет hello"
    daemon.last_key_time = time.time()
    daemon._process_buffer()
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    assert injector.replacements


# --- buffer processing ------------------------------------------------------


def test_process_buffer_switches_and_replaces(daemon: LinguaFixDaemon) -> None:
    for event in type_text("ghbdtn"):
        daemon._handle_event(event)
    daemon._process_buffer()
    switcher = daemon.switcher
    injector = daemon.injector
    assert isinstance(switcher, FakeSwitcher)
    assert isinstance(injector, FakeInjector)
    assert switcher.switches == ["ru"]
    # Six physical keys were pressed, so six Backspaces are sent.
    assert injector.replacements == [(6, "привет", "ru")]


def test_process_buffer_noop_for_correct_layout(daemon: LinguaFixDaemon) -> None:
    daemon.buffer = "hello"
    daemon._process_buffer()
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    assert injector.replacements == []


def test_process_buffer_skips_stop_words(daemon: LinguaFixDaemon) -> None:
    daemon.buffer = "password"
    daemon._process_buffer()
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    assert injector.replacements == []


def test_process_buffer_clears_buffer(daemon: LinguaFixDaemon) -> None:
    daemon.buffer = "ghbdtn"
    daemon._process_buffer()
    assert daemon.buffer == ""


def test_process_buffer_skips_short_text(daemon: LinguaFixDaemon) -> None:
    daemon.buffer = "ab"
    daemon._process_buffer()
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    assert injector.replacements == []


# --- dry run ----------------------------------------------------------------


def test_dry_run_does_not_switch_or_replace() -> None:
    daemon = LinguaFixDaemon(
        Config(analysis_timeout=0.1),
        switcher=FakeSwitcher("us"),
        injector=FakeInjector(),
        dry_run=True,
    )
    daemon.buffer = "ghbdtn"
    daemon._process_buffer()
    switcher = daemon.switcher
    injector = daemon.injector
    assert isinstance(switcher, FakeSwitcher)
    assert isinstance(injector, FakeInjector)
    assert switcher.switches == []
    assert injector.replacements == []


def test_status_text_reports_layout() -> None:
    daemon = LinguaFixDaemon(Config(), switcher=FakeSwitcher("ru"), injector=FakeInjector())
    daemon._running = True
    assert "ru" in daemon.status_text()
    assert "active" in daemon.status_text()


def test_tray_fix_processes_pending_buffer() -> None:
    daemon = LinguaFixDaemon(
        Config(analysis_timeout=0.1),
        switcher=FakeSwitcher("us"),
        injector=FakeInjector(),
    )
    for event in type_text("ghbdtn"):
        daemon._handle_event(event)
    daemon._tray_fix()
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    assert injector.replacements == [(6, "привет", "ru")]


def test_tray_fix_without_buffer_is_noop() -> None:
    daemon = LinguaFixDaemon(Config(), switcher=FakeSwitcher(), injector=FakeInjector())
    daemon._tray_fix()  # must not raise


# --- privacy ----------------------------------------------------------------


def test_typed_text_is_not_written_to_logs(
    daemon: LinguaFixDaemon, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    daemon.buffer = "ghbdtn"
    daemon._process_buffer()
    # The correction must be logged as metadata, never as the typed text.
    assert "ghbdtn" not in caplog.text
    assert "привет" not in caplog.text
    assert "length 6" in caplog.text


def test_stop_word_text_is_not_written_to_logs(
    daemon: LinguaFixDaemon, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    daemon.buffer = "password"
    daemon._process_buffer()
    assert "password" not in caplog.text


# --- config reload ----------------------------------------------------------


def test_reload_config_updates_detector(
    daemon: LinguaFixDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_config = Config(stop_words=["brandnew"], min_word_length=5)
    monkeypatch.setattr("linguafix.config.load_config", lambda: new_config)
    daemon.reload_config()
    assert daemon.config is new_config
    assert "brandnew" in daemon.detector.stop_words
    assert daemon.detector.min_word_length == 5


def test_reload_config_survives_errors(
    daemon: LinguaFixDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom() -> Config:
        raise RuntimeError("broken config")

    monkeypatch.setattr("linguafix.config.load_config", boom)
    daemon.reload_config()  # must not raise
    assert daemon.config.analysis_timeout == 0.1


# --- single instance --------------------------------------------------------


def test_lock_is_exclusive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    first = LinguaFixDaemon(Config())
    second = LinguaFixDaemon(Config())
    try:
        assert first.acquire_lock() is True
        assert second.acquire_lock() is False
    finally:
        first.release_lock()
        second.release_lock()


# --- main loop --------------------------------------------------------------


def test_run_processes_events_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config(analysis_timeout=0.1, stop_words=["password"])
    device = FakeDevice(events=type_text("ghbdtn"))
    switcher = FakeSwitcher("us")
    injector = FakeInjector()
    daemon = LinguaFixDaemon(
        config,
        switcher=switcher,
        injector=injector,
        devices=[device],
    )
    monkeypatch.setattr(daemon, "acquire_lock", lambda: True)
    monkeypatch.setattr(daemon, "release_lock", lambda: None)
    monkeypatch.setattr(daemon, "_install_signal_handlers", lambda: None)

    thread = threading.Thread(target=daemon.run)
    thread.start()
    device.trigger()
    time.sleep(0.5)
    daemon.stop()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert switcher.switches == ["ru"]
    assert injector.replacements == [(6, "привет", "ru")]


def test_run_without_devices_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    daemon = LinguaFixDaemon(Config(), switcher=FakeSwitcher(), injector=FakeInjector())
    monkeypatch.setattr(daemon, "acquire_lock", lambda: True)
    monkeypatch.setattr(daemon, "release_lock", lambda: None)
    monkeypatch.setattr(daemon, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(daemon, "discover_devices", lambda: [])
    assert daemon.run() == 2
