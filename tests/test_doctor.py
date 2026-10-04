"""Tests for :mod:`linguafix.doctor`."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from linguafix import doctor
from linguafix.config import Config


def test_marker_mapping_covers_statuses() -> None:
    assert set(doctor._MARKER) == {doctor.OK, doctor.WARN, doctor.FAIL}


def test_session_type_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "Wayland")
    assert doctor._session_type() == "wayland"
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    assert doctor._session_type() == "unknown"


def test_gnome_version_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: "/usr/bin/gnome-shell")
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "GNOME Shell 43.6\n", ""),
    )
    assert doctor._gnome_major_version() == 43


def test_gnome_version_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    assert doctor._gnome_major_version() is None


def test_check_gnome_version_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_gnome_major_version", lambda: 43)
    result = doctor.check_gnome_version()
    assert result.status == doctor.OK


def test_check_gnome_version_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_gnome_major_version", lambda: 50)
    result = doctor.check_gnome_version()
    assert result.status == doctor.WARN
    assert result.hint


def test_check_gnome_version_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_gnome_major_version", lambda: None)
    assert doctor.check_gnome_version().status == doctor.WARN


def test_check_device_access_uaccess(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_uaccess_rule_present", lambda: True)
    monkeypatch.setattr(doctor, "_input_group_membership", lambda: False)
    result = doctor.check_device_access()
    assert result.status == doctor.OK
    assert "uaccess" in result.detail


def test_check_device_access_input_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_uaccess_rule_present", lambda: False)
    monkeypatch.setattr(doctor, "_input_group_membership", lambda: True)
    assert doctor.check_device_access().status == doctor.OK


def test_check_device_access_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_uaccess_rule_present", lambda: False)
    monkeypatch.setattr(doctor, "_input_group_membership", lambda: False)
    result = doctor.check_device_access()
    assert result.status == doctor.FAIL
    assert "71-linguafix.rules" in result.hint
    assert ".deb" in result.hint


def test_uaccess_rule_present_true(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rule = tmp_path / "71-linguafix.rules"
    rule.write_text('KERNEL=="event*", TAG+="uaccess"\n', encoding="utf-8")
    monkeypatch.setattr(doctor, "_UDEV_RULE_DIRS", (tmp_path,))
    assert doctor._uaccess_rule_present() is True


def test_uaccess_rule_present_false_for_group_rule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rule = tmp_path / "71-linguafix.rules"
    rule.write_text('KERNEL=="event*", GROUP="input", MODE="0660"\n', encoding="utf-8")
    monkeypatch.setattr(doctor, "_UDEV_RULE_DIRS", (tmp_path,))
    assert doctor._uaccess_rule_present() is False


def test_uaccess_rule_present_no_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(doctor, "_UDEV_RULE_DIRS", (tmp_path,))
    assert doctor._uaccess_rule_present() is False


def test_check_event_devices_none_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_readable_event_devices", lambda: (0, 0))
    assert doctor.check_event_devices().status == doctor.WARN


def test_check_event_devices_unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_readable_event_devices", lambda: (0, 5))
    result = doctor.check_event_devices()
    assert result.status == doctor.FAIL
    assert "udev" in result.hint


def test_check_event_devices_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_readable_event_devices", lambda: (5, 5))
    assert doctor.check_event_devices().status == doctor.OK


def test_check_uinput_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    monkeypatch.setattr(doctor, "Path", lambda _p: _FakePath(exists=False, writable=False))
    assert doctor.check_uinput().status == doctor.WARN


class _FakePath:
    def __init__(self, exists: bool, writable: bool) -> None:
        self._exists = exists
        self._writable = writable

    def exists(self) -> bool:
        return self._exists


def test_check_uinput_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "Path", lambda _p: _FakePath(exists=True, writable=True))
    monkeypatch.setattr(doctor.os, "access", lambda *_a: True)
    assert doctor.check_uinput().status == doctor.OK


def test_check_tools_all_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
    result = doctor.check_tools()
    assert result.status == doctor.FAIL


def test_check_tools_layout_ok_but_no_injector(monkeypatch: pytest.MonkeyPatch) -> None:
    available = {"g3kb-switch": "/usr/bin/g3kb-switch"}
    monkeypatch.setattr(doctor.shutil, "which", lambda name: available.get(name))
    result = doctor.check_tools()
    assert result.status == doctor.WARN


def test_check_tools_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert doctor.check_tools().status == doctor.OK


def test_render_includes_hint_for_failures() -> None:
    results = [
        doctor.CheckResult("A", doctor.OK, "fine"),
        doctor.CheckResult("B", doctor.FAIL, "broken", "fix it"),
    ]
    text = doctor.render(results)
    assert "✅" in text
    assert "❌" in text
    assert "↳ fix it" in text


def test_has_failures() -> None:
    assert doctor.has_failures([doctor.CheckResult("A", doctor.FAIL, "")])
    assert not doctor.has_failures([doctor.CheckResult("A", doctor.WARN, "")])


def test_run_doctor_returns_zero_when_clean(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        doctor, "collect_checks", lambda _c=None: [doctor.CheckResult("A", doctor.OK, "ok")]
    )
    assert doctor.run_doctor(Config()) == 0
    assert "критических проблем не найдено" in capsys.readouterr().out


def test_run_doctor_returns_one_on_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        doctor, "collect_checks", lambda _c=None: [doctor.CheckResult("A", doctor.FAIL, "no")]
    )
    assert doctor.run_doctor(Config()) == 1
    assert "есть проблемы" in capsys.readouterr().out


def test_collect_checks_runs_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "_uaccess_rule_present", lambda: True)
    monkeypatch.setattr(doctor, "_readable_event_devices", lambda: (2, 2))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(doctor, "_gnome_major_version", lambda: 43)
    results = doctor.collect_checks(Config())
    names = [r.name for r in results]
    assert "Тип сессии" in names
    assert "Конфигурация" in names
    assert len(results) >= 8
