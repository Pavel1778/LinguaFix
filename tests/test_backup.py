"""Export/import of user settings (Stage 11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from linguafix import backup, cli
from linguafix.config import Config, load_config


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path


def test_build_backup_shape(isolated_env: Path) -> None:
    data = backup.build_backup()
    assert data["format"] == backup.BACKUP_FORMAT
    assert data["version"] == backup.BACKUP_VERSION
    assert isinstance(data["config"], dict)
    assert data["dictionary"] == []
    assert data["snippets"] == ""


def test_roundtrip_config_dictionary_snippets(
    isolated_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Configure something non-default, a dictionary word and a snippet.
    config = Config(mode="hybrid", typo_correction=True)
    from linguafix.config import save_config
    from linguafix.dictionary import add_user_word

    save_config(config)
    add_user_word("vercel")
    snippets = backup.snippets_path()
    snippets.parent.mkdir(parents=True, exist_ok=True)
    snippets.write_text('[snippets]\n"дт" = "{date}"\n', encoding="utf-8")

    out = isolated_env / "b.json"
    assert cli.main(["export", str(out)]) == 0
    assert "сохранены" in capsys.readouterr().out
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["config"]["mode"] == "hybrid"
    assert payload["dictionary"] == ["vercel"]

    # Wipe and restore.
    from linguafix.dictionary import load_user_dictionary, save_user_dictionary

    save_user_dictionary([])
    save_config(Config())
    snippets.write_text("", encoding="utf-8")

    assert cli.main(["import", str(out)]) == 0
    assert "Восстановлено" in capsys.readouterr().out
    assert load_config().mode == "hybrid"
    assert load_user_dictionary() == ["vercel"]
    assert "{date}" in snippets.read_text(encoding="utf-8")


def test_apply_backup_selective(isolated_env: Path) -> None:
    data = {
        "format": backup.BACKUP_FORMAT,
        "version": 1,
        "config": Config(mode="manual").to_dict(),
        "dictionary": ["alpha"],
        "snippets": "[snippets]\n",
    }
    result = backup.apply_backup(data, restore_config=False)
    assert result["config"] == 0
    assert result["dictionary"] == 1
    assert load_config().mode == "auto"


def test_read_backup_rejects_foreign_file(isolated_env: Path, tmp_path: Path) -> None:
    path = tmp_path / "nope.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="not a LinguaFix backup"):
        backup.read_backup(path)


def test_read_backup_rejects_future_version(isolated_env: Path, tmp_path: Path) -> None:
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"format": backup.BACKUP_FORMAT, "version": 99}), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported backup version"):
        backup.read_backup(path)


def test_import_missing_file(isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["import", str(isolated_env / "missing.json")]) == 1
    assert "Не удалось прочитать" in capsys.readouterr().out


def test_config_path_command(isolated_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["config", "path"]) == 0
    assert "config.toml" in capsys.readouterr().out


def test_restart_command(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import linguafix.daemon_control as dc

    monkeypatch.setattr(dc, "restart", lambda: True)
    assert cli.main(["restart"]) == 0
    assert "запущен" in capsys.readouterr().out

    monkeypatch.setattr(dc, "restart", lambda: False)
    assert cli.main(["restart"]) == 1


def test_backup_paths(isolated_env: Path) -> None:
    paths = backup.backup_paths()
    assert set(paths) == {"config", "dictionary", "snippets"}
    assert paths["config"].name == "config.toml"
