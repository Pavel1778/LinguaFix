"""Command line interface for LinguaFix.

The CLI is intentionally thin: it starts and stops the daemon, inspects status,
manages the configuration file and can trigger a manual correction.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .config import Config, cache_dir, config_path, load_config, save_config
from .converter import LayoutConverter
from .detector import LanguageDetector
from .injector import TextInjector
from .switcher import LayoutSwitcher

LOCK_FILE_NAME = "daemon.lock"
START_TIMEOUT = 5.0

# Russian user-facing strings (English duplicates live in the README).
MSG_NOT_RUNNING = "LinguaFix не запущен."
MSG_STOPPED = "LinguaFix остановлен."
MSG_ALREADY_STOPPED = "LinguaFix уже остановлен."
MSG_STARTED = "LinguaFix запущен."
MSG_AUTOSTART_INSTALLED = "Автозапуск установлен."
MSG_AUTOSTART_REMOVED = "Автозапуск удалён."
MSG_CONFIG_RESET = "Конфигурация сброшена к значениям по умолчанию."


def _lock_path() -> Path:
    """Return the path of the daemon lock file."""
    return cache_dir() / LOCK_FILE_NAME


def _read_pid() -> int | None:
    """Return the PID stored in the lock file, if any and alive."""
    path = _lock_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.isdigit():
        return None
    pid = int(raw)
    if _pid_alive(pid):
        return pid
    return None


def _pid_alive(pid: int) -> bool:
    """Return ``True`` when a process with ``pid`` exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _autostart_path() -> Path:
    """Return the XDG autostart desktop file path."""
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / "linguafix.desktop"


def cmd_start(args: argparse.Namespace) -> int:
    """Start the daemon, either in the foreground or detached."""
    if _read_pid() is not None:
        print(MSG_STARTED)
        return 0
    if args.foreground:
        from .daemon import LinguaFixDaemon
        from .logging_setup import setup_logging

        config = load_config()
        setup_logging(config.log_level, console=True)
        daemon = LinguaFixDaemon(config, dry_run=args.dry_run)
        return daemon.run()

    command = [sys.executable, "-m", "linguafix", "start", "--foreground"]
    if args.dry_run:
        command.append("--dry-run")
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        if _read_pid() is not None:
            print(MSG_STARTED)
            return 0
        time.sleep(0.1)
    print("Не удалось запустить LinguaFix. Смотрите логи: ~/.local/state/linguafix/")
    return 1


def cmd_stop(_args: argparse.Namespace) -> int:
    """Stop a running daemon via SIGTERM."""
    pid = _read_pid()
    if pid is None:
        print(MSG_ALREADY_STOPPED)
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"Не удалось остановить LinguaFix: {exc}")
        return 1
    print(MSG_STOPPED)
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    """Print the daemon status and runtime environment."""
    config = load_config()
    pid = _read_pid()
    if pid is None:
        print(MSG_NOT_RUNNING)
    else:
        print(f"LinguaFix запущен (PID {pid}).")

    switcher = LayoutSwitcher(layouts=config.layouts, switch_method=config.switch_method)
    injector = TextInjector(backend=config.backend)
    print(f"Раскладки: {', '.join(config.layouts)}")
    print(f"Текущая раскладка: {switcher.get_current_layout(force=True)}")
    print(f"Переключение: {switcher.describe()}")
    print(f"Ввод текста: {injector.describe()}")
    print(f"Конфигурация: {config_path()}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Show, edit or reset the configuration file."""
    if args.config_action == "show":
        path = config_path()
        if not path.exists():
            save_config(Config())
        print(path.read_text(encoding="utf-8"))
        return 0
    if args.config_action == "edit":
        editor = os.environ.get("EDITOR", "nano")
        if not config_path().exists():
            save_config(Config())
        return subprocess.run([editor, str(config_path())], check=False).returncode
    if args.config_action == "reset":
        save_config(Config())
        print(MSG_CONFIG_RESET)
        return 0
    print("Использование: linguafix config show|edit|reset")
    return 2


def cmd_fix(args: argparse.Namespace) -> int:
    """Manually correct a piece of text."""
    config = load_config()
    text = args.text if args.text else sys.stdin.read().strip()
    if not text:
        print("Нет текста для исправления.")
        return 2

    converter = LayoutConverter()
    detector = LanguageDetector(
        converter=converter,
        stop_words=config.stop_words,
        min_word_length=config.min_word_length,
    )
    switcher = LayoutSwitcher(layouts=config.layouts, switch_method=config.switch_method)
    injector = TextInjector(converter=converter, backend=config.backend)

    current = switcher.get_current_layout(force=True)
    target = detector.target_layout(text, current)
    if target is None:
        print(f"Исправление не требуется (раскладка {current}).")
        return 0

    converted = converter.convert(text, current, target)
    print(f"{text} -> {converted} ({current} -> {target})")
    if args.apply and not args.dry_run:
        switcher.switch_to(target)
        time.sleep(0.05)
        if not injector.replace_text(text, converted, target):
            print("Не удалось применить исправление.")
            return 1
    elif args.dry_run:
        print("Режим --dry-run: изменения не применены.")
    return 0


def _bundled_data_file(name: str) -> Path | None:
    """Return the path of a bundled data file (icon, service, desktop)."""
    try:
        from importlib import resources

        candidate = Path(str(resources.files("linguafix") / "data" / name))
        if candidate.exists():
            return candidate
    except (ModuleNotFoundError, FileNotFoundError):
        pass
    # Fall back to the source tree layout when running from a checkout.
    fallback = Path(__file__).resolve().parent.parent.parent / "data" / name
    return fallback if fallback.exists() else None


def cmd_install_autostart(_args: argparse.Namespace) -> int:
    """Install the XDG autostart entry and enable the systemd user unit."""
    source = _bundled_data_file("linguafix.desktop")
    if source is None:
        print("Не найден файл linguafix.desktop.")
        return 1
    target = _autostart_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    unit_source = _bundled_data_file("linguafix.service")
    if unit_source is not None:
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        (unit_dir / "linguafix.service").write_text(
            unit_source.read_text(encoding="utf-8"), encoding="utf-8"
        )
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, capture_output=True)
    print(MSG_AUTOSTART_INSTALLED)
    return 0


def cmd_uninstall_autostart(_args: argparse.Namespace) -> int:
    """Remove the XDG autostart entry and disable the systemd user unit."""
    target = _autostart_path()
    if target.exists():
        target.unlink()
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", "linguafix.service"],
        check=False,
        capture_output=True,
    )
    print(MSG_AUTOSTART_REMOVED)
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    """Print the LinguaFix version."""
    print(f"LinguaFix {__version__}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="linguafix",
        description="LinguaFix — автоматический переключатель раскладки клавиатуры.",
    )
    parser.add_argument("--version", action="version", version=f"LinguaFix {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="запустить демон")
    start.add_argument("--foreground", action="store_true", help="не уходить в фон")
    start.add_argument(
        "--dry-run",
        action="store_true",
        help="анализировать, но не менять раскладку и не заменять текст",
    )
    start.set_defaults(func=cmd_start)

    stop = subparsers.add_parser("stop", help="остановить демон")
    stop.set_defaults(func=cmd_stop)

    status = subparsers.add_parser("status", help="показать статус")
    status.set_defaults(func=cmd_status)

    config = subparsers.add_parser("config", help="работа с конфигурацией")
    config.add_argument("config_action", choices=["show", "edit", "reset"])
    config.set_defaults(func=cmd_config)

    fix = subparsers.add_parser("fix", help="исправить текст вручную")
    fix.add_argument("--text", help="текст для исправления (иначе читается из stdin)")
    fix.add_argument("--apply", action="store_true", help="применить исправление на экране")
    fix.add_argument(
        "--dry-run",
        action="store_true",
        help="только показать исправление, ничего не применять",
    )
    fix.set_defaults(func=cmd_fix)

    install = subparsers.add_parser("install-autostart", help="включить автозапуск")
    install.set_defaults(func=cmd_install_autostart)

    uninstall = subparsers.add_parser("uninstall-autostart", help="выключить автозапуск")
    uninstall.set_defaults(func=cmd_uninstall_autostart)

    version = subparsers.add_parser("version", help="показать версию")
    version.set_defaults(func=cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``linguafix`` console script.

    Args:
        argv: Optional argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        The process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
