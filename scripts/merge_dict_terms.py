#!/usr/bin/env python3
"""Merge newline-separated terms into a thematic dictionary file, deduplicating.

Terms are matched case-insensitively; existing order is preserved and a term
that already exists (in any case) is not re-appended. Blank lines and terms with
internal whitespace are dropped, so a file always holds one word per line.

Usage:
    python3 scripts/merge_dict_terms.py dictionaries/it/ru-it-1k.txt new-terms.txt
"""

from __future__ import annotations

import sys
from pathlib import Path


def merge(target: Path, additions: Path) -> tuple[int, int]:
    existing = target.read_text(encoding="utf-8").splitlines()
    seen = {line.strip().lower() for line in existing if line.strip()}
    added = 0
    kept = [line for line in existing if line.strip()]
    for raw in additions.read_text(encoding="utf-8").splitlines():
        term = raw.strip()
        if not term or " " in term or term.lower() in seen:
            continue
        seen.add(term.lower())
        kept.append(term)
        added += 1
    target.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return len(kept), added


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    total, added = merge(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"{sys.argv[1]}: {total} words ({added} added)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
