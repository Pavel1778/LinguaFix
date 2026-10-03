"""Doctor behaviour in a session-less environment (TTY, ssh, cron).

A tester may run ``linguafix doctor`` from a context that has no graphical
session: no ``XDG_SESSION_TYPE``, no ``DISPLAY``/``WAYLAND_DISPLAY``, no D-Bus.
These tests pin the behaviour: doctor must not crash, must say the session type
is unknown, and must not blow up on a missing ``systemctl``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from linguafix import doctor
from linguafix.config import Config

# Variables that describe a graphical session. Clearing them makes the process
# look like it was started from a TTY, ssh or cron.
_SESSION_VARS = (
    "XDG_SESSION_TYPE",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_CURRENT_DESKTOP",
)


@pytest.fixture
def headless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every graphical-session variable from the environment."""
    for name in _SESSION_VARS:
        monkeypatch.delenv(name, raising=False)


def test_session_type_is_unknown_when_unset(headless: None) -> None:
    assert doctor._session_type() == "unknown"


def test_check_backends_marks_unknown_session_as_warning(
    headless: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    results = doctor.check_backends(Config())
    session = next(r for r in results if r.name == "Тип сессии")
    assert session.status == doctor.WARN
    assert "unknown" in session.detail
    assert "сесси" in session.hint


def test_check_backends_ok_with_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    results = doctor.check_backends(Config())
    session = next(r for r in results if r.name == "Тип сессии")
    assert session.status == doctor.OK
    assert session.detail == "wayland"


def test_run_doctor_does_not_crash_without_session(
    headless: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole command must return a code, not raise."""
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    monkeypatch.setattr(doctor, "_readable_event_devices", lambda: (0, 0))
    code = doctor.run_doctor(Config())
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert "unknown" in out
    assert "Итог:" in out


def test_run_doctor_survives_missing_systemctl(
    headless: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing binary must not crash doctor.

    ``subprocess.run`` with ``check=False`` still raises ``FileNotFoundError``
    when the executable is absent, so doctor must guard every call. Force the
    GNOME probe to attempt a subprocess and make it fail.
    """
    calls: list[list[str]] = []

    def _record(argv: list[str], *_args: object, **_kwargs: object) -> object:
        calls.append(list(argv))
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gnome-shell")
    monkeypatch.setattr(doctor.subprocess, "run", _record)
    code = doctor.run_doctor(Config())
    assert code in (0, 1)
    out = capsys.readouterr().out
    assert out
    assert calls, "the GNOME probe should have attempted a subprocess"
    assert "не удалось определить" in out
    assert not any("systemctl" in argv[0] for argv in calls if argv)


def test_doctor_from_empty_environment() -> None:
    """End-to-end: clear the environment and run doctor as a subprocess."""
    import subprocess
    import sys

    env = {
        "HOME": os.environ.get("HOME", "/tmp"),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    src = str(Path(__file__).resolve().parent.parent / "src")
    env["PYTHONPATH"] = src
    result = subprocess.run(
        [sys.executable, "-m", "linguafix", "doctor"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert result.returncode in (0, 1)
    assert "Traceback" not in result.stderr
    assert "LinguaFix doctor" in result.stdout
    assert "unknown" in result.stdout
