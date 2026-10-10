"""Momentum indicators: RSI.

Wilder's original smoothing, not a simple rolling mean of gains and losses, and not a naive
``.ewm(alpha=1/period, adjust=False)`` either -- that seeds its recursion from the first single
gain/loss observation, while Wilder's definition seeds the first average as the **simple mean of
the first `period` gains/losses**, then recurses from there. The two seedings converge eventually,
but "eventually" is dozens of bars away and tens of RSI points off in the meantime (see
:func:`app.indicators.base.wilder_smooth`, which implements the correct seeding this function
uses) -- wrong by the difference between "neutral" and "approaching overbought" on real data. This
is what every charting platform means by "RSI(14)"; a simple-mean RSI is a different, less common
indicator that happens to share the name and the 0-100 range, so a chart drawn from one and a rule
evaluated against the other would disagree on exactly the crossings a momentum rule cares about.

A flat stretch (no gains, or no losses) is not an error case to leave as ``NaN``/``inf`` -- it is
the indicator's own boundary condition, and Wilder's formula degenerates cleanly there once handled
explicitly: no losses at all means nothing but strength, RSI = 100; no gains at all means RSI = 0.

A ``close`` that is itself ``NaN`` is re-masked to ``NaN`` in the output rather than left to
whatever the smoothing's "hold the previous state" behavior would otherwise produce there --
see the re-mask at the bottom of :func:`rsi`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from app.indicators.base import (
    IndicatorSpec,
    Pane,
    ParamKind,
    ParamSpec,
    column_name,
    wilder_smooth,
)

__all__ = ["RSI_SPEC", "rsi"]

_PERIOD = ParamSpec(
    name="period", kind=ParamKind.INT, default=14, minimum=2, maximum=500, label="Period"
)


def rsi(bars: pd.DataFrame, /, *, period: int) -> pd.DataFrame:
    """Wilder's RSI of ``close``."""
    col = column_name("rsi", [period])
    close = bars["close"]
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    # `delta`, and therefore `gain`/`loss`, carries one leading NaN of its own (row 0 has no prior
    # close to diff against) -- that is not one of the `period` real observations Wilder's seed
    # averages over, so it is dropped before smoothing rather than fed in as a NaN seed input.
    # `wilder_smooth` then re-indexes onto `gain.iloc[1:]`'s index, and reindexing the result back
    # onto `bars.index` below reintroduces row 0 as NaN.
    avg_gain = wilder_smooth(gain.iloc[1:], period).reindex(bars.index)
    avg_loss = wilder_smooth(loss.iloc[1:], period).reindex(bars.index)

    result = pd.Series(np.nan, index=bars.index, dtype="float64")
    ready = avg_gain.notna() & avg_loss.notna()
    # A window with no losses is RSI = 100 and one with no gains is 0; both are well defined, and
    # both are pinned by tests against strictly monotonic series.
    #
    # A window with **neither** -- a perfectly flat close -- is not. RS is 0/0 there. This used to
    # resolve to 100 by letting the "no losses" branch win the tie, which reads as "maximally
    # overbought" about an instrument that has not moved at all, and would fire any `rsi(14) > 70`
    # rule on a halted or untraded series. `docs/reports/phase-5.md` recorded it as a known
    # judgement call to revisit once Phase 6 attached rules to thresholds; Phase 6 shipped and it
    # was not revisited. It also claimed the behaviour was pinned by a test, and no test covered it.
    #
    # NaN is the answer that matches what this codebase does everywhere else with a figure it cannot
    # support: an undefined RSI propagates as undefined, and a rule referencing it does not fire,
    # rather than firing on a fabricated extreme.
    flat = ready & (avg_gain == 0) & (avg_loss == 0)
    no_loss = ready & ~flat & (avg_loss == 0)
    no_gain = ready & ~flat & ~no_loss & (avg_gain == 0)
    normal = ready & ~flat & ~no_loss & ~no_gain

    result[no_loss] = 100.0
    result[no_gain] = 0.0
    rs = avg_gain[normal] / avg_loss[normal]
    result[normal] = 100 - 100 / (1 + rs)

    # A bar whose `delta` is itself NaN (because that bar's `close`, or the previous bar's, was
    # missing) must not surface a value here -- `wilder_smooth`'s underlying `ewm` holds the
    # previous average forward across a NaN gain/loss rather than emitting NaN there, which would
    # otherwise repeat (or, worse, drift from) the last valid RSI instead of admitting the input
    # was missing. `close.diff()` makes one missing close NaN at *two* positions (the bar itself
    # and the one after it, since both differences touch it), and both must be re-masked.
    result[delta.isna()] = np.nan

    return pd.DataFrame({col: result}, index=bars.index)


def _rsi_warmup(params: Mapping[str, Any]) -> int:
    """``period``, not ``period - 1``.

    ``close.diff()`` introduces one leading NaN of its own (there is no prior bar for the first
    row), and :func:`~app.indicators.base.wilder_smooth`'s seed -- the simple mean of the first
    `period` gain/loss observations -- settles ``period - 1`` bars after that, at the same
    NaN-count composition as :func:`app.indicators.trend._macd_warmup`. ``1 + (period - 1) ==
    period``.
    """
    return int(params["period"])


def _rsi_fn(bars: pd.DataFrame, /, **params: Any) -> pd.DataFrame:
    """Adapts ``rsi``'s named-keyword signature to the registry's ``**params: Any`` calling
    convention -- see ``app.indicators.trend._sma_fn`` for why this seam exists in every module
    here rather than as a single shared helper in ``base.py``."""
    return rsi(bars, period=params["period"])


RSI_SPEC = IndicatorSpec(
    name="rsi",
    title="Relative Strength Index",
    fn=_rsi_fn,
    params=(_PERIOD,),
    pane=Pane.OSCILLATOR,
    warmup=_rsi_warmup,
    description="Wilder-smoothed Relative Strength Index of close over `period` bars.",
)
