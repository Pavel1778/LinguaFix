"""Tests for the GUI's ``systemctl --user`` bridge."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from linguafix.gui import systemd_bridge


class _Result:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


class _FakeRun:
    """Callable that records argv and returns a canned result or raises."""

    def __init__(self, returncode: int = 0, stdout: str = "", exc: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self._returncode = returncode
        self._stdout = stdout
        self._exc = exc

    def __call__(self, argv: list[str], **_kwargs: Any) -> _Result:
        self.calls.append(argv)
        if self._exc is not None:
            raise self._exc
        return _Result(self._returncode, self._stdout)


def _fake_run(returncode: int = 0, stdout: str = "", exc: Exception | None = None) -> _FakeRun:
    return _FakeRun(returncode, stdout, exc)


def test_is_service_active_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(systemd_bridge.subprocess, "run", _fake_run(0, "active\n"))
    assert systemd_bridge.is_service_active() is True


def test_is_service_active_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(systemd_bridge.subprocess, "run", _fake_run(3, "inactive\n"))
    assert systemd_bridge.is_service_active() is False


def test_is_service_enabled_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(systemd_bridge.subprocess, "run", _fake_run(0, "enabled\n"))
    assert systemd_bridge.is_service_enabled() is True


def test_start_and_stop_use_expected_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake_run(0)
    monkeypatch.setattr(systemd_bridge.subprocess, "run", fake)
    assert systemd_bridge.start_service() is True
    assert systemd_bridge.stop_service() is True
    assert systemd_bridge.enable_autostart() is True
    assert systemd_bridge.disable_autostart() is True
    assert systemd_bridge.reload_service() is True
    assert fake.calls[0] == ["systemctl", "--user", "start", "linguafix.service"]
    assert fake.calls[1] == ["systemctl", "--user", "stop", "linguafix.service"]
    assert fake.calls[2] == ["systemctl", "--user", "enable", "linguafix.service"]
    assert fake.calls[3] == ["systemctl", "--user", "disable", "linguafix.service"]
    assert fake.calls[4] == ["systemctl", "--user", "reload-or-restart", "linguafix.service"]


def test_file_not_found_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        systemd_bridge.subprocess, "run", _fake_run(exc=FileNotFoundError("no systemctl"))
    )
    assert systemd_bridge.start_service() is False
    assert systemd_bridge.is_service_active() is False


def test_timeout_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        systemd_bridge.subprocess,
        "run",
        _fake_run(exc=subprocess.TimeoutExpired("systemctl", 5)),
    )
    assert systemd_bridge.stop_service() is False
    assert systemd_bridge.is_service_enabled() is False


def test_oserror_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(systemd_bridge.subprocess, "run", _fake_run(exc=OSError("boom")))
    assert systemd_bridge.reload_service() is False


def test_nonzero_exit_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(systemd_bridge.subprocess, "run", _fake_run(1))
    assert systemd_bridge.start_service() is False
