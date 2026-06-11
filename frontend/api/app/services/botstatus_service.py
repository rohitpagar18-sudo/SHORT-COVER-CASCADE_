"""Infer bot RUNNING/STOPPED from logs/bot.log mtime.

Threshold default = 120s. The bot writes to bot.log on every 5-min scan
plus heartbeat/info lines in between; anything within 2 minutes is
treated as live. Configurable via env SCC_BOT_ALIVE_SECONDS."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional, Tuple

from ..paths import BOT_LOG
from ..time_utils import IST, fmt_ist


def _threshold_seconds() -> int:
    try:
        return int(os.environ.get("SCC_BOT_ALIVE_SECONDS", "120"))
    except ValueError:
        return 120


def status() -> Tuple[str, Optional[str]]:
    """Return (status, last_activity_ist_iso_or_None)."""
    try:
        st = BOT_LOG.stat()
    except OSError:
        return "STOPPED", None
    mtime = datetime.fromtimestamp(st.st_mtime, tz=IST)
    age = (datetime.now(IST) - mtime).total_seconds()
    return ("RUNNING" if age <= _threshold_seconds() else "STOPPED", fmt_ist(mtime))
