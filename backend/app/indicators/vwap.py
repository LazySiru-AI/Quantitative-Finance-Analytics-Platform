"""Anchored VWAP.

``cumsum(typical_price * volume) / cumsum(volume)`` from an anchor forward, where typical price is
``(high + low + close) / 3``. Two anchor modes:

* ``"session"`` restarts the accumulation at every exchange-local trading-session boundary --
  ordinary intraday VWAP, the line every intraday chart draws by default.
* An ISO date (``"2026-06-01"``) accumulates from that date to the end of the series, for "VWAP
  since the breakout" style analysis.

**Registered for ``{5m, 1h}`` only** (:data:`VWAP_SPEC.intervals`). A session anchor on a bar that
*is* a session (daily, weekly) restarts on every single bar, which is not an anchor at all -- it
degenerates to the bar's own typical price and draws a line that looks authoritative and says
nothing. ``parse_spec`` enforces this once the spec declares ``intervals``; see
:mod:`app.indicators.base`.

The anchor parameter is :attr:`~app.indicators.base.ParamKind.CHOICE_OR_DATE` -- a fixed token or an
arbitrary date. That kind exists for this parameter: encoding it as a plain ``CHOICE`` over
``("session",)`` would let the backend accept a date while the frontend, which builds its controls
from the parameter kind, could only ever render a one-option dropdown. The date-anchored form is the
reason an *anchored* VWAP is worth having at all, so it has to survive the trip to the UI.
"""

from __future__ import annotations

import datetime as dt
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
from app.market.models import Interval

__all__ = ["VWAP_SPEC", "anchored_vwap"]

#: Exchange timezone used to determine session boundaries. The `IndicatorFn` contract in base.py
#: passes only `bars` and `params` -- no `Profile.exchange_timezone` -- so a session-anchored VWAP
#: cannot ask the caller which exchange a symbol trades on. Hardcoded to the codebase's one
#: exchange assumption (`Profile.exchange_timezone` defaults to this same value, and every
#: instrument seen so far -- SOXL, TQQQ, NVDA -- is US-listed). A non-US symbol would get session
#: boundaries at the wrong local midnight; flagged here rather than silently assumed correct.
_SESSION_TZ = "America/New_York"


_ANCHOR = ParamSpec(
    name="anchor",
    kind=ParamKind.CHOICE_OR_DATE,
    default="session",
    choices=("session",),
    label="Anchor",
)


def anchored_vwap(bars: pd.DataFrame, /, *, anchor: str | dt.date) -> pd.DataFrame:
    """Anchored VWAP. ``anchor`` is the string ``"session"`` or a :class:`datetime.date`."""
    col = column_name("vwap", [anchor])
    if bars.empty:
        return pd.DataFrame({col: pd.Series(dtype="float64")}, index=bars.index)

    typical = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    # Missing or zero volume must not divide by zero: filled to 0.0 so it contributes no weight
    # rather than raising or poisoning the cumulative sum with NaN.
    volume = bars["volume"].fillna(0.0).astype("float64")
    local_date = pd.to_datetime(bars["ts"], utc=True).dt.tz_convert(_SESSION_TZ).dt.date

    if anchor == "session":
        # A new group starts every time the exchange-local date changes from the previous bar.
        group = local_date.ne(local_date.shift()).cumsum()
        keep = pd.Series(True, index=bars.index)
    else:
        # Bars before the anchor date have no defined accumulation; group them apart from the
        # accumulating run so their volume/typical-price never leaks into cumsum() for the run
        # that starts at the anchor, then mask them to NaN explicitly below.
        keep = local_date >= anchor
        group = keep.astype("int64")

    weighted = typical * volume
    cum_weighted = weighted.groupby(group).cumsum()
    cum_volume = volume.groupby(group).cumsum()
    vwap = cum_weighted / cum_volume.replace(0.0, np.nan)
    vwap = vwap.where(keep, other=np.nan)

    return pd.DataFrame({col: vwap}, index=bars.index)


def _warmup(params: Mapping[str, Any]) -> int:
    """0 for the registered default (``anchor="session"``).

    Session anchoring never produces a leading NaN: every bar belongs to some session, so the
    accumulation restarts at the first bar of each one rather than waiting on a lookback window.
    Date anchoring's leading-NaN count depends on how many bars in the actual series fall before
    the anchor date, which `warmup`'s signature (`Callable[[Mapping[str, Any]], int]`, params only,
    no bars) cannot express -- another instance of the gap documented in the module docstring. Since
    the catalog's registered default is ``"session"``, this callable is exact for that default and
    for every entry the registry-wide warmup sweep in tests/test_indicators.py exercises; the
    date-anchor case is covered by its own dedicated test instead.
    """
    return 0


def _vwap_fn(bars: pd.DataFrame, /, **params: Any) -> pd.DataFrame:
    """Adapter -- see ``app.indicators.trend._sma_fn``."""
    return anchored_vwap(bars, anchor=params["anchor"])


VWAP_SPEC = IndicatorSpec(
    name="vwap",
    title="Anchored VWAP",
    fn=_vwap_fn,
    params=(_ANCHOR,),
    pane=Pane.PRICE,
    intervals=frozenset({Interval.FIVE_MIN, Interval.HOUR}),
    warmup=_warmup,
    description="Volume-weighted average price accumulated from a session start or a chosen date.",
)
