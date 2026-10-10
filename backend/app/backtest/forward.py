"""Forward returns, sample independence, and distribution summaries.

The single implementation of "what happened after bar ``t``" in this codebase.
:mod:`app.rules.evidence` computed its own before this module existed and now calls in here instead,
which is the point: two forward-return implementations agreeing today is not a property anyone can
maintain, and the failure mode when they drift is a decision table and a workbench reporting
different numbers for the same question, with no way to tell which is right.

**The convention, stated once.** A rule evaluated on bar ``t`` uses ``t``'s close, which is only
known once the session has settled, so the first obtainable price is the *next* bar's open::

    NEXT_OPEN:   entry = open[t + 1],  exit = close[t + horizon]
    SAME_CLOSE:  entry = close[t],     exit = close[t + horizon - 1]

Both hold for exactly ``horizon`` bars. :attr:`~app.rules.models.Entry.SAME_CLOSE` exists only so a
caller can watch an apparent edge evaporate once the fill is moved to a price that was actually
obtainable -- it is an upper bound on a real result, never an estimate of one.

**Windows that fall off the end are excluded, never truncated.** A trigger eleven bars before the
last stored session has no 20-bar forward return. Measuring it over the eleven bars available and
labelling it a 20-bar return would mix horizons inside one statistic, and would do so preferentially
at the most recent end of the sample -- the part a reader trusts most.

**A zero or negative entry price is dropped, not divided by.** Bad prints exist in long histories.
``0.0`` would produce an infinite return and a negative one would flip the sign, and either would
survive into a median as a plausible-looking number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtest.models import Distribution
from app.market.models import jsonable_float
from app.rules.models import Entry

__all__ = ["describe", "forward_returns", "hit_rate", "independent_count", "independent_mask"]


def forward_returns(bars: pd.DataFrame, *, horizon: int, entry: Entry) -> np.ndarray:
    """Forward return from each bar's trigger to its horizon exit, one value per row of ``bars``.

    ``NaN`` where the window falls off the end of the series, or where the entry price is not a
    usable positive number. See the module docstring for both conventions.
    """
    if horizon < 1:
        raise ValueError(f"horizon must be at least 1 bar, got {horizon}")

    n = len(bars)
    returns = np.full(n, np.nan, dtype=float)
    if n == 0:
        return returns

    idx = np.arange(n)
    closes = bars["close"].to_numpy(dtype=float)
    if entry is Entry.NEXT_OPEN:
        entry_idx = idx + 1
        entry_prices_all = bars["open"].to_numpy(dtype=float)
    else:
        entry_idx = idx
        entry_prices_all = closes
    exit_idx = entry_idx + horizon - 1

    in_bounds = (entry_idx >= 0) & (entry_idx <= n - 1) & (exit_idx >= 0) & (exit_idx <= n - 1)
    safe_entry_idx = np.clip(entry_idx, 0, n - 1)
    safe_exit_idx = np.clip(exit_idx, 0, n - 1)
    entry_price = entry_prices_all[safe_entry_idx]
    exit_price = closes[safe_exit_idx]

    usable = in_bounds & np.isfinite(entry_price) & np.isfinite(exit_price) & (entry_price > 0)
    returns[usable] = exit_price[usable] / entry_price[usable] - 1.0
    return returns


def independent_mask(trigger_positions: np.ndarray, horizon: int) -> np.ndarray:
    """Boolean mask over ``trigger_positions`` marking a maximal non-overlapping subset.

    Greedy in bar order: accept a trigger, discard every later one whose forward window would still
    be open, repeat. Greedy-earliest is optimal for interval scheduling on equal-length windows, so
    this is the largest such subset, not merely one of them -- which matters, because a smaller
    count would understate the evidence rather than overstate it and would be the safer bug to have,
    but a *different* count run to run would make significance verdicts irreproducible.

    Returned as a mask rather than a count so callers can also report *which* episodes survived --
    top-decile moves cluster, and "43 triggers, 5 distinct episodes" is a different fact from "43
    triggers".
    """
    mask = np.zeros(trigger_positions.size, dtype=bool)
    next_allowed = -1
    for i, t in enumerate(trigger_positions):
        if t < next_allowed:
            continue
        mask[i] = True
        next_allowed = t + horizon
    return mask


def independent_count(trigger_positions: np.ndarray, horizon: int) -> int:
    """Number of non-overlapping triggers. Every significance claim rests on this, never on the raw
    trigger count: two triggers three bars apart under a 20-bar horizon share seventeen bars of the
    same forward path and are not two observations of anything."""
    return int(independent_mask(trigger_positions, horizon).sum())


def hit_rate(values: np.ndarray) -> float | None:
    """Fraction of returns strictly greater than zero. ``None`` for an empty sample.

    Strictly greater, not "greater or equal": a flat outcome is not a win. On an instrument with a
    stale-repeated close the difference is the whole statistic.
    """
    if values.size == 0:
        return None
    return jsonable_float(float(np.mean(values > 0)))


def describe(values: np.ndarray) -> Distribution:
    """Summarise a return sample by its percentiles.

    ``NaN`` is not filtered here -- callers pass an already-masked sample, and silently dropping
    ``NaN`` would let a caller that forgot to mask report a count larger than the numbers behind it.
    A sample containing ``NaN`` produces ``NaN`` percentiles, which :func:`jsonable_float` turns into
    ``None``; that is a visible failure rather than a quiet one.
    """
    count = int(values.size)
    if count == 0:
        return Distribution(count=0)

    p05, p25, p50, p75, p95 = (float(v) for v in np.percentile(values, [5, 25, 50, 75, 95]))
    return Distribution(
        count=count,
        mean=jsonable_float(float(np.mean(values))),
        median=jsonable_float(p50),
        # ddof=1 -- the sample standard deviation, undefined at n=1 rather than zero. numpy returns
        # NaN there, which `jsonable_float` maps to None, which is the honest answer: one
        # observation says nothing about dispersion.
        stdev=jsonable_float(float(np.std(values, ddof=1))) if count > 1 else None,
        p05=jsonable_float(p05),
        p25=jsonable_float(p25),
        p75=jsonable_float(p75),
        p95=jsonable_float(p95),
        minimum=jsonable_float(float(np.min(values))),
        maximum=jsonable_float(float(np.max(values))),
    )
