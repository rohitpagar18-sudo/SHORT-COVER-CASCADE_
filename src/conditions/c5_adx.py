"""C5 — ADX Trend Filter (Phase 6.1, SHADOW MODE).

Wilder ADX(14) measures trend strength on the underlying spot index.
Higher ADX means a more directional market. +DI/-DI describe whether the
direction is up or down. The full check is:

    di_aligned = (+DI > -DI) for CE, (-DI > +DI) for PE
    adx_rising = adx > adx_prev          (the real ignition filter)
    adx_ok     = adx >= adx_min

All three default ON but each leg is toggleable. ``check_c5_adx`` is a
pure function: heavy ADX math lives in ``src/indicators/adx.py``; this
module only renders the pass/fail decision.

Phase 6.1 SHADOW MODE: even when this returns ``passed=False``, the
orchestrator does NOT block the alert — C5's ``gating`` flag (set in
``check_all_conditions``) is False during shadow validation. Only the
result string and the structured ``fields`` dict get logged / shown.
"""

from __future__ import annotations


def check_c5_adx(
    adx: float,
    adx_prev: float,
    di_plus: float,
    di_minus: float,
    option_type: str,
    cfg,
) -> tuple[bool, str, dict]:
    """Evaluate the ADX trend filter for one strike.

    Args:
        adx: ADX(period) at the latest closed candle.
        adx_prev: ADX(period) at the previous closed candle (for the
            ``require_rising`` check).
        di_plus: +DI at the latest candle.
        di_minus: -DI at the latest candle.
        option_type: ``"CE"`` or ``"PE"``.
        cfg: ``C5AdxConfig`` from ``src.config_loader``. Reads
            ``adx_min``, ``require_rising``, ``use_di_alignment``.

    Returns:
        ``(passed, reason, fields)`` where ``fields`` is a flat dict
        ``{adx, adx_prev, di_plus, di_minus, di_aligned}`` ready to merge
        into the signals.jsonl record. ``reason`` is always populated —
        on pass it summarises which legs were satisfied; on fail it names
        the leg that blocked.
    """
    if option_type == "CE":
        di_aligned = di_plus > di_minus
    elif option_type == "PE":
        di_aligned = di_minus > di_plus
    else:
        # Defensive — orchestrator only passes CE/PE, but keep this safe.
        return False, (
            f"C5 ERROR: invalid option_type '{option_type}'"
        ), {
            "adx": adx, "adx_prev": adx_prev,
            "di_plus": di_plus, "di_minus": di_minus,
            "di_aligned": False,
        }

    adx_rising = adx > adx_prev
    adx_min = float(cfg.adx_min)
    adx_ok = adx >= adx_min

    require_di = bool(cfg.use_di_alignment)
    require_rise = bool(cfg.require_rising)

    di_leg_pass = di_aligned or not require_di
    rise_leg_pass = adx_rising or not require_rise

    passed = di_leg_pass and rise_leg_pass and adx_ok

    arrow = "↑" if adx_rising else "↓"
    di_str = (
        f"{'+DI>−DI' if option_type == 'CE' else '−DI>+DI'} "
        f"({di_plus:.1f} vs {di_minus:.1f})"
    )

    if passed:
        reason = (
            f"C5 PASS: ADX {adx:.1f} {arrow} "
            f"(>= {adx_min:.0f}), {di_str}"
        )
    else:
        # Build a precise failure reason — first leg that blocked wins.
        if not adx_ok:
            reason = (
                f"C5 FAIL: ADX {adx:.1f} {arrow} below {adx_min:.0f}"
            )
        elif require_rise and not adx_rising:
            reason = (
                f"C5 FAIL: ADX flat/falling ({adx:.1f} <= prev {adx_prev:.1f})"
            )
        elif require_di and not di_aligned:
            reason = (
                f"C5 FAIL: DI misaligned for {option_type} "
                f"(+DI {di_plus:.1f}, −DI {di_minus:.1f})"
            )
        else:
            # Should be unreachable but keep an honest fallback.
            reason = (
                f"C5 FAIL: ADX {adx:.1f}, +DI {di_plus:.1f}, −DI {di_minus:.1f}"
            )

    fields = {
        "adx": float(adx),
        "adx_prev": float(adx_prev),
        "di_plus": float(di_plus),
        "di_minus": float(di_minus),
        "di_aligned": bool(di_aligned),
    }
    return passed, reason, fields
