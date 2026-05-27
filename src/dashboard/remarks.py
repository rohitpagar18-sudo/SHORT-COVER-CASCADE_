"""Phase 5.2 bot-remark generator.

Pure functions — no I/O, no logging, no raises. Two passes:

1. ``generate_remark_and_tags`` — called at alert time with a snapshot
   dict and a context dict. Returns a human-readable ``bot_remark``
   (3–5 short clauses, ~25 words) and a structured ``bot_tags`` string
   (comma-separated, no spaces) for ML queries.

2. ``generate_outcome_remark`` — called after the user fills in the
   Order Status column in the Excel Order Place sheet. Maps the
   outcome category + alert quality to a rule-based outcome sentence.

3. ``telegram_short_remark`` — trims a long remark to verdict + 1–2
   observations for the Telegram alert "Insight:" line.

VIX regime lookup tolerates both enum-name form ("LOW", "NORMAL", ...)
and enum-value form ("Low Vol", "Normal", ...) so callers can pass
either ``info.regime.name`` or ``info.regime.value`` without surprise.
"""

from __future__ import annotations

from typing import List, Tuple


# ---------------------------------------------------------------------------
# Threshold maps — every helper returns (tag, human_phrase).
# ---------------------------------------------------------------------------


def _vwap_zone(opt_above_vwap_pct: float) -> Tuple[str, str]:
    p = opt_above_vwap_pct
    if p < 10:
        return ("fresh_breakout", f"opt {p:.0f}% above VWAP (fresh)")
    if p < 20:
        return ("clean_entry", f"opt {p:.0f}% above VWAP")
    if p < 25:
        return ("mid_entry", f"opt {p:.0f}% above VWAP (mid-zone)")
    return ("late_entry", f"opt {p:.0f}% above VWAP (near filter)")


def _rsi_zone(rsi: float) -> Tuple[str, str]:
    if rsi < 55:
        return ("low_rsi", f"RSI {rsi:.0f} early momentum")
    if rsi < 65:
        return ("moderate_rsi", f"RSI {rsi:.0f} moderate")
    if rsi < 75:
        return ("strong_rsi", f"RSI {rsi:.0f} healthy zone")
    return ("high_rsi", f"RSI {rsi:.0f} high momentum")


def _oi_strength(oi: float, oi_ma: float) -> Tuple[str, str]:
    if oi_ma <= 0:
        return ("oi_unknown", "OI data unclear")
    pct_below = ((oi_ma - oi) / oi_ma) * 100.0
    if pct_below > 15:
        return ("strong_oi", f"OI {pct_below:.0f}% below MA (strong cover)")
    if pct_below > 8:
        return ("moderate_oi", f"OI {pct_below:.0f}% below MA")
    if pct_below > 0:
        return ("weak_oi", f"OI {pct_below:.0f}% below MA (marginal)")
    return ("no_oi_signal", "OI not below MA — C2 should not have passed")


def _volume_strength(volume: float, volume_ma: float) -> Tuple[str, str]:
    if volume_ma <= 0:
        return ("vol_unknown", "vol data unclear")
    ratio = volume / volume_ma
    if ratio > 2.0:
        return ("explosive_volume", f"vol {ratio:.1f}× MA (explosive)")
    if ratio > 1.5:
        return ("high_volume", f"vol {ratio:.1f}× MA")
    if ratio > 1.2:
        return ("moderate_volume", f"vol {ratio:.1f}× MA")
    return ("low_volume", f"vol {ratio:.1f}× MA (marginal)")


def _time_zone(time_hhmm: str) -> Tuple[str, str]:
    h, m = int(time_hhmm[:2]), int(time_hhmm[3:5])
    minutes = h * 60 + m
    if minutes < 600:
        return ("opening", "opening hour")
    if minutes < 660:
        return ("morning", "morning push")
    if minutes < 720:
        return ("mid_morning", "mid-morning")
    if minutes < 780:
        return ("lunch", "lunch session")
    if minutes < 840:
        return ("early_afternoon", "early afternoon")
    return ("afternoon", "afternoon")


# VixRegime.value is "Low Vol" / "Normal" / "Elevated" / "High Vol", but
# callers may also pass the enum NAME ("LOW" / "NORMAL" / ...). Both work.
_VIX_PHRASES = {
    "LOW": ("low_vix", "LOW VIX (0.75× SL)"),
    "NORMAL": ("normal_vix", ""),
    "ELEVATED": ("elevated_vix", "ELEVATED VIX (1.25× SL)"),
    "HIGH": ("high_vix", "HIGH VIX (1.5× SL)"),
}
_VIX_VALUE_ALIASES = {
    "LOW VOL": "LOW",
    "NORMAL": "NORMAL",
    "ELEVATED": "ELEVATED",
    "HIGH VOL": "HIGH",
}


def _vix_context(vix_regime: str) -> Tuple[str, str]:
    if not vix_regime:
        return ("normal_vix", "")
    key = str(vix_regime).strip().upper()
    if key in _VIX_PHRASES:
        return _VIX_PHRASES[key]
    aliased = _VIX_VALUE_ALIASES.get(key)
    if aliased:
        return _VIX_PHRASES[aliased]
    return ("normal_vix", "")


def _expiry_context(is_expiry_day: bool) -> Tuple[str, str]:
    if is_expiry_day:
        return ("expiry_day", "expiry-day TP 2R/3R applied")
    return ("normal_day", "")


def _sequence_context(daily_sl_count: int, daily_alert_count: int) -> Tuple[str, str]:
    if daily_alert_count == 0:
        return ("first_alert", "first alert of day")
    if daily_sl_count > 0:
        return ("after_sl", f"after {daily_sl_count} SL today — caution")
    return (
        f"alert_{daily_alert_count + 1}",
        f"{daily_alert_count + 1}th alert of day",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_remark_and_tags(snapshot: dict, context: dict) -> Tuple[str, str]:
    """Build the entry-time bot_remark and bot_tags.

    Args:
        snapshot: must contain ``option_close``, ``option_vwap``, ``rsi``,
            ``rsi_ma``, ``oi``, ``oi_ma``, ``volume``, ``volume_ma``,
            ``opt_above_vwap_pct``.
        context: must contain ``time_hhmm`` and optionally ``vix_regime``,
            ``is_expiry_day``, ``daily_sl_count``, ``daily_alert_count``.

    Returns:
        ``(bot_remark, bot_tags)``. The remark is human-readable
        ("5/5 strong — opt 8% above VWAP, RSI 67 healthy zone, ..."),
        the tags are comma-separated with no spaces ready for ML queries
        ("fresh_breakout,strong_rsi,strong_oi,...").
    """
    observations: list[str] = []
    tags: list[str] = []

    t, p = _vwap_zone(snapshot["opt_above_vwap_pct"])
    tags.append(t); observations.append(p)

    t, p = _rsi_zone(snapshot["rsi"])
    tags.append(t); observations.append(p)

    t, p = _oi_strength(snapshot["oi"], snapshot["oi_ma"])
    tags.append(t); observations.append(p)

    t, p = _volume_strength(snapshot["volume"], snapshot["volume_ma"])
    tags.append(t); observations.append(p)

    t, p = _time_zone(context["time_hhmm"])
    tags.append(t)
    if p:
        observations.append(p)

    t, p = _vix_context(context.get("vix_regime", "NORMAL"))
    tags.append(t)
    if p:
        observations.append(p)

    t, p = _expiry_context(context.get("is_expiry_day", False))
    tags.append(t)
    if p:
        observations.append(p)

    t, p = _sequence_context(
        context.get("daily_sl_count", 0),
        context.get("daily_alert_count", 0),
    )
    tags.append(t); observations.append(p)

    verdict = _verdict(snapshot)

    # Keep the first 4 indicator observations + 1 contextual observation
    # so the remark stays a tight ~25 words.
    primary = observations[:4]
    secondary = [o for o in observations[4:] if o][:1]

    remark = f"{verdict} — " + ", ".join(primary + secondary) + "."
    return remark, ",".join(tags)


def _verdict(snapshot: dict) -> str:
    """Pick a quality prefix: strong / clean / borderline."""
    p = snapshot["opt_above_vwap_pct"]
    rsi = snapshot["rsi"]
    oi_ratio = (
        snapshot["oi"] / snapshot["oi_ma"]
        if snapshot["oi_ma"] > 0
        else 1.0
    )
    vol_ratio = (
        snapshot["volume"] / snapshot["volume_ma"]
        if snapshot["volume_ma"] > 0
        else 1.0
    )

    strong = (
        p < 15 and 60 <= rsi < 75 and oi_ratio < 0.85 and vol_ratio > 1.5
    )
    if strong:
        return "5/5 strong"

    marginal = (
        rsi < 55 or oi_ratio > 0.93 or vol_ratio < 1.2 or p > 22
    )
    if marginal:
        return "5/5 borderline"

    return "5/5 clean"


def generate_outcome_remark(
    alert_data: dict,
    outcome: str,
    exit_price: float | None = None,
    pnl: float | None = None,
) -> str:
    """Generate the outcome remark after the user marks Order Status.

    Pure rule-based. The verbosity reflects alert quality (strong vs
    borderline) so two TP2 hits can read differently if their entries
    differed in setup quality.
    """
    bot_remark = alert_data.get("bot_remark", "") or ""
    is_strong = "strong" in bot_remark
    is_marginal = "borderline" in bot_remark

    exit_str = f"₹{exit_price:.2f}" if exit_price is not None else "exit"

    if outcome == "TP2_HIT":
        if is_strong:
            return (
                f"Held to TP2 ({exit_str}) — strong setup played out. "
                "2.5R captured."
            )
        return f"Held to TP2 ({exit_str}) — 2.5R captured. Outcome confirmed setup."
    if outcome == "TP1_HIT":
        return f"TP1 hit at {exit_str} — 1.5R captured. Reversed before TP2."
    if outcome == "SL_HIT":
        if is_strong:
            return f"SL hit at {exit_str} — unusual reversal on strong setup."
        if is_marginal:
            return f"SL hit at {exit_str} — marginal entry showed in outcome."
        return f"SL hit at {exit_str} — reversed quickly."
    if outcome == "WOULD_SKIP":
        return "Skipped post-review — your judgement overrode 5/5."
    if outcome == "PARTIAL":
        pnl_str = f"₹{pnl:.0f}" if pnl is not None else "n/a"
        return f"Partial exit — manual decision, P&L {pnl_str}."
    return ""


def telegram_short_remark(bot_remark: str) -> str:
    """Trim ``bot_remark`` to its verdict + 1–2 observations for Telegram.

    Designed for the "Insight:" line in the alert message. Output is
    typically 50–75 characters; never exceeds ~80.
    """
    if not bot_remark:
        return ""
    parts = bot_remark.split(" — ", 1)
    if len(parts) < 2:
        return bot_remark[:80]
    verdict, rest = parts
    rest_clean = rest.rstrip(".")
    obs = [o.strip() for o in rest_clean.split(",") if o.strip()]
    if len(obs) >= 2:
        return f"{verdict} — {obs[0]}, {obs[1]}"
    return f"{verdict} — {obs[0]}" if obs else verdict
