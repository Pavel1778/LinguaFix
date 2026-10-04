"""Command line interface for LinguaFix.

The CLI is intentionally thin: it starts and stops the daemon, inspects status,
manages the configuration file and can trigger a manual correction.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .collect_logs import collect_logs
from .config import Config, cache_dir, config_path, load_config, save_config
from .converter import LayoutConverter
from .detector import LanguageDetector
from .doctor import run_doctor
from .injector import TextInjector
from .switcher import LayoutSwitcher

logger = logging.getLogger(__name__)

LOCK_FILE_NAME = "daemon.lock"
START_TIMEOUT = 5.0
# How long ``stop`` waits for a graceful SIGTERM exit before escalating. The
# budget is 3 s; SIGKILL is sent after 2 s so ``stop`` always returns in time.
STOP_GRACE = 2.0
STOP_POLL = 0.1

# Russian user-facing strings (English duplicates live in the README).
MSG_NOT_RUNNING = "LinguaFix не запущен."
MSG_STOPPED = "LinguaFix остановлен."
MSG_STOPPED_FORCED = "LinguaFix не ответил на SIGTERM; отправлен SIGKILL."
MSG_KILLED = "LinguaFix принудительно завершён (SIGKILL)."
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


def _wait_for_exit(pid: int, timeout: float) -> bool:
    """Wait up to ``timeout`` seconds for ``pid`` to disappear."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(STOP_POLL)
    return not _pid_alive(pid)


def cmd_stop(_args: argparse.Namespace) -> int:
    """Stop a running daemon, escalating to SIGKILL if it does not respond."""
    pid = _read_pid()
    if pid is None:
        print(MSG_ALREADY_STOPPED)
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print(MSG_ALREADY_STOPPED)
        return 0
    except OSError as exc:
        print(f"Не удалось остановить LinguaFix: {exc}")
        return 1

    if _wait_for_exit(pid, STOP_GRACE):
        print(MSG_STOPPED)
        return 0

    # The daemon is wedged (for example stuck in a subprocess); escalate.
    logger.warning("PID %d did not exit within %.1fs; sending SIGKILL", pid, STOP_GRACE)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError as exc:
        print(f"Не удалось принудительно остановить LinguaFix: {exc}")
        return 1
    _wait_for_exit(pid, STOP_GRACE)
    print(MSG_STOPPED_FORCED)
    return 0


def cmd_kill(_args: argparse.Namespace) -> int:
    """Force-stop a running daemon with SIGKILL, without a graceful attempt."""
    pid = _read_pid()
    if pid is None:
        print(MSG_ALREADY_STOPPED)
        return 0
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        print(MSG_ALREADY_STOPPED)
        return 0
    except OSError as exc:
        print(f"Не удалось завершить LinguaFix: {exc}")
        return 1
    _wait_for_exit(pid, STOP_GRACE)
    print(MSG_KILLED)
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
    print(f"Режим: {config.mode}")
    print(f"Переключение: {switcher.describe()}")
    print(f"Ввод текста: {injector.describe()}")
    print(f"Конфигурация: {config_path()}")
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    """Show or change the working mode (auto/manual/hybrid)."""
    config = load_config()
    if args.mode is None:
        print(config.mode)
        return 0
    config.mode = args.mode
    try:
        config.validate()
    except ValueError as exc:
        print(f"Недопустимый режим: {exc}")
        return 2
    save_config(config)
    print(f"Режим: {config.mode}")
    return 0


def cmd_undo(_args: argparse.Namespace) -> int:
    """Ask a running daemon to undo its most recent correction."""
    pid = _read_pid()
    if pid is None:
        print(MSG_NOT_RUNNING)
        return 1
    try:
        os.kill(pid, signal.SIGUSR1)
    except OSError as exc:
        print(f"Не удалось отменить исправление: {exc}")
        return 1
    print("Запрошена отмена последнего исправления.")
    return 0


def cmd_dict(args: argparse.Namespace) -> int:
    """Manage the user dictionary (words that are never corrected)."""
    from .dictionary import add_user_word, load_user_dictionary, save_user_dictionary

    path = config_path_for_dict()
    action = args.dict_action
    if action == "list":
        words = load_user_dictionary(str(path))
        if not words:
            print(f"Словарь пуст ({path}).")
            return 0
        print("\n".join(words))
        return 0
    if action == "add":
        if not args.word:
            print("Укажите слово: linguafix dict add <слово>")
            return 2
        words = add_user_word(args.word, str(path))
        print(f"Добавлено. Всего слов: {len(words)}.")
        return 0
    if action == "remove":
        if not args.word:
            print("Укажите слово: linguafix dict remove <слово>")
            return 2
        words = load_user_dictionary(str(path))
        remaining = [w for w in words if w.lower() != args.word.lower()]
        if len(remaining) == len(words):
            print(f"Слово {args.word!r} не найдено.")
            return 1
        save_user_dictionary(remaining, str(path))
        print(f"Удалено. Всего слов: {len(remaining)}.")
        return 0
    print("Использование: linguafix dict list|add <слово>|remove <слово>")
    return 2


def config_path_for_dict() -> Path:
    """Return the user-dictionary path from the current configuration."""
    from .dictionary import user_dictionary_path

    return user_dictionary_path(load_config().dictionary_custom_path)


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
        try:
            # Not captured: the editor needs the terminal.
            return subprocess.run([editor, str(config_path())], check=False).returncode
        except OSError as exc:
            print(f"Не удалось запустить редактор {editor}: {exc}")
            return 1
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
    # Keep the dry-run contract identical to the daemon: report the intended
    # action to the logger as well as to stdout, then do not touch anything.
    logger.info("fix: %d chars, %s -> %s", len(text), current, target)
    print(f"{text} -> {converted} ({current} -> {target})")
    if args.dry_run:
        logger.info("Dry run: skipping layout switch and text replacement")
        print("Режим --dry-run: изменения не применены.")
        return 0
    if args.apply:
        switcher.switch_to(target)
        time.sleep(0.05)
        if not injector.replace_text(len(text), converted, target):
            print("Не удалось применить исправление.")
            return 1
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


def _run_quiet(argv: list[str]) -> int:
    """Run ``argv`` ignoring failures, including a missing executable.

    ``check=False`` does not suppress ``FileNotFoundError`` when the binary is
    absent (for example ``systemctl`` in a container), so it is caught here.
    """
    try:
        return subprocess.run(argv, check=False, capture_output=True).returncode
    except OSError as exc:
        logger.debug("Command %s failed: %s", argv, exc)
        return 127


def _launcher_path() -> str:
    """Return the path used to launch the daemon from the unit/autostart files."""
    launcher = shutil.which("linguafix")
    if launcher:
        return launcher
    return str(Path(sys.executable).with_name("linguafix"))


def _render_template(text: str) -> str:
    """Substitute the ``@BIN@`` placeholder with the launcher path."""
    return text.replace("@BIN@", _launcher_path())


def cmd_install_autostart(_args: argparse.Namespace) -> int:
    """Install the XDG autostart entry and enable the systemd user unit."""
    source = _bundled_data_file("linguafix-autostart.desktop")
    if source is None:
        print("Не найден файл linguafix.desktop.")
        return 1
    target = _autostart_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_render_template(source.read_text(encoding="utf-8")), encoding="utf-8")

    unit_source = _bundled_data_file("linguafix.service")
    if unit_source is not None:
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True, exist_ok=True)
        (unit_dir / "linguafix.service").write_text(
            _render_template(unit_source.read_text(encoding="utf-8")), encoding="utf-8"
        )
        _run_quiet(["systemctl", "--user", "daemon-reload"])
    print(MSG_AUTOSTART_INSTALLED)
    return 0


def cmd_uninstall_autostart(_args: argparse.Namespace) -> int:
    """Remove the XDG autostart entry and disable the systemd user unit."""
    target = _autostart_path()
    if target.exists():
        target.unlink()
    _run_quiet(["systemctl", "--user", "disable", "--now", "linguafix.service"])
    print(MSG_AUTOSTART_REMOVED)
    return 0


def cmd_gui(_args: argparse.Namespace) -> int:
    """Open the GTK4 graphical interface."""
    from .gui import main as gui_main

    return gui_main()


def cmd_version(_args: argparse.Namespace) -> int:
    """Print the LinguaFix version."""
    print(f"LinguaFix {__version__}")
    return 0


def cmd_collect_logs(args: argparse.Namespace) -> int:
    """Build a diagnostic tarball for a bug report."""
    output_dir = Path(args.output).expanduser() if args.output else None
    try:
        archive = collect_logs(output_dir)
    except OSError as exc:
        print(f"Не удалось создать архив: {exc}")
        return 1
    print(f"Диагностический архив создан: {archive}")
    print("Приложите его к issue на GitHub (текст, который вы набирали, в него не попадает).")
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Run environment self-diagnosis and print a status table."""
    return run_doctor()


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

    kill = subparsers.add_parser("kill", help="принудительно завершить зависший демон (SIGKILL)")
    kill.set_defaults(func=cmd_kill)

    status = subparsers.add_parser("status", help="показать статус")
    status.set_defaults(func=cmd_status)

    mode = subparsers.add_parser("mode", help="показать или сменить режим (auto/manual/hybrid)")
    mode.add_argument("mode", nargs="?", choices=["auto", "manual", "hybrid"], default=None)
    mode.set_defaults(func=cmd_mode)

    undo = subparsers.add_parser("undo", help="отменить последнее исправление")
    undo.set_defaults(func=cmd_undo)

    dict_parser = subparsers.add_parser("dict", help="словарь слов, которые не исправлять")
    dict_parser.add_argument("dict_action", choices=["list", "add", "remove"])
    dict_parser.add_argument("word", nargs="?", help="слово для add/remove")
    dict_parser.set_defaults(func=cmd_dict)

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

    doctor = subparsers.add_parser("doctor", help="самодиагностика окружения")
    doctor.set_defaults(func=cmd_doctor)

    collect = subparsers.add_parser("collect-logs", help="собрать диагностический архив для issue")
    collect.add_argument(
        "--output",
        metavar="DIR",
        help="каталог для архива (по умолчанию — домашний каталог)",
    )
    collect.set_defaults(func=cmd_collect_logs)

    install = subparsers.add_parser("install-autostart", help="включить автозапуск")
    install.set_defaults(func=cmd_install_autostart)

    uninstall = subparsers.add_parser("uninstall-autostart", help="выключить автозапуск")
    uninstall.set_defaults(func=cmd_uninstall_autostart)

    version = subparsers.add_parser("version", help="показать версию")
    version.set_defaults(func=cmd_version)

    gui = subparsers.add_parser("gui", help="открыть графический интерфейс (GTK4)")
    gui.set_defaults(func=cmd_gui)

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
