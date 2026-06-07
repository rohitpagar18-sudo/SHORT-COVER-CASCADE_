"""Phase 5D — First-alert-only episode collapse (D1).

Live behavior is unchanged: when a strike keeps passing conditions on
successive 5-min candles while it moves in our direction, the bot
keeps firing Telegram alerts. This module ONLY collapses those
re-fires for the *paper-trade* counting layer. It is read-only over
``logs/alerts.jsonl`` and derives ``alert_id`` at read-time.

An ``Episode`` is the set of alerts sharing the configured episode key
(default ``[symbol, option_type]``) whose candle timestamps fall within
``dedup_window_minutes`` of the episode's first alert. The
representative alert (the one that becomes the paper trade) is the
earliest by candle timestamp; ties are broken by the configured
``relation_priority`` (ITM1 wins by default).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger

IST = ZoneInfo("Asia/Kolkata")

# Sentinel attached to alert rows whose candle_timestamp had to fall
# back to alert_time (pre-mid-Phase-6 logs). Kept short for the
# dashboard "fidelity_note" column.
LEGACY_CANDLE_TS_NOTE = "legacy_pre_candle_ts"


# ---------------------------------------------------------------------------
# alert_id derivation (read-time only — never injected into alert-firing path)
# ---------------------------------------------------------------------------


def _get(row: dict[str, Any] | pd.Series, key: str, default: Any = None) -> Any:
    if isinstance(row, pd.Series):
        if key in row.index:
            v = row[key]
            if pd.isna(v):
                return default
            return v
        return default
    return row.get(key, default)


def _resolve_candle_timestamp(
    row: dict[str, Any] | pd.Series,
) -> tuple[datetime, bool]:
    """Return (candle_ts_aware_ist, used_fallback).

    Prefers the ``candle_timestamp`` field added mid-Phase-6. Legacy
    rows without that field fall back to ``alert_time`` then
    ``timestamp_ist`` (also a legacy alias used by some scripts).
    """
    raw = _get(row, "candle_timestamp")
    fallback = False
    if raw is None:
        raw = _get(row, "alert_time")
        fallback = True
    if raw is None:
        raw = _get(row, "timestamp_ist")
        fallback = True
    if raw is None:
        raise ValueError(
            "alert row missing timestamp fields: need any of "
            "candle_timestamp / alert_time / timestamp_ist"
        )
    ts = pd.to_datetime(raw)
    if ts.tzinfo is None:
        ts = ts.tz_localize(IST)
    return ts.to_pydatetime(), fallback


def derive_alert_id(row: dict[str, Any] | pd.Series) -> tuple[str, bool]:
    """Build the read-time ``alert_id`` for one alerts.jsonl row.

    Format: ``"{date}|{symbol}|{strike}|{option_type}|{expiry}|{candle_timestamp}"``

    Returns (alert_id, used_fallback). ``used_fallback`` is True for
    legacy rows that lacked ``candle_timestamp`` and had to fall back
    to ``alert_time``.
    """
    candle_ts, used_fallback = _resolve_candle_timestamp(row)
    date = candle_ts.date().isoformat()
    symbol = str(_get(row, "symbol", "?"))
    strike = _get(row, "strike", "?")
    try:
        strike = int(strike)
    except (TypeError, ValueError):
        strike = "?"
    option_type = str(_get(row, "option_type", "?")).upper()
    expiry = str(_get(row, "expiry", "?"))
    alert_id = (
        f"{date}|{symbol}|{strike}|{option_type}|{expiry}|"
        f"{candle_ts.isoformat()}"
    )
    return alert_id, used_fallback


# ---------------------------------------------------------------------------
# alerts.jsonl reader
# ---------------------------------------------------------------------------


def load_alerts_jsonl(path: str | Path) -> pd.DataFrame:
    """Read ``alerts.jsonl`` into a DataFrame.

    Holiday / data_issue / non-alert events are filtered out — only
    ``event_type == "alert"`` rows survive. Returns an empty frame
    with no columns when the file is absent or empty.
    """
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    rows: list[dict] = []
    with p.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(
                    f"paper_episodes: skipping malformed line {lineno} "
                    f"in {p.name}: {e}"
                )
                continue
            if rec.get("event_type", "alert") != "alert":
                continue
            rows.append(rec)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df


# ---------------------------------------------------------------------------
# Episode model
# ---------------------------------------------------------------------------


@dataclass
class Episode:
    """One paper-trade episode.

    Attributes:
        episode_id: stable string built from the episode key + the
            representative's candle_timestamp. Used as a dashboard
            grouping key (NOT as the paper trade's primary key — that
            is the representative's ``alert_id``).
        key_values: tuple of values matching the configured
            ``episode_key`` columns.
        representative_idx: integer index (within the input frame) of
            the alert that becomes the paper trade.
        member_indices: sorted list of all rows belonging to this
            episode, including the representative.
        echo_indices: ``member_indices`` minus the representative.
        first_candle_ts: candle timestamp of the representative (=
            earliest in the episode).
        window_end: ``first_candle_ts + dedup_window_minutes``.
    """

    episode_id: str
    key_values: tuple
    representative_idx: int
    member_indices: list[int] = field(default_factory=list)
    echo_indices: list[int] = field(default_factory=list)
    first_candle_ts: datetime | None = None
    window_end: datetime | None = None


def _row_key_values(row: pd.Series, episode_key: Sequence[str]) -> tuple:
    return tuple(_get(row, k) for k in episode_key)


def _relation_rank(
    relation: Any, relation_priority: Sequence[str]
) -> int:
    """Lower = preferred. Unknown labels go to the end."""
    if relation is None or pd.isna(relation):
        return len(relation_priority) + 1
    r = str(relation).strip().upper()
    try:
        return relation_priority.index(r)
    except ValueError:
        return len(relation_priority)


# ---------------------------------------------------------------------------
# Public: collapse alerts into episodes
# ---------------------------------------------------------------------------


def collapse_into_episodes(
    alerts: pd.DataFrame,
    episode_key: Sequence[str],
    dedup_window_minutes: int,
    relation_priority: Sequence[str],
) -> tuple[pd.DataFrame, list[Episode]]:
    """Collapse alerts into first-alert-only episodes.

    Args:
        alerts: DataFrame of ``event_type == "alert"`` rows (e.g. from
            ``load_alerts_jsonl``). Each row gets ``alert_id``,
            ``candle_ts``, ``paper_role`` ("representative" or "echo"),
            ``episode_id``, and ``fidelity_note`` appended.
        episode_key: list of column names whose tuple identifies an
            episode. Default ``[symbol, option_type]``.
        dedup_window_minutes: a re-fire within this many minutes of
            the episode's first alert belongs to the same episode.
        relation_priority: tie-break order for the rare same-candle
            multi-strike case. ITM1 first by default.

    Returns:
        ``(annotated_alerts, episodes)`` where ``annotated_alerts`` is
        a copy of the input frame plus the columns above, and
        ``episodes`` is the list of ``Episode`` objects.

    Algorithm:
        1. Sort by candle timestamp ascending, then by file order
           (stable secondary key).
        2. Walk in order. For each row, find an open episode with the
           matching key whose window covers this row's candle_ts —
           assign it as an echo. Otherwise open a new episode with
           this row as its provisional representative.
        3. Tie-break: if a later same-candle_ts row outranks the
           current representative by ``relation_priority``, swap.
    """
    if alerts is None or alerts.empty:
        return pd.DataFrame(), []

    df = alerts.copy().reset_index(drop=True)

    # Derive alert_id + candle_ts + fidelity once.
    alert_ids: list[str] = []
    candle_tss: list[datetime] = []
    fidelity_notes: list[str | None] = []
    for _, row in df.iterrows():
        aid, fallback = derive_alert_id(row)
        alert_ids.append(aid)
        ts, _ = _resolve_candle_timestamp(row)
        candle_tss.append(ts)
        fidelity_notes.append(LEGACY_CANDLE_TS_NOTE if fallback else None)
    df["alert_id"] = alert_ids
    df["candle_ts"] = candle_tss
    df["fidelity_note"] = fidelity_notes

    # Stable sort: oldest first, then preserve file order via the
    # original index, exposed as ``_file_order`` for tie-break.
    df["_file_order"] = range(len(df))
    df = df.sort_values(
        by=["candle_ts", "_file_order"], kind="stable"
    ).reset_index(drop=True)

    window = timedelta(minutes=int(dedup_window_minutes))
    episodes: list[Episode] = []
    open_idx_by_key: dict[tuple, int] = {}  # key -> index into episodes

    paper_roles: list[str] = ["echo"] * len(df)
    episode_ids: list[str | None] = [None] * len(df)

    for i, row in df.iterrows():
        key = _row_key_values(row, episode_key)
        ts: datetime = row["candle_ts"]

        existing_ep_idx = open_idx_by_key.get(key)
        if existing_ep_idx is not None:
            ep = episodes[existing_ep_idx]
            assert ep.window_end is not None
            if ts <= ep.window_end:
                # Belongs to existing episode.
                ep.member_indices.append(int(i))
                episode_ids[int(i)] = ep.episode_id

                # Tie-break: only swap representative if the new row
                # shares the FIRST candle_ts (= the rep's ts) and beats
                # the current rep by relation priority. We never let a
                # later candle override the rep — that would break the
                # "earliest wins" primary rule.
                if ts == ep.first_candle_ts:
                    cur_rep = df.loc[ep.representative_idx]
                    new_rank = _relation_rank(
                        row.get("relation"), relation_priority
                    )
                    cur_rank = _relation_rank(
                        cur_rep.get("relation"), relation_priority
                    )
                    if new_rank < cur_rank:
                        ep.representative_idx = int(i)
                continue
            # Window expired — open a new episode for this key.

        # Open a new episode.
        ep_id = f"{ts.isoformat()}|{'|'.join(str(v) for v in key)}"
        ep = Episode(
            episode_id=ep_id,
            key_values=key,
            representative_idx=int(i),
            member_indices=[int(i)],
            first_candle_ts=ts,
            window_end=ts + window,
        )
        episodes.append(ep)
        open_idx_by_key[key] = len(episodes) - 1
        episode_ids[int(i)] = ep_id

    # Finalize: derive echo_indices and stamp paper_role per row.
    for ep in episodes:
        ep.member_indices = sorted(ep.member_indices)
        ep.echo_indices = [i for i in ep.member_indices if i != ep.representative_idx]
        paper_roles[ep.representative_idx] = "representative"

    df["paper_role"] = paper_roles
    df["episode_id"] = episode_ids
    return df, episodes


def episode_representatives(
    annotated_alerts: pd.DataFrame,
) -> pd.DataFrame:
    """Filter the annotated frame to ONLY the representative rows."""
    if annotated_alerts is None or annotated_alerts.empty:
        return annotated_alerts
    return annotated_alerts[
        annotated_alerts["paper_role"] == "representative"
    ].copy().reset_index(drop=True)


def collapse_ratio(annotated_alerts: pd.DataFrame, episodes: Iterable[Episode]) -> str:
    """Human string ``"raw → episodes (X.XX:1)"`` for the backfill log."""
    eps = list(episodes)
    raw = 0 if annotated_alerts is None or annotated_alerts.empty else len(annotated_alerts)
    n = len(eps)
    if n == 0:
        return f"{raw} raw alerts → 0 episodes"
    return f"{raw} raw alerts → {n} episodes ({raw / n:.2f}:1)"
