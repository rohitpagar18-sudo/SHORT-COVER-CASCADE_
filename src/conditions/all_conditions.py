"""Combined orchestrator for all five entry conditions.

``check_all_conditions`` runs C0–C4 against a single option snapshot
and spot context, returning an ``AllConditionsResult`` that lists each
sub-result with its reason string. The orchestrator deliberately runs
all five conditions (no short-circuit) so logs can show the full
combination that failed.

Phase 5.2: ``AllConditionsResult`` also carries the C1 distance
``opt_above_vwap_pct`` so the orchestrator can log it on every scan
record and decide whether to write an extended-zone event.

The result object is structured for direct serialisation into the
signals log in Phase 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.conditions.c0_spot_trend import check_c0
from src.conditions.c1_option_price_vwap import check_c1
from src.conditions.c2_oi_below_ma import check_c2
from src.conditions.c3_rsi_momentum import check_c3
from src.conditions.c4_volume import check_c4
from src.indicators.calculator import IndicatorSnapshot


@dataclass
class ConditionResult:
    """One condition's outcome plus a human-readable reason."""

    name: str
    passed: bool
    reason: str


@dataclass
class AllConditionsResult:
    """Combined outcome of C0–C4 for a single closed candle."""

    all_passed: bool
    results: list[ConditionResult] = field(default_factory=list)
    opt_above_vwap_pct: float = 0.0  # Phase 5.2: C1 distance for logging.

    def failed_conditions(self) -> list[str]:
        """Names of conditions that failed, in C0–C4 order."""
        return [r.name for r in self.results if not r.passed]

    def passed_conditions(self) -> list[str]:
        """Names of conditions that passed, in C0–C4 order."""
        return [r.name for r in self.results if r.passed]

    def short_summary(self) -> str:
        """``C0 ✓ C1 ✓ C2 ✗ C3 ✓ C4 ✓`` style one-liner."""
        return " ".join(
            f"{r.name} {'✓' if r.passed else '✗'}" for r in self.results
        )

    def by_name(self, name: str) -> ConditionResult | None:
        """Look up a sub-result by name ('C0' .. 'C4'). Returns None if absent."""
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
) -> AllConditionsResult:
    """Run all five conditions on a single closed candle.

    Args:
        option_snapshot: IndicatorSnapshot computed from the option's
            5-minute candles.
        spot_close: latest spot index close (NIFTY / BANKNIFTY).
        spot_vwap: spot session VWAP.
        option_type: ``"CE"`` or ``"PE"``.
        config: ``AppConfig`` from ``src.config_loader``. Provides the
            ``conditions.c1_max_distance_pct`` (Phase 5.2) and
            ``conditions.c3_rsi_min`` / ``conditions.c3_rsi_max``
            thresholds — never hardcoded.

    Returns:
        ``AllConditionsResult`` listing each C0–C4 outcome plus the
        C1 distance pct. We do NOT short-circuit on the first failure:
        logs from Phase 5 need to show the exact combination that failed.
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

    all_passed = all(r.passed for r in results)
    return AllConditionsResult(
        all_passed=all_passed,
        results=results,
        opt_above_vwap_pct=opt_above_vwap_pct,
    )
