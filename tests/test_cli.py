"""Tests for :mod:`linguafix.cli`."""

from __future__ import annotations

import argparse
import signal
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
        "kill",
        "status",
        "mode",
        "undo",
        "dict",
        "config",
        "fix",
        "doctor",
        "collect-logs",
        "install-autostart",
        "uninstall-autostart",
        "version",
        "export",
        "import",
        "restart",
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
    from linguafix import daemon_control

    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    assert cli.main(["stop"]) == 0
    assert "уже остановлен" in capsys.readouterr().out


def test_stop_delegates_to_daemon_control(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``stop`` must go through ``daemon_control.stop`` (stops the systemd unit)."""
    from linguafix import daemon_control

    stopped: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(daemon_control, "stop", lambda: stopped.append(True) or True)
    assert cli.main(["stop"]) == 0
    assert stopped == [True]
    assert "остановлен" in capsys.readouterr().out


def test_stop_reports_failure(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from linguafix import daemon_control

    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(daemon_control, "stop", lambda: False)
    assert cli.main(["stop"]) == 1
    assert "Не удалось остановить" in capsys.readouterr().out


def test_kill_delegates_to_daemon_control(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from linguafix import daemon_control

    killed: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(daemon_control, "kill", lambda: killed.append(True) or True)
    assert cli.main(["kill"]) == 0
    assert killed == [True]
    assert "SIGKILL" in capsys.readouterr().out


def test_kill_when_not_running(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from linguafix import daemon_control

    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    assert cli.main(["kill"]) == 0
    assert "уже остановлен" in capsys.readouterr().out


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
    applied: list[tuple[int, str, str]] = []
    monkeypatch.setattr(
        cli.TextInjector,
        "replace_text",
        lambda self, count, new, layout: applied.append((count, new, layout)) or True,
    )
    assert cli.main(["fix", "--text", "ghbdtn", "--apply"]) == 0
    assert applied == [(6, "привет", "ru")]


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


def test_fix_honours_user_dictionary(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # A taught brand is not in the frequency corpora; the CLI must load the
    # user dictionary so ``fix`` agrees with the daemon on ``муксуд``.
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env / "data"))
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "ru")
    assert cli.main(["dict", "add", "vercel"]) == 0
    capsys.readouterr()
    assert cli.main(["fix", "--text", "муксуд"]) == 0
    assert "vercel" in capsys.readouterr().out


def test_fix_dry_run_does_not_apply(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli.LayoutSwitcher, "get_current_layout", lambda self, force=False: "us")
    applied: list[tuple[int, str, str]] = []
    monkeypatch.setattr(
        cli.TextInjector,
        "replace_text",
        lambda self, count, new, layout: applied.append((count, new, layout)) or True,
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


def test_install_autostart_renders_bin_placeholder(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = isolated_env / "src" / "linguafix.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text("[Desktop Entry]\nExec=@BIN@ start --foreground\n", encoding="utf-8")
    monkeypatch.setattr(
        cli, "_bundled_data_file", lambda name: desktop if name.endswith("desktop") else None
    )
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_launcher_path", lambda: "/usr/bin/linguafix")
    assert cli.main(["install-autostart"]) == 0
    written = cli._autostart_path().read_text(encoding="utf-8")
    assert "@BIN@" not in written
    assert "Exec=/usr/bin/linguafix start --foreground" in written


def test_bundled_unit_and_desktop_are_templates() -> None:
    """The shipped files must keep the placeholder for installers to render."""
    from importlib import resources

    base = resources.files("linguafix") / "data"
    assert "@BIN@" in (base / "linguafix.service").read_text(encoding="utf-8")
    assert "@BIN@" in (base / "linguafix.desktop").read_text(encoding="utf-8")


def test_udev_rule_uses_uaccess() -> None:
    """The shipped udev rule must grant access via uaccess, not the input group."""
    rule = Path(__file__).resolve().parent.parent / "data" / "71-linguafix.rules"
    text = rule.read_text(encoding="utf-8")
    active = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    assert any('TAG+="uaccess"' in line for line in active)
    assert not any("GROUP=" in line for line in active)
    # Every active rule needs ACTION!="remove": on systemd 257+ (Debian 13) the
    # uaccess ACL is applied by 73-seat-late.rules, which only processes rules
    # that guard against the "remove" event.
    assert all('ACTION!="remove"' in line for line in active)


def test_repo_and_packaged_data_files_match() -> None:
    """``data/`` and ``src/linguafix/data/`` must not drift apart."""
    from importlib import resources

    packaged = Path(str(resources.files("linguafix") / "data"))
    repo_data = Path(__file__).resolve().parent.parent / "data"
    for name in ("linguafix.service", "linguafix.desktop", "linguafix.svg"):
        assert (repo_data / name).read_bytes() == (packaged / name).read_bytes(), name


def test_uninstall_autostart(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    target = cli._autostart_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    monkeypatch.setattr(cli, "_run_quiet", lambda *a, **k: 0)
    assert cli.main(["uninstall-autostart"]) == 0
    assert not target.exists()
    assert "Автозапуск удалён" in capsys.readouterr().out


def test_run_quiet_survives_missing_binary() -> None:
    assert cli._run_quiet(["definitely-not-a-real-binary-xyz"]) == 127


def test_install_autostart_survives_missing_systemctl(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = isolated_env / "src" / "linguafix.desktop"
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text("Exec=@BIN@ start\n", encoding="utf-8")
    unit = isolated_env / "src" / "linguafix.service"
    unit.write_text("ExecStart=@BIN@ start\n", encoding="utf-8")

    def fake(name: str) -> Path:
        return unit if name.endswith("service") else desktop

    monkeypatch.setattr(cli, "_bundled_data_file", fake)
    assert cli.main(["install-autostart"]) == 0


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


def test_cmd_gui_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    import linguafix.gui as gui

    monkeypatch.setattr(gui, "main", lambda: 0)
    assert cli.cmd_gui(argparse.Namespace()) == 0


def test_start_detached_reports_success_when_alive(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Popen:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(cli.subprocess, "Popen", _Popen)
    monkeypatch.setattr(cli, "_read_pid", lambda: 4242)
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    assert cli.cmd_start(argparse.Namespace(foreground=False, dry_run=False)) == 0
    assert "запущен" in capsys.readouterr().out


def test_start_detached_reports_failure_when_daemon_dies(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daemon that never comes up must not print success."""

    class _Popen:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(cli.subprocess, "Popen", _Popen)
    monkeypatch.setattr(cli, "_read_pid", lambda: None)
    monkeypatch.setattr(cli, "START_TIMEOUT", 0.01)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    assert cli.cmd_start(argparse.Namespace(foreground=False, dry_run=False)) == 1
    assert "Не удалось запустить" in capsys.readouterr().out


def test_mode_show_and_set(isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["mode"]) == 0
    assert capsys.readouterr().out.strip() == "auto"

    assert cli.main(["mode", "manual"]) == 0
    assert "manual" in capsys.readouterr().out
    assert cli.main(["mode"]) == 0
    assert capsys.readouterr().out.strip() == "manual"


def test_mode_signals_running_daemon(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Changing the mode must reach a running daemon, not only the file."""
    from linguafix import daemon_control

    reloads: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(daemon_control, "reload_config", lambda: reloads.append(True) or True)

    assert cli.main(["mode", "manual"]) == 0
    assert reloads == [True]


def test_mode_does_not_signal_when_daemon_stopped(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from linguafix import daemon_control

    reloads: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    monkeypatch.setattr(daemon_control, "reload_config", lambda: reloads.append(True) or True)

    assert cli.main(["mode", "manual"]) == 0
    assert reloads == []


def test_undo_requires_running_daemon(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_read_pid", lambda: None)
    assert cli.main(["undo"]) == 1
    assert "не запущен" in capsys.readouterr().out


def test_undo_signals_daemon(
    isolated_env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(cli, "_read_pid", lambda: 4242)
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    assert cli.main(["undo"]) == 0
    assert signals == [(4242, signal.SIGUSR1)]


def test_dict_add_list_remove(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env / "data"))
    assert cli.main(["dict", "list"]) == 0
    assert "пуст" in capsys.readouterr().out

    assert cli.main(["dict", "add", "котопёс"]) == 0
    assert cli.main(["dict", "add", "гайдлайн"]) == 0
    assert cli.main(["dict", "list"]) == 0
    listed = capsys.readouterr().out
    assert "котопёс" in listed and "гайдлайн" in listed

    assert cli.main(["dict", "remove", "котопёс"]) == 0
    assert cli.main(["dict", "list"]) == 0
    assert "котопёс" not in capsys.readouterr().out


def test_dict_remove_missing_word(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env / "data"))
    assert cli.main(["dict", "remove", "нетакого"]) == 1
    assert "не найдено" in capsys.readouterr().out


def test_dict_add_without_word(
    isolated_env: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(isolated_env / "data"))
    assert cli.main(["dict", "add"]) == 2
    assert "Укажите слово" in capsys.readouterr().out


def test_install_autostart_uses_dedicated_autostart_file(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The menu entry and the autostart entry are distinct desktop files."""
    requested: list[str] = []

    def fake(name: str) -> Path | None:
        requested.append(name)
        desktop = isolated_env / "src" / name
        desktop.parent.mkdir(parents=True, exist_ok=True)
        desktop.write_text("Exec=@BIN@ start\n", encoding="utf-8")
        return desktop

    monkeypatch.setattr(cli, "_bundled_data_file", fake)
    assert cli.main(["install-autostart"]) == 0
    assert "linguafix-autostart.desktop" in requested
