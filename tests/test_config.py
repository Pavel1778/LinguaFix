"""Tests for :mod:`linguafix.config`."""

from __future__ import annotations

from pathlib import Path

import pytest

from linguafix import config as config_module
from linguafix.config import Config, load_config, save_config


def test_defaults() -> None:
    config = Config()
    assert config.analysis_timeout == 0.8
    assert config.min_word_length == 3
    assert config.layouts == ["us", "ru"]
    assert config.backend == "auto"
    assert config.switch_method == "auto"
    assert config.notify_on_fix is False
    assert config.tray_enabled is True
    assert config.hotkey == "SHIFT+SHIFT"
    assert config.log_level == "INFO"
    assert config.on_space is True
    assert config.on_enter is True
    assert config.on_tab is False
    assert config.on_punctuation is False
    assert config.punctuation_chars == ".!?,;:"
    assert config.backspace_settle_ms == 30
    assert isinstance(config.stop_words, list)
    assert "password" in config.stop_words


def test_load_creates_default_file(tmp_config_path: Path) -> None:
    config = load_config(tmp_config_path)
    assert tmp_config_path.exists()
    assert config.analysis_timeout == 0.8
    text = tmp_config_path.read_text(encoding="utf-8")
    assert "analysis_timeout" in text
    assert "on_space" in text
    assert "backspace_settle_ms" in text


def test_save_and_load_round_trip(tmp_config_path: Path) -> None:
    config = Config()
    config.analysis_timeout = 2.5
    config.min_word_length = 4
    config.layouts = ["us", "ru", "de"]
    config.notify_on_fix = True
    config.log_level = "DEBUG"
    save_config(config, tmp_config_path)

    loaded = load_config(tmp_config_path)
    assert loaded.analysis_timeout == 2.5
    assert loaded.min_word_length == 4
    assert loaded.layouts == ["us", "ru", "de"]
    assert loaded.notify_on_fix is True
    assert loaded.log_level == "DEBUG"


def test_corrupted_toml_falls_back_to_defaults(tmp_config_path: Path) -> None:
    tmp_config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_config_path.write_text("this is = not [ valid toml", encoding="utf-8")
    config = load_config(tmp_config_path)
    assert config.analysis_timeout == 0.8
    backups = list(tmp_config_path.parent.glob("config.toml.corrupt-*"))
    assert len(backups) == 1


def test_invalid_values_fall_back_to_defaults(tmp_config_path: Path) -> None:
    tmp_config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_config_path.write_text('backend = "nonsense"\n', encoding="utf-8")
    config = load_config(tmp_config_path)
    assert config.backend == "auto"


def test_unknown_keys_are_ignored(tmp_config_path: Path) -> None:
    tmp_config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_config_path.write_text("unknown_key = 1\nanalysis_timeout = 3.0\n", encoding="utf-8")
    config = load_config(tmp_config_path)
    assert config.analysis_timeout == 3.0


def test_validation_normalises_values() -> None:
    config = Config(layouts=["US", "RU"], backend="UINPUT", log_level="debug")
    assert config.layouts == ["us", "ru"]
    assert config.backend == "uinput"
    assert config.log_level == "DEBUG"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"analysis_timeout": 0},
        {"analysis_timeout": -1.0},
        {"min_word_length": 0},
        {"layouts": []},
        {"backend": "bogus"},
        {"switch_method": "bogus"},
        {"log_level": "bogus"},
        {"backspace_settle_ms": -1},
    ],
)
def test_validation_rejects_bad_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Config(**kwargs)


def test_new_field_defaults() -> None:
    config = Config()
    assert config.mode == "auto"
    assert config.languages == ["en", "ru"]
    assert config.hotkeys_enabled is True
    assert config.hotkey_fix_last_word == "SHIFT+SHIFT"
    assert config.hotkey_undo_last_fix == "CTRL+Z"
    assert config.hotkey_reload_config == "CTRL+SHIFT+R"
    assert config.hotkey_toggle_mode == ""
    assert config.hotkey_double_tap_ms == 300
    assert config.undo_window_seconds == 10
    assert config.undo_history_depth == 3
    assert config.confidence_threshold == 0.6
    assert config.context_analysis is True
    assert config.context_weight == 0.3
    assert config.ignore_emails_urls is True
    assert config.dictionary_size == 5000
    assert config.exceptions_apps == []
    assert config.log_rotation_mb == 5
    assert config.notify_on_error is False
    assert config.sound_on_fix is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "bogus"},
        {"languages": ["xx"]},
        {"languages": []},
        {"undo_window_seconds": 1},
        {"undo_window_seconds": 100},
        {"undo_history_depth": 0},
        {"confidence_threshold": 0.1},
        {"confidence_threshold": 0.99},
        {"context_weight": 2.0},
        {"dictionary_size": 123},
        {"log_rotation_mb": 0},
        {"log_rotation_mb": 100},
        {"backspace_settle_ms": 500},
        {"custom_skip_regex": "([unclosed"},
        {"hotkey_fix_last_word": "ENTER"},
        {"hotkey_fix_last_word": "CTRL+SPACE"},
        {"hotkey_undo_last_fix": "TAB"},
    ],
)
def test_new_field_validation_rejects_bad_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Config(**kwargs)


def test_hotkey_normalisation() -> None:
    config = Config(hotkey_fix_last_word="ctrl+shift+f12", hotkey_undo_last_fix="pause")
    assert config.hotkey_fix_last_word == "CTRL+SHIFT+F12"
    assert config.hotkey_undo_last_fix == "PAUSE"


def test_legacy_hotkey_syncs_to_fix_hotkey() -> None:
    config = Config(hotkey="F13")
    assert config.hotkey_fix_last_word == "F13"


def test_old_pause_default_migrates_to_double_shift() -> None:
    # A config written before the double-tap default: both fields carry PAUSE.
    config = Config(hotkey="PAUSE", hotkey_fix_last_word="PAUSE")
    assert config.hotkey_fix_last_word == "SHIFT+SHIFT"
    assert config.hotkey == "SHIFT+SHIFT"


def test_deliberate_pause_on_new_field_is_preserved() -> None:
    # The user explicitly chose PAUSE only on the new field; leave it alone.
    config = Config(hotkey="PAUSE", hotkey_fix_last_word="F13")
    assert config.hotkey_fix_last_word == "F13"


def test_explicit_legacy_pause_without_new_field_keeps_pause() -> None:
    # Legacy-only value is treated as a deliberate choice (there is no second
    # PAUSE to prove it is the old default), so it is not migrated.
    config = Config(hotkey="PAUSE")
    assert config.hotkey_fix_last_word == "PAUSE"


def test_section_tables_are_flattened() -> None:
    config = Config.from_dict(
        {
            "trigger": {"on_space": False},
            "hotkeys": {"fix_last_word": "F13", "swallow": False},
            "notifications": {"sound_on_fix": True},
            "undo": {"window_seconds": 20},
            "exceptions": {"apps": ["gnome-terminal"]},
            "dictionary": {"size": 1000},
        }
    )
    assert config.on_space is False
    assert config.hotkey_fix_last_word == "F13"
    assert config.hotkey_swallow is False
    assert config.sound_on_fix is True
    assert config.undo_window_seconds == 20
    assert config.exceptions_apps == ["gnome-terminal"]
    assert config.dictionary_size == 1000


def test_exceptions_strip_blanks() -> None:
    config = Config(exceptions_apps=[" code ", "", "kitty"])
    assert config.exceptions_apps == ["code", "kitty"]


def test_trigger_and_timing_fields_round_trip(tmp_config_path: Path) -> None:
    config = Config()
    config.on_tab = True
    config.on_punctuation = True
    config.punctuation_chars = ".,"
    config.backspace_settle_ms = 60
    save_config(config, tmp_config_path)

    loaded = load_config(tmp_config_path)
    assert loaded.on_space is True
    assert loaded.on_tab is True
    assert loaded.on_punctuation is True
    assert loaded.punctuation_chars == ".,"
    assert loaded.backspace_settle_ms == 60


def test_to_dict_contains_all_fields() -> None:
    data = Config().to_dict()
    for field in Config.__dataclass_fields__:
        assert field in data


def test_xdg_paths_honour_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert config_module.config_path() == tmp_path / "cfg" / "linguafix" / "config.toml"
    assert config_module.state_dir() == tmp_path / "state" / "linguafix"
    assert config_module.cache_dir() == tmp_path / "cache" / "linguafix"


def test_stop_words_are_lower_cased() -> None:
    config = Config(stop_words=["PassWord", "LOGIN"])
    assert config.stop_words == ["password", "login"]


def test_from_dict_ignores_unknown_keys() -> None:
    config = Config.from_dict({"analysis_timeout": 2.0, "nope": True})
    assert config.analysis_timeout == 2.0


def test_from_dict_bad_types_fall_back() -> None:
    config = Config.from_dict({"analysis_timeout": "not-a-number"})
    assert config.analysis_timeout == 0.8
