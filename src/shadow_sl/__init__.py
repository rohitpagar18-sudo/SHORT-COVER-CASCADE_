"""Shadow stop-loss laboratory — read-only, experimental.

This package is intentionally ISOLATED from the live pipeline:

  * It never imports from ``src.paper.*`` or ``src.dashboard.*``.
  * It never writes to ``logs/paper_trades.jsonl``, the monthly Parquet
    files, or the Excel workbooks.
  * It only reads ``logs/alerts.jsonl`` and the existing
    ``data/replay_cache/<date>/<sym>_<strike>_<TYPE>.parquet`` cache.
  * Its single output is ``logs/shadow_sl.jsonl``.

Different SL strategies (sma19 baseline, atr_initial, chandelier,
chandelier_time) plug into a small registry. The candle walk lives in
``engine.py`` — not in the live Phase 5B-A kernel. The live kernel is
the source of truth for real and paper outcomes; this module is
purely for shadow comparison.
"""

from src.shadow_sl.engine import REGISTRY, register, walk_candles  # noqa: F401
from src.shadow_sl import methods as _methods  # noqa: F401  -- side-effect: registers methods
