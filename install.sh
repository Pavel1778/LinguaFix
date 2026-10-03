#!/usr/bin/env bash
#
# LinguaFix installer for Debian / Ubuntu (GNOME, X11 or Wayland).
#
# The script is idempotent: running it again re-installs/updates the same
# components without duplicating anything. Pass --yes for a non-interactive run.
set -uo pipefail

APP_NAME="linguafix"
# USER is not guaranteed to be set (cron, su, some containers). Fall back to id.
CURRENT_USER="${SUDO_USER:-${USER:-$(id -un)}}"
VENV_DIR="${HOME}/.local/share/${APP_NAME}/venv"
BIN="${VENV_DIR}/bin/${APP_NAME}"
UNIT_DIR="${HOME}/.config/systemd/user"
AUTOSTART_DIR="${HOME}/.config/autostart"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
UDEV_RULE="/etc/udev/rules.d/99-${APP_NAME}.rules"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ASSUME_YES=0
for arg in "$@"; do
    case "${arg}" in
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help)
            echo "Usage: bash install.sh [--yes]"
            exit 0
            ;;
    esac
done

log()  { printf '\033[1;34m[linguafix]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[linguafix]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[linguafix]\033[0m %s\n' "$*" >&2; }

confirm() {
    # confirm <prompt> -> 0 (yes) / 1 (no)
    if [ "${ASSUME_YES}" -eq 1 ]; then
        return 0
    fi
    local reply
    read -r -p "$1 [y/N] " reply
    case "${reply}" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# 1. Distribution check
# ---------------------------------------------------------------------------
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}:${ID_LIKE:-}" in
        debian*|ubuntu*|*debian*|*ubuntu*) : ;;
        *) warn "Система не похожа на Debian/Ubuntu (ID=${ID:-unknown}); продолжаю." ;;
    esac
else
    warn "Не удалось прочитать /etc/os-release; продолжаю."
fi

# ---------------------------------------------------------------------------
# 2. Python check
# ---------------------------------------------------------------------------
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if have "${candidate}"; then
        if "${candidate}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
            PYTHON="${candidate}"
            break
        fi
    fi
done
if [ -z "${PYTHON}" ]; then
    err "Требуется Python 3.10+. Установите: sudo apt install python3"
    exit 1
fi
log "Использую интерпретатор: ${PYTHON} ($(${PYTHON} --version 2>&1))"

# ---------------------------------------------------------------------------
# 3. System dependencies
# ---------------------------------------------------------------------------
APT_PACKAGES="python3-venv python3-pip python3-evdev python3-uinput python3-gi gir1.2-appindicator3-0.1 wtype xdotool libnotify-bin"
if have apt-get; then
    if confirm "Установить системные зависимости через apt (нужен sudo)?"; then
        sudo apt-get update
        # Install packages individually: some (for example python3-uinput on
        # Ubuntu) may not exist in every release, and one missing name must not
        # abort the whole install. Missing optional packages fall back to the
        # virtualenv-provided equivalents.
        for pkg in ${APT_PACKAGES}; do
            if apt-cache show "${pkg}" >/dev/null 2>&1; then
                sudo apt-get install -y "${pkg}" || warn "Не удалось установить ${pkg}."
            else
                warn "Пакет ${pkg} недоступен в этом репозитории; пропускаю."
            fi
        done
    else
        log "Пропускаю установку системных пакетов."
    fi
else
    warn "apt-get не найден. Установите зависимости вручную: ${APT_PACKAGES}"
fi

# ---------------------------------------------------------------------------
# 4. GNOME version check and optional g3kb-switch
# ---------------------------------------------------------------------------
GNOME_VERSION="$(gnome-shell --version 2>/dev/null | grep -oE '[0-9]+' | head -1 || true)"
if [ -n "${GNOME_VERSION}" ]; then
    if [ "${GNOME_VERSION}" -ge 42 ] && [ "${GNOME_VERSION}" -le 45 ]; then
        log "Обнаружен GNOME ${GNOME_VERSION} (поддерживается: 42–45)."
    else
        warn "GNOME ${GNOME_VERSION} вне протестированного диапазона (42–45)."
        warn "Переключение раскладки через g3kb-switch может не работать."
    fi
else
    warn "Не удалось определить версию GNOME (gnome-shell не найден)."
fi

if have g3kb-switch; then
    log "g3kb-switch уже установлен."
else
    warn "g3kb-switch не найден — переключение раскладки в GNOME Wayland работать не будет."
    warn "g3kb-switch требует расширение GNOME Shell и поддерживает GNOME 42–45."
    warn "Установите его отдельно (см. https://github.com/dvorka/g3kb-switch) или через:"
    warn "  sudo apt install g3kb-switch    # если пакет доступен в вашем репозитории"
fi

# ---------------------------------------------------------------------------
# 5. Virtual environment + package install
# ---------------------------------------------------------------------------
log "Создаю виртуальное окружение: ${VENV_DIR}"
mkdir -p "$(dirname "${VENV_DIR}")"
if [ ! -x "${VENV_DIR}/bin/python" ]; then
    # Reuse apt-installed python3-evdev/python3-uinput via the system site
    # packages; otherwise pip rebuilds python-uinput from source, which fails
    # on a clean Debian without build tools.
    "${PYTHON}" -m venv --system-site-packages "${VENV_DIR}"
fi
"${VENV_DIR}/bin/pip" install --upgrade pip >/dev/null
log "Устанавливаю пакет (editable) из ${REPO_DIR}"
"${VENV_DIR}/bin/pip" install -e "${REPO_DIR}"

# ---------------------------------------------------------------------------
# 6. udev rule
# ---------------------------------------------------------------------------
if [ -f "${REPO_DIR}/data/99-${APP_NAME}.rules" ]; then
    if confirm "Установить udev-правило в ${UDEV_RULE} (нужен sudo)?"; then
        sudo mkdir -p "$(dirname "${UDEV_RULE}")"
        sudo install -m 0644 "${REPO_DIR}/data/99-${APP_NAME}.rules" "${UDEV_RULE}"
        if have udevadm; then
            sudo udevadm control --reload-rules || true
            sudo udevadm trigger || true
        fi
    else
        log "Пропускаю установку udev-правила."
    fi
fi

# ---------------------------------------------------------------------------
# 7. uinput module
# ---------------------------------------------------------------------------
# Access to /dev/input and /dev/uinput is granted by the udev rule above via
# TAG+="uaccess" (the active session user), so no group membership is needed.
# Only load the module so /dev/uinput exists.
if have modprobe; then
    sudo modprobe uinput 2>/dev/null || warn "Не удалось загрузить модуль uinput."
fi

# ---------------------------------------------------------------------------
# 8. systemd user service
# ---------------------------------------------------------------------------
mkdir -p "${UNIT_DIR}"
if [ -f "${REPO_DIR}/data/${APP_NAME}.service" ]; then
    # data/*.service and data/*.desktop carry a "@BIN@" placeholder so that both
    # install.sh (venv launcher) and the .deb (/usr/bin/linguafix) can share them.
    sed "s|@BIN@|${BIN}|g" "${REPO_DIR}/data/${APP_NAME}.service" \
        > "${UNIT_DIR}/${APP_NAME}.service"
    chmod 0644 "${UNIT_DIR}/${APP_NAME}.service"
    log "Установлен systemd user service: ${UNIT_DIR}/${APP_NAME}.service"
fi

# ---------------------------------------------------------------------------
# 9. XDG autostart
# ---------------------------------------------------------------------------
mkdir -p "${AUTOSTART_DIR}"
if [ -f "${REPO_DIR}/data/${APP_NAME}.desktop" ]; then
    sed "s|@BIN@|${BIN}|g" "${REPO_DIR}/data/${APP_NAME}.desktop" \
        > "${AUTOSTART_DIR}/${APP_NAME}.desktop"
    chmod 0644 "${AUTOSTART_DIR}/${APP_NAME}.desktop"
    log "Установлен автозапуск: ${AUTOSTART_DIR}/${APP_NAME}.desktop"
fi

# ---------------------------------------------------------------------------
# 10. Icon
# ---------------------------------------------------------------------------
if [ -f "${REPO_DIR}/data/${APP_NAME}.svg" ]; then
    mkdir -p "${ICON_DIR}"
    install -m 0644 "${REPO_DIR}/data/${APP_NAME}.svg" "${ICON_DIR}/${APP_NAME}.svg"
    gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi

# ---------------------------------------------------------------------------
# 11. Enable and start the service
# ---------------------------------------------------------------------------
if have systemctl; then
    systemctl --user daemon-reload || true
    systemctl --user enable --now "${APP_NAME}.service" || \
        warn "Не удалось включить сервис (возможно, нет активной user-сессии)."
fi

# ---------------------------------------------------------------------------
# 12. Notification
# ---------------------------------------------------------------------------
if have notify-send; then
    notify-send "${APP_NAME}" "LinguaFix установлен и запущен" || true
fi

# ---------------------------------------------------------------------------
# 13. Self-test
# ---------------------------------------------------------------------------
if [ -x "${BIN}" ]; then
    log "Самодиагностика (linguafix doctor):"
    "${BIN}" doctor || warn "Диагностика нашла проблемы — см. вывод выше."
fi

# ---------------------------------------------------------------------------
# 14. Final instructions
# ---------------------------------------------------------------------------
echo
log "Готово!"
cat <<EOF

Проверка:
  ${BIN} doctor
  ${BIN} status
  systemctl --user status ${APP_NAME}.service
  journalctl --user -u ${APP_NAME}.service -n 50 --no-pager

Конфигурация: ~/.config/${APP_NAME}/config.toml
Логи:         ~/.local/state/${APP_NAME}/${APP_NAME}.log

Если что-то не работает, см. docs/TROUBLESHOOTING.md.
EOF
