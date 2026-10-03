"""Tests for :mod:`linguafix.collect_logs`."""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path

import pytest

from linguafix import collect_logs as cl
from linguafix.config import Config

EXPECTED_MEMBERS = {
    cl.README_TXT,
    cl.DOCTOR_TXT,
    cl.CONFIG_TOML,
    cl.DAEMON_LOG,
    cl.JOURNAL_TXT,
    cl.ENV_TXT,
    cl.DEVICES_TXT,
    cl.PACKAGES_TXT,
}


@pytest.fixture()
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point config/state directories at a temporary tree."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path


def test_run_never_raises_on_missing_binary() -> None:
    output = cl._run(["definitely-not-a-real-binary-xyz"])
    assert "failed to run" in output


def test_run_captures_output() -> None:
    output = cl._run(["bash", "-c", "echo hello"])
    assert "hello" in output


def test_tail_missing_file(tmp_path: Path) -> None:
    assert "does not exist" in cl._tail(tmp_path / "nope.log", 10)


def test_tail_returns_last_lines(tmp_path: Path) -> None:
    path = tmp_path / "x.log"
    path.write_text("\n".join(f"line{i}" for i in range(100)), encoding="utf-8")
    tail = cl._tail(path, 5)
    assert "line99" in tail
    assert "line0" not in tail
    assert len(tail.strip().splitlines()) == 5


def test_doctor_text_contains_table() -> None:
    text = cl.doctor_text(Config())
    assert "LinguaFix doctor" in text
    assert "Тип сессии" in text


def test_config_text_when_missing(isolated_state: Path) -> None:
    assert "does not exist" in cl.config_text()


def test_config_text_when_present(isolated_state: Path) -> None:
    from linguafix.config import save_config

    save_config(Config())
    assert "analysis_timeout" in cl.config_text()


def test_env_text_has_session_line() -> None:
    text = cl.env_text()
    assert "XDG_SESSION_TYPE" in text
    assert "kernel:" in text


def test_devices_text_lists_patterns() -> None:
    text = cl.devices_text()
    assert "/dev/input/event*" in text
    assert "/dev/uinput" in text


def test_packages_text_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cl, "_run", lambda *_a, **_k: "python3-evdev 1.6.1\n")
    assert "evdev" in cl.packages_text()


def test_packages_text_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cl, "_run", lambda *_a, **_k: "")
    assert "no matching packages" in cl.packages_text()


def test_collect_logs_creates_archive(isolated_state: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    archive = cl.collect_logs(out, config=Config())
    assert archive.exists()
    assert archive.name.startswith("linguafix-logs-")
    assert archive.suffixes[-2:] == [".tar", ".gz"]


def test_archive_contains_all_sections(isolated_state: Path, tmp_path: Path) -> None:
    archive = cl.collect_logs(tmp_path, config=Config())
    with tarfile.open(archive, "r:gz") as tar:
        names = set(tar.getnames())
    assert names == EXPECTED_MEMBERS


def test_archive_has_no_typed_text(isolated_state: Path, tmp_path: Path) -> None:
    """The bundle must never contain typed characters."""
    from linguafix.config import state_dir

    log_dir = state_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / cl.LOG_FILE_NAME).write_text(
        "2026-01-01 INFO linguafix.daemon: buffer=8 chars us -> ru\n",
        encoding="utf-8",
    )
    archive = cl.collect_logs(tmp_path, config=Config())
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.extractfile(cl.DAEMON_LOG)
        assert member is not None
        content = member.read().decode("utf-8")
    assert "buffer=8 chars" in content


def test_collect_logs_creates_output_dir(isolated_state: Path, tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    archive = cl.collect_logs(nested, config=Config())
    assert archive.parent == nested


def test_readme_explains_privacy(isolated_state: Path, tmp_path: Path) -> None:
    archive = cl.collect_logs(tmp_path, config=Config())
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.extractfile(cl.README_TXT)
        assert member is not None
        assert "no typed text" in member.read().decode("utf-8")


def test_journal_text_handles_missing_journalctl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cl,
        "_run",
        lambda *_a, **_k: "<failed to run journalctl: FileNotFoundError>\n",
    )
    assert "failed to run" in cl.journal_text()


def test_subprocess_never_uses_shell_for_direct_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.setattr(cl.subprocess, "run", fake_run)
    cl._run(["journalctl", "--user"])
    argv, kwargs = captured[0]
    assert argv == ["journalctl", "--user"]
    assert "shell" not in kwargs
    assert kwargs["check"] is False
