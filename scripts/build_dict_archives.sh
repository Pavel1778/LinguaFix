#!/usr/bin/env bash
#
# Build one .tar.gz per thematic dictionary category.
#
# ``linguafix dict install <category>`` fetches
# ``releases/latest/download/linguafix-dict-<slug>.tar.gz`` and looks for the
# member ``<lang>-<slug>-1k.txt`` inside it. The archive keeps the category
# folder layout (``it/ru-it-1k.txt``), so the member name matches.
#
# Usage: scripts/build_dict_archives.sh [output-dir]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-${REPO_DIR}/dist/dict-archives}"

mkdir -p "${OUT_DIR}"
cd "${REPO_DIR}"

for dir in dictionaries/*/; do
    slug="$(basename "${dir}")"
    # Only real categories carry a README; skip ``base`` and stray folders.
    [ -f "${dir}README.md" ] || continue
    tar -czf "${OUT_DIR}/linguafix-dict-${slug}.tar.gz" -C dictionaries "${slug}"
done

ls -l "${OUT_DIR}"
