"""The version must be declared identically everywhere it is used.

Three places carry the release version and they must agree, or a build ships a
``.deb`` whose name, metadata and ``__version__`` disagree:

* ``pyproject.toml`` (packaging metadata; ``scripts/build_deb.sh`` reads it),
* ``src/linguafix/__init__.py`` (``__version__``),
* ``CHANGELOG.md`` (the newest released heading).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib

from linguafix import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE)


def _pyproject_version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version: str = data["project"]["version"]
    return version


def _changelog_version() -> str:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = CHANGELOG_HEADING.search(text)
    assert match is not None, "CHANGELOG.md has no '## [x.y.z]' heading"
    return match.group(1)


def test_version_matches_pyproject() -> None:
    assert __version__ == _pyproject_version()


def test_version_matches_changelog() -> None:
    assert __version__ == _changelog_version()


# Docs that a user follows to install a downloaded package. A stale version in
# the example makes ``apt install ./linguafix_<old>_all.deb`` fail with
# "no such file", which is exactly what a first-time user hits.
_INSTALL_DOCS = ("README.md", "docs/INSTALL.md", "docs/TESTING.md")
_DEB_EXAMPLE = re.compile(r"linguafix_(\d+\.\d+\.\d+)_all\.deb")


def test_install_docs_use_current_version() -> None:
    stale: list[str] = []
    for name in _INSTALL_DOCS:
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for match in _DEB_EXAMPLE.finditer(text):
            if match.group(1) != __version__:
                stale.append(f"{name}: {match.group(0)}")
    assert not stale, "Install docs reference an old package version:\n" + "\n".join(stale)
