"""Tests for :mod:`linguafix.logging_setup` and :mod:`linguafix.tray`."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from linguafix.logging_setup import LOG_FILE_NAME, setup_logging
from linguafix.tray import TrayIcon


def test_setup_logging_creates_file(tmp_path: Path) -> None:
    log_file = setup_logging("DEBUG", log_dir=tmp_path)
    assert log_file.exists()
    assert log_file.name == LOG_FILE_NAME
    logging.getLogger("test").debug("hello")
    assert "hello" in log_file.read_text(encoding="utf-8")
    logging.getLogger().handlers.clear()


def test_setup_logging_is_idempotent(tmp_path: Path) -> None:
    setup_logging("INFO", log_dir=tmp_path)
    setup_logging("INFO", log_dir=tmp_path)
    assert len(logging.getLogger().handlers) == 1
    logging.getLogger().handlers.clear()


def test_setup_logging_console(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging("INFO", log_dir=tmp_path, console=True)
    logging.getLogger("test").info("console-message")
    assert "console-message" in capsys.readouterr().err
    logging.getLogger().handlers.clear()


def test_setup_logging_invalid_level_falls_back(tmp_path: Path) -> None:
    setup_logging("NOT-A-LEVEL", log_dir=tmp_path)
    assert logging.getLogger().level == logging.INFO
    logging.getLogger().handlers.clear()


# --- tray -------------------------------------------------------------------


def test_tray_start_without_gi() -> None:
    tray = TrayIcon()
    # On a headless CI machine PyGObject is unavailable; start() must not raise.
    result = tray.start()
    assert result in (True, False)
    tray.stop()


def test_tray_available_is_boolean() -> None:
    assert isinstance(TrayIcon.available(), bool)


def test_tray_callbacks_are_stored() -> None:
    calls: list[str] = []
    tray = TrayIcon(
        on_fix=lambda: calls.append("fix"),
        on_settings=lambda: calls.append("settings"),
        on_quit=lambda: calls.append("quit"),
    )
    assert tray.on_fix is not None
    assert tray.on_settings is not None
    assert tray.on_quit is not None


def test_tray_build_menu_uses_module() -> None:
    created: list[str] = []

    class FakeMenuItem:
        def __init__(self, label: str = "") -> None:
            self.label = label
            created.append(label)

        def connect(self, *_args: object) -> None:
            return None

        def set_sensitive(self, *_args: object) -> None:
            return None

    class FakeMenu:
        def append(self, item: object) -> None:
            return None

        def show_all(self) -> None:
            return None

    class FakeGtk:
        Menu = FakeMenu
        MenuItem = FakeMenuItem

    tray = TrayIcon(on_fix=lambda: None, on_quit=lambda: None)
    tray._build_menu(FakeGtk)
    assert "Исправить сейчас" in created
    assert "Выход" in created


def test_tray_stop_without_start() -> None:
    TrayIcon().stop()  # must not raise


def test_tray_status_callback_is_stored() -> None:
    tray = TrayIcon(on_status=lambda: "LinguaFix: active")
    assert tray.on_status is not None


def test_tray_show_status_without_callback_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "linguafix.tray.subprocess.run",
        lambda *a, **k: calls.append(list(a[0])),
    )
    TrayIcon()._show_status()  # no callback -> nothing happens
    assert calls == []


def test_tray_show_status_notifies(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "linguafix.tray.subprocess.run",
        lambda *a, **k: calls.append(list(a[0])),
    )
    tray = TrayIcon(on_status=lambda: "LinguaFix: active, layout=us")
    tray._show_status()
    assert calls
    assert "LinguaFix: active, layout=us" in calls[0]


def test_tray_show_status_handles_callback_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> str:
        raise RuntimeError("nope")

    monkeypatch.setattr("linguafix.tray.subprocess.run", lambda *a, **k: None)
    TrayIcon(on_status=boom)._show_status()  # must not raise


def test_tray_menu_contains_show_status() -> None:
    created: list[str] = []

    class FakeMenuItem:
        def __init__(self, label: str = "") -> None:
            created.append(label)

        def connect(self, *_args: object) -> None:
            return None

        def set_sensitive(self, *_args: object) -> None:
            return None

    class FakeMenu:
        def append(self, item: object) -> None:
            return None

        def show_all(self) -> None:
            return None

    class FakeGtk:
        Menu = FakeMenu
        MenuItem = FakeMenuItem

    tray = TrayIcon(on_status=lambda: "ok")
    tray._build_menu(FakeGtk)
    assert "Показать статус" in created
