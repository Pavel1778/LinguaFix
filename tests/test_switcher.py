"""Tests for :mod:`linguafix.switcher`."""

from __future__ import annotations

import subprocess

import pytest

from linguafix import switcher as switcher_module
from linguafix.switcher import LayoutSwitcher


def fake_completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["cmd"], returncode, stdout, "")


def test_backend_auto_prefers_g3kb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        switcher_module,
        "_which",
        lambda name: f"/usr/bin/{name}" if name == "g3kb-switch" else None,
    )
    switcher = LayoutSwitcher(["us", "ru"], "auto", session_type="wayland")
    assert switcher.backend == "g3kb-switch"


def test_backend_auto_uses_setxkbmap_on_x11(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        switcher_module, "_which", lambda name: f"/usr/bin/{name}" if name == "setxkbmap" else None
    )
    switcher = LayoutSwitcher(["us", "ru"], "auto", session_type="x11")
    assert switcher.backend == "setxkbmap"


def test_backend_auto_none_on_wayland_without_g3kb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        switcher_module, "_which", lambda name: f"/usr/bin/{name}" if name == "setxkbmap" else None
    )
    switcher = LayoutSwitcher(["us", "ru"], "auto", session_type="wayland")
    assert switcher.backend == "none"


def test_requested_backend_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: None)
    assert LayoutSwitcher(["us", "ru"], "g3kb-switch").backend == "none"
    assert LayoutSwitcher(["us", "ru"], "setxkbmap").backend == "none"


def test_get_current_layout_g3kb_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(switcher_module, "_run", lambda cmd, timeout=2.0: fake_completed("1\n"))
    switcher = LayoutSwitcher(["us", "ru"], "g3kb-switch")
    assert switcher.get_current_layout() == "ru"


def test_get_current_layout_g3kb_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(switcher_module, "_run", lambda cmd, timeout=2.0: fake_completed("us\n"))
    switcher = LayoutSwitcher(["us", "ru"], "g3kb-switch")
    assert switcher.get_current_layout() == "us"


def test_get_current_layout_setxkbmap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        switcher_module,
        "_run",
        lambda cmd, timeout=2.0: fake_completed("rules: evdev\nlayout: us,ru\n"),
    )
    switcher = LayoutSwitcher(["us", "ru"], "setxkbmap")
    assert switcher.get_current_layout() == "us"


def test_get_current_layout_falls_back_to_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: None)
    switcher = LayoutSwitcher(["us", "ru"], "auto", session_type="wayland")
    assert switcher.get_current_layout() == "us"


def test_get_current_layout_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    calls = {"count": 0}

    def counting_run(cmd: list[str], timeout: float = 2.0) -> subprocess.CompletedProcess[str]:
        calls["count"] += 1
        return fake_completed("0\n")

    monkeypatch.setattr(switcher_module, "_run", counting_run)
    switcher = LayoutSwitcher(["us", "ru"], "g3kb-switch")
    switcher.get_current_layout()
    switcher.get_current_layout()
    assert calls["count"] == 1
    switcher.get_current_layout(force=True)
    assert calls["count"] == 2


def test_switch_to_g3kb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    recorded: list[list[str]] = []

    def record(cmd: list[str], timeout: float = 2.0) -> subprocess.CompletedProcess[str]:
        recorded.append(cmd)
        return fake_completed("")

    monkeypatch.setattr(switcher_module, "_run", record)
    switcher = LayoutSwitcher(["us", "ru"], "g3kb-switch")
    assert switcher.switch_to("ru") is True
    assert recorded[-1] == ["g3kb-switch", "-s", "1"]
    assert switcher.get_current_layout() == "ru"


def test_switch_to_setxkbmap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    recorded: list[list[str]] = []
    monkeypatch.setattr(
        switcher_module,
        "_run",
        lambda cmd, timeout=2.0: (recorded.append(cmd), fake_completed(""))[1],
    )
    switcher = LayoutSwitcher(["us", "ru"], "setxkbmap")
    assert switcher.switch_to("ru") is True
    assert recorded[-1] == ["setxkbmap", "ru"]


def test_switch_to_unknown_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    switcher = LayoutSwitcher(["us", "ru"], "g3kb-switch")
    assert switcher.switch_to("de") is False


def test_switch_to_without_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: None)
    switcher = LayoutSwitcher(["us", "ru"], "auto", session_type="wayland")
    assert switcher.switch_to("ru") is False


def test_switch_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(switcher_module, "_run", lambda cmd, timeout=2.0: fake_completed("", 1))
    switcher = LayoutSwitcher(["us", "ru"], "g3kb-switch")
    assert switcher.switch_to("ru") is False


def test_run_handles_missing_command(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("nope")

    monkeypatch.setattr(subprocess, "run", boom)
    result = switcher_module._run(["does-not-exist"])
    assert result.returncode == -1


def test_describe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(switcher_module, "_which", lambda name: "/usr/bin/" + name)
    switcher = LayoutSwitcher(["us", "ru"], "g3kb-switch", session_type="wayland")
    assert "g3kb-switch" in switcher.describe()
    assert "wayland" in switcher.describe()
