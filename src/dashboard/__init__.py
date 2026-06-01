"""Phase 5.2 dashboard package — JSONL → Parquet → Excel pipeline.

Public API:
  - ``sync_jsonl_to_parquet`` — read every JSONL log, write new rows to
    the monthly Parquet files in ``data/``. Idempotent.
  - ``update_dashboard`` — refresh the current quarter's Excel workbook
    in ``logs/dashboards/``. Idempotent.
  - ``sync_excel_notes_to_parquet`` — best-effort back-fill of
    user-filled outcome columns from the Order Place sheet to Parquet.
  - ``generate_remark_and_tags`` — bot_remark + bot_tags at alert time.
  - ``generate_outcome_remark`` — rule-based outcome remark after the
    user marks Order Status.
  - ``telegram_short_remark`` — short verdict line for the Telegram
    alert "Insight:" row.
"""

from __future__ import annotations

from src.dashboard.data_writer import (
    sync_auto_outcomes_to_parquet,
    sync_excel_notes_to_parquet,
    sync_jsonl_to_parquet,
)
from src.dashboard.excel_builder import update_dashboard
from src.dashboard.remarks import (
    generate_outcome_remark,
    generate_remark_and_tags,
    telegram_short_remark,
)

__all__ = [
    "sync_jsonl_to_parquet",
    "sync_auto_outcomes_to_parquet",
    "sync_excel_notes_to_parquet",
    "update_dashboard",
    "generate_remark_and_tags",
    "generate_outcome_remark",
    "telegram_short_remark",
]
