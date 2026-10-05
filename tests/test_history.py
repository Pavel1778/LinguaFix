"""The correction history: metadata only, bounded, and undoable.

The history must never contain the typed text — only the word length, the
layouts and a timestamp — so these tests assert both the behaviour and the
privacy invariant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest

evdev = pytest.importorskip("evdev")

from linguafix import daemon_control  # noqa: E402
from linguafix.config import Config  # noqa: E402
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


def test_history_records_metadata_after_a_fix() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    snapshot = daemon.history_snapshot()
    assert len(snapshot) == 1
    entry = snapshot[0]
    assert entry["length"] == 6
    assert entry["source"] == "us"
    assert entry["target"] == "ru"
    assert entry["undone"] is False
    assert isinstance(entry["at"], float)


def test_history_never_contains_the_typed_text() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    for entry in daemon.history_snapshot():
        for value in entry.values():
            assert "ghbdtn" not in str(value)
            assert "привет" not in str(value)


def test_history_is_bounded_by_history_size() -> None:
    daemon = make_daemon(history_size=3)
    for index in range(5):
        daemon._record_undo(f"word{index}", "us", 4, source="us", target="ru")
    assert len(daemon.history_snapshot()) == 3


def test_history_newest_first() -> None:
    daemon = make_daemon()
    daemon._record_undo("first", "us", 4, source="us", target="ru")
    first = cast(int, daemon.history_snapshot()[0]["id"])
    daemon._record_undo("second", "us", 4, source="us", target="ru")
    snapshot = daemon.history_snapshot()
    assert cast(int, snapshot[0]["id"]) != first
    assert cast(int, snapshot[0]["id"]) > cast(int, snapshot[1]["id"])


def test_undo_marks_the_history_row() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert daemon._undo_last_fix() is True
    assert daemon.history_snapshot()[0]["undone"] is True


def test_undo_with_stale_id_is_refused() -> None:
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    stale = cast(int, daemon.history_snapshot()[0]["id"]) - 99
    assert daemon._undo_last_fix(entry_id=stale) is False
    # The real entry is still undoable.
    assert daemon._undo_last_fix() is True


def test_history_snapshot_is_written_metadata_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    daemon = make_daemon()
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    daemon._write_history_snapshot()
    path = daemon_control.cache_dir() / "history.json"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "ghbdtn" not in text
    assert "привет" not in text
    assert daemon_control.read_history()[0]["length"] == 6


def test_read_history_missing_file_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert daemon_control.read_history() == []


def test_request_history_without_daemon_is_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert daemon_control.request_history() is False
