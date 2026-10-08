"""Thematic (professional) dictionaries: content, CLI, priority and .deb."""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from linguafix import cli
from linguafix.config import Config
from linguafix.detector import LanguageDetector
from linguafix.thematic import (
    CATEGORIES,
    category,
    category_slugs,
    disable_category,
    download_category,
    enable_category,
    installed_category_slugs,
    load_thematic_words,
    repo_category_source,
    thematic_path,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DICTIONARIES = REPO_ROOT / "dictionaries"


def _run_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr("sys.argv", ["linguafix", *argv])
    return cli.main()


# --- Repository content ----------------------------------------------------


def test_every_category_ships_both_languages() -> None:
    for cat in CATEGORIES:
        for language in cat.languages:
            source = repo_category_source(cat.slug, language)
            assert source is not None, f"{cat.slug}/{language}"
            assert source.is_file()
            assert source.parent == DICTIONARIES / cat.slug


def test_every_category_has_a_readme() -> None:
    for cat in CATEGORIES:
        assert (DICTIONARIES / cat.slug / "README.md").is_file(), cat.slug


def test_category_files_are_non_trivial() -> None:
    """A shipped list must hold real words, not a stub."""
    for cat in CATEGORIES:
        for language in cat.languages:
            source = repo_category_source(cat.slug, language)
            assert source is not None
            words = [w for w in source.read_text(encoding="utf-8").splitlines() if w.strip()]
            assert len(words) >= 50, f"{cat.slug}/{language} has only {len(words)} words"
            # One word per line, UTF-8, no frequency column.
            assert all(" " not in w.strip() for w in words[:20])


def test_category_slugs_are_unique() -> None:
    slugs = category_slugs()
    assert len(slugs) == len(set(slugs))
    assert "base" not in slugs  # base is the general list, not a thematic one


def test_expected_category_set_is_shipped() -> None:
    """v0.2.8.1 adds seven professional categories to the original five."""
    expected = {
        "it",
        "medicine",
        "legal",
        "finance",
        "engineering",
        "science",
        "business",
        "electronics",
        "media",
        "education",
        "gaming",
        "sport",
    }
    assert set(category_slugs()) == expected


# --- Download / offline fallback ------------------------------------------


def test_download_category_uses_bundled_copy_when_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.error

    def fail(url: str, timeout: float = 0) -> object:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    target, count = download_category("it", "ru", str(tmp_path))
    assert count >= 50
    assert target.is_file()
    assert target == thematic_path("it", "ru", str(tmp_path))


def test_download_category_prefers_release_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def make_archive(member: str, text: str) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            payload = text.encode("utf-8")
            info = tarfile.TarInfo(member)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        return buffer.getvalue()

    def fake_urlopen(url: str, timeout: float = 0) -> io.BytesIO:
        seen.append(url)
        return io.BytesIO(make_archive("ru-it-1k.txt", "алгоритм\nдеплой\n"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    _, count = download_category("it", "ru", str(tmp_path))
    assert seen[0].endswith("linguafix-dict-it.tar.gz")
    assert count == 2
    assert load_thematic_words("it", "ru", str(tmp_path)) == {"алгоритм", "деплой"}


def test_download_category_rejects_unknown(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        download_category("nope", "ru", str(tmp_path))
    with pytest.raises(ValueError):
        download_category("it", "zz", str(tmp_path))


def test_category_lookup_helpers() -> None:
    assert category("IT") is not None
    assert category("it").slug == "it"  # type: ignore[union-attr]
    assert category("missing") is None


# --- Config plumbing -------------------------------------------------------


def test_config_defaults_to_base_only() -> None:
    assert Config().installed_dict_categories == ["base"]


def test_config_normalises_and_keeps_base() -> None:
    config = Config(installed_dict_categories=["IT", " it ", "medicine"])
    assert config.installed_dict_categories == ["base", "it", "medicine"]
    # ``base`` is re-inserted even when the caller drops it.
    assert Config(installed_dict_categories=["it"]).installed_dict_categories == ["base", "it"]
    assert Config(installed_dict_categories="legal").installed_dict_categories == ["base", "legal"]


def test_enable_and_disable_category() -> None:
    assert enable_category(["base"], "it") == ["base", "it"]
    assert enable_category(["base", "it"], "it") == ["base", "it"]
    assert disable_category(["base", "it", "legal"], "it") == ["base", "legal"]
    # ``base`` cannot be removed.
    assert disable_category(["base"], "base") == ["base"]


# --- Detector integration / priority --------------------------------------


def test_thematic_words_widen_the_vocabulary(tmp_path: Path) -> None:
    data_dir = tmp_path / "dicts"
    download_category("it", "ru", str(data_dir))
    detector = LanguageDetector(
        extended_dictionary_dir=str(data_dir), thematic_categories=["base", "it"]
    )
    assert "деплой" in detector.vocabulary("ru")


def test_category_not_enabled_is_not_loaded(tmp_path: Path) -> None:
    data_dir = tmp_path / "dicts"
    download_category("legal", "ru", str(data_dir))
    detector = LanguageDetector(extended_dictionary_dir=str(data_dir), thematic_categories=["base"])
    assert "юрисдикция" not in detector.vocabulary("ru")
    detector.set_thematic_categories(["base", "legal"])
    assert "юрисдикция" in detector.vocabulary("ru")


def test_user_dictionary_outranks_thematic(tmp_path: Path) -> None:
    """A word the user taught wins over a thematic word (priority order)."""
    data_dir = tmp_path / "dicts"
    download_category("it", "ru", str(data_dir))
    detector = LanguageDetector(
        extended_dictionary_dir=str(data_dir),
        thematic_categories=["base", "it"],
        user_words=["деплой"],
    )
    assert detector.is_user_word("деплой")
    # And the detector still scores the user word as a known word.
    assert "деплой" in detector.vocabulary("ru")


# --- CLI -------------------------------------------------------------------


def test_cli_categories_lists_all(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_cli(monkeypatch, ["dict", "categories"])
    assert code == 0
    out = capsys.readouterr().out
    for cat in CATEGORIES:
        assert cat.slug in out


def test_cli_install_and_remove_category(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_cli(monkeypatch, ["dict", "install", "it", "--lang", "ru"])
    assert code == 0
    assert "Установлено" in capsys.readouterr().out
    directory = isolated_home / "xdg_data_home" / "linguafix" / "dictionaries"
    assert thematic_path("it", "ru", str(directory)).is_file()

    assert _run_cli(monkeypatch, ["dict", "list-installed"]) == 0
    assert "it" in capsys.readouterr().out

    assert _run_cli(monkeypatch, ["dict", "remove-category", "it"]) == 0
    assert "отключена" in capsys.readouterr().out
    from linguafix.config import load_config

    assert load_config().installed_dict_categories == ["base"]


def test_cli_install_unknown_category(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_cli(monkeypatch, ["dict", "install", "nope"])
    assert code == 2
    assert "Неизвестная категория" in capsys.readouterr().out


def test_installed_category_slugs_reports_disk(
    isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.error

    def fail(url: str, timeout: float = 0) -> object:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    directory = isolated_home / "xdg_data_home" / "linguafix" / "dictionaries"
    download_category("medicine", "ru", str(directory))
    assert installed_category_slugs("ru", str(directory)) == ("medicine",)
    assert installed_category_slugs("en", str(directory)) == ()


# --- Packaging -------------------------------------------------------------


def test_thematic_lists_are_not_bundled_in_the_deb() -> None:
    """The .deb ships only the base lists; thematic ones are downloaded."""
    script = (REPO_ROOT / "scripts" / "build_deb.sh").read_text(encoding="utf-8")
    # The build copies the base ``*-50k.txt`` files, not the thematic folders.
    assert "*-50k.txt" in script
    for cat in CATEGORIES:
        assert f"dictionaries/{cat.slug}/" not in script


def test_base_lists_are_in_the_built_deb() -> None:
    """When a .deb exists, every base list must be inside it."""
    deb = REPO_ROOT / "dist" / "linguafix_0.2.8_all.deb"
    if not deb.is_file():
        pytest.skip("no built .deb to inspect")
    listing = subprocess.run(
        ["dpkg-deb", "-c", str(deb)],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    for language in ("ru", "en", "uk", "de", "fr"):
        assert f"{language}-50k.txt" in listing
    # Thematic folders must not be shipped.
    assert "dictionaries/it/" not in listing


def test_release_workflow_attaches_category_archives() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "linguafix-dict-" in workflow
    assert "dist/dict-archives" in workflow
