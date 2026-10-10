"""Power analysis for the Agent Workflow study's pre-registered decision rule --
`docs/WORKFLOW-STUDY-PLAN.md` §7 -- and a calendar-time projection for its data bar.

**What this module answers, and what it deliberately does not.** §7 requires 60 trading sessions and
40 gated candidates to accumulate before the decision rule is evaluated at all, and as of this
module's writing three workflow runs exist with zero fills. Two questions follow from that: when does
the bar get crossed at the desk's real candidate-arrival rate, and -- even once it is -- is the §4
discrimination test (the one instrument in the study with real statistical power, per `study.py`'s own
docstring) actually able to detect an effect size this programme's own record makes plausible? This
module answers both with a zero-model-cost Monte Carlo simulation and a historical-data projection.
**It computes planning information only. It does not alter, relax, or pre-empt §7's decision rule in
any way** -- the rule is still evaluated exactly as `app.workflow.study` computes it, once the real
data clears the bar, and nothing here substitutes for that.

**Two independent halves.**

`simulate_discrimination_power` asks: at a given number of gated candidates and a given true
hit-rate difference between a gate's passed and refused sets, what fraction of simulated draws would
reach the pre-registered `q <= 0.10` threshold? It reuses `app.backtest.scan.binomial_p_value` and
`.benjamini_hochberg` **verbatim** -- the same `m = 3` pipeline `app.workflow.study._discrimination`
runs -- rather than reimplementing either statistic, per `docs/WORKFLOW-STUDY-PLAN.md` §4's "reuse
these verbatim" instruction. It needs no stored data and is safe to run anywhere, any time.

`estimate_candidate_arrival_rate` asks: at what rate does this desk's own historical signal activity
actually produce gated candidates, so the 40-candidate bar can be translated into a calendar date?
It reads real stored bars (`app.market.store`) and the real strategy-card library
(`Settings.library_dir`), so unlike the power simulation it can fail gracefully -- returning an
explicit "unavailable" result rather than a fabricated number -- when that data is not present (a
fresh clone, or a test's isolated temp store).
"""

from __future__ import annotations

import datetime as dt
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from app.backtest.scan import benjamini_hochberg, binomial_p_value
from app.config import Settings
from app.market import store as market_store
from app.market.models import Interval
from app.rules import evaluate as rule_evaluate
from app.rules import grammar
from app.tournament.models import StrategyCard
from app.workflow import regime as regime_mod
from app.workflow.candidates import GateName
from app.workflow.pipeline import DEFAULT_MAX_RESEARCH_SYMBOLS

__all__ = [
    "GATES",
    "ArrivalRateEstimate",
    "CardArrivalRate",
    "PowerCell",
    "estimate_candidate_arrival_rate",
    "simulate_discrimination_power",
]

#: The three gates `app.workflow.study._discrimination` tests -- restated here rather than imported
#: because that name is private to its module (the same "mirror, do not reach through privacy"
#: convention `app.workflow.pipeline._scan_signals`'s own docstring documents for this package). Order
#: and membership must match `study._GATES` exactly, since both feed `benjamini_hochberg` with the
#: same `m = 3`.
GATES: tuple[GateName, ...] = ("ta_gated", "vibe_gated", "full_workflow")


# ---------------------------------------------------------------------------
# Part 1: discrimination-test power, zero model cost
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PowerCell:
    """One `(n_gated_candidates, effect_size)` grid cell's Monte Carlo result."""

    n_gated_candidates: int
    effect_size: float
    """Assumed true `passed_hit_rate - refused_hit_rate`, e.g. `0.05` = 5 percentage points."""
    power: float
    """Fraction of `n_draws` simulated draws in which `target_gate`'s BH-adjusted q-value reached
    `q_threshold` or below."""
    n_draws: int


def simulate_discrimination_power(
    n_candidates_grid: Sequence[int],
    effect_sizes: Sequence[float],
    *,
    baseline_hit_rate: float = 0.50,
    pass_fraction: float = 0.40,
    target_gate: GateName = "full_workflow",
    q_threshold: float = 0.10,
    n_draws: int = 4000,
    seed: int = 0,
) -> tuple[PowerCell, ...]:
    """Monte Carlo power of §4's decision-rule check (b): the fraction of simulated draws in which
    `target_gate`'s Benjamini-Hochberg-adjusted q-value reaches `q_threshold` (the pre-registered
    `0.10`) or below.

    **The simulated experiment, matching `study._discrimination` step for step.** On each draw and for
    each of `GATES`, `n_gated_candidates` observations split `pass_fraction` / `(1 - pass_fraction)`
    into passed/refused sets. Each refused-set observation is an independent Bernoulli draw at
    `baseline_hit_rate` (a coin-flip-ish forward-return-positive rate, standing in for `raw_signal`'s
    unconditional base rate); each passed-set observation is an independent Bernoulli draw at
    `baseline_hit_rate + effect_size`, clipped to `[0, 1]`. `binomial_p_value` is then computed exactly
    as `study._discrimination` computes it -- against the passed set's observed successes and the
    *observed* (not the true) refused hit rate, because that is what the real test conditions on, not
    a value this simulation is allowed to peek at. `benjamini_hochberg` adjusts all three gates'
    p-values together (`m = 3`), and the draw counts as a "hit" iff `target_gate`'s q-value is not
    `None` and is `<= q_threshold`.

    **Why all three gates are simulated identically, and what that costs.** In a real run
    `full_workflow`'s pass rate is the intersection of `ta_gated` and `vibe_gated`'s and so is lower
    than either alone (`app.workflow.pipeline._passes_gate`), and the three gates' decisions on the
    same candidate are correlated, not independent. Modelling that faithfully would need three
    correlated pass rates and a joint sampling model this study has no historical data to calibrate
    (three real workflow runs, zero fills, as of this module's writing). Treating all three gates as
    exchangeable draws at the same `pass_fraction` is a simplification, not an oversight: it keeps
    every gate's discrimination test as easy to pass as `target_gate`'s, so the reported power for
    `target_gate` is not depressed by an arbitrary choice of the *other* two gates' difficulty, and the
    BH correction is exercised with the same `m = 3` shape the real pipeline always has.

    Deterministic given `seed`. A single `random.Random(seed)` instance is threaded through every draw
    of every `(n, effect)` cell in `n_candidates_grid` x `effect_sizes` order, so the same seed
    reproduces the identical table bit-for-bit; a different seed gives a different (still valid) Monte
    Carlo estimate of the same quantity.

    Raises `ValueError` for `target_gate` not in `GATES`, `pass_fraction` outside `(0, 1)`, or
    `q_threshold`/`baseline_hit_rate` outside `[0, 1]` -- all programming errors in the caller, not
    data conditions to report on.
    """
    if target_gate not in GATES:
        raise ValueError(f"target_gate must be one of {GATES}, got {target_gate!r}")
    if not 0.0 < pass_fraction < 1.0:
        raise ValueError(f"pass_fraction must be in (0, 1), got {pass_fraction}")
    if not 0.0 <= baseline_hit_rate <= 1.0:
        raise ValueError(f"baseline_hit_rate must be in [0, 1], got {baseline_hit_rate}")
    if not 0.0 <= q_threshold <= 1.0:
        raise ValueError(f"q_threshold must be in [0, 1], got {q_threshold}")
    if n_draws <= 0:
        raise ValueError(f"n_draws must be positive, got {n_draws}")

    target_index = GATES.index(target_gate)
    rng = random.Random(seed)
    cells: list[PowerCell] = []

    for n in n_candidates_grid:
        passed_n = round(n * pass_fraction)
        refused_n = n - passed_n
        for effect in effect_sizes:
            passed_rate = min(1.0, max(0.0, baseline_hit_rate + effect))
            hits = 0
            for _ in range(n_draws):
                q_values = benjamini_hochberg(
                    _one_draw(
                        rng,
                        passed_n=passed_n,
                        refused_n=refused_n,
                        passed_rate=passed_rate,
                        baseline_hit_rate=baseline_hit_rate,
                    )
                )
                q = q_values[target_index]
                if q is not None and q <= q_threshold:
                    hits += 1
            cells.append(
                PowerCell(
                    n_gated_candidates=n,
                    effect_size=effect,
                    power=hits / n_draws,
                    n_draws=n_draws,
                )
            )
    return tuple(cells)


def _one_draw(
    rng: random.Random,
    *,
    passed_n: int,
    refused_n: int,
    passed_rate: float,
    baseline_hit_rate: float,
) -> list[float | None]:
    """One Monte Carlo draw's p-value list across `GATES`, in `GATES` order -- the exact shape
    `study._discrimination` builds before handing it to `benjamini_hochberg`."""
    p_values: list[float | None] = []
    for _gate in GATES:
        if passed_n == 0 or refused_n == 0:
            p_values.append(None)
            continue
        refused_successes = rng.binomialvariate(refused_n, baseline_hit_rate)
        passed_successes = rng.binomialvariate(passed_n, passed_rate)
        refused_hit_rate = refused_successes / refused_n
        p_values.append(binomial_p_value(passed_successes, passed_n, refused_hit_rate))
    return p_values


# ---------------------------------------------------------------------------
# Part 2: historical candidate-arrival rate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CardArrivalRate:
    """One strategy card's historical gated-candidate rate, scored over its own priced history."""

    agent_id: str
    universe_size: int
    sessions: int
    """Count of distinct sessions any universe symbol had a priced bar -- the denominator of
    `mean_gated_candidates_per_session`."""
    mean_gated_candidates_per_session: float
    window_start: dt.date | None
    window_end: dt.date | None


@dataclass(frozen=True)
class ArrivalRateEstimate:
    """The regime map's cards, individually rated, plus a single planning figure."""

    per_card: tuple[CardArrivalRate, ...]
    overall_mean_per_session: float | None
    """Unweighted mean of `per_card`'s own means. `None` when `per_card` is empty -- see `note`."""
    max_research_symbols: int
    note: str


def _load_card(agent_id: str, *, settings: Settings) -> StrategyCard | None:
    """A deliberate copy of `app.workflow.pipeline._load_card`'s body: that function is private to
    its module, and this package's convention (see `_scan_signals`'s own docstring) is to mirror
    pipeline logic in a caller's own module rather than reach through another module's privacy."""
    for path in sorted(settings.library_dir.rglob(f"{agent_id}.json")):
        try:
            return StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
    return None


def _card_daily_fire_counts(
    card: StrategyCard, *, settings: Settings
) -> dict[dt.date, int] | None:
    """`{session: count of universe symbols whose entry rule fired that session}`, over each symbol's
    full stored history -- `None` if the card's entry rule does not parse or no universe symbol has
    any stored history at all.

    Mirrors `app.workflow.pipeline._scan_signals`'s rule -- full history, unknown truth (warmup/gap/no
    bar) becomes `False`, never raises -- but evaluates each symbol's whole stored history in one
    vectorised `evaluate` call rather than one `AsOfMarket` call per session. The two are equivalent
    for a causal rule (every bar's indicator value depends only on bars up to and including it, which
    is `app.rules.evaluate`'s own contract), and only the vectorised form is fast enough to cover years
    of daily bars for every universe symbol of every regime-map card sequentially on a
    memory-constrained host.
    """
    try:
        entry_tree = grammar.parse(card.entry)
    except ValueError:
        return None

    counts: dict[dt.date, int] = defaultdict(int)
    sessions: set[dt.date] = set()
    any_symbol = False
    for symbol in card.universe:
        frame = market_store.read_frame(symbol, Interval.DAY, settings=settings)
        if frame is None or frame.empty:
            continue
        try:
            signal = rule_evaluate.evaluate(entry_tree, frame, interval=Interval.DAY)
        except ValueError:
            continue
        any_symbol = True
        fired = signal.fillna(False).tolist()
        dates = frame["ts"].dt.date.tolist()
        for on, flag in zip(dates, fired, strict=True):
            sessions.add(on)
            if flag:
                counts[on] += 1

    if not any_symbol or not sessions:
        return None
    return {on: counts.get(on, 0) for on in sessions}


def estimate_candidate_arrival_rate(
    *, settings: Settings, max_research_symbols: int = DEFAULT_MAX_RESEARCH_SYMBOLS
) -> ArrivalRateEstimate:
    """Mean gated candidates per session for every strategy card `regime_map.json` can route to.

    "Gated candidate" here means what `app.workflow.pipeline._stage_candidate_scan` actually gates and
    researches: the day's firing symbols, capped at `max_research_symbols`
    (`chosen = firing[:max_research_symbols]` -- applied identically here). A raw uncapped firing count
    would overstate the real arrival rate whenever more than `max_research_symbols` names fire the same
    session. (Names that fire *beyond* the cap are now also written to the observation log with
    `skip_reason="over_cap"`, so the study's negative record is complete -- but they are never gated or
    researched, and this rate deliberately still counts only the capped set, recomputed from firing
    counts here rather than read back from the observation log.)

    **Sequential, one card and one symbol at a time.** This host is memory-constrained and another
    session may be running backtests concurrently; nothing here batches across cards or holds more than
    one card's frames in memory at once.

    **A real run trades one card per session, not every regime-map card at once.** Each `CardArrivalRate`
    is scored over that card's *own* priced history as if it had been the active card every session --
    it is not a simulation of the actual regime-gated daily process (that would need `regime.classify`
    replayed over history, which this module does not attempt). `overall_mean_per_session` is the
    unweighted mean of those per-card figures: an order-of-magnitude planning number, not a forecast of
    which card trades on which day.

    Returns `per_card=()` and `overall_mean_per_session=None`, with `note` explaining why, rather than
    a fabricated rate, when the regime map cannot be loaded, no listed card has both a parseable entry
    rule and any stored history for its universe (e.g. an isolated test's empty temp store), or the
    regime map names no cards at all.
    """
    try:
        regime_map = regime_mod.load_regime_map(settings)
    except Exception as exc:  # degrades to an explicit "unavailable" result, not a crash
        return ArrivalRateEstimate(
            per_card=(),
            overall_mean_per_session=None,
            max_research_symbols=max_research_symbols,
            note=f"regime map unavailable: {exc}",
        )

    agent_ids = sorted({agent_id for cards in regime_map.values() for agent_id in cards})
    if not agent_ids:
        return ArrivalRateEstimate(
            per_card=(),
            overall_mean_per_session=None,
            max_research_symbols=max_research_symbols,
            note="regime map names no strategy cards; arrival rate unavailable.",
        )

    per_card: list[CardArrivalRate] = []
    for agent_id in agent_ids:
        card = _load_card(agent_id, settings=settings)
        if card is None:
            continue
        daily_counts = _card_daily_fire_counts(card, settings=settings)
        if daily_counts is None:
            continue
        capped = [min(count, max_research_symbols) for count in daily_counts.values()]
        dates = sorted(daily_counts)
        per_card.append(
            CardArrivalRate(
                agent_id=card.agent_id,
                universe_size=len(card.universe),
                sessions=len(capped),
                mean_gated_candidates_per_session=sum(capped) / len(capped),
                window_start=dates[0],
                window_end=dates[-1],
            )
        )

    if not per_card:
        return ArrivalRateEstimate(
            per_card=(),
            overall_mean_per_session=None,
            max_research_symbols=max_research_symbols,
            note=(
                "no regime-map card had both a parseable entry rule and any stored bar history for "
                "its universe; arrival rate unavailable (this is the expected result against an "
                "isolated/empty test store, not a real deficiency of a populated one)."
            ),
        )

    overall = sum(row.mean_gated_candidates_per_session for row in per_card) / len(per_card)
    note = (
        f"Unweighted mean across {len(per_card)} of {len(agent_ids)} regime-map card(s) (the "
        "remainder had no loadable card, no parseable entry rule, or no stored history for their "
        "universe). Each card is scored over its own full stored history independently, capped at "
        f"max_research_symbols={max_research_symbols} candidates/session, as if it were the active "
        "card every session in that history -- not a replay of the actual regime-gated process, "
        "which trades exactly one card per session. Treat as an order-of-magnitude planning figure."
    )
    return ArrivalRateEstimate(
        per_card=tuple(per_card),
        overall_mean_per_session=overall,
        max_research_symbols=max_research_symbols,
        note=note,
    )
