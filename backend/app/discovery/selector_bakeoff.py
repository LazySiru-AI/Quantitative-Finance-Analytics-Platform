"""Grade the eight Round 33 entrants against each other -- the driver, not the measurement.

**What this module is not.** `strategy-program/ROUND-33-PLAN.md` §6 pre-registers a specific,
one-shot measurement: daily decision dates from 2003-01-02 through 2026-08-18, regime labels
reconstructed per §5 (a three-signal `RegimeCall` with `fear_greed_components=()`, a release-lagged
FRED `T10Y2Y`), graded with a stationary-bootstrap IC against the candidate pool's own equal weight,
`block=21`, `seed=33`. §9 is explicit that running that replay twice against the same store is one
measurement counted twice, not two measurements -- so this module does not run it. What it builds is
the *machinery* that measurement needs: a day-by-day replay loop that threads `prior_picks` the way
`app.discovery.workflow_selectors.select_for_workflow` requires, and the grading arithmetic (IC,
bootstrap p, hit rate, Benjamini-Hochberg, churn, implied $/day) applied to whatever decision dates
and regime labels the caller supplies.

**Regime labels are supplied, not reconstructed.** `run_selector_bakeoff` takes an optional
`regime_for` callback and defaults to a constant `"choppy_neutral"` for every date. That default is
adequate for exercising this driver's own control flow against a small fixture -- it is *not* §5's
frozen reconstruction, which needs SPY bars, a release-lagged FRED series and the same three-signal
`classify()` degradation §5 specifies in detail. Building that reconstruction is `app.workflow`'s
job, not this package's -- `app.discovery` has never imported `app.workflow` and this module does
not start. The pre-registered run supplies its own `regime_for` built from that reconstruction.

**Reused, not reimplemented.** Every statistic here is the same function `app.discovery.exam` already
uses: :func:`~app.discovery.stats.ic_summary` for the bootstrapped mean IC,
:func:`~app.discovery.stats.information_coefficient` for the per-date cross-section correlation,
:func:`~app.backtest.scan.binomial_p_value` for the descriptive hit-rate test, and
:func:`~app.discovery.costs.apply_costs` for turnover. The one piece of grading arithmetic that does
not exist yet anywhere in the repository is Benjamini-Hochberg itself (`app.discovery.stats` has the
bootstrap and the rank correlation, not FDR control), so :func:`_benjamini_hochberg` is new, small,
and the standard construction -- sort by p-value, `q_i = p_i * m / rank_i`, enforce monotonicity from
the largest rank down.

**The score fed to `information_coefficient` is a binary "was this picked" indicator, not a
continuous rank.** `select_for_workflow`'s pinned return type is a plain shortlist -- see its module
docstring -- so there is no per-candidate numeric score to correlate the way `app.discovery.selector`
carries one via `SymbolScore`. Pairing a 0/1 "picked" indicator against each considered candidate's
forward return and taking the Spearman correlation (exactly what `information_coefficient` already
computes, unmodified) is the natural extension of §6's "beat the pool's own equal weight" framing
from a single excess-return number into a full cross-section correlation, and it degrades gracefully
to the excess-return sign when only one or two candidates are ever picked. This is a design choice
this module makes, not one `ROUND-33-PLAN.md` states outright, and is recorded here rather than left
implicit.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal

from app.backtest.scan import binomial_p_value
from app.config import Settings
from app.discovery.candidates import CandidateSet
from app.discovery.costs import apply_costs
from app.discovery.exam import _forward_return
from app.discovery.stats import ICSummary, ic_summary, information_coefficient
from app.discovery.workflow_selectors import SELECTOR_IDS, _pool_for, select_for_workflow

__all__ = [
    "BakeoffResult",
    "SelectorGrade",
    "run_selector_bakeoff",
]

#: The horizon and bootstrap block/seed §6 pins for the real measurement. Callers building the
#: pre-registered run should not need to override these; a caller building a fixture-scale unit test
#: may pass smaller values if a synthetic window is too short to carry a 21-day horizon.
DEFAULT_HORIZON_DAYS: int = 21
DEFAULT_BOOTSTRAP_BLOCK: float = 21.0
DEFAULT_SEED: int = 33


@dataclass(frozen=True, slots=True)
class SelectorGrade:
    """One entrant's grade over one slice (in-sample or held-out) -- §6's secondary metrics included."""

    selector_id: str
    n_dates: int
    """Decision dates replayed, whether or not any of them produced a measurable IC."""
    n_scored: int
    """Dates that produced a measurable per-date IC -- `ICSummary.n`, not `n_dates`."""
    mean_ic: float | None
    bootstrap_p: float | None
    hit_rate: float | None
    """Fraction of priceable trials where the pick basket beat the pool's equal weight. Descriptive
    only -- see `app.discovery.exam`'s own caveat on overlapping daily-cadence trials."""
    binomial_p: float | None
    bh_q: float | None
    """Benjamini-Hochberg q-value, `m=8` -- every entrant and both controls, always, per §6."""
    mean_churn: Decimal | None
    """`app.discovery.costs.turnover`'s mean over consecutive daily pick sets."""
    implied_dollars_per_day: float | None
    """Mean count of shortlist symbols new since the prior session, times $4 -- §6's proxy for what
    this selector would have cost in paid research spend."""


@dataclass(frozen=True, slots=True)
class BakeoffResult:
    """Every entrant, graded on both slices of the walk-forward split -- §6."""

    in_sample: tuple[SelectorGrade, ...]
    holdout: tuple[SelectorGrade, ...]

    def grade(self, selector_id: str, *, slice_name: str = "in_sample") -> SelectorGrade | None:
        """One entrant's grade on one named slice (`"in_sample"` or `"holdout"`), or `None`."""
        grades = self.in_sample if slice_name == "in_sample" else self.holdout
        return next((g for g in grades if g.selector_id == selector_id), None)


@dataclass(frozen=True, slots=True)
class _Trial:
    """One decision date's replay for one entrant -- kept only as long as it takes to grade."""

    as_of: dt.date
    picks: tuple[str, ...]
    ic: float | None
    hit: bool | None


def _default_decision_dates(start: dt.date, end: dt.date) -> tuple[dt.date, ...]:
    """Calendar weekdays in `[start, end]`.

    A placeholder, not a trading calendar -- it does not know about holidays, and the pre-registered
    §5 run should pass a `decision_dates_fn` built from the store's own session dates (the same way
    `app.paper.marketdata.SessionCalendar` derives one from a benchmark symbol's stored bars) rather
    than rely on this default. Adequate for driving this module's own control flow against a fixture.
    """
    dates: list[dt.date] = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            dates.append(day)
        day += dt.timedelta(days=1)
    return tuple(dates)


def _default_regime_for(_settings: Settings, _as_of: dt.date) -> str:
    """The constant-regime default -- see the module docstring's second paragraph."""
    return "choppy_neutral"


def _default_card_universe_for(_as_of: dt.date) -> tuple[str, ...]:
    return ()


def _benchmark_pool(selector_id: str, regime_label: str, settings: Settings) -> CandidateSet | None:
    """The pool a trial's forward-return benchmark is measured against.

    Mirrors each entrant's own pool wiring (`workflow_selectors._pool_for`, plus the two entrants
    that do not go through it) so a selector is graded against exactly the universe it chose from,
    never a different one. `control_card_universe` has no such universe by construction -- §3 entrant
    7 reads no price history at all -- so its trials fall back to grading against its own picks,
    which collapses the benchmark to the pick basket itself and is disclosed here rather than left to
    be discovered as an unexplained `None` mean IC.
    """
    if selector_id == "divers_mom6":
        from app.discovery.candidates import theme_candidates

        return theme_candidates(settings)
    if selector_id == "control_week_rotation":
        from app.discovery.candidates import sector_candidates

        return sector_candidates(settings)
    if selector_id == "control_card_universe":
        return None
    return _pool_for(selector_id, regime_label, settings=settings)


def _replay_one_selector(
    selector_id: str,
    dates: tuple[dt.date, ...],
    *,
    settings: Settings,
    regime_for: Callable[[Settings, dt.date], str],
    card_universe_for: Callable[[dt.date], tuple[str, ...]],
    horizon_days: int,
) -> tuple[_Trial, ...]:
    trials: list[_Trial] = []
    prior: tuple[str, ...] = ()
    for as_of in dates:
        regime_label = regime_for(settings, as_of)
        picks = select_for_workflow(
            selector_id,
            as_of=as_of,
            regime_label=regime_label,
            settings=settings,
            prior_picks=prior,
            card_universe=card_universe_for(as_of),
        )

        pool = _benchmark_pool(selector_id, regime_label, settings)
        considered = pool.symbols_as_of(as_of) if pool is not None else picks
        end = as_of + dt.timedelta(days=horizon_days)
        forward: dict[str, Decimal] = {}
        for symbol in considered:
            value = _forward_return(symbol, start=as_of, end=end, settings=settings)
            if value is not None:
                forward[symbol] = value

        usable = sorted(forward)
        scores = [1.0 if s in picks else 0.0 for s in usable]
        returns = [float(forward[s]) for s in usable]
        ic = information_coefficient(scores, returns) if len(usable) >= 2 else None

        pick_values = [float(forward[s]) for s in picks if s in forward]
        bench_values = [float(v) for v in forward.values()]
        pick_return = sum(pick_values) / len(pick_values) if pick_values else None
        bench_return = sum(bench_values) / len(bench_values) if bench_values else None
        hit = None if pick_return is None or bench_return is None else pick_return > bench_return

        trials.append(_Trial(as_of=as_of, picks=picks, ic=ic, hit=hit))
        prior = picks
    return tuple(trials)


def _grade_trials(selector_id: str, trials: Sequence[_Trial]) -> SelectorGrade:
    ics = [t.ic for t in trials]
    summary: ICSummary | None = ic_summary(
        ics, bootstrap=True, block=DEFAULT_BOOTSTRAP_BLOCK, seed=DEFAULT_SEED
    )

    hits = [t.hit for t in trials if t.hit is not None]
    n_scored_hits = len(hits)
    hit_rate = (sum(1 for h in hits if h) / n_scored_hits) if n_scored_hits else None
    binom_p = (
        binomial_p_value(sum(1 for h in hits if h), n_scored_hits, 0.5) if n_scored_hits else None
    )

    costed = apply_costs([t.picks for t in trials])
    mean_churn = costed.mean_turnover if trials else None

    new_counts: list[int] = []
    previous: tuple[str, ...] = ()
    for t in trials:
        new_counts.append(len(set(t.picks) - set(previous)))
        previous = t.picks
    implied = (sum(new_counts) / len(new_counts)) * 4.0 if new_counts else None

    return SelectorGrade(
        selector_id=selector_id,
        n_dates=len(trials),
        n_scored=summary.n if summary is not None else 0,
        mean_ic=summary.mean if summary is not None else None,
        bootstrap_p=summary.bootstrap_p if summary is not None else None,
        hit_rate=hit_rate,
        binomial_p=binom_p,
        bh_q=None,  # filled in by `_grade_slice` once every entrant's p-value is known.
        mean_churn=mean_churn,
        implied_dollars_per_day=implied,
    )


def _benjamini_hochberg(p_values: dict[str, float | None], *, m: int) -> dict[str, float | None]:
    """Standard Benjamini-Hochberg FDR control, `m` fixed at the full entrant count.

    `ROUND-33-PLAN.md` §6: "Benjamini-Hochberg across all 8 entrants, controls included -- the
    denominator rule applied without exception." `m` is therefore always `len(SELECTOR_IDS)` (8), not
    the count of entrants that happened to produce a measurable bootstrap p-value -- an entrant with
    no measurable IC still occupies a slot in the correction, it simply cannot itself be rejected.
    """
    items = sorted(((sid, p) for sid, p in p_values.items() if p is not None), key=lambda kv: kv[1])
    result: dict[str, float | None] = {sid: None for sid in p_values}
    if not items or m <= 0:
        return result

    n = len(items)
    raw_q = [min(1.0, p * m / (i + 1)) for i, (_, p) in enumerate(items)]
    for i in range(n - 2, -1, -1):
        raw_q[i] = min(raw_q[i], raw_q[i + 1])
    for (sid, _), q in zip(items, raw_q, strict=True):
        result[sid] = q
    return result


def _grade_slice(
    dates: tuple[dt.date, ...],
    *,
    settings: Settings,
    regime_for: Callable[[Settings, dt.date], str],
    card_universe_for: Callable[[dt.date], tuple[str, ...]],
    horizon_days: int,
) -> tuple[SelectorGrade, ...]:
    grades: dict[str, SelectorGrade] = {}
    for selector_id in SELECTOR_IDS:
        trials = _replay_one_selector(
            selector_id,
            dates,
            settings=settings,
            regime_for=regime_for,
            card_universe_for=card_universe_for,
            horizon_days=horizon_days,
        )
        grades[selector_id] = _grade_trials(selector_id, trials)

    p_values = {sid: grades[sid].bootstrap_p for sid in SELECTOR_IDS}
    q_values = _benjamini_hochberg(p_values, m=len(SELECTOR_IDS))
    return tuple(replace(grades[sid], bh_q=q_values[sid]) for sid in SELECTOR_IDS)


def run_selector_bakeoff(
    *,
    settings: Settings,
    in_sample: tuple[dt.date, dt.date],
    holdout: tuple[dt.date, dt.date],
    decision_dates_fn: Callable[[dt.date, dt.date], tuple[dt.date, ...]] | None = None,
    regime_for: Callable[[Settings, dt.date], str] | None = None,
    card_universe_for: Callable[[dt.date], tuple[str, ...]] | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> BakeoffResult:
    """Replay all eight `SELECTOR_IDS` over `in_sample` and `holdout`, and grade each -- §6.

    `in_sample` and `holdout` are each a `(start, end)` date pair, turned into decision dates by
    `decision_dates_fn` (a calendar-weekday default if omitted -- see :func:`_default_decision_dates`
    for why a caller running the real §6 measurement should supply the store's own trading calendar
    instead). `regime_for` and `card_universe_for` default to constants (`"choppy_neutral"` and `()`
    respectively); see the module docstring for why building §5's actual regime reconstruction is out
    of scope here. This function does not itself constitute the pre-registered run -- see §9 and the
    module docstring's opening paragraph.
    """
    dates_fn = decision_dates_fn or _default_decision_dates
    regime_fn = regime_for or _default_regime_for
    card_fn = card_universe_for or _default_card_universe_for

    in_sample_dates = dates_fn(*in_sample)
    holdout_dates = dates_fn(*holdout)

    in_sample_grades = _grade_slice(
        in_sample_dates,
        settings=settings,
        regime_for=regime_fn,
        card_universe_for=card_fn,
        horizon_days=horizon_days,
    )
    holdout_grades = _grade_slice(
        holdout_dates,
        settings=settings,
        regime_for=regime_fn,
        card_universe_for=card_fn,
        horizon_days=horizon_days,
    )
    return BakeoffResult(in_sample=in_sample_grades, holdout=holdout_grades)
