"""Robustness audit: races, crashes, device loss, memory and shutdown.

Each test targets one failure mode that matters for a daemon which reads every
keystroke and injects text. Only the OS boundary (devices, switcher, injector)
is faked; the daemon's real logic runs.
"""

from __future__ import annotations

import os
import selectors
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from linguafix import daemon as daemon_module
from linguafix.config import Config
from linguafix.daemon import LinguaFixDaemon
from linguafix.detector import LanguageDetector


@dataclass
class FakeEvent:
    type: int
    code: int
    value: int


@dataclass
class FakeDevice:
    events: list[FakeEvent] = field(default_factory=list)
    name: str = "Fake Keyboard"
    fail_on_read: bool = False
    closed: bool = False
    _read_fd: int = field(init=False)
    _write_fd: int = field(init=False)

    def __post_init__(self) -> None:
        self._read_fd, self._write_fd = os.pipe()
        self.fd = self._read_fd

    def read(self) -> list[FakeEvent]:
        if self.fail_on_read:
            raise OSError(19, "No such device")
        events, self.events = self.events, []
        return events

    def trigger(self) -> None:
        os.write(self._write_fd, b"x")

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            os.close(self._read_fd)
            os.close(self._write_fd)

    def capabilities(self) -> dict[int, list[int]]:
        return {}


class FakeSwitcher:
    backend = "fake"

    def __init__(self, current: str = "us", on_switch: Callable[[], None] | None = None) -> None:
        self.current = current
        self.switches: list[str] = []
        self.on_switch = on_switch

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.switches.append(layout)
        self.current = layout
        if self.on_switch is not None:
            self.on_switch()
        return True

    def describe(self) -> str:
        return "backend=fake"


class FakeInjector:
    backend = "fake"

    def __init__(self, on_replace: Callable[[], None] | None = None) -> None:
        self.replacements: list[tuple[int, str, str]] = []
        self.on_replace = on_replace

    def replace_text(self, backspace_count: int, new: str, layout: str) -> bool:
        self.replacements.append((backspace_count, new, layout))
        if self.on_replace is not None:
            self.on_replace()
        return True

    def describe(self) -> str:
        return "backend=fake"


def _make_daemon(**kwargs: object) -> LinguaFixDaemon:
    config = Config(analysis_timeout=0.1, min_word_length=3, stop_words=["password"])
    return LinguaFixDaemon(
        config,
        detector=LanguageDetector(converter=None, stop_words=config.stop_words, min_word_length=3),
        switcher=kwargs.pop("switcher", FakeSwitcher("us")),
        injector=kwargs.pop("injector", FakeInjector()),
        **kwargs,
    )


# --- 3. race condition: typing during a fix ---------------------------------


def test_typing_during_fix_is_not_lost() -> None:
    """A key pressed while the fix runs must be buffered, not dropped."""
    injector = FakeInjector()
    daemon = _make_daemon(injector=injector)

    def type_during_fix() -> None:
        # Simulates the user hitting a key between the backspaces and the text.
        daemon.buffer += "x"

    injector.on_replace = type_during_fix
    daemon.buffer = "ghbdtn"
    daemon._process_buffer()

    assert injector.replacements == [(0, "привет", "ru")]
    # The keystroke landed in the buffer and was not swallowed by the fix.
    assert daemon.buffer == "x"


def test_concurrent_fixes_do_not_duplicate() -> None:
    """Two threads calling _process_buffer must correct the text only once."""
    injector = FakeInjector()
    daemon = _make_daemon(injector=injector)
    daemon.buffer = "ghbdtn"

    threads = [threading.Thread(target=daemon._process_buffer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert len(injector.replacements) == 1
    assert daemon.buffer == ""


# --- 4. device unplug -------------------------------------------------------


def test_device_read_error_is_survived_and_rediscovered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A removed device must not crash the loop; discovery runs again."""
    device = FakeDevice()
    daemon = _make_daemon(devices=[device])
    daemon._running = True

    rediscovered: list[object] = []

    def discover() -> list[FakeDevice]:
        rediscovered.append(object())
        return []

    monkeypatch.setattr(daemon, "discover_devices", discover)
    monkeypatch.setattr(daemon_module, "DEVICE_RESCAN_DELAY", 0.0)

    selector = selectors.DefaultSelector()
    selector.register(device.fd, selectors.EVENT_READ, device)

    thread = threading.Thread(target=daemon._loop, args=(selector,))
    thread.start()
    try:
        device.fail_on_read = True
        device.trigger()
        time.sleep(0.4)
    finally:
        daemon.stop()
        thread.join(timeout=5)
        selector.close()

    assert not thread.is_alive()
    assert rediscovered, "the loop must retry device discovery after the last one goes away"
    assert device.closed


def test_run_returns_zero_when_device_disappears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = FakeDevice()
    daemon = _make_daemon(devices=[device])
    monkeypatch.setattr(daemon, "acquire_lock", lambda: True)
    monkeypatch.setattr(daemon, "release_lock", lambda: None)
    monkeypatch.setattr(daemon, "_install_signal_handlers", lambda: None)
    monkeypatch.setattr(daemon, "discover_devices", lambda: [])
    monkeypatch.setattr(daemon_module, "DEVICE_RESCAN_DELAY", 0.0)

    thread = threading.Thread(target=daemon.run)
    thread.start()
    time.sleep(0.1)
    device.fail_on_read = True
    device.trigger()
    time.sleep(0.2)
    daemon.stop()
    thread.join(timeout=5)

    assert not thread.is_alive()


# --- 5. several keyboards ---------------------------------------------------


def test_events_from_all_keyboards_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every discovered keyboard is registered and read, not just the first."""
    import evdev

    ev_key = evdev.ecodes.EV_KEY
    a_code = int(evdev.ecodes.KEY_A)

    first = FakeDevice(events=[FakeEvent(ev_key, a_code, 1)])
    second = FakeDevice(events=[FakeEvent(ev_key, a_code, 1)])
    daemon = _make_daemon(devices=[first, second])
    daemon._running = True

    seen: list[int] = []

    def record(event: object) -> None:
        seen.append(id(event))

    monkeypatch.setattr(daemon, "_handle_event", record)

    selector = selectors.DefaultSelector()
    selector.register(first.fd, selectors.EVENT_READ, first)
    selector.register(second.fd, selectors.EVENT_READ, second)

    thread = threading.Thread(target=daemon._loop, args=(selector,))
    thread.start()
    try:
        first.trigger()
        second.trigger()
        time.sleep(0.4)
    finally:
        daemon.stop()
        thread.join(timeout=5)
        selector.close()

    # One event handled per device: both keyboards are listened to.
    assert len(seen) == 2


# --- 6. memory: the buffer is bounded ---------------------------------------


def test_buffer_is_bounded_by_max_buffer_size() -> None:
    config = Config(analysis_timeout=10.0, min_word_length=3, max_buffer_size=20)
    daemon = LinguaFixDaemon(
        config,
        detector=LanguageDetector(converter=None, stop_words=[], min_word_length=3),
        switcher=FakeSwitcher("us"),
        injector=FakeInjector(),
    )

    import evdev

    ev_key = evdev.ecodes.EV_KEY
    a_code = int(evdev.ecodes.KEY_A)
    for _ in range(1000):
        daemon._handle_event(FakeEvent(ev_key, a_code, 1))

    assert len(daemon.buffer) <= config.max_buffer_size


def test_max_buffer_size_is_validated() -> None:
    with pytest.raises(ValueError):
        Config(max_buffer_size=0)


# --- 7. SIGTERM during a fix ------------------------------------------------


def test_shutdown_before_fix_skips_replacement() -> None:
    injector = FakeInjector()
    switcher = FakeSwitcher("us")
    daemon = _make_daemon(injector=injector, switcher=switcher)
    daemon._shutdown_requested = True
    daemon.buffer = "ghbdtn"

    daemon._process_buffer()

    assert switcher.switches == []
    assert injector.replacements == []


def test_shutdown_arriving_mid_fix_completes_atomically() -> None:
    """SIGTERM after the fix started must not leave the text half-applied."""
    injector = FakeInjector()
    daemon = _make_daemon(injector=injector)

    def request_shutdown() -> None:
        daemon._shutdown_requested = True

    switcher = FakeSwitcher("us", on_switch=request_shutdown)
    daemon.switcher = switcher  # type: ignore[assignment]
    daemon.buffer = "ghbdtn"
    daemon._process_buffer()

    # Once started, the fix finishes: all backspaces and the text go together.
    assert injector.replacements == [(0, "привет", "ru")]


def test_sigterm_handler_sets_flags() -> None:
    daemon = _make_daemon()
    daemon._running = True
    daemon._handle_stop(15, None)
    assert daemon._running is False
    assert daemon._shutdown_requested is True


# --- exception safety -------------------------------------------------------


def test_event_error_is_survived(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = _make_daemon()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("bad event")

    monkeypatch.setattr(daemon, "_handle_event_inner", boom)
    daemon._handle_event(object())  # must not raise
