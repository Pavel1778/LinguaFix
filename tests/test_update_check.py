"""Opt-in update check (Stage 13)."""

from __future__ import annotations

from pathlib import Path

import pytest

from linguafix import update_check


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v0.2.0", (0, 2, 0)),
        ("0.2.0", (0, 2, 0)),
        ("1.10.3", (1, 10, 3)),
        ("0.2.0-rc1", (0, 2, 0)),
        ("garbage", (0,)),
        ("", (0,)),
    ],
)
def test_parse_version(text: str, expected: tuple[int, ...]) -> None:
    assert update_check.parse_version(text) == expected


def test_is_newer() -> None:
    assert update_check.is_newer("v0.3.0", "0.2.0") is True
    assert update_check.is_newer("0.2.0", "0.2.0") is False
    assert update_check.is_newer("0.1.9", "0.2.0") is False
    assert update_check.is_newer("0.2.1", "0.2.0") is True


def test_check_for_update_available(isolated_env: Path) -> None:
    info = update_check.check_for_update("0.2.0", fetch=lambda _url: "v0.3.0")
    assert info is not None
    assert info.update_available is True
    assert info.latest == "v0.3.0"
    assert "releases" in info.url


def test_check_for_update_offline_returns_none(isolated_env: Path) -> None:
    def boom(_url: str) -> str:
        raise OSError("no network")

    assert update_check.check_for_update("0.2.0", fetch=boom) is None


def test_fetch_latest_bad_payload(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    class _Response(io.BytesIO):
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(update_check.urllib.request, "urlopen", lambda *_a, **_k: _Response(b"{}"))
    with pytest.raises(OSError, match="tag_name"):
        update_check.fetch_latest()


def test_maybe_check_disabled_is_noop(isolated_env: Path) -> None:
    called: list[str] = []
    assert (
        update_check.maybe_check(False, now=1000.0, fetch=lambda u: called.append(u) or "1.0")
        is None
    )
    assert called == []


def test_maybe_check_throttles(isolated_env: Path) -> None:
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return "9.9.9"

    first = update_check.maybe_check(True, now=1000.0, current="0.2.0", fetch=fetch)
    assert first is not None and first.update_available
    assert len(calls) == 1

    # Within the interval: no second network call.
    assert update_check.maybe_check(True, now=1000.0 + 10, current="0.2.0", fetch=fetch) is None
    assert len(calls) == 1

    # Past the interval: checks again.
    second = update_check.maybe_check(
        True, now=1000.0 + update_check.CHECK_INTERVAL_SECONDS + 1, current="0.2.0", fetch=fetch
    )
    assert second is not None
    assert len(calls) == 2


def test_daemon_check_disabled_does_nothing(
    monkeypatch: pytest.MonkeyPatch, isolated_env: Path
) -> None:
    from linguafix.config import Config
    from linguafix.daemon import LinguaFixDaemon

    daemon = LinguaFixDaemon(config=Config(update_check_enabled=False))
    called: list[int] = []
    monkeypatch.setattr(update_check, "check_for_update", lambda *a, **k: called.append(1) or None)
    daemon._maybe_check_update()
    assert called == []


def test_daemon_check_enabled_notifies(monkeypatch: pytest.MonkeyPatch, isolated_env: Path) -> None:
    from linguafix.config import Config
    from linguafix.daemon import LinguaFixDaemon

    daemon = LinguaFixDaemon(config=Config(update_check_enabled=True))
    info = update_check.UpdateInfo("0.2.0", "v0.3.0", True, "https://example/releases")
    monkeypatch.setattr(update_check, "check_for_update", lambda *a, **k: info)
    notified: list[str] = []
    monkeypatch.setattr(daemon, "_notify_update", notified.append)

    daemon._maybe_check_update()
    assert notified == ["v0.3.0"]
    # A second call within the interval is throttled in memory.
    daemon._maybe_check_update()
    assert notified == ["v0.3.0"]
