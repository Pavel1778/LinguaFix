"""Tests for :mod:`linguafix.daemon_control`.

The module is the single control surface the GUI uses, so it must behave when
systemd is present, when it is absent, and when a daemon was started manually.
"""

from __future__ import annotations

import signal
from pathlib import Path

import pytest

from linguafix import daemon_control


@pytest.fixture
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the XDG dirs at a tmp dir so the lock file is hermetic."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path


def test_read_pid_missing_file(isolated_env: Path) -> None:
    assert daemon_control.read_pid() is None


def test_read_pid_rejects_garbage(isolated_env: Path) -> None:
    path = daemon_control.lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-a-pid", encoding="utf-8")
    assert daemon_control.read_pid() is None


def test_read_pid_returns_live_pid(isolated_env: Path) -> None:
    import os

    path = daemon_control.lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")
    assert daemon_control.read_pid() == os.getpid()


def test_read_pid_dead_process_is_none(isolated_env: Path) -> None:
    path = daemon_control.lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("999999999", encoding="utf-8")
    assert daemon_control.read_pid() is None


def test_is_running_true_with_lock(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_control, "read_pid", lambda: 4242)
    monkeypatch.setattr(daemon_control, "systemd_active", lambda: False)
    assert daemon_control.is_running() is True


def test_is_running_true_with_systemd_only(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon_control, "read_pid", lambda: None)
    monkeypatch.setattr(daemon_control, "systemd_active", lambda: True)
    assert daemon_control.is_running() is True


def test_is_running_false_when_neither(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_control, "read_pid", lambda: None)
    monkeypatch.setattr(daemon_control, "systemd_active", lambda: False)
    assert daemon_control.is_running() is False


def test_stop_kills_manual_daemon(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A daemon started from the terminal must be stoppable (the GUI bug)."""
    killed: list[tuple[int, int]] = []
    alive = {"v": True}

    def fake_kill(pid: int, sig: int) -> None:
        killed.append((pid, sig))
        if sig == signal.SIGTERM:
            alive["v"] = False

    monkeypatch.setattr(daemon_control, "systemd_active", lambda: False)
    monkeypatch.setattr(daemon_control, "systemd_enabled", lambda: False)
    monkeypatch.setattr(daemon_control, "read_pid", lambda: 4242 if alive["v"] else None)
    monkeypatch.setattr(daemon_control, "_kill_pid", lambda pid, sig: fake_kill(pid, sig))
    monkeypatch.setattr(daemon_control, "pid_alive", lambda pid: alive["v"])
    assert daemon_control.stop() is True
    assert killed == [(4242, signal.SIGTERM)]


def test_stop_escalates_to_sigkill(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(daemon_control, "systemd_active", lambda: False)
    monkeypatch.setattr(daemon_control, "systemd_enabled", lambda: False)
    monkeypatch.setattr(daemon_control, "read_pid", lambda: 4242)
    monkeypatch.setattr(daemon_control, "_kill_pid", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(daemon_control, "pid_alive", lambda pid: True)
    monkeypatch.setattr(daemon_control, "STOP_GRACE", 0.0)
    assert daemon_control.stop() is False  # never actually stops
    assert (4242, signal.SIGTERM) in killed
    assert (4242, signal.SIGKILL) in killed


def test_stop_uses_systemd_when_active(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon_control, "systemd_active", lambda: True)
    monkeypatch.setattr(daemon_control, "read_pid", lambda: None)
    monkeypatch.setattr(daemon_control, "_systemctl", lambda args, timeout=5.0: calls.append(args))
    daemon_control.stop()
    assert calls == [["stop", "linguafix.service"]]


def test_start_prefers_systemd_when_enabled(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    monkeypatch.setattr(daemon_control, "systemd_enabled", lambda: True)
    monkeypatch.setattr(daemon_control, "systemd_active", lambda: True)
    monkeypatch.setattr(daemon_control, "_systemctl", lambda args, timeout=5.0: calls.append(args))
    monkeypatch.setattr(daemon_control, "read_pid", lambda: None)
    assert daemon_control.start() is True
    assert calls == [["start", "linguafix.service"]]


def test_start_spawns_when_systemd_disabled(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    monkeypatch.setattr(daemon_control, "systemd_enabled", lambda: False)
    monkeypatch.setattr(
        daemon_control, "spawn_detached", lambda dry_run=False: spawned.append(True)
    )
    monkeypatch.setattr(daemon_control, "_wait_until", lambda predicate, timeout: True)
    monkeypatch.setattr(daemon_control, "read_pid", lambda: 4242)
    assert daemon_control.start() is True
    assert spawned == [True]


def test_start_reports_failure_when_daemon_dies(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daemon that writes the lock then dies must not look like a start."""
    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    monkeypatch.setattr(daemon_control, "systemd_enabled", lambda: False)
    monkeypatch.setattr(daemon_control, "spawn_detached", lambda dry_run=False: None)
    monkeypatch.setattr(daemon_control, "_wait_until", lambda predicate, timeout: True)
    monkeypatch.setattr(daemon_control, "read_pid", lambda: None)
    monkeypatch.setattr(daemon_control.time, "sleep", lambda _s: None)
    assert daemon_control.start() is False


def test_start_already_running_is_noop(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spawned: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(
        daemon_control, "spawn_detached", lambda dry_run=False: spawned.append(True)
    )
    assert daemon_control.start() is True
    assert spawned == []


def test_reload_uses_sighup_for_manual_daemon(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(daemon_control, "read_pid", lambda: 4242)
    monkeypatch.setattr(
        daemon_control, "_kill_pid", lambda pid, sig: sent.append((pid, sig)) or True
    )
    assert daemon_control.reload_config() is True
    assert sent == [(4242, signal.SIGHUP)]


def test_reload_falls_back_to_systemctl(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon_control, "read_pid", lambda: None)

    class _Result:
        returncode = 0

    monkeypatch.setattr(
        daemon_control, "_systemctl", lambda args, timeout=5.0: calls.append(args) or _Result()
    )
    assert daemon_control.reload_config() is True
    assert calls == [["reload-or-restart", "linguafix.service"]]


def test_autostart_reflects_xdg_entry(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_control, "systemd_enabled", lambda: False)
    assert daemon_control.autostart_enabled() is False
    autostart = isolated_env / "config" / "autostart" / "linguafix.desktop"
    autostart.parent.mkdir(parents=True, exist_ok=True)
    autostart.write_text("[Desktop Entry]\n", encoding="utf-8")
    assert daemon_control.autostart_enabled() is True


def test_systemctl_missing_is_handled(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_control.shutil, "which", lambda _name: None)
    assert daemon_control._systemctl(["is-active", "linguafix.service"]) is None
    assert daemon_control.systemd_active() is False
    assert daemon_control.systemd_enabled() is False
    assert daemon_control.enable_autostart() is False


def test_pid_alive_permission_error_means_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_permission(pid: int, sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(daemon_control.os, "kill", raise_permission)
    assert daemon_control.pid_alive(1) is True


def test_pid_alive_missing_process(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_missing(pid: int, sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(daemon_control.os, "kill", raise_missing)
    assert daemon_control.pid_alive(999999) is False


def test_wait_until_success_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    assert daemon_control._wait_until(lambda: True, 1.0) is True
    monkeypatch.setattr(daemon_control, "POLL_INTERVAL", 0.0)
    assert daemon_control._wait_until(lambda: False, 0.0) is False


def test_spawn_detached_prefers_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[list[str]] = []

    class _Popen:
        def __init__(self, argv: list[str], **_kwargs: object) -> None:
            recorded.append(argv)

    monkeypatch.setattr(daemon_control.shutil, "which", lambda _name: "/usr/bin/linguafix")
    monkeypatch.setattr(daemon_control.subprocess, "Popen", _Popen)
    daemon_control.spawn_detached()
    assert recorded == [["/usr/bin/linguafix", "start", "--foreground"]]


def test_spawn_detached_falls_back_to_module(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[list[str]] = []

    class _Popen:
        def __init__(self, argv: list[str], **_kwargs: object) -> None:
            recorded.append(argv)

    monkeypatch.setattr(daemon_control.shutil, "which", lambda _name: None)
    monkeypatch.setattr(daemon_control.subprocess, "Popen", _Popen)
    monkeypatch.setattr(daemon_control.sys, "executable", "/usr/bin/python3")
    daemon_control.spawn_detached(dry_run=True)
    assert recorded == [
        ["/usr/bin/python3", "-m", "linguafix", "start", "--foreground", "--dry-run"]
    ]


def test_spawn_detached_handles_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_oserror(*_args: object, **_kwargs: object) -> None:
        raise OSError("nope")

    monkeypatch.setattr(daemon_control.shutil, "which", lambda _name: None)
    monkeypatch.setattr(daemon_control.subprocess, "Popen", raise_oserror)
    daemon_control.spawn_detached()  # must not raise


def test_start_falls_back_when_systemd_start_fails(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[bool] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    monkeypatch.setattr(daemon_control, "systemd_enabled", lambda: True)
    monkeypatch.setattr(daemon_control, "systemd_active", lambda: False)
    monkeypatch.setattr(daemon_control, "_systemctl", lambda args, timeout=5.0: None)
    monkeypatch.setattr(daemon_control, "_wait_until", lambda predicate, timeout: False)
    monkeypatch.setattr(
        daemon_control, "spawn_detached", lambda dry_run=False: spawned.append(True)
    )
    daemon_control.start()
    assert spawned == [True]


def test_restart_when_stopped_just_starts(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    called: list[str] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: False)
    monkeypatch.setattr(
        daemon_control, "start", lambda dry_run=False: called.append("start") or True
    )
    assert daemon_control.restart() is True
    assert called == ["start"]


def test_restart_service_daemon(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon_control, "is_running", lambda: True)
    monkeypatch.setattr(daemon_control, "systemd_enabled", lambda: True)
    monkeypatch.setattr(daemon_control, "systemd_active", lambda: False)
    monkeypatch.setattr(daemon_control, "stop", lambda: True)
    monkeypatch.setattr(daemon_control, "_systemctl", lambda args, timeout=5.0: calls.append(args))
    monkeypatch.setattr(daemon_control, "_wait_until", lambda predicate, timeout: True)
    assert daemon_control.restart() is True
    assert calls == [["start", "linguafix.service"]]


def test_enable_and_disable_autostart(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class _Result:
        returncode = 0

    monkeypatch.setattr(
        daemon_control, "_systemctl", lambda args, timeout=5.0: calls.append(args) or _Result()
    )
    assert daemon_control.enable_autostart() is True
    assert daemon_control.disable_autostart() is True
    assert calls == [["enable", "linguafix.service"], ["disable", "linguafix.service"]]


def test_undo_requires_running_daemon(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_control, "read_pid", lambda: None)
    assert daemon_control.undo_last_fix() is False


def test_undo_signals_daemon(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(daemon_control, "read_pid", lambda: 4242)
    monkeypatch.setattr(
        daemon_control, "_kill_pid", lambda pid, sig: sent.append((pid, sig)) or True
    )
    assert daemon_control.undo_last_fix() is True
    assert sent == [(4242, signal.SIGUSR1)]


def test_pid_alive_rejects_nonpositive() -> None:
    assert daemon_control.pid_alive(0) is False
    assert daemon_control.pid_alive(-1) is False


def test_read_pid_removes_stale_lock(isolated_env: Path) -> None:
    """A lock file left by a crashed daemon is cleaned up on read."""
    path = daemon_control.lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("999999999", encoding="utf-8")
    assert daemon_control.read_pid() is None
    assert not path.exists()


def test_is_zombie_true_for_zombie(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        daemon_control.Path,
        "read_text",
        lambda self, encoding=None: "123 (linguafix) Z 1 2 3",
    )
    assert daemon_control._is_zombie(123) is True


def test_is_zombie_false_for_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        daemon_control.Path,
        "read_text",
        lambda self, encoding=None: "123 (linguafix) S 1 2 3",
    )
    assert daemon_control._is_zombie(123) is False


def test_is_zombie_false_when_proc_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_missing(self: Path, encoding: str | None = None) -> str:
        raise FileNotFoundError

    monkeypatch.setattr(daemon_control.Path, "read_text", raise_missing)
    assert daemon_control._is_zombie(123) is False


def test_pid_alive_treats_zombie_as_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    """The "toggle works every other time" bug: a zombie must not read as alive."""
    monkeypatch.setattr(daemon_control.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(daemon_control, "_is_zombie", lambda pid: True)
    assert daemon_control.pid_alive(4242) is False


def test_pid_alive_real_zombie() -> None:
    """End-to-end: a child that exited but is not reaped must not read as alive."""
    import subprocess
    import sys
    import time

    if not Path("/proc/self/stat").exists():  # pragma: no cover - Linux only
        pytest.skip("requires /proc")

    child = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        time.sleep(0.4)
        assert Path(f"/proc/{child.pid}/stat").read_text().split()[2] == "Z"
        assert daemon_control.pid_alive(child.pid) is False
    finally:
        child.wait()
