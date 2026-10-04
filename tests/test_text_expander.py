"""Text expansion / snippets (Stage 7).

Snippets are opt-in and run before layout analysis, so a trigger is expanded
verbatim instead of being "corrected". A snippet never fires when the feature
is disabled or the trigger does not match exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.config import Config  # noqa: E402
from linguafix.converter import LayoutConverter  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector  # noqa: E402
from linguafix.text_expander import TextExpander  # noqa: E402

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

    def replace_text(self, backspace_count: int, new: str, layout: str) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True

    def describe(self) -> str:
        return "backend=fake"


_KEY_BY_CHAR = {char: (f"KEY_{char.upper()}", False) for char in "abcdefghijklmnopqrstuvwxyz"}
for _sym, _name in {" ": "KEY_SPACE", "!": "KEY_1", "@": "KEY_2", ".": "KEY_DOT"}.items():
    _KEY_BY_CHAR[_sym] = (_name, True)


def _press(daemon: LinguaFixDaemon, text: str) -> None:
    for char in text:
        name, shift = _KEY_BY_CHAR[char]
        daemon._shift = shift
        daemon._handle_event(FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), 1))
        daemon._handle_event(FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), 0))


def _make_daemon(**kwargs: object) -> LinguaFixDaemon:
    options: dict[str, object] = {"stop_words": [], "analysis_timeout": 0.8}
    options.update(kwargs)
    config = Config(**options)
    detector = LanguageDetector(
        converter=LayoutConverter(),
        stop_words=config.stop_words,
        min_word_length=config.min_word_length,
        confidence_threshold=config.confidence_threshold,
    )
    return LinguaFixDaemon(
        config,
        detector=detector,
        switcher=FakeSwitcher("us"),
        injector=FakeInjector(),
    )


def _fixes(daemon: LinguaFixDaemon) -> list[tuple[int, str, str]]:
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    return injector.replacements


# --- TextExpander unit tests -----------------------------------------------------


def test_expander_matches_exact_trigger() -> None:
    expander = TextExpander({"!!email": "user@example.com"})
    assert expander.check("!!email") == ("!!email", "user@example.com")


def test_expander_ignores_unknown_and_partial_triggers() -> None:
    expander = TextExpander({"!!email": "user@example.com"})
    assert expander.check("!!emai") is None
    assert expander.check("email") is None


def test_expander_resolves_date_placeholder() -> None:
    expander = TextExpander({"!!date": "{date}"})
    result = expander.check("!!date")
    assert result is not None
    trigger, expansion = result
    assert trigger == "!!date"
    assert len(expansion) == 10 and expansion[4] == "-" and expansion[7] == "-"


def test_expander_load_reads_snippets_table(tmp_path: Path) -> None:
    path = tmp_path / "snippets.toml"
    path.write_text('[snippets]\n"!!shrug" = "x"\n', encoding="utf-8")
    expander = TextExpander()
    expander.load(path)
    assert expander.snippets == {"!!shrug": "x"}


def test_expander_load_missing_file_keeps_current(tmp_path: Path) -> None:
    expander = TextExpander({"!!a": "b"})
    expander.load(tmp_path / "absent.toml")
    assert expander.snippets == {"!!a": "b"}


def test_expander_load_malformed_file_keeps_current(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("this is = = not toml", encoding="utf-8")
    expander = TextExpander({"!!a": "b"})
    expander.load(path)
    assert expander.snippets == {"!!a": "b"}


def test_expander_load_without_table_yields_empty(tmp_path: Path) -> None:
    path = tmp_path / "empty.toml"
    path.write_text("other = 1\n", encoding="utf-8")
    expander = TextExpander({"!!a": "b"})
    expander.load(path)
    assert expander.snippets == {}


# --- daemon integration ----------------------------------------------------------


def test_snippet_expands_on_boundary(tmp_path: Path) -> None:
    path = tmp_path / "snippets.toml"
    path.write_text('[snippets]\n"!!email" = "user@example.com"\n', encoding="utf-8")
    daemon = _make_daemon(text_expander_enabled=True, text_expander_snippets_path=str(path))
    _press(daemon, "!!email")
    daemon._process_buffer(force=True)
    assert _fixes(daemon) == [(7, "user@example.com", "us")]


def test_snippet_disabled_does_nothing(tmp_path: Path) -> None:
    path = tmp_path / "snippets.toml"
    path.write_text('[snippets]\n"!!email" = "user@example.com"\n', encoding="utf-8")
    daemon = _make_daemon(text_expander_enabled=False, text_expander_snippets_path=str(path))
    _press(daemon, "!!email")
    daemon._process_buffer(force=True)
    assert _fixes(daemon) == []


def test_snippet_wins_over_layout_fix(tmp_path: Path) -> None:
    """A trigger that also looks like the wrong layout is expanded, not converted."""
    path = tmp_path / "snippets.toml"
    path.write_text('[snippets]\n"ghbdtn" = "hello there"\n', encoding="utf-8")
    daemon = _make_daemon(text_expander_enabled=True, text_expander_snippets_path=str(path))
    _press(daemon, "ghbdtn")
    daemon._process_buffer(force=True)
    assert _fixes(daemon) == [(6, "hello there", "us")]


def test_snippet_reload_picks_up_new_file(tmp_path: Path) -> None:
    path = tmp_path / "snippets.toml"
    daemon = _make_daemon(text_expander_enabled=True, text_expander_snippets_path=str(path))
    assert daemon._expander.snippets == {}
    path.write_text('[snippets]\n"!!x" = "y"\n', encoding="utf-8")
    daemon._load_snippets(daemon.config)
    assert daemon._expander.snippets == {"!!x": "y"}
