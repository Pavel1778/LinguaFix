"""Tests for focused-application detection and its fallbacks."""

from __future__ import annotations

import pytest

from linguafix import app_focus


def test_strip_desktop_suffix() -> None:
    assert app_focus._strip_desktop_suffix("org.gnome.Terminal.desktop") == "Terminal"
    assert app_focus._strip_desktop_suffix("code") == "code"


def test_get_active_app_returns_first_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_focus, "_PROBES", (lambda: "gnome-terminal", lambda: "code"))
    assert app_focus.get_active_app() == "gnome-terminal"


def test_get_active_app_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_focus, "_PROBES", (lambda: None, lambda: "code"))
    assert app_focus.get_active_app() == "code"


def test_get_active_app_returns_none_when_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> str | None:
        raise RuntimeError("probe failed")

    monkeypatch.setattr(app_focus, "_PROBES", (boom, lambda: None))
    assert app_focus.get_active_app() is None


def test_xprop_parses_wm_class(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        def __init__(self, stdout: str, returncode: int = 0) -> None:
            self.stdout = stdout
            self.returncode = returncode

    def fake_run(argv: list[str], **_kwargs: object) -> _Result:
        if "_NET_ACTIVE_WINDOW" in argv:
            return _Result("_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3400007")
        return _Result('WM_CLASS(STRING) = "gnome-terminal", "Gnome-terminal"')

    monkeypatch.setattr(app_focus.subprocess, "run", fake_run)
    assert app_focus._xprop() == "gnome-terminal"


def test_xprop_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("xprop")

    monkeypatch.setattr(app_focus.subprocess, "run", fake_run)
    assert app_focus._xprop() is None
