"""Packaging contract: the shipped unit, desktop entry and package data.

These tests guard the artefacts that a broken packaging change would silently
drop: the systemd user unit (a negative ``Nice`` once made the unit restart
forever), the CSS file the GUI needs at runtime, and the build script's own
invariants. They are pure file/config checks so they run in CI without a
graphical session or Docker.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from linguafix import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent
UNIT = REPO_ROOT / "data" / "linguafix.service"
UNIT_IN_PACKAGE = REPO_ROOT / "src" / "linguafix" / "data" / "linguafix.service"
DESKTOP = REPO_ROOT / "data" / "linguafix.desktop"
GUI_CSS = REPO_ROOT / "src" / "linguafix" / "gui" / "style.css"
BUILD_DEB = REPO_ROOT / "scripts" / "build_deb.sh"


# --- systemd user unit ------------------------------------------------------


def test_unit_files_are_identical() -> None:
    assert UNIT.read_text(encoding="utf-8") == UNIT_IN_PACKAGE.read_text(encoding="utf-8")


def test_unit_has_no_scheduling_directives() -> None:
    text = UNIT.read_text(encoding="utf-8")
    # A user unit has no CAP_SYS_NICE: a negative Nice or a real-time policy
    # makes systemd treat startup as fatal (exit 201) and the unit never runs.
    active = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any(line.startswith("Nice=") for line in active)
    assert not any(line.startswith("CPUSchedulingPolicy") for line in active)


def test_unit_restarts_and_runs_in_foreground() -> None:
    text = UNIT.read_text(encoding="utf-8")
    assert "Restart=always" in text
    assert "ExecStart=@BIN@ start --foreground" in text
    assert "WantedBy=default.target" in text


def test_desktop_entry_points_at_gui() -> None:
    text = DESKTOP.read_text(encoding="utf-8")
    assert "Exec=@BIN@ gui" in text
    assert "Icon=linguafix" in text
    assert "StartupWMClass=io.github.pavel1778.LinguaFix" in text


# --- package data -----------------------------------------------------------


def test_gui_css_exists_and_is_declared() -> None:
    assert GUI_CSS.is_file()
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # The GUI loads style.css via importlib.resources, so it must be package
    # data or the installed app raises FileNotFoundError at startup.
    assert re.search(r'"linguafix\.gui"\s*=\s*\["\*\.css"\]', pyproject)


def test_package_data_covers_runtime_assets() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = pyproject.split("[tool.setuptools.package-data]", 1)[1]
    for pattern in ('"data/*.json"', '"data/*.txt"', '"data/*.svg"', '"data/*.desktop"'):
        assert pattern in block, f"package-data is missing {pattern}"


def test_build_script_strips_bytecode() -> None:
    script = BUILD_DEB.read_text(encoding="utf-8")
    # Stale .pyc under the installed tree shadow edited sources and were a
    # reported bug; the build must strip them.
    assert "__pycache__" in script
    assert "*.pyc" in script


@pytest.mark.skipif(shutil.which("dpkg-deb") is None, reason="dpkg-deb not available")
def test_deb_carries_css_and_unit(tmp_path: Path) -> None:
    """Build a throwaway .deb and assert the GUI CSS and unit are inside it."""
    build = subprocess.run(
        ["bash", str(BUILD_DEB)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert build.returncode == 0, build.stderr
    deb = REPO_ROOT / "dist" / f"linguafix_{__version__}_all.deb"
    assert deb.is_file(), f"build produced no {deb.name}"
    listing = subprocess.run(
        ["dpkg-deb", "--contents", str(deb)], capture_output=True, text=True, check=True
    ).stdout
    assert "/gui/style.css" in listing
    assert "/systemd/user/linguafix.service" in listing
    assert "/usr/bin/linguafix" in listing


# --- release workflow -------------------------------------------------------


def test_release_workflow_only_fires_on_release_tags() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    # A stage tag such as ``v0.2.0-stage2`` must never publish a release, or it
    # would ship the previous version's .deb under the stage name.
    assert "tags:" in text
    assert '"v[0-9]+.[0-9]+.[0-9]+"' in text


def test_release_workflow_builds_and_verifies_the_deb() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "build_deb.sh" in text
    assert "smoke_test.sh" in text
    assert "deb_selfsufficiency_test.sh" in text
    assert "action-gh-release" in text


# --- CI workflow ------------------------------------------------------------


def test_ci_jobs_have_a_timeout() -> None:
    text = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # A stuck runner once left the Python 3.12 job pending for ~49 minutes; a
    # timeout-minutes on every job bounds that instead of hanging the check.
    _, _, jobs_text = text.partition("\njobs:\n")
    assert jobs_text, "ci.yml has no jobs section"
    jobs = re.findall(
        r"(?m)^  ([A-Za-z0-9_-]+):\n(.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
        jobs_text,
        re.S,
    )
    assert jobs, "ci.yml declares no jobs"
    for name, body in jobs:
        assert re.search(
            r"(?m)^    timeout-minutes:\s*\d+", body
        ), f"CI job {name!r} has no timeout-minutes"
