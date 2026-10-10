"""Assembles the decision table: bars in, one evaluated row per rule out.

This is the composition layer for Phase 6, in the same spirit as :mod:`app.market.macro` composes
FRED, CNN and the bar store into one snapshot. It owns no parsing, no evaluation maths and no
evidence statistics of its own -- :mod:`app.rules.grammar`, :mod:`app.rules.evaluate` and
:mod:`app.rules.evidence` own those -- but it owns three things that only exist at this seam:

**One bad rule must not empty the table.** A rule that fails to parse, that references an indicator
this interval does not support, or that fails to evaluate still produces a :class:`~app.rules.models.
DecisionRow` -- carrying a :class:`~app.market.models.MarketWarning` that says why -- rather than
being dropped. A table a user reads as "every catalogued rule, evaluated" must not silently shrink
because one entry had a typo; see :func:`_degraded_row`.

**Bars are fetched and framed exactly once per table, not once per rule.** :func:`build_decision_table`
reads the store a single time via :func:`app.market.store.ensure_series` -- the same entry point
``/api/market/bars`` uses, so a rule sees exactly the bars a chart for the same symbol/interval would
-- and converts the result to the ``pandas`` frame every rule's :func:`~app.rules.evaluate.evaluate`
call shares. Twelve rules therefore cost one store read and one frame build, not twelve.

**Identical rule conditions are evaluated once, and different ones sharing an indicator compute it
once between them.** :func:`~app.rules.grammar.render` turns a parsed tree back into its canonical
text; two catalog entries that happen to describe the same condition (or a caller passing a duplicate
rule) collapse onto one :func:`~app.rules.evaluate.evaluate` call and share its signal via
``signal_cache``, keyed by that rendered text. That dedupes whole conditions, but ``rsi_oversold`` and
``rsi_overbought`` render to different text and would never share a ``signal_cache`` entry even though
both want ``rsi:14`` computed against the same bars -- for that, :func:`build_decision_table` also
builds a request-scoped :class:`~app.rules.evaluate.IndicatorCache` and hands it to every ``evaluate()``
call, so the underlying indicator is computed once regardless of which rule asked for it first. The two
caches are deliberately separate and complementary: ``signal_cache`` dedupes whole evaluated conditions,
``IndicatorCache`` dedupes the indicator computations *inside* conditions that otherwise differ. Both
are caller-owned (built fresh per table, discarded when this function returns) rather than module-level
state, for the same reason patching :mod:`app.indicators.registry` for the duration of a request was
ruled out: these endpoints run synchronously, FastAPI dispatches sync handlers to a thread pool, and two
concurrent requests mutating and restoring the same module-level function would race. Nothing here
mutates anything beyond a dict this function itself allocated and will drop on return.

**The three collaborators are injectable**, matching how :func:`app.market.macro.build_snapshot` takes
``fred=``/``cnn=``/``registry=``: ``grammar``, ``evaluator`` and ``evidence`` default to the real
modules, imported lazily inside :func:`_default_grammar` / :func:`_default_evaluator` /
:func:`_default_evidence` so this module -- and its tests -- stay importable even while
``app.rules.grammar`` and ``app.rules.evidence`` are still being written elsewhere in this phase.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Protocol

import pandas as pd

from app.config import Settings
from app.db.duck import Interval
from app.market import store
from app.market.models import BarSeries, MarketWarning
from app.market.registry import ProviderRegistry
from app.rules import catalog as catalog_module
from app.rules.evaluate import IndicatorCache
from app.rules.models import (
    DecisionRow,
    DecisionTable,
    Evidence,
    Rule,
    RuleState,
    SignificanceCriteria,
    TriState,
)
from app.rules.nodes import BoolExpr

__all__ = ["build_decision_table"]


# ---------------------------------------------------------------------------
# Injectable collaborators
# ---------------------------------------------------------------------------


class Grammar(Protocol):
    """The subset of `app.rules.grammar` this module (and `app.api.rules`) calls.

    Not underscore-prefixed: `app.api.rules` reuses this exact type for its own `/validate`
    collaborator hook rather than redeclaring an equivalent Protocol, so the two routers' notion of
    "a grammar module" cannot drift apart."""

    def parse(self, expression: str) -> BoolExpr: ...

    def render(self, node: BoolExpr) -> str: ...


class Evaluator(Protocol):
    """The subset of `app.rules.evaluate` this module (and `app.api.rules`) calls. See `Grammar`.

    `indicator_cache` is optional and keyword-only so a substituted `Evaluator` -- a test double, or
    any implementation written before this parameter existed -- can still ignore it and remain a
    structural match for this Protocol. `build_decision_table` always constructs a real
    `IndicatorCache` and always passes it: conformance to this widened signature is `mypy --strict`'s
    job, not a runtime check -- see the module docstring's "the three collaborators are injectable"
    paragraph and this module's test suite, where `FakeEvaluator` declares the parameter for exactly
    this reason.
    """

    def evaluate(
        self,
        node: BoolExpr,
        bars: pd.DataFrame,
        *,
        interval: Interval,
        indicator_cache: IndicatorCache | None = None,
    ) -> pd.Series: ...

    def required_specs(self, node: BoolExpr) -> list[str]: ...


class EvidenceBuilder(Protocol):
    """The subset of `app.rules.evidence` this module calls."""

    def compute_evidence(self, signal: pd.Series, bars: pd.DataFrame) -> list[Evidence]: ...

    def rule_state(self, signal: pd.Series, bars: pd.DataFrame) -> RuleState: ...


def _default_grammar() -> Grammar:
    from app.rules import grammar

    return grammar


def _default_evaluator() -> Evaluator:
    from app.rules import evaluate

    return evaluate


def _default_evidence() -> EvidenceBuilder:
    from app.rules import evidence

    return evidence


def _significance_criteria() -> SignificanceCriteria:
    from app.rules.evidence import significance_criteria

    return significance_criteria()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_decision_table(
    cfg: Settings,
    symbol: str,
    interval: Interval,
    *,
    rules: Sequence[Rule] | None = None,
    registry: ProviderRegistry | None = None,
    grammar: Grammar | None = None,
    evaluator: Evaluator | None = None,
    evidence: EvidenceBuilder | None = None,
) -> DecisionTable:
    """One decision table: every rule in `rules` (the full catalog by default), for one instrument.

    A `~app.market.providers.base.ProviderError` from the store -- a confirmed-missing symbol, or
    every provider down with nothing already stored -- is not caught here and propagates to the
    caller, exactly as `app.market.store.ensure_series` raises it for `/api/market/bars`; the API
    layer maps it to a status the same way `app.api.market._handle` does. A symbol the store *can*
    answer but holds no bars for (a valid ticker with nothing synced yet) is not an error: the table
    comes back with `bars_evaluated=0` and no rows, carrying a warning that says why, rather than a
    500 or a table of rows nobody could have derived from zero bars. See the module docstring for
    what "one bad rule" means and why identical rules share one evaluation.
    """
    grammar_mod = grammar or _default_grammar()
    evaluator_mod = evaluator or _default_evaluator()
    evidence_mod = evidence or _default_evidence()
    rule_list = list(rules) if rules is not None else catalog_module.catalog()
    upper = symbol.upper()

    series = store.ensure_series(upper, interval, registry=registry, settings=cfg)
    warnings: list[MarketWarning] = list(series.warnings)
    bars = _bars_frame(series)
    generated_at = dt.datetime.now(dt.UTC)

    if bars.empty:
        warnings.append(
            MarketWarning(
                kind="short_history",
                message=(
                    f"{upper} {interval.value}: no stored bars -- the decision table is empty "
                    "until data is synced for this symbol and interval"
                ),
            )
        )
        return DecisionTable(
            symbol=upper,
            interval=interval,
            generated_at=generated_at,
            bars_evaluated=0,
            first_bar=None,
            last_bar=None,
            rows=[],
            warnings=warnings,
        )

    rows: list[DecisionRow] = []
    # Keyed by the tree's canonical rendered text -- see the module docstring's "identical rule
    # conditions are evaluated once" paragraph.
    signal_cache: dict[str, pd.Series] = {}
    # Shared indicator computation *across* differently-rendered rule trees -- see the same
    # paragraph. Built unconditionally: `Evaluator` is typed to require this parameter (see its
    # docstring), so any collaborator that structurally matches the Protocol -- including a
    # substituted test double -- is guaranteed to accept it, and `mypy --strict` is what enforces
    # that rather than a runtime check.
    indicator_cache = IndicatorCache()

    for rule in rule_list:
        if rule.intervals and interval not in rule.intervals:
            allowed = ", ".join(sorted(i.value for i in rule.intervals))
            rows.append(
                _degraded_row(
                    rule,
                    kind="unsupported_interval",
                    message=(
                        f"{rule.rule_id}: not defined on {interval.value} bars (only {allowed})"
                    ),
                )
            )
            continue

        try:
            node = grammar_mod.parse(rule.expression)
        except Exception as exc:  # a catalog or user rule can carry any parser-defined failure
            rows.append(_degraded_row(rule, kind="parse_error", message=f"{rule.rule_id}: {exc}"))
            continue

        try:
            cache_key = grammar_mod.render(node)
        except Exception:
            # Rendering only formats an already-parsed tree back to text for display and as this
            # cache's key; a tree that just parsed successfully failing to render is not expected,
            # but this row's own evaluation must not be lost over a display-only failure. Falling
            # back to the rule's own expression still gives every rule *some* cache key, just one
            # that cannot collide with a different rule's differently-spelled equivalent condition.
            cache_key = rule.expression

        try:
            if cache_key in signal_cache:
                signal = signal_cache[cache_key]
            else:
                signal = evaluator_mod.evaluate(
                    node, bars, interval=interval, indicator_cache=indicator_cache
                )
                signal_cache[cache_key] = signal
        except Exception as exc:
            rows.append(_degraded_row(rule, kind="evaluate_error", message=f"{rule.rule_id}: {exc}"))
            continue

        try:
            state = evidence_mod.rule_state(signal, bars)
            row_evidence = evidence_mod.compute_evidence(signal, bars)
        except Exception as exc:
            rows.append(_degraded_row(rule, kind="evidence_error", message=f"{rule.rule_id}: {exc}"))
            continue

        rows.append(DecisionRow(rule=rule, state=state, evidence=row_evidence, warnings=[]))

    # `bars` is guaranteed non-empty here -- the empty case already returned above.
    return DecisionTable(
        symbol=upper,
        interval=interval,
        generated_at=generated_at,
        bars_evaluated=len(bars),
        first_bar=bars["ts"].min().date(),
        last_bar=bars["ts"].max().date(),
        rows=rows,
        # Imported directly rather than taken off the injected `EvidenceBuilder`: the thresholds are
        # a constant of how this system grades, not per-call behaviour a fake would want to vary, and
        # widening the Protocol for them would make every test double carry a method none of them
        # care about. Local import to match `_default_evidence`'s deferral.
        criteria=_significance_criteria(),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _bars_frame(series: BarSeries) -> pd.DataFrame:
    """The OHLCV frame `evaluate()` and `evidence.py` expect, built once for the whole table.

    Same construction `app.api.market.indicator_series` uses for the chart's own indicator overlays:
    `ts` as tz-aware UTC, every price column explicit `float64` so a `None` volume on a halted
    session does not leave the column `object`-dtyped and silently fall back to slow, differently
    behaved arithmetic in every downstream rolling/ewm call.
    """
    return pd.DataFrame(
        {
            "ts": pd.Series([b.ts for b in series.bars], dtype="datetime64[ns, UTC]"),
            **{
                column: pd.Series([getattr(b, column) for b in series.bars], dtype="float64")
                for column in ("open", "high", "low", "close", "adj_close", "volume")
            },
        }
    )


def _degraded_row(rule: Rule, *, kind: str, message: str) -> DecisionRow:
    """A row for a rule that could not be evaluated on this table -- still appears, with why.

    `app.rules.models.DecisionRow`'s docstring is explicit that this is the required behaviour: a row
    that could not be evaluated must not silently vanish from a table the user reads as complete.
    `TriState.UNKNOWN` is the correct state here for the same reason it is correct through an
    indicator's warmup window -- this row was never actually evaluated `True` or `False`.
    """
    return DecisionRow(
        rule=rule,
        state=RuleState(state=TriState.UNKNOWN),
        evidence=[],
        warnings=[MarketWarning(kind=kind, message=message)],
    )
