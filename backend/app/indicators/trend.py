"""Trend indicators: SMA, EMA, MACD.

Two conventions are pinned here because the popular defaults are wrong for this purpose:

* SMA uses ``min_periods=period`` on the rolling window. Pandas' default (``min_periods=1``) would
  compute a "20-day average" from the first three bars of a series, which is not a shorter average
  -- it is a different statistic wearing the same label, and it would poison a backtest's first
  handful of signals with numbers no chart would ever show.
* EMA uses ``adjust=False``. That is the recursive form (``EMA_t = alpha*close_t +
  (1-alpha)*EMA_{t-1}``) every charting platform draws. Pandas' default, ``adjust=True``, computes
  a fully-weighted series that diverges from the recursive one most exactly at the start of the
  series -- precisely where warmup correctness is being asserted.

A ``close`` that is itself ``NaN`` is re-masked to ``NaN`` in EMA's output rather than left to
``ewm(adjust=False)``'s own behavior for a missing input, which is to hold the previous EMA value
forward and emit a fabricated repeat -- silent, and indistinguishable downstream from a
genuinely flat close. See :func:`_ema_series`.

MACD chains two EMAs and then a third EMA of their difference. Its combined warmup is *not*
``signal`` bars -- the signal line's own smoothing starts from a macd line that is itself NaN
through the slow EMA's warmup, and the two warmups compose by addition on the NaN *count*, not by
addition on the 1-based "bars until first value" figure. See :func:`_macd_warmup`. The same missing-
``close`` re-masking propagates through the chain: a bar with a missing close is NaN in both EMAs,
therefore NaN in ``macd`` (NaN minus/from anything is NaN), and the ``signal`` EMA -- built by
calling ``.ewm`` again on the already-NaN-bearing ``macd`` line -- gets that same bar re-masked
explicitly too, since chaining another ``ewm(adjust=False)`` on top would otherwise let *that*
smoothing hold its own previous value forward across the gap. ``hist`` needs no separate re-mask:
it is a subtraction of the (already correctly NaN'd) ``macd`` and ``signal`` series.

MACD also rejects ``fast >= slow`` with :class:`~app.indicators.base.IndicatorError`. Nothing about
subtracting two EMAs requires the faster one to be faster -- ``EMA(26) - EMA(12)`` is just as
computable as ``EMA(12) - EMA(26)`` -- but it inverts the sign of every crossover a momentum rule
keys off, silently relabelling "bullish" as "bearish" under the parameters the user actually asked
for.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from app.indicators.base import (
    IndicatorError,
    IndicatorSpec,
    Pane,
    ParamKind,
    ParamSpec,
    column_name,
)

__all__ = ["EMA_SPEC", "MACD_SPEC", "SMA_SPEC", "ema", "macd", "sma"]

_PERIOD = ParamSpec(
    name="period", kind=ParamKind.INT, default=20, minimum=2, maximum=500, label="Period"
)


def sma(bars: pd.DataFrame, /, *, period: int) -> pd.DataFrame:
    """Simple moving average of ``close``."""
    col = column_name("sma", [period])
    series = bars["close"].rolling(period, min_periods=period).mean()
    return pd.DataFrame({col: series}, index=bars.index)


def _sma_warmup(params: Mapping[str, Any]) -> int:
    return int(params["period"]) - 1


def _sma_fn(bars: pd.DataFrame, /, **params: Any) -> pd.DataFrame:
    """Adapts :func:`sma`'s named-keyword signature to :class:`~app.indicators.base.IndicatorFn`.

    ``sma`` keeps ``period: int`` as an explicit, typed keyword rather than ``**params: Any`` so
    that direct callers (tests, and Phase 6/7 code that wants one specific indicator rather than a
    registry lookup) get a real signature instead of an untyped dict. The protocol both
    ``IndicatorSpec.fn`` and the registry's ``compute()`` require is structurally different
    (``**params: Any`` only) from a function with named keyword-only parameters, which mypy does not
    treat as compatible -- this adapter is the seam between "nice API to call directly" and "matches
    the registry's calling convention," repeated once per indicator in each of this package's
    modules rather than solved by editing ``base.py``.
    """
    return sma(bars, period=params["period"])


SMA_SPEC = IndicatorSpec(
    name="sma",
    title="Simple Moving Average",
    fn=_sma_fn,
    params=(_PERIOD,),
    pane=Pane.PRICE,
    warmup=_sma_warmup,
    description="Rolling mean of close over `period` bars.",
)


def _ema_series(close: pd.Series, period: int) -> pd.Series:
    """EMA of ``close``, recursive (``adjust=False``) form, shared by :func:`ema` and :func:`macd`.

    Re-masks any bar where ``close`` itself is NaN back to NaN: ``ewm(adjust=False)`` treats a
    missing input as "hold state" and emits a fabricated repeat of the previous EMA there instead,
    which is wrong for the same reason a missing bar isn't quietly forward-filled anywhere else in
    this package (see :func:`app.indicators.momentum.rsi`'s analogous re-mask).
    """
    series = close.ewm(span=period, adjust=False, min_periods=period).mean()
    series[close.isna()] = np.nan
    return series


def ema(bars: pd.DataFrame, /, *, period: int) -> pd.DataFrame:
    """Exponential moving average of ``close``, recursive (``adjust=False``) form."""
    col = column_name("ema", [period])
    series = _ema_series(bars["close"], period)
    return pd.DataFrame({col: series}, index=bars.index)


def _ema_warmup(params: Mapping[str, Any]) -> int:
    return int(params["period"]) - 1


def _ema_fn(bars: pd.DataFrame, /, **params: Any) -> pd.DataFrame:
    """Adapter -- see :func:`_sma_fn`."""
    return ema(bars, period=params["period"])


EMA_SPEC = IndicatorSpec(
    name="ema",
    title="Exponential Moving Average",
    fn=_ema_fn,
    params=(_PERIOD,),
    pane=Pane.PRICE,
    warmup=_ema_warmup,
    description="Recursive exponential moving average of close over `period` bars.",
)


_FAST = ParamSpec(name="fast", kind=ParamKind.INT, default=12, minimum=1, maximum=500, label="Fast")
_SLOW = ParamSpec(name="slow", kind=ParamKind.INT, default=26, minimum=2, maximum=500, label="Slow")
_SIGNAL = ParamSpec(
    name="signal", kind=ParamKind.INT, default=9, minimum=1, maximum=500, label="Signal"
)


def macd(bars: pd.DataFrame, /, *, fast: int, slow: int, signal: int) -> pd.DataFrame:
    """MACD line, signal line, and histogram.

    ``macd`` = EMA(fast) - EMA(slow). ``signal`` is the EMA(signal) of the macd line -- computed by
    calling ``.ewm`` directly on the macd series, leading NaNs and all, which is what makes the
    warmup compose the way :func:`_macd_warmup` describes rather than simply being ``signal``.
    ``hist`` = macd - signal.

    Raises :class:`~app.indicators.base.IndicatorError` if ``fast >= slow`` -- see the module
    docstring.
    """
    if fast >= slow:
        raise IndicatorError(f"macd: fast period ({fast}) must be less than slow period ({slow})")
    base = column_name("macd", [fast, slow, signal])
    close = bars["close"]
    ema_fast = _ema_series(close, fast)
    ema_slow = _ema_series(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    # See the module docstring: a bar already NaN in `macd_line` (warmup, or a re-masked missing
    # close inherited from either EMA) must not let this second `.ewm` hold its own previous
    # `signal` value forward across that same gap.
    signal_line[macd_line.isna()] = np.nan
    hist = macd_line - signal_line
    return pd.DataFrame(
        {
            f"{base}_macd": macd_line,
            f"{base}_signal": signal_line,
            f"{base}_hist": hist,
        },
        index=bars.index,
    )


def _macd_warmup(params: Mapping[str, Any]) -> int:
    """``(slow - 1) + (signal - 1)``, not ``slow + signal - 1``.

    Chaining two ``ewm(..., min_periods=p)`` calls composes on the leading-NaN *count*: the macd
    line carries ``slow - 1`` leading NaNs from the slow EMA, and re-applying ``ewm(min_periods=
    signal)`` on top of that NaN-laden series adds another ``signal - 1`` before its own first valid
    value -- pandas' ``min_periods`` counts *non-null observations*, so the NaNs already present at
    the head are inherited rather than counted a second time. Verified empirically against pandas
    (not just derived on paper) in ``tests/test_indicators.py::TestMACD``, because this is exactly
    the kind of off-by-one that looks right until it is checked against real output.
    """
    return (int(params["slow"]) - 1) + (int(params["signal"]) - 1)


def _macd_fn(bars: pd.DataFrame, /, **params: Any) -> pd.DataFrame:
    """Adapter -- see :func:`_sma_fn`."""
    return macd(bars, fast=params["fast"], slow=params["slow"], signal=params["signal"])


MACD_SPEC = IndicatorSpec(
    name="macd",
    title="MACD",
    fn=_macd_fn,
    params=(_FAST, _SLOW, _SIGNAL),
    outputs=("macd", "signal", "hist"),
    pane=Pane.OSCILLATOR,
    warmup=_macd_warmup,
    description="Moving Average Convergence/Divergence: EMA(fast) - EMA(slow), plus its own signal"
    " EMA and the histogram of the two.",
)
