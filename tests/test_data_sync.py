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


def test_deb_depends_on_svg_icon_loader() -> None:
    """The .deb must pull in the gdk-pixbuf SVG loader and the icon theme.

    The app icon is an SVG installed into ``hicolor``. GNOME renders a
    ``Icon=<name>`` entry through gdk-pixbuf, which needs the SVG loader from
    ``librsvg2-common``; without it (and the ``hicolor-icon-theme`` that
    declares the ``scalable/apps`` directory) the launcher shows a blank or
    generic icon on a minimal install.
    """
    script = (REPO_ROOT / "scripts" / "build_deb.sh").read_text(encoding="utf-8")
    depends_line = next(line for line in script.splitlines() if line.startswith("Depends:"))
    assert "librsvg2-common" in depends_line
    assert "hicolor-icon-theme" in depends_line
