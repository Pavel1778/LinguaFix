"""User dictionaries: words the user has taught LinguaFix to leave alone.

The daemon never writes typed text to disk, so the "add to dictionary" action
is a separate, explicit file the user (or the GUI) edits. The file is a simple
newline-separated list, one word per line; blank lines and ``#`` comments are
ignored.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_WORD_LENGTH = 64


def user_dictionary_path(override: str = "") -> Path:
    """Return the path of the user dictionary.

    Args:
        override: Explicit path from the configuration. When empty the default
            XDG data location is used.
    """
    if override.strip():
        return Path(override).expanduser()
    import os

    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "linguafix" / "dictionary.txt"


def load_user_dictionary(path: str = "") -> list[str]:
    """Read the user dictionary, returning ``[]`` when it does not exist.

    Only the likely words are returned: lines are stripped, comments and blanks
    dropped, and duplicates removed while preserving order.
    """
    file_path = user_dictionary_path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError:
        logger.debug("Could not read user dictionary %s", file_path, exc_info=True)
        return []

    words: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        word = raw.strip()
        if not word or word.startswith("#"):
            continue
        if len(word) > MAX_WORD_LENGTH:
            continue
        lowered = word.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        words.append(word)
    return words


def save_user_dictionary(words: list[str], path: str = "") -> None:
    """Write ``words`` to the user dictionary (best-effort, deduplicated)."""
    file_path = user_dictionary_path(path)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in words:
        word = str(raw).strip()
        if not word or len(word) > MAX_WORD_LENGTH:
            continue
        if word.lower() in seen:
            continue
        seen.add(word.lower())
        cleaned.append(word)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("\n".join(cleaned) + ("\n" if cleaned else ""), encoding="utf-8")
    except OSError:
        logger.warning("Could not write user dictionary %s", file_path, exc_info=True)


def add_user_word(word: str, path: str = "") -> list[str]:
    """Append a word to the dictionary, returning the new word list."""
    words = load_user_dictionary(path)
    if word.strip() and word.strip().lower() not in {w.lower() for w in words}:
        words.append(word.strip())
        save_user_dictionary(words, path)
    return words
