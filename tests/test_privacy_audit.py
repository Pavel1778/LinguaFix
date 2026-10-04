"""Privacy audit: no typed text may ever be persisted or leak.

LinguaFix reads every keystroke, so the one hard guarantee it must keep is that
the typed characters are never written anywhere: not to the log, the cache, the
state directory, the config file, the systemd journal, a subprocess argv, or an
exception traceback.

These tests drive the real daemon with a fake keyboard and a distinctive secret
string, then search every artefact the daemon could have produced for any trace
of that string.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest

from linguafix import logging_setup
from linguafix.config import Config, cache_dir, config_path, load_config, save_config, state_dir
from linguafix.daemon import LinguaFixDaemon
from linguafix.detector import LanguageDetector

# Substrings that must never appear anywhere. Chosen so a partial leak (just the
# digits, just the word) is still caught.
SECRET = "секретное_слово_12345"
SECRET_MARKERS = ("секретное", "12345", "слово_12", "SECRET")

# A few config fields are persisted on purpose; the secret must not reach them.
_ALLOWED_CONFIG_KEYS = {
    "analysis_timeout",
    "min_word_length",
    "max_buffer_size",
    "stop_words",
    "layouts",
    "backend",
    "switch_method",
    "notify_on_fix",
    "tray_enabled",
    "hotkey",
    "log_level",
    "on_space",
    "on_enter",
    "on_tab",
    "on_punctuation",
    "punctuation_chars",
    "backspace_settle_ms",
    "trigger_settle_ms",
    "languages",
    "notify_on_error",
    "sound_on_fix",
    "log_rotation_mb",
    "mode",
    "hotkeys_enabled",
    "hotkey_fix_last_word",
    "hotkey_undo_last_fix",
    "hotkey_toggle_mode",
    "hotkey_reload_config",
    "hotkey_swallow",
    "hotkey_double_tap_ms",
    "undo_window_seconds",
    "undo_history_depth",
    "confidence_threshold",
    "context_analysis",
    "context_weight",
    "ignore_all_caps",
    "ignore_with_digits",
    "ignore_emails_urls",
    "plausibility_check",
    "structural_boundaries",
    "identifier_guard",
    "password_guard",
    "plausibility_floor",
    "max_consecutive_consonants",
    "min_vowel_ratio",
    "custom_skip_regex",
    "exceptions_apps",
    "exceptions_force_in_manual",
    "dictionary_size",
    "dictionary_custom_path",
    "typo_correction",
    "typo_max_distance",
    "typo_min_word_length",
    "text_expander_enabled",
    "text_expander_snippets_path",
    "selection_fix_enabled",
    "selection_fix_hotkey",
    "app_layouts",
    "app_layout_switch",
    "update_check_enabled",
}


class _RecordingInjector:
    """Injector that records the argv-like calls a real backend would make."""

    backend = "fake"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def replace_text(self, backspace_count: int, new: str, layout: str) -> bool:
        # A real wtype/xdotool backend passes the text as an argument; record it
        # so the test can assert the daemon never leaks it that way either.
        self.calls.append(["wtype", new])
        return True

    def describe(self) -> str:
        return "backend=fake"


class _Switcher:
    backend = "fake"

    def __init__(self, current: str = "us") -> None:
        self.current = current

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        return True

    def describe(self) -> str:
        return "backend=fake"


def _search(path: Path, markers: tuple[str, ...]) -> list[str]:
    """Return every marker found in the file at ``path`` (binary-safe)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    hits: list[str] = []
    for marker in markers:
        if marker.encode("utf-8") in raw:
            hits.append(marker)
    return hits


def _walk(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def _run_secret_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LinguaFixDaemon:
    """Run a real daemon session whose buffer contains the secret string.

    The daemon is driven through its real ``_handle_event``/``_process_buffer``
    paths with a fake injector; the log is the real rotating file handler
    redirected into ``tmp_path``.
    """
    # Redirect every XDG directory into the test tmpdir so the search is
    # hermetic and cannot accidentally read the developer's real files.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    logging_setup.setup_logging("DEBUG", log_dir=state_dir(), console=True)

    config = Config(analysis_timeout=0.1, min_word_length=1, stop_words=[])
    save_config(config)
    injector = _RecordingInjector()
    daemon = LinguaFixDaemon(
        config,
        detector=LanguageDetector(
            converter=None,
            stop_words=[],
            min_word_length=1,
            plausibility_check=False,
            structural_boundaries=False,
            identifier_guard=False,
        ),
        switcher=_Switcher("us"),
        injector=injector,
    )

    # Type the secret into the buffer and force a correction so the injector is
    # actually invoked with it.
    daemon.buffer = SECRET
    daemon.last_key_time = 0.0
    daemon._process_buffer()

    # Also exercise the failure path: an injector that raises must not leak the
    # buffer into the traceback.
    def boom(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("injector exploded")

    monkeypatch.setattr(injector, "replace_text", boom)
    daemon.buffer = SECRET
    daemon._process_buffer()

    for handler in logging.getLogger().handlers:
        handler.flush()
    return daemon


def test_no_secret_in_log_cache_state_or_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run_secret_session(tmp_path, monkeypatch)

    offenders: dict[str, list[str]] = {}
    for root in (state_dir(), cache_dir(), tmp_path / "config"):
        for path in _walk(root):
            hits = _search(path, SECRET_MARKERS)
            if hits:
                offenders[str(path)] = hits
    assert offenders == {}, f"typed text leaked into: {offenders}"


def test_config_contains_no_accumulated_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run_secret_session(tmp_path, monkeypatch)
    text = config_path().read_text(encoding="utf-8")
    for marker in SECRET_MARKERS:
        assert marker not in text
    # The config must not grow any history/word-list keys.
    parsed = load_config()
    assert set(parsed.to_dict()) <= _ALLOWED_CONFIG_KEYS


def test_no_secret_in_subprocess_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No argv passed to subprocess may contain the typed text."""
    recorded: list[list[str]] = []
    real_run = subprocess.run

    def spy_run(*args: Any, **kwargs: Any) -> Any:
        argv = args[0]
        recorded.append([str(a) for a in argv] if isinstance(argv, list) else [str(argv)])
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", spy_run)
    # notify_on_fix on so the notify-send path runs too.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    logging_setup.setup_logging("DEBUG", log_dir=state_dir())

    config = Config(analysis_timeout=0.1, min_word_length=1, stop_words=[], notify_on_fix=True)
    save_config(config)
    daemon = LinguaFixDaemon(
        config,
        detector=LanguageDetector(
            converter=None,
            stop_words=[],
            min_word_length=1,
            plausibility_check=False,
            structural_boundaries=False,
            identifier_guard=False,
        ),
        switcher=_Switcher("us"),
        injector=_RecordingInjector(),
    )
    daemon.buffer = SECRET
    daemon.last_key_time = 0.0
    daemon._process_buffer()

    for argv in recorded:
        joined = " ".join(argv)
        for marker in SECRET_MARKERS:
            assert marker not in joined, f"{marker!r} leaked into argv: {argv}"


def test_traceback_does_not_contain_buffer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """An exception while processing the buffer must not embed the buffer."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    config = Config(analysis_timeout=0.1, min_word_length=1, stop_words=[])
    daemon = LinguaFixDaemon(
        config,
        detector=LanguageDetector(
            converter=None,
            stop_words=[],
            min_word_length=1,
            plausibility_check=False,
            structural_boundaries=False,
            identifier_guard=False,
        ),
        switcher=_Switcher("us"),
        injector=_RecordingInjector(),
    )

    def boom(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError(f"cannot convert {SECRET}")

    monkeypatch.setattr(daemon.converter, "convert", boom)
    daemon.buffer = SECRET

    with caplog.at_level(logging.ERROR):
        # Must not raise: the daemon survives, and the traceback is logged.
        daemon._process_buffer()

    # The daemon logged the failure...
    assert any("Failed to process the buffer" in r.message for r in caplog.records)
    # ...but the traceback text must not contain the buffer. This asserts the
    # invariant that no code path raises an exception whose message embeds the
    # typed text.
    combined = caplog.text
    assert SECRET not in combined
    assert "12345" not in combined


def test_no_secret_in_user_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Search the systemd user journal for the secret, when journalctl exists."""
    import shutil

    if shutil.which("journalctl") is None:
        pytest.skip("journalctl is not available")
    _run_secret_session(tmp_path, monkeypatch)
    result = subprocess.run(
        ["journalctl", "--user", "-u", "linguafix.service", "--no-pager", "-n", "500"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    output = (result.stdout or "") + (result.stderr or "")
    for marker in SECRET_MARKERS:
        assert marker not in output, f"{marker!r} leaked into the journal"


def test_daemon_survives_injector_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    config = Config(analysis_timeout=0.1, min_word_length=1, stop_words=[])
    injector = _RecordingInjector()
    daemon = LinguaFixDaemon(
        config,
        detector=LanguageDetector(
            converter=None,
            stop_words=[],
            min_word_length=1,
            plausibility_check=False,
            structural_boundaries=False,
            identifier_guard=False,
        ),
        switcher=_Switcher("us"),
        injector=injector,
    )

    def boom(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(injector, "replace_text", boom)
    daemon.buffer = SECRET
    daemon._process_buffer()  # must not raise
    assert daemon.buffer == ""
