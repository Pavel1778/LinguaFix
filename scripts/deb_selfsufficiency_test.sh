#!/usr/bin/env bash
# Zero-config (.deb self-sufficiency) test.
#
# Proves that `apt install ./linguafix_*.deb` needs no manual step: no usermod,
# no relogin, no `systemctl --user enable` typed by the user, no modprobe. The
# package must install its udev rule (uaccess), its user unit and all data files
# by itself, and `apt remove --purge` must leave the system clean.
#
# Unlike smoke_test.sh (which checks the CLI runs), this script checks the
# *packaging contract*. It runs in a clean container without a graphical
# session, so it verifies files and enablement, not live device ACLs.
#
# Usage:
#   bash scripts/deb_selfsufficiency_test.sh [path/to/linguafix_*.deb]
#
# Environment:
#   SMOKE_IMAGE   Docker image to use (default: debian:12)
#
# Exits non-zero when any check fails.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_IMAGE="${SMOKE_IMAGE:-debian:12}"
DEB="${1:-}"

log() { printf '\033[1;34m[zero-config]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[zero-config] FAIL:\033[0m %s\n' "$*" >&2; exit 1; }

if [ -z "${DEB}" ]; then
    DEB="$(ls -1 "${REPO_DIR}"/dist/linguafix_*.deb 2>/dev/null | head -1 || true)"
fi
[ -n "${DEB}" ] && [ -f "${DEB}" ] || fail "no .deb found; run 'make build-deb' first"
log "Testing package: ${DEB} (image: ${SMOKE_IMAGE})"

DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
    $DOCKER info >/dev/null 2>&1 || fail "Docker is not available"
fi

DEB_DIR="$(cd "$(dirname "${DEB}")" && pwd)"
DEB_NAME="$(basename "${DEB}")"

$DOCKER run --rm -v "${DEB_DIR}:/pkg:ro" "${SMOKE_IMAGE}" bash -c '
set -e

say() { printf "\n== %s ==\n" "$1"; }
check() { # check <description> <command...>
    if "$@" >/dev/null 2>&1; then
        echo "ok   - ${1}"
    else
        echo "FAIL - ${1}"
        exit 1
    fi
}
expect_absent() { # expect_absent <path>
    if [ -e "$1" ]; then echo "FAIL - still present: $1"; exit 1; fi
    echo "ok   - absent: $1"
}

export DEBIAN_FRONTEND=noninteractive
# systemd provides systemctl; the package Recommends it via the base system.
apt-get update -qq
apt-get install -y -qq systemd >/dev/null 2>&1 || true
apt-get install -y -qq "/pkg/'"${DEB_NAME}"'" >/dev/null

say "1. udev rule installed and uses uaccess (not the input group)"
RULES=/usr/lib/udev/rules.d/71-linguafix.rules
test -f "${RULES}" || { echo "FAIL - udev rule not installed at ${RULES}"; exit 1; }
grep -q "TAG+=\"uaccess\"" "${RULES}" || { echo "FAIL - rule has no uaccess"; exit 1; }
! grep -q "GROUP=\"input\"" "${RULES}" || { echo "FAIL - rule still uses GROUP=input"; exit 1; }
grep -E '^[^#]*KERNEL==' "${RULES}" | grep -q 'ACTION!="remove"' \
    || { echo "FAIL - rule is missing ACTION!=\"remove\""; exit 1; }
echo "ok   - uaccess rule present, no GROUP=input, ACTION!=remove"

say "2. systemd user unit installed and points at /usr/bin/linguafix"
UNIT=/usr/lib/systemd/user/linguafix.service
test -f "${UNIT}" || { echo "FAIL - unit missing"; exit 1; }
grep -q "^ExecStart=/usr/bin/linguafix start" "${UNIT}" || { echo "FAIL - unit ExecStart wrong"; exit 1; }
! grep -q "@BIN@" "${UNIT}" || { echo "FAIL - unit still has @BIN@"; exit 1; }
echo "ok   - unit ExecStart=/usr/bin/linguafix start"

say "3. user service enabled globally, without any manual step"
if command -v systemctl >/dev/null 2>&1; then
    test -L /etc/systemd/user/default.target.wants/linguafix.service \
        || { echo "FAIL - service not enabled globally"; exit 1; }
    systemctl --user is-enabled --global linguafix.service | grep -q enabled \
        || { echo "FAIL - is-enabled --global did not report enabled"; exit 1; }
    echo "ok   - linguafix.service enabled (global)"
else
    echo "skip - systemctl unavailable in this image"
fi

say "4. no group membership was changed (usermod must not be needed)"
# The real user that installs the package; root must never be added to input.
id -u tester >/dev/null 2>&1 || useradd -m -s /bin/bash tester
! id -nG tester | grep -qw input || { echo "FAIL - install added tester to input"; exit 1; }
! id -nG root | grep -qw input || { echo "FAIL - install added root to input"; exit 1; }
echo "ok   - no user added to the input group"

say "5. data files shipped"
for f in layouts.json ngrams_en.json ngrams_ru.json stop_words.txt \
         linguafix.service linguafix.desktop linguafix.svg; do
    test -f "/usr/lib/linguafix/linguafix/data/${f}" || { echo "FAIL - missing data ${f}"; exit 1; }
done
echo "ok   - all data files present"

say "6. entry point runs and doctor accepts the packaged access rule"
test -x /usr/bin/linguafix || { echo "FAIL - /usr/bin/linguafix not executable"; exit 1; }
linguafix version | grep -q LinguaFix || { echo "FAIL - version failed"; exit 1; }
linguafix doctor | grep -q "udev-правило с uaccess" \
    || { echo "FAIL - doctor does not see the uaccess rule"; exit 1; }
echo "ok   - doctor reports the uaccess rule"
# doctor runs as root here and creates a root config; a real user config lives
# in that user home and is purged separately in step 8. Remove the root one so
# step 9 can assert a genuinely clean system.
rm -rf /root/.config/linguafix

say "7. reinstall is idempotent"
apt-get install -y -qq --reinstall "/pkg/'"${DEB_NAME}"'" >/dev/null
test -f "${RULES}" && test -f "${UNIT}" || { echo "FAIL - files gone after reinstall"; exit 1; }
echo "ok   - reinstall keeps everything in place"

say "8. apt remove --purge leaves nothing behind"
# Simulate the per-user state a real session would create for the installing
# user (the SUDO_USER that the purge is expected to clean up).
mkdir -p /home/tester/.config/linguafix /home/tester/.local/share/linguafix \
         /home/tester/.local/state/linguafix /home/tester/.cache/linguafix
touch /home/tester/.config/linguafix/config.toml /home/tester/.cache/linguafix/daemon.lock
chown -R tester:tester /home/tester/.config/linguafix /home/tester/.local /home/tester/.cache

SUDO_USER=tester apt-get remove -y -qq --purge linguafix >/dev/null 2>&1 || true

expect_absent "${RULES}"
expect_absent "${UNIT}"
expect_absent /etc/systemd/user/default.target.wants/linguafix.service
expect_absent /home/tester/.config/linguafix
expect_absent /home/tester/.local/share/linguafix
expect_absent /home/tester/.local/state/linguafix
expect_absent /home/tester/.cache/linguafix

say "9. no linguafix file remains anywhere"
leftovers="$(find / -xdev -name "*linguafix*" 2>/dev/null | grep -v "^/pkg/" | grep -v "/var/cache/apt" | grep -v "/var/lib/dpkg" || true)"
if [ -n "${leftovers}" ]; then
    echo "FAIL - leftovers:"; echo "${leftovers}"; exit 1
fi
echo "ok   - no leftovers outside the apt/dpkg caches"

echo
echo "ZERO-CONFIG OK"
' || fail "self-sufficiency test failed inside the container"

log "Self-sufficiency test passed for ${SMOKE_IMAGE}."
