"""Grade a selector by replaying it: decide with data up to T, then score against what happened.

**The question this package exists to answer.** Not "did this basket beat SPY" -- every backtest in
this repository already answers that, on a universe an analyst wrote down in 2026. The question here
is *would a stated rule, run at a date in the past with nothing after it, have found the sector that
went up?* That is answerable on data already in the store, and it produces two numbers the programme
has never had for anything: a hit rate and a false-positive rate.

**The benchmark is the equal-weight candidate set, not SPY, and this is the whole design.** A
selector graded against SPY in a bull market looks brilliant for picking anything at all, because
almost everything beat cash and a good fraction beat the index. The only question that isolates
*selection skill* is whether the chosen candidates beat the average of the candidates that were
available to choose from on the same day. `app.tournament.runner`'s `_BENCHMARK = "SPY"` is the right
benchmark for the question that module asks and the wrong one for this question -- it books an entire
sector's move as skill, which is precisely how a hindsight-picked semiconductor basket comes to look
like a strategy.

**Forward measurement is allowed to see the future; the decision is not.** :func:`_forward_return`
deliberately reads bars after the decision date, because grading is not deciding. The separation is
structural rather than conventional: the decision goes through
:func:`app.discovery.selector.select`, which only ever touches an
:class:`~app.paper.marketdata.AsOfMarket` pinned to the decision date and physically cannot read past
it, while grading happens here, afterwards, on a `Selection` that has already been fixed. Nothing in
this module can feed a number back into a choice that was already made.

**What a good result here would and would not establish.** A hit rate significantly above one half
would establish that the rank key carried information about the following period *within this
candidate set, over these dates*. It would not establish that the effect survives costs, that it
holds for single stocks, or that it holds out of sample -- the dates below overlap the same era as
every other figure in the programme. And the candidate roster is itself chosen in 2026; see
:data:`app.discovery.candidates.SECTOR_ETF_ROSTER` for the size and shape of the bias that leaves.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from decimal import Decimal
from statistics import median

import pandas as pd

from app.backtest.scan import binomial_p_value
from app.config import Settings
from app.discovery.candidates import CandidateSet
from app.discovery.costs import apply_costs
from app.discovery.selector import Selection, select
from app.discovery.stats import ICSummary, ic_summary, information_coefficient
from app.paper.marketdata import AsOfMarket

__all__ = [
    "ExamResult",
    "TrialResult",
    "annual_decision_dates",
    "monthly_decision_dates",
    "run_exam",
]


def _frame(market: AsOfMarket, symbol: str) -> pd.DataFrame:
    """Timestamped adjusted closes through `market.as_of`, oldest first, indexed 0..n-1."""
    frame = market.history(symbol, lookback_days=None)
    if frame.empty:
        return frame
    column = "adj_close" if "adj_close" in frame.columns else "close"
    out = frame[["ts", column]].rename(columns={column: "px"}).dropna()
    return out.reset_index(drop=True)


def _value_at(frame: pd.DataFrame, when: dt.date) -> float | None:
    """The last price at or before `when`, or `None` if the frame starts after it.

    "At or before" rather than "on" because `when` is a calendar date and may be a weekend or a
    holiday. Taking the previous session is the same convention `AsOfMarket.close` uses.

    Located by `searchsorted` on the already-sorted timestamp column rather than by building a
    date-valued mask. The mask version was correct and unusably slow: it materialised a Python `date`
    for every bar in the symbol's full history on *every* call, and a monthly-spaced exam makes
    roughly six thousand calls across twenty-one symbols, which is tens of millions of throwaway
    objects. The store guarantees `ts` is sorted ascending (`app.db.duck.read_bars` orders by it), so
    a binary search is both equivalent and constant-ish.
    """
    if frame.empty:
        return None
    cutoff = pd.Timestamp(when, tz="UTC") + pd.Timedelta(days=1)
    position = int(frame["ts"].searchsorted(cutoff, side="left"))
    if position == 0:
        return None
    return float(frame["px"].iloc[position - 1])


def _forward_return(
    symbol: str, *, start: dt.date, end: dt.date, settings: Settings
) -> Decimal | None:
    """Total return of `symbol` from `start` to `end`, or `None` if either end is unpriceable.

    This is the grading step and it reads the future on purpose -- see the module docstring. It is
    kept in this module, never in `selector`, so that the two capabilities never sit behind the same
    import.
    """
    frame = _frame(AsOfMarket(as_of=end, settings=settings), symbol)
    first = _value_at(frame, start)
    last = _value_at(frame, end)
    if first is None or last is None or first <= 0.0:
        return None
    return Decimal(str(round(last / first - 1.0, 8)))


@dataclass(frozen=True, slots=True)
class TrialResult:
    """One decision date, graded."""

    as_of: dt.date
    horizon_end: dt.date
    picks: tuple[str, ...]
    pick_return: Decimal | None
    """Equal-weighted forward return of the picks. `None` when no pick could be priced over the
    horizon, which is recorded as an untested trial rather than a failed one."""
    benchmark_return: Decimal | None
    """Equal-weighted forward return of *everything the selector considered on this date* -- the
    candidates that were scoreable, not the whole roster. Using the roster would credit the selector
    for avoiding funds that did not yet exist."""
    excess: Decimal | None
    best_available: tuple[str, Decimal] | None
    """The candidate that actually did best over the horizon, and by how much. Not a target -- no
    selector reaches it consistently -- but it is what makes a mediocre positive excess legible: it
    says how much was on the table."""
    ic: float | None = None
    """Rank correlation between the scores the selector assigned across the whole cross-section and
    what those candidates went on to do. Where `excess` reduces this date to one bit, `ic` keeps the
    roughly twenty paired observations it was computed from -- see `app.discovery.stats`."""
    cost: Decimal = Decimal(0)
    """Trading cost charged to this decision, from the turnover of moving into `picks` from the
    previous trial's. Zero when the exam was run without costs."""
    groups: tuple[tuple[str, ...], ...] = ()
    """The correlation partition at this date, empty when collapse was off."""

    @property
    def hit(self) -> bool | None:
        """Whether the picks beat the equal-weight candidate set, **net of cost**. `None` for an
        untested trial."""
        net = self.net_excess
        return None if net is None else net > 0

    @property
    def net_excess(self) -> Decimal | None:
        """`excess` after subtracting this decision's trading cost. Identical to `excess` when the
        exam was run costless, so every downstream aggregate can read this field unconditionally."""
        return None if self.excess is None else self.excess - self.cost


@dataclass(frozen=True, slots=True)
class ExamResult:
    """Every trial, plus the aggregate the exam exists to produce."""

    candidate_set: str
    rank_key: str
    top_n: int
    horizon_days: int
    trials: tuple[TrialResult, ...]
    cost_bps: Decimal = Decimal(0)
    collapsed: bool = False

    @property
    def tested(self) -> tuple[TrialResult, ...]:
        return tuple(t for t in self.trials if t.excess is not None)

    @property
    def hits(self) -> int:
        return sum(1 for t in self.tested if t.hit)

    @property
    def hit_rate(self) -> float | None:
        tested = self.tested
        return None if not tested else self.hits / len(tested)

    @property
    def median_excess(self) -> Decimal | None:
        """Median **net** excess -- after costs. Gross excess is still on each trial for anyone who
        wants to see what the costs took."""
        values = [t.net_excess for t in self.tested if t.net_excess is not None]
        return None if not values else Decimal(str(median(float(v) for v in values)))

    @property
    def ic(self) -> ICSummary | None:
        """The information-coefficient aggregate across every date that produced one.

        This is the headline the hit rate cannot be. `strategy-program/DISCOVERY.md` §4 concluded that
        23 annual trials could never reach significance, which is true of a binomial on 23 bits and
        false of the underlying evidence: each of those dates also carried a full ranked cross-section
        that the hit rate discarded.
        """
        return ic_summary([t.ic for t in self.trials])

    def ic_bootstrapped(self, *, block: float = 3.0, seed: int = 0) -> ICSummary | None:
        """`ic` with a stationary-bootstrap p-value, for decision dates spaced closer than their own
        horizon. Set `block` near the number of consecutive dates sharing data -- twelve for monthly
        dates on an annual horizon."""
        return ic_summary([t.ic for t in self.trials], bootstrap=True, block=block, seed=seed)

    @property
    def p_value(self) -> float | None:
        """Exact two-sided binomial test of the hit rate against a coin flip.

        Reuses `app.backtest.scan.binomial_p_value` rather than restating the arithmetic, for the
        reason that module gives at length: the statistics in this repository stay auditable and
        there is exactly one implementation of each.

        A caveat this number cannot carry by itself: overlapping horizons are not independent
        trials. Annual decision dates with a one-year horizon are close to non-overlapping; anything
        shorter-spaced overstates the effective sample size, and the p-value with it.
        """
        tested = self.tested
        return None if not tested else binomial_p_value(self.hits, len(tested), 0.5)

    def picked(self, symbol: str) -> tuple[dt.date, ...]:
        """Every decision date on which `symbol` was among the picks.

        The point of the whole exercise in one method: `result.picked("SOXX")` says when, if ever, a
        stated rule running on contemporaneous data would have put semiconductors in front of you.
        """
        return tuple(t.as_of for t in self.trials if symbol in t.picks)


def annual_decision_dates(
    start: dt.date, end: dt.date, *, month: int = 1, day: int = 2
) -> tuple[dt.date, ...]:
    """One decision date per year in `[start, end]`.

    Annual spacing with an annual horizon keeps the trials nearly non-overlapping, which is what lets
    `ExamResult.p_value` mean roughly what it says. It also matches how a person would actually use
    this -- nobody rebalances a sector view daily -- and it keeps the trial count honest: twenty
    years is twenty trials, not five thousand, and a rule that needs five thousand overlapping
    trials to look significant has not shown anything.
    """
    years = range(start.year, end.year + 1)
    dates = tuple(d for y in years if start <= (d := dt.date(y, month, day)) <= end)
    return dates


def monthly_decision_dates(start: dt.date, end: dt.date, *, day: int = 2) -> tuple[dt.date, ...]:
    """One decision date per month in `[start, end]`.

    Twelve times the dates of :func:`annual_decision_dates` over the same history, which is the only
    way to get more measurements out of a fixed number of years. It buys real information -- each date
    carries its own cross-section, and the ranking on 2019-06-02 is genuinely not the ranking on
    2019-01-02 -- but the *horizons* then overlap by eleven twelfths, so consecutive observations are
    strongly serially dependent.

    That dependence must be priced, not ignored. `ExamResult.p_value` (a binomial over trials assumed
    independent) becomes actively misleading at this spacing and will report significance that is not
    there; use `ExamResult.ic_bootstrapped(block=12)` instead, which resamples in blocks long enough
    to carry the overlap into the null distribution.
    """
    dates: list[dt.date] = []
    year, month = start.year, start.month
    while True:
        current = dt.date(year, month, day)
        if current > end:
            break
        if current >= start:
            dates.append(current)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return tuple(dates)


def run_exam(
    *,
    candidates: CandidateSet,
    settings: Settings,
    decision_dates: tuple[dt.date, ...],
    horizon_days: int = 365,
    top_n: int = 3,
    rank_key: str = "mom12_1",
    collapse: bool = False,
    cost_bps: Decimal = Decimal(0),
) -> ExamResult:
    """Replay one selector across `decision_dates` and grade each decision against its own horizon.

    `decision_dates` must be chronological -- costs are charged on turnover between *consecutive*
    elements, so an unsorted sequence would invent trades that never happened. Sorted here rather than
    asserted, because the failure is silent and the fix is one line.
    """
    ordered_dates = tuple(sorted(decision_dates))
    selections: list[Selection] = []
    trials: list[TrialResult] = []
    for as_of in ordered_dates:
        end = as_of + dt.timedelta(days=horizon_days)
        selection: Selection = select(
            as_of,
            candidates=candidates,
            settings=settings,
            top_n=top_n,
            rank_key=rank_key,
            collapse=collapse,
        )
        selections.append(selection)

        forward: dict[str, Decimal] = {}
        for symbol in selection.considered:
            value = _forward_return(symbol, start=as_of, end=end, settings=settings)
            if value is not None:
                forward[symbol] = value

        pick_values = [forward[s] for s in selection.picks if s in forward]
        pick_return = (
            None
            if not pick_values
            else Decimal(str(round(sum(float(v) for v in pick_values) / len(pick_values), 8)))
        )
        bench_values = list(forward.values())
        benchmark_return = (
            None
            if not bench_values
            else Decimal(str(round(sum(float(v) for v in bench_values) / len(bench_values), 8)))
        )
        excess = (
            None
            if pick_return is None or benchmark_return is None
            else pick_return - benchmark_return
        )
        best = max(forward.items(), key=lambda kv: kv[1]) if forward else None

        # The information coefficient over the full cross-section: every candidate that was both
        # scoreable at `as_of` and priceable over the horizon, paired score-against-outcome. Built
        # from `selection.score_of` rather than from the picks, because the picks are the part the
        # hit rate already measured and the rest is the part it threw away.
        paired = [(selection.score_of(s), forward[s]) for s in sorted(forward)]
        usable = [(float(sc), float(fr)) for sc, fr in paired if sc is not None]
        ic = (
            information_coefficient([s for s, _ in usable], [f for _, f in usable])
            if len(usable) >= 2
            else None
        )

        trials.append(
            TrialResult(
                as_of=as_of,
                horizon_end=end,
                picks=selection.picks,
                pick_return=pick_return,
                benchmark_return=benchmark_return,
                excess=excess,
                best_available=best,
                ic=ic,
                groups=selection.groups,
            )
        )

    # Costs are charged on turnover between consecutive decisions, which is only knowable once every
    # decision is made -- so the trials are rebuilt here with their cost attached rather than being
    # charged inside the loop above. See `app.discovery.costs` for why per-trial round trips would
    # invent turnover a stable rule never had.
    if cost_bps:
        costed = apply_costs([t.picks for t in trials], cost_bps=cost_bps)
        trials = [
            replace(trial, cost=cost) for trial, cost in zip(trials, costed.costs, strict=True)
        ]

    return ExamResult(
        candidate_set=candidates.name,
        rank_key=rank_key,
        top_n=top_n,
        horizon_days=horizon_days,
        trials=tuple(trials),
        cost_bps=cost_bps,
        collapsed=collapse,
    )
