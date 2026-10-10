"""Proposes theses from structure and priors -- deliberately not from the sample.

Hazard property (2) in :mod:`app.thesis`'s docstring: *the generator sees the data*. If a proposer
inspects this ticker's history and then writes a hypothesis, the hypothesis is a description of that
history dressed as a claim about the process, and every test that follows is circular. The trial
ledger and the holdout limit the damage; they do not undo it.

So the default author is **blind to the sample**. It sees the symbol, the interval, and the
instrument's class -- whether it is a daily-reset leveraged product, an index fund, a single name --
and nothing else. Its proposals come from a fixed catalogue of standard market hypotheses, each with
its rules, its predicted direction and its falsification criterion written in advance and stored in
this file rather than generated per run.

That makes the proposals unoriginal, which is the point. An unoriginal hypothesis tested honestly is
worth more than a bespoke one tested circularly, and the machinery that matters -- pre-registration,
the ledger, the holdout, the budget -- is identical either way. A language model swapped in here
changes who writes the hypothesis and changes nothing about what refuses it, exactly as
:mod:`app.report.narrative` refuses ungrounded prose whether a model or a template wrote it.

**Reverse conditioning is the one honest way to generate candidates from data**, because it is
explicit about doing so and its output is labelled exploratory. A thesis derived that way is welcome
here -- it just arrives through :func:`propose_from_candidate`, which stamps the rationale so the
card can say where it came from, and it consumes a trial like everything else.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.db.duck import Interval
from app.thesis import instruments
from app.thesis.models import Direction, Thesis

__all__ = ["CATALOGUE", "Template", "propose", "propose_from_candidate"]


@dataclass(frozen=True, slots=True)
class Template:
    """One standard hypothesis, written before any ticker was chosen."""

    key: str
    hypothesis: str
    entry: str
    exit: str | None
    horizon: int
    direction: Direction
    falsifies_if: str
    rationale: str
    max_holding_bars: int | None = None
    stop_loss_pct: float | None = None
    leveraged_only: bool = False
    """Proposed only for daily-reset products, where the mechanism is specific to them."""


#: The proposal catalogue. Ordered, and the loop walks it in order.
#:
#: Every entry states what would refute it *in the template*, not at test time. That ordering is the
#: guard: a criterion written after the numbers arrive is a criterion chosen to pass, and there is no
#: code path here that can produce one.
CATALOGUE: tuple[Template, ...] = (
    Template(
        key="band_reversion",
        hypothesis=(
            "A close below the lower Bollinger band is followed by a higher-than-baseline rate of "
            "positive 20-bar returns."
        ),
        entry="close < bb_lower(20,2)",
        exit="close > sma(20)",
        horizon=20,
        direction=Direction.UP,
        falsifies_if=(
            "the 20-bar hit rate after a lower-band touch does not exceed the instrument's "
            "unconditional 20-bar hit rate over the same sample"
        ),
        rationale=(
            "Standard mean-reversion prior: a two-sigma excursion is, by construction, unusual "
            "relative to recent dispersion. Proposed from the indicator's definition, not from this "
            "instrument's history."
        ),
        max_holding_bars=40,
    ),
    Template(
        key="trend_following",
        hypothesis=(
            "A 50-day EMA crossing above the 200-day EMA is followed by a higher-than-baseline "
            "rate of positive 60-bar returns."
        ),
        entry="ema(50) crosses_above ema(200)",
        exit="ema(50) crosses_below ema(200)",
        horizon=60,
        direction=Direction.UP,
        falsifies_if=(
            "the 60-bar hit rate after the crossover does not exceed the instrument's "
            "unconditional 60-bar hit rate over the same sample"
        ),
        rationale=(
            "Trend-following prior. The mechanically plausible part of the trend-following case is "
            "about drawdown rather than return -- but `evaluate_thesis` measures hit rate against "
            "baseline and computes no drawdown, so stating the hypothesis in terms of drawdown "
            "would have produced a verdict that did not answer the question asked. It did, until "
            "this was corrected: the template claimed a drawdown effect and was scored on 60-bar "
            "hit rate. The drawdown comparison is still reported, on the strategy card, where it "
            "informs a reader without pretending to have been tested."
        ),
    ),
    Template(
        key="momentum_persistence",
        hypothesis=(
            "A close above the 200-day simple moving average is followed by a higher-than-baseline "
            "rate of positive 20-bar returns."
        ),
        entry="close > sma(200)",
        exit="close < sma(200)",
        horizon=20,
        direction=Direction.UP,
        falsifies_if=(
            "the 20-bar hit rate above the 200-day average does not exceed the unconditional rate"
        ),
        rationale="Momentum prior: the most widely cited single trend filter in the literature.",
    ),
    Template(
        key="oversold_bounce",
        hypothesis=(
            "An RSI(14) reading below 30 is followed by a higher-than-baseline rate of positive "
            "5-bar returns."
        ),
        entry="rsi(14) < 30",
        exit="rsi(14) > 50",
        horizon=5,
        direction=Direction.UP,
        falsifies_if=(
            "the 5-bar hit rate after an oversold reading does not exceed the unconditional rate"
        ),
        rationale=(
            "The most commonly traded oscillator threshold. Included partly because it is widely "
            "believed, which makes a negative result informative."
        ),
        max_holding_bars=10,
        stop_loss_pct=0.15,
    ),
    Template(
        key="volatility_contraction",
        hypothesis=(
            "A narrow Bollinger band width is followed by a higher-than-baseline rate of large "
            "20-bar moves in either direction."
        ),
        entry="bb_upper(20,2) - bb_lower(20,2) < close * 0.04",
        exit=None,
        horizon=20,
        direction=Direction.UP,
        falsifies_if=(
            "the 20-bar hit rate after a band squeeze does not exceed the unconditional rate"
        ),
        rationale=(
            "Volatility-clustering prior: realised volatility is autocorrelated, so compression is "
            "informative about dispersion even when it is not informative about direction. Note the "
            "declared direction is up while the hypothesis is about magnitude -- this is the "
            "template most likely to be refuted, and it is kept for that reason."
        ),
        max_holding_bars=20,
    ),
    Template(
        key="decay_avoidance",
        hypothesis=(
            "For a daily-reset leveraged product, a close above the 200-day average is followed by "
            "a higher-than-baseline rate of positive 60-bar returns."
        ),
        entry="close > sma(200)",
        exit="close < sma(200)",
        horizon=60,
        direction=Direction.UP,
        falsifies_if=(
            "the 60-bar hit rate above the 200-day average does not exceed the instrument's "
            "unconditional 60-bar hit rate over the same sample"
        ),
        rationale=(
            "Specific to daily-reset products, whose multi-day returns are path-dependent, so a "
            "trend filter plausibly avoids some of the choppy-market decay. That decay claim is "
            "about drawdown and about the comparison against the unlevered equivalent -- neither "
            "of which `evaluate_thesis` measures, so neither appears in the hypothesis or the "
            "falsification criterion above. Both are reported on the strategy card, which is where "
            "an untested comparison belongs. Note this leaves the template statistically "
            "indistinguishable from `trend_following`; the difference is the instrument it is "
            "proposed for, not the measurement."
        ),
        leveraged_only=True,
    ),
)


def propose(
    symbol: str,
    interval: Interval = Interval.DAY,
    *,
    exclude: Sequence[str] = (),
) -> list[Thesis]:
    """Every applicable template, as theses, in catalogue order.

    ``exclude`` drops templates by key -- used by the loop to skip hypotheses already registered for
    this ticker in an earlier run, since re-registering an identical thesis is a no-op in the ledger
    and would burn an iteration producing nothing new.

    Sees the symbol, the interval and the instrument class. It does **not** see the bars.
    """
    leveraged = instruments.lookup(symbol) is not None
    skip = set(exclude)
    out: list[Thesis] = []
    for template in CATALOGUE:
        if template.key in skip:
            continue
        if template.leveraged_only and not leveraged:
            continue
        out.append(
            Thesis(
                symbol=symbol.upper(),
                interval=interval,
                hypothesis=template.hypothesis,
                entry=template.entry,
                exit=template.exit,
                max_holding_bars=template.max_holding_bars,
                stop_loss_pct=template.stop_loss_pct,
                horizon=template.horizon,
                direction=template.direction,
                falsifies_if=template.falsifies_if,
                rationale=template.rationale,
            )
        )
    return out


def propose_from_candidate(
    symbol: str,
    *,
    entry: str,
    exit: str | None,
    horizon: int,
    direction: Direction,
    falsifies_if: str,
    source: str,
    interval: Interval = Interval.DAY,
    hypothesis: str | None = None,
) -> Thesis:
    """A thesis derived from an exploratory study, stamped with where it came from.

    Reverse conditioning reads the sample and hands back conditions that describe it -- an honest way
    to generate candidates precisely because it is explicit about doing so. This function exists so
    that provenance survives into the card: a thesis proposed this way was suggested *by* the data,
    and a reader deciding how much weight to give a surviving result needs to know that. It consumes
    a trial like every other thesis.
    """
    return Thesis(
        symbol=symbol.upper(),
        interval=interval,
        hypothesis=hypothesis or f"The condition `{entry}` precedes above-baseline {horizon}-bar returns.",
        entry=entry,
        exit=exit,
        horizon=horizon,
        direction=direction,
        falsifies_if=falsifies_if,
        rationale=(
            f"Generated from {source}, which reads the sample to suggest conditions. This thesis "
            "was therefore suggested by the same history it is scored against; treat a surviving "
            "result with more suspicion than one proposed from priors."
        ),
    )


def template_for(key: str) -> Template | None:
    return next((t for t in CATALOGUE if t.key == key), None)
