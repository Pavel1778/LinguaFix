"""Typo correction ("T9") for a single word.

LinguaFix is a layout switcher, not a general spell-checker, so this is a
deliberately conservative corrector. It only ever replaces a word that is

* **not** already in the language's vocabulary,
* at least ``min_length`` characters long,
* within ``max_distance`` edits of exactly one vocabulary word.

A long word may allow two edits, but the second edit is expensive: with two
edits many vocabulary words sit at the same distance, so the choice is decided
by frequency and only accepted when the most frequent candidate clearly beats
the runner-up (``top1_ratio_strict``). A wrong correction is worse than no
correction, so an ambiguous two-edit match is left alone. The distance is the
optimal string alignment (Damerau-Levenshtein), so a swapped pair such as
``teh`` -> ``the`` is a single edit.
"""

from __future__ import annotations

from collections import defaultdict

# A typo candidate is looked up among words that share its first letter. This
# keeps a 10 000-word vocabulary cheap to search without an index structure.
DEFAULT_MAX_DISTANCE = 1
DEFAULT_MIN_LENGTH = 4
# Words at least this long may be corrected with two edits instead of one.
DEFAULT_LONG_WORD_THRESHOLD = 6
DEFAULT_MAX_DISTANCE_LONG = 2
# With two edits a word is only corrected when the most frequent nearest
# candidate is at least this many times more frequent than the runner-up. The
# value is deliberately modest: even a clear two-edit typo such as
# ``прветт`` -> ``привет`` only beats ``проект`` by ~25x in the corpus, so a
# higher bar would reject the very typos this feature exists to catch.
DEFAULT_TOP1_RATIO_STRICT = 10.0


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
    """Suggest a single correction for a misspelled word of one language.

    Args:
        words: Vocabulary, ordered most-frequent-first. The order is what
            breaks a tie between two equally distant candidates: the earlier
            word is treated as more frequent.
        max_distance: Edits allowed for a word shorter than
            ``long_word_threshold``.
        min_length: Words shorter than this are never corrected.
        long_word_threshold: Words at least this long may use
            ``long_word_max_distance`` edits.
        long_word_max_distance: Edits allowed for a long word.
        top1_ratio_strict: Minimum frequency ratio between the best and the
            second-best candidate before a two-edit correction is accepted.
    """

    def __init__(
        self,
        words: list[str],
        max_distance: int = DEFAULT_MAX_DISTANCE,
        min_length: int = DEFAULT_MIN_LENGTH,
        long_word_threshold: int = DEFAULT_LONG_WORD_THRESHOLD,
        long_word_max_distance: int = DEFAULT_MAX_DISTANCE_LONG,
        top1_ratio_strict: float = DEFAULT_TOP1_RATIO_STRICT,
    ) -> None:
        self._words = {word.lower() for word in words}
        self._max_distance = max_distance
        self._min_length = min_length
        self._long_word_threshold = long_word_threshold
        self._long_word_max_distance = long_word_max_distance
        self._top1_ratio_strict = top1_ratio_strict
        self._by_first: dict[str, list[str]] = defaultdict(list)
        self._rank: dict[str, int] = {}
        for index, word in enumerate(words):
            lowered = word.lower()
            self._rank.setdefault(lowered, index)
            if len(lowered) >= min_length:
                self._by_first[lowered[0]].append(lowered)

    @property
    def vocabulary_size(self) -> int:
        """Number of words the corrector can suggest."""
        return len(self._words)

    def _distance_limit(self, word: str) -> int:
        """Return the edit budget for ``word`` (two for long words, else one)."""
        if len(word) >= self._long_word_threshold:
            return max(self._max_distance, self._long_word_max_distance)
        return self._max_distance

    def _frequency(self, word: str) -> float:
        """Return a higher-is-more-frequent score for ``word``.

        The vocabulary is stored most-frequent-first, so rank 0 is the most
        frequent word. ``1 / (rank + 1)`` keeps the *ratio* between two words
        meaningful (a rank-98 word really is ~25x more frequent than a rank-2444
        one), which the two-edit guard relies on.
        """
        rank = self._rank.get(word)
        if rank is None:
            return 0.0
        return 1.0 / (rank + 1)

    def suggest(self, word: str) -> str | None:
        """Return the corrected word, or ``None`` when no single fix is certain.

        ``None`` is returned for a word that is already correct, is too short,
        is not a plain letter word, or whose nearest candidates are ambiguous.
        A two-edit candidate is only accepted when it clearly beats the runner-up
        by frequency, so a two-edit guess never overrides a plausible alternative.
        """
        lowered = word.lower()
        if len(lowered) < self._min_length or not lowered.isalpha():
            return None
        if lowered in self._words:
            return None

        limit = self._distance_limit(lowered)
        # Nearest candidates, keyed by distance so a one-edit match always wins
        # over a two-edit one.
        nearest: dict[int, list[str]] = defaultdict(list)
        best_distance = limit + 1
        for candidate in self._by_first.get(lowered[0], ()):
            if abs(len(candidate) - len(lowered)) > limit:
                continue
            distance = bounded_damerau_levenshtein(lowered, candidate, limit)
            if distance > limit:
                continue
            nearest[distance].append(candidate)
            best_distance = min(best_distance, distance)
        if best_distance > limit:
            return None

        candidates = nearest[best_distance]
        if len(candidates) == 1:
            return candidates[0]

        # Several words are equally close. Pick the most frequent, but only when
        # it is clearly ahead; otherwise the correction is too risky.
        ranked = sorted(candidates, key=self._frequency, reverse=True)
        top, runner_up = ranked[0], ranked[1]
        top_freq, runner_freq = self._frequency(top), self._frequency(runner_up)
        if top_freq <= 0.0:
            return None
        if runner_freq <= 0.0:
            return top
        if top_freq / runner_freq < self._top1_ratio_strict:
            return None
        return top
