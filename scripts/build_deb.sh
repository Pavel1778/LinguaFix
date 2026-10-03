#!/usr/bin/env bash
#
# Build a Debian package for LinguaFix without dh_make, using dpkg-deb directly.
#
# Layout of the resulting package:
#   /usr/bin/linguafix                              launcher wrapper
#   /usr/lib/linguafix/linguafix/...                Python package + data
#   /usr/share/applications/linguafix.desktop       desktop entry
#   /usr/share/icons/hicolor/scalable/apps/*.svg    icon
#   /usr/lib/systemd/user/linguafix.service         systemd user unit
#   /lib/udev/rules.d/99-linguafix.rules            udev rule
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"

VERSION="$(grep -m1 '^version' pyproject.toml | sed -E 's/.*"([^"]+)".*/\1/')"
PKG="linguafix"
ARCH="all"
BUILD_DIR="${REPO_DIR}/build/${PKG}_${VERSION}_${ARCH}"
DIST_DIR="${REPO_DIR}/dist"

echo "[linguafix] Building ${PKG} ${VERSION} (${ARCH})"

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}/DEBIAN"
# A setgid bit inherited from the parent directory makes dpkg-deb reject the
# control directory, so strip it explicitly.
chmod g-s "${BUILD_DIR}" "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/usr/lib/${PKG}"
mkdir -p "${BUILD_DIR}/usr/share/applications"
mkdir -p "${BUILD_DIR}/usr/share/icons/hicolor/scalable/apps"
mkdir -p "${BUILD_DIR}/usr/lib/systemd/user"
mkdir -p "${BUILD_DIR}/lib/udev/rules.d"
mkdir -p "${DIST_DIR}"

# --- Python package ---------------------------------------------------------
cp -r "${REPO_DIR}/src/${PKG}" "${BUILD_DIR}/usr/lib/${PKG}/${PKG}"
find "${BUILD_DIR}/usr/lib/${PKG}" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${BUILD_DIR}/usr/lib/${PKG}" -name '*.pyc' -delete
# Normalise permissions regardless of the developer's umask.
chmod -R a+rX "${BUILD_DIR}/usr/lib/${PKG}"

# --- Launcher wrapper -------------------------------------------------------
cat > "${BUILD_DIR}/usr/bin/${PKG}" <<'EOF'
#!/bin/sh
# LinguaFix launcher: run the packaged module with the system Python.
PYTHONPATH="/usr/lib/linguafix${PYTHONPATH:+:${PYTHONPATH}}" \
    exec /usr/bin/python3 -m linguafix "$@"
EOF
chmod 0755 "${BUILD_DIR}/usr/bin/${PKG}"

# --- Data files -------------------------------------------------------------
install -m 0644 "${REPO_DIR}/data/${PKG}.svg" \
    "${BUILD_DIR}/usr/share/icons/hicolor/scalable/apps/${PKG}.svg"
install -m 0644 "${REPO_DIR}/data/${PKG}.desktop" \
    "${BUILD_DIR}/usr/share/applications/${PKG}.desktop"
install -m 0644 "${REPO_DIR}/data/${PKG}.service" \
    "${BUILD_DIR}/usr/lib/systemd/user/${PKG}.service"
install -m 0644 "${REPO_DIR}/data/99-${PKG}.rules" \
    "${BUILD_DIR}/lib/udev/rules.d/99-${PKG}.rules"

# --- DEBIAN/control ---------------------------------------------------------
INSTALLED_SIZE="$(du -sk "${BUILD_DIR}" | cut -f1)"
cat > "${BUILD_DIR}/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10), python3-evdev, python3-uinput, libnotify-bin, wtype
Recommends: g3kb-switch, xdotool, python3-gi, gir1.2-appindicator3-0.1
Installed-Size: ${INSTALLED_SIZE}
Maintainer: Pavel1778 <noreply@github.com>
Homepage: https://github.com/Pavel1778/LinguaFix
Description: Automatic keyboard layout switcher for Debian GNOME
 LinguaFix is a background daemon that detects text typed in the wrong
 keyboard layout (for example "ghbdtn" instead of "привет") and fixes it
 automatically. It works on both X11 and Wayland.
EOF

# --- DEBIAN/postinst --------------------------------------------------------
cat > "${BUILD_DIR}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger || true
fi

if [ -n "${SUDO_USER:-}" ]; then
    TARGET_USER="${SUDO_USER}"
elif [ -n "${USER:-}" ]; then
    TARGET_USER="${USER}"
fi

if [ -n "${TARGET_USER:-}" ] && [ "${TARGET_USER}" != "root" ]; then
    if ! id -nG "${TARGET_USER}" | grep -qw input; then
        adduser "${TARGET_USER}" input || true
        echo "LinguaFix: пользователь ${TARGET_USER} добавлен в группу input."
        echo "LinguaFix: выйдите из системы и войдите снова, чтобы изменения вступили в силу."
    fi
fi

echo "LinguaFix установлен. Запустите: linguafix start"
EOF
chmod 0755 "${BUILD_DIR}/DEBIAN/postinst"

# --- DEBIAN/prerm -----------------------------------------------------------
cat > "${BUILD_DIR}/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now linguafix.service >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "${BUILD_DIR}/DEBIAN/prerm"

# --- DEBIAN/postrm ----------------------------------------------------------
cat > "${BUILD_DIR}/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger || true
fi
exit 0
EOF
chmod 0755 "${BUILD_DIR}/DEBIAN/postrm"

# --- Build ------------------------------------------------------------------
dpkg-deb --build --root-owner-group "${BUILD_DIR}" "${DIST_DIR}/${PKG}_${VERSION}_${ARCH}.deb"

echo "[linguafix] Package built: ${DIST_DIR}/${PKG}_${VERSION}_${ARCH}.deb"
