"""Project root resolution.

PROJECT_ROOT defaults to the parent of the `frontend/` folder
(i.e. the bot repo root). Override via env SCC_ROOT.

This module is the ONLY place that knows where bot files live. The API
is read-only over those files; nothing else should construct absolute
paths to the bot.
"""
from __future__ import annotations

import os
from pathlib import Path


def _resolve_root() -> Path:
    env = os.environ.get("SCC_ROOT")
    if env:
        return Path(env).resolve()
    # this file: <root>/frontend/api/app/paths.py
    return Path(__file__).resolve().parents[3]


PROJECT_ROOT: Path = _resolve_root()

CONFIG_PATH: Path = PROJECT_ROOT / "config" / "config.yaml"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
DATA_DIR: Path = PROJECT_ROOT / "data"

SIGNALS_JSONL: Path = LOGS_DIR / "signals.jsonl"
ALERTS_JSONL: Path = LOGS_DIR / "alerts.jsonl"
PAPER_TRADES_JSONL: Path = LOGS_DIR / "paper_trades.jsonl"
STATE_JSON: Path = LOGS_DIR / "state.json"
BOT_LOG: Path = LOGS_DIR / "bot.log"

PAPER_OVERRIDES_CSV: Path = LOGS_DIR / "paper_overrides.csv"

WEB_DIST_DIR: Path = PROJECT_ROOT / "frontend" / "web" / "dist"
