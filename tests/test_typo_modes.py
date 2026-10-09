"""Independent T9 / punctuation modes (v0.2.8.2).

The user reported "T9-спам в manual": with ``typo_correction`` on, manual mode
kept auto-rewriting words every few seconds. The fix makes the T9 mode
independent of the global layout ``mode`` and gates the automatic pass on it:

* ``off`` -- T9 never runs;
* ``manual`` -- T9 runs only on the explicit hotkey (``CTRL+SHIFT+F``);
* ``auto`` / ``hybrid`` -- T9 runs on a word boundary.

These tests pin the mode contract and the precision guards that keep correct
words from being rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

evdev = pytest.importorskip("evdev")

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
        # A permissive stub: these tests exercise mode gating, not backend
        # typability (the uinput limits are covered in test_punctuation.py).
        return True

    def replace_text(
        self, backspace_count: int, new: str, layout: str, boundary_char: str = ""
    ) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True

    def describe(self) -> str:
        return "backend=fake"


_KEY_BY_CHAR: dict[str, str] = {" ": "KEY_SPACE"}
for _letter in "abcdefghijklmnopqrstuvwxyz":
    _KEY_BY_CHAR[_letter] = f"KEY_{_letter.upper()}"


def _press(daemon: LinguaFixDaemon, text: str) -> None:
    for char in text:
        name = _KEY_BY_CHAR[char]
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


def _injector(daemon: LinguaFixDaemon) -> FakeInjector:
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    return injector


def _feed(daemon: LinguaFixDaemon, word: str, layout: str, boundary: str = " ") -> None:
    """Seed a word (including Cyrillic) and flush it as if a boundary was hit."""
    switcher = daemon.switcher
    assert isinstance(switcher, FakeSwitcher)
    switcher.current = layout
    daemon.buffer = word
    daemon._scancodes = [0] * len(word)
    daemon._process_buffer(boundary=True, boundary_char=boundary)


# --- mode gating ------------------------------------------------------------


def test_typo_mode_off_disables_t9() -> None:
    """``typo_mode = "off"`` must never correct, even in auto layout mode."""
    daemon = _make_daemon(typo_mode="off")
    _press(daemon, "langauge")
    _press(daemon, " ")
    assert _injector(daemon).replacements == []


def test_typo_mode_manual_only_hotkey() -> None:
    """``typo_mode = "manual"`` stays quiet automatically, fires on the hotkey."""
    daemon = _make_daemon(typo_mode="manual")
    _press(daemon, "langauge")
    _press(daemon, " ")
    assert _injector(daemon).replacements == []
    daemon._force_typo_fix()
    assert _injector(daemon).replacements == [(8, "language", "us")]


def test_typo_mode_auto_triggers_on_boundary() -> None:
    """``typo_mode = "auto"`` corrects on the Space boundary."""
    daemon = _make_daemon(typo_mode="auto")
    _press(daemon, "langauge")
    _press(daemon, " ")
    assert _injector(daemon).replacements == [(9, "language ", "us")]


def test_typo_mode_independent_of_layout_mode() -> None:
    """Manual layout mode with automatic T9: the two modes do not interfere."""
    daemon = _make_daemon(mode="manual", typo_mode="auto")
    _press(daemon, "langauge")
    _press(daemon, " ")
    assert _injector(daemon).replacements == [(9, "language ", "us")]


def test_punctuation_mode_off_disables() -> None:
    daemon = _make_daemon(punctuation_mode="off")
    assert daemon._punctuation_correction("текст--", "ru") is None


def test_punctuation_mode_manual_only_hotkey() -> None:
    daemon = _make_daemon(punctuation_mode="manual")
    assert daemon._punctuation_correction("текст--", "ru") is None
    assert daemon._punctuation_correction("текст--", "ru", force=True) == "текст\u2014"


def test_punctuation_mode_auto_runs() -> None:
    daemon = _make_daemon(punctuation_mode="auto")
    assert daemon._punctuation_correction("текст--", "ru") == "текст\u2014"


# --- no spam / precision ----------------------------------------------------


def test_typo_no_spam_in_manual() -> None:
    """Twenty correct Russian words must not produce a single typo fix.

    This is the regression for the reported "T9-спам в manual": every word is
    already in the corpus, so the unknown-word guard alone must reject them.
    """
    words = [
        "привет",
        "человек",
        "программа",
        "работа",
        "время",
        "дело",
        "жизнь",
        "день",
        "рука",
        "раз",
        "город",
        "место",
        "слово",
        "вопрос",
        "книга",
        "стол",
        "окно",
        "дорога",
        "земля",
        "вода",
    ]
    daemon = _make_daemon(typo_mode="auto", mode="manual")
    for word in words:
        _feed(daemon, word, "ru")
    assert _injector(daemon).replacements == []


def test_typo_only_for_unknown_words() -> None:
    """A real word is never rewritten; a typo is (mode permitting)."""
    daemon = _make_daemon(typo_mode="auto")
    from linguafix.typo import TypoCorrector

    vocab = daemon.detector.ordered_vocabulary("ru")
    corrector = TypoCorrector(vocab, min_length=4)
    for correct in ("привет", "человек", "программа"):
        assert corrector.suggest(correct) in (None, correct)
    assert corrector.suggest("прогрмма") == "программа"


def test_typo_does_not_touch_number_url_email() -> None:
    """Digits, e-mails and URLs are never sent to T9."""
    daemon = _make_daemon(typo_mode="auto")
    for token, layout in (("3.14", "ru"), ("test@example.com", "ru"), ("github.com", "ru")):
        assert daemon._typo_correction(token, layout) is None
