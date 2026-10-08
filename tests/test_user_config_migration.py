"""Migration of a real v0.2.7 ``config.toml`` (from the live-test report).

This reproduces the exact file the user pasted from ``linguafix config show``
on v0.2.7 and asserts what v0.2.8 turns it into on first load. The rules are:

* stale *defaults* are upgraded (``hotkey_undo_last_fix = "CTRL+CTRL"``,
  ``hotkey_double_tap_ms = 300``, the ``gedit`` exception, a float tail);
* the user's explicit choices are left alone (``mode = "manual"``,
  ``backspace_settle_ms = 80``, ``min_word_length = 3``).
"""

from __future__ import annotations

from pathlib import Path

from linguafix.config import DEFAULT_DOUBLE_TAP_MS, Config, load_config

# The user's v0.2.7 config, copied verbatim from ``linguafix config show``
# (the ``stop_words`` list is trimmed to a few entries — it is not migrated).
USER_CONFIG_V027 = """\
analysis_timeout = 0.7000000000000001
analysis_timeout_adaptive = true
min_word_length = 3
max_buffer_size = 200
stop_words = ["password", "token", "secret", "email"]
layouts = ["us", "ru"]
languages = ["en", "ru"]
backend = "auto"
switch_method = "auto"
notify_on_fix = false
notify_on_error = false
sound_on_fix = false
tray_enabled = true
hotkey = "SHIFT+SHIFT"
log_level = "INFO"
log_rotation_mb = 5
on_space = true
on_enter = true
on_tab = false
on_punctuation = false
punctuation_chars = ".!?,;:"
backspace_settle_ms = 80
trigger_settle_ms = 50
mode = "manual"
hotkeys_enabled = true
hotkey_fix_last_word = "SHIFT+SHIFT"
hotkey_undo_last_fix = "CTRL+CTRL"
hotkey_toggle_mode = ""
hotkey_reload_config = "CTRL+SHIFT+R"
hotkey_swallow = true
hotkey_double_tap_ms = 300
undo_window_seconds = 10
undo_history_depth = 3
confidence_threshold = 0.6
context_analysis = true
context_weight = 0.3
ignore_all_caps = false
ignore_with_digits = false
ignore_emails_urls = true
plausibility_check = true
structural_boundaries = true
identifier_guard = true
password_guard = true
plausibility_floor = -7.0
max_consecutive_consonants = 6
min_vowel_ratio = 0.15
custom_skip_regex = ""
exceptions_apps = ["gnome-terminal", "kgx", "code", "sublime_text", "gedit", "steam"]
exceptions_force_in_manual = []
dictionary_size = 5000
dictionary_custom_path = ""
history_size = 20
quiet_hours_enabled = false
quiet_hours_start = "22:00"
quiet_hours_end = "08:00"
typo_correction = true
typo_max_distance = 1
typo_min_word_length = 4
typo_max_distance_long = 2
typo_long_word_threshold = 6
typo_top1_ratio_strict = 10.0
punctuation_correction = true
punctuation_dashes = true
punctuation_ellipsis = true
punctuation_smart_quotes = false
punctuation_fix_spacing = true
text_expander_enabled = false
text_expander_snippets_path = ""
selection_fix_enabled = true
selection_fix_hotkey = "CTRL+SHIFT+L"
app_layout_switch = false
update_check_enabled = false
"""


def _load_user_config(tmp_path: Path) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(USER_CONFIG_V027, encoding="utf-8")
    return load_config(path)


def test_stale_defaults_are_migrated(tmp_path: Path) -> None:
    config = _load_user_config(tmp_path)
    # A float slider tail is rounded on load.
    assert config.analysis_timeout == 0.7
    # The pre-0.2.8 undo default is not a real binding.
    assert config.hotkey_undo_last_fix == "SHIFT+BACKSPACE"
    # The pre-0.2.8 double-tap window is too short.
    assert config.hotkey_double_tap_ms == DEFAULT_DOUBLE_TAP_MS == 2000
    # The old text-editor exception entry is upgraded to the current one.
    assert "gedit" not in config.exceptions_apps
    assert "texteditor" in config.exceptions_apps


def test_user_choices_are_preserved(tmp_path: Path) -> None:
    config = _load_user_config(tmp_path)
    assert config.mode == "manual"
    assert config.backspace_settle_ms == 80
    assert config.min_word_length == 3
    assert config.typo_correction is True
    assert config.trigger_settle_ms == 50


def test_absent_toggle_layout_hotkey_gets_the_default(tmp_path: Path) -> None:
    """The field was missing from the user's file; it must default, not crash."""
    config = _load_user_config(tmp_path)
    assert config.hotkey_toggle_layout_last_word == "CTRL+SHIFT+T"


def test_other_exception_entries_are_kept(tmp_path: Path) -> None:
    config = _load_user_config(tmp_path)
    for app in ("gnome-terminal", "kgx", "code", "sublime_text", "steam"):
        assert app in config.exceptions_apps


def test_migrated_config_round_trips(tmp_path: Path) -> None:
    """Saving the migrated config must persist the new values (config show)."""
    from linguafix.config import save_config

    path = tmp_path / "config.toml"
    config = _load_user_config(tmp_path)
    save_config(config, path)
    text = path.read_text(encoding="utf-8")
    assert "hotkey_undo_last_fix = 'SHIFT+BACKSPACE'" in text.replace('"', "'")
    assert "hotkey_double_tap_ms = 2000" in text
    assert "0.7000000000000001" not in text

    reloaded = load_config(path)
    assert reloaded.hotkey_double_tap_ms == 2000
    assert reloaded.mode == "manual"
