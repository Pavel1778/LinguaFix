"""Tests for :mod:`linguafix.cli`."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from linguafix import cli


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect XDG directories into a temporary tree."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path


def test_build_parser_has_all_commands() -> None:
    parser = cli.build_parser()
    actions = [
        choice for action in parser._actions for choice in getattr(action, "choices", []) or []
    ]
    for command in (
        "start",
        "stop",
        "status",
        "config",
        "fix",
        "doctor",
        "collect-logs",
        "install-autostart",
        "uninstall-autostart",
        "version",
    ):
        assert command in actions


def test_version_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["version"]) == 0
    assert "LinguaFix" in capsys.readouterr().out


def test_doctor_command(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "run_doctor", lambda: 0)
    assert cli.main(["doctor"]) == 0


def test_collect_logs_command(
    isolated_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["collect-logs", "--output", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "архив создан" in out
    assert list(tmp_path.glob("linguafix-logs-*.tar.gz"))


def test_collect_logs_command_failure(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(cli, "collect_logs", boom)
    assert cli.main(["collect-logs"]) == 1
    assert "Не удалось создать архив" in capsys.readouterr().out


def test_status_when_not_running(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_read_pid", lambda: None)
    assert cli.main(["status"]) == 0
    assert "не запущен" in capsys.readouterr().out


def test_status_when_running(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_read_pid", lambda: 4242)
    assert cli.main(["status"]) == 0
    assert "4242" in capsys.readouterr().out


def test_stop_when_not_running(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_read_pid", lambda: None)
    assert cli.main(["stop"]) == 0
    assert "уже остановлен" in capsys.readouterr().out


def test_stop_sends_signal(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_read_pid", lambda: 4242)
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    assert cli.main(["stop"]) == 0
    assert killed == [(4242, cli.signal.SIGTERM)]


def test_config_show(isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["config", "show"]) == 0
    output = capsys.readouterr().out
    assert "analysis_timeout" in output


def test_config_reset(isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["config", "reset"]) == 0
    assert "сброшена" in capsys.readouterr().out


def test_fix_reports_no_change(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "us")
    assert cli.main(["fix", "--text", "hello"]) == 0
    assert "не требуется" in capsys.readouterr().out


def test_fix_shows_conversion(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "us")
    assert cli.main(["fix", "--text", "ghbdtn"]) == 0
    assert "привет" in capsys.readouterr().out


def test_fix_apply(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "us")
    monkeypatch.setattr(cli.LayoutSwitcher, "switch_to", lambda self, layout: True)
    applied: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        cli.TextInjector,
        "replace_text",
        lambda self, old, new, layout: applied.append((old, new, layout)) or True,
    )
    assert cli.main(["fix", "--text", "ghbdtn", "--apply"]) == 0
    assert applied == [("ghbdtn", "привет", "ru")]


def test_fix_apply_failure(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "us")
    monkeypatch.setattr(cli.LayoutSwitcher, "switch_to", lambda self, layout: True)
    monkeypatch.setattr(cli.TextInjector, "replace_text", lambda self, o, n, layout: False)
    assert cli.main(["fix", "--text", "ghbdtn", "--apply"]) == 1


def test_fix_empty_text(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", type("S", (), {"read": staticmethod(lambda: "")})())
    assert cli.main(["fix"]) == 2
    assert "Нет текста" in capsys.readouterr().out


def test_fix_dry_run_does_not_apply(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "us")
    applied: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        cli.TextInjector,
        "replace_text",
        lambda self, old, new, layout: applied.append((old, new, layout)) or True,
    )
    assert cli.main(["fix", "--text", "ghbdtn", "--apply", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "привет" in out
    assert "dry-run" in out
    assert applied == []


def test_start_dry_run_flag_is_parsed() -> None:
    args = cli.build_parser().parse_args(["start", "--foreground", "--dry-run"])
    assert args.dry_run is True


def test_install_autostart(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = isolated_env / "src" / "linguafix.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text("[Desktop Entry]\nName=LinguaFix\n", encoding="utf-8")
    monkeypatch.setattr(
        cli, "_bundled_data_file", lambda name: desktop if name.endswith("desktop") else None
    )
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: None)
    assert cli.main(["install-autostart"]) == 0
    assert cli._autostart_path().exists()
    assert "Автозапуск установлен" in capsys.readouterr().out


def test_install_autostart_missing_source(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_bundled_data_file", lambda name: None)
    assert cli.main(["install-autostart"]) == 1


def test_uninstall_autostart(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    target = cli._autostart_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: None)
    assert cli.main(["uninstall-autostart"]) == 0
    assert not target.exists()
    assert "Автозапуск удалён" in capsys.readouterr().out


def test_pid_alive_for_current_process() -> None:
    import os

    assert cli._pid_alive(os.getpid()) is True


def test_pid_alive_for_missing_process() -> None:
    assert cli._pid_alive(999_999_999) is False


def test_read_pid_invalid_file(isolated_env: Path) -> None:
    path = cli._lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-a-pid", encoding="utf-8")
    assert cli._read_pid() is None


def test_read_pid_missing_file(isolated_env: Path) -> None:
    assert cli._read_pid() is None


def test_start_when_already_running(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_read_pid", lambda: 1234)
    args = argparse.Namespace(foreground=False)
    assert cli.cmd_start(args) == 0
    assert "запущен" in capsys.readouterr().out
