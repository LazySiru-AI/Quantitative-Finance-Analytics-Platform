"""Bull and bear cases over one :class:`~app.thesis.models.StrategyCard`'s fixed statistics.

The debate is about interpretation, never about the numbers: both sides read the same
:class:`~app.report.models.FactBundle` :mod:`app.thesis.strategycard` already built, and neither
side may say anything the bundle cannot support. That is enforced by routing every point through the
identical ``{{fact:id}}`` discipline :mod:`app.report.narrative` enforces for the Phase 8 per-holding
report -- this module calls :func:`app.report.narrative.verify`, it does not write a second checker.

**No LLM is configured, and none is needed.** Every point below is a fixed Python string template
selected by which facts the bundle actually holds, exactly the pattern
:func:`app.report.narrative.draft_evidence` and its siblings use: a point whose required facts are
missing, or present with a ``None`` value, is silently dropped rather than rendered with a gap in it.
Deterministic and reproducible -- the same card always produces the same debate.

**The bear case must draw blood.** Per the module's charter, it is not enough to say "there is
uncertainty" -- it must name the specific condition under which the strategy loses money and how
often that condition occurred historically. :func:`_bear_worst_case` does that from
``expected_return.p05`` and ``worst_trade``; :func:`_bear_regime` does it again, more specifically,
from whichever :class:`~app.thesis.models.RegimeSlice` the bundle shows the weakest edge in, and
states the bar count -- literally how often that regime occurred in the sample.

Every :class:`DebatePoint` carries **template** text, not rendered prose -- ``{{fact:...}}``
references, exactly like :class:`~app.report.models.NarrativeDraft`. A caller renders it against the
card's own bundle with :func:`app.report.narrative.render` when it is time to display, so the debate
can never drift from the figures it describes. This is also why ``narrative.verify`` is the correct
test of "did this module invent anything": run against the template text, not the rendered output.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.report import narrative
from app.report.models import FactBundle, NarrativeDraft
from app.thesis.models import RegimeSlice, StrategyCard

__all__ = ["Debate", "DebatePoint", "build_debate"]


class DebatePoint(BaseModel):
    """One argument, grounded in the bundle it cites.

    ``text`` is template text -- ``{{fact:id}}`` references and no bare numerals, verified against
    the bundle at construction time via :func:`app.report.narrative.verify`. It is not rendered here;
    render it against the same :class:`~app.report.models.FactBundle` with
    :func:`app.report.narrative.render` to display it, the same as any other Phase 8 narrative.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    fact_ids: tuple[str, ...]
    """Every fact id this point cites, in order of first appearance. A subset of what
    ``narrative.verify`` would report as ``cited`` for this text -- kept here directly so a caller
    does not have to re-parse the template to know what backs a point."""


class Debate(BaseModel):
    """The bull and bear cases for one card. Either side may be empty when the bundle does not carry
    enough to support a given point -- an empty side is honest, not a bug to paper over with a
    fallback sentence that cites nothing."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    bull: tuple[DebatePoint, ...] = ()
    bear: tuple[DebatePoint, ...] = ()


#: Regime label -> plain-English condition name. Words, not numbers, so they never trip the bare-
#: numeral check; the numbers that back each description are cited separately as facts.
_REGIME_DESCRIPTIONS: dict[str, str] = {
    "high_volatility": "high-volatility",
    "low_volatility": "low-volatility",
    "uptrend": "uptrend",
    "downtrend": "downtrend",
}


def _available(bundle: FactBundle, fact_ids: tuple[str, ...]) -> bool:
    """Every cited fact must be both present and non-``None``.

    Mirrors the gate :func:`app.report.narrative._sentence` applies before offering a template
    sentence: a *missing* fact is refused by ``narrative.verify`` on its own, but a fact that is
    present with value ``None`` verifies fine (it renders as an em dash) and would still produce a
    debate point with a blank in it -- "the edge in high-volatility conditions was --" reads as a
    finding, not as an absence, and a debate point should never do that.
    """
    for fact_id in fact_ids:
        fact = bundle.get(fact_id)
        if fact is None or fact.value is None:
            return False
    return True


def _point(template: str, fact_ids: tuple[str, ...], bundle: FactBundle) -> DebatePoint | None:
    """A point if every cited fact is available and the template verifies; ``None`` otherwise.

    Verification is delegated entirely to :func:`app.report.narrative.verify` -- this function does
    not decide on its own whether a ``{{fact:...}}`` reference is well-formed or whether a numeral is
    bare, because that is exactly the checker :mod:`app.report.narrative` already owns.
    """
    if not _available(bundle, fact_ids):
        return None
    draft = NarrativeDraft(text=template, source="template")
    grounding = narrative.verify(draft, bundle)
    if not grounding.grounded:  # pragma: no cover - a template/bundle id mismatch is a bug to fix
        return None
    return DebatePoint(text=template, fact_ids=fact_ids)


# ---------------------------------------------------------------------------------------------
# Bull case
# ---------------------------------------------------------------------------------------------


def _bull_edge(bundle: FactBundle) -> DebatePoint | None:
    return _point(
        "The measured hit rate was {{fact:evidence.hit_rate}} against an unconditional baseline of "
        "{{fact:evidence.baseline_hit_rate}} -- an edge of {{fact:evidence.edge}} across "
        "{{fact:evidence.independent_n}} independent observations.",
        ("evidence.hit_rate", "evidence.baseline_hit_rate", "evidence.edge", "evidence.independent_n"),
        bundle,
    )


def _bull_holdout(bundle: FactBundle) -> DebatePoint | None:
    return _point(
        "The effect held on the holdout: {{fact:holdout.hit_rate}} against a baseline of "
        "{{fact:holdout.baseline_hit_rate}} at p={{fact:holdout.p_value}}, on "
        "{{fact:holdout.independent_n}} independent observations the thesis was never screened "
        "against before this test.",
        (
            "holdout.hit_rate",
            "holdout.baseline_hit_rate",
            "holdout.p_value",
            "holdout.independent_n",
        ),
        bundle,
    )


def _bull_frequency(bundle: FactBundle) -> DebatePoint | None:
    return _point(
        "The rule fires often enough to trade: {{fact:triggers_per_year}} triggers a year, with a "
        "median holding period of {{fact:holding_period.median}} bars.",
        ("triggers_per_year", "holding_period.median"),
        bundle,
    )


def _bull_frequency_only(bundle: FactBundle) -> DebatePoint | None:
    return _point(
        "The rule fires {{fact:triggers_per_year}} times a year.",
        ("triggers_per_year",),
        bundle,
    )


# ---------------------------------------------------------------------------------------------
# Bear case
# ---------------------------------------------------------------------------------------------


def _bear_worst_case(bundle: FactBundle) -> DebatePoint | None:
    """The headline bear point: what the worst outcomes actually looked like, not a generic
    disclaimer. Cites the distribution's own 5th percentile (``expected_return.p05``) and the single
    worst realised trade from the backtest -- both computed by existing engines, neither invented
    here. The template names the tail in words rather than as "5%": ``narrative.verify`` refuses any
    bare digit, including one that happens to be correct, so even a true number has to arrive as a
    fact reference -- exactly the discipline this module exists to enforce on itself as much as on
    a narrative it might feed."""
    return _point(
        "Near the bottom of the distribution's tail, across {{fact:expected_return.count}} measured "
        "outcomes, the forward return was {{fact:expected_return.p05}} or worse, and the single "
        "worst realised trade in the backtest lost {{fact:worst_trade}}.",
        ("expected_return.count", "expected_return.p05", "worst_trade"),
        bundle,
    )


def _bear_worst_case_no_trade(bundle: FactBundle) -> DebatePoint | None:
    """As :func:`_bear_worst_case`, for a card with no backtest trades to cite a worst trade from --
    still names the tail of the distribution, which came from the loop's own evidence."""
    return _point(
        "Near the bottom of the distribution's tail, across {{fact:expected_return.count}} measured "
        "outcomes, the forward return was {{fact:expected_return.p05}} or worse.",
        ("expected_return.count", "expected_return.p05"),
        bundle,
    )


def _bear_regime(card: StrategyCard, bundle: FactBundle) -> DebatePoint | None:
    """Names the specific market condition under which the edge is weakest or reverses, and how often
    that condition occurred historically -- the regime slice's own bar count. Selecting "weakest
    measured edge" from the regime slices is a read of numbers :mod:`app.thesis.strategycard` already
    computed, not a new statistical claim; the cited p-value and independent-n let a reader judge for
    themselves whether that weak slice is itself well powered."""
    worst: RegimeSlice | None = None
    worst_edge: float | None = None
    for regime in card.regimes:
        if regime.evidence is None or regime.evidence.edge is None:
            continue
        if worst_edge is None or regime.evidence.edge < worst_edge:
            worst_edge = regime.evidence.edge
            worst = regime

    if worst is None:
        return None
    label = worst.label
    description = _REGIME_DESCRIPTIONS.get(label, label.replace("_", " "))
    prefix = f"regime.{label}"
    return _point(
        f"The edge is weakest in {description} conditions, which this history spent "
        f"{{{{fact:{prefix}.bars}}}} bars in: there the measured edge was {{{{fact:{prefix}.edge}}}} "
        f"against a baseline hit rate of {{{{fact:{prefix}.baseline_hit_rate}}}}, on "
        f"{{{{fact:{prefix}.independent_n}}}} independent observations.",
        (f"{prefix}.bars", f"{prefix}.edge", f"{prefix}.baseline_hit_rate", f"{prefix}.independent_n"),
        bundle,
    )


def _bear_conditional(card: StrategyCard, bundle: FactBundle) -> DebatePoint | None:
    """If :mod:`app.thesis.strategycard` flagged the edge as conditional (present on one side of a
    regime pair and absent or reversed on the other), say so plainly and point at the regime slices
    rather than repeating the warning's own free text, which is not a cited fact and could not pass
    ``narrative.verify``."""
    if not any(w.kind == "conditional_edge" for w in card.warnings):
        return None
    return _point(
        "This edge is conditional, not unconditional: it is not consistent across both sides of at "
        "least one high/low-volatility or uptrend/downtrend split. See the regime slices for the "
        "specific numbers on each side before treating it as a property of the instrument as a "
        "whole.",
        (),
        bundle,
    )


def _bear_tax(bundle: FactBundle) -> DebatePoint | None:
    return _point(
        "After the strategy's own wash sales and an assumed top-bracket tax rate, the return falls "
        "from a gross {{fact:tax.gross_return}} to an after-tax {{fact:tax.after_tax_return}}, with "
        "{{fact:tax.wash_sales_triggered}} wash sales the rule would have triggered against itself "
        "by re-entering after its own losing exits.",
        ("tax.gross_return", "tax.after_tax_return", "tax.wash_sales_triggered"),
        bundle,
    )


def _bear_selection(bundle: FactBundle) -> DebatePoint | None:
    return _point(
        "This ticker's ledger has tested {{fact:ledger.total_trials}} theses, of which "
        "{{fact:ledger.rejected}} were rejected and {{fact:ledger.inconclusive}} were inconclusive: "
        "a single survivor drawn from a large family of attempts is weaker evidence than the same "
        "result would be as the only thesis ever tested on this ticker.",
        ("ledger.total_trials", "ledger.rejected", "ledger.inconclusive"),
        bundle,
    )


def _bear_cost_drag(bundle: FactBundle) -> DebatePoint | None:
    return _point(
        "Trading frictions alone cost {{fact:strategy.cost_drag}} of return; an edge that does not "
        "clear that drag by a wide margin is not a tradeable edge.",
        ("strategy.cost_drag",),
        bundle,
    )


# ---------------------------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------------------------


def build_debate(card: StrategyCard) -> Debate:
    """Bull and bear cases for ``card``, over its own bundle.

    Returns an empty :class:`Debate` (both sides ``()``) when the card has no bundle -- a debate
    cannot cite facts that were never assembled, and offering ungrounded prose instead would be
    exactly the failure :mod:`app.report.narrative` exists to prevent.
    """
    if card.bundle is None:
        return Debate(symbol=card.symbol)
    bundle = card.bundle

    bull_candidates = (
        _bull_edge(bundle),
        _bull_holdout(bundle),
        _bull_frequency(bundle) or _bull_frequency_only(bundle),
    )
    bear_candidates = (
        _bear_worst_case(bundle) or _bear_worst_case_no_trade(bundle),
        _bear_regime(card, bundle),
        _bear_conditional(card, bundle),
        _bear_tax(bundle),
        _bear_cost_drag(bundle),
        _bear_selection(bundle),
    )

    return Debate(
        symbol=card.symbol,
        bull=tuple(p for p in bull_candidates if p is not None),
        bear=tuple(p for p in bear_candidates if p is not None),
    )
