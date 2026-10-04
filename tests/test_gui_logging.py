"""The GUI entry point must configure logging before it starts.

Without this the GUI's ``logger`` calls (a failed start/stop, a missing daemon)
vanish. These tests do not need a display: the GTK stack is stubbed out.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from linguafix import gui, logging_setup


def test_gui_main_configures_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(logging_setup, "setup_logging", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(gui, "gtk_available", lambda: True)

    fake_app = types.ModuleType("linguafix.gui.app")

    class _FakeApp:
        def run(self, argv: object) -> int:
            return 0

    fake_app.LinguaFixApplication = _FakeApp
    monkeypatch.setitem(sys.modules, "linguafix.gui.app", fake_app)

    assert gui.main([]) == 0
    assert calls, "setup_logging was not called"
    assert calls[0]["file_name"] == logging_setup.GUI_LOG_FILE_NAME


def test_gui_log_file_is_separate_from_daemon(tmp_path: Path) -> None:
    path = logging_setup.setup_logging(
        "INFO", log_dir=tmp_path, file_name=logging_setup.GUI_LOG_FILE_NAME
    )
    assert path.name == "gui.log"
    assert path.name != logging_setup.LOG_FILE_NAME
    assert path.exists()
