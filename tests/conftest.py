"""Shared pytest fixtures for the LinguaFix test-suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from linguafix.converter import LayoutConverter
from linguafix.detector import LanguageDetector

# Minimal stop-word list used across tests.
STOP_WORDS = ["password", "login", "token", "secret", "sudo"]


@pytest.fixture
def converter() -> LayoutConverter:
    """Return a converter backed by the bundled layout definitions."""
    return LayoutConverter()


@pytest.fixture
def detector(converter: LayoutConverter) -> LanguageDetector:
    """Return a detector using the bundled corpora and test stop words."""
    return LanguageDetector(converter=converter, stop_words=STOP_WORDS, min_word_length=3)


@pytest.fixture
def tmp_config_path(tmp_path: Path) -> Path:
    """Return a temporary path for a config file."""
    return tmp_path / "linguafix" / "config.toml"
