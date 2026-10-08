"""User dictionaries: words the user has taught LinguaFix to leave alone.

The daemon never writes typed text to disk, so the "add to dictionary" action
is a separate, explicit file the user (or the GUI) edits. The file is a simple
newline-separated list, one word per line; blank lines and ``#`` comments are
ignored.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

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


# --------------------------------------------------------------------------
# Extended (frequency) dictionaries.
#
# These are *separate* from the user dictionary above. The user dictionary
# teaches LinguaFix words to leave alone; an extended dictionary is a bulk list
# of common words that widens the detector's vocabulary so more real words are
# recognised. Nothing here ever receives typed text: the files are read from
# the bundle or downloaded from a fixed URL.
# --------------------------------------------------------------------------

# Curated word lists shipped with the project, one per language.
BUNDLED_DICTIONARY_LANGUAGES: Final[tuple[str, ...]] = ("ru", "en", "uk", "de", "fr")
BUNDLED_DICTIONARY_SUFFIX: Final[str] = "-50k.txt"

# Where ``linguafix dict download`` fetches lists from by default. The project
# mirrors the upstream top-50k lists (word column only) under the repo's
# ``dictionaries/`` folder. The upstream FrequencyWords source (MIT) is kept as
# a fallback so the command still works if the mirror is unreachable.
_BUNDLED_RAW_BASE: Final[str] = (
    "https://raw.githubusercontent.com/Pavel1778/LinguaFix/main/dictionaries/"
)
_UPSTREAM_RAW: Final[dict[str, str]] = {
    lang: (
        "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/"
        f"content/2018/{lang}/{lang}_50k.txt"
    )
    for lang in BUNDLED_DICTIONARY_LANGUAGES
}
_DOWNLOAD_TIMEOUT: Final[float] = 30.0


def default_extended_dictionary_dir() -> Path:
    """Return the default directory for extended dictionaries.

    Uses ``$XDG_DATA_HOME/linguafix/dictionaries`` (falling back to
    ``~/.local/share``), matching the user dictionary's location.
    """
    import os

    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "linguafix" / "dictionaries"


def extended_dictionary_path(language: str, directory: str = "") -> Path:
    """Return the file path of the extended dictionary for ``language``."""
    base = Path(directory).expanduser() if directory.strip() else default_extended_dictionary_dir()
    return base / f"{language.lower()}.txt"


def load_extended_dictionary(language: str, directory: str = "") -> set[str]:
    """Read the extended dictionary for ``language`` (empty when absent).

    Parses the same format as the bundled ``<lang>-50k.txt`` files: one word
    per line, optionally followed by a whitespace-separated frequency that is
    ignored. Blank lines and ``#`` comments are dropped.
    """
    file_path = extended_dictionary_path(language, directory)
    try:
        text = file_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return set()
    words: set[str] = set()
    for raw in text.splitlines():
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        word = entry.split()[0]
        if word:
            words.add(word.lower())
    return words


_COMMENT_PREFIXES: Final[tuple[str, ...]] = ("#", "//")


def _write_words(words: list[str], destination: Path) -> int:
    """Write a deduplicated word list to ``destination``. Return count.

    Comment lines are dropped so an annotated export (``# top 50k``) does not
    smuggle a stray ``#`` token into the detector's vocabulary.
    """
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in words:
        token = str(raw).strip()
        if not token or token.startswith(_COMMENT_PREFIXES):
            continue
        word = token.split()[0]
        lowered = word.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(word)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(cleaned) + ("\n" if cleaned else ""), encoding="utf-8")
    return len(cleaned)


def import_dictionary_file(source: str, language: str, directory: str = "") -> int:
    """Import an external word list as the extended dictionary for ``language``.

    Args:
        source: Path to the file to import (``<lang>-50k.txt``, a plain word
            list, or any file whose first whitespace-separated column is a
            word).
        language: Target language code (``ru``, ``en``, ...).
        directory: Destination directory; the default XDG location is used when
            empty.

    Returns:
        The number of words written.

    Raises:
        FileNotFoundError: The source file does not exist.
        ValueError: ``language`` is empty.
    """
    lang = language.strip().lower()
    if not lang:
        raise ValueError("language code is required")
    source_path = Path(source).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    words = source_path.read_text(encoding="utf-8").splitlines()
    destination = extended_dictionary_path(lang, directory)
    count = _write_words(words, destination)
    logger.info("Imported %d words for language %s into %s", count, lang, destination)
    return count


def download_extended_dictionary(language: str, directory: str = "") -> tuple[Path, int]:
    """Download the top-50k word list for ``language`` into ``directory``.

    Tries the project mirror first, then the upstream FrequencyWords source.

    Returns:
        ``(path, word_count)``.

    Raises:
        ValueError: ``language`` is not one of the supported dictionaries.
        urllib.error.URLError: Both sources could not be reached.
    """
    import urllib.error
    import urllib.request

    lang = language.strip().lower()
    if lang not in BUNDLED_DICTIONARY_LANGUAGES:
        supported = ", ".join(BUNDLED_DICTIONARY_LANGUAGES)
        raise ValueError(f"unsupported language {lang!r}; choose one of: {supported}")

    urls = [_BUNDLED_RAW_BASE + f"{lang}{BUNDLED_DICTIONARY_SUFFIX}"]
    if lang in _UPSTREAM_RAW:
        urls.append(_UPSTREAM_RAW[lang])

    last_error: Exception | None = None
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT) as response:  # nosec B310
                text = response.read().decode("utf-8")
        except (urllib.error.URLError, OSError, UnicodeDecodeError) as exc:
            last_error = exc
            logger.debug("Dictionary download failed from %s", url, exc_info=True)
            continue
        destination = extended_dictionary_path(lang, directory)
        count = _write_words(text.splitlines(), destination)
        logger.info("Downloaded %d words for language %s", count, lang)
        return destination, count
    assert last_error is not None
    raise last_error
