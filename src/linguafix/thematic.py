"""Thematic (professional) dictionaries.

Alongside the general frequency lists (``base``) LinguaFix can load domain
vocabularies -- IT, medicine, legal, finance, engineering -- so that
professional terms a user types are recognised instead of being "corrected".

Design:

* A *category* is a slug (``it``, ``medicine``) with a title and a set of
  languages, each backed by ``dictionaries/<slug>/<lang>-<slug>-1k.txt``.
* Installing a category copies its file for the chosen language into
  ``<extended_dictionary_dir>/thematic/<lang>/<slug>.txt`` and records the slug
  in ``config.installed_dict_categories``. The file is kept when the category is
  removed, so a re-install needs no network.
* Downloads come from the project's GitHub Release assets first (an archive
  ``linguafix-dict-<slug>.tar.gz``), then the repository mirror, then a locally
  shipped copy -- the same offline-friendly order as the base lists.

Nothing here ever receives typed text: the files are curated lists read from the
bundle or downloaded from a fixed URL.
"""

from __future__ import annotations

import io
import logging
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .dictionary import _write_words, default_extended_dictionary_dir

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DictionaryCategory:
    """A thematic dictionary category and the languages it ships."""

    slug: str
    title_ru: str
    title_en: str
    languages: tuple[str, ...]

    def file_name(self, language: str) -> str:
        """Return the word-list file name for ``language`` in this category."""
        return f"{language.lower()}-{self.slug}-1k.txt"


CATEGORIES: Final[tuple[DictionaryCategory, ...]] = (
    DictionaryCategory("it", "IT / программирование", "IT / programming", ("ru", "en")),
    DictionaryCategory("medicine", "Медицина и биология", "Medicine and biology", ("ru", "en")),
    DictionaryCategory("legal", "Юриспруденция", "Law", ("ru", "en")),
    DictionaryCategory("finance", "Финансы и бухгалтерия", "Finance and accounting", ("ru", "en")),
    DictionaryCategory("engineering", "Инженерия и строительство", "Engineering", ("ru", "en")),
)

_CATEGORY_BY_SLUG: Final[dict[str, DictionaryCategory]] = {c.slug: c for c in CATEGORIES}

_RELEASE_ASSET_BASE: Final[str] = "https://github.com/Pavel1778/LinguaFix/releases/latest/download/"
_BRANCH_MIRROR_BASE: Final[str] = (
    "https://raw.githubusercontent.com/Pavel1778/LinguaFix/main/dictionaries/"
)
_DOWNLOAD_TIMEOUT: Final[float] = 30.0

# The repository copy, used as the offline fallback from a checkout.
_REPO_DICTIONARIES: Final[Path] = Path(__file__).resolve().parent.parent.parent / "dictionaries"


def category(slug: str) -> DictionaryCategory | None:
    """Return the category for ``slug`` or ``None`` when unknown."""
    return _CATEGORY_BY_SLUG.get(slug.strip().lower())


def category_slugs() -> tuple[str, ...]:
    """Return every category slug, in a stable order."""
    return tuple(c.slug for c in CATEGORIES)


def thematic_dir(language: str, directory: str = "") -> Path:
    """Return the directory holding thematic lists for ``language``."""
    base = Path(directory).expanduser() if directory.strip() else default_extended_dictionary_dir()
    return base / "thematic" / language.lower()


def thematic_path(category_slug: str, language: str, directory: str = "") -> Path:
    """Return the installed file path for ``category_slug``/``language``."""
    return thematic_dir(language, directory) / f"{category_slug.lower()}.txt"


def repo_category_source(category_slug: str, language: str) -> Path | None:
    """Return the repository copy of a category list, or ``None``.

    Used as the offline fallback when the release asset and the branch mirror
    are both unreachable (for example in CI, or from a source checkout).
    """
    cat = category(category_slug)
    if cat is None or language.lower() not in cat.languages:
        return None
    candidate = _REPO_DICTIONARIES / cat.slug / cat.file_name(language)
    return candidate if candidate.is_file() else None


def load_thematic_words(category_slug: str, language: str, directory: str = "") -> set[str]:
    """Read an installed thematic list, returning an empty set when absent."""
    file_path = thematic_path(category_slug, language, directory)
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


def installed_category_slugs(language: str, directory: str = "") -> tuple[str, ...]:
    """Return the categories whose file is present for ``language``."""
    present: list[str] = []
    for cat in CATEGORIES:
        if language.lower() not in cat.languages:
            continue
        if thematic_path(cat.slug, language, directory).is_file():
            present.append(cat.slug)
    return tuple(present)


def _download_bytes(url: str) -> bytes:
    """Fetch ``url`` returning its bytes, raising on any network error."""
    with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT) as response:  # nosec B310
        return bytes(response.read())


def _extract_archive(payload: bytes, member: str) -> str | None:
    """Return the decoded ``member`` text from a ``.tar.gz`` payload."""
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            for name in archive.getnames():
                if Path(name).name == member:
                    handle = archive.extractfile(name)
                    if handle is None:
                        return None
                    return handle.read().decode("utf-8")
    except (tarfile.TarError, OSError):
        return None
    return None


def download_category(
    category_slug: str, language: str = "ru", directory: str = ""
) -> tuple[Path, int]:
    """Download a thematic list for ``category_slug``/``language``.

    Sources, in order: the GitHub Release archive
    ``linguafix-dict-<slug>.tar.gz``, the repository mirror, then the locally
    shipped copy. The file lands in ``thematic/<lang>/<slug>.txt``.

    Returns:
        ``(path, word_count)``.

    Raises:
        ValueError: Unknown category or a language the category does not ship.
        urllib.error.URLError: No source was reachable and no local copy exists.
    """
    cat = category(category_slug)
    if cat is None:
        supported = ", ".join(category_slugs())
        raise ValueError(f"unknown category {category_slug!r}; choose one of: {supported}")
    lang = language.strip().lower()
    if lang not in cat.languages:
        supported = ", ".join(cat.languages)
        raise ValueError(f"category {cat.slug!r} has no {lang!r} list; choose one of: {supported}")

    member = cat.file_name(lang)
    archive_name = f"linguafix-dict-{cat.slug}.tar.gz"
    destination = thematic_path(cat.slug, lang, directory)
    last_error: Exception | None = None

    # 1. Release archive (single asset per category).
    try:
        payload = _download_bytes(_RELEASE_ASSET_BASE + archive_name)
        text = _extract_archive(payload, member)
        if text is not None:
            count = _write_words(text.splitlines(), destination)
            logger.info("Downloaded %d %s words for %s", count, cat.slug, lang)
            return destination, count
    except (urllib.error.URLError, OSError) as exc:
        last_error = exc
        logger.debug("Category archive download failed for %s", cat.slug, exc_info=True)

    # 2. Branch mirror (raw file).
    try:
        text = _download_bytes(_BRANCH_MIRROR_BASE + f"{cat.slug}/{member}").decode("utf-8")
        count = _write_words(text.splitlines(), destination)
        logger.info("Downloaded %d %s words for %s (mirror)", count, cat.slug, lang)
        return destination, count
    except (urllib.error.URLError, OSError, UnicodeDecodeError) as exc:
        last_error = exc
        logger.debug("Category mirror download failed for %s", cat.slug, exc_info=True)

    # 3. Locally shipped copy (offline / CI).
    source = repo_category_source(cat.slug, lang)
    if source is not None:
        count = _write_words(source.read_text(encoding="utf-8").splitlines(), destination)
        logger.info("Installed bundled %d %s words for %s", count, cat.slug, lang)
        return destination, count

    assert last_error is not None
    raise last_error


def enable_category(config_categories: list[str], slug: str) -> list[str]:
    """Return ``config_categories`` with ``slug`` added (deduplicated)."""
    result = [c for c in config_categories if c != slug]
    result.append(slug)
    return result


def disable_category(config_categories: list[str], slug: str) -> list[str]:
    """Return ``config_categories`` with ``slug`` removed (``base`` stays)."""
    return [c for c in config_categories if c != slug or c == "base"]
