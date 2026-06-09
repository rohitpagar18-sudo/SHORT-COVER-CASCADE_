"""Phase 5D — Paper Trades + Paper Dashboard + Echoes sheets.

Three new sheets appended to the existing quarterly workbook:

  1. ``Paper Trades``      — one row per episode representative
                              (TAKEN + SKIPPED). Coloured by outcome.
  2. ``Paper Dashboard``   — KPI cards built with Excel formulas
                              over Paper Trades. Manual columns win.
  3. ``Echoes (diagnostic)`` — every non-representative (echo)
                              re-fire. Hidden by default; collapse-
                              ratio data lives here.

The sheets read from a ``paper_trades.jsonl`` produced by
``src.paper.engine.run_paper_engine``. The dashboard builder calls
the engine once per workbook refresh, so the on-disk JSONL and the
sheets stay in lock-step. Manual overrides come from the user's
``paper_overrides.csv`` and ALWAYS win over the auto values.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd
from loguru import logger
from openpyxl.formatting.rule import DataBarRule, CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Paper-specific palette (use judgment, make it readable)
# ---------------------------------------------------------------------------

PAPER_HEADER_FILL = PatternFill("solid", fgColor="2E7D32")  # deep green
PAPER_HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
PAPER_BODY_FONT = Font(name="Calibri", size=11)
PAPER_TITLE_FONT = Font(name="Calibri", bold=True, color="2E7D32", size=16)
PAPER_SUB_FONT = Font(name="Calibri", italic=True, color="595959", size=10)

# Per-row fill by paper outcome (D5 spec).
PAPER_OUTCOME_FILLS = {
    "TP2_HIT":     PatternFill("solid", fgColor="6FBF73"),  # deep green
    "TP1_BE":      PatternFill("solid", fgColor="C8E6C9"),  # light green
    "TP1_HIT":     PatternFill("solid", fgColor="C8E6C9"),  # light green
    "SL_HIT":      PatternFill("solid", fgColor="EF9A9A"),  # red
    "HARD_EXIT":   PatternFill("solid", fgColor="EF9A9A"),  # red
    "OPEN_SQOFF":  PatternFill("solid", fgColor="FFD180"),  # amber
    "NO_DATA":     PatternFill("solid", fgColor="EEEEEE"),  # hatched grey
}

PAPER_SKIPPED_FILL = PatternFill("solid", fgColor="E0E0E0")  # grey

OUTCOME_CHIP = {
    "TP2_HIT":    "🟢 TP2",
    "TP1_BE":     "🟡 TP1→BE",
    "TP1_HIT":    "🟢 TP1",
    "SL_HIT":     "🔴 SL",
    "HARD_EXIT":  "🔴 Hard",
    "OPEN_SQOFF": "⏹ SqOff",
    "NO_DATA":    "· N/A",
}

MANUAL_OUTCOME_CHOICES = "TP2,TP1_BE,SL,Whipsaw,No-fill,Skipped,Open,Indeterminate"
MANUAL_DECISION_CHOICES = "TAKEN,SKIPPED,ECHO"

PAPER_SHEET_BANNER = (
    "PAPER — reconstructed from cached OHLC, not real fills. "
    "First-alert-only."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_paper_headers(ws: Worksheet, headers: Iterable[str], row: int = 1) -> None:
    for col_idx, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=col_idx, value=h)
        c.font = PAPER_HEADER_FONT
        c.fill = PAPER_HEADER_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 28


def _autofit(ws: Worksheet, df: pd.DataFrame, header_row: int = 1) -> None:
    for col_idx, col in enumerate(df.columns, start=1):
        max_len = max(
            [len(str(col))] + [len(str(v)) for v in df[col].head(200).tolist()]
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(
            max(12, max_len + 2), 38
        )


def _outcome_chip(outcome: str | None, decision: str | None) -> str:
    if decision and str(decision).upper() == "SKIPPED":
        return "· skip"
    if outcome is None:
        return ""
    return OUTCOME_CHIP.get(str(outcome).upper(), str(outcome))


# ---------------------------------------------------------------------------
# Paper Trades sheet
# ---------------------------------------------------------------------------


PAPER_TRADE_COLUMNS = [
    # Primary trade detail — shown first for quick review
    "date", "candle_timestamp", "symbol", "strike", "relation",
    "option_type", "expiry", "entry", "sl", "tp1", "tp2", "lots",
    "lot_size",
    # Outcome — what happened
    "paper_pnl", "outcome", "result_chip", "exit_price",
    "decision", "is_expiry_day",
    # Decision detail
    "decision_reason", "slot",
    # Manual override columns
    "manual_decision", "manual_reason", "manual_outcome",
    "manual_exit", "user_notes",
    # Detailed metrics (back)
    "exit_time", "realized_R", "mfe", "mae", "mfe_R", "mae_R",
    "max_drawdown_R", "intrabar_ambiguous", "fidelity", "fidelity_note",
    # Identity / diagnostics
    "alert_id", "episode_id", "bot_remark", "bot_tags", "triggered_caps",
]


def _fmt_expiry(val: object) -> str:
    """Format ISO date as '9th Jul 26' style."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    try:
        from datetime import date as _date
        s = str(val)[:10]
        d = _date.fromisoformat(s)
        day = d.day
        if 11 <= day <= 13:
            sfx = "th"
        else:
            sfx = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        return f"{day}{sfx} {d.strftime('%b')} {d.strftime('%y')}"
    except Exception:
        return str(val)


def build_paper_trades_sheet(
    ws: Worksheet,
    paper_trades_df: pd.DataFrame,
) -> int:
    """Fill the ``Paper Trades`` sheet from a merged-overrides frame.

    The frame must already include ``manual_*`` columns (filled or
    None) — call ``src.paper.persistence.merge_overrides`` before
    handing it here.
    """
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:H1")
    title = ws.cell(row=1, column=1, value="Paper Trades")
    title.font = PAPER_TITLE_FONT
    title.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    ws.merge_cells("A2:H2")
    sub = ws.cell(row=2, column=1, value=PAPER_SHEET_BANNER)
    sub.font = PAPER_SUB_FONT

    header_row = 4

    if paper_trades_df is None or paper_trades_df.empty:
        _set_paper_headers(ws, ["(no paper trades yet — run the bot)"], row=header_row)
        return 0

    df = paper_trades_df.copy()
    for col in PAPER_TRADE_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # Compute the result chip column at write-time so the dashboard
    # never disagrees with the underlying outcome / decision.
    df["result_chip"] = df.apply(
        lambda r: _outcome_chip(r.get("outcome"), r.get("decision")),
        axis=1,
    )

    df = df[PAPER_TRADE_COLUMNS].copy()
    if "expiry" in df.columns:
        df["expiry"] = df["expiry"].apply(_fmt_expiry)
    _set_paper_headers(ws, df.columns, row=header_row)

    written = 0
    for offset, (_, row) in enumerate(df.iterrows()):
        excel_row = header_row + 1 + offset
        for col_idx, col in enumerate(df.columns, start=1):
            v = row[col]
            if isinstance(v, list):
                v = ",".join(str(x) for x in v) if v else None
            if pd.isna(v):
                v = None
            cell = ws.cell(row=excel_row, column=col_idx, value=v)
            cell.font = PAPER_BODY_FONT
        written += 1

    _autofit(ws, df, header_row=header_row)

    # ---------------- per-row fills by outcome / decision ----------------
    col_index = {name: idx + 1 for idx, name in enumerate(df.columns)}
    n_cols = len(df.columns)

    for offset, (_, row) in enumerate(df.iterrows()):
        excel_row = header_row + 1 + offset
        decision = str(row.get("decision") or "").upper()
        outcome = str(row.get("outcome") or "").upper()
        fill = None
        strikethrough = False
        if decision == "SKIPPED":
            fill = PAPER_SKIPPED_FILL
            strikethrough = True
        else:
            fill = PAPER_OUTCOME_FILLS.get(outcome)
        if fill is not None:
            for c in range(1, n_cols + 1):
                ws.cell(row=excel_row, column=c).fill = fill
        if strikethrough:
            for c in range(1, n_cols + 1):
                cell = ws.cell(row=excel_row, column=c)
                cell.font = Font(name="Calibri", size=11, strike=True)

    # ---------------- data bars on realized_R + paper_pnl ----------------
    if written > 0:
        for col_name, positive_color, negative_color in [
            ("realized_R", "63B881", "EF6C6C"),
            ("paper_pnl", "63B881", "EF6C6C"),
        ]:
            if col_name not in col_index:
                continue
            letter = get_column_letter(col_index[col_name])
            range_ref = f"{letter}{header_row + 1}:{letter}{header_row + written}"
            ws.conditional_formatting.add(
                range_ref,
                DataBarRule(
                    start_type="num", start_value=-3,
                    end_type="num", end_value=3,
                    color=positive_color,
                ),
            )
            ws.conditional_formatting.add(
                range_ref,
                CellIsRule(
                    operator="lessThan", formula=["0"],
                    fill=PatternFill("solid", fgColor=negative_color),
                ),
            )

    # ---------------- data-validation dropdowns on manual columns -------
    if written > 0:
        dec_letter = get_column_letter(col_index["manual_decision"])
        out_letter = get_column_letter(col_index["manual_outcome"])
        dec_range = f"{dec_letter}{header_row + 1}:{dec_letter}{header_row + written}"
        out_range = f"{out_letter}{header_row + 1}:{out_letter}{header_row + written}"

        dec_dv = DataValidation(
            type="list",
            formula1=f'"{MANUAL_DECISION_CHOICES}"',
            allow_blank=True,
            showErrorMessage=False,
        )
        dec_dv.add(dec_range)
        ws.add_data_validation(dec_dv)

        out_dv = DataValidation(
            type="list",
            formula1=f'"{MANUAL_OUTCOME_CHOICES}"',
            allow_blank=True,
            showErrorMessage=False,
        )
        out_dv.add(out_range)
        ws.add_data_validation(out_dv)

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1).coordinate
    return written


# ---------------------------------------------------------------------------
# Paper Dashboard (KPIs via Excel formulas)
# ---------------------------------------------------------------------------


def build_paper_dashboard_sheet(
    ws: Worksheet,
    paper_trades_df: pd.DataFrame,
    paper_trades_sheet_name: str = "Paper Trades",
    collapse_summary: str | None = None,
) -> None:
    """KPI cards built with Excel formulas over the Paper Trades sheet.

    The dashboard reads manual-first then auto: every KPI references
    a helper column whose value is ``manual_outcome`` if set else
    ``outcome``. That helper column lives on Paper Trades and is
    populated at write-time so the formulas don't need IFERROR.
    """
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:H1")
    title = ws.cell(row=1, column=1, value="Paper Dashboard")
    title.font = PAPER_TITLE_FONT
    title.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    ws.merge_cells("A2:H2")
    sub = ws.cell(row=2, column=1, value=PAPER_SHEET_BANNER)
    sub.font = PAPER_SUB_FONT

    if paper_trades_df is None or paper_trades_df.empty:
        ws.cell(row=4, column=1, value="(no paper trades yet)").font = PAPER_SUB_FONT
        return

    # Range references — Paper Trades data block is rows 5..(5+n-1).
    n = len(paper_trades_df)
    data_start = 5
    data_end = data_start + n - 1
    sheet_ref = f"'{paper_trades_sheet_name}'!"

    # Map columns to letters. Must match the column order in
    # ``build_paper_trades_sheet`` exactly.
    column_letter = {
        col: get_column_letter(i + 1)
        for i, col in enumerate(PAPER_TRADE_COLUMNS)
    }
    dec_col = column_letter["decision"]
    eff_outcome_col = column_letter["outcome"]
    manual_outcome_col = column_letter["manual_outcome"]
    realized_R_col = column_letter["realized_R"]
    paper_pnl_col = column_letter["paper_pnl"]
    mfe_R_col = column_letter["mfe_R"]
    mae_R_col = column_letter["mae_R"]
    dd_R_col = column_letter["max_drawdown_R"]
    entry_col = column_letter["entry"]
    lots_col = column_letter["lots"]
    lot_size_col = column_letter["lot_size"]

    def rng(col_letter: str) -> str:
        return f"{sheet_ref}{col_letter}{data_start}:{col_letter}{data_end}"

    taken_count_f = f"=COUNTIF({rng(dec_col)},\"TAKEN\")"
    skipped_count_f = f"=COUNTIF({rng(dec_col)},\"SKIPPED\")"
    # Resolved = TAKEN AND outcome in {TP2,TP1_BE,TP1_HIT,SL_HIT,HARD_EXIT}
    resolved_f = (
        f"=SUMPRODUCT(({rng(dec_col)}=\"TAKEN\")*"
        f"(({rng(eff_outcome_col)}=\"TP2_HIT\")+"
        f"({rng(eff_outcome_col)}=\"TP1_BE\")+"
        f"({rng(eff_outcome_col)}=\"TP1_HIT\")+"
        f"({rng(eff_outcome_col)}=\"SL_HIT\")+"
        f"({rng(eff_outcome_col)}=\"HARD_EXIT\")))"
    )
    wins_f = (
        f"=SUMPRODUCT(({rng(dec_col)}=\"TAKEN\")*"
        f"(({rng(eff_outcome_col)}=\"TP2_HIT\")+"
        f"({rng(eff_outcome_col)}=\"TP1_BE\")+"
        f"({rng(eff_outcome_col)}=\"TP1_HIT\")))"
    )
    losses_f = (
        f"=SUMPRODUCT(({rng(dec_col)}=\"TAKEN\")*"
        f"(({rng(eff_outcome_col)}=\"SL_HIT\")+"
        f"({rng(eff_outcome_col)}=\"HARD_EXIT\")))"
    )
    # Headline P&L: TAKEN only.
    headline_pnl_f = (
        f"=SUMPRODUCT(({rng(dec_col)}=\"TAKEN\")*{rng(paper_pnl_col)})"
    )
    # All-alerts P&L diagnostic — include every row in the file
    # (still TAKEN rows only inflates correctly because echoes are
    # not in this sheet; this number is the "if I'd taken every
    # representative" reading).
    all_pnl_f = f"=SUM({rng(paper_pnl_col)})"
    avg_R_f = (
        f"=IFERROR(AVERAGEIFS({rng(realized_R_col)},{rng(dec_col)},\"TAKEN\"),0)"
    )
    max_dd_R_f = (
        f"=IFERROR(MIN(IF({rng(dec_col)}=\"TAKEN\",{rng(dd_R_col)})),0)"
    )
    avg_mfe_R_f = (
        f"=IFERROR(AVERAGEIFS({rng(mfe_R_col)},{rng(dec_col)},\"TAKEN\"),0)"
    )
    avg_mae_R_f = (
        f"=IFERROR(AVERAGEIFS({rng(mae_R_col)},{rng(dec_col)},\"TAKEN\"),0)"
    )
    peak_outlay_f = (
        f"=IFERROR(MAX(({rng(dec_col)}=\"TAKEN\")*"
        f"({rng(entry_col)}*{rng(lots_col)}*{rng(lot_size_col)})),0)"
    )

    # Win rate = wins / resolved (taken+resolved).
    win_rate_f = (
        f"=IFERROR(({wins_f.lstrip('=')})/({resolved_f.lstrip('=')}),0)"
    )

    kpi_rows = [
        ("Taken count",                taken_count_f),
        ("Skipped count",              skipped_count_f),
        ("Resolved (taken & resolved)", resolved_f),
        ("Wins (TP1 / TP2)",           wins_f),
        ("Losses (SL / Hard)",         losses_f),
        ("Win rate",                   win_rate_f),
        ("Average R",                  avg_R_f),
        ("Average MFE (R)",            avg_mfe_R_f),
        ("Average MAE (R)",            avg_mae_R_f),
        ("Max drawdown (R, taken)",    max_dd_R_f),
        ("Peak premium outlay (₹)",    peak_outlay_f),
    ]

    # Headline P&L (TAKEN only) — large + bold, deep green.
    ws.cell(row=4, column=1, value="HEADLINE PAPER P&L (TAKEN ONLY)").font = Font(
        bold=True, color="FFFFFF", size=11
    )
    ws.cell(row=4, column=1).fill = PatternFill("solid", fgColor="2E7D32")
    ws.merge_cells("A4:C4")

    big = ws.cell(row=5, column=1, value=headline_pnl_f)
    big.font = Font(size=22, bold=True, color="2E7D32")
    big.alignment = Alignment(horizontal="left", vertical="center")
    big.number_format = '₹#,##0.00;[Red]-₹#,##0.00'
    ws.merge_cells("A5:C5")
    ws.row_dimensions[5].height = 36

    # All-alerts diagnostic — greyed, smaller.
    ws.cell(row=6, column=1, value="all-alerts P&L (diagnostic, biased by re-fires)").font = Font(
        italic=True, color="757575", size=10
    )
    ws.merge_cells("A6:C6")
    diag = ws.cell(row=7, column=1, value=all_pnl_f)
    diag.font = Font(size=12, color="757575")
    diag.number_format = '₹#,##0.00'
    ws.merge_cells("A7:C7")

    # KPI table.
    row = 9
    ws.cell(row=row, column=1, value="KPI").font = PAPER_HEADER_FONT
    ws.cell(row=row, column=1).fill = PAPER_HEADER_FILL
    ws.cell(row=row, column=2, value="Value").font = PAPER_HEADER_FONT
    ws.cell(row=row, column=2).fill = PAPER_HEADER_FILL
    for i, (label, formula) in enumerate(kpi_rows, start=1):
        ws.cell(row=row + i, column=1, value=label).font = PAPER_BODY_FONT
        cell = ws.cell(row=row + i, column=2, value=formula)
        cell.font = PAPER_BODY_FONT
        if "rate" in label.lower():
            cell.number_format = "0.0%"
        elif "₹" in label:
            cell.number_format = '₹#,##0'
        elif "(R" in label or "R)" in label or label == "Average R":
            cell.number_format = "0.00"

    # Outcome distribution table + collapse ratio.
    table_start = row + len(kpi_rows) + 3
    ws.cell(row=table_start, column=1, value="Outcome distribution").font = Font(
        bold=True, color="2E7D32", size=12
    )
    ws.cell(row=table_start + 1, column=1, value="Outcome").font = PAPER_HEADER_FONT
    ws.cell(row=table_start + 1, column=1).fill = PAPER_HEADER_FILL
    ws.cell(row=table_start + 1, column=2, value="Count").font = PAPER_HEADER_FONT
    ws.cell(row=table_start + 1, column=2).fill = PAPER_HEADER_FILL
    for j, outcome_label in enumerate(
        ["TP2_HIT", "TP1_HIT", "TP1_BE", "SL_HIT", "HARD_EXIT", "OPEN_SQOFF", "NO_DATA"],
        start=2,
    ):
        ws.cell(row=table_start + j, column=1, value=outcome_label).font = PAPER_BODY_FONT
        fill = PAPER_OUTCOME_FILLS.get(outcome_label)
        if fill:
            ws.cell(row=table_start + j, column=1).fill = fill
        ws.cell(
            row=table_start + j, column=2,
            value=f'=COUNTIF({rng(eff_outcome_col)},"{outcome_label}")',
        ).font = PAPER_BODY_FONT

    # Collapse-ratio block (so re-fire inflation is visible).
    cr_row = table_start + 11
    ws.cell(row=cr_row, column=1, value="Episode collapse ratio").font = Font(
        bold=True, color="2E7D32", size=12
    )
    ws.cell(row=cr_row + 1, column=1, value=(collapse_summary or "(not recorded)"))
    ws.cell(row=cr_row + 1, column=1).font = PAPER_BODY_FONT

    # Generated-at footer.
    foot_row = cr_row + 3
    ws.cell(
        row=foot_row, column=1,
        value=f"Generated at {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')} IST",
    ).font = PAPER_SUB_FONT

    # Column widths
    for col_letter in ("A", "B", "C"):
        ws.column_dimensions[col_letter].width = 32


# ---------------------------------------------------------------------------
# Echoes sheet (hidden by default)
# ---------------------------------------------------------------------------


def build_echoes_sheet(
    ws: Worksheet,
    annotated_alerts: pd.DataFrame,
) -> int:
    """Echoes — every non-representative re-fire.

    Hidden by default so the main Paper Trades sheet stays
    first-alert-only. Kept for diagnostics: re-fire inflation, per-
    strike clustering, late chasers, etc.
    """
    ws.sheet_state = "hidden"
    ws.sheet_view.showGridLines = False

    ws.merge_cells("A1:H1")
    title = ws.cell(row=1, column=1, value="Echoes (diagnostic)")
    title.font = PAPER_TITLE_FONT
    title.alignment = Alignment(horizontal="left", vertical="center")

    ws.merge_cells("A2:H2")
    sub = ws.cell(
        row=2, column=1,
        value=(
            "Non-representative alerts — every re-fire that was collapsed "
            "into an episode. NOT counted in TAKEN P&L."
        ),
    )
    sub.font = PAPER_SUB_FONT

    header_row = 4
    if annotated_alerts is None or annotated_alerts.empty:
        _set_paper_headers(ws, ["(no alerts loaded)"], row=header_row)
        return 0

    echoes = annotated_alerts[annotated_alerts["paper_role"] == "echo"].copy()
    if echoes.empty:
        _set_paper_headers(ws, ["(no echoes — no re-fires)"], row=header_row)
        return 0

    show_cols = [
        c for c in (
            "alert_id", "episode_id", "candle_ts", "date", "symbol",
            "strike", "relation", "option_type", "entry", "sl",
            "tp1", "tp2", "bot_remark", "bot_tags", "fidelity_note",
        ) if c in echoes.columns
    ]
    out = echoes[show_cols].copy()
    if "candle_ts" in out.columns:
        out["candle_ts"] = out["candle_ts"].astype(str)
    out = out.sort_values(by=["episode_id", "candle_ts"]).reset_index(drop=True)

    _set_paper_headers(ws, out.columns, row=header_row)
    for offset, (_, row) in enumerate(out.iterrows()):
        excel_row = header_row + 1 + offset
        for col_idx, col in enumerate(out.columns, start=1):
            v = row[col]
            if pd.isna(v):
                v = None
            ws.cell(row=excel_row, column=col_idx, value=v).font = PAPER_BODY_FONT
    _autofit(ws, out, header_row=header_row)
    ws.freeze_panes = ws.cell(row=header_row + 1, column=1).coordinate
    return len(out)
