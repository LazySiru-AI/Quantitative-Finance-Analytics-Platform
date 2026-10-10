"""Volatility indicators: Bollinger Bands, ATR.

**Bollinger's standard deviation is the population form, ``ddof=0``.** Pandas' ``.std()`` defaults
to the sample form, ``ddof=1``. Every charting platform -- TradingView, ThinkorSwim, the original
Bollinger convention itself -- uses ``ddof=0``. The two forms differ by a factor of
``sqrt(n / (n-1))``, which is close enough on a 20-period window that a band drawn with the wrong
one still looks plausible, and far enough that it moves band-touch trigger dates -- exactly the kind
of study Phase 7 runs against these columns. **Do not "fix" this to ``ddof=1``**; that is the
popular default, not the correct one for this purpose, and changing it silently changes every
band-touch backtest that has ever run against this column.

ATR uses Wilder's smoothing, the same recursive form RSI uses (see
:func:`app.indicators.base.wilder_smooth`: seeded from the simple mean of the first `period` true
ranges, not from a naive ``ewm(alpha=1/period, adjust=False)`` seeded off the first single
observation), not a plain rolling mean of true range.

**True range must not be computed with ``skipna=True``.** ``DataFrame.max(axis=1)``'s default
silently drops whichever of the three legs is NaN and takes the max of what is left -- correct by
accident on the first bar (there genuinely is no previous close to diff against, so those two legs
*should* be ignored there), but wrong everywhere else: a missing ``high`` or ``low`` on any later
bar makes the ``high - prev_close`` / ``low - prev_close`` legs the only candidates, and if the
close barely moved that yields a true range near zero when the real, unobserved range could have
been enormous -- a fabricated number with no NaN anywhere to flag it. True range is computed here
with ``skipna=False`` so a missing input makes that bar's true range NaN like everything else that
depends on missing data, and the first bar -- the one case where a NaN leg is expected rather than
missing data -- is special-cased explicitly instead of relying on ``skipna`` to paper over both
situations identically.
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

__all__ = ["ATR_SPEC", "BB_SPEC", "atr", "bollinger"]

_BB_PERIOD = ParamSpec(
    name="period", kind=ParamKind.INT, default=20, minimum=2, maximum=500, label="Period"
)
_BB_STDDEV = ParamSpec(
    name="stddev", kind=ParamKind.FLOAT, default=2.0, minimum=0.1, maximum=10.0, label="Std Dev"
)


def bollinger(bars: pd.DataFrame, /, *, period: int, stddev: float) -> pd.DataFrame:
    """Bollinger Bands: ``mid`` is the SMA, ``upper``/``lower`` are ``mid +/- stddev * population_std``."""
    base = column_name("bb", [period, stddev])
    close = bars["close"]
    mid = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std(ddof=0)  # population std -- see module docstring
    band = stddev * std
    return pd.DataFrame(
        {
            f"{base}_upper": mid + band,
            f"{base}_mid": mid,
            f"{base}_lower": mid - band,
        },
        index=bars.index,
    )


def _bb_warmup(params: Mapping[str, Any]) -> int:
    return int(params["period"]) - 1


def _bb_fn(bars: pd.DataFrame, /, **params: Any) -> pd.DataFrame:
    """Adapter -- see ``app.indicators.trend._sma_fn``."""
    return bollinger(bars, period=params["period"], stddev=params["stddev"])


BB_SPEC = IndicatorSpec(
    name="bb",
    title="Bollinger Bands",
    fn=_bb_fn,
    params=(_BB_PERIOD, _BB_STDDEV),
    outputs=("upper", "mid", "lower"),
    pane=Pane.PRICE,
    warmup=_bb_warmup,
    description="SMA +/- `stddev` population standard deviations, over `period` bars.",
)


_ATR_PERIOD = ParamSpec(
    name="period", kind=ParamKind.INT, default=14, minimum=2, maximum=500, label="Period"
)


def atr(bars: pd.DataFrame, /, *, period: int) -> pd.DataFrame:
    """Wilder-smoothed Average True Range."""
    col = column_name("atr", [period])
    high, low, close = bars["high"], bars["low"], bars["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1, skipna=False)  # a missing leg must NaN the row -- see the module docstring
    if len(true_range) > 0:
        # Row 0 is the one case where a NaN leg (both prev-close legs, since `shift(1)` has
        # nothing to shift into row 0) is expected rather than a sign of missing data -- its true
        # range is simply `high - low`.
        true_range.iloc[0] = high.iloc[0] - low.iloc[0]
    series = wilder_smooth(true_range, period)
    # A true range that is NaN from a genuinely missing high/low/close (not row 0's expected
    # "no previous close") must not surface a value -- `wilder_smooth`'s `ewm` holds the previous
    # average forward across a NaN input rather than emitting NaN there. See momentum.rsi's
    # analogous re-mask for the same reasoning.
    series[true_range.isna()] = np.nan
    return pd.DataFrame({col: series}, index=bars.index)


def _atr_warmup(params: Mapping[str, Any]) -> int:
    """``period - 1``.

    Unlike RSI's gain/loss series, true range has no leading NaN of its own -- the first bar's true
    range is defined (``high - low``) without needing a previous close -- so only
    :func:`~app.indicators.base.wilder_smooth`'s own ``period - 1`` warmup (its seed, the simple
    mean of the first `period` true ranges, settles at index ``period - 1``) applies.
    """
    return int(params["period"]) - 1


def _atr_fn(bars: pd.DataFrame, /, **params: Any) -> pd.DataFrame:
    """Adapter -- see ``app.indicators.trend._sma_fn``."""
    return atr(bars, period=params["period"])


ATR_SPEC = IndicatorSpec(
    name="atr",
    title="Average True Range",
    fn=_atr_fn,
    params=(_ATR_PERIOD,),
    pane=Pane.OSCILLATOR,
    warmup=_atr_warmup,
    description="Wilder-smoothed average of true range over `period` bars.",
)
