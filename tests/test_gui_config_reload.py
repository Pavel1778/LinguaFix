"""Tests for config propagation from the GUI to a running daemon.

A daemon keeps its own copy of the configuration. Writing ``config.toml`` alone
is therefore invisible to it, so :meth:`GuiState.save` must ask a live daemon to
reload. Without that, a switch flipped in the GUI (typo correction, a trigger, a
guard) is saved but the feature silently does nothing -- the "T9 is on but does
not correct" bug.

These tests import ``linguafix.gui.state``, which has no GTK dependency, so they
run everywhere (no display required).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from linguafix.config import Config, load_config
from linguafix.gui import state as gui_state
from linguafix.gui.state import GuiState


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect XDG directories into a temporary tree."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return tmp_path


def test_save_pushes_reload_to_running_daemon(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reloads: list[bool] = []
    monkeypatch.setattr(gui_state, "daemon_is_running", lambda: True)
    monkeypatch.setattr(gui_state, "daemon_reload_config", lambda: reloads.append(True) or True)

    state = GuiState(config=Config(typo_correction=True))
    state.save()

    assert reloads == [True]
    # The file is written too, so a later restart picks the setting up.
    assert load_config().typo_correction is True


def test_save_does_not_reload_when_daemon_stopped(
    isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reloads: list[bool] = []
    monkeypatch.setattr(gui_state, "daemon_is_running", lambda: False)
    monkeypatch.setattr(gui_state, "daemon_reload_config", lambda: reloads.append(True) or True)

    GuiState(config=Config(typo_correction=True)).save()

    assert reloads == []


def test_set_mode_reloads_once(isolated_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``set_mode`` relies on ``save`` and must not double-reload."""
    reloads: list[bool] = []
    monkeypatch.setattr(gui_state, "daemon_is_running", lambda: True)
    monkeypatch.setattr(gui_state, "daemon_reload_config", lambda: reloads.append(True) or True)

    state = GuiState(config=Config())
    state.set_mode("manual")

    assert reloads == [True]
    assert load_config().mode == "manual"
