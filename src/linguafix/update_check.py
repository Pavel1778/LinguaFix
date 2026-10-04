"""Opt-in update check (Stage 13).

Once a day the daemon asks the GitHub releases API for the latest tag and, if
it is newer than the running version, logs a line and (optionally) shows a
desktop notification. The check is **off by default**: it is the only feature
that talks to the network, so the user must enable it explicitly.

No typed text, configuration content or identifiers are sent — the request is
a plain ``GET`` of the public releases endpoint.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .config import cache_dir

logger = logging.getLogger(__name__)

RELEASES_URL = "https://api.github.com/repos/Pavel1778/LinguaFix/releases/latest"
RELEASES_PAGE = "https://github.com/Pavel1778/LinguaFix/releases/latest"
REQUEST_TIMEOUT = 5.0
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
_STAMP_NAME = "update_check.json"


@dataclass(frozen=True)
class UpdateInfo:
    """Result of an update check."""

    current: str
    latest: str
    update_available: bool
    url: str = ""


def parse_version(text: str) -> tuple[int, ...]:
    """Parse a dotted version into a comparable tuple, ignoring a leading ``v``.

    Non-numeric suffixes (``0.2.0-rc1``) are dropped. Unparsable parts yield
    ``0`` so a malformed remote tag can never look newer by accident.
    """
    cleaned = text.strip().lstrip("vV")
    parts: list[int] = []
    for chunk in cleaned.split("."):
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    """Return ``True`` when ``candidate`` is a strictly newer version."""
    return parse_version(candidate) > parse_version(current)


def _stamp_path() -> Path:
    return cache_dir() / _STAMP_NAME


def _last_check() -> float:
    try:
        return float(json.loads(_stamp_path().read_text(encoding="utf-8"))["last_check"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0.0


def _record_check(now: float) -> None:
    path = _stamp_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_check": now}), encoding="utf-8")
    except OSError:
        logger.debug("Could not write update-check stamp", exc_info=True)


def fetch_latest(url: str = RELEASES_URL, timeout: float = REQUEST_TIMEOUT) -> str:
    """Return the ``tag_name`` of the latest GitHub release.

    Raises:
        OSError: On any network or decoding failure.
    """
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"LinguaFix/{__version__}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise OSError(str(exc)) from exc
    tag = payload.get("tag_name") if isinstance(payload, dict) else None
    if not isinstance(tag, str) or not tag:
        raise OSError("release response has no tag_name")
    return tag


def check_for_update(
    current: str = __version__,
    *,
    url: str = RELEASES_URL,
    fetch: Callable[[str], str] | None = None,
) -> UpdateInfo | None:
    """Check for a newer release.

    Args:
        current: The running version.
        url: Releases endpoint to query.
        fetch: Optional callable ``(url) -> tag`` for tests; defaults to
            :func:`fetch_latest`.

    Returns:
        An :class:`UpdateInfo`, or ``None`` when the check failed (offline).
    """
    getter = fetch or fetch_latest
    try:
        latest = getter(url)
    except OSError as exc:
        logger.debug("Update check failed: %s", exc)
        return None
    return UpdateInfo(
        current=current,
        latest=latest,
        update_available=is_newer(latest, current),
        url=RELEASES_PAGE,
    )


def is_due(now: float, interval: float = CHECK_INTERVAL_SECONDS) -> bool:
    """Return ``True`` when the last check is older than ``interval``."""
    return now - _last_check() >= interval


def maybe_check(
    enabled: bool,
    *,
    now: float,
    current: str = __version__,
    interval: float = CHECK_INTERVAL_SECONDS,
    fetch: Callable[[str], str] | None = None,
) -> UpdateInfo | None:
    """Check at most once per ``interval`` when ``enabled``.

    Throttled by a timestamp in the cache directory, so the daemon can call it
    on every poll without hammering GitHub.
    """
    if not enabled:
        return None
    last = _last_check()
    if last and now - last < interval:
        return None
    info = check_for_update(current, fetch=fetch)
    _record_check(now)
    return info
