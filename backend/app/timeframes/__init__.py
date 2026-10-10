"""Multi-timeframe rule research: how well does each decision rule work at each candle size?

This package deliberately bypasses `app.backtest.strategy` / `app.backtest.metrics` and never reads
`BARS_PER_YEAR`. It answers a narrower question than a backtest does -- "when this rule fired, did
price go the way the rule implied?" -- and that question needs only bar-position arithmetic, which
`app.rules.evidence` and `app.backtest.forward` already do correctly at any interval.

Staying off the annualization path is the point, not an accident. Annualizing a 5-minute-bar Sharpe
by sqrt(19656) produces a number with a plausible magnitude and no defensible meaning, and the live
paperdesk and tournament stacks run daily-only through code this package never touches -- so a
research sweep cannot regress them.

See `docs/research/timeframes/` for the findings this package implements, and `06-interface-contract.md`
for the frozen shapes.
"""

from app.timeframes.models import (
    DEFAULT_COST_BPS,
    FDR_ALPHA,
    MIN_INDEPENDENT,
    RESEARCH_UNIVERSE,
    RuleAccuracyCell,
    SignalTrace,
    interval_minutes,
    sector_of,
    symbols_in,
)

__all__ = [
    "DEFAULT_COST_BPS",
    "FDR_ALPHA",
    "MIN_INDEPENDENT",
    "RESEARCH_UNIVERSE",
    "RuleAccuracyCell",
    "SignalTrace",
    "interval_minutes",
    "sector_of",
    "symbols_in",
]
