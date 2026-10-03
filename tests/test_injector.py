"""Tests for :mod:`linguafix.injector`."""

from __future__ import annotations

import subprocess
import sys
import types

import pytest

from linguafix import injector as injector_module
from linguafix.converter import LayoutConverter
from linguafix.injector import TextInjector


def fake_completed(returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["cmd"], returncode, "", "")


def test_backend_none_when_nothing_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(injector_module, "_which", lambda name: None)
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: False)
    injector = TextInjector(backend="auto")
    assert injector.backend == "none"


def test_backend_auto_prefers_uinput(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(injector_module, "_which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    assert TextInjector(backend="auto").backend == "uinput"


def test_backend_auto_falls_back_to_wtype(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        injector_module, "_which", lambda name: "/usr/bin/wtype" if name == "wtype" else None
    )
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: False)
    assert TextInjector(backend="auto").backend == "wtype"


def test_backend_auto_falls_back_to_xdotool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        injector_module, "_which", lambda name: "/usr/bin/xdotool" if name == "xdotool" else None
    )
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: False)
    assert TextInjector(backend="auto").backend == "xdotool"


def test_requested_backend_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(injector_module, "_which", lambda name: None)
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: False)
    assert TextInjector(backend="wtype").backend == "none"
    assert TextInjector(backend="xdotool").backend == "none"
    assert TextInjector(backend="uinput").backend == "none"


def test_replace_text_wtype(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        injector_module, "_which", lambda name: "/usr/bin/wtype" if name == "wtype" else None
    )
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: False)
    commands: list[list[str]] = []

    def record(cmd: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return fake_completed(0)

    monkeypatch.setattr(injector_module, "_run", record)
    injector = TextInjector(backend="auto")
    assert injector.replace_text("ghbdtn", "привет", "ru") is True
    assert commands.count(["wtype", "key", "BackSpace"]) == 6
    assert ["wtype", "-s", "0", "-d", "0", "привет"] in commands


def test_replace_text_xdotool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        injector_module, "_which", lambda name: "/usr/bin/xdotool" if name == "xdotool" else None
    )
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: False)
    commands: list[list[str]] = []

    def record(cmd: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        return fake_completed(0)

    monkeypatch.setattr(injector_module, "_run", record)
    injector = TextInjector(backend="auto")
    assert injector.replace_text("ab", "cd", "us") is True
    assert commands.count(["xdotool", "key", "BackSpace"]) == 2
    assert ["xdotool", "type", "--clearmodifiers", "cd"] in commands


def test_replace_text_no_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(injector_module, "_which", lambda name: None)
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: False)
    injector = TextInjector(backend="auto")
    assert injector.replace_text("a", "b", "us") is False


def test_replace_text_backspace_failure_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        injector_module, "_which", lambda name: "/usr/bin/xdotool" if name == "xdotool" else None
    )
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: False)
    monkeypatch.setattr(injector_module, "_run", lambda cmd, timeout=10.0: fake_completed(1))
    injector = TextInjector(backend="auto")
    assert injector.replace_text("ab", "cd", "us") is False


def test_replace_text_typing_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        injector_module, "_which", lambda name: "/usr/bin/xdotool" if name == "xdotool" else None
    )
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: False)
    calls = {"n": 0}

    def run(cmd: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
        calls["n"] += 1
        return fake_completed(0 if cmd[-1] == "BackSpace" else 1)

    monkeypatch.setattr(injector_module, "_run", run)
    injector = TextInjector(backend="auto")
    assert injector.replace_text("a", "b", "us") is False


def test_char_to_key_letters_and_shift() -> None:
    injector = TextInjector(converter=LayoutConverter(), backend="auto")
    assert injector._char_to_key("q", "us") == ("KEY_Q", False)
    assert injector._char_to_key("Q", "us") == ("KEY_Q", True)
    assert injector._char_to_key(" ", "us") == ("KEY_SPACE", False)
    assert injector._char_to_key("!", "us") == ("KEY_1", True)
    assert injector._char_to_key("й", "ru") == ("KEY_Q", False)
    assert injector._char_to_key("Й", "ru") == ("KEY_Q", True)
    assert injector._char_to_key("ж", "ru") == ("KEY_SEMICOLON", False)


def test_char_to_key_unknown_char() -> None:
    injector = TextInjector(converter=LayoutConverter(), backend="auto")
    assert injector._char_to_key("\u2603", "us") is None


def test_describe() -> None:
    injector = TextInjector(backend="auto")
    assert "backend=" in injector.describe()


# --- uinput backend with fake evdev/uinput modules --------------------------

_KNOWN_FAKE_KEYS = {
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


class _FakeEcodes:
    """Minimal ecodes namespace with the keys used by the injector."""

    EV_KEY = 1

    def __getattr__(self, name: str) -> int:
        if name in _KNOWN_FAKE_KEYS:
            return _KNOWN_FAKE_KEYS[name]
        if name.startswith("KEY_"):
            # Any other KEY_* resolves to a stable pseudo code.
            return abs(hash(name)) % 200 + 100
        raise AttributeError(name)


class _FakeUInputDevice:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.events: list[tuple[int, int, int]] = []
        self.synced = 0

    def __enter__(self) -> _FakeUInputDevice:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def write(self, event_type: int, code: int, value: int) -> None:
        self.events.append((event_type, code, value))

    def syn(self) -> None:
        self.synced += 1


@pytest.fixture
def fake_uinput(monkeypatch: pytest.MonkeyPatch) -> type[_FakeUInputDevice]:
    """Install fake ``evdev`` and ``uinput`` modules for the uinput backend."""
    fake_evdev = types.ModuleType("evdev")
    fake_evdev.ecodes = _FakeEcodes()
    fake_uinput_mod = types.ModuleType("uinput")
    fake_uinput_mod.UInput = _FakeUInputDevice
    fake_uinput_mod.KEY_A = 30
    monkeypatch.setitem(sys.modules, "evdev", fake_evdev)
    monkeypatch.setitem(sys.modules, "uinput", fake_uinput_mod)
    return _FakeUInputDevice


def test_type_uinput_emits_events(
    monkeypatch: pytest.MonkeyPatch, fake_uinput: type[_FakeUInputDevice]
) -> None:
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    injector = TextInjector(backend="uinput")
    assert injector._type_uinput("Qq ", "us") is True


def test_type_uinput_unknown_char_fails(
    monkeypatch: pytest.MonkeyPatch, fake_uinput: type[_FakeUInputDevice]
) -> None:
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    injector = TextInjector(backend="uinput")
    assert injector._type_uinput("\u2603", "us") is False


def test_uinput_tap(monkeypatch: pytest.MonkeyPatch, fake_uinput: type[_FakeUInputDevice]) -> None:
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    injector = TextInjector(backend="uinput")
    assert injector._uinput_tap("KEY_BACKSPACE", count=3) is True


def test_uinput_tap_unknown_key(
    monkeypatch: pytest.MonkeyPatch, fake_uinput: type[_FakeUInputDevice]
) -> None:
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    injector = TextInjector(backend="uinput")
    # A name that is not an evdev KEY_* attribute resolves to ``None``.
    assert injector._uinput_tap("NOT_A_KEY") is False


def test_replace_text_uinput(
    monkeypatch: pytest.MonkeyPatch, fake_uinput: type[_FakeUInputDevice]
) -> None:
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    injector = TextInjector(backend="uinput")
    assert injector.replace_text("gh", "привет", "ru") is True


def test_uinput_missing_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    monkeypatch.setitem(sys.modules, "evdev", None)
    injector = TextInjector(backend="uinput")
    assert injector._type_uinput("a", "us") is False
    assert injector._uinput_tap("KEY_A") is False


def test_uinput_batch_is_atomic(
    monkeypatch: pytest.MonkeyPatch, fake_uinput: type[_FakeUInputDevice]
) -> None:
    """Backspaces and the new text must be flushed with a single ``syn``.

    The kernel only delivers the batch once ``syn`` is called, so a crash before
    that point leaves the text untouched instead of half-deleted.
    """
    created: list[_FakeUInputDevice] = []

    class RecordingUInput(_FakeUInputDevice):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    fake_uinput_mod = sys.modules["uinput"]
    monkeypatch.setattr(fake_uinput_mod, "UInput", RecordingUInput)

    injector = TextInjector(backend="uinput")
    assert injector.replace_text("ghbdtn", "привет", "ru") is True

    assert len(created) == 1
    device = created[0]
    # Exactly one syn for the whole replacement: nothing is applied until then.
    assert device.synced == 1
    # Six backspaces (press + release each) precede the typed characters.
    backspaces = [e for e in device.events if e[1] == _KNOWN_FAKE_KEYS["KEY_BACKSPACE"]]
    assert len(backspaces) == 12


def test_uinput_batch_no_syn_means_nothing_applied(
    monkeypatch: pytest.MonkeyPatch, fake_uinput: type[_FakeUInputDevice]
) -> None:
    """If the batch fails before ``syn``, no key event is delivered."""

    class FailingUInput(_FakeUInputDevice):
        def write(self, event_type: int, code: int, value: int) -> None:
            super().write(event_type, code, value)
            if len(self.events) == 3:
                raise OSError("simulated crash mid-batch")

    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    fake_uinput_mod = sys.modules["uinput"]
    monkeypatch.setattr(fake_uinput_mod, "UInput", FailingUInput)

    injector = TextInjector(backend="uinput")
    assert injector.replace_text("ghbdtn", "привет", "ru") is False
