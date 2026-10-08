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
#   /usr/lib/udev/rules.d/71-linguafix.rules        udev rule
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
mkdir -p "${BUILD_DIR}/usr/lib/udev/rules.d"
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
# The service and desktop files carry a "@BIN@" placeholder for the launcher
# path: install.sh renders it with the venv binary, the .deb with /usr/bin.
render_unit() {
    local src="$1" dest="$2" bin="$3"
    sed "s|@BIN@|${bin}|g" "${src}" > "${dest}"
    chmod 0644 "${dest}"
}
render_unit "${REPO_DIR}/data/${PKG}.desktop" \
    "${BUILD_DIR}/usr/share/applications/${PKG}.desktop" "/usr/bin/${PKG}"
render_unit "${REPO_DIR}/data/${PKG}.service" \
    "${BUILD_DIR}/usr/lib/systemd/user/${PKG}.service" "/usr/bin/${PKG}"
install -m 0644 "${REPO_DIR}/data/71-${PKG}.rules" \
    "${BUILD_DIR}/usr/lib/udev/rules.d/71-${PKG}.rules"

# --- DEBIAN/control ---------------------------------------------------------
INSTALLED_SIZE="$(du -sk "${BUILD_DIR}" | cut -f1)"
cat > "${BUILD_DIR}/DEBIAN/control" <<EOF
Package: ${PKG}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.10), python3-tomli | python3 (>= 3.11), python3-tomli-w, python3-evdev, libnotify-bin, wtype, librsvg2-common, hicolor-icon-theme
Recommends: g3kb-switch, xdotool, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-appindicator3-0.1, python3-pyatspi, gir1.2-atspi-2.0, wl-clipboard, xclip
Installed-Size: ${INSTALLED_SIZE}
Maintainer: Pavel1778 <noreply@github.com>
Homepage: https://github.com/Pavel1778/LinguaFix
Description: Automatic keyboard layout switcher for Debian GNOME
 LinguaFix is a background daemon that detects text typed in the wrong
 keyboard layout (for example "ghbdtn" instead of "привет") and fixes it
 automatically. It works on both X11 and Wayland.
EOF

# --- DEBIAN/postinst --------------------------------------------------------
# The package is zero-config: installing it must not ask the user to run
# usermod, to relogin or to enable anything by hand.
#
#   * device access is granted by the udev rule via TAG+="uaccess" (see
#     data/71-linguafix.rules), so no group membership is touched;
#   * the uinput module is loaded so /dev/uinput appears;
#   * the user unit is enabled globally so it starts at the next login. It is
#     deliberately not started here: the package may be installed without a
#     running graphical session.
cat > "${BUILD_DIR}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e

# Reload udev so the uaccess ACLs are applied to the device nodes.
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules || true
    udevadm trigger || true
fi

# Refresh the desktop database so the application menu shows LinguaFix right
# after installation, without waiting for a re-login or a desktop refresh.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi

# Rebuild the icon cache so the launcher picks up the icon immediately.
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi

# Load uinput so /dev/uinput exists (best effort; a container may lack it).
if command -v modprobe >/dev/null 2>&1; then
    modprobe uinput 2>/dev/null || true
fi

# Reload the systemd user manager after the unit file was replaced, so a later
# ``systemctl --user restart linguafix.service`` does not warn that the unit
# changed on disk. Best effort: an install without a running user bus still
# succeeds.
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
fi

# Enable the user unit for every user, without touching anyone's session.
# --global writes the symlink under /etc/systemd/user, which is what makes the
# service start on the next login. Do not fail the install if systemd is absent.
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user enable --global linguafix.service >/dev/null 2>&1 || true
fi

echo "LinguaFix установлен. Сервис запустится при следующем входе в сессию."
EOF
chmod 0755 "${BUILD_DIR}/DEBIAN/postinst"

# --- DEBIAN/prerm -----------------------------------------------------------
# Called on remove and on upgrade. Disable the global enablement so an upgrade
# can re-establish it, and stop the unit for any user who has a session.
cat > "${BUILD_DIR}/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --global linguafix.service >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 0755 "${BUILD_DIR}/DEBIAN/prerm"

# --- DEBIAN/postrm ----------------------------------------------------------
# On purge, remove the global enablement and the per-user state, and reload
# udev so the ACLs are dropped. Other users' data is never touched beyond the
# files that belong to this package.
cat > "${BUILD_DIR}/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e

case "${1:-}" in
    remove|purge)
        # Running the CLI (and ``doctor``) as root leaves root-owned bytecode
        # under /usr/lib, which dpkg does not track. Drop it, then prune the
        # directories it leaves empty, so a purge leaves nothing behind.
        if command -v py3clean >/dev/null 2>&1; then
            py3clean /usr/lib/linguafix >/dev/null 2>&1 || true
        fi
        if [ -d /usr/lib/linguafix ]; then
            find /usr/lib/linguafix -type d -name '__pycache__' \
                -prune -exec rm -rf {} + 2>/dev/null || true
            find /usr/lib/linguafix -depth -type d -empty \
                -exec rmdir {} + 2>/dev/null || true
        fi
        ;;
esac

case "${1:-}" in
    purge)
        if command -v systemctl >/dev/null 2>&1; then
            systemctl --user disable --global linguafix.service >/dev/null 2>&1 || true
        fi
        rm -rf /etc/systemd/user/default.target.wants/linguafix.service
        # Per-user state for the user that requested the install, when known.
        for candidate in "${SUDO_USER:-}" "${USER:-}"; do
            [ -n "${candidate}" ] || continue
            [ "${candidate}" = "root" ] && continue
            home="$(getent passwd "${candidate}" | cut -d: -f6)"
            [ -n "${home}" ] || continue
            rm -rf "${home}/.config/linguafix" \
                   "${home}/.local/share/linguafix" \
                   "${home}/.local/state/linguafix" \
                   "${home}/.cache/linguafix"
        done
        ;;
esac

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
