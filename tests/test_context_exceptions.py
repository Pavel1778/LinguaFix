"""Context analysis, per-app exceptions and user dictionaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

evdev = pytest.importorskip("evdev")

from linguafix import dictionary  # noqa: E402
from linguafix.config import Config  # noqa: E402
from linguafix.converter import LayoutConverter  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector  # noqa: E402

EV_KEY = evdev.ecodes.EV_KEY


@dataclass
class FakeEvent:
    type: int
    code: int
    value: int


@dataclass
class FakeSwitcher:
    current: str = "us"
    switches: list[str] = field(default_factory=list)

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        self.switches.append(layout)
        return True

    def describe(self) -> str:
        return "backend=fake"


@dataclass
class FakeInjector:
    replacements: list[tuple[int, str, str]] = field(default_factory=list)

    def can_type(self, char: str, layout: str) -> bool:
        # Mirror the uinput backend: only Space is layout-invariant and typed.
        return char == " "

    def replace_text(
        self, backspace_count: int, new: str, layout: str, boundary_char: str = ""
    ) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True

    def describe(self) -> str:
        return "backend=fake"


_KEY_BY_CHAR = {" ": ("KEY_SPACE", False)}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    _KEY_BY_CHAR[_letter] = (f"KEY_{_letter.upper()}", False)


def make_event(name: str, value: int = 1) -> FakeEvent:
    return FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), value)


def press(daemon: LinguaFixDaemon, text: str) -> None:
    for char in text:
        name, _shift = _KEY_BY_CHAR[char]
        daemon._handle_event(make_event(name, 1))
        daemon._handle_event(make_event(name, 0))


def tap(daemon: LinguaFixDaemon, name: str) -> None:
    daemon._handle_event(make_event(name, 1))
    daemon._handle_event(make_event(name, 0))


def make_daemon(monkeypatch: pytest.MonkeyPatch, **kwargs: object) -> LinguaFixDaemon:
    options: dict[str, object] = {"stop_words": ["password"]}
    options.update(kwargs)
    config = Config(**options)
    detector = LanguageDetector(
        converter=LayoutConverter(),
        stop_words=config.stop_words,
        min_word_length=config.min_word_length,
        confidence_threshold=config.confidence_threshold,
    )
    if "dictionary_custom_path" in kwargs:
        monkeypatch.setattr(
            "linguafix.daemon.load_user_dictionary",
            lambda path: dictionary.load_user_dictionary(path),
        )
    return LinguaFixDaemon(
        config,
        detector=detector,
        switcher=FakeSwitcher(),
        injector=FakeInjector(),
    )


def _injector(daemon: LinguaFixDaemon) -> FakeInjector:
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    return injector


# --- context analysis -------------------------------------------------------


def test_context_analysis_can_flip_a_borderline_word() -> None:
    converter = LayoutConverter()
    without = LanguageDetector(converter, confidence_threshold=0.3)
    without.context_weight = 0.0
    with_context = LanguageDetector(converter, confidence_threshold=0.3)
    with_context.context_weight = 0.3

    # A borderline 3-letter buffer the plain model leaves alone; a clear Russian
    # neighbour tips it over the line.
    assert without.target_layout("xno", "us", "привет") is None
    assert with_context.target_layout("xno", "us", "привет") == "ru"


def test_context_does_not_change_the_current_layout() -> None:
    converter = LayoutConverter()
    detector = LanguageDetector(converter)
    detector.context_weight = 0.3
    # "привет" is already Russian; a Russian neighbour must not "fix" it.
    assert detector.target_layout("привет", "ru", "привет") is None


def test_daemon_uses_neighbour_as_context(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(monkeypatch, context_analysis=True, context_weight=0.6)
    daemon._last_word = "привет"
    injector = _injector(daemon)
    press(daemon, "xno")
    tap(daemon, "KEY_SPACE")
    assert injector.replacements and injector.replacements[0][2] == "ru"


def test_context_disabled_ignores_neighbour(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(monkeypatch, context_analysis=False)
    daemon._last_word = "привет"
    press(daemon, "xno")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == []


# --- per-app exceptions -----------------------------------------------------


def test_app_exception_skips_even_in_auto_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("linguafix.daemon.get_active_app", lambda: "gnome-terminal")
    daemon = make_daemon(monkeypatch, mode="auto", exceptions_apps=["gnome-terminal"])
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == []


def test_unlisted_app_still_fixes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("linguafix.daemon.get_active_app", lambda: "firefox")
    daemon = make_daemon(monkeypatch, mode="auto", exceptions_apps=["gnome-terminal"])
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == [(7, "привет ", "ru")]


def test_force_in_manual_list_applies_to_manual_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("linguafix.daemon.get_active_app", lambda: "kitty")
    daemon = make_daemon(monkeypatch, mode="manual", exceptions_force_in_manual=["kitty"])
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == [(7, "привет ", "ru")]


# --- skip rules -------------------------------------------------------------


def test_ignore_all_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(monkeypatch, ignore_all_caps=True)
    press(daemon, "ghbdtn")
    # Uppercase the buffer directly; the daemon derives it from scancodes.
    daemon.buffer = "GHBDTN"
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == []


def test_ignore_with_digits(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(monkeypatch, ignore_with_digits=True)
    daemon.buffer = "ghbdtn1"
    daemon._scancodes = [1, 2, 3, 4, 5, 6, 7]
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == []


def test_email_url_skipped_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(monkeypatch, ignore_emails_urls=True)
    daemon.buffer = "test@example.com"
    daemon._scancodes = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == []


def test_custom_skip_regex(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = make_daemon(monkeypatch, custom_skip_regex=r"^ghb")
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == []


def test_invalid_custom_skip_regex_rejected_by_config() -> None:
    with pytest.raises(ValueError):
        Config(custom_skip_regex=r"([unclosed")


def test_invalid_custom_skip_regex_is_ignored_by_daemon() -> None:
    from linguafix.daemon import _compile_skip_regex

    assert _compile_skip_regex(r"([unclosed") is None


# --- user dictionary --------------------------------------------------------


def test_user_dictionary_path_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert dictionary.user_dictionary_path() == tmp_path / "linguafix" / "dictionary.txt"


def test_user_dictionary_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    dictionary.add_user_word("Кот", str(path))
    dictionary.add_user_word("кит", str(path))
    dictionary.add_user_word("Кот", str(path))  # duplicate ignored
    assert dictionary.load_user_dictionary(str(path)) == ["Кот", "кит"]


def test_user_dictionary_ignores_comments_and_blanks(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    path.write_text("# comment\n\nкот\n  кит  \n", encoding="utf-8")
    assert dictionary.load_user_dictionary(str(path)) == ["кот", "кит"]


def test_user_word_stops_a_fix(tmp_path: Path) -> None:
    path = tmp_path / "dictionary.txt"
    # "ghbdtn" is the physical keys of "привет"; teaching the daemon that the
    # typed form is legitimate must stop the correction.
    dictionary.add_user_word("ghbdtn", str(path))
    converter = LayoutConverter()
    detector = LanguageDetector(converter, user_words=dictionary.load_user_dictionary(str(path)))
    assert detector.target_layout("ghbdtn", "us") is None


def test_daemon_loads_user_dictionary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "dictionary.txt"
    dictionary.add_user_word("ghbdtn", str(path))
    daemon = make_daemon(monkeypatch, dictionary_custom_path=str(path))
    press(daemon, "ghbdtn")
    tap(daemon, "KEY_SPACE")
    assert _injector(daemon).replacements == []


def test_dictionary_size_limits_vocabulary() -> None:
    converter = LayoutConverter()
    detector = LanguageDetector(converter, dictionary_size=5)
    assert all(len(vocab) <= 5 for vocab in detector._vocabularies.values())


def test_detector_setters_reload() -> None:
    detector = LanguageDetector(LayoutConverter())
    detector.set_dictionary_size(1000)
    detector.set_context_weight(0.5)
    detector.set_user_words(["кот"])
    assert detector.context_weight == 0.5
    assert detector.user_words == ["кот"]
    # A taught word is always left alone, regardless of layout.
    assert detector.target_layout("кот", "ru") is None
    assert detector.target_layout("кот", "us") is None
