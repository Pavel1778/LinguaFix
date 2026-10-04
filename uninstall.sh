#!/usr/bin/env bash
#
# LinguaFix uninstaller. Removes the user service, autostart entry, icon and
# (with confirmation) the virtual environment and configuration.
set -uo pipefail

APP_NAME="linguafix"
SHARE_DIR="${HOME}/.local/share/${APP_NAME}"
VENV_DIR="${SHARE_DIR}/venv"
UNIT_DIR="${HOME}/.config/systemd/user"
AUTOSTART_DIR="${HOME}/.config/autostart"
ICON_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
CONFIG_DIR="${HOME}/.config/${APP_NAME}"
STATE_DIR="${HOME}/.local/state/${APP_NAME}"
CACHE_DIR="${HOME}/.cache/${APP_NAME}"
UDEV_RULE="/etc/udev/rules.d/71-${APP_NAME}.rules"

have() { command -v "$1" >/dev/null 2>&1; }

ASSUME_YES=0
PURGE=0
for arg in "$@"; do
    case "${arg}" in
        -y|--yes) ASSUME_YES=1 ;;
        --purge) PURGE=1; ASSUME_YES=1 ;;
        -h|--help)
            echo "Usage: bash uninstall.sh [--yes] [--purge]"
            exit 0
            ;;
    esac
done

log()  { printf '\033[1;34m[linguafix]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[linguafix]\033[0m %s\n' "$*" >&2; }

confirm() {
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

# Stop and disable the service.
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now "${APP_NAME}.service" >/dev/null 2>&1 || true
    systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

rm -f "${UNIT_DIR}/${APP_NAME}.service"
rm -f "${AUTOSTART_DIR}/${APP_NAME}.desktop"
rm -f "${ICON_DIR}/${APP_NAME}.svg"

if [ -f "${UDEV_RULE}" ] && confirm "Удалить udev-правило ${UDEV_RULE} (нужен sudo)?"; then
    sudo rm -f "${UDEV_RULE}"
    if have udevadm; then
        sudo udevadm control --reload-rules || true
    fi
fi

if confirm "Удалить виртуальное окружение ${VENV_DIR}?"; then
    rm -rf "${VENV_DIR}"
    # Remove the parent directory too when the venv was the only thing in it.
    rmdir "${SHARE_DIR}" 2>/dev/null || true
fi

if [ "${PURGE}" -eq 1 ] || confirm "Удалить конфигурацию и логи (${CONFIG_DIR}, ${STATE_DIR})?"; then
    rm -rf "${CONFIG_DIR}" "${STATE_DIR}" "${CACHE_DIR}"
fi

log "LinguaFix удалён. Группу input пользователю не удаляю (её используют другие инструменты)."
