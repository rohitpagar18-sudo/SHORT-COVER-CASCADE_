"""Shadow-SL runner — read-only over alerts.jsonl + replay_cache.

Walks every alert in ``logs/alerts.jsonl`` against the enabled shadow
methods and appends one row per ``(alert × method)`` to
``logs/shadow_sl.jsonl``.

Read-only guarantees
--------------------
This module touches the following paths and NO others:

  * Reads  ``logs/alerts.jsonl``               (alert source)
  * Reads  ``config/config.yaml``              (toggles + per-method params)
  * Reads  ``data/replay_cache/<date>/<sym>_<strike>_<TYPE>.parquet``
                                               (candles; cache-miss -> skip)
  * Writes ``logs/shadow_sl.jsonl``            (its only output)

It MUST NEVER touch ``logs/paper_trades.jsonl``, the monthly Parquet
files, or the Excel workbooks. Tests assert this invariant.

Idempotency
-----------
Re-running the script appends only rows whose
``(entry_time, symbol, strike, option_type, method)`` tuple is not
already present in the output file. The write is atomic (tempfile +
``os.replace``) so a crash mid-write cannot corrupt the existing file.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import date as date_cls, date, datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

from src.shadow_sl import engine  # noqa: F401 - ensures methods register

IST = ZoneInfo("Asia/Kolkata")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALERTS_PATH = PROJECT_ROOT / "logs" / "alerts.jsonl"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "logs" / "shadow_sl.jsonl"
REPLAY_CACHE_DIR = PROJECT_ROOT / "data" / "replay_cache"

DEDUP_KEYS = ("entry_time", "symbol", "strike", "option_type", "method")


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Summary of one ``run()`` invocation."""

    alerts_read: int
    alerts_skipped_cache_miss: int
    rows_written: int
    rows_skipped_duplicate: int
    methods_run: list[str]
    output_path: Path


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _read_alerts(alerts_path: Path) -> list[dict[str, Any]]:
    """Read ``alerts.jsonl``. Returns only ``event_type == 'alert'`` rows."""
    if not alerts_path.exists():
        return []
    out: list[dict[str, Any]] = []
    with alerts_path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(
                    f"shadow_sl.runner: skipping malformed line {lineno} "
                    f"in {alerts_path.name}: {e}"
                )
                continue
            if rec.get("event_type", "alert") != "alert":
                continue
            out.append(rec)
    return out


def _read_existing_keys(output_path: Path) -> set[tuple]:
    """Return the set of dedup keys already in ``output_path``."""
    if not output_path.exists():
        return set()
    keys: set[tuple] = set()
    with output_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            keys.add(_dedup_key(rec))
    return keys


def _dedup_key(rec: dict[str, Any]) -> tuple:
    return tuple(rec.get(k) for k in DEDUP_KEYS)


def _atomic_append(output_path: Path, rows: Iterable[dict[str, Any]]) -> int:
    """Append ``rows`` to ``output_path`` atomically.

    Reads the current file, writes existing + new rows into a tempfile
    in the same directory, then ``os.replace``s the tempfile over the
    target. Returns the number of new rows actually written.
    """
    rows = list(rows)
    if not rows:
        return 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if output_path.exists():
        existing = output_path.read_text(encoding="utf-8")
    # Ensure existing content ends with a newline so concatenation is clean.
    if existing and not existing.endswith("\n"):
        existing += "\n"
    new_lines = "\n".join(json.dumps(r, default=_json_default) for r in rows) + "\n"

    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=output_path.parent,
        prefix=".shadow_sl.",
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(existing)
        tmp.write(new_lines)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, output_path)
    return len(rows)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date_cls)):
        return obj.isoformat()
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    raise TypeError(f"Unhandled type {type(obj).__name__}")


# ---------------------------------------------------------------------------
# Candle loading — cache-only (read-only over data/replay_cache/)
# ---------------------------------------------------------------------------


def _cache_path(
    symbol: str, strike: int, option_type: str, trading_date: date
) -> Path:
    return (
        REPLAY_CACHE_DIR
        / trading_date.isoformat()
        / f"{symbol.upper()}_{int(strike)}_{option_type.upper()}.parquet"
    )


def _load_cached_candles(
    symbol: str, strike: int, option_type: str, trading_date: date
) -> pd.DataFrame | None:
    p = _cache_path(symbol, strike, option_type, trading_date)
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception as e:
        logger.warning(f"shadow_sl.runner: failed to read {p}: {e}")
        return None


# ---------------------------------------------------------------------------
# Alert-level utilities
# ---------------------------------------------------------------------------


def _resolve_entry_timestamp(alert: dict[str, Any]) -> datetime:
    """Pick the entry-candle timestamp (matches paper.episodes)."""
    raw = (
        alert.get("candle_timestamp")
        or alert.get("alert_time")
        or alert.get("timestamp_ist")
    )
    if raw is None:
        raise ValueError("alert row missing candle_timestamp/alert_time/timestamp_ist")
    ts = pd.to_datetime(raw)
    if ts.tzinfo is None:
        ts = ts.tz_localize(IST)
    else:
        ts = ts.tz_convert(IST)
    return ts.to_pydatetime()


def _is_expiry_from_alert(alert: dict[str, Any]) -> bool:
    """Infer is_expiry from the logged ``day_type`` field (Normal/Expiry)."""
    return str(alert.get("day_type") or "").strip().lower() == "expiry"


def _tp_multipliers(
    risk_reward_cfg: Any, is_expiry: bool
) -> tuple[float, float]:
    if is_expiry:
        return (
            float(risk_reward_cfg.expiry_day_tp1_r),
            float(risk_reward_cfg.expiry_day_tp2_r),
        )
    return (
        float(risk_reward_cfg.normal_day_tp1_r),
        float(risk_reward_cfg.normal_day_tp2_r),
    )


# ---------------------------------------------------------------------------
# Method configuration extraction
# ---------------------------------------------------------------------------


def _enabled_methods_from_config(shadow_cfg: Any) -> list[tuple[str, dict[str, Any]]]:
    """Return [(method_name, params_dict)] for every enabled method.

    Accepts either a pydantic model (with ``methods`` attribute holding
    per-method models) OR a plain dict (for tests). Skips methods whose
    ``enabled`` flag is False, and methods whose name is not in
    :data:`src.shadow_sl.engine.REGISTRY`.
    """
    pairs: list[tuple[str, dict[str, Any]]] = []
    atr_period = int(_get(shadow_cfg, "atr_period", 14))

    methods_block = _get(shadow_cfg, "methods", {}) or {}
    items: Iterable
    if isinstance(methods_block, dict):
        items = methods_block.items()
    else:
        # pydantic model: iterate field names declared on the model class.
        field_names = list(getattr(type(methods_block), "model_fields", {}).keys())
        items = ((name, getattr(methods_block, name)) for name in field_names)

    for name, settings in items:
        enabled = bool(_get(settings, "enabled", False))
        if not enabled:
            continue
        if name not in engine.REGISTRY:
            logger.warning(f"shadow_sl.runner: unknown method '{name}' — skipped")
            continue
        params = _settings_to_dict(settings)
        params.setdefault("atr_period", atr_period)
        pairs.append((name, params))
    return pairs


def _get(obj: Any, attr: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _settings_to_dict(settings: Any) -> dict[str, Any]:
    if isinstance(settings, dict):
        out = {k: v for k, v in settings.items() if k != "enabled"}
        return out
    if hasattr(settings, "model_dump"):
        d = settings.model_dump()
        d.pop("enabled", None)
        return d
    return {}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run(
    *,
    app_config: Any,
    alerts_path: Path | str = DEFAULT_ALERTS_PATH,
    output_path: Path | str = DEFAULT_OUTPUT_PATH,
    candle_loader=None,
) -> RunResult:
    """Run shadow-SL evaluation across every alert.

    Args:
        app_config: An ``AppConfig`` exposing ``risk_reward`` and
            ``shadow_sl`` blocks. ``shadow_sl.enabled == False`` short-
            circuits to a no-op result.
        alerts_path: Override the alerts file path (default
            ``logs/alerts.jsonl``).
        output_path: Override the shadow output file (default
            ``logs/shadow_sl.jsonl``).
        candle_loader: Optional callable
            ``(symbol, strike, option_type, trading_date) -> DataFrame |
            None`` — defaults to the read-only replay-cache loader.

    Returns:
        :class:`RunResult` describing how many rows were written.
    """
    shadow_cfg = getattr(app_config, "shadow_sl", None)
    if shadow_cfg is None or not bool(_get(shadow_cfg, "enabled", False)):
        return RunResult(0, 0, 0, 0, [], Path(output_path))

    method_pairs = _enabled_methods_from_config(shadow_cfg)
    if not method_pairs:
        return RunResult(0, 0, 0, 0, [], Path(output_path))

    alerts_path = Path(alerts_path)
    output_path = Path(output_path)

    loader = candle_loader or _load_cached_candles

    alerts = _read_alerts(alerts_path)
    existing_keys = _read_existing_keys(output_path)

    hh, mm = (int(x) for x in str(app_config.time_rules.hard_squareoff_time).split(":"))
    hard_squareoff_str = f"{hh:02d}:{mm:02d}"

    new_rows: list[dict[str, Any]] = []
    cache_misses = 0
    dup_skips = 0

    for alert in alerts:
        try:
            entry_ts = _resolve_entry_timestamp(alert)
        except Exception as e:
            logger.warning(f"shadow_sl.runner: bad alert timestamps ({e}) — skipped")
            continue
        symbol = str(alert.get("symbol") or "")
        try:
            strike = int(alert.get("strike"))
        except (TypeError, ValueError):
            continue
        option_type = str(alert.get("option_type") or "").upper()
        relation = str(alert.get("relation") or "")
        expiry = str(alert.get("expiry") or "")
        is_expiry = _is_expiry_from_alert(alert)

        try:
            entry = float(alert["entry"])
            sl_alert = float(alert["sl"])
        except (KeyError, TypeError, ValueError):
            continue
        R = entry - sl_alert
        if R <= 0:
            continue
        tp1_r, tp2_r = _tp_multipliers(app_config.risk_reward, is_expiry)
        tp1 = entry + R * tp1_r
        tp2 = entry + R * tp2_r

        trading_date = entry_ts.astimezone(IST).date()
        candles = loader(symbol, strike, option_type, trading_date)
        if candles is None or candles.empty:
            cache_misses += 1
            continue

        for method_name, raw_params in method_pairs:
            params = dict(raw_params)
            params["entry_timestamp"] = entry_ts
            params["hard_squareoff_time"] = hard_squareoff_str
            entry_time_str = entry_ts.isoformat()
            key = (entry_time_str, symbol, strike, option_type, method_name)
            if key in existing_keys:
                dup_skips += 1
                continue
            try:
                evaluate = engine.get_method(method_name)
                result = evaluate(entry, sl_alert, tp1, tp2, candles, params)
            except Exception as e:
                logger.warning(
                    f"shadow_sl.runner: method '{method_name}' raised on "
                    f"{symbol}/{strike}{option_type}@{entry_time_str}: {e}"
                )
                continue
            row = {
                "date": trading_date.isoformat(),
                "entry_time": entry_time_str,
                "symbol": symbol,
                "strike": strike,
                "option_type": option_type,
                "relation": relation,
                "method": method_name,
                "entry": float(entry),
                "initial_sl": float(sl_alert),
                "tp1": float(tp1),
                "tp2": float(tp2),
                "exit_price": result.get("exit_price"),
                "exit_time": result.get("exit_time"),
                "exit_reason": result.get("exit_reason"),
                "r_multiple": result.get("r_multiple"),
                "max_unrealized_r": result.get("max_unrealized_r"),
                "gave_back_r": result.get("gave_back_r"),
                "is_expiry": bool(is_expiry),
            }
            new_rows.append(row)
            existing_keys.add(key)

    written = _atomic_append(output_path, new_rows)

    return RunResult(
        alerts_read=len(alerts),
        alerts_skipped_cache_miss=cache_misses,
        rows_written=written,
        rows_skipped_duplicate=dup_skips,
        methods_run=[m for m, _ in method_pairs],
        output_path=output_path,
    )
