"""Per-app default layout (Stage 9).

A preferred layout per application, applied when the focused application
changes. The mapping is user-owned; nothing is learned from typed text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

evdev = pytest.importorskip("evdev")

from linguafix.app_layouts import POLL_INTERVAL, AppLayoutManager, normalise_app  # noqa: E402
from linguafix.config import Config  # noqa: E402
from linguafix.converter import LayoutConverter  # noqa: E402
from linguafix.daemon import LinguaFixDaemon  # noqa: E402
from linguafix.detector import LanguageDetector  # noqa: E402


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
    def replace_text(self, backspace_count: int, new: str, layout: str) -> bool:
        return True

    def describe(self) -> str:
        return "backend=fake"


class FakeProbe:
    def __init__(self, app: str | None = None) -> None:
        self.app = app
        self.calls = 0

    def __call__(self) -> str | None:
        self.calls += 1
        return self.app


def test_normalise_app() -> None:
    assert normalise_app("  Kitty ") == "kitty"


def test_manager_disabled_does_nothing() -> None:
    probe = FakeProbe("kitty")
    manager = AppLayoutManager({"kitty": "ru"}, lambda _layout: True, probe, enabled=False)
    assert manager.maybe_apply(10.0) is None
    assert probe.calls == 0


def test_manager_switches_on_focus_change() -> None:
    probe = FakeProbe("kitty")
    switched: list[str] = []
    manager = AppLayoutManager(
        {"kitty": "ru"}, lambda layout: switched.append(layout) or True, probe, True
    )
    assert manager.maybe_apply(10.0) == "ru"
    assert switched == ["ru"]


def test_manager_does_not_repeat_for_same_app() -> None:
    probe = FakeProbe("kitty")
    switched: list[str] = []
    manager = AppLayoutManager(
        {"kitty": "ru"}, lambda layout: switched.append(layout) or True, probe, True
    )
    manager.maybe_apply(10.0)
    manager.maybe_apply(10.0 + POLL_INTERVAL)
    assert switched == ["ru"]


def test_manager_throttles_probe() -> None:
    probe = FakeProbe("kitty")
    manager = AppLayoutManager({"kitty": "ru"}, lambda _layout: True, probe, True)
    manager.maybe_apply(10.0)
    manager.maybe_apply(10.0 + POLL_INTERVAL / 2)
    assert probe.calls == 1


def test_manager_unknown_app_does_not_switch() -> None:
    probe = FakeProbe("firefox")
    switched: list[str] = []
    manager = AppLayoutManager(
        {"kitty": "ru"}, lambda layout: switched.append(layout) or True, probe, True
    )
    assert manager.maybe_apply(10.0) is None
    assert switched == []


def test_manager_handles_probe_error() -> None:
    def boom() -> str | None:
        raise RuntimeError("no bus")

    manager = AppLayoutManager({"kitty": "ru"}, lambda _layout: True, boom, True)
    assert manager.maybe_apply(10.0) is None


def test_manager_no_app_returns_none() -> None:
    manager = AppLayoutManager({"kitty": "ru"}, lambda _layout: True, FakeProbe(None), True)
    assert manager.maybe_apply(10.0) is None


def test_manager_preferred_layout() -> None:
    manager = AppLayoutManager({"kitty": "ru"})
    assert manager.preferred_layout("Kitty") == "ru"
    assert manager.preferred_layout("firefox") is None
    assert manager.preferred_layout(None) is None


def test_manager_describe() -> None:
    assert AppLayoutManager().describe() == "no per-app layouts"
    assert AppLayoutManager({"kitty": "ru"}).describe() == "kitty->ru"


def test_manager_update_resets_current() -> None:
    probe = FakeProbe("kitty")
    switched: list[str] = []
    manager = AppLayoutManager(
        {"kitty": "ru"}, lambda layout: switched.append(layout) or True, probe, True
    )
    manager.maybe_apply(10.0)
    manager.update(
        {"kitty": "en"}, enabled=True, switch_layout=lambda layout: switched.append(layout) or True
    )
    manager.maybe_apply(10.0 + POLL_INTERVAL)
    assert switched == ["ru", "en"]


# --- daemon wiring ---------------------------------------------------------------


def _make_daemon(switcher: FakeSwitcher, **kwargs: object) -> LinguaFixDaemon:
    options: dict[str, object] = {"stop_words": [], "analysis_timeout": 0.8}
    options.update(kwargs)
    config = Config(**options)
    detector = LanguageDetector(
        converter=LayoutConverter(),
        stop_words=config.stop_words,
        min_word_length=config.min_word_length,
        confidence_threshold=config.confidence_threshold,
    )
    return LinguaFixDaemon(config, detector=detector, switcher=switcher, injector=FakeInjector())


def test_daemon_app_layout_manager_wired() -> None:
    switcher = FakeSwitcher()
    daemon = _make_daemon(switcher, app_layouts={"kitty": "ru"}, app_layout_switch=True)
    daemon.app_layout_manager._probe = FakeProbe("kitty")
    daemon.app_layout_manager._last_check = float("-inf")
    daemon.app_layout_manager.maybe_apply(10.0)
    assert switcher.switches == ["ru"]


def test_daemon_app_layout_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    switcher = FakeSwitcher()
    daemon = _make_daemon(switcher)
    assert daemon.app_layout_manager.layouts == {}
    updated = Config(app_layouts={"code": "us"}, app_layout_switch=True, stop_words=[])
    monkeypatch.setattr("linguafix.config.load_config", lambda *_a, **_k: updated)
    daemon.reload_config()
    assert daemon.app_layout_manager.layouts == {"code": "us"}
    assert daemon.app_layout_manager.enabled is True


def test_config_normalises_app_layouts() -> None:
    config = Config(app_layouts={"  Kitty ": "RU"}, app_layout_switch=1)
    assert config.app_layouts == {"kitty": "ru"}
    assert config.app_layout_switch is True


def test_config_app_layout_section_flattens() -> None:
    from linguafix.config import Config as C

    config = C.from_dict({"app_layouts": {"kitty": "ru"}, "app_layout_switch": True})
    assert config.app_layouts == {"kitty": "ru"}


def test_manager_switch_failure_returns_none() -> None:
    probe = FakeProbe("kitty")
    manager = AppLayoutManager({"kitty": "ru"}, lambda _l: False, probe, True)
    assert manager.maybe_apply(10.0) is None
