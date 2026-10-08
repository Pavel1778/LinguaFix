"""Extended (frequency) dictionaries: file handling, CLI and detector wiring."""

from __future__ import annotations

import io
import urllib.error
from pathlib import Path

import pytest

from linguafix import cli
from linguafix.config import Config
from linguafix.detector import LanguageDetector
from linguafix.dictionary import (
    BUNDLED_DICTIONARY_LANGUAGES,
    bundled_dictionary_source,
    default_extended_dictionary_dir,
    download_extended_dictionary,
    extended_dictionary_path,
    import_dictionary_file,
    load_extended_dictionary,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_default_dir_is_under_xdg_data(isolated_home: Path) -> None:
    directory = default_extended_dictionary_dir()
    assert directory == isolated_home / "xdg_data_home" / "linguafix" / "dictionaries"


def test_path_and_load_round_trip(tmp_path: Path) -> None:
    data_dir = tmp_path / "dicts"
    source = tmp_path / "wordlist.txt"
    source.write_text("# comment\nпривет\nмир  42\n\nhello\nПРИВЕТ\n", encoding="utf-8")
    count = import_dictionary_file(str(source), "ru", str(data_dir))
    # Deduplicated case-insensitively, sorted, comments and frequencies dropped.
    assert count == 3
    written = extended_dictionary_path("ru", str(data_dir)).read_text(encoding="utf-8")
    assert written.splitlines() == ["привет", "мир", "hello"]
    assert load_extended_dictionary("ru", str(data_dir)) == {"привет", "мир", "hello"}


def test_load_absent_dictionary_is_empty(tmp_path: Path) -> None:
    assert load_extended_dictionary("ru", str(tmp_path / "nope")) == set()


def test_import_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        import_dictionary_file(str(tmp_path / "missing.txt"), "ru", str(tmp_path))


def test_import_requires_language(tmp_path: Path) -> None:
    source = tmp_path / "words.txt"
    source.write_text("hi\n", encoding="utf-8")
    with pytest.raises(ValueError):
        import_dictionary_file(str(source), "  ", str(tmp_path))


def test_download_rejects_unknown_language(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        download_extended_dictionary("xx", str(tmp_path))


def test_download_tries_release_asset_before_mirror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stable ``/releases/latest/download`` asset is the first source tried."""
    seen: list[str] = []
    payload = b"alpha\nbeta\n"

    class _Response(io.BytesIO):
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def fake_urlopen(url: str, timeout: float = 0) -> _Response:
        seen.append(url)
        return _Response(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    download_extended_dictionary("ru", str(tmp_path))
    assert seen[0].startswith("https://github.com/Pavel1778/LinguaFix/releases/latest/download/")
    assert seen[0].endswith("ru-50k.txt")


def test_download_falls_back_to_bundled_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When every network source fails the shipped list is used (offline works)."""

    def fail(url: str, timeout: float = 0) -> object:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    target, count = download_extended_dictionary("ru", str(tmp_path))
    assert count > 1000
    assert target.is_file()


def test_bundled_dictionary_source_finds_repo_lists() -> None:
    for language in BUNDLED_DICTIONARY_LANGUAGES:
        source = bundled_dictionary_source(language)
        assert source is not None, language
        assert source.is_file()
        assert source.parent == REPO_ROOT / "dictionaries"


def test_repo_ships_all_advertised_dictionaries() -> None:
    """Every advertised language must have a ``dictionaries/<lang>-50k.txt``."""
    for language in BUNDLED_DICTIONARY_LANGUAGES:
        assert (REPO_ROOT / "dictionaries" / f"{language}-50k.txt").is_file()


def test_download_writes_the_mirror_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = b"alpha\nbeta\n"

    class _Response(io.BytesIO):
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    def fake_urlopen(url: str, timeout: float = 0) -> _Response:
        return _Response(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    target, count = download_extended_dictionary("ru", str(tmp_path))
    assert count == 2
    assert target.read_text(encoding="utf-8").splitlines() == ["alpha", "beta"]


# --- Detector integration -------------------------------------------------


def test_extended_dictionary_widens_vocabulary(tmp_path: Path) -> None:
    data_dir = tmp_path / "dicts"
    data_dir.mkdir()
    # A Cyrillic word the bundled corpus has never seen.
    (data_dir / "ru.txt").write_text("флумпель\n", encoding="utf-8")
    detector = LanguageDetector(extended_dictionary_dir=str(data_dir))
    assert "флумпель" in detector.vocabulary("ru")


def test_extended_dictionary_dir_survives_reload(tmp_path: Path) -> None:
    data_dir = tmp_path / "dicts"
    data_dir.mkdir()
    (data_dir / "ru.txt").write_text("флумпель\n", encoding="utf-8")
    detector = LanguageDetector()
    assert "флумпель" not in detector.vocabulary("ru")
    detector.set_extended_dictionary_dir(str(data_dir))
    assert "флумпель" in detector.vocabulary("ru")


# --- Config plumbing ------------------------------------------------------


def test_config_normalises_extended_dir() -> None:
    assert Config(extended_dictionary_dir="  /tmp/x  ").extended_dictionary_dir == "/tmp/x"
    assert Config().extended_dictionary_dir == ""


# --- CLI ------------------------------------------------------------------


def _run_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", ["linguafix", *argv])
    return cli.main()


def test_cli_import_file_saves_config(
    isolated_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "ru-50k.txt"
    source.write_text("привет\nмир\n", encoding="utf-8")
    code = _run_cli(
        monkeypatch,
        ["dict", "import-file", str(source), "--lang", "ru"],
    )
    # The command writes into the default XDG dir, which `isolated_home` moved.
    assert code == 0
    out = capsys.readouterr().out
    assert "Импортировано 2 слов" in out


def test_cli_download_language(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = b"alpha\nbeta\n"

    class _Response(io.BytesIO):
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=0: _Response(payload))
    code = _run_cli(monkeypatch, ["dict", "download", "ru"])
    assert code == 0
    assert "Скачано 2 слов" in capsys.readouterr().out


def test_cli_download_unknown_language(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_cli(monkeypatch, ["dict", "download", "xx"])
    assert code == 2
    assert "unsupported language" in capsys.readouterr().out
