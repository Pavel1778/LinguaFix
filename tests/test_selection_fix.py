"""Selection fix (Stage 8).

The hotkey converts the layout of the text the user already selected: copy,
convert, paste, restore the clipboard. Every external step is best-effort, so
these tests use a fake injector and monkeypatched clipboard access.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

evdev = pytest.importorskip("evdev")

from linguafix import selection_fix as selection_fix_module  # noqa: E402
from linguafix.config import Config  # noqa: E402
from linguafix.converter import LayoutConverter  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector  # noqa: E402
from linguafix.injector import TextInjector  # noqa: E402
from linguafix.selection_fix import SelectionFix  # noqa: E402


@dataclass
class FakeSwitcher:
    current: str = "us"

    def get_current_layout(self, *, force: bool = False) -> str:
        return self.current

    def switch_to(self, layout: str) -> bool:
        self.current = layout
        return True

    def describe(self) -> str:
        return "backend=fake"


@dataclass
class FakeInjector:
    combos: list[list[str]] = field(default_factory=list)
    combo_result: bool = True

    def tap_combo(self, key_names: list[str]) -> bool:
        self.combos.append(list(key_names))
        return self.combo_result

    def replace_text(self, backspace_count: int, new: str, layout: str) -> bool:
        return True

    def describe(self) -> str:
        return "backend=fake"


def _make_selection_fix(
    injector: FakeInjector | None = None, session_type: str = "wayland"
) -> SelectionFix:
    return SelectionFix(
        converter=LayoutConverter(),
        injector=injector,
        session_type=session_type,
    )


def _patch_clipboard(
    fix: SelectionFix, monkeypatch: pytest.MonkeyPatch, text: str | None
) -> list[str]:
    """Patch clipboard read/write; return the list of written values."""
    written: list[str] = []
    monkeypatch.setattr(fix, "_read_clipboard", lambda: text)
    monkeypatch.setattr(fix, "_write_clipboard", lambda value: written.append(value) or True)
    return written


def test_selection_fix_converts_and_restores_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    injector = FakeInjector()
    fix = _make_selection_fix(injector)
    written = _patch_clipboard(fix, monkeypatch, "ghbdtn")
    monkeypatch.setattr(selection_fix_module.time, "sleep", lambda _s: None)
    assert fix.convert_selection() is True
    assert written == ["привет", "ghbdtn"]
    assert injector.combos == [["KEY_LEFTCTRL", "KEY_C"], ["KEY_LEFTCTRL", "KEY_V"]]


def test_selection_fix_without_injector_returns_false() -> None:
    fix = _make_selection_fix(None)
    assert fix.convert_selection() is False


def test_selection_fix_copy_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    injector = FakeInjector(combo_result=False)
    fix = _make_selection_fix(injector)
    monkeypatch.setattr(selection_fix_module.time, "sleep", lambda _s: None)
    assert fix.convert_selection() is False


def test_selection_fix_empty_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    injector = FakeInjector()
    fix = _make_selection_fix(injector)
    _patch_clipboard(fix, monkeypatch, "")
    monkeypatch.setattr(selection_fix_module.time, "sleep", lambda _s: None)
    assert fix.convert_selection() is False


def test_selection_fix_no_layout_change(monkeypatch: pytest.MonkeyPatch) -> None:
    injector = FakeInjector()
    fix = _make_selection_fix(injector)
    # "12345" is layout-invariant, so there is no layout change to make.
    written = _patch_clipboard(fix, monkeypatch, "12345")
    monkeypatch.setattr(selection_fix_module.time, "sleep", lambda _s: None)
    assert fix.convert_selection() is False
    assert written == []


def test_selection_fix_write_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    injector = FakeInjector()
    fix = _make_selection_fix(injector)
    monkeypatch.setattr(fix, "_read_clipboard", lambda: "ghbdtn")
    monkeypatch.setattr(fix, "_write_clipboard", lambda _value: False)
    monkeypatch.setattr(selection_fix_module.time, "sleep", lambda _s: None)
    assert fix.convert_selection() is False


def test_selection_fix_paste_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    injector = FakeInjector()
    fix = _make_selection_fix(injector)
    _patch_clipboard(fix, monkeypatch, "ghbdtn")
    calls = {"n": 0}

    def tap_combo(key_names: list[str]) -> bool:
        calls["n"] += 1
        return calls["n"] == 1  # copy ok, paste fails

    monkeypatch.setattr(injector, "tap_combo", tap_combo)
    monkeypatch.setattr(selection_fix_module.time, "sleep", lambda _s: None)
    assert fix.convert_selection() is False


def test_selection_fix_command_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    fix = _make_selection_fix(session_type="wayland")
    monkeypatch.setattr(selection_fix_module, "_which", lambda name: f"/usr/bin/{name}")
    assert fix._read_command() == ["wl-paste", "--no-newline"]
    assert fix._write_command() == ["wl-copy"]
    fix_x11 = _make_selection_fix(session_type="x11")
    assert fix_x11._read_command() == ["xclip", "-selection", "clipboard", "-o"]
    assert fix_x11._write_command() == ["xclip", "-selection", "clipboard"]


def test_selection_fix_no_clipboard_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    fix = _make_selection_fix(session_type="x11")
    monkeypatch.setattr(selection_fix_module, "_which", lambda _name: None)
    assert fix._read_command() is None
    assert fix._write_command() is None
    assert fix._read_clipboard() is None
    assert fix._write_clipboard("x") is False


# --- injector tap_combo ----------------------------------------------------------


class _RecordingDevice:
    def __init__(self) -> None:
        self.events: list[tuple[int, int, int]] = []

    def write(self, ev_type: int, code: int, value: int) -> None:
        self.events.append((int(ev_type), int(code), int(value)))

    def syn(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_tap_combo_writes_chord(monkeypatch: pytest.MonkeyPatch) -> None:
    device = _RecordingDevice()
    injector = TextInjector(converter=LayoutConverter(), backend="uinput")
    injector._backend = "uinput"
    monkeypatch.setattr(TextInjector, "_open_uinput", staticmethod(lambda *_a: device))
    assert injector.tap_combo(["KEY_LEFTCTRL", "KEY_C"]) is True
    # Ctrl down, C down, C up, Ctrl up.
    codes = [code for _t, code, _v in device.events]
    assert codes == [
        int(evdev.ecodes.KEY_LEFTCTRL),
        int(evdev.ecodes.KEY_C),
        int(evdev.ecodes.KEY_C),
        int(evdev.ecodes.KEY_LEFTCTRL),
    ]


def test_tap_combo_unknown_key_returns_false() -> None:
    injector = TextInjector(converter=LayoutConverter(), backend="uinput")
    injector._backend = "uinput"
    assert injector.tap_combo(["KEY_NOT_A_KEY"]) is False


def test_tap_combo_non_uinput_backend_returns_false() -> None:
    injector = TextInjector(converter=LayoutConverter(), backend="auto")
    injector._backend = "none"
    assert injector.tap_combo(["KEY_LEFTCTRL", "KEY_C"]) is False


# --- daemon wiring ---------------------------------------------------------------


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
        config, detector=detector, switcher=FakeSwitcher("us"), injector=FakeInjector()
    )


def test_selection_fix_hotkey_is_registered() -> None:
    daemon = _make_daemon()
    daemon._held_modifiers = {"ctrl", "shift"}
    assert daemon._match_hotkey(int(evdev.ecodes.KEY_L)) == "selection_fix"


def test_selection_fix_hotkey_runs_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = _make_daemon()
    called: list[bool] = []
    monkeypatch.setattr(daemon.selection_fix, "convert_selection", lambda: called.append(True))
    daemon._run_hotkey("selection_fix")
    assert called == [True]


def test_selection_fix_disabled_skips_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = _make_daemon(selection_fix_enabled=False)
    called: list[bool] = []
    monkeypatch.setattr(daemon.selection_fix, "convert_selection", lambda: called.append(True))
    daemon._run_hotkey("selection_fix")
    assert called == []


def test_selection_fix_hotkey_reload() -> None:
    daemon = _make_daemon()
    daemon.config.selection_fix_hotkey = "CTRL+ALT+L"
    daemon._hotkeys["selection_fix"] = daemon._parse_hotkey("CTRL+ALT+L")
    daemon._held_modifiers = {"ctrl", "alt"}
    assert daemon._match_hotkey(int(evdev.ecodes.KEY_L)) == "selection_fix"
