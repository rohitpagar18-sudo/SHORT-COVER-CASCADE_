"""Combined orchestrator for the entry conditions.

``check_all_conditions`` runs C0–C4 (and optionally a shadow C5) against
a single option snapshot and spot context, returning an
``AllConditionsResult`` that lists each sub-result with its reason string.
The orchestrator deliberately runs every condition (no short-circuit) so
logs can show the full combination that failed.

Phase 5.2: ``AllConditionsResult`` also carries the C1 distance
``opt_above_vwap_pct`` so the orchestrator can log it on every scan
record and decide whether to write an extended-zone event.

Phase 6.1: C5 ADX trend filter joins the result set in SHADOW MODE.
Critical: each ``ConditionResult`` now carries a ``gating`` flag and
``all_passed`` is computed only over results with ``gating=True``.
Existing C0–C4 entries default to ``gating=True`` so today's trigger
behaviour is identical. Shadow C5 sets ``gating=False``; flipping
``config.conditions.c5_adx.gating`` ON later turns C5 into a real
blocker without touching this code.

The result object is structured for direct serialisation into the
signals log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.conditions.c0_spot_trend import check_c0
from src.conditions.c1_option_price_vwap import check_c1
from src.conditions.c2_oi_below_ma import check_c2
from src.conditions.c3_rsi_momentum import check_c3
from src.conditions.c4_volume import check_c4
from src.conditions.c5_adx import check_c5_adx
from src.indicators.calculator import IndicatorSnapshot


@dataclass
class ConditionResult:
    """One condition's outcome plus a human-readable reason.

    ``gating`` controls whether this result counts toward ``all_passed``.
    Default True keeps C0–C4 behaviour identical to pre-Phase-6.1. Shadow
    C5 is appended with ``gating=False`` so it cannot block an alert.
    """

    name: str
    passed: bool
    reason: str
    gating: bool = True


@dataclass
class AllConditionsResult:
    """Combined outcome of all conditions for a single closed candle."""

    all_passed: bool
    results: list[ConditionResult] = field(default_factory=list)
    opt_above_vwap_pct: float = 0.0  # Phase 5.2: C1 distance for logging.
    # Phase 6.1: structured C5 fields (None when C5 is disabled).
    c5_fields: Optional[dict] = None

    def failed_conditions(self) -> list[str]:
        """Names of conditions that failed, in declaration order."""
        return [r.name for r in self.results if not r.passed]

    def passed_conditions(self) -> list[str]:
        """Names of conditions that passed, in declaration order."""
        return [r.name for r in self.results if r.passed]

    def short_summary(self) -> str:
        """``C0 ✓ C1 ✓ C2 ✗ C3 ✓ C4 ✓`` style one-liner."""
        return " ".join(
            f"{r.name} {'✓' if r.passed else '✗'}" for r in self.results
        )

    def by_name(self, name: str) -> ConditionResult | None:
        """Look up a sub-result by name. Returns None if absent."""
        for r in self.results:
            if r.name == name:
                return r
        return None


def _c1_max_distance(config) -> float:
    """Phase 5.2: prefer config.conditions.c1_max_distance_pct (new),
    fall back to config.strike.late_entry_threshold_percent (legacy).
    """
    conditions = getattr(config, "conditions", None)
    if conditions is not None:
        val = getattr(conditions, "c1_max_distance_pct", None)
        if val is not None:
            return float(val)
    return float(config.strike.late_entry_threshold_percent)


def check_all_conditions(
    option_snapshot: IndicatorSnapshot,
    spot_close: float,
    spot_vwap: float,
    option_type: str,
    config,
    c5_inputs: Optional[dict] = None,
) -> AllConditionsResult:
    """Run all conditions on a single closed candle.

    Args:
        option_snapshot: IndicatorSnapshot computed from the option's
            5-minute candles.
        spot_close: latest spot index close (NIFTY / BANKNIFTY).
        spot_vwap: spot session VWAP.
        option_type: ``"CE"`` or ``"PE"``.
        config: ``AppConfig`` from ``src.config_loader``.
        c5_inputs: Phase 6.1, optional. When ``config.conditions.c5_adx.enabled``
            is True, the orchestrator passes a dict with one of:
              - ``{"ok": True, "adx": ..., "adx_prev": ..., "di_plus": ..., "di_minus": ...}``
              - ``{"ok": False, "reason": "<insufficient/error reason>"}``
            When the config flag is False OR ``c5_inputs`` is None, C5 is
            ABSENT entirely (no result, no fields, no alert line). This
            differs from C0's "SKIPPED-as-pass" behaviour by design.

    Returns:
        ``AllConditionsResult`` listing each outcome. ``all_passed`` is
        computed over results whose ``gating=True``. C5 in shadow mode is
        ``gating=False`` and therefore display/log-only.

        We do NOT short-circuit: logs must show the exact combination
        that failed.
    """
    results: list[ConditionResult] = []

    c0_enabled = getattr(
        getattr(config, "conditions", None),
        "c0_spot_trend_filter_enabled",
        False,
    )
    if c0_enabled:
        ok, reason = check_c0(spot_close, spot_vwap, option_type)
        results.append(ConditionResult("C0", ok, reason))
    else:
        results.append(ConditionResult(
            "C0", True,
            "C0 SKIPPED: spot trend filter disabled in config",
        ))

    c1_max = _c1_max_distance(config)
    c1_ok, c1_reason, opt_above_vwap_pct = check_c1(option_snapshot, c1_max)
    results.append(ConditionResult("C1", c1_ok, c1_reason))

    ok, reason = check_c2(option_snapshot)
    results.append(ConditionResult("C2", ok, reason))

    ok, reason = check_c3(
        option_snapshot,
        config.conditions.c3_rsi_min,
        config.conditions.c3_rsi_max,
    )
    results.append(ConditionResult("C3", ok, reason))

    ok, reason = check_c4(option_snapshot)
    results.append(ConditionResult("C4", ok, reason))

    # Phase 6.1 — C5 ADX trend filter (shadow or gating).
    c5_cfg = getattr(getattr(config, "conditions", None), "c5_adx", None)
    c5_enabled = bool(getattr(c5_cfg, "enabled", False))
    c5_gating = bool(getattr(c5_cfg, "gating", False))
    c5_fields: Optional[dict] = None

    if c5_enabled:
        if c5_inputs is None or not c5_inputs.get("ok", False):
            reason_msg = (
                c5_inputs.get("reason", "C5 inputs missing")
                if isinstance(c5_inputs, dict) else "C5 inputs missing"
            )
            results.append(ConditionResult(
                "C5", False,
                f"C5 FAIL: insufficient data ({reason_msg})",
                gating=c5_gating,
            ))
            c5_fields = {
                "adx": None, "adx_prev": None,
                "di_plus": None, "di_minus": None,
                "di_aligned": None,
            }
        else:
            passed, reason, fields = check_c5_adx(
                adx=float(c5_inputs["adx"]),
                adx_prev=float(c5_inputs["adx_prev"]),
                di_plus=float(c5_inputs["di_plus"]),
                di_minus=float(c5_inputs["di_minus"]),
                option_type=option_type,
                cfg=c5_cfg,
            )
            results.append(ConditionResult(
                "C5", passed, reason, gating=c5_gating,
            ))
            c5_fields = fields

    # all_passed only considers gating results. C5 in shadow mode
    # (gating=False) is excluded — it shows in logs/Telegram but never
    # blocks an alert. C0 SKIPPED stays in the gating set with passed=True
    # which preserves today's exact behaviour.
    all_passed = all(r.passed for r in results if r.gating)
    return AllConditionsResult(
        all_passed=all_passed,
        results=results,
        opt_above_vwap_pct=opt_above_vwap_pct,
        c5_fields=c5_fields,
    )
