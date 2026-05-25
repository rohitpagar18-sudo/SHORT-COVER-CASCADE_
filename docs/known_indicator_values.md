# Known Indicator Values — Real Chart Data

Source: Upstox/TradingView and Zerodha Kite screenshots.
Use as test fixtures in Phase 2 to validate indicator calculations.

## Acceptance Threshold
Bot indicator values should match these within:
- VWAP: ±0.5%
- RSI: ±2 points
- MAs: ±1%

## VWAP Type Confirmation
Upstox screenshots explicitly label: "VWAP hlc3 Session"
- Price input: (High + Low + Close) / 3
- Session-anchored, resets 9:15 AM IST daily

## Candle 1 — Valid Short-Cover Setup
- Platform: Zerodha Kite
- Instrument: NIFTY 05MAY 24050 PE
- Date/Time: 05 May 2026, 10:27 AM
- Option Close: 113.30
- RSI(14): 63.35
- RSI MA(20): 49.65
- Volume MA(20): 12.4M
- OI: 8.84M
- OI MA(20): not labeled (red line visible)
- Status: Likely valid C2/C3 (OI line visible below MA, RSI above MA and above 50)

## Candle 2 — STRONGEST DATA POINT (post-move short cover)
- Platform: Zerodha Kite
- Instrument: NIFTY 05MAY 23900 CE
- Date/Time: 05 May 2026, 1:29 PM
- Option Close: 144.30
- RSI(14): 51.47
- RSI MA(20): not labeled
- Volume MA(20): 13.5M
- OI: 4.51M (declining sharply from earlier 11.2M)
- OI MA(20): 11.2M
- OI vs MA: OI is 60% BELOW MA — classic C2 valid signal
- Status: This is the only candle with BOTH OI and OI MA labeled.
  Use as primary test fixture for C2 logic validation.

## Candle 3 — End-of-Day Reading (limited usefulness)
- Platform: Upstox (TradingView embedded)
- Instrument: NIFTY 19MAY26 23600 CE
- Date/Time: 14 May 2026, near close
- Option OHLC: O=248.40, H=251.85, L=223.00, C=228.15
- Day change: −8.48%
- Day volume: 1.124M (Volume MA: 1.957M)
- VWAP (hlc3 Session): 177.81
- RSI(14): 63.83
- OI: 3,776,175
- Status: End-of-day, not mid-session. Useful for VWAP formula check
  (given OHLC + volume series, our VWAP should compute to ~177.81)

## Candle 4 — No Signal Day (negative test case)
- Platform: Zerodha Kite
- Instrument: NIFTY MAY 23600 CE (monthly)
- Date/Time: 15 May 2026, end of session
- Option Close: 329.20
- Day change: −19.46%
- RSI(14): 45.84
- RSI MA(20): 35.33
- Volume MA(20): 49.4k
- OI: 987k
- OI MA(20): 938k
- Status: OI ABOVE MA (C2 fails) — correctly no signal all day
- Use as negative test case in C2

## Candle 5 — Gap Day, All Conditions Fail (negative test case)
- Platform: Upstox (TradingView embedded)
- Instrument: NIFTY 19MAY26 23600 PE
- Date/Time: 16 May 2026, end of session
- Option OHLC: O=279.80, H=292.95, L=268.80, C=272.50
- Day change: −2.43%
- VWAP (hlc3 Session): 117.04 (very low — confirms gap-up open day)
- RSI(14): 52.28
- RSI MA(20): 53.24
- RSI vs MA: BELOW (C3 fails)
- Volume MA(20): 4.314M (current 4.751M)
- OI: 2,163,008
- OI MA(20): 2,018,445
- OI vs MA: ABOVE (C2 fails)
- Status: Multiple conditions fail — correct rejection

## Summary for Test Suite (Phase 2)

| Test Type | Candle | What to Verify |
|---|---|---|
| Positive C2 | Candle 2 | OI 4.51M vs MA 11.2M → C2 valid |
| Positive C3 | Candle 1 | RSI 63.35 vs MA 49.65 → C3 valid |
| Negative C2 | Candle 4 | OI 987k vs MA 938k → C2 fails |
| Negative C3 | Candle 5 | RSI 52.28 vs MA 53.24 → C3 fails |
| VWAP formula | Candle 3 | hlc3 VWAP should ≈ 177.81 |
| Gap day | Candle 5 | Very low VWAP confirms gap day detection |

## Missing Data (acknowledged gaps)
- Spot NIFTY at each candle: not in screenshots (need separate chart)
- Individual candle OHLC mid-chart: only day OHLC available
- India VIX values: not visible on these charts (Upstox API provides live)