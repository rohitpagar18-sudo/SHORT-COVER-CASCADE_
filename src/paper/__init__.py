"""Phase 5D — Paper-trade tracking & first-alert selection layer.

A *read-only* layer over the alert-only bot. Episode-collapses re-fires
into one paper trade, runs a deterministic selection gate (§13/§14
caps), then calls the Phase 5B-A exit kernel on each TAKEN
representative to compute virtual outcomes. No order placement, no
live-scan side effects. Replaced by broker callbacks once Phase 8 lands.
"""

from src.paper.episodes import (
    Episode,
    derive_alert_id,
    collapse_into_episodes,
)
from src.paper.selector import SelectionResult, select_paper_trades
from src.paper.outcome import PaperOutcome, compute_paper_outcome

__all__ = [
    "Episode",
    "derive_alert_id",
    "collapse_into_episodes",
    "SelectionResult",
    "select_paper_trades",
    "PaperOutcome",
    "compute_paper_outcome",
]
