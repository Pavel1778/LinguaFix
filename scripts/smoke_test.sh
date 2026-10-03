#!/usr/bin/env bash
# Runtime smoke test for the built .deb package.
#
# Installs the package into a clean Debian container (Docker) and verifies that
# the CLI actually starts: `version`, `--help`, `status` and `doctor`. Unlike the
# pytest suite, which replaces the operating-system boundary with fakes, this
# exercises the real installed entry point and its runtime dependencies.
#
# Usage:
#   bash scripts/smoke_test.sh [path/to/linguafix_*.deb]
#
# Environment:
#   SMOKE_IMAGE   Docker image to use (default: debian:12)
#
# Exits non-zero when any smoke check fails.
set -u

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_IMAGE="${SMOKE_IMAGE:-debian:12}"
DEB="${1:-}"

log() { printf '\033[1;34m[smoke]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[smoke] FAIL:\033[0m %s\n' "$*" >&2; exit 1; }

if [ -z "${DEB}" ]; then
    DEB="$(ls -1 "${REPO_DIR}"/dist/linguafix_*.deb 2>/dev/null | head -1 || true)"
fi
[ -n "${DEB}" ] && [ -f "${DEB}" ] || fail "no .deb found; run 'make build-deb' first"
log "Testing package: ${DEB}"

DOCKER="docker"
if ! docker info >/dev/null 2>&1; then
    DOCKER="sudo docker"
    $DOCKER info >/dev/null 2>&1 || fail "Docker is not available"
fi

DEB_DIR="$(cd "$(dirname "${DEB}")" && pwd)"
DEB_NAME="$(basename "${DEB}")"

$DOCKER run --rm -v "${DEB_DIR}:/pkg:ro" "${SMOKE_IMAGE}" bash -c '
set -e
apt-get update -qq
apt-get install -y -qq "/pkg/'"${DEB_NAME}"'" >/dev/null

echo "--- entry point ---"
command -v linguafix >/dev/null || { echo "linguafix not on PATH"; exit 1; }
test -x /usr/bin/linguafix || { echo "/usr/bin/linguafix missing or not executable"; exit 1; }

echo "--- version ---"
linguafix version | grep -q "LinguaFix" || { echo "version check failed"; exit 1; }

echo "--- help ---"
linguafix --help | grep -q "doctor" || { echo "help missing doctor"; exit 1; }

echo "--- status ---"
linguafix status >/dev/null

echo "--- data files present and loadable ---"
DATA=/usr/lib/linguafix/linguafix/data
for f in layouts.json ngrams_en.json ngrams_ru.json stop_words.txt; do
    test -f "${DATA}/${f}" || { echo "missing data file ${f}"; exit 1; }
done
python3 - <<PY || { echo "data files failed to load"; exit 1; }
import sys
sys.path.insert(0, "/usr/lib/linguafix")
from linguafix.converter import LayoutConverter
from linguafix.detector import LanguageDetector
assert LayoutConverter().convert("ghbdtn", "us", "ru") == "привет"
assert LanguageDetector().detect("привет") == "ru"
print("data load OK")
PY

echo "--- systemd unit points at the packaged launcher ---"
grep -q "^ExecStart=/usr/bin/linguafix " /usr/lib/systemd/user/linguafix.service \
    || { echo "unit ExecStart does not point at /usr/bin/linguafix"; exit 1; }
! grep -q "@BIN@" /usr/lib/systemd/user/linguafix.service \
    || { echo "unit still contains @BIN@ placeholder"; exit 1; }
! grep -q "@BIN@" /usr/share/applications/linguafix.desktop \
    || { echo "desktop file still contains @BIN@ placeholder"; exit 1; }

echo "--- udev rule grants uaccess, not the input group ---"
RULE=/usr/lib/udev/rules.d/99-linguafix.rules
test -f "${RULE}" || { echo "udev rule not installed at ${RULE}"; exit 1; }
grep -q "TAG+=\"uaccess\"" "${RULE}" || { echo "udev rule has no uaccess"; exit 1; }
! grep -q "GROUP=\"input\"" "${RULE}" || { echo "udev rule still uses GROUP=input"; exit 1; }

echo "--- install-autostart renders the packaged launcher ---"
linguafix install-autostart >/dev/null
grep -q "^Exec=/usr/bin/linguafix start" "${HOME}/.config/autostart/linguafix.desktop" \
    || { echo "autostart Exec not rendered"; exit 1; }
grep -q "^ExecStart=/usr/bin/linguafix start" "${HOME}/.config/systemd/user/linguafix.service" \
    || { echo "installed unit ExecStart not rendered"; exit 1; }

echo "--- doctor (expected to report failures in a bare container) ---"
linguafix doctor || true

echo "--- collect-logs ---"
linguafix collect-logs --output /tmp | grep -q "архив создан" || { echo "collect-logs failed"; exit 1; }
ls /tmp/linguafix-logs-*.tar.gz >/dev/null || { echo "no tarball produced"; exit 1; }

echo "--- daemon dry-run start (no input devices -> exit 2 is acceptable) ---"
timeout 15 linguafix start --foreground --dry-run || true

echo "SMOKE OK"
' || fail "smoke test failed inside the container"

log "Smoke test passed."
