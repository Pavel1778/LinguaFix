"""Regression: the ``рhello`` truncation bug.

The user typed ``hello`` while the Russian layout was active, so the keys
produced ``руддщ``. LinguaFix replaced the text but left the first character
behind (``рhello``) because the number of Backspaces and the on-screen text had
drifted apart.

These tests pin the fix at two levels:

* the daemon tracks one scancode per typed character, so the Backspace count
  always equals the number of physical keys, and
* the uinput backend flushes the deletion, waits, then types the replacement,
  so an asynchronous compositor cannot race the deletion.
"""

from __future__ import annotations

from typing import Any, ClassVar

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
    """Records ``(backspace_count, new_text, layout)`` calls."""

    backend = "fake"

    def __init__(self) -> None:
        self.replacements: list[tuple[int, str, str]] = []

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


def _press(daemon: LinguaFixDaemon, key_names: list[str]) -> None:
    for name in key_names:
        code = int(getattr(evdev.ecodes, name))
        daemon._handle_event(type("E", (), {"type": EV_KEY, "code": code, "value": 1})())
        daemon._handle_event(type("E", (), {"type": EV_KEY, "code": code, "value": 0})())


def _daemon_with_fake_injector(settle_ms: int = 0) -> LinguaFixDaemon:
    config = Config(analysis_timeout=0.8, stop_words=[], backspace_settle_ms=settle_ms)
    detector = LanguageDetector(converter=None, stop_words=[], min_word_length=3)
    return LinguaFixDaemon(
        config,
        detector=detector,
        switcher=FakeSwitcher("ru"),
        injector=FakeInjector(),
    )


# --- the daemon sends exactly as many Backspaces as keys ---------------------


def test_backspace_count_equals_number_of_typed_keys() -> None:
    daemon = _daemon_with_fake_injector()
    _press(daemon, RU_WORD_KEYS)
    assert daemon.buffer == "руддщ"
    _press(daemon, ["KEY_SPACE"])

    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    # Five Backspaces for the five physical keys plus one for the triggering
    # Space, and the Space is retyped before "hello" so nothing is stranded.
    assert injector.replacements == [(6, "hello ", "us")]
    assert daemon.buffer == ""


def test_extra_keypress_is_included_in_the_count() -> None:
    """A stray key must not desynchronise the deletion from the screen.

    The scancode buffer is the source of truth: seven keys are seven Backspaces,
    even if a character-level buffer would have drifted.
    """
    daemon = _daemon_with_fake_injector()
    _press(daemon, ["KEY_H", "KEY_E", "KEY_L", "KEY_L", "KEY_O", "KEY_DOT"])
    assert daemon.buffer == "руддщю"
    _press(daemon, ["KEY_SPACE"])

    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    count, _new, _layout = injector.replacements[0]
    assert count == 7


def test_backspace_after_typing_reduces_the_count() -> None:
    daemon = _daemon_with_fake_injector()
    _press(daemon, ["KEY_H", "KEY_E", "KEY_L", "KEY_L", "KEY_O", "KEY_Q"])
    _press(daemon, ["KEY_BACKSPACE"])
    assert daemon.buffer == "руддщ"
    _press(daemon, ["KEY_SPACE"])

    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    # Five word keys plus the triggering Space, which is retyped before "hello".
    assert injector.replacements == [(6, "hello ", "us")]


# --- the uinput backend emits the right events -------------------------------


def test_uinput_emits_five_backspaces_and_five_letters(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingUInput.instances.clear()
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    monkeypatch.setattr(evdev, "UInput", RecordingUInput)

    injector = TextInjector(backend="uinput")
    assert injector.replace_text(5, "hello", "us") is True

    assert len(RecordingUInput.instances) == 2
    backspace_device, text_device = RecordingUInput.instances

    # The deletion is a complete, self-contained batch: five Backspaces
    # (press + release each) and one syn.
    assert backspace_device.presses == [(EV_KEY, BACKSPACE, 1)] * 5
    assert backspace_device.synced == 1

    # The replacement is exactly the five letters of "hello" (no Shift for
    # lowercase), flushed with its own syn.
    letters = [code for _etype, code, _value in text_device.presses]
    assert letters == [
        int(evdev.ecodes.KEY_H),
        int(evdev.ecodes.KEY_E),
        int(evdev.ecodes.KEY_L),
        int(evdev.ecodes.KEY_L),
        int(evdev.ecodes.KEY_O),
    ]
    assert text_device.synced == 1
    assert not any(code == BACKSPACE for _etype, code, _value in text_device.written)


def test_backspace_batch_is_flushed_before_the_text_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deletion must be flushed before the replacement is written."""
    RecordingUInput.instances.clear()
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    monkeypatch.setattr(evdev, "UInput", RecordingUInput)

    injector = TextInjector(backend="uinput", settle_ms=0)
    assert injector.replace_text(5, "hello", "us") is True

    backspace_device, text_device = RecordingUInput.instances
    assert backspace_device.synced == 1
    assert text_device.synced == 1
    # The text device is created only after the backspace batch was flushed.
    assert RecordingUInput.instances.index(backspace_device) < RecordingUInput.instances.index(
        text_device
    )


def test_settle_delay_is_applied_between_the_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    """``backspace_settle_ms`` becomes a sleep between the two flushes."""
    RecordingUInput.instances.clear()
    sleeps: list[float] = []

    def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    monkeypatch.setattr(evdev, "UInput", RecordingUInput)
    monkeypatch.setattr("linguafix.injector.time.sleep", record_sleep)

    injector = TextInjector(backend="uinput", settle_ms=30)
    assert injector.replace_text(5, "hello", "us") is True

    assert 0.03 in sleeps


def test_zero_settle_delay_does_not_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingUInput.instances.clear()
    sleeps: list[float] = []

    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    monkeypatch.setattr(evdev, "UInput", RecordingUInput)
    monkeypatch.setattr("linguafix.injector.time.sleep", sleeps.append)

    injector = TextInjector(backend="uinput", settle_ms=0)
    assert injector.replace_text(5, "hello", "us") is True
    assert sleeps == []


def test_daemon_passes_settle_ms_to_the_injector() -> None:
    config = Config(backspace_settle_ms=45)
    daemon = LinguaFixDaemon(config, switcher=FakeSwitcher("us"), injector=None)
    injector: Any = daemon.injector
    assert injector._settle_ms == 45


# --- end to end: daemon drives the real uinput injector ----------------------


def test_daemon_with_real_uinput_injector_emits_exact_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typing "руддщ" + Space emits exactly 5 Backspaces and the 5 letters.

    This wires the daemon to the *real* ``TextInjector`` (with a fake
    ``evdev.UInput``) so the whole path — scancode buffer, boundary trigger,
    backspace count and uinput batch — is exercised together.
    """
    RecordingUInput.instances.clear()
    monkeypatch.setattr(TextInjector, "_uinput_available", lambda self: True)
    monkeypatch.setattr(evdev, "UInput", RecordingUInput)
    monkeypatch.setattr("linguafix.injector.time.sleep", lambda _seconds: None)

    config = Config(analysis_timeout=0.8, stop_words=[], backspace_settle_ms=30)
    daemon = LinguaFixDaemon(
        config,
        detector=LanguageDetector(converter=None, stop_words=[], min_word_length=3),
        switcher=FakeSwitcher("ru"),
    )
    _press(daemon, RU_WORD_KEYS)
    _press(daemon, ["KEY_SPACE"])

    assert len(RecordingUInput.instances) == 2
    backspace_device, text_device = RecordingUInput.instances
    # Six Backspaces: the five word keys and the triggering Space.
    assert backspace_device.presses == [(EV_KEY, BACKSPACE, 1)] * 6
    assert backspace_device.synced == 1
    assert text_device.synced == 1
    # The Space is retyped last, after "hello".
    assert [code for _etype, code, _value in text_device.presses] == [
        int(evdev.ecodes.KEY_H),
        int(evdev.ecodes.KEY_E),
        int(evdev.ecodes.KEY_L),
        int(evdev.ecodes.KEY_L),
        int(evdev.ecodes.KEY_O),
        int(evdev.ecodes.KEY_SPACE),
    ]
    assert daemon.buffer == ""


def test_separator_token_is_not_rewritten() -> None:
    """A word joined to another by a separator is left untouched."""
    daemon = _daemon_with_fake_injector()
    # "vfibyf-rjynhjkm" would convert to "машина-контроль"; the hyphen means it
    # is a compound token and must not be rewritten.
    _press(daemon, ["KEY_V", "KEY_F", "KEY_I", "KEY_B", "KEY_Y", "KEY_F"])
    _press(daemon, ["KEY_MINUS"])
    _press(daemon, ["KEY_R", "KEY_J", "KEY_Y", "KEY_N", "KEY_H", "KEY_J", "KEY_K", "KEY_M"])
    _press(daemon, ["KEY_SPACE"])

    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    assert injector.replacements == []
