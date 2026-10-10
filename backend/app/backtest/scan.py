"""Many conditions, one honest trial count: the exact binomial test and Benjamini-Hochberg correction
that back :class:`app.backtest.models.ScanResult`, plus the :func:`scan` entry point that assembles
one.

**Why this module exists.** Testing thirty conditions and reporting the six that cleared
``p <= 0.05`` is exactly as misleading as it sounds even though every individual p-value is computed
correctly: at ``alpha=0.05`` roughly one in twenty *null* conditions clears that bar by chance alone,
so thirty independent nulls produce a discovery about one time in two. Benjamini-Hochberg (1995)
controls the *expected fraction of false discoveries among the flagged set*, not the per-test error
rate, which is the guarantee that actually matters once more than one hypothesis is on the table. The
price of that guarantee is that every trial -- including the ones that could not be tested at all --
must be declared and counted; see :func:`benjamini_hochberg`.

**Collaborators are injected**, matching the pattern :mod:`app.rules.service` documents under
"injectable collaborators": :func:`scan` takes an :class:`Evaluate` callable rather than importing
:mod:`app.backtest.events` itself, because that module is being written by another agent in parallel
and this one must stay importable -- and independently testable with fabricated
:class:`~app.backtest.models.HorizonStats` -- without it.

**One `IndicatorCache` can be threaded through every `evaluate` call in one scan.** This module never
computes an indicator itself -- it only ever calls the injected :class:`Evaluate` -- so it cannot
*perform* the sharing :mod:`app.rules.evaluate` describes under "sharing a computed indicator across
two different rule trees." What it can do, and does, is carry one caller-supplied
:class:`~app.rules.evaluate.IndicatorCache` across every ``(expression, horizon)`` pair in the loop
below, so whichever :class:`Evaluate` implementation the caller wired up -- if it is one that calls
:func:`app.rules.evaluate.evaluate` with that same cache -- gets the benefit for free: thirty
conditions built around ``rsi:14`` compute it once for the whole scan rather than once per condition.
``indicator_cache`` defaults to ``None`` and is forwarded only when the caller supplied one, for
exactly the reason :mod:`app.rules.service` gives for the same default: an :class:`Evaluate` written
before this parameter existed is not guaranteed to accept it, and calling it with a keyword it does
not declare would raise ``TypeError`` rather than silently doing nothing.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from typing import Protocol

from app.backtest.models import (
    GuardFinding,
    GuardReport,
    GuardStatus,
    HorizonStats,
    ScanEntry,
    ScanResult,
)
from app.db.duck import Interval
from app.market.models import MarketWarning
from app.rules.evaluate import IndicatorCache
from app.rules.models import Entry

__all__ = ["Evaluate", "benjamini_hochberg", "binomial_p_value", "scan"]


# ---------------------------------------------------------------------------
# Exact two-sided binomial test
# ---------------------------------------------------------------------------


def binomial_p_value(successes: int, trials: int, p_null: float) -> float:
    """Exact two-sided binomial test by the method of small p-values -- what
    ``scipy.stats.binomtest`` computes, reimplemented in pure Python because scipy is not installed
    in this repository and the statistics here must stay auditable: sum ``P(X=i)`` over every
    outcome ``i`` in ``0..trials`` whose probability under the null is no larger than the observed
    outcome's probability (with a relative tolerance so the observed outcome's own term is never
    excluded by floating-point noise), rather than doubling the one-sided tail -- doubling gives a
    nonsensical result whenever the null is not exactly 0.5, since the two tails are not generally
    symmetric. **This is not a normal approximation** to the binomial -- no continuity correction,
    no z-score, nothing that only becomes accurate as ``trials`` grows -- it sums the exact discrete
    pmf, so it is equally correct at ``trials=5`` and ``trials=6000``.

    **Every pmf term is computed in log space via `math.lgamma`, never via `math.comb`.**
    ``math.comb(trials, k)`` materialises the exact binomial coefficient as a Python integer, which
    for `trials` in the thousands has hundreds to thousands of digits; multiplying that integer by a
    float (`p_null**k`) forces an int-to-float conversion that raises `OverflowError` once the
    coefficient exceeds what a float can hold (~1.8e308) -- and `close > sma(200)` at horizon 1
    against ordinary tickers with ~6,300 sessions of daily history reaches `trials` in the
    thousands routinely, so this was not a rare edge case but a routine crash. Working in log space
    sidesteps the giant intermediate entirely: ``log C(n,k) = lgamma(n+1) - lgamma(k+1) -
    lgamma(n-k+1)``, and ``log pmf(k) = log C(n,k) + k*log(p) + (n-k)*log(1-p)`` is always `<= 0`
    (it is the log of a probability), so `math.exp` of it can never overflow -- at worst it
    underflows to `0.0` for an outcome whose probability is indistinguishable from zero at double
    precision, which is the mathematically correct thing for that term to contribute to the sum, not
    an error condition to guard against.

    ``trials == 0`` returns ``1.0``: no data can reject any null. ``p_null`` of exactly ``0.0`` or
    ``1.0`` is degenerate (every trial is forced, so the outcome is certain) and is handled directly
    rather than falling through to a ``log(0)`` domain error in the pmf. ``k == 0`` and ``k ==
    trials`` need no special case beyond that: `lgamma(1) == 0` exactly, so the binomial-coefficient
    term for either endpoint is well-defined. ``successes > trials`` is a programming error in the
    caller, not a data condition to report on, so it raises.
    """
    if successes < 0 or trials < 0:
        raise ValueError(f"successes and trials must be non-negative, got {successes}, {trials}")
    if successes > trials:
        raise ValueError(f"successes ({successes}) cannot exceed trials ({trials})")
    if not 0.0 <= p_null <= 1.0:
        raise ValueError(f"p_null must be in [0, 1], got {p_null}")

    if trials == 0:
        return 1.0

    if p_null == 0.0:
        return 0.0 if successes > 0 else 1.0
    if p_null == 1.0:
        return 0.0 if successes < trials else 1.0

    log_p = math.log(p_null)
    log_1mp = math.log(1.0 - p_null)
    log_n_fact = math.lgamma(trials + 1)

    def log_pmf(k: int) -> float:
        log_coef = log_n_fact - math.lgamma(k + 1) - math.lgamma(trials - k + 1)
        return log_coef + k * log_p + (trials - k) * log_1mp

    # Each term is <= 1.0 (it is a probability), so exponentiating a log-pmf can never overflow --
    # it can only underflow to 0.0, which is the correct contribution for a vanishingly unlikely
    # outcome, not a failure.
    pmfs = [math.exp(log_pmf(k)) for k in range(trials + 1)]
    observed = pmfs[successes]
    threshold = observed * (1.0 + 1e-7)
    total = sum(p for p in pmfs if p <= threshold)
    return min(total, 1.0)


# ---------------------------------------------------------------------------
# Benjamini-Hochberg
# ---------------------------------------------------------------------------


def benjamini_hochberg(p_values: Sequence[float | None]) -> list[float | None]:
    """Benjamini-Hochberg (1995) adjusted q-values, in the input order.

    **`None` entries pass through as `None` but still count toward `m`.** This is the single most
    important line of reasoning in this module. `m`, the denominator of the BH correction, is
    supposed to be "how many hypotheses were tested" -- and an untestable condition (a guard failure,
    a zero-sample horizon, an evaluation error) still *consumed a trial*: it was one of the questions
    this scan asked. Excluding it from `m` would shrink the denominator every *other* entry's q-value
    is divided by, which mechanically makes every testable entry look stronger the more untestable
    entries the scan happens to contain. That is precisely the kind of manipulation-by-omission this
    whole module exists to prevent -- structurally identical to reporting "six discoveries out of six
    trials" after quietly dropping the other twenty-four attempts. So `m = len(p_values)` always, and
    a `None` keeps its seat in the ranking without ever receiving a rank of its own or a q-value.

    Procedure: rank the testable p-values ascending as `p_(1) <= ... <= p_(k)` (`k` testable among
    `m` total), form `q_(i) = min(1, p_(i) * m / i)`, then enforce step-up monotonicity by taking the
    cumulative minimum walking from the largest rank down to the smallest -- `q_(i) =
    min(q_(i), q_(i+1))` -- since without that pass a p-value smaller than its neighbour could
    otherwise receive a *larger* q-value, which the "adjusted p-value" framing promises can never
    happen.
    """
    m = len(p_values)
    result: list[float | None] = [None] * m
    if m == 0:
        return result

    testable = [(p, i) for i, p in enumerate(p_values) if p is not None]
    if not testable:
        return result

    # Rank ascending by p-value; ties keep their relative input order (stable sort).
    testable.sort(key=lambda pair: pair[0])
    k = len(testable)

    raw_q = [min(1.0, p * m / (rank + 1)) for rank, (p, _) in enumerate(testable)]

    # Step-up monotonicity: cumulative minimum from the largest rank down.
    adjusted = list(raw_q)
    for rank in range(k - 2, -1, -1):
        adjusted[rank] = min(adjusted[rank], adjusted[rank + 1])

    for (_, original_index), q in zip(testable, adjusted, strict=True):
        result[original_index] = q
    return result


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


class Evaluate(Protocol):
    """The per-(expression, horizon) collaborator :func:`scan` calls. Matches the shape of a guard
    check plus a single-horizon slice of what :mod:`app.backtest.events` computes for an
    :class:`~app.backtest.models.EventStudy`, without importing that module -- see the module
    docstring's "collaborators are injected" paragraph.

    ``indicator_cache`` is optional and keyword-only for the same reason
    :class:`app.rules.service.Evaluator` makes it optional: an implementation written before this
    parameter existed must not be broken by a caller that does not know to omit it. :func:`scan` only
    ever passes it when its own caller opted in by supplying ``indicator_cache=`` -- see the module
    docstring's "one IndicatorCache can be threaded through every evaluate call" paragraph.
    """

    def __call__(
        self,
        expression: str,
        horizon: int,
        *,
        indicator_cache: IndicatorCache | None = None,
    ) -> tuple[GuardReport, HorizonStats | None]: ...


def scan(
    symbol: str,
    interval: Interval,
    expressions: Sequence[str],
    horizons: Sequence[int],
    *,
    evaluate: Evaluate,
    entry: Entry = Entry.NEXT_OPEN,
    alpha: float = 0.10,
    bars: int = 0,
    first_bar: dt.date | None = None,
    last_bar: dt.date | None = None,
    warnings: Sequence[MarketWarning] | None = None,
    generated_at: dt.datetime | None = None,
    run_id: str | None = None,
    indicator_cache: IndicatorCache | None = None,
) -> ScanResult:
    """Run every (expression, horizon) pair through `evaluate`, correct across the whole set, and
    assemble a `ScanResult`.

    Every pair -- `len(expressions) * len(horizons)` of them -- produces exactly one `ScanEntry`,
    whatever `evaluate` returns for it, including a failed guard or a raised exception. `trials`
    always equals `len(entries)`: see `ScanResult`'s validator, which is the enforcement of that
    promise this module leans on rather than duplicates.

    `indicator_cache` defaults to `None`, which reproduces the exact call `evaluate(expression,
    horizon)` this function has always made -- every existing caller is unaffected. Passed one, it is
    forwarded as `indicator_cache=` on every call in the loop below, so an `Evaluate` implementation
    that threads it into `app.rules.evaluate.evaluate` shares indicator computation across every
    expression and horizon in this one scan. See the module docstring's "one IndicatorCache can be
    threaded through every evaluate call" paragraph.

    For each entry with a passing guard and measurable stats, the p-value is the exact two-sided
    binomial test of `HorizonStats.independent_sample_size` draws against
    `HorizonStats.baseline_hit_rate`, **never** against `sample_size` -- overlapping windows inflate
    the raw count and would shrink the p-value with no new information behind it (see
    `app.backtest.forward.independent_count`). The number of "successes" out of that independent
    sample is not directly observed -- only `hit_rate`, computed over the *full*, overlapping sample,
    is -- so it is approximated as `round(hit_rate * independent_sample_size)`. This is honestly an
    approximation, not a derivation: it assumes the hit rate among the independent subset matches the
    hit rate among the full overlapping sample, which is not guaranteed (the independent subset is a
    specific greedy-earliest selection, not a random one). The alternative of recomputing a hit rate
    directly from only the independent trigger dates would be more principled, but it is not
    available through this module's injected `Evaluate` seam -- `HorizonStats` as defined in
    `app.backtest.models` does not carry a separate independent-only hit rate, and adding one is a
    contract change outside the two files this module may touch. Rounding to the nearest integer
    (rather than floor or ceil) is the least-biased way to turn that approximate fraction into a
    whole count of successes for `binomial_p_value`.

    An entry is untestable -- `p_value = None`, `q_value = None`, `discovery = False`, and it still
    occupies a trial -- when its guard did not pass, when no stats were produced, when
    `independent_sample_size == 0` (nothing to test against the null), or when computing its
    p-value raises for any other reason: the `try`/`except` around the loop body covers both
    `evaluate` and the p-value computation for exactly this reason, so a raise anywhere in that
    pipeline folds into this same state -- one lost trial, never a lost table.
    """
    entries: list[ScanEntry] = []
    p_values: list[float | None] = []

    for expression in expressions:
        for horizon in horizons:
            try:
                if indicator_cache is not None:
                    guard, stats = evaluate(expression, horizon, indicator_cache=indicator_cache)
                else:
                    guard, stats = evaluate(expression, horizon)
                # The p-value computation is deliberately inside this same try: it reads `evaluate`'s
                # output and can raise on data this module cannot fully anticipate (an out-of-range
                # `baseline_hit_rate` a fabricated or upstream `HorizonStats` slipped through with,
                # an arithmetic edge case not yet seen). The trials invariant is this module's whole
                # reason to exist, and it cannot be kept by a loop that dies partway on *any*
                # exception, wherever in this block it originates. One expression raising must cost
                # exactly one entry -- the same "one bad rule must not empty the table" rule
                # `app.rules.service` follows.
                p_value = _entry_p_value(guard, stats)
            except Exception as exc:
                # Marked FAILED rather than UNVERIFIED because the guard genuinely did not clear it,
                # and a study must never render numbers for an entry in this state. This is the same
                # "untestable entry" state the module docstring and `scan`'s docstring already define
                # for a failed guard or missing stats -- a raise here is folded into that state
                # rather than inventing a new one, so it still consumes exactly one trial with
                # `p_value = None`, `q_value = None`, `discovery = False`.
                guard = GuardReport(
                    status=GuardStatus.FAILED,
                    expression=expression,
                    findings=[
                        GuardFinding(
                            check="evaluate",
                            passed=False,
                            detail=f"evaluation raised {type(exc).__name__}: {exc}",
                        )
                    ],
                )
                stats = None
                p_value = None
            entries.append(
                ScanEntry(
                    label=expression,
                    expression=expression,
                    horizon=horizon,
                    guard=guard,
                    stats=stats,
                    p_value=p_value,
                )
            )
            p_values.append(p_value)

    q_values = benjamini_hochberg(p_values)

    final_entries: list[ScanEntry] = []
    discoveries = 0
    for scan_entry, q_value in zip(entries, q_values, strict=True):
        discovery = q_value is not None and q_value <= alpha
        if discovery:
            discoveries += 1
        final_entries.append(scan_entry.model_copy(update={"q_value": q_value, "discovery": discovery}))

    return ScanResult(
        symbol=symbol.upper(),
        interval=interval,
        generated_at=generated_at or dt.datetime.now(dt.UTC),
        entry=entry,
        alpha=alpha,
        trials=len(final_entries),
        entries=final_entries,
        discoveries=discoveries,
        bars=bars,
        first_bar=first_bar,
        last_bar=last_bar,
        run_id=run_id,
        warnings=list(warnings) if warnings is not None else [],
    )


def _entry_p_value(guard: GuardReport, stats: HorizonStats | None) -> float | None:
    """The p-value for one scan entry, or `None` if it cannot be tested. See `scan`'s docstring for
    why `independent_sample_size` and `baseline_hit_rate` are the only inputs used."""
    if not guard.ok or stats is None:
        return None
    if stats.independent_sample_size <= 0:
        return None
    if stats.baseline_hit_rate is None or stats.hit_rate is None:
        return None

    successes = round(stats.hit_rate * stats.independent_sample_size)
    successes = max(0, min(successes, stats.independent_sample_size))
    return binomial_p_value(successes, stats.independent_sample_size, stats.baseline_hit_rate)
