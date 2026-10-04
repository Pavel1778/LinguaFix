#!/usr/bin/env python3
"""Build ``ngrams_<lang>.json`` corpora from FrequencyWords lists.

The detector needs two things per language: a frequency-ordered vocabulary and a
character-bigram model derived from that vocabulary. The upstream word lists
(https://github.com/hermitdave/FrequencyWords, CC-BY-SA) are ``word count`` per
line, most frequent first.

Usage::

    scripts/build_corpora.py en:/path/en_50k.txt ru:/path/ru_50k.txt ...

The generated files are written to ``src/linguafix/data/``. Words are stored in
frequency order because ``LanguageDetector`` keeps the first
``Config.dictionary_size`` of them.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

# How many words to ship per language. ``Config.dictionary_size`` may be up to
# 10000, so the file must hold at least that many.
MAX_WORDS = 10000
# Bigrams are counted over the most frequent words only: a model built from
# every word over-weights rare letter pairs and blurs the language signal.
BIGRAM_WORDS = 5000
# Only plain letter words (plus the apostrophe) are useful for detection.
_WORD_RE = re.compile(r"^[^\W\d_]+(?:'[^\W\d_]+)*$", re.UNICODE)
DATA_DIR = Path(__file__).resolve().parent.parent / "src" / "linguafix" / "data"


def read_words(path: Path, limit: int) -> list[str]:
    """Return the first ``limit`` usable words from a FrequencyWords file."""
    words: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        word = line.split(" ", 1)[0].strip().lower()
        if not word or len(word) > 32 or not _WORD_RE.match(word):
            continue
        if word in seen:
            continue
        seen.add(word)
        words.append(word)
        if len(words) >= limit:
            break
    return words


def build_bigrams(words: list[str]) -> dict[str, float]:
    """Return ``{bigram: probability}`` from the padded words."""
    counts: collections.Counter[str] = collections.Counter()
    for word in words:
        padded = "^" + word + "$"
        for index in range(len(padded) - 1):
            counts[padded[index : index + 2]] += 1
    total = sum(counts.values())
    if not total:
        return {}
    return {bigram: count / total for bigram, count in counts.most_common()}


def build_language(language: str, source: Path) -> dict[str, object]:
    """Build the corpus payload for one language."""
    words = read_words(source, MAX_WORDS)
    bigrams = build_bigrams(words[:BIGRAM_WORDS])
    return {
        "language": language,
        "vocabulary_size": len(words),
        "bigram_count": len(bigrams),
        "words": words,
        "bigrams": bigrams,
    }


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for spec in argv:
        language, _, path = spec.partition(":")
        if not language or not path:
            print(f"invalid argument {spec!r}; expected <lang>:<path>", file=sys.stderr)
            return 2
        payload = build_language(language, Path(path))
        target = DATA_DIR / f"ngrams_{language}.json"
        target.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        print(
            f"{language}: {payload['vocabulary_size']} words, "
            f"{payload['bigram_count']} bigrams -> {target}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
