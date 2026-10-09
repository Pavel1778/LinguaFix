#!/usr/bin/env python3
"""Rewrite the word count in every thematic ``README.md`` from the real files.

The ``~N слов`` cells drifted from the lists as they were edited. This keeps the
documentation honest: the count is measured from the shipped file, never typed
by hand. Run it after touching a thematic list.

Usage: ``python3 scripts/refresh_dict_readmes.py [--check]``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
DICT_ROOT = REPO_DIR / "dictionaries"

_COUNT_RE = re.compile(
    r"(\| `(?P<lang>ru|en)-(?P<slug>[a-z]+)-1k\.txt` \| [^|]+ \| )(?:~\d+|\d+)( слов \|)"
)


def _count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def main() -> int:
    check = "--check" in sys.argv[1:]
    failures = 0
    for readme in sorted(DICT_ROOT.glob("*/README.md")):
        directory = readme.parent
        original = readme.read_text(encoding="utf-8")

        def replace(match: re.Match[str], directory: Path = directory) -> str:
            target = directory / f"{match.group('lang')}-{match.group('slug')}-1k.txt"
            return f"{match.group(1)}{_count(target)} слов |"

        updated = _COUNT_RE.sub(replace, original)
        if updated == original:
            continue
        if check:
            failures += 1
            print(f"drift: {readme}")
        else:
            readme.write_text(updated, encoding="utf-8")
            print(f"updated: {readme}")
    if check and failures:
        print(f"{failures} README(s) out of date")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
