#!/usr/bin/env bash
#
# Set up a development environment for LinguaFix.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"

PYTHON="${PYTHON:-python3}"
VENV="${VENV:-.venv}"

echo "[linguafix] Creating virtual environment in ${VENV}"
"${PYTHON}" -m venv "${VENV}"
"${VENV}/bin/pip" install --upgrade pip
"${VENV}/bin/pip" install -e ".[dev]"

echo "[linguafix] Installing git hooks"
if command -v pre-commit >/dev/null 2>&1 && [ -f .pre-commit-config.yaml ]; then
    "${VENV}/bin/pre-commit" install || true
fi

cat <<EOF

[linguafix] Development environment ready.

Activate it with:
    source ${VENV}/bin/activate

Then run:
    make check      # lint + typecheck + tests
    make test       # tests with coverage
EOF
