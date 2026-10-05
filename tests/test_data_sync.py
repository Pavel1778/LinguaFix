"""The packaged ``data/`` copies must stay identical to the source copies.

The desktop entry, autostart entry, systemd unit and icon live in two places:
``data/`` (used by ``install.sh`` and ``scripts/build_deb.sh``) and
``src/linguafix/data/`` (shipped inside the Python package). They are edited by
hand, so they can silently drift; this test fails when they do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
PACKAGE_DATA_DIR = REPO_ROOT / "src" / "linguafix" / "data"

# Files intentionally duplicated between the two directories.
DUPLICATED = (
    "linguafix.desktop",
    "linguafix-autostart.desktop",
    "linguafix.service",
    "linguafix.svg",
)


@pytest.mark.parametrize("name", DUPLICATED)
def test_duplicated_data_file_is_in_sync(name: str) -> None:
    root_copy = DATA_DIR / name
    package_copy = PACKAGE_DATA_DIR / name
    assert root_copy.is_file(), f"{root_copy} is missing"
    assert package_copy.is_file(), f"{package_copy} is missing"
    assert (
        root_copy.read_bytes() == package_copy.read_bytes()
    ), f"{name} differs between data/ and src/linguafix/data/; keep them in sync"
