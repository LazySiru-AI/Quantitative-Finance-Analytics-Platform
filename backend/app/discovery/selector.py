"""Rank a candidate set as of a date, using only bars that existed on that date.

**What a selector is, and what it is not.** A selector answers "which of these, today?" It does not
size a position, place a trade, or carry a thesis. Keeping it that small is what makes it gradeable:
:mod:`app.discovery.exam` can replay one selector across twenty years of decision dates and compare
what it chose against what the candidate set as a whole did, and the only thing varying is the choice.

**Every number here comes through** :class:`~app.paper.marketdata.AsOfMarket`, which cannot read past
its own ``as_of`` -- see that class's docstring. This module never opens a parquet file itself and
never accepts an end date as a parameter. That is not defensive style; it is the single property that
separates this package from every backtest already in the repository, all of which were handed a
universe an analyst wrote down after seeing the outcome.

**Adjusted closes, and why they are safe here even though they are revised retroactively.**
:mod:`app.backtest.guards` is careful to say that proving an indicator causal does not prove the
*bars* are point-in-time: a provider that restates history leaves every indicator perfectly causal
over data nobody could have seen. Adjusted closes are exactly such a restatement -- Yahoo rescales
every bar before a distribution each time one occurs. The ratio this module takes is nonetheless
clean, and the reason is worth stating rather than assuming: a distribution paid at ``d`` scales all
bars before ``d`` by one common factor, so for two dates ``t1 < t2 <= as_of`` a distribution at
``d > as_of`` scales both by the same amount and cancels out of ``adj_close[t2] / adj_close[t1]``,
while one falling between them scales only ``t1`` and correctly shows up as part of the return. Raw
closes would silently drop the dividend, which would rank XLU and XLP below where they belong against
XLK for reasons that have nothing to do with either sector.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

import pandas as pd

from app.config import Settings
from app.discovery.candidates import CandidateSet
from app.discovery.clusters import collapse_to_one_per_group, correlation_groups
from app.paper.marketdata import AsOfMarket

__all__ = [
    "RANK_KEYS",
    "Selection",
    "SymbolScore",
    "select",
]

#: Trading days per calendar year, the unit every lookback below is expressed in.
_YEAR: Final = 252
#: Trading days per month, used for the skip in twelve-minus-one momentum.
_MONTH: Final = 21


def _series(market: AsOfMarket, symbol: str) -> pd.Series:
    """Adjusted closes for `symbol` through the market's own `as_of`, oldest first.

    `lookback_days=None` is deliberate and matches what `AsOfMarket.history` tells recursive-indicator
    callers to pass: it means "every stored bar up to as_of" rather than a window some default
    argument chose. Nothing here is recursive, but a rank key that silently ran out of history would
    be scored as a weak signal instead of as a missing one, and the difference matters to a hit rate.
    """
    frame = market.history(symbol, lookback_days=None)
    if frame.empty:
        return pd.Series(dtype="float64")
    column = "adj_close" if "adj_close" in frame.columns else "close"
    return frame[column].astype("float64").dropna().reset_index(drop=True)


def _total_return(series: pd.Series, *, back: int, skip: int = 0) -> float | None:
    """Return over the window ending `skip` bars before the last, starting `back` bars before that.

    Returns `None` rather than a number whenever the series is too short or the base price is
    non-positive. A caller that gets `None` records the symbol as unscoreable for that date, which is
    a different fact from "scored badly" and is kept different all the way into the exam's output.
    """
    end = len(series) - 1 - skip
    start = end - back
    if start < 0 or end <= start:
        return None
    base = float(series.iloc[start])
    if base <= 0.0:
        return None
    return float(series.iloc[end]) / base - 1.0


def _momentum_12_1(series: pd.Series) -> float | None:
    """Twelve-month return excluding the most recent month.

    The skipped month is not a detail. Short-horizon reversal is one of the most reliably documented
    effects in the literature, and a plain trailing-twelve-month rank buys whatever just spiked and
    is about to give it back. Skipping a month is the standard construction for exactly that reason,
    and it costs nothing point-in-time -- it uses *less* recent data, never more.
    """
    return _total_return(series, back=_YEAR - _MONTH, skip=_MONTH)


def _momentum_6(series: pd.Series) -> float | None:
    """Six-month total return, no skip. A faster key, kept as a contrast to `mom12_1`: if the two
    disagree about a sector for years at a time, the exam will say which one was right rather than
    leaving it to taste."""
    return _total_return(series, back=_YEAR // 2)


def _trend(series: pd.Series) -> float | None:
    """Last close over its own 200-day simple moving average, minus one.

    A level rather than a change: `mom12_1` asks "how much did this rise", this asks "is it above its
    own long trend". The distinction is what lets the exam separate a selector that chases the
    steepest riser from one that holds anything in an uptrend, which behave very differently in a
    regime change and identically in a bull market.
    """
    if len(series) < 200:
        return None
    average = float(series.iloc[-200:].mean())
    if average <= 0.0:
        return None
    return float(series.iloc[-1]) / average - 1.0


#: The rank keys a selector may be built on, by name. Named rather than passed as bare callables so
#: that a stored exam result records *which* key produced it in a form that survives serialisation --
#: an exam whose result cannot say what rule generated it is an anecdote.
RANK_KEYS: Final[dict[str, object]] = {
    "mom12_1": _momentum_12_1,
    "mom6": _momentum_6,
    "trend": _trend,
}


@dataclass(frozen=True, slots=True)
class SymbolScore:
    """One candidate's rank score on one decision date, or the fact that it had none."""

    symbol: str
    score: Decimal | None
    """`None` means the rank key could not be computed -- too little history at `as_of`. Kept
    distinct from a low score everywhere downstream: "we could not judge this" and "we judged this
    poorly" are different claims and only one of them is evidence about the selector."""


@dataclass(frozen=True, slots=True)
class Selection:
    """What a selector chose on one date, and everything it considered while choosing.

    The full `scores` table is carried, not just `picks`, because the exam's most useful output is
    not "was the pick good" but "was the pick better than the alternatives it passed over" -- and
    that comparison cannot be reconstructed from the picks alone after the fact.
    """

    as_of: dt.date
    candidate_set: str
    rank_key: str
    picks: tuple[str, ...]
    scores: tuple[SymbolScore, ...]
    groups: tuple[tuple[str, ...], ...] = ()
    """The correlation partition used to collapse near-duplicates, empty when `collapse` was off.

    Carried rather than recomputed because it is measured data, not a setting: it says which
    candidates the market considered interchangeable *on this date*, which is the fact a reader needs
    to judge whether a three-name pick was three bets or one."""

    @property
    def considered(self) -> tuple[str, ...]:
        """Every symbol that was scoreable on this date -- the denominator for a hit rate."""
        return tuple(s.symbol for s in self.scores if s.score is not None)

    def score_of(self, symbol: str) -> Decimal | None:
        """This date's score for `symbol`, or `None` if it was unscoreable or absent. The lookup
        `app.discovery.exam` needs to pair scores against realized returns for an information
        coefficient."""
        for entry in self.scores:
            if entry.symbol == symbol:
                return entry.score
        return None


def select(
    as_of: dt.date,
    *,
    candidates: CandidateSet,
    settings: Settings,
    top_n: int = 3,
    rank_key: str = "mom12_1",
    collapse: bool = False,
) -> Selection:
    """Rank `candidates` as of `as_of` and take the best `top_n`.

    `collapse=True` first partitions the candidates by measured trailing correlation
    (:func:`app.discovery.clusters.correlation_groups`) and keeps only the best-ranked member of each
    group, so a pair like SMH/SOXX cannot occupy two of three slots. The partition is measured at
    `as_of` from bars before it, never declared from a 2026 table -- see that module's docstring for
    why a hand-written duplicate list would reintroduce exactly the hindsight this package exists to
    remove. Off by default so the uncollapsed result stays reproducible.

    Ties break alphabetically. That is arbitrary, and it is recorded here rather than left implicit
    because `strategy-program/PROTOCOL.md` measured a 53.9-point spread in three-year return from
    universe *ordering* alone -- an arbitrary tiebreak in a selector is the same hazard one layer up,
    and a silent one would be indistinguishable from signal in the exam's output.
    """
    if rank_key not in RANK_KEYS:
        raise KeyError(f"unknown rank_key {rank_key!r}; known keys are {sorted(RANK_KEYS)}")
    key_fn = RANK_KEYS[rank_key]

    market = AsOfMarket(as_of=as_of, settings=settings)
    scores: list[SymbolScore] = []
    for symbol in candidates.symbols_as_of(as_of):
        raw = key_fn(_series(market, symbol))  # type: ignore[operator]
        scores.append(
            SymbolScore(symbol=symbol, score=None if raw is None else Decimal(str(round(raw, 8))))
        )

    ranked = sorted(
        (s for s in scores if s.score is not None),
        key=lambda s: (-(s.score or Decimal(0)), s.symbol),
    )
    order = tuple(s.symbol for s in ranked)

    groups: tuple[tuple[str, ...], ...] = ()
    if collapse and order:
        groups = correlation_groups(order, as_of, settings=settings)
        order = collapse_to_one_per_group(order, groups)

    return Selection(
        as_of=as_of,
        candidate_set=candidates.name,
        rank_key=rank_key,
        picks=order[:top_n],
        scores=tuple(scores),
        groups=groups,
    )
