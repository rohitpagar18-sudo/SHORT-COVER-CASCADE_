"""Phase 5.2 — JSONL → Parquet (and Excel → Parquet) sync.

Two public functions:

  sync_jsonl_to_parquet()
      Reads logs/signals.jsonl, logs/alerts.jsonl, logs/gap_log.jsonl,
      and appends only the *new* rows to monthly Parquet files in
      data/scc_data_YYYY-MM.parquet. Idempotent: running twice in a
      row produces 0 new rows on the second run.

  sync_excel_notes_to_parquet()
      Best-effort reader for the user-filled Order Place columns
      (order_status, exit_price, pnl_rupees, user_notes). Writes the
      back-fill into the matching alert rows in the monthly Parquet
      files. Silently skips on any error — Excel-not-found never blocks
      the bot.

Dedup key is ``(timestamp_ist, event_type, symbol, strike, option_type)``.
For event_type == "gap" the per-symbol detail is flattened into
``nifty_*`` / ``banknifty_*`` columns and the row's ``symbol`` is null.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

IST = ZoneInfo("Asia/Kolkata")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOGS_DIR = PROJECT_ROOT / "logs"
DATA_DIR = PROJECT_ROOT / "data"
DASHBOARDS_DIR = LOGS_DIR / "dashboards"

SIGNALS_JSONL = LOGS_DIR / "signals.jsonl"
ALERTS_JSONL = LOGS_DIR / "alerts.jsonl"
GAP_JSONL = LOGS_DIR / "gap_log.jsonl"

DEDUP_KEY_COLS = (
    "timestamp_ist",
    "event_type",
    "symbol",
    "strike",
    "option_type",
)


# ---------------------------------------------------------------------------
# JSONL → DataFrame
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(
                    f"Skipping malformed JSON in {path.name} line {lineno}: {e}"
                )
    return rows


def _flatten_reasons(record: dict) -> dict:
    """Promote nested ``reasons.CN`` into top-level ``reasons.C0`` etc."""
    out = dict(record)
    reasons = out.pop("reasons", None)
    if isinstance(reasons, dict):
        for k, v in reasons.items():
            out[f"reasons.{k}"] = v
    return out


def _flatten_gap_record(record: dict) -> dict:
    """Turn a gap JSONL record into a flat row.

    ``per_symbol`` becomes ``nifty_*`` / ``banknifty_*`` columns.
    """
    out: dict[str, Any] = {
        "timestamp_ist": record.get("timestamp_ist"),
        "event_type": "gap",
        "symbol": None,
        "strike": None,
        "option_type": None,
        "decision": record.get("decision"),
        "enabled": record.get("enabled"),
        "threshold_pct": record.get("threshold_pct"),
        "direction": record.get("direction"),
        "any_triggered": record.get("any_triggered"),
    }
    per_sym = record.get("per_symbol") or {}
    for sym, prefix in (("NIFTY", "nifty"), ("BANKNIFTY", "banknifty")):
        info = per_sym.get(sym) or {}
        out[f"{prefix}_open"] = info.get("open")
        out[f"{prefix}_prev_close"] = info.get("prev_close")
        out[f"{prefix}_gap_pct"] = info.get("gap_pct")
        out[f"{prefix}_triggers"] = info.get("triggers")
        out[f"{prefix}_error"] = info.get("error")
    return out


def _records_to_frame(
    signals: Iterable[dict],
    alerts: Iterable[dict],
    gaps: Iterable[dict],
) -> pd.DataFrame:
    rows: list[dict] = []
    for r in signals:
        rows.append(_flatten_reasons(r))
    for r in alerts:
        rows.append(_flatten_reasons(r))
    for r in gaps:
        rows.append(_flatten_gap_record(r))

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # Backfill the common columns so downstream filtering is uniform.
    if "event_type" not in df.columns:
        df["event_type"] = "scan"
    df["event_type"] = df["event_type"].fillna("scan")

    if "symbol" not in df.columns:
        df["symbol"] = None
    if "strike" not in df.columns:
        df["strike"] = None
    if "option_type" not in df.columns:
        df["option_type"] = None

    df["timestamp_ist"] = df["timestamp_ist"].astype(str)
    df["date"] = df["timestamp_ist"].str.slice(0, 10)
    df["month"] = df["timestamp_ist"].str.slice(0, 7)
    return df


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------


def _dedup_key_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return a frame with only the dedup-key columns, normalised to strings.

    Strings are used because Parquet null handling for ints/floats can
    flip None ↔ NaN, which would otherwise break equality compare. The
    string-only key is stable across reads.
    """
    out = pd.DataFrame()
    for col in DEDUP_KEY_COLS:
        if col not in df.columns:
            out[col] = pd.Series([None] * len(df))
        else:
            out[col] = df[col].astype("object").where(df[col].notna(), None).map(
                lambda v: "" if v is None else str(v)
            )
    return out


def _filter_new_rows(
    incoming: pd.DataFrame, existing: pd.DataFrame
) -> pd.DataFrame:
    if incoming.empty:
        return incoming
    if existing.empty:
        return incoming
    inc_keys = _dedup_key_frame(incoming).astype(str).agg("||".join, axis=1)
    ex_keys = _dedup_key_frame(existing).astype(str).agg("||".join, axis=1)
    mask = ~inc_keys.isin(set(ex_keys))
    return incoming[mask].copy()


# ---------------------------------------------------------------------------
# Parquet I/O
# ---------------------------------------------------------------------------


def _parquet_path(month: str) -> Path:
    return DATA_DIR / f"scc_data_{month}.parquet"


def _read_existing_parquet(month: str) -> pd.DataFrame:
    p = _parquet_path(month)
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(p)
    except Exception as e:
        logger.warning(f"Failed to read {p}: {e} — will rewrite from scratch")
        return pd.DataFrame()


def _write_parquet(month: str, df: pd.DataFrame) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    p = _parquet_path(month)
    df.to_parquet(p, index=False)


# ---------------------------------------------------------------------------
# Public — JSONL → Parquet
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    rows_added: int = 0
    months_updated: int = 0
    total_rows_in_parquet: int = 0


def sync_jsonl_to_parquet() -> dict:
    """Sync every JSONL line into the monthly Parquet files.

    Returns a dict with keys ``rows_added``, ``months_updated``,
    ``total_rows_in_parquet``. Idempotent.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    signals = _read_jsonl(SIGNALS_JSONL)
    alerts = _read_jsonl(ALERTS_JSONL)
    gaps = _read_jsonl(GAP_JSONL)

    incoming = _records_to_frame(signals, alerts, gaps)
    if incoming.empty:
        return {"rows_added": 0, "months_updated": 0, "total_rows_in_parquet": 0}

    rows_added = 0
    months_updated = 0
    total_rows = 0

    for month, month_df in incoming.groupby("month"):
        existing = _read_existing_parquet(month)
        new_rows = _filter_new_rows(month_df, existing)
        if new_rows.empty and not existing.empty:
            total_rows += len(existing)
            continue
        combined = (
            pd.concat([existing, new_rows], ignore_index=True)
            if not existing.empty
            else new_rows
        )
        # Preserve column order: known cols first then anything new.
        combined = combined.sort_values("timestamp_ist").reset_index(drop=True)
        _write_parquet(month, combined)
        rows_added += len(new_rows)
        months_updated += 1
        total_rows += len(combined)

    logger.info(
        f"Parquet sync: +{rows_added} rows across {months_updated} months "
        f"(total {total_rows} rows)"
    )
    return {
        "rows_added": int(rows_added),
        "months_updated": int(months_updated),
        "total_rows_in_parquet": int(total_rows),
    }


# ---------------------------------------------------------------------------
# Public — Excel notes → Parquet
# ---------------------------------------------------------------------------


def _all_parquet_months() -> list[Path]:
    if not DATA_DIR.exists():
        return []
    return sorted(DATA_DIR.glob("scc_data_*.parquet"))


def _all_quarterly_dashboards() -> list[Path]:
    if not DASHBOARDS_DIR.exists():
        return []
    return sorted(DASHBOARDS_DIR.glob("dashboard_*.xlsx"))


_OUTCOME_COLUMNS = ("order_status", "exit_price", "pnl_rupees", "user_notes")


def _read_order_place_notes() -> pd.DataFrame:
    """Read the user-filled outcome columns from EVERY quarterly Excel.

    Returns an empty frame if no Excel exists or no rows are filled.
    """
    try:
        import openpyxl  # noqa: F401  (loaded lazily; absence is harmless)
    except Exception as e:
        logger.debug(f"openpyxl unavailable: {e}")
        return pd.DataFrame()

    workbooks = _all_quarterly_dashboards()
    if not workbooks:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for wb_path in workbooks:
        try:
            sheet = pd.read_excel(
                wb_path,
                sheet_name="Order Place",
                engine="openpyxl",
            )
        except Exception as e:
            logger.debug(f"Skipping {wb_path}: {e}")
            continue
        if sheet.empty:
            continue

        # Normalise column names (Excel ones are Title Case).
        rename_map = {
            "Timestamp IST": "timestamp_ist",
            "Symbol": "symbol",
            "Strike": "strike",
            "Option": "option_type",
            "Order Status": "order_status",
            "Exit Price": "exit_price",
            "P&L": "pnl_rupees",
            "User Notes": "user_notes",
        }
        # Keep only columns we know how to use.
        cols_present = [c for c in rename_map if c in sheet.columns]
        sheet = sheet[cols_present].rename(columns=rename_map)

        # Drop rows where no outcome column is filled.
        if not any(c in sheet.columns for c in _OUTCOME_COLUMNS):
            continue
        outcome_cols_in_frame = [c for c in _OUTCOME_COLUMNS if c in sheet.columns]
        mask = sheet[outcome_cols_in_frame].notna().any(axis=1)
        sheet = sheet[mask].copy()
        if sheet.empty:
            continue

        frames.append(sheet)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def sync_excel_notes_to_parquet() -> dict:
    """Best-effort back-fill of outcome columns from Excel into Parquet.

    Never raises. Any error is logged at debug level and reported in the
    return dict's ``skipped_reason``.

    Match key is ``(timestamp_ist, symbol, strike, option_type)`` against
    rows with ``event_type == "alert"``.
    """
    try:
        notes = _read_order_place_notes()
    except Exception as e:
        return {"alerts_updated": 0, "skipped_reason": f"read_failed: {e}"}

    if notes.empty:
        return {"alerts_updated": 0, "skipped_reason": "no notes filled yet"}

    months = _all_parquet_months()
    if not months:
        return {"alerts_updated": 0, "skipped_reason": "no parquet files yet"}

    # Normalise key columns on the notes side.
    notes["timestamp_ist"] = notes["timestamp_ist"].astype(str)
    if "strike" in notes.columns:
        notes["strike"] = pd.to_numeric(notes["strike"], errors="coerce")
    if "symbol" in notes.columns:
        notes["symbol"] = notes["symbol"].astype(str)
    if "option_type" in notes.columns:
        notes["option_type"] = notes["option_type"].astype(str)

    # Generate outcome_remark for any row where order_status is set.
    if "order_status" in notes.columns:
        from src.dashboard.remarks import generate_outcome_remark

        def _row_remark(row: pd.Series) -> str | None:
            status = row.get("order_status")
            if pd.isna(status) or status is None:
                return None
            return generate_outcome_remark(
                alert_data={"bot_remark": ""},
                outcome=str(status),
                exit_price=(
                    float(row["exit_price"])
                    if "exit_price" in row and pd.notna(row["exit_price"])
                    else None
                ),
                pnl=(
                    float(row["pnl_rupees"])
                    if "pnl_rupees" in row and pd.notna(row["pnl_rupees"])
                    else None
                ),
            )

        notes["outcome_remark"] = notes.apply(_row_remark, axis=1)

    alerts_updated = 0
    for parquet_path in months:
        try:
            df = pd.read_parquet(parquet_path)
        except Exception as e:
            logger.debug(f"Skipping {parquet_path}: {e}")
            continue
        if df.empty or "event_type" not in df.columns:
            continue

        merge_cols = [
            c
            for c in ("timestamp_ist", "symbol", "strike", "option_type")
            if c in df.columns and c in notes.columns
        ]
        if not merge_cols:
            continue

        # Make merge keys robust to dtype mismatch.
        df_keys = df.copy()
        df_keys["timestamp_ist"] = df_keys["timestamp_ist"].astype(str)
        if "strike" in merge_cols:
            df_keys["strike"] = pd.to_numeric(df_keys["strike"], errors="coerce")
        if "symbol" in merge_cols:
            df_keys["symbol"] = df_keys["symbol"].astype("object").map(
                lambda v: "" if v is None else str(v)
            )
        if "option_type" in merge_cols:
            df_keys["option_type"] = df_keys["option_type"].astype("object").map(
                lambda v: "" if v is None else str(v)
            )

        notes_keys = notes.copy()
        notes_keys["timestamp_ist"] = notes_keys["timestamp_ist"].astype(str)
        if "strike" in merge_cols:
            notes_keys["strike"] = pd.to_numeric(notes_keys["strike"], errors="coerce")
        if "symbol" in merge_cols:
            notes_keys["symbol"] = notes_keys["symbol"].astype("object").map(
                lambda v: "" if v is None else str(v)
            )
        if "option_type" in merge_cols:
            notes_keys["option_type"] = notes_keys["option_type"].astype("object").map(
                lambda v: "" if v is None else str(v)
            )

        outcome_cols = [
            c
            for c in (*_OUTCOME_COLUMNS, "outcome_remark")
            if c in notes_keys.columns
        ]
        if not outcome_cols:
            continue

        merged = df_keys.merge(
            notes_keys[merge_cols + outcome_cols],
            on=merge_cols,
            how="left",
            suffixes=("", "_excel"),
        )

        updated_count = 0
        for col in outcome_cols:
            excel_col = f"{col}_excel"
            if excel_col not in merged.columns:
                excel_col = col  # merged column not suffixed → use directly
            if excel_col not in merged.columns:
                continue
            mask = (
                (merged["event_type"] == "alert")
                & merged[excel_col].notna()
            )
            if not mask.any():
                continue
            if col not in df.columns:
                df[col] = None
            df.loc[mask, col] = merged.loc[mask, excel_col].values
            updated_count += int(mask.sum())

        if updated_count > 0:
            _write_parquet(
                parquet_path.stem.replace("scc_data_", ""), df
            )
            alerts_updated += updated_count

    if alerts_updated == 0:
        return {"alerts_updated": 0, "skipped_reason": "no matching alerts"}
    return {"alerts_updated": int(alerts_updated)}


# ---------------------------------------------------------------------------
# Helper used by excel_builder
# ---------------------------------------------------------------------------


def load_parquet_for_quarter(year: int, quarter: int) -> pd.DataFrame:
    """Concatenate the 3 months of a calendar quarter into one DataFrame.

    Empty months are skipped. Missing files are skipped.
    Returns an empty frame if nothing exists for the quarter.
    """
    start_month = (quarter - 1) * 3 + 1
    months = [f"{year:04d}-{start_month + i:02d}" for i in range(3)]
    frames = []
    for m in months:
        p = _parquet_path(m)
        if p.exists():
            try:
                frames.append(pd.read_parquet(p))
            except Exception as e:
                logger.warning(f"Skipping {p}: {e}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def quarter_for_date(d: datetime | None = None) -> tuple[int, int]:
    """Return (year, quarter) for the IST today (or for ``d``)."""
    if d is None:
        d = datetime.now(IST)
    return d.year, (d.month - 1) // 3 + 1


# ---------------------------------------------------------------------------
# Public — Auto outcome replay (Phase 5B-A)
# ---------------------------------------------------------------------------

AUTO_OUTCOME_COLUMNS = (
    "auto_order_status",
    "auto_exit_price",
    "auto_exit_time",
    "auto_exit_reason",
    "auto_pnl_per_unit",
    "mfe",
    "mae",
    "intrabar_ambiguous",
)


def sync_auto_outcomes_to_parquet(
    feed: Any | None = None,
    app_config: Any | None = None,
) -> dict:
    """Phase 5B-A — replay each alert and stamp ``auto_*`` outcome columns.

    Idempotent and append-only: existing non-null ``auto_order_status``
    rows are skipped. Manual outcome columns are never touched.

    Args:
        feed: Active ``BaseFeed`` for option-chain + candle fetches.
            Pass ``None`` to run in read-only / cache-only mode (any
            slice not already cached will be skipped).
        app_config: ``AppConfig``. Required to honour the toggle and
            read exit knobs. If ``None`` or the toggle is OFF, this
            function is a no-op.

    Returns:
        ``{"alerts_stamped": int, "alerts_skipped": int,
        "skipped_reason": str | None}``
    """
    if app_config is None:
        return {
            "alerts_stamped": 0,
            "alerts_skipped": 0,
            "skipped_reason": "no app_config provided",
        }
    if not getattr(app_config.dashboard, "auto_outcome_tracking", False):
        return {
            "alerts_stamped": 0,
            "alerts_skipped": 0,
            "skipped_reason": "dashboard.auto_outcome_tracking is OFF",
        }

    # Local imports keep the module load cheap when the feature is OFF.
    from src.dashboard.candle_cache import get_or_fetch_candles
    from src.dashboard.outcome_replay import replay_alert

    months = _all_parquet_months()
    if not months:
        return {
            "alerts_stamped": 0,
            "alerts_skipped": 0,
            "skipped_reason": "no parquet files yet",
        }

    stamped = 0
    skipped = 0
    for parquet_path in months:
        try:
            df = pd.read_parquet(parquet_path)
        except Exception as e:
            logger.warning(f"auto_outcomes: skip {parquet_path}: {e}")
            continue
        if df.empty or "event_type" not in df.columns:
            continue

        # Ensure all auto_* columns exist so .loc assignment is safe.
        for col in AUTO_OUTCOME_COLUMNS:
            if col not in df.columns:
                df[col] = None

        alerts_mask = df["event_type"] == "alert"
        if not alerts_mask.any():
            continue

        # Idempotency: only consider alerts WITHOUT a prior verdict.
        needs_stamp = alerts_mask & df["auto_order_status"].isna()
        if not needs_stamp.any():
            continue

        any_change = False
        for idx in df.index[needs_stamp]:
            row = df.loc[idx]
            # Defensive: ensure the alert row has the required fields.
            required = ("timestamp_ist", "entry", "sl", "tp1", "tp2",
                        "symbol", "strike", "option_type", "expiry")
            if any(pd.isna(row.get(k)) for k in required):
                skipped += 1
                continue

            alert_ts = pd.to_datetime(row["timestamp_ist"])
            trading_date = alert_ts.date()

            try:
                candles = get_or_fetch_candles(
                    feed=feed,
                    symbol=str(row["symbol"]),
                    strike=int(row["strike"]),
                    option_type=str(row["option_type"]),
                    expiry=str(row["expiry"]),
                    trading_date=trading_date,
                )
            except Exception as e:
                logger.warning(
                    f"auto_outcomes: candle fetch failed for "
                    f"{row.get('timestamp_ist')}: {e}"
                )
                skipped += 1
                continue

            if candles is None or candles.empty:
                skipped += 1
                continue

            try:
                result = replay_alert(row, candles, app_config)
            except Exception as e:
                logger.warning(
                    f"auto_outcomes: replay failed for "
                    f"{row.get('timestamp_ist')}: {e}"
                )
                skipped += 1
                continue

            if result is None:
                # Refusal (trailing-SL ON) or insufficient candles.
                skipped += 1
                continue

            df.at[idx, "auto_order_status"] = result.auto_order_status
            df.at[idx, "auto_exit_price"] = result.auto_exit_price
            df.at[idx, "auto_exit_time"] = result.auto_exit_time
            df.at[idx, "auto_exit_reason"] = result.auto_exit_reason
            df.at[idx, "auto_pnl_per_unit"] = result.auto_pnl_per_unit
            df.at[idx, "mfe"] = result.mfe
            df.at[idx, "mae"] = result.mae
            df.at[idx, "intrabar_ambiguous"] = result.intrabar_ambiguous
            stamped += 1
            any_change = True

        if any_change:
            month_key = parquet_path.stem.replace("scc_data_", "")
            _write_parquet(month_key, df)

    if stamped == 0:
        return {
            "alerts_stamped": 0,
            "alerts_skipped": skipped,
            "skipped_reason": (
                "no eligible alerts (already stamped, cache miss, "
                "or day not complete)"
            ),
        }
    logger.info(
        f"auto_outcomes: stamped {stamped} alerts, skipped {skipped}"
    )
    return {
        "alerts_stamped": stamped,
        "alerts_skipped": skipped,
        "skipped_reason": None,
    }
