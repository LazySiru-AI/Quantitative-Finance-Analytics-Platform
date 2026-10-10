"""Frozen shapes for the multi-timeframe rule study.

Authored from `docs/research/timeframes/06-interface-contract.md`, which is the agreed boundary
between the service layer, the HTTP layer and the UI. Changing a field here changes three codebases
at once -- raise it rather than editing unilaterally.

The invariants in `RuleAccuracyCell` are enforced by validators rather than left to callers. The
central one: a cell that fails the sufficiency gate carries `None` in every statistic, so a caller
*cannot* render an ungated number by mistake. That is a correctness property of this study, not a
display preference -- the whole exercise is worthless if a 3-observation cell can show a percentage.
"""

from __future__ import annotations

import datetime as dt
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.db.duck import Interval
from app.market.models import Bar

__all__ = [
    "DEFAULT_COST_BPS",
    "FDR_ALPHA",
    "MIN_INDEPENDENT",
    "RESEARCH_UNIVERSE",
    "IndicatorSeries",
    "Regime",
    "RuleAccuracyCell",
    "Scope",
    "SignalTrace",
    "interval_minutes",
    "sector_of",
    "symbols_in",
]

Scope = Literal["symbol", "sector", "universe"]
Regime = Literal["all", "rising", "falling", "flat"]

#: The sufficiency gate, in *independent* (non-overlapping, rising-edge-deduplicated) observations.
#:
#: 20 sits between this codebase's own existing evidence grades -- `WEAK` at 8 and `SUGGESTIVE` at 30
#: in `app.rules.evidence` -- so a bare percentage here can never contradict a grade the same data
#: already carries elsewhere. Below 20 the binomial standard error exceeds ~15pp, wider than
#: essentially any real lift, which makes the number noise wearing a percentage sign.
MIN_INDEPENDENT: Final[int] = 20

#: Round-trip cost assumption in basis points. Overridable per request.
DEFAULT_COST_BPS: Final[float] = 5.0

#: Benjamini-Hochberg false-discovery rate. The grid is thousands of cells; without this, dozens
#: look significant by construction.
FDR_ALPHA: Final[float] = 0.10

#: Minutes of market time one bar of each interval represents.
#:
#: `1h` is 60 even though a session's last hourly bar is a 30-minute stub, and `4h` is 240 even
#: though the second bar of each session is a 2.5h remainder -- these are nominal bar sizes used to
#: convert a bar-native horizon into comparable calendar time, not exact durations. `1w` is 5
#: sessions. The irregularity is real and is surfaced to the user through `RuleAccuracyCell.warnings`
#: rather than smuggled into this table.
_INTERVAL_MINUTES: Final[dict[Interval, int]] = {
    Interval.FIVE_MIN: 5,
    Interval.FIFTEEN_MIN: 15,
    Interval.THIRTY_MIN: 30,
    Interval.HOUR: 60,
    Interval.FOUR_HOUR: 240,
    Interval.DAY: 390,
    Interval.WEEK: 1950,
}


def interval_minutes(interval: Interval) -> int:
    """Nominal minutes of market time in one bar of `interval`."""
    return _INTERVAL_MINUTES[interval]


#: The frozen research universe: 20 liquid names across eight sectors.
#:
#: Liquid so intraday bars are dense and spreads realistic; sector-spread so the per-sector view has
#: something to say. AMZN, NVDA, QQQ and SOXX already carry intraday history in the store.
RESEARCH_UNIVERSE: Final[tuple[tuple[str, str], ...]] = (
    ("SPY", "Broad Market"),
    ("QQQ", "Broad Market"),
    ("AAPL", "Technology"),
    ("MSFT", "Technology"),
    ("NVDA", "Technology"),
    ("AMD", "Technology"),
    ("SOXX", "Technology"),
    ("GOOGL", "Communication Services"),
    ("META", "Communication Services"),
    ("AMZN", "Consumer Discretionary"),
    ("TSLA", "Consumer Discretionary"),
    ("KO", "Consumer Staples"),
    ("WMT", "Consumer Staples"),
    ("JPM", "Financials"),
    ("BAC", "Financials"),
    ("JNJ", "Health Care"),
    ("UNH", "Health Care"),
    ("XOM", "Energy"),
    ("CVX", "Energy"),
    ("CAT", "Industrials"),
)

_SECTOR_BY_SYMBOL: Final[dict[str, str]] = {symbol: sector for symbol, sector in RESEARCH_UNIVERSE}


def sector_of(symbol: str) -> str | None:
    """Sector label for a universe symbol, or `None` if it is not in the research universe."""
    return _SECTOR_BY_SYMBOL.get(symbol.upper())


def symbols_in(sector: str) -> tuple[str, ...]:
    """Universe symbols belonging to `sector`, in universe order."""
    return tuple(sym for sym, sec in RESEARCH_UNIVERSE if sec == sector)


class IndicatorSeries(BaseModel):
    """One indicator's values aligned to a bar window, matching the frontend's existing shape.

    Mirrors `frontend/src/api/market.ts`'s `IndicatorSeries` field-for-field so `Chart.tsx` can
    render it with no adapter. `null` marks the warmup region and must stay `null`: coerced to 0 a
    Bollinger band collapses onto the axis and reads as a crash rather than as missing data.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    name: str
    title: str
    pane: Literal["price", "oscillator"]
    columns: dict[str, list[float | None]]
    warmup: int


class RuleAccuracyCell(BaseModel):
    """One rule, one interval, one scope, one horizon.

    `lift` is the headline. `hit_rate` alone is not interpretable: in a rising window a zero-skill
    rule's hit rate tracks market drift and looks excellent, while its lift stays near zero in every
    regime. The UI contract requires `hit_rate` to be shown only beside its `base_rate`.
    """

    model_config = ConfigDict(frozen=True)

    # identity
    rule_id: str
    interval: Interval
    scope: Scope
    scope_key: str
    horizon_bars: int
    horizon_minutes: int
    horizon_label: str

    # sample
    n_raw: int
    n_episodes: int
    n_independent: int
    sufficient: bool

    # measurement
    hit_rate: float | None = None
    base_rate: float | None = None
    lift: float | None = None
    lift_ci_low: float | None = None
    lift_ci_high: float | None = None
    median_return: float | None = None
    baseline_median_return: float | None = None

    # significance
    p_value: float | None = None
    q_value: float | None = None

    # costs
    cost_bps_assumed: float = DEFAULT_COST_BPS
    cost_adjusted_edge: float | None = None

    # provenance
    regime: Regime = "all"
    first_bar: dt.datetime
    last_bar: dt.datetime
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_invariants(self) -> RuleAccuracyCell:
        if not (self.n_independent <= self.n_episodes <= self.n_raw):
            raise ValueError(
                f"sample counts must narrow: n_independent({self.n_independent}) <= "
                f"n_episodes({self.n_episodes}) <= n_raw({self.n_raw})"
            )

        gated = (
            self.hit_rate,
            self.base_rate,
            self.lift,
            self.lift_ci_low,
            self.lift_ci_high,
            self.p_value,
            self.q_value,
            self.cost_adjusted_edge,
        )
        if not self.sufficient and any(value is not None for value in gated):
            raise ValueError(
                "an insufficient cell must carry None in every statistic -- emitting a number the "
                "gate rejected is the failure mode this study exists to avoid"
            )

        if self.sufficient != (self.n_independent >= MIN_INDEPENDENT):
            raise ValueError(
                f"sufficient={self.sufficient} contradicts n_independent={self.n_independent} "
                f"against MIN_INDEPENDENT={MIN_INDEPENDENT}"
            )

        if (
            self.hit_rate is not None
            and self.base_rate is not None
            and self.lift is not None
            and abs(self.lift - (self.hit_rate - self.base_rate)) > 1e-9
        ):
            raise ValueError(
                f"lift({self.lift}) must equal hit_rate({self.hit_rate}) - base_rate({self.base_rate})"
            )

        return self


class SignalTrace(BaseModel):
    """Everything the drill-down chart needs for one rule on one symbol at one interval.

    `fired_at` carries **rising edges only** -- the same de-duplication the accuracy path applies.
    Marking every True bar would draw 77 markers a day for `bb_squeeze` and visibly contradict the
    `n_episodes` the table reports for the same cell.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    interval: Interval
    rule_id: str
    expression: str
    bars: list[Bar]
    indicators: list[IndicatorSeries]
    fired_at: list[dt.datetime]
    warmup_until: dt.datetime | None = None
