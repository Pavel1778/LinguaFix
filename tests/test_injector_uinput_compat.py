"""Regression tests for the uinput backend on Debian 12 and Debian 13.

Debian 13 (trixie) ships ``python-uinput`` 1.0.1, whose ``KEY_*`` constants are
``(event_type, code)`` tuples and whose public API is ``Device``/``emit``.
Debian 12 (bookworm) ships 0.11.2, whose ``KEY_*`` constants are also tuples.
The injector must therefore never read key codes from the ``uinput`` package;
it uses ``evdev.ecodes`` for key codes and ``evdev.UInput`` for the device.

These tests pin that contract so a future refactor cannot reintroduce the
``int(uinput.KEY_A)`` crash.
"""

from __future__ import annotations

import sys
import types
from typing import Any, ClassVar

import pytest

from linguafix.converter import LayoutConverter
from linguafix.injector import TextInjector

# Real evdev key codes (the values are stable kernel ABI constants).
_ECODES = {
    "EV_KEY": 1,
    "KEY_LEFTSHIFT": 42,
    "KEY_BACKSPACE": 14,
    "KEY_Q": 16,
    "KEY_A": 30,
    "KEY_Z": 44,
    "KEY_1": 2,
    "KEY_SPACE": 57,
    "KEY_SEMICOLON": 39,
    "KEY_ENTER": 28,
    "KEY_G": 34,
    "KEY_H": 35,
    "KEY_PRINT": 210,
}


class _Ecodes:
    EV_KEY = 1

    def __getattr__(self, name: str) -> int:
        if name in _ECODES:
            return _ECODES[name]
        if name.startswith("KEY_"):
            return abs(hash(name)) % 200 + 100
        raise AttributeError(name)


class _RecordingUInput:
    """Stand-in for ``evdev.UInput`` that records the events it is asked to emit."""

    instances: ClassVar[list[Any]] = []

    def __init__(self, events: object, name: str = "linguafix") -> None:
        self.events_arg = events
        self.name = name
        self.written: list[tuple[int, int, int]] = []
        self.synced = 0
        _RecordingUInput.instances.append(self)

    def write(self, event_type: int, code: int, value: int) -> None:
        self.written.append((event_type, code, value))

    def syn(self) -> None:
        self.synced += 1

    def close(self) -> None:
        return None


def _install_env(monkeypatch: pytest.MonkeyPatch, key_a: object) -> None:
    """Install a fake evdev and a uinput whose ``KEY_A`` has the given shape."""
    _RecordingUInput.instances.clear()

    fake_evdev = types.ModuleType("evdev")
    fake_evdev.ecodes = _Ecodes()
    fake_evdev.UInput = _RecordingUInput
    monkeypatch.setitem(sys.modules, "evdev", fake_evdev)

    # A realistic python-uinput module: KEY_* may be a tuple and there is no
    # UInput attribute (Debian exposes Device instead).
    fake_uinput = types.ModuleType("uinput")
    fake_uinput.KEY_A = key_a
    monkeypatch.setitem(sys.modules, "uinput", fake_uinput)

    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)


@pytest.mark.parametrize("key_a", [(1, 30), 30], ids=["tuple-debian13", "int-legacy"])
def test_type_uinput_works_regardless_of_uinput_key_shape(
    monkeypatch: pytest.MonkeyPatch, key_a: object
) -> None:
    """Typing must work whether ``uinput.KEY_A`` is a tuple or an int."""
    _install_env(monkeypatch, key_a)
    injector = TextInjector(converter=LayoutConverter(), backend="uinput")

    assert injector._type_uinput("Qq ", "us") is True
    assert injector.replace_text(2, "привет", "ru") is True

    device = _RecordingUInput.instances[-1]
    # Every emitted code is a plain int, never a tuple.
    assert all(isinstance(code, int) for _etype, code, _value in device.written)


def test_uinput_never_reads_key_codes_from_uinput_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A poisoned ``uinput`` module must not break the backend.

    ``uinput.KEY_A`` is a tuple and ``uinput`` has no ``UInput``; if the injector
    touched either, this test would raise instead of succeeding.
    """
    _install_env(monkeypatch, (1, 30))
    injector = TextInjector(converter=LayoutConverter(), backend="uinput")

    assert injector._type_uinput("a", "us") is True
    assert injector._uinput_batch(1, "b", "us") is True
    assert injector._uinput_tap("KEY_BACKSPACE") is True


def test_uinput_capabilities_use_evdev_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The device must be created with ``{EV_KEY: [int, ...]}`` capabilities."""
    _install_env(monkeypatch, (1, 30))
    injector = TextInjector(converter=LayoutConverter(), backend="uinput")
    assert injector._type_uinput("q", "us") is True

    device = _RecordingUInput.instances[-1]
    assert isinstance(device.events_arg, dict)
    assert list(device.events_arg) == [1]  # EV_KEY
    codes = device.events_arg[1]
    assert codes == sorted(codes)
    assert all(isinstance(code, int) for code in codes)
    assert _ECODES["KEY_Q"] in codes
