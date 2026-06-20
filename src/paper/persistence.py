"""Phase 5D — Paper-trade persistence (D4).

Two on-disk artifacts:

  - ``logs/paper_trades.jsonl`` — auto-generated. One record per TAKEN
    episode representative. Keyed by ``alert_id``; the generator
    rewrites the file in full on every run, but ordering + content is
    deterministic so the file stays idempotent. SKIPPED reps are NOT
    persisted — they are not paper trades.

  - ``logs/paper_overrides.csv`` — **user-owned manual override file.**
    Use it to correct an auto-computed outcome when the candle replay
    got it wrong (data gap, broker fill differed from cache, etc.).
    Keyed by ``alert_id`` with columns ``manual_decision``,
    ``manual_reason``, ``manual_outcome``, ``manual_exit``,
    ``user_notes``. The generator NEVER overwrites or deletes this
    file; it only creates it (headers-only) when missing.

The ``merge_overrides`` helper produces the unified view that the
dashboard renders: manual values win over auto whenever they are set,
auto values fill in the rest.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from loguru import logger


OVERRIDE_COLUMNS = (
    "alert_id",
    "manual_decision",
    "manual_reason",
    "manual_outcome",
    "manual_exit",
    "user_notes",
)


@dataclass
class PaperTradeRecord:
    """One row of ``paper_trades.jsonl``.

    Combines the read-time alert detail + selection verdict + outcome
    so the dashboard generator can render a paper trade without
    re-joining anything.
    """

    alert_id: str
    episode_id: str
    paper_role: str  # representative
    date: str
    candle_timestamp: str
    symbol: str
    strike: int
    relation: str
    option_type: str
    expiry: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    lots: int
    lot_size: int
    is_expiry_day: bool

    # Selection-gate verdict
    decision: str           # TAKEN / SKIPPED
    decision_reason: str
    slot: int | None

    # Outcome (only meaningful for TAKEN; SKIPPED rows still get the
    # kernel's verdict on the candles to keep the data complete, but
    # the dashboard only reports paper_pnl on TAKEN).
    outcome: str
    exit_price: float | None
    exit_time: str | None
    exit_reason: str
    realized_R: float
    paper_pnl: float
    paper_pnl_per_unit: float
    mfe: float
    mae: float
    mfe_R: float
    mae_R: float
    max_drawdown_R: float
    intrabar_ambiguous: bool
    fidelity: str
    fidelity_note: str | None  # legacy_pre_candle_ts | None

    # Bookkeeping — surfaced for the dashboard / debugging.
    bot_remark: str | None = None
    bot_tags: str | None = None
    triggered_caps: list[str] | None = None

    # Split-leg exit breakdown (TP1_BE / TP1_HIT only). ``None`` for
    # single-leg outcomes. Front-end renders "₹leg1 → ₹leg2" when both
    # are present; otherwise the single ``exit_price`` is shown.
    exit_price_leg1: float | None = None
    exit_price_leg2: float | None = None


# ---------------------------------------------------------------------------
# paper_trades.jsonl
# ---------------------------------------------------------------------------


def write_paper_trades(
    path: str | Path,
    records: Iterable[PaperTradeRecord],
) -> int:
    """Write the full set of paper-trade records to ``path``.

    Idempotent overwrite: every call rebuilds the file from scratch.
    Returns the number of records written.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
            n += 1
    return n


def read_paper_trades(path: str | Path) -> pd.DataFrame:
    """Read ``paper_trades.jsonl`` into a DataFrame.

    Empty / missing file → empty frame.
    """
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    rows: list[dict] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(
                    f"paper_persistence: skipping malformed line in {p}: {e}"
                )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# paper_overrides.csv  (USER-OWNED — never rewritten by the generator)
# ---------------------------------------------------------------------------


def ensure_overrides_file(path: str | Path) -> Path:
    """Create the overrides CSV with headers if it does not exist.

    Never touches the file once it exists — preserves user edits.
    Returns the resolved Path.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        return p
    with p.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(OVERRIDE_COLUMNS)
    logger.info(f"paper_persistence: created empty overrides file at {p}")
    return p


def read_overrides(path: str | Path) -> pd.DataFrame:
    """Read the user's overrides CSV.

    Returns an empty frame (with the canonical column set) if missing
    or empty. Tolerant of partial column sets — missing columns are
    filled with None.
    """
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=list(OVERRIDE_COLUMNS))
    try:
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
    except Exception as e:
        logger.warning(f"paper_persistence: cannot read overrides {p}: {e}")
        return pd.DataFrame(columns=list(OVERRIDE_COLUMNS))
    for col in OVERRIDE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    # Treat empty strings as missing values for downstream logic.
    for col in df.columns:
        df[col] = df[col].where(df[col].astype(str).str.strip() != "", None)
    return df


def merge_overrides(
    trades: pd.DataFrame, overrides: pd.DataFrame
) -> pd.DataFrame:
    """Merge ``overrides`` onto ``trades`` — manual values always win.

    Resulting columns include the auto fields plus ``manual_*`` and
    a ``effective_decision`` / ``effective_outcome`` pair that is
    ``manual_*`` if present else ``auto_*``. Original auto columns are
    preserved unchanged so the dashboard can show both side-by-side.
    """
    if trades is None or trades.empty:
        return trades

    merged = trades.copy()
    for col in OVERRIDE_COLUMNS:
        if col == "alert_id":
            continue
        if col not in merged.columns:
            merged[col] = None

    if overrides is not None and not overrides.empty and "alert_id" in overrides.columns:
        ov_indexed = overrides.set_index("alert_id")
        for col in OVERRIDE_COLUMNS:
            if col == "alert_id":
                continue
            if col not in ov_indexed.columns:
                continue
            mapped = merged["alert_id"].map(ov_indexed[col])
            mask = mapped.notna()
            merged.loc[mask, col] = mapped[mask].values

    def _eff(row: pd.Series, manual_col: str, auto_col: str) -> Any:
        m = row.get(manual_col)
        if m is not None and not (isinstance(m, float) and pd.isna(m)) and str(m).strip() != "":
            return m
        return row.get(auto_col)

    merged["effective_decision"] = merged.apply(
        lambda r: _eff(r, "manual_decision", "decision"), axis=1
    )
    merged["effective_outcome"] = merged.apply(
        lambda r: _eff(r, "manual_outcome", "outcome"), axis=1
    )
    return merged
