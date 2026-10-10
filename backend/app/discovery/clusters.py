"""Group near-identical candidates as of a date, so one bet cannot occupy several slots.

**The defect this fixes.** `strategy-program/DISCOVERY.md` §5 recorded it as a known limitation:
``SMH`` and ``SOXX`` both track semiconductors and correlate above 0.95, so a top-three selector could
and repeatedly did spend two of its three slots on one sector. That is wrong in both directions at
once. It overstates the exam's *evidence* -- the §3 table counted those two picks as two independent
observations of the rule finding semiconductors when they are very nearly one -- and it overstates the
strategy's *diversification*, because a "three sector" portfolio holding SMH, SOXX and one other is a
two-thirds concentrated bet wearing a three-name label.

**Correlation is measured, never declared.** The obvious fix is a hand-written table saying SMH and
SOXX are the same thing. That would work for the pair somebody thought of and fail silently for every
pair they did not -- IGV against XLK, XBI against IBB, XOP against XLE. Worse, it would be a 2026
judgement applied to 2004, which is the exact error this whole package exists to stop making. So
membership is computed from trailing returns at each decision date, through the same
:class:`~app.paper.marketdata.AsOfMarket` the selector uses, and a pair that was not yet correlated in
2004 is correctly treated as two bets then and one bet later if it converges.

**Single-linkage, and the tradeoff that comes with it.** Two symbols join the same group when their
correlation clears :data:`DEFAULT_THRESHOLD`, and groups merge transitively -- if A is close to B and
B to C, all three are one group even when A and C are not close on their own. Single linkage chains
like this, and chaining is a real cost: a long chain of moderately-related funds can collapse into one
group and cost the selector a legitimately distinct pick. It is the right tradeoff at this threshold
anyway, because the failure it prevents is worse than the one it causes: allowing a duplicate through
inflates the measured evidence, while collapsing one pick too many only costs diversification the
exam will then honestly report as a lower score.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Sequence

import pandas as pd

from app.config import Settings
from app.paper.marketdata import AsOfMarket

__all__ = [
    "DEFAULT_LOOKBACK",
    "DEFAULT_THRESHOLD",
    "collapse_to_one_per_group",
    "correlation_groups",
]

#: Daily-return correlation at or above which two candidates are treated as one bet.
#:
#: 0.95 rather than a rounder 0.9 because the pairs this must catch are the ones tracking the *same
#: index* -- SMH/SOXX sit near 0.97 -- while genuinely distinct sector pairs that merely move together
#: in a drawdown (XLI/XLB, XLF/KRE) sit well below. Set it at 0.9 and the whole cyclical complex
#: collapses into one group in a crisis year, which would delete real choices exactly when the
#: selector is being tested hardest.
DEFAULT_THRESHOLD = 0.95

#: Trading days of returns the correlation is measured over. One year: long enough that a single
#: shared shock cannot manufacture 0.95, short enough to notice a pair that has genuinely converged.
DEFAULT_LOOKBACK = 252


def _returns(market: AsOfMarket, symbol: str, lookback: int) -> pd.Series:
    """Daily fractional returns for `symbol` over the last `lookback + 1` bars through `as_of`."""
    frame = market.history(symbol, lookback_days=None)
    if frame.empty:
        return pd.Series(dtype="float64")
    column = "adj_close" if "adj_close" in frame.columns else "close"
    prices = frame[column].astype("float64").dropna()
    return prices.pct_change().dropna().iloc[-lookback:].reset_index(drop=True)


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation, or `None` when either series is constant or they cannot be paired."""
    n = min(len(xs), len(ys))
    if n < 30:
        return None
    a, b = list(xs[-n:]), list(ys[-n:])
    sa, sb = statistics.pstdev(a), statistics.pstdev(b)
    if sa == 0 or sb == 0:
        return None
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True)) / n
    return cov / (sa * sb)


def correlation_groups(
    symbols: Sequence[str],
    as_of: dt.date,
    *,
    settings: Settings,
    threshold: float = DEFAULT_THRESHOLD,
    lookback: int = DEFAULT_LOOKBACK,
) -> tuple[tuple[str, ...], ...]:
    """Partition `symbols` into groups of mutually near-identical candidates, as of `as_of`.

    Every symbol appears in exactly one group; a symbol correlated with nothing forms a group of one,
    so the return value is always a full partition and callers never have to handle a missing name.
    Groups and the symbols inside them are sorted, for the same reason the candidate set is: an
    arbitrary order here would put the universe-ordering noise floor
    (`strategy-program/PROTOCOL.md` §7) underneath every result.

    A pair whose correlation cannot be computed -- either symbol too short at `as_of` -- is treated as
    *uncorrelated*. That is the conservative direction: it keeps two candidates as two bets rather
    than silently merging names the data cannot actually vouch for.
    """
    market = AsOfMarket(as_of=as_of, settings=settings)
    ordered = sorted(symbols)
    series = {s: _returns(market, s, lookback) for s in ordered}

    parent = {s: s for s in ordered}

    def find(s: str) -> str:
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    for i, left in enumerate(ordered):
        for right in ordered[i + 1 :]:
            rho = _pearson(series[left].tolist(), series[right].tolist())
            if rho is not None and rho >= threshold:
                a, b = find(left), find(right)
                if a != b:
                    parent[b] = a

    grouped: dict[str, list[str]] = {}
    for s in ordered:
        grouped.setdefault(find(s), []).append(s)
    return tuple(sorted(tuple(sorted(members)) for members in grouped.values()))


def collapse_to_one_per_group(
    ranked: Sequence[str], groups: Sequence[Sequence[str]]
) -> tuple[str, ...]:
    """Walk `ranked` best-first, keeping a symbol only if its group is not already represented.

    Order is preserved, so the *best-ranked* member of each group is the one that survives -- the
    selector's own preference decides which of SMH and SOXX represents semiconductors, rather than
    this module imposing one.
    """
    index = {symbol: i for i, group in enumerate(groups) for symbol in group}
    seen: set[int] = set()
    out: list[str] = []
    for symbol in ranked:
        key = index.get(symbol, -1)
        if key in seen:
            continue
        if key != -1:
            seen.add(key)
        out.append(symbol)
    return tuple(out)
