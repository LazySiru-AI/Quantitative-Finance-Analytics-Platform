"""Confirmed swing pivots, and oscillator values sampled at them -- the primitive divergence needs.

**Why this module exists.** Every other indicator in the registry answers "what is this series doing
now". Divergence asks something the rest of the DSL cannot phrase: *how does now compare to the last
time price turned?* That requires locating a prior turning point and reading a second series at that
point. Without it, "price makes a lower low while MACD makes a higher low" -- the note's own claim,
and the standard textbook definition -- is not expressible, and the 2026-08-11 strategy study had to
record it as untestable.

**A swing low is not a rolling minimum.** ``low.rolling(n).min()`` is trailing and always available;
a swing low is a *local* minimum, which by construction cannot be recognised until enough bars have
formed on its right-hand side. Bar ``j`` is a swing low when ``low[j]`` is the minimum of the
``2*lookback + 1`` bars centred on it. That definition looks forward, so the value is published
**``lookback`` bars later, at ``j + lookback``** -- the first bar at which a live observer could have
known it. Everything in this module hangs off that lag.

**The lag is the whole correctness argument.** A naive implementation centres a rolling window and
publishes the result at ``j``, which reads ``lookback`` bars of the future and produces a backtest
that buys every bottom. :mod:`app.backtest.guards` would catch it -- the tail-truncation check
recomputes on ``bars[:k]`` and compares -- and this module is written to pass that check exactly,
with no tolerance, like every other registry entry. The value at bar ``t`` depends only on pivots
``j`` with ``j + lookback <= t``, whose detection window ``[j - lookback, j + lookback]`` therefore
lies entirely at or before ``t``. Truncating anything after ``t`` cannot move it.

**What is published between pivots.** The most recently confirmed pivot, held forward. A rule asking
``low < swing_low(5)`` is asking "is price now under the last confirmed swing low", which is the
question a divergence rule needs, and it stays answerable on every bar rather than only on the rare
bar a pivot confirms.

**Ties are pivots too.** A flat bottom where several adjacent bars share the minimum yields several
pivots, each confirmed on its own bar, and the forward fill keeps the latest. Demanding strict
inequality would silently drop every double bottom -- one of the patterns the note explicitly names
(p.1, "Triangular, double bottom").

**Companion sampling is anchored to *price* pivots, not to the oscillator's own.** ``rsi_at_swing``
and ``macd_at_swing`` report what the oscillator read at the bar price turned. That is the textbook
construction: divergence compares an oscillator across two price extremes, not across two oscillator
extremes, which would be a different (and much weaker) statement. It also keeps the two halves of a
divergence expression referring to the same instant in time, which is what makes
``low < swing_low(5) and rsi(14) > rsi_at_swing_low(14,5)`` mean what it appears to mean.
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
)
from app.indicators.momentum import RSI_SPEC, rsi
from app.indicators.trend import MACD_SPEC, macd

__all__ = [
    "MACD_AT_SWING_SPEC",
    "RSI_AT_SWING_SPEC",
    "SWING_SPEC",
    "confirmed_pivots",
    "macd_at_swing",
    "rsi_at_swing",
    "swing",
]

_LOOKBACK = ParamSpec(
    name="lookback", kind=ParamKind.INT, default=5, minimum=1, maximum=250, label="Lookback"
)
_PERIOD = ParamSpec(
    name="period", kind=ParamKind.INT, default=14, minimum=2, maximum=500, label="Period"
)
_FAST = ParamSpec(name="fast", kind=ParamKind.INT, default=12, minimum=1, maximum=500, label="Fast")
_SLOW = ParamSpec(name="slow", kind=ParamKind.INT, default=26, minimum=2, maximum=500, label="Slow")
_SIGNAL = ParamSpec(
    name="signal", kind=ParamKind.INT, default=9, minimum=1, maximum=500, label="Signal"
)


def confirmed_pivots(
    series: pd.Series, *, lookback: int, high: bool, companion: pd.Series | None = None
) -> pd.Series:
    """The most recently confirmed pivot of ``series``, held forward, published with its lag.

    ``high=True`` finds local maxima, ``False`` local minima. When ``companion`` is given, the value
    published is ``companion`` sampled at the pivot bar rather than ``series`` itself -- that is what
    makes an oscillator readable at a price turning point.

    The returned series is aligned to ``series.index`` and is ``NaN`` until the first pivot confirms.
    """
    values = series.to_numpy(dtype="float64")
    n = values.size
    out = np.full(n, np.nan, dtype="float64")
    if n == 0 or lookback < 1:
        return pd.Series(out, index=series.index, dtype="float64")

    window = 2 * lookback + 1
    rolled = series.rolling(window, center=True).max() if high else series.rolling(window, center=True).min()
    # `rolling(center=True)` leaves NaN at both edges (too few bars on one side), and NaN never
    # compares equal, so edge bars are simply not pivots -- which is correct, not a special case:
    # a bar without `lookback` neighbours on both sides has not been shown to be a local extremum.
    is_pivot = (series == rolled).to_numpy(dtype=bool) & np.isfinite(values)

    source = values if companion is None else companion.to_numpy(dtype="float64")

    # Publish each pivot at `j + lookback`, the first bar it could have been known on, then hold it
    # forward. Distinct pivots map to distinct publication bars, so no assignment overwrites another.
    pivot_positions = np.flatnonzero(is_pivot)
    publish_at = pivot_positions + lookback
    in_range = publish_at < n
    out[publish_at[in_range]] = source[pivot_positions[in_range]]

    result = pd.Series(out, index=series.index, dtype="float64").ffill()
    return result


def swing(bars: pd.DataFrame, /, *, lookback: int) -> pd.DataFrame:
    """Price at the last confirmed swing high (of ``high``) and swing low (of ``low``)."""
    base = column_name("swing", [lookback])
    return pd.DataFrame(
        {
            f"{base}_high": confirmed_pivots(bars["high"], lookback=lookback, high=True),
            f"{base}_low": confirmed_pivots(bars["low"], lookback=lookback, high=False),
        },
        index=bars.index,
    )


def rsi_at_swing(bars: pd.DataFrame, /, *, period: int, lookback: int) -> pd.DataFrame:
    """RSI read at the bar of the last confirmed price swing high / swing low."""
    base = column_name("rsi_at_swing", [period, lookback])
    values = rsi(bars, period=period).iloc[:, 0]
    return pd.DataFrame(
        {
            f"{base}_high": confirmed_pivots(
                bars["high"], lookback=lookback, high=True, companion=values
            ),
            f"{base}_low": confirmed_pivots(
                bars["low"], lookback=lookback, high=False, companion=values
            ),
        },
        index=bars.index,
    )


def macd_at_swing(
    bars: pd.DataFrame, /, *, fast: int, slow: int, signal: int, lookback: int
) -> pd.DataFrame:
    """The MACD **line** read at the bar of the last confirmed price swing high / swing low.

    The line, not the histogram: divergence is conventionally read off the MACD line, and the
    histogram's own sign changes are already reachable through ``macd_hist``.
    """
    base = column_name("macd_at_swing", [fast, slow, signal, lookback])
    line = macd(bars, fast=fast, slow=slow, signal=signal)[column_name("macd", [fast, slow, signal]) + "_macd"]
    return pd.DataFrame(
        {
            f"{base}_high": confirmed_pivots(
                bars["high"], lookback=lookback, high=True, companion=line
            ),
            f"{base}_low": confirmed_pivots(
                bars["low"], lookback=lookback, high=False, companion=line
            ),
        },
        index=bars.index,
    )


def _swing_warmup(params: Mapping[str, Any]) -> int:
    """``2 * lookback``: the earliest bar that can be a pivot is ``lookback`` (it needs that many
    neighbours on its left), and it is not published until ``lookback`` bars after that."""
    return 2 * int(params["lookback"])


def _companion_warmup(source_warmup: int, lookback: int) -> int:
    """A pivot is only usable once the sampled series has a value there, so the first usable pivot
    sits at ``max(lookback, source_warmup)`` and publishes ``lookback`` bars later."""
    return max(int(lookback), int(source_warmup)) + int(lookback)


def _rsi_at_swing_warmup(params: Mapping[str, Any]) -> int:
    return _companion_warmup(RSI_SPEC.warmup({"period": params["period"]}), params["lookback"])


def _macd_at_swing_warmup(params: Mapping[str, Any]) -> int:
    return _companion_warmup(
        MACD_SPEC.warmup(
            {"fast": params["fast"], "slow": params["slow"], "signal": params["signal"]}
        ),
        params["lookback"],
    )


def _swing_fn(bars: pd.DataFrame, /, **params: Any) -> pd.DataFrame:
    return swing(bars, lookback=params["lookback"])


def _rsi_at_swing_fn(bars: pd.DataFrame, /, **params: Any) -> pd.DataFrame:
    return rsi_at_swing(bars, period=params["period"], lookback=params["lookback"])


def _macd_at_swing_fn(bars: pd.DataFrame, /, **params: Any) -> pd.DataFrame:
    return macd_at_swing(
        bars,
        fast=params["fast"],
        slow=params["slow"],
        signal=params["signal"],
        lookback=params["lookback"],
    )


SWING_SPEC = IndicatorSpec(
    name="swing",
    title="Confirmed Swing Pivot",
    fn=_swing_fn,
    params=(_LOOKBACK,),
    outputs=("high", "low"),
    pane=Pane.PRICE,
    warmup=_swing_warmup,
    data_dependent_warmup=True,
    description="Price at the last confirmed swing high/low -- a local extremum over `lookback`"
    " bars either side, published `lookback` bars after it forms.",
)

RSI_AT_SWING_SPEC = IndicatorSpec(
    name="rsi_at_swing",
    title="RSI at Swing Pivot",
    fn=_rsi_at_swing_fn,
    params=(_PERIOD, _LOOKBACK),
    outputs=("high", "low"),
    pane=Pane.OSCILLATOR,
    warmup=_rsi_at_swing_warmup,
    data_dependent_warmup=True,
    description="RSI read at the bar of the last confirmed price swing high/low -- the second half"
    " of a divergence comparison.",
)

MACD_AT_SWING_SPEC = IndicatorSpec(
    name="macd_at_swing",
    title="MACD at Swing Pivot",
    fn=_macd_at_swing_fn,
    params=(_FAST, _SLOW, _SIGNAL, _LOOKBACK),
    outputs=("high", "low"),
    pane=Pane.OSCILLATOR,
    warmup=_macd_at_swing_warmup,
    data_dependent_warmup=True,
    description="MACD line read at the bar of the last confirmed price swing high/low -- the second"
    " half of a divergence comparison.",
)
