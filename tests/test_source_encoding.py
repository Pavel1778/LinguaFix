"""The repository's text sources must be valid UTF-8, with no mojibake.

A single mis-encoded save (a text editor writing UTF-8 bytes through a
Latin-1 pipeline) doubles the encoding of every non-ASCII character, turning
Cyrillic comments and — worse — user-facing notification strings into garbage.
The resulting file still imports and the test suite still passes, so the
corruption ships silently and only the end user sees it.

This guard scans every tracked text source and fails on the byte sequences a
double-encoded save produces. The bundled frequency dictionaries are excluded:
they legitimately contain accented Latin words that overlap the signature set.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Suffixes that are code or prose: the files where an English/Cyrillic mix is
# expected. Data files (``.json`` corpora, ``.txt`` word lists) legitimately
# contain accented Latin words, so they are outside the scan.
TEXT_SUFFIXES = (".py", ".md", ".astro", ".ts", ".sh", ".toml", ".cfg", ".ini")

# Index of the mojibake signature characters. A double-encoded Cyrillic or
# em-dash character always surfaces at least one of these, none of which occurs
# in genuine source outside the excluded dictionaries.
_MOJIBAKE_CHARS = frozenset("\u00d0\u00d1\u0110\u0111\u0178\u015a\u0153\u017e")

_EXCLUDED_PREFIXES = ("dictionaries/", "site/dist/", "site/.astro/", "site/node_modules/")


def _tracked_text_files() -> list[str]:
    output = subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT, text=True)
    return [
        name
        for name in output.splitlines()
        if name.endswith(TEXT_SUFFIXES) and not name.startswith(_EXCLUDED_PREFIXES)
    ]


def test_no_mojibake_in_tracked_sources() -> None:
    """No tracked text source may contain a double-encoded byte sequence."""
    offenders: list[str] = []
    for name in _tracked_text_files():
        try:
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - surfaced below
            offenders.append(f"{name}: not valid UTF-8 ({exc})")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _MOJIBAKE_CHARS & set(line):
                offenders.append(f"{name}:{lineno}")
    assert not offenders, "Mojibake (double-encoded UTF-8) found in:\n" + "\n".join(offenders)


@pytest.mark.parametrize("name", ["src/linguafix/daemon.py"])
def test_notification_strings_are_recoverable(name: str) -> None:
    """The fixed notification labels must be the intended Cyrillic text.

    A regression guard narrower than the scan above: it pins the exact strings a
    user sees, so a corruption that happens to avoid the signature set (for
    example by round-tripping through a different codec) is still caught.
    """
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    assert "Раскладка исправлена" in text
    assert "Доступна версия {latest}" in text
