# Phase 6.1 — Shadow C5 (ADX Trend Filter)

**Status:** Additive sub-phase landed during the Phase 6 live alert-only
validation window. **Non-gating.** No change to which alerts fire today.

## Goal

Capture ADX(14) data on every scan so we can decide, after N days of
shadow logging, whether ADX should join the C1–C4 trigger set as C5.

## What changed

- New indicator: `src/indicators/adx.py` (Wilder-approx ADX/+DI/-DI on
  the SPOT 5-min OHLC, multi-day, rolling — NOT session-anchored).
- New pure condition: `src/conditions/c5_adx.py`. Decision-only — heavy
  math stays in the indicator module.
- `ConditionResult` grows a `gating: bool = True` field. `all_passed` is
  now computed only over `gating=True` results, so shadow C5 (appended
  with `gating=False`) never blocks an alert.
- Orchestrator computes ADX **once per `_scan_symbol`** and reuses across
  CE/PE/strikes. The full C5 path is crash-isolated: any exception logs
  a `data_issue` row (`issue_type="C5_ADX"`) and the C1–C4 alert still
  fires.
- Telegram alert appends a combined C5 + Spot DI + Opt DI line when
  `c5_adx.enabled` (see "Combined Telegram line" below).
- `signals.jsonl` gains the fields: `adx`, `adx_prev`, `di_plus`,
  `di_minus`, `di_aligned`, `option_di_plus`, `option_di_minus`,
  `option_di_aligned`, `c5_passed`, `c5_reason`,
  `session_candle_index`. Rows are written with explicit `null` when C5
  is disabled so Parquet doesn't choke. `schema_version` bumped to `3`.

## Config keys (config/config.yaml)

```yaml
conditions:
  c5_adx:
    enabled: ON           # compute + log + display
    gating:  OFF          # flip later to require C1–C5
    period:  14
    adx_min: 20           # 15=earliest, 20=balanced, 25=established
    require_rising: ON    # adx > adx_prev (ignition filter)
    use_di_alignment: OFF # see "Decision: DI alignment OFF" below
    lookback_candles: 150
```

### Decision: DI alignment OFF (on its own merits)

C5's job is to measure trend **strength**, not direction:

- **Strength legs (drive C5 ✓/❌):** `adx >= adx_min` AND `adx > adx_prev`.
- **Direction legs (already covered upstream):** C0 (spot vs spot VWAP)
  and C1 (option vs option VWAP) already pin the trade direction. Adding
  a DI-alignment requirement on top would be a redundant directional
  gate, not a strength filter.
- **+DI / −DI keep flowing into `signals.jsonl`** on every scan and into
  the Telegram alert line for visibility, but they no longer flip the
  C5 ✓/❌. Phase 7 backtests have the full data to revisit this if the
  shadow window shows DI-alignment carrying independent signal.

This decision is independent of the C0 toggle and stands on the
strength-vs-direction split alone.

### Combined Telegram line (Spot DI + Opt DI)

The C5 suffix on the alert line shows ADX state PLUS two directional
indicators, both informational:

```
C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓ | C5 ✓  ADX 24.1 ↑  |  Spot +DI>−DI ✓  Opt +DI>−DI ✓
C0 ✓ C1 ✓ C2 ✓ C3 ✓ C4 ✓ | C5 ❌  ADX 16.1 ↓  |  Spot +DI<−DI ✗  Opt +DI>−DI ✓
```

- **Spot DI** uses CE/PE context. CE wants `+DI > −DI` (✓); PE wants
  `−DI > +DI` (✓). The label flips accordingly: `Spot +DI>−DI` for CE,
  `Spot −DI>+DI` for PE.
- **Opt DI** is **direction-agnostic**: we are always BUYING the option
  and always want the premium trending up, so it's always `Opt +DI>−DI ✓`
  or `Opt +DI<−DI ✗` regardless of CE/PE. Computed on the option's own
  5-min candle series, same period as spot (`c5_adx.period`), reusing
  `compute_adx_di`. Fewer than `2*period` option candles → renders as
  `Opt N/A`; never blocks the alert, never defaults to aligned.
- **Option DI is informational only.** It does NOT affect C5 pass/fail.
  Spot+Opt comparison is what Phase 7 will mine for: does the option-side
  +DI > −DI signal predict outcome independently of spot ADX strength?

### Two-switch semantics

| enabled | gating | Effect                                                               |
|---------|--------|----------------------------------------------------------------------|
| OFF     | n/a    | C5 absent: not computed, no log fields, no alert line                |
| ON      | OFF    | **Shadow:** computed + logged + shown, NEVER blocks an alert         |
| ON      | ON     | **Gating:** C5 joins the trigger set; alert only when C1–C5 pass     |

C0 stays exactly as it was — irrelevant to C5.

## Acceptance line for Phase 6.1

1. Bot runs the alert-only validation window with `enabled:ON, gating:OFF`.
2. After N days (target: same N as the Phase 6 window), pull
   `scc_data_YYYY-MM.parquet` and compute, **per direction (CE/PE)**:
   - Of all C1–C4 alerts where C5 passed → win rate / R-multiple.
   - Of all C1–C4 alerts where C5 failed → same metrics.
   - Tune `adx_min` from the distribution; decide whether the lift
     justifies promoting C5 to gating.
3. If kept, flip `c5_adx.gating: ON` and document the decision under
   "Strategy Decisions Locked In" in CLAUDE.md.

## Calibration follow-up

The ADX implementation uses `pandas.ewm(alpha=1/period, adjust=False)`
which approximates Wilder but differs from canonical Wilder seeding for
the first ~2*period rows. With `lookback_candles=150` (~2 sessions) the
warm-up has long since washed out. The calibration test in
`tests/test_indicators.py::test_adx_uptrend_passes_min` currently uses a
synthetic series. On the second laptop during market hours, capture a
Kite ADX(14) screenshot and add the fixture to
`docs/known_indicator_values.md`; assert bot ADX within ±4 of the chart.
If that ever breaks, swap in true Wilder seeding (same pattern as
`src/indicators/rsi.py`) — do not silently switch.
