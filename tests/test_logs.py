"""``linguafix logs`` reads the daemon log file (metadata only, never text)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from linguafix.logs import log_file_path, read_tail


def _write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "linguafix.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_read_tail_returns_last_lines(tmp_path: Path) -> None:
    path = _write(tmp_path, [f"line {i}" for i in range(100)])
    assert read_tail(path, 3) == ["line 97", "line 98", "line 99"]


def test_read_tail_filters_by_level(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            "2026-10-08 12:00:00 INFO     linguafix.daemon: started",
            "2026-10-08 12:00:01 DEBUG    linguafix.daemon: flushing",
            "2026-10-08 12:00:02 ERROR    linguafix.daemon: boom",
        ],
    )
    assert read_tail(path, 10, level="DEBUG") == [
        "2026-10-08 12:00:01 DEBUG    linguafix.daemon: flushing"
    ]


def test_read_tail_missing_file_is_empty(tmp_path: Path) -> None:
    assert read_tail(tmp_path / "nope.log", 10) == []


def test_log_file_path_is_under_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert log_file_path() == tmp_path / "linguafix" / "linguafix.log"


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = iter(lines)

    def __iter__(self) -> Iterator[str]:
        return self._lines


class _FakePopen:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.stdout = _FakeStdout(["INFO a\n", "ERROR b\n"])
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self) -> int:
        return 0


def test_follow_streams_and_filters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from linguafix import logs

    monkeypatch.setattr(logs.subprocess, "Popen", _FakePopen)
    rc = logs.follow(Path("/tmp/x.log"), 10, level="ERROR")
    assert rc == 0
    assert capsys.readouterr().out == "ERROR b\n"


def test_follow_returns_one_when_tail_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from linguafix import logs

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("no tail")

    monkeypatch.setattr(logs.subprocess, "Popen", _boom)
    assert logs.follow(Path("/tmp/x.log"), 5) == 1
