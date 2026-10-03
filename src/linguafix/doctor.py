"""Environment self-diagnosis for LinguaFix.

The ``linguafix doctor`` command runs a series of read-only checks against the
running system (permissions, devices, external tools, session type, GNOME
version and the resolved backends) and prints a table with a status marker and a
hint for every failed or degraded check.

The module is deliberately free of side effects: it never changes the layout,
never writes text and never modifies the configuration.
"""

from __future__ import annotations

import grp
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Config, config_path, load_config
from .injector import TextInjector
from .switcher import LayoutSwitcher

logger = logging.getLogger(__name__)

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

_MARKER = {OK: "✅", WARN: "⚠️", FAIL: "❌"}

# Range of GNOME Shell versions for which g3kb-switch is known to work.
GNOME_MIN = 42
GNOME_MAX = 45

COMMAND_TIMEOUT = 5.0


@dataclass
class CheckResult:
    """The outcome of a single diagnostic check.

    Args:
        name: Human-readable check name.
        status: One of :data:`OK`, :data:`WARN` or :data:`FAIL`.
        detail: Short description of what was found.
        hint: Optional suggestion shown when the check did not pass.
    """

    name: str
    status: str
    detail: str
    hint: str = ""


def _session_type() -> str:
    """Return the current session type (``wayland``, ``x11`` or ``unknown``)."""
    return os.environ.get("XDG_SESSION_TYPE", "").lower() or "unknown"


def _gnome_major_version() -> int | None:
    """Return the major GNOME Shell version, or ``None`` if undetectable."""
    executable = shutil.which("gnome-shell")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for token in result.stdout.split():
        if token[:1].isdigit():
            try:
                return int(token.split(".")[0])
            except ValueError:
                return None
    return None


def _input_group_membership() -> bool:
    """Return ``True`` when the current user belongs to the ``input`` group."""
    try:
        names = {grp.getgrgid(gid).gr_name for gid in os.getgroups()}
    except (KeyError, OSError):  # pragma: no cover - defensive
        return False
    return "input" in names


# Directories where a distribution installs udev rules, in lookup order.
_UDEV_RULE_DIRS = (
    Path("/usr/lib/udev/rules.d"),
    Path("/etc/udev/rules.d"),
    Path("/run/udev/rules.d"),
)


def _uaccess_rule_present() -> bool:
    """Return ``True`` when an installed LinguaFix rule grants ``uaccess``.

    The packaged udev rule gives device access to the active session user with
    ``TAG+="uaccess"`` instead of adding the user to the ``input`` group, so a
    correct install can have read access without any group membership.
    """
    for directory in _UDEV_RULE_DIRS:
        try:
            rules = list(directory.glob("*linguafix*.rules"))
        except OSError:  # pragma: no cover - defensive
            continue
        for rule in rules:
            try:
                text = rule.read_text(encoding="utf-8", errors="replace")
            except OSError:  # pragma: no cover - defensive
                continue
            if 'TAG+="uaccess"' in text or "TAG+='uaccess'" in text:
                return True
    return False


def _readable_event_devices() -> tuple[int, int]:
    """Return ``(readable, total)`` counts for ``/dev/input/event*`` nodes."""
    total = 0
    readable = 0
    for path in sorted(Path("/dev/input").glob("event*")):
        total += 1
        if os.access(path, os.R_OK):
            readable += 1
    return readable, total


def check_device_access() -> CheckResult:
    """Check how access to the input devices is granted.

    A correct install grants it either through the packaged udev rule
    (``TAG+="uaccess"``, the .deb path) or, on the developer path, through
    membership of the ``input`` group. Either is accepted.
    """
    uaccess = _uaccess_rule_present()
    in_group = _input_group_membership()
    if uaccess:
        return CheckResult(
            "Правило доступа",
            OK,
            "udev-правило с uaccess установлено",
        )
    if in_group:
        return CheckResult(
            "Правило доступа",
            OK,
            "пользователь в группе input (dev-путь)",
        )
    return CheckResult(
        "Правило доступа",
        FAIL,
        "нет udev-правила с uaccess и нет группы input",
        "установите пакет .deb (udev-правило ставится автоматически) "
        "или на dev-пути скопируйте data/99-linguafix.rules в "
        "/etc/udev/rules.d/ и перелогиньтесь; подробнее — docs/TROUBLESHOOTING.md",
    )


def check_event_devices() -> CheckResult:
    """Check read access to ``/dev/input/event*``."""
    readable, total = _readable_event_devices()
    if total == 0:
        return CheckResult(
            "Устройства /dev/input/event*",
            WARN,
            "устройства не найдены",
            "проверьте, что вы в графической сессии и есть клавиатура",
        )
    if readable == 0:
        return CheckResult(
            "Устройства /dev/input/event*",
            FAIL,
            f"0 из {total} доступны для чтения",
            "перезагрузите udev-правило: sudo udevadm control --reload-rules && "
            "sudo udevadm trigger; проверьте getfacl (см. docs/TROUBLESHOOTING.md)",
        )
    return CheckResult(
        "Устройства /dev/input/event*",
        OK,
        f"{readable} из {total} доступны для чтения",
    )


def check_uinput() -> CheckResult:
    """Check that ``/dev/uinput`` exists and is writable."""
    path = Path("/dev/uinput")
    if not path.exists():
        return CheckResult(
            "Устройство /dev/uinput",
            WARN,
            "не найдено",
            "sudo modprobe uinput; бэкенд uinput будет недоступен",
        )
    if os.access(path, os.W_OK):
        return CheckResult("Устройство /dev/uinput", OK, "доступно для записи")
    return CheckResult(
        "Устройство /dev/uinput",
        FAIL,
        "нет прав на запись",
        "перезагрузите udev-правило: sudo udevadm control --reload-rules && "
        "sudo udevadm trigger; проверьте getfacl (см. docs/TROUBLESHOOTING.md)",
    )


def check_tools() -> CheckResult:
    """Check availability of the external layout/injection tools."""
    found: list[str] = []
    missing: list[str] = []
    for tool in ("g3kb-switch", "wtype", "xdotool", "setxkbmap"):
        if shutil.which(tool) is not None:
            found.append(tool)
        else:
            missing.append(tool)
    detail = "найдены: " + (", ".join(found) if found else "нет")
    if missing:
        detail += "; нет: " + ", ".join(missing)
    if "g3kb-switch" not in found and "setxkbmap" not in found:
        return CheckResult(
            "Внешние утилиты",
            FAIL,
            detail,
            "установите g3kb-switch (Wayland) или setxkbmap (X11)",
        )
    if "wtype" not in found and "xdotool" not in found:
        return CheckResult(
            "Внешние утилиты",
            WARN,
            detail,
            "нет wtype/xdotool; замена текста возможна только через uinput",
        )
    return CheckResult("Внешние утилиты", OK, detail)


def check_gnome_version() -> CheckResult:
    """Check the GNOME Shell version against the supported range."""
    version = _gnome_major_version()
    if version is None:
        return CheckResult(
            "Версия GNOME",
            WARN,
            "не удалось определить (gnome-shell не найден)",
            "переключение раскладки через g3kb-switch может не работать",
        )
    if GNOME_MIN <= version <= GNOME_MAX:
        return CheckResult(
            "Версия GNOME", OK, f"{version} (поддерживается {GNOME_MIN}–{GNOME_MAX})"
        )
    return CheckResult(
        "Версия GNOME",
        WARN,
        f"{version} вне диапазона {GNOME_MIN}–{GNOME_MAX}",
        "g3kb-switch может не работать; проверьте документацию расширения",
    )


def check_backends(config: Config) -> list[CheckResult]:
    """Resolve the switcher and injector backends and report them."""
    session = _session_type()
    switcher = LayoutSwitcher(layouts=config.layouts, switch_method=config.switch_method)
    injector = TextInjector(backend=config.backend)

    switcher_result = CheckResult(
        "Переключение раскладки",
        OK if switcher.backend != "none" else FAIL,
        switcher.describe(),
        "установите g3kb-switch или setxkbmap",
    )
    injector_result = CheckResult(
        "Замена текста",
        OK if injector.backend != "none" else FAIL,
        injector.describe(),
        "установите wtype (Wayland), xdotool (X11) или python3-uinput",
    )
    if session == "unknown":
        session_result = CheckResult(
            "Тип сессии",
            WARN,
            "unknown (XDG_SESSION_TYPE не задан)",
            "запустите doctor из графической сессии GNOME; из TTY/ssh "
            "переключение раскладки и замена текста недоступны",
        )
    else:
        session_result = CheckResult("Тип сессии", OK, session)
    return [session_result, switcher_result, injector_result]


def check_config(config: Config) -> CheckResult:
    """Report the configuration file location and layout list."""
    return CheckResult(
        "Конфигурация",
        OK,
        f"{config_path()} (раскладки: {', '.join(config.layouts)})",
    )


def collect_checks(config: Config | None = None) -> list[CheckResult]:
    """Run all checks and return their results in display order.

    Args:
        config: Optional configuration; loaded from disk when omitted.

    Returns:
        The list of check results.
    """
    cfg = config or load_config()
    results = [
        check_device_access(),
        check_event_devices(),
        check_uinput(),
        check_tools(),
        check_gnome_version(),
    ]
    results.extend(check_backends(cfg))
    results.append(check_config(cfg))
    return results


def render(results: list[CheckResult]) -> str:
    """Render the check results as a fixed-width table with markers.

    Args:
        results: Results produced by :func:`collect_checks`.

    Returns:
        The formatted table as a single string.
    """
    name_width = max((len(r.name) for r in results), default=0)
    lines: list[str] = []
    for result in results:
        marker = _MARKER.get(result.status, "?")
        line = f"{marker}  {result.name.ljust(name_width)}  {result.detail}"
        lines.append(line)
        if result.hint and result.status != OK:
            lines.append(f"   {' ' * name_width}  ↳ {result.hint}")
    return "\n".join(lines)


def has_failures(results: list[CheckResult]) -> bool:
    """Return ``True`` when any check has the :data:`FAIL` status."""
    return any(result.status == FAIL for result in results)


def run_doctor(config: Config | None = None) -> int:
    """Run the diagnostics, print the table and return an exit code.

    Args:
        config: Optional configuration override.

    Returns:
        ``0`` when no check failed, ``1`` otherwise.
    """
    results = collect_checks(config)
    print("LinguaFix doctor")
    print("=" * 40)
    print(render(results))
    print()
    if has_failures(results):
        print("Итог: есть проблемы, см. подсказки выше.")
        return 1
    print("Итог: критических проблем не найдено.")
    return 0
