"""Shared pytest fixtures for the short-cover-cascade test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config_loader import AppConfig, load_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


@pytest.fixture
def config() -> AppConfig:
    """Load the real config.yaml (test code never touches live APIs)."""
    return load_config(CONFIG_PATH)


@pytest.fixture
def kite_config(config: AppConfig) -> AppConfig:
    """Config with active_feed forced to kite."""
    return config.model_copy(
        update={"feeds": config.feeds.model_copy(update={"active_feed": "kite"})}
    )


@pytest.fixture
def upstox_config(config: AppConfig) -> AppConfig:
    """Config with active_feed forced to upstox."""
    return config.model_copy(
        update={"feeds": config.feeds.model_copy(update={"active_feed": "upstox"})}
    )
