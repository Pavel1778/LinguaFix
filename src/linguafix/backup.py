"""Export and import of user settings (Stage 11).

A backup bundles the three user-owned files — the configuration, the user
dictionary and the snippets — into one JSON document. No typed text, logs or
state are included, so a backup is safe to share.

The format is intentionally small and stable::

    {"format": "linguafix-backup", "version": 1,
     "config": {...}, "dictionary": ["word", ...], "snippets": "..."}
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final

from .config import Config, config_path, load_config, save_config, snippets_path
from .dictionary import load_user_dictionary, save_user_dictionary, user_dictionary_path

logger = logging.getLogger(__name__)

BACKUP_FORMAT: Final[str] = "linguafix-backup"
BACKUP_VERSION: Final[int] = 1


def build_backup() -> dict[str, Any]:
    """Return a JSON-serialisable snapshot of the user settings."""
    snippets_file = snippets_path()
    return {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "config": load_config().to_dict(),
        "dictionary": load_user_dictionary(),
        "snippets": snippets_file.read_text(encoding="utf-8") if snippets_file.exists() else "",
    }


def write_backup(path: Path) -> Path:
    """Write a backup to ``path`` and return the resolved path."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_backup(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_backup(path: Path) -> dict[str, Any]:
    """Read and validate a backup file.

    Raises:
        ValueError: If the file is not a LinguaFix backup.
    """
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != BACKUP_FORMAT:
        raise ValueError("not a LinguaFix backup")
    version = data.get("version")
    if not isinstance(version, int) or version > BACKUP_VERSION:
        raise ValueError(f"unsupported backup version: {version!r}")
    return data


def _restore_config(config: dict[str, Any]) -> bool:
    known = set(Config.__dataclass_fields__)
    filtered = {key: value for key, value in config.items() if key in known}
    if not filtered:
        return False
    save_config(Config.from_dict(filtered))
    return True


def apply_backup(
    data: dict[str, Any],
    *,
    restore_config: bool = True,
    restore_dictionary: bool = True,
    restore_snippets: bool = True,
) -> dict[str, int]:
    """Apply the parts of ``data`` selected by the flags.

    Returns a mapping of section name to the number of entries restored
    (``1``/``0`` for the single-file config and snippets).
    """
    result = {"config": 0, "dictionary": 0, "snippets": 0}

    if restore_config and isinstance(data.get("config"), dict):
        result["config"] = 1 if _restore_config(data["config"]) else 0

    if restore_dictionary and isinstance(data.get("dictionary"), list):
        words = [str(word) for word in data["dictionary"] if str(word).strip()]
        save_user_dictionary(words)
        result["dictionary"] = len(words)

    if restore_snippets and isinstance(data.get("snippets"), str):
        text = data["snippets"]
        snippets_file = snippets_path()
        snippets_file.parent.mkdir(parents=True, exist_ok=True)
        snippets_file.write_text(text, encoding="utf-8")
        result["snippets"] = 1

    return result


def backup_paths() -> dict[str, Path]:
    """Return the files a backup covers (for diagnostics)."""
    return {
        "config": config_path(),
        "dictionary": user_dictionary_path(),
        "snippets": snippets_path(),
    }
