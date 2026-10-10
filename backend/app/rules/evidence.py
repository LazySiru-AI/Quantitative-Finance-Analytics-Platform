"""Historical evidence for a rule: what happened after it fired, versus what happens anyway.

See the module docstring on :mod:`app.rules.models` for the four honesty rules this module exists
to enforce. This file is the implementation; that one is the contract. Four things earn their own
paragraph here because each is an easy way to accidentally manufacture an edge that is not real:

**Return convention.** A rule evaluated on bar ``t`` uses ``t``'s close, which is only known once
the session has settled. :attr:`~app.rules.models.Entry.NEXT_OPEN` -- the default, and the only
convention anyone should read as an estimate -- prices the trade at the *next* bar's open and holds
it for exactly ``horizon`` bars, closing out at ``close[t + horizon]``::

    entry_idx = t + 1
    exit_idx  = entry_idx + horizon - 1 = t + horizon
    return    = close[exit_idx] / open[entry_idx] - 1

:attr:`~app.rules.models.Entry.SAME_CLOSE` reuses the identical ``entry_idx + horizon - 1`` window
but prices the entry at the signal bar's own close instead of the next bar's open::

    entry_idx = t
    exit_idx  = entry_idx + horizon - 1 = t + horizon - 1
    return    = close[exit_idx] / close[entry_idx] - 1

It exists only so a caller can see how much of a rule's apparent edge evaporates once the fill is
pushed to a price that was actually obtainable -- see ``TestLookahead`` in the test module for a
worked example where a same-bar spike-and-revert produces a large ``SAME_CLOSE`` "edge" out of pure
lookahead while ``NEXT_OPEN`` correctly sees nothing, because by the time a real order could have
been placed the reversion had already happened.

**Baseline.** ``hit_rate`` alone answers "how often did a gain follow a trigger"; it says nothing
without ``baseline_hit_rate``, the same measurement over *every* evaluable bar in the identical
sample (same horizon, same entry convention, same exclusions). A rule that fires on a coin flip
must show ``hit_rate`` close to ``baseline_hit_rate`` -- if it does not, the baseline was computed
wrong, not the rule right.

**Independence.** Overlapping forward windows are not independent draws: a trigger three bars apart
from the last one, under a 20-bar horizon, shares seventeen bars of the same price path with it.
:func:`~app.backtest.forward.independent_count` performs a greedy non-overlapping scan -- walk the
triggers in bar order, accept one, discard every later trigger within ``horizon`` bars of it, repeat
-- and :attr:`~app.rules.models.Evidence.significance` is judged against that count, never against
the raw ``sample_size``.

**The return convention itself lives in** :mod:`app.backtest.forward`, not here. This module used to
carry its own copy; the workbench needs the identical arithmetic, and two implementations agreeing
today is not a property anyone can maintain. When they drift, the decision table and the workbench
report different numbers for the same question with nothing to say which is right.

**Unknown is not false.** ``pd.NA`` in ``signal`` means the rule had no truth value on that bar
(indicator warmup, a data gap). Those bars are dropped from both the trigger set and the baseline
denominator -- counting them as quiet "did not fire" bars would pad the baseline with sessions the
rule was never actually asked about.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Final

import numpy as np
import pandas as pd

from app.backtest.forward import forward_returns as _forward_returns
from app.backtest.forward import hit_rate as _rate
from app.backtest.forward import independent_count as _independent_count
from app.market.models import jsonable_float
from app.rules.models import (
    HORIZONS,
    Entry,
    Evidence,
    RuleState,
    Significance,
    SignificanceCriteria,
    TriState,
)

__all__ = ["compute_evidence", "rule_state", "significance_criteria"]


# ---------------------------------------------------------------------------
# Significance thresholds
# ---------------------------------------------------------------------------
#
# Deliberately not a p-value -- see `Significance`'s docstring for why one would be dishonest here
# (multiple rules, no correction, a human who already looked at this history before writing the
# rule). Instead this leans on a rough intuition about how many *independent* Bernoulli draws it
# takes before an observed proportion is more likely to be signal than sampling noise: the standard
# error of a proportion is `sqrt(0.25 / n)`, which is already ~18 percentage points at n=8 and still
# ~9 points at n=30. Both thresholds below sit comfortably above that noise floor for their sample
# size, and both are picked to err toward INSUFFICIENT when in doubt -- a false "nothing here" costs
# a second look in the workbench; a false "worth a look" costs a place in a live decision table.

#: Minimum independent (non-overlapping) triggers before any claim is entertained at all.
_MIN_INDEPENDENT_WEAK: Final[int] = 8
#: Minimum independent triggers, and minimum |edge| in hit-rate percentage points, for SUGGESTIVE.
_MIN_INDEPENDENT_SUGGESTIVE: Final[int] = 30
_MIN_EDGE_WEAK: Final[float] = 0.15
_MIN_EDGE_SUGGESTIVE: Final[float] = 0.08


def significance_criteria() -> SignificanceCriteria:
    """The thresholds behind every grade in a decision table, in a form the UI can render.

    Built from the constants above rather than restated anywhere, so the legend a user reads and
    the rule the code applies cannot drift apart. That is the whole reason this is a function on
    this module and not a paragraph in a component.

    Surfaced because a UAT persona pointed out that the Scan page names its method (Benjamini-
    Hochberg) while the decision table grades every rule "insufficient" with no stated test or
    threshold beside it -- so the grade read as an opinion rather than as a rule the reader could
    check a row against.
    """
    return SignificanceCriteria(
        weak_min_independent=_MIN_INDEPENDENT_WEAK,
        weak_min_edge=_MIN_EDGE_WEAK,
        suggestive_min_independent=_MIN_INDEPENDENT_SUGGESTIVE,
        suggestive_min_edge=_MIN_EDGE_SUGGESTIVE,
    )


def _validate_alignment(signal: pd.Series, bars: pd.DataFrame) -> None:
    """Refuse a signal whose index does not exactly match the bars it is scored against.

    A signal built against a different (or differently-ordered, or differently-filtered) index than
    the bars it is later zipped with is a lookahead bug wearing a disguise: row ``i`` of ``signal``
    would silently pair with the wrong bar's forward return, and the resulting edge would look like
    a discovery right up until it was traded.
    """
    if not signal.index.equals(bars.index):
        raise ValueError(
            "signal.index must exactly match bars.index; a misaligned signal/bars pair silently "
            "pairs each trigger with the wrong bar's forward return"
        )
    if signal.dtype != "boolean":
        raise TypeError(f"signal must have dtype 'boolean' (nullable), got {signal.dtype!r}")


def _median(values: np.ndarray) -> float | None:
    if values.size == 0:
        return None
    return jsonable_float(float(np.median(values)))


def _significance(independent_sample_size: int, edge: float | None) -> Significance:
    """See the module-level threshold constants for the reasoning. Coarse and one-directional: it
    only ever upgrades away from INSUFFICIENT when both the sample and the effect clear their bar
    together, never on either alone."""
    if edge is None:
        return Significance.INSUFFICIENT
    magnitude = abs(edge)
    if (
        independent_sample_size >= _MIN_INDEPENDENT_SUGGESTIVE
        and magnitude >= _MIN_EDGE_SUGGESTIVE
    ):
        return Significance.SUGGESTIVE
    if independent_sample_size >= _MIN_INDEPENDENT_WEAK and magnitude >= _MIN_EDGE_WEAK:
        return Significance.WEAK
    return Significance.INSUFFICIENT


def _evidence_for_horizon(
    signal: pd.Series, bars: pd.DataFrame, *, horizon: int, entry: Entry
) -> Evidence:
    returns = _forward_returns(bars, horizon=horizon, entry=entry)

    known_mask = signal.notna().to_numpy(dtype=bool)
    # `.fillna(False)` is safe here only because it is intersected with `known_mask` below: an
    # unknown bar is never allowed to count as a non-trigger baseline row via this cast, it is
    # dropped from both sets entirely, same as the module docstring requires.
    true_mask = signal.fillna(False).to_numpy(dtype=bool)

    evaluable = known_mask & ~np.isnan(returns)
    triggered = evaluable & true_mask

    baseline_sample = returns[evaluable]
    trigger_sample = returns[triggered]

    hit_rate = _rate(trigger_sample)
    baseline_hit_rate = _rate(baseline_sample)
    edge = None if hit_rate is None or baseline_hit_rate is None else hit_rate - baseline_hit_rate

    trigger_positions = np.flatnonzero(triggered)
    independent_sample_size = _independent_count(trigger_positions, horizon)

    return Evidence(
        horizon=horizon,
        entry=entry,
        hit_rate=hit_rate,
        baseline_hit_rate=baseline_hit_rate,
        median_return=_median(trigger_sample),
        baseline_median_return=_median(baseline_sample),
        sample_size=int(trigger_positions.size),
        independent_sample_size=independent_sample_size,
        significance=_significance(independent_sample_size, edge),
    )


def compute_evidence(
    signal: pd.Series,
    bars: pd.DataFrame,
    *,
    horizons: Sequence[int] = HORIZONS,
    entry: Entry = Entry.NEXT_OPEN,
) -> list[Evidence]:
    """One :class:`~app.rules.models.Evidence` per horizon, in the order given.

    ``signal`` must share ``bars.index`` exactly (see :func:`_validate_alignment`) and carry the
    nullable ``"boolean"`` dtype, so ``pd.NA`` can express "this rule had no truth value here" as
    distinct from ``False``.
    """
    _validate_alignment(signal, bars)
    return [
        _evidence_for_horizon(signal, bars, horizon=horizon, entry=entry) for horizon in horizons
    ]


def rule_state(signal: pd.Series, bars: pd.DataFrame) -> RuleState:
    """The rule's current state, read off the most recent settled bar.

    Session dates come straight from ``bars["ts"]``: the store already normalises a daily bar's
    timestamp to that session's date at midnight UTC (see `app.market.models`'s module docstring),
    so no further timezone conversion belongs here -- doing one would be as likely to shift the date
    as to preserve it.
    """
    _validate_alignment(signal, bars)
    n = len(bars)
    if n == 0:
        return RuleState(
            state=TriState.UNKNOWN,
            as_of=None,
            last_trigger=None,
            bars_since_trigger=None,
            triggers_in_history=0,
        )

    ts = bars["ts"]
    if ts.dt.tz is None:
        raise ValueError("bars['ts'] must be timezone-aware UTC")
    dates: pd.Series = ts.dt.date

    last_value = signal.iloc[-1]
    if pd.isna(last_value):
        state = TriState.UNKNOWN
    elif bool(last_value):
        state = TriState.TRUE
    else:
        state = TriState.FALSE

    true_positions = np.flatnonzero(signal.fillna(False).to_numpy(dtype=bool))
    triggers_in_history = int(true_positions.size)
    last_trigger: dt.date | None
    bars_since_trigger: int | None
    if triggers_in_history == 0:
        last_trigger = None
        bars_since_trigger = None
    else:
        last_idx = int(true_positions[-1])
        last_trigger = dates.iloc[last_idx]
        bars_since_trigger = (n - 1) - last_idx

    return RuleState(
        state=state,
        as_of=dates.iloc[-1],
        last_trigger=last_trigger,
        bars_since_trigger=bars_since_trigger,
        triggers_in_history=triggers_in_history,
    )
