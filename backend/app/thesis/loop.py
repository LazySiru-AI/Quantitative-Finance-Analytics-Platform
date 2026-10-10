"""Guard 4: a declared iteration budget, and the place the other three bind together.

"Loop until the thesis is proven" always terminates successfully, because there is always another
specification that works. So a run declares its budget before it starts, every iteration decrements
it whether or not it produced anything, and **exhausting the budget with nothing surviving is a
valid, reportable outcome** -- ``no thesis survived twelve attempts`` is real information about the
ticker, not a failed run.

The order of operations in :func:`run` is the design, and each step is placed where it is to close a
specific hole:

1. **Register first.** :func:`~app.thesis.preregister.register` then
   :func:`~app.thesis.ledger.record`, before a single bar is evaluated. A run that dies here has
   still spent its trial. Registering on *completion* would leave abandoned attempts invisible,
   which is hazard property (1).
2. **Test in-sample only.** The holdout frame is not passed to anything at this stage. It is not a
   rule that the loop must not peek; the bars are not in scope.
3. **Screen before spending the holdout.** A thesis that fails its own pre-declared falsification
   criterion in-sample is rejected here and *never touches the holdout*. There is one look per
   ticker, and spending it on something already refuted wastes the only out-of-sample test that
   ticker will ever get.
4. **Correct against the whole ledger**, not this run. The family is every thesis ever registered
   for the ticker, including the ones this run abandoned.
5. **One holdout claim, ever.** :func:`~app.thesis.holdout.claim` raises on the second attempt and
   records the burn.

**Direction is checked, not just magnitude.** A thesis predicting ``UP`` whose measured effect is
significantly negative is *refuted*, not confirmed. A loop that scored on ``abs(edge)`` would report
that as a discovery, which is how a mean-reversion claim survives on momentum data.

**At most one record per run may carry** :attr:`~app.thesis.models.Verdict.SURVIVED`, because at
most one thesis per run is ever holdout-tested. The catalogue's templates are correlated by
construction -- a 200-day SMA rule and a 50/200 EMA cross move together -- so a run that clears the
in-sample screen once often clears it again on the next template. Every candidate after the first is
downgraded to :attr:`~app.thesis.models.Verdict.INCONCLUSIVE` the moment it clears the screen with a
look already spoken for, whether that happens mid-loop (a later template also clears the bar) or
after the loop (the chosen candidate loses the holdout to a concurrent claim, see
:func:`~app.thesis.holdout.claim`). :class:`~app.thesis.models.LoopResult` enforces the resulting
invariant structurally -- see its ``model_validator``s -- so a producer bug here cannot silently
reintroduce an unconfirmed survivor the way an earlier version of this function did.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Protocol

import pandas as pd

from app.backtest.forward import describe as describe_returns
from app.backtest.forward import forward_returns, hit_rate, independent_count
from app.backtest.scan import binomial_p_value
from app.config import Settings, get_settings
from app.db.duck import Interval
from app.market import store
from app.market.models import BarSeries, MarketWarning
from app.market.registry import ProviderRegistry
from app.rules.models import Entry
from app.rules.nodes import BoolExpr
from app.thesis import author as author_module
from app.thesis import holdout as holdout_module
from app.thesis import ledger as ledger_module
from app.thesis import preregister
from app.thesis.models import (
    DEFAULT_ITERATION_BUDGET,
    Direction,
    Evidence,
    LoopOutcome,
    LoopResult,
    Thesis,
    ThesisRecord,
    ThesisStatus,
    Verdict,
)

__all__ = [
    "HOLDOUT_ALPHA",
    "MIN_INDEPENDENT_FOR_VERDICT",
    "SIGNIFICANCE_Q",
    "evaluate_thesis",
    "run",
]

#: Independent observations a thesis needs before any verdict other than inconclusive.
#:
#: Thirty is the line the plan draws for a small-sample caveat elsewhere, and a verdict is a stronger
#: statement than a caveat. Below this the honest answer is that the test had no power, which is
#: :attr:`~app.thesis.models.Verdict.INCONCLUSIVE` -- the expected outcome for most theses on most
#: tickers.
MIN_INDEPENDENT_FOR_VERDICT: int = 30

#: The q-value a thesis must clear, against the ticker's whole trial ledger, to survive.
#:
#: 0.10 rather than 0.05: this is a screening step whose output a human then examines, and the
#: expensive error is discarding a real effect rather than looking at one more card. The correction
#: is doing the heavy lifting regardless -- against a ledger of forty, a raw p of 0.01 does not clear
#: this.
SIGNIFICANCE_Q: float = 0.10

#: Unadjusted threshold the holdout must clear.
#:
#: Unadjusted deliberately. Everywhere else in this project a raw p-value is misleading because the
#: family is large and was searched; here it is one pre-registered test of one frozen thesis against
#: data nothing has looked at. That is the single situation where a raw p-value means what it says,
#: and it is the entire reason the holdout is worth reserving a quarter of the history for.
HOLDOUT_ALPHA: float = 0.05


class Evaluator(Protocol):
    """The subset of `app.rules.evaluate` this module needs.

    Typed with the real `BoolExpr` rather than `object`: a Protocol widening the parameter would not
    match the module it is meant to describe (a callable accepting `object` is not satisfied by one
    accepting only `BoolExpr`), and loosening it to satisfy the checker would mean the seam no longer
    describes what actually goes through it.
    """

    def evaluate(self, node: BoolExpr, bars: pd.DataFrame, *, interval: Interval) -> pd.Series: ...


class Grammar(Protocol):
    def parse(self, expression: str) -> BoolExpr: ...


def _default_grammar() -> Grammar:
    from app.rules import grammar

    return grammar


def _default_evaluator() -> Evaluator:
    from app.rules import evaluate

    return evaluate


def _bars_frame(series: BarSeries) -> pd.DataFrame:
    """Same construction as every other consumer -- see `app.rules.service._bars_frame`."""
    return pd.DataFrame(
        {
            "ts": pd.Series([b.ts for b in series.bars], dtype="datetime64[ns, UTC]"),
            **{
                column: pd.Series([getattr(b, column) for b in series.bars], dtype="float64")
                for column in ("open", "high", "low", "close", "adj_close", "volume")
            },
        }
    )


def evaluate_thesis(
    thesis: Thesis,
    bars: pd.DataFrame,
    *,
    grammar: Grammar | None = None,
    evaluator: Evaluator | None = None,
) -> Evidence:
    """Measure one thesis on one frame. Computes no statistics of its own.

    Everything here comes from :mod:`app.backtest.forward` and :mod:`app.backtest.scan` -- the same
    arithmetic the decision table and the workbench use, so a thesis cannot be scored by a second
    implementation that happens to be kinder.

    The p-value is the exact two-sided binomial of the *independent* trigger count against the
    unconditional hit rate over the same evaluable bars.
    """
    grammar_mod = grammar or _default_grammar()
    evaluator_mod = evaluator or _default_evaluator()

    if bars.empty:
        return Evidence(horizon=thesis.horizon)

    node = grammar_mod.parse(thesis.entry)
    signal = evaluator_mod.evaluate(node, bars, interval=thesis.interval)

    returns = forward_returns(bars, horizon=thesis.horizon, entry=Entry.NEXT_OPEN)
    known = signal.notna().to_numpy(dtype=bool)
    fired = signal.fillna(False).to_numpy(dtype=bool)
    import numpy as np

    evaluable = known & ~np.isnan(returns)
    triggered = evaluable & fired

    trigger_returns = returns[triggered]
    baseline_returns = returns[evaluable]
    positions = np.flatnonzero(triggered)
    independent = independent_count(positions, thesis.horizon)

    rate = hit_rate(trigger_returns)
    baseline = hit_rate(baseline_returns)

    p_value: float | None = None
    if rate is not None and baseline is not None and independent > 0:
        # Successes among the independent subset are not directly observed -- only the hit rate over
        # the full overlapping sample is -- so this is the same documented approximation
        # `app.backtest.scan` makes, and it is an approximation rather than a derivation.
        successes = round(rate * independent)
        p_value = binomial_p_value(successes, independent, baseline)

    return Evidence(
        horizon=thesis.horizon,
        hit_rate=rate,
        baseline_hit_rate=baseline,
        median_return=describe_returns(trigger_returns).median,
        baseline_median_return=describe_returns(baseline_returns).median,
        distribution=describe_returns(trigger_returns),
        sample_size=int(positions.size),
        independent_sample_size=independent,
        p_value=p_value,
    )


def _direction_agrees(thesis: Thesis, evidence: Evidence) -> bool:
    """Whether the measured effect points the way the thesis predicted.

    Checked separately from magnitude because a loop scoring on ``abs(edge)`` would count a
    significant effect in the *opposite* direction as a confirmation -- which is how a
    mean-reversion claim survives on momentum data.
    """
    edge = evidence.edge
    if edge is None:
        return False
    return edge > 0 if thesis.direction is Direction.UP else edge < 0


def _screen(thesis: Thesis, evidence: Evidence) -> Verdict:
    """The in-sample screen, before the holdout is spent.

    Three outcomes and the ordering matters: underpowered is checked *first*, so a tiny sample with a
    large edge is inconclusive rather than rejected. Rejecting it would be a stronger claim than the
    data supports in the other direction.
    """
    if evidence.independent_sample_size < MIN_INDEPENDENT_FOR_VERDICT:
        return Verdict.INCONCLUSIVE
    if not _direction_agrees(thesis, evidence):
        return Verdict.REJECTED
    return Verdict.SURVIVED


def _confirm(thesis: Thesis, evidence: Evidence) -> Verdict:
    """The holdout verdict. As strict as the in-sample screen, plus its own significance test.

    An earlier version asked only whether the holdout edge pointed the predicted way. On a driftless
    random walk that is a coin flip, so a thesis that squeaked through the in-sample screen had
    roughly even odds of being "confirmed" out-of-sample -- and the null-series test caught exactly
    that, reporting a survivor on pure noise at one seed in eight. A sign check is not a test.

    So the holdout must clear the same power floor as the in-sample screen *and* an unadjusted
    significance threshold. Unadjusted is correct here and not an oversight: this is one
    pre-registered test of one frozen thesis on data nothing has looked at, which is the single
    situation in this entire project where a raw p-value means what it says.

    A holdout too small to power the test yields :attr:`~app.thesis.models.Verdict.INCONCLUSIVE`, not
    ``SURVIVED``. "The out-of-sample period could not settle it" is the honest reading, and it is a
    different statement from "the effect was absent".
    """
    if evidence.independent_sample_size < MIN_INDEPENDENT_FOR_VERDICT:
        return Verdict.INCONCLUSIVE
    if not _direction_agrees(thesis, evidence):
        return Verdict.REJECTED
    if evidence.p_value is None or evidence.p_value > HOLDOUT_ALPHA:
        return Verdict.INCONCLUSIVE
    return Verdict.SURVIVED


def run(
    symbol: str,
    *,
    interval: Interval = Interval.DAY,
    budget: int = DEFAULT_ITERATION_BUDGET,
    settings: Settings | None = None,
    registry: ProviderRegistry | None = None,
    bars: pd.DataFrame | None = None,
    grammar: Grammar | None = None,
    evaluator: Evaluator | None = None,
) -> LoopResult:
    """One complete run against one ticker. See the module docstring for why the steps are ordered
    as they are.

    ``bars`` is injectable so a caller -- notably the null-series test, which is the most important
    test in this feature -- can point the whole loop at a synthetic series without touching the store.
    """
    cfg = settings or get_settings()
    upper = symbol.upper()
    started = dt.datetime.now(dt.UTC)
    warnings: list[MarketWarning] = []

    if bars is None:
        series = store.ensure_series(upper, interval, registry=registry, settings=cfg)
        warnings.extend(series.warnings)
        frame = _bars_frame(series)
    else:
        frame = bars

    def finish(outcome: LoopOutcome, records: list[ThesisRecord], used: int) -> LoopResult:
        return LoopResult(
            symbol=upper,
            interval=interval,
            started_at=started,
            finished_at=dt.datetime.now(dt.UTC),
            outcome=outcome,
            budget=budget,
            iterations_used=used,
            records=records,
            cards=[],
            ledger=ledger_module.stats_for(upper, settings=cfg),
            holdout=holdout_module.load(upper, settings=cfg),
            warnings=warnings,
        )

    if frame.empty:
        warnings.append(
            MarketWarning(kind="short_history", message=f"{upper}: no stored bars to test against")
        )
        return finish(LoopOutcome.NO_DATA, [], 0)

    try:
        state = holdout_module.establish(upper, frame, settings=cfg)
    except holdout_module.HoldoutUnavailable as exc:
        warnings.append(MarketWarning(kind="holdout_unavailable", message=f"{upper}: {exc}"))
        return finish(LoopOutcome.HOLDOUT_UNAVAILABLE, [], 0)

    in_sample, out_of_sample = holdout_module.split_frame(frame, state.split_date)

    # A thesis already carried to a terminal state is not re-evaluated. Without this, a second run
    # re-proposed the identical catalogue, re-tested every hash and *overwrote* the stored p-values
    # -- five of five changed on a re-run against different bars, while the trial count stayed at
    # five. The first evaluation vanished with no trace in the denominator, which is hazard property
    # (1) reappearing inside the very machinery built to prevent it. Registration is idempotent on
    # the content hash, so the ledger was right; it was the loop that was quietly re-rolling.
    already = {
        r.thesis_hash
        for r in ledger_module.records_for(upper, settings=cfg)
        if r.status
        in (ThesisStatus.IN_SAMPLE_TESTED, ThesisStatus.HOLDOUT_TESTED, ThesisStatus.ABANDONED)
    }

    proposals = author_module.propose(upper, interval)
    records: list[ThesisRecord] = []
    used = 0
    exhausted_catalogue = True
    survivor: ThesisRecord | None = None

    for thesis in proposals:
        if used >= budget:
            exhausted_catalogue = False
            break
        if preregister.content_hash(thesis) in already:
            # Not an iteration: nothing was proposed, tested or spent. The trial is already in the
            # ledger from the run that did test it, and counting it again would inflate the budget's
            # apparent effort without adding evidence.
            continue
        used += 1

        # 1. Register before anything runs. A crash from here on still leaves the trial behind.
        record = preregister.register(thesis)
        ledger_module.record(record, settings=cfg)

        # 2. In-sample only. The holdout frame is not in scope for this call.
        try:
            evidence = evaluate_thesis(
                thesis, in_sample, grammar=grammar, evaluator=evaluator
            )
        except Exception as exc:
            ledger_module.update_outcome(
                record.thesis_hash, status=ThesisStatus.ABANDONED, settings=cfg
            )
            records.append(record.model_copy(update={"status": ThesisStatus.ABANDONED}))
            warnings.append(
                MarketWarning(
                    kind="thesis_failed",
                    message=f"{thesis.hypothesis[:60]}...: could not be evaluated ({exc})",
                )
            )
            continue

        # 4. Correct against the ticker's whole ledger, filling this thesis's own slot.
        q_value, family = ledger_module.correct_over_ledger(
            upper, evidence.p_value, thesis_hash=record.thesis_hash, settings=cfg
        )
        evidence = evidence.model_copy(
            update={"q_value": q_value, "trials_at_evaluation": family}
        )

        # 3. Screen before spending the holdout.
        verdict = _screen(thesis, evidence)
        if verdict is Verdict.SURVIVED and (q_value is None or q_value > SIGNIFICANCE_Q):
            verdict = Verdict.INCONCLUSIVE

        # A ticker has exactly one holdout look, ever, and it is already spoken for the instant the
        # first in-sample screen clears -- `survivor` below is set once and never replaced. A second
        # (or third, or fourth) thesis clearing the same screen later in this loop can never be
        # confirmed: there is no second look to spend on it. Reporting it as SURVIVED here would be
        # claiming a confirmation that will never happen, which is exactly the defect this function
        # exists to not reproduce. INCONCLUSIVE is the honest reading -- the same "the out-of-sample
        # period could not settle it" reading `_confirm` gives a candidate whose holdout comes back
        # underpowered, and it is a normal, reportable result rather than a downgrade to apologize
        # for. The thesis is still registered and still counted in the ledger -- and, being
        # IN_SAMPLE_TESTED, it also joins `already` on a future run and is never re-proposed, since
        # re-proposing it would not change the answer: this ticker's one look is spent regardless of
        # which candidate it went to. Only the verdict changes here, never the trial.
        if verdict is Verdict.SURVIVED and survivor is not None:
            verdict = Verdict.INCONCLUSIVE

        updated = record.model_copy(
            update={
                "status": ThesisStatus.IN_SAMPLE_TESTED,
                "in_sample": evidence,
                "verdict": verdict,
            }
        )
        ledger_module.update_outcome(
            record.thesis_hash,
            status=ThesisStatus.IN_SAMPLE_TESTED,
            verdict=verdict,
            p_value=evidence.p_value,
            payload=updated.model_dump_json(),
            settings=cfg,
        )
        records.append(updated)

        if verdict is Verdict.SURVIVED and survivor is None:
            survivor = updated

    # 5. One holdout claim, ever -- and only for something that survived the in-sample screen.
    if survivor is not None:
        try:
            claimed = holdout_module.claim(upper, survivor.thesis_hash, settings=cfg)
        except holdout_module.HoldoutBurned as exc:
            warnings.append(MarketWarning(kind="holdout_burned", message=str(exc)))
            # `survivor` cleared the in-sample screen but lost the race for the ticker's one look --
            # someone else's claim landed first (see `TestRegressionsFromAdversarialQA
            # .test_concurrent_holdout_claims_grant_exactly_one_clean_look`). It is still sitting in
            # `records` with verdict=SURVIVED and holdout=None at this point, which is precisely the
            # unconfirmed-survivor shape `LoopResult` now refuses to construct. It was never refuted
            # and never confirmed, so INCONCLUSIVE is the honest verdict, exactly as it is for a
            # second in-sample survivor that never got a look -- the two are the same situation,
            # just reached by different timing.
            downgraded = survivor.model_copy(update={"verdict": Verdict.INCONCLUSIVE})
            ledger_module.update_outcome(
                survivor.thesis_hash,
                status=ThesisStatus.IN_SAMPLE_TESTED,
                verdict=Verdict.INCONCLUSIVE,
                payload=downgraded.model_dump_json(),
                settings=cfg,
            )
            records = [downgraded if r.thesis_hash == survivor.thesis_hash else r for r in records]
            return finish(LoopOutcome.HOLDOUT_UNAVAILABLE, records, used)

        holdout_evidence = evaluate_thesis(
            survivor.thesis, out_of_sample, grammar=grammar, evaluator=evaluator
        )
        final = _confirm(survivor.thesis, holdout_evidence)
        promoted = survivor.model_copy(
            update={
                "status": ThesisStatus.HOLDOUT_TESTED,
                "holdout": holdout_evidence,
                "verdict": final,
            }
        )
        ledger_module.update_outcome(
            survivor.thesis_hash,
            status=ThesisStatus.HOLDOUT_TESTED,
            verdict=final,
            payload=promoted.model_dump_json(),
            settings=cfg,
        )
        records = [promoted if r.thesis_hash == survivor.thesis_hash else r for r in records]
        del claimed

        if final is Verdict.SURVIVED:
            return finish(LoopOutcome.SURVIVOR_FOUND, records, used)

    # Which limit actually stopped the search. "No thesis survived twelve attempts" is information
    # about the ticker; "the author had five ideas and none worked" is information about the author,
    # and with a five-template catalogue against a budget of twelve the second was the usual case
    # while being reported as the first.
    outcome = (
        LoopOutcome.CATALOGUE_EXHAUSTED if exhausted_catalogue else LoopOutcome.BUDGET_EXHAUSTED
    )
    return finish(outcome, records, used)


def excluded_keys(symbol: str, *, settings: Settings | None = None) -> Sequence[str]:
    """Template keys already registered for this ticker, so a later run does not re-spend an
    iteration on a thesis the ledger already holds."""
    seen = {r.thesis.entry for r in ledger_module.records_for(symbol, settings=settings)}
    return [t.key for t in author_module.CATALOGUE if t.entry in seen]
