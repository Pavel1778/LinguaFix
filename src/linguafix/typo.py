"""Typo correction ("T9") for a single word.

LinguaFix is a layout switcher, not a general spell-checker, so this is a
deliberately conservative corrector. It only ever replaces a word that is

* **not** already in the language's vocabulary,
* at least ``min_length`` characters long,
* within ``max_distance`` edits of exactly one vocabulary word.

When two vocabulary words are equally close the word is left alone: a wrong
correction is worse than no correction. The distance is the optimal string
alignment (Damerau-Levenshtein) so a swapped pair such as ``teh`` -> ``the`` is
a single edit.
"""

from __future__ import annotations

from collections import defaultdict

# A typo candidate is looked up among words that share its first letter. This
# keeps a 10 000-word vocabulary cheap to search without an index structure.
DEFAULT_MAX_DISTANCE = 1
DEFAULT_MIN_LENGTH = 4


def bounded_damerau_levenshtein(a: str, b: str, max_distance: int) -> int:
    """Return the edit distance between ``a`` and ``b``, capped at ``max_distance``.

    The result is ``max_distance + 1`` when the true distance exceeds the cap,
    which lets the caller reject the pair without paying for the full matrix.
    The metric is optimal string alignment: substitutions, insertions,
    deletions and transpositions of adjacent characters each cost one.
    """
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_distance:
        return max_distance + 1
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous_previous: list[int] = []
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        row_min = i
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            value = min(
                previous[j] + 1,  # deletion
                current[j - 1] + 1,  # insertion
                previous[j - 1] + cost,  # substitution
            )
            if i > 1 and j > 1 and char_a == b[j - 2] and a[i - 2] == char_b:
                value = min(value, previous_previous[j - 2] + 1)  # transposition
            current.append(value)
            row_min = min(row_min, value)
        if row_min > max_distance:
            return max_distance + 1
        previous_previous, previous = previous, current
    return previous[-1] if previous[-1] <= max_distance else max_distance + 1


class TypoCorrector:
    """Suggest a single correction for a misspelled word of one language."""

    def __init__(
        self,
        words: list[str],
        max_distance: int = DEFAULT_MAX_DISTANCE,
        min_length: int = DEFAULT_MIN_LENGTH,
    ) -> None:
        self._words = {word.lower() for word in words}
        self._max_distance = max_distance
        self._min_length = min_length
        self._by_first: dict[str, list[str]] = defaultdict(list)
        for word in words:
            lowered = word.lower()
            if len(lowered) >= min_length:
                self._by_first[lowered[0]].append(lowered)

    @property
    def vocabulary_size(self) -> int:
        """Number of words the corrector can suggest."""
        return len(self._words)

    def suggest(self, word: str) -> str | None:
        """Return the corrected word, or ``None`` when no single fix is certain.

        ``None`` is returned for a word that is already correct, is too short,
        is not a plain letter word, or has more than one equally close
        candidate.
        """
        lowered = word.lower()
        if len(lowered) < self._min_length or not lowered.isalpha():
            return None
        if lowered in self._words:
            return None

        best: str | None = None
        best_distance = self._max_distance + 1
        tied = False
        for candidate in self._by_first.get(lowered[0], ()):
            if abs(len(candidate) - len(lowered)) > self._max_distance:
                continue
            distance = bounded_damerau_levenshtein(lowered, candidate, self._max_distance)
            if distance > self._max_distance:
                continue
            if distance < best_distance:
                best_distance = distance
                best = candidate
                tied = False
            elif distance == best_distance:
                tied = True
        if best is None or tied:
            return None
        return best
