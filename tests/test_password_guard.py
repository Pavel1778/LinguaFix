"""AT-SPI password-field guard (Stage 6).

A focused password entry must never be rewritten. AT-SPI reports the focused
element's role; a positive ``"password"`` verdict skips the fix, while an
undetermined role (``None``) leaves normal behaviour untouched so a missing
accessibility bus does not disable the daemon.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

evdev = pytest.importorskip("evdev")

from linguafix import app_focus  # noqa: E402
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

    def replace_text(self, backspace_count: int, new: str, layout: str) -> bool:
        self.replacements.append((backspace_count, new, layout))
        return True

    def describe(self) -> str:
        return "backend=fake"


_KEY_BY_CHAR = {char: (f"KEY_{char.upper()}", False) for char in "abcdefghijklmnopqrstuvwxyz"}
_KEY_BY_CHAR[" "] = ("KEY_SPACE", False)


def _press(daemon: LinguaFixDaemon, text: str) -> None:
    for char in text:
        name, _shift = _KEY_BY_CHAR[char]
        daemon._handle_event(FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), 1))
        daemon._handle_event(FakeEvent(EV_KEY, int(getattr(evdev.ecodes, name)), 0))


def _make_daemon(role: str | None, *, password_guard: bool = True) -> LinguaFixDaemon:
    config = Config(stop_words=[], analysis_timeout=0.8, password_guard=password_guard)
    detector = LanguageDetector(
        converter=LayoutConverter(),
        stop_words=config.stop_words,
        min_word_length=config.min_word_length,
        confidence_threshold=config.confidence_threshold,
    )
    daemon = LinguaFixDaemon(
        config,
        detector=detector,
        switcher=FakeSwitcher("us"),
        injector=FakeInjector(),
    )
    daemon._focused_role_probe = lambda: role
    return daemon


def _fixes(daemon: LinguaFixDaemon) -> list[tuple[int, str, str]]:
    injector = daemon.injector
    assert isinstance(injector, FakeInjector)
    return injector.replacements


def test_password_field_skips_the_fix() -> None:
    daemon = _make_daemon("password")
    _press(daemon, "ghbdtn")
    daemon._process_buffer(force=True)
    assert _fixes(daemon) == []


def test_text_field_is_corrected() -> None:
    daemon = _make_daemon("text")
    _press(daemon, "ghbdtn")
    daemon._process_buffer(force=True)
    assert _fixes(daemon) == [(6, "привет", "ru")]


def test_undetermined_role_falls_back_to_correction() -> None:
    daemon = _make_daemon(None)
    _press(daemon, "ghbdtn")
    daemon._process_buffer(force=True)
    assert _fixes(daemon) == [(6, "привет", "ru")]


def test_probe_failure_falls_back_to_correction() -> None:
    daemon = _make_daemon(None)

    def boom() -> str | None:
        raise RuntimeError("no accessibility bus")

    daemon._focused_role_probe = boom
    _press(daemon, "ghbdtn")
    daemon._process_buffer(force=True)
    assert _fixes(daemon) == [(6, "привет", "ru")]


def test_guard_can_be_disabled() -> None:
    daemon = _make_daemon("password", password_guard=False)
    _press(daemon, "ghbdtn")
    daemon._process_buffer(force=True)
    assert _fixes(daemon) == [(6, "привет", "ru")]


def test_get_focused_role_returns_none_without_atspi(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no accessibility stack the probe degrades to ``None``, not an error."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "gi":
            raise ImportError("no gi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert app_focus.get_focused_role() is None
    assert app_focus.is_password_field() is False


def test_is_password_field_true_only_for_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_focus, "_ROLE_PROBES", (lambda: "password",))
    assert app_focus.is_password_field() is True
    monkeypatch.setattr(app_focus, "_ROLE_PROBES", (lambda: "text",))
    assert app_focus.is_password_field() is False


# --- AT-SPI traversal helpers, exercised with fakes ------------------------------


class _State:
    ACTIVE = "active"
    FOCUSED = "focused"


class _Role:
    PASSWORD_TEXT = "password-text"


class _FakeAtspi:
    StateType = _State
    Role = _Role


class _StateSet:
    def __init__(self, states: set[str]) -> None:
        self._states = states

    def contains(self, state: object) -> bool:
        return state in self._states


class _Node:
    """Minimal stand-in for an AT-SPI accessible node."""

    def __init__(
        self,
        *,
        role: object = None,
        states: set[str] | None = None,
        children: list[object] | None = None,
        fail_state: bool = False,
        fail_count: bool = False,
        fail_child: bool = False,
    ) -> None:
        self._role = role
        self._states = states or set()
        self._children = children or []
        self._fail_state = fail_state
        self._fail_count = fail_count
        self._fail_child = fail_child

    def get_state_set(self) -> _StateSet:
        if self._fail_state:
            raise RuntimeError("boom")
        return _StateSet(self._states)

    def get_child_count(self) -> int:
        if self._fail_count:
            raise RuntimeError("boom")
        return len(self._children)

    def get_child_at_index(self, index: int) -> object:
        if self._fail_child:
            raise RuntimeError("boom")
        return self._children[index]

    def get_role(self) -> object:
        return self._role


def test_atspi_active_app_finds_active_child() -> None:
    active = _Node(states={_State.ACTIVE})
    desktop = _Node(children=[_Node(), active, None])
    assert app_focus._atspi_active_app(desktop, _FakeAtspi) is active


def test_atspi_active_app_returns_none_without_active() -> None:
    desktop = _Node(children=[_Node(), _Node()])
    assert app_focus._atspi_active_app(desktop, _FakeAtspi) is None


def test_atspi_focused_descendant_finds_nested_focus() -> None:
    focused = _Node(states={_State.FOCUSED})
    deep = _Node(children=[_Node(children=[focused])])
    root = _Node(children=[deep])
    assert app_focus._atspi_focused_descendant(root, _FakeAtspi) is focused


def test_atspi_focused_descendant_none_when_nothing_focused() -> None:
    root = _Node(children=[_Node(children=[_Node()])])
    assert app_focus._atspi_focused_descendant(root, _FakeAtspi) is None


def test_atspi_focused_descendant_depth_guard() -> None:
    node = _Node()
    for _ in range(40):
        node = _Node(children=[node])
    assert app_focus._atspi_focused_descendant(node, _FakeAtspi) is None


def test_atspi_focused_descendant_tolerates_failures() -> None:
    assert app_focus._atspi_focused_descendant(_Node(fail_state=True), _FakeAtspi) is None
    assert app_focus._atspi_focused_descendant(_Node(fail_count=True), _FakeAtspi) is None
    root = _Node(children=[_Node()], fail_child=True)
    assert app_focus._atspi_focused_descendant(root, _FakeAtspi) is None


def _install_fake_atspi(monkeypatch: pytest.MonkeyPatch, desktop: _Node) -> None:
    import sys
    import types

    fake_gi = types.ModuleType("gi")
    fake_gi.require_version = lambda *_a, **_k: None
    fake_repo = types.ModuleType("gi.repository")

    class _Atspi:
        StateType = _State
        Role = _Role

        @staticmethod
        def get_desktop(_index: int) -> _Node:
            return desktop

    fake_repo.Atspi = _Atspi
    fake_gi.repository = fake_repo
    monkeypatch.setitem(sys.modules, "gi", fake_gi)
    monkeypatch.setitem(sys.modules, "gi.repository", fake_repo)


def test_atspi_focused_role_detects_password(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _Node(role=_Role.PASSWORD_TEXT, states={_State.FOCUSED})
    app = _Node(states={_State.ACTIVE}, children=[entry])
    _install_fake_atspi(monkeypatch, _Node(children=[app]))
    assert app_focus._atspi_focused_role() == "password"


def test_atspi_focused_role_detects_text(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = _Node(role="entry", states={_State.FOCUSED})
    app = _Node(states={_State.ACTIVE}, children=[entry])
    _install_fake_atspi(monkeypatch, _Node(children=[app]))
    assert app_focus._atspi_focused_role() == "text"


def test_atspi_focused_role_none_without_focus(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _Node(states={_State.ACTIVE}, children=[_Node()])
    _install_fake_atspi(monkeypatch, _Node(children=[app]))
    assert app_focus._atspi_focused_role() is None


def test_atspi_focused_role_none_without_active_app(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_atspi(monkeypatch, _Node(children=[_Node()]))
    assert app_focus._atspi_focused_role() is None
