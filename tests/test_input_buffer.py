"""Input buffering: keys typed during a replacement are not lost.

A fix runs on the event-loop thread and sleeps between the Backspace batch and
the new text (``backspace_settle_ms``). Keys pressed in that window used to be
dropped because the loop was busy. They are now queued and replayed once the
replacement finishes, against the corrected screen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import Config  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector  # noqa: E402

EV_KEY = int(evdev.ecodes.EV_KEY)


@dataclass
class FakeEvent:
    type: int
    code: int
    value: int


class FakeSwitcher:
    backend = "fake"

    def __init__(self, current: str = "us") -> None:
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

    def __init__(self, on_replace: Callable[[], None] | None = None) -> None:
        self.replacements: list[tuple[int, str, str]] = []
        self.on_replace = on_replace

    def can_type(self, char: str, layout: str) -> bool:
        return char == " "

    def replace_text(self, backspace_count: int, new: str, layout: str) -> bool:
        self.replacements.append((backspace_count, new, layout))
        if self.on_replace is not None:
            self.on_replace()
        return True

    def describe(self) -> str:
        return "backend=fake"


def _make_daemon(injector: FakeInjector) -> LinguaFixDaemon:
    config = Config(analysis_timeout=0.1, min_word_length=3, stop_words=[], on_space=True)
    return LinguaFixDaemon(
        config,
        detector=LanguageDetector(converter=None, stop_words=[], min_word_length=3),
        switcher=FakeSwitcher("us"),
        injector=injector,
    )


def _event(name: str, value: int = 1) -> FakeEvent:
    return FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), value)


def _type(daemon: LinguaFixDaemon, names: list[str]) -> None:
    for name in names:
        daemon._handle_event(_event(name, 1))
        daemon._handle_event(_event(name, 0))


def test_key_typed_during_fix_is_replayed() -> None:
    """A key pressed while the replacement runs lands in the buffer afterwards."""
    daemon_ref: dict[str, LinguaFixDaemon] = {}

    def type_during_fix() -> None:
        # The user hits ``x`` between the backspaces and the injected text.
        daemon_ref["daemon"]._handle_event(_event("KEY_X", 1))
        daemon_ref["daemon"]._handle_event(_event("KEY_X", 0))

    injector = FakeInjector(on_replace=type_during_fix)
    daemon = _make_daemon(injector)
    daemon_ref["daemon"] = daemon

    _type(daemon, ["KEY_G", "KEY_H", "KEY_B", "KEY_D", "KEY_T", "KEY_N"])
    assert daemon.buffer == "ghbdtn"

    daemon._process_buffer(boundary=True, boundary_char=" ")

    assert injector.replacements == [(7, "привет ", "ru")]
    # The key queued during the fix was replayed, not dropped. After the fix the
    # ru layout is active, so the physical KEY_X now produces ``ч``.
    assert daemon.buffer == "ч"
    assert daemon._deferred_events == []


def test_events_are_queued_while_processing() -> None:
    """``_handle_event`` defers instead of processing while a fix is in flight."""
    daemon = _make_daemon(FakeInjector())
    daemon._processing_buffer = True

    daemon._handle_event(_event("KEY_X", 1))

    assert daemon.buffer == ""
    assert len(daemon._deferred_events) == 1

    daemon._processing_buffer = False
    daemon._replay_deferred_events()
    assert daemon.buffer == "x"
    assert daemon._deferred_events == []


def test_deferred_queue_is_bounded() -> None:
    """A held key cannot grow the deferred queue without bound."""
    from linguafix.daemon import _MAX_DEFERRED_EVENTS

    daemon = _make_daemon(FakeInjector())
    daemon._processing_buffer = True
    for _ in range(_MAX_DEFERRED_EVENTS + 20):
        daemon._handle_event(_event("KEY_X", 1))

    assert len(daemon._deferred_events) == _MAX_DEFERRED_EVENTS
