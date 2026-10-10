"""Turn the round runner's per-window output into a scorecard.

The runner (not this module) trades every card through every window it is eligible for and writes
one `app.tournament.models.AgentResult` per (card, window) as
``<results-root>/<window-tag>/runs/<round>-<agent_id>.json``. This module reads that tree, computes
the two per-window metrics the round is judged on, and rolls each card's numbers up into a single
comparable score -- without ever inventing a number for a window that was not actually run.

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \\
        --results data/rounds/r1-2026-08/results \\
        --json data/rounds/r1-2026-08/results/scorecard.json

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name (the
hyphen), so it can only be invoked by file path, with `backend` and the repo root already on
``PYTHONPATH`` for the `app.*` imports this module makes.

**The primary metric, and why.** A strategy that is long 90% of the time in a window the benchmark
returned 40% in has a large `total_return` for a reason that has nothing to do with its rules. `excess
= total_return - benchmark_return` does not correct for that; `adjusted_excess = total_return -
(exposure * benchmark_return)` asks the sharper question -- did the *rules* beat simply being invested
the same fraction of the time the strategy actually was -- and it is what `median_adjusted_excess`
ranks on.

**What "ranked" means.** A card that only cleared the round's main-window eligibility gate on paper
but never actually ran the required number of times, or ran and never once took a trade, has not
produced a comparable result. `ranked=False` for such a card, and it is reported with all its real
numbers rather than being sorted to the bottom of the ranking, which would misrepresent "no
comparable result" as "worst result". A card is also `ranked=False` when a run file exists for a
window the eligibility map marks ineligible for provenance reasons (`CardScore.provenance_violation`)
-- see `aggregate_card`.

**Ranking on the median alone hides a convex payoff.** Round 1's clearest finding: a card that hedged
hard in a crash and cost a little in every ordinary window returned the field's best single-window
number by seventeen points, and still ranked 17th of 18, because a median cannot distinguish "flat
because hedged" from "flat because it never traded". `compute_dominance` adds a second view --
per-criterion ranks on `median_adjusted_excess`, `worst_adjusted_excess` and `hit_rate`, their Borda
composite, and the Pareto-non-dominated frontier -- reported alongside the median, never instead of
it. `--rank-by` (`RANK_BY_CHOICES`) picks which criterion orders the primary table; every column,
including the other three criteria and frontier membership, is printed regardless of which is chosen.

**`adjusted_excess` itself scales with exposure, and that is a second, separate bias.** Against a
large negative benchmark, the exposure term is a large credit for anyone holding much capital, so two
cards can differ by many points on `adjusted_excess` for a reason that has nothing to do with how well
either one traded -- round 2's `REPORT.md` §2 measured capital exposure correlating with GFC-window
adjusted excess at Pearson r = +0.797 across ten cards. `realised_pnl` reports the plain dollar P&L
beside every adjusted figure so that decomposition is visible without hand computation;
`excess_per_exposure` divides adjusted excess by capital exposure to ask the scale-free question
instead, and is a `--rank-by` choice in its own right; and a row is flagged
(`CardScore.incommensurable_exposure`) whenever its mean exposure differs from the ranked field's
median by more than a factor of two, so a reader is told rather than left to infer that its
`median_adjusted_excess` is not on the same scale as the rest of the table. None of this replaces the
median-based ranking or its `--rank-by median` default, which is unchanged.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, NamedTuple

from app.tournament.models import AgentResult

__all__ = [
    "HORIZON_ORDER",
    "MAIN_WINDOW_TAGS",
    "MATRICES",
    "MIN_EXPOSURE_FOR_RATIO",
    "MIN_RANKED_PER_HORIZON",
    "R2_MATRIX",
    "R4_MAIN_WINDOW_TAGS",
    "R4_MATRIX",
    "R5_BEAR_TAGS",
    "R5_HORIZON",
    "R5_LADDER_TAGS",
    "R5_MATRIX",
    "RANK_BY_CHOICES",
    "CardScore",
    "HorizonScore",
    "Matrix",
    "WindowCell",
    "adjusted_excess",
    "aggregate_card",
    "annualized_adjusted_excess",
    "annualized_benchmark",
    "annualized_return",
    "compute_dominance",
    "detect_matrix",
    "excess",
    "excess_per_exposure",
    "flag_incommensurable_exposure",
    "load_results",
    "realised_pnl",
    "render_markdown",
    "reorder_by_rank_criterion",
    "score_round",
    "window_years",
]

#: The eight round-2 regime tags, duplicated from `strategy-program/tools/windows.MAIN_WINDOWS` rather
#: than imported from it. The two files are siblings under a hyphenated directory
#: (`strategy-program/tools/`), which is not a legal Python package name, so importing across them
#: would mean either a `sys.path` hack or an `importlib.util.spec_from_file_location` dance -- more
#: fragile than eight short strings kept in sync by inspection. If the matrix changes, both files need
#: updating either way; a shared import would only save noticing it in one place instead of two.
MAIN_WINDOW_TAGS: tuple[str, ...] = (
    "q4-2018",
    "covid",
    "bear-2022",
    "chop-2015",
    "chop-2011",
    "bull-2024",
    "recent",
    "gfc",
)

#: Below this many actually-run main windows, a card's aggregate numbers describe too small a sample
#: to rank against cards that ran in all eight -- `strategy-program/WINDOWS.md`'s gate (round 1's was
#: 3 of 5; round 2 binds the same ~60% proportion harder against the larger matrix, mirroring
#: `strategy_program.tools.windows.MIN_ELIGIBLE_MAIN_WINDOWS`).
MIN_RANKED_MAIN_WINDOWS = 5

#: Round 4's matrix: six regimes, **none** of which appears in `MAIN_WINDOW_TAGS`. `PROTOCOL.md`
#: 6(a) forced that -- cards are frozen and the engine is deterministic, so re-running a card on a
#: window it has already seen recomputes the same number rather than sampling anything, and a
#: promotion resting on two rounds that share windows is one measurement counted twice.
R4_MAIN_WINDOW_TAGS: tuple[str, ...] = (
    "recovery-2009",
    "taper-2013",
    "oil-2014",
    "volmageddon-2018",
    "inflation-2021",
    "banks-2023",
)

#: Round 4's gate, over six windows -- the same ~65% proportion as round 1's 3-of-5 and round 2's
#: 5-of-8. It is a separate constant rather than a new value for `MIN_RANKED_MAIN_WINDOWS` because
#: rounds 2 and 3 were scored against 5-of-8 and their published tables have to stay reproducible.
MIN_RANKED_R4_WINDOWS = 4


class Matrix(NamedTuple):
    """Which windows a round ranks over, and how many of them a card must have run.

    Before round 4 both halves were module constants and every gate computation in this file
    intersected against `MAIN_WINDOW_TAGS` directly. That was correct for as long as there was one
    matrix. Round 4 introduced a second one with no overlap at all, at which point the constants
    stopped describing "the main windows" and started describing "round 2's main windows" -- and
    scoring round 4 against them produced an *empty leaderboard rather than an error*, because a card
    that ran none of the eight is unranked for entirely ordinary reasons. A silent empty result is
    the worst available failure mode for a scorer, so the matrix now travels with the call.

    **`min_ranked_per_horizon`**, added for round 5, is a second, narrower gate than `min_ranked`.
    `min_ranked` answers "has this card run enough of the *whole* matrix to be ranked at all" -- for
    round 5 that is still a meaningful question over all 27 windows. But round 5 also needs a gate
    per *horizon* (a card can clear the whole-matrix gate while having run only one of the two 10-year
    windows, which is not enough of a sample to report a 10-year median on its own), and that is a
    different quantity: `min_ranked` cannot express it because it is one number for the whole matrix,
    not one per horizon-sized subset of it. Rather than invent a free-floating module constant the
    caller has to remember to go and look up by matrix name -- a second source of truth for a gating
    parameter that is otherwise entirely a property of the matrix -- this adds a second optional field
    right beside `min_ranked`, so a reader who has already found one gate on `Matrix` finds the other
    the same way. `None` (the default) for a matrix with no horizon concept at all -- `R2_MATRIX` and
    `R4_MATRIX`, whose windows are each their own regime with no "same horizon, different eras" grouping
    -- and no code outside `R5_MATRIX`'s handling ever reads it.
    """

    name: str
    tags: tuple[str, ...]
    min_ranked: int
    min_ranked_per_horizon: int | None = None


R2_MATRIX = Matrix("r2", MAIN_WINDOW_TAGS, MIN_RANKED_MAIN_WINDOWS)
R4_MATRIX = Matrix("r4", R4_MAIN_WINDOW_TAGS, MIN_RANKED_R4_WINDOWS)

#: Round 5's "ladder" arm: 21 windows at five horizons (6 months to 10 years), each horizon sampled at
#: more than one point in calendar history so a horizon's number is not just one era's number wearing a
#: label -- transcribed from `data/rounds/r5-2026-08/windows.json`'s `arms.ladder`, in the file's own
#: order (10y windows first, down to 6m). If that file and this tuple ever disagree, the file is right;
#: update this tuple from it, not the other way round.
R5_LADDER_TAGS: tuple[str, ...] = (
    "h10y-1",
    "h10y-2",
    "h5y-1",
    "h5y-2",
    "h5y-3",
    "h3y-1",
    "h3y-2",
    "h3y-3",
    "h3y-4",
    "h1y-1",
    "h1y-2",
    "h1y-3",
    "h1y-4",
    "h1y-5",
    "h1y-6",
    "h6m-1",
    "h6m-2",
    "h6m-3",
    "h6m-4",
    "h6m-5",
    "h6m-6",
)

#: Round 5's "bear" arm: 6 windows, each deliberately chosen to start near a market top and run through
#: a real drawdown (covid, the 2022 bear, Q4 2018, the 2015-16 growth scare) rather than sampled from
#: calendar history the way the ladder arm is -- transcribed from `windows.json`'s `arms.bear`. Kept as
#: a second tuple, not folded into `R5_LADDER_TAGS`, precisely so a median can be taken over one arm
#: without the other silently mixed in -- see the module docstring's "ladder and bear arms separately"
#: requirement and `CardScore.per_horizon_bear`.
R5_BEAR_TAGS: tuple[str, ...] = (
    "b6m-1",
    "b6m-2",
    "b6m-3",
    "b1y-1",
    "b1y-2",
    "b1y-3",
)

#: Every round-5 window tag's nominal horizon label, ladder and bear arms both -- also transcribed from
#: `windows.json` (each window's own `"horizon"` key), not derived from the tag string, so a future tag
#: that does not follow the `h<n><unit>-<k>` / `b<n><unit>-<k>` naming convention cannot silently
#: misparse into the wrong bucket. `HORIZON_ORDER` below is the canonical left-to-right order these
#: labels are reported in.
R5_HORIZON: dict[str, str] = {
    "h10y-1": "10y",
    "h10y-2": "10y",
    "h5y-1": "5y",
    "h5y-2": "5y",
    "h5y-3": "5y",
    "h3y-1": "3y",
    "h3y-2": "3y",
    "h3y-3": "3y",
    "h3y-4": "3y",
    "h1y-1": "1y",
    "h1y-2": "1y",
    "h1y-3": "1y",
    "h1y-4": "1y",
    "h1y-5": "1y",
    "h1y-6": "1y",
    "h6m-1": "6m",
    "h6m-2": "6m",
    "h6m-3": "6m",
    "h6m-4": "6m",
    "h6m-5": "6m",
    "h6m-6": "6m",
    "b6m-1": "6m",
    "b6m-2": "6m",
    "b6m-3": "6m",
    "b1y-1": "1y",
    "b1y-2": "1y",
    "b1y-3": "1y",
}

#: Which arm each round-5 tag belongs to, for grouping a card's run windows into `CardScore.
#: per_horizon_ladder` versus `.per_horizon_bear` -- see those fields' docstrings for why the two must
#: never be aggregated together.
_R5_TAG_ARM: dict[str, str] = {
    **{tag: "ladder" for tag in R5_LADDER_TAGS},
    **{tag: "bear" for tag in R5_BEAR_TAGS},
}

#: Shortest-to-longest, the order every horizon-keyed table and dict in this module reports in.
HORIZON_ORDER: tuple[str, ...] = ("6m", "1y", "3y", "5y", "10y")

#: Round 5's whole-matrix gate, over 27 windows -- kept at roughly the same ~60-67% proportion as round
#: 1's 3-of-5, round 2's 5-of-8 and round 4's 4-of-6 (27 * 0.63 ~ 17). This gate answers a narrower
#: question than it used to, though: with round 5's horizons ranging from 2 windows (10y) to 6 (1y and
#: 6m), clearing 17-of-27 says only "this card has a broad base of runs somewhere in the matrix", not
#: "this card has enough runs at any one horizon to report that horizon's number" -- that second,
#: per-horizon question is `MIN_RANKED_PER_HORIZON` below, and is the one round 5's whole design is
#: actually about.
MIN_RANKED_R5_WINDOWS = 17

#: The per-horizon gate (see `Matrix.min_ranked_per_horizon`'s docstring for why this lives on the
#: matrix rather than as a free-floating lookup). Set to 2 because the 10-year horizon has exactly two
#: windows in the whole matrix (`h10y-1`, `h10y-2`) -- any gate higher than 2 would make the 10-year
#: horizon un-reportable for every card no matter how it traded, and any gate of 1 would let a single
#: run stand in for "the 10-year median", which is not a median of anything. 2 is therefore not a
#: proportion chosen by analogy to the whole-matrix gates above; it is the smallest horizon's entire
#: population, and every other horizon (which has 3 to 6 windows) clears it more easily.
MIN_RANKED_PER_HORIZON = 2

R5_MATRIX = Matrix(
    "r5",
    R5_LADDER_TAGS + R5_BEAR_TAGS,
    MIN_RANKED_R5_WINDOWS,
    min_ranked_per_horizon=MIN_RANKED_PER_HORIZON,
)

#: Round 11's **live** matrix: the out-of-sample period 2026-02-17 to 2026-08-18, cut into six
#: contiguous, non-overlapping sub-windows on SPY's own session calendar. Boundaries are
#: pre-registered in `strategy-program/ROUND-11-PLAN.md` section 2 and produced by
#: `strategy-program/tools/run_live_matrix.sh`; if that script and this tuple ever disagree, the
#: script is right.
#:
#: **These are not six regime windows and must not be read as if they were.** Every other matrix in
#: this file samples deliberately different market environments -- a GFC, a COVID crash, two chop
#: regimes, a decade of bull market. These six are one environment cut into pieces, in calendar
#: order, because that environment is the only period no card could have been designed against
#: (every card is frozen with `designed_through = 2026-02-13`). What the split buys is a *hit rate*
#: and a median across six observations rather than one number, so a single outsized month cannot
#: carry a card. What it does not buy, and cannot, is regime coverage.
R11_LIVE_TAGS: tuple[str, ...] = (
    "live-1",
    "live-2",
    "live-3",
    "live-4",
    "live-5",
    "live-6",
)

#: All six, not a proportion: the sub-windows are contiguous slices of one period that every card in
#: the field is eligible for, so a card missing one has *failed* rather than been ineligible -- which
#: is a reconciliation problem to fix before scoring, not a coverage rule to score around. Contrast
#: `MIN_RANKED_MAIN_WINDOWS` and friends, where windows genuinely predate some cards' price history.
MIN_RANKED_R11_WINDOWS = 6

R11_MATRIX = Matrix("r11", R11_LIVE_TAGS, MIN_RANKED_R11_WINDOWS)

#: By name, for the CLI's `--matrix`.
MATRICES: dict[str, Matrix] = {
    m.name: m for m in (R2_MATRIX, R4_MATRIX, R5_MATRIX, R11_MATRIX)
}


def detect_matrix(window_tags: Sequence[str]) -> Matrix | None:
    """The matrix the discovered window directories belong to, or `None` if that is not decidable.

    Returns `None` rather than guessing when the tags touch more than one matrix, or none -- the caller
    turns that into an error telling the operator to pass `--matrix`. Guessing here would reintroduce
    exactly the silent-empty-leaderboard failure `Matrix` exists to prevent.
    """
    present = set(window_tags)
    hits = [m for m in (R2_MATRIX, R4_MATRIX, R5_MATRIX, R11_MATRIX) if present & set(m.tags)]
    return hits[0] if len(hits) == 1 else None


#: Duplicated from `strategy_program.tools.windows.PROVENANCE_REASON_PREFIX` for the same reason
#: `MAIN_WINDOW_TAGS` above is duplicated rather than imported. Used to recognise an eligibility-map
#: reason string as a provenance (basket-lookahead) rejection rather than an ordinary price-history
#: one -- see `aggregate_card`'s handling of a run file that exists for a window the eligibility map
#: marks ineligible for this reason.
_PROVENANCE_REASON_PREFIX = "universe knowable only from"


def corrected_return(result: AgentResult) -> Decimal:
    """The card's actual return: `ending_equity / starting_equity - 1`.

    **Not** `result.total_return`, which is defective -- see `strategy-program/DEFECTS.md` D1. The
    runner divides its equity curve by `starting_equity` before handing it to `metrics.compute`,
    which computes `equity[-1] / equity[0] - 1`; the constant cancels out of that ratio, so the
    reported figure is rebased to the *first session's close* rather than to starting equity. Any
    card that filled an order on session one therefore has its first day silently excluded, which the
    runner's own adjacent comment says must not happen.

    Measured across round 1's three complete windows, 14 card-window pairs disagree by more than
    0.05pp and two change sign -- `A-rotation` in `covid` reports -0.652% against a true +0.465%.

    `starting_equity` is guaranteed positive by the broker mandate, so this never divides by zero.
    """
    return result.ending_equity / result.starting_equity - 1


def capital_exposure(result: AgentResult) -> Decimal | None:
    """Time-weighted fraction of starting capital actually at risk, from the trade log.

    **Not** `result.exposure` -- see `strategy-program/DEFECTS.md` D2. That field is
    `mean(bool(open_lots))` across sessions, i.e. the fraction of sessions on which the card held
    *anything at all*. A four-slot card holding one slot every session reports `1.0` with a quarter
    of its capital deployed, and multiplying that by a benchmark return over-credits it badly.

    Computed as `sum(quantity * entry_price * bars_held) / (sessions * starting_equity)`. `bars_held`
    is the exact session count the position was open for, so no trading-calendar reconstruction is
    needed. Entry notional over *starting* equity is the right pairing because the engine sizes
    `position_pct` as a fraction of starting equity, not of current equity.

    `None` for a card that took no trades, or where `sessions` is zero -- an unmeasurable exposure,
    not a zero one.
    """
    # Prefer the engine's own figure where it exists. `AgentResult.capital_exposure` was added when
    # D2 was fixed between rounds 1 and 2, and it is computed from the lots actually open at each
    # session's close -- which the engine knows exactly and this reconstruction can only infer. The
    # two agree to within 1.21pp across round 2's 170 runs; the residual is an off-by-one in which
    # sessions `bars_held` is taken to span, and the engine is right about that by construction.
    #
    # The reconstruction is kept, not deleted, for two reasons: round-1 run files predate the field
    # and would otherwise be unscoreable, which would break the two-consecutive-rounds promotion
    # rule; and it remains an independent check on the engine.
    engine_figure = getattr(result, "capital_exposure", None)
    if engine_figure is not None:
        return Decimal(str(engine_figure))
    if not result.trades or result.sessions <= 0 or result.starting_equity <= 0:
        return None
    invested = sum(t.quantity * t.entry_price * t.bars_held for t in result.trades)
    return Decimal(invested) / (Decimal(result.sessions) * result.starting_equity)


def excess(result: AgentResult) -> Decimal | None:
    """`corrected_return - benchmark_return`. `None` when the window's own benchmark return is
    unknown -- never substituted with zero, which would silently claim the strategy tied the
    benchmark."""
    if result.benchmark_return is None:
        return None
    return corrected_return(result) - result.benchmark_return


def adjusted_excess(result: AgentResult) -> Decimal | None:
    """`corrected_return - (capital_exposure * benchmark_return)` -- the primary ranking metric.

    It asks whether the card's *rules* beat holding the benchmark with the same fraction of capital
    for the same time. Without the exposure term, simply being invested dominates the ranking: the
    tournament preceding this program measured Spearman rho = 0.648 between exposure and three-year
    return.

    Both corrections in the inputs matter, and both were found mid-round. Using the runner's raw
    `exposure` here moved `c04-riskmanaged`'s `gfc` figure from +25.45% to +55.45%, and flipped
    `c03-breakout`'s sign; using the runner's raw `total_return` flips `A-rotation`'s `covid` result
    from a loss to a gain. See `strategy-program/DEFECTS.md`.

    Falls back to the session-presence exposure only when the card took no trades at all, where the
    two coincide at zero anyway. `None` when the benchmark is unknown -- an unknown benchmark is not
    a zero-return one, and treating it as zero would misstate the excess in whichever direction the
    true value lies.
    """
    if result.benchmark_return is None:
        return None
    exposure = capital_exposure(result)
    if exposure is None:
        if result.exposure is None:
            return None
        exposure = Decimal(str(result.exposure))
    return corrected_return(result) - (exposure * result.benchmark_return)


def realised_pnl(result: AgentResult) -> Decimal:
    """`ending_equity - starting_equity` -- the actual dollars made or lost, with no benchmark or
    exposure adjustment of any kind.

    This is the number `adjusted_excess` cannot show on its own. Round 2's `REPORT.md` §2 found that
    `c08-generalist` **lost $426** in the GFC window and still scored **+19.20%** adjusted excess,
    because holding 41.7% of capital through a -56% market and losing only 4.25% is, arithmetically, a
    large excess over a same-sized passive position -- a correct statement about relative performance
    that nonetheless reads, unqualified, as a win. Printing `realised_pnl` beside every adjusted figure
    makes that decomposition visible without requiring a reader to compute it by hand, as the round-2
    report's author had to.
    """
    return result.ending_equity - result.starting_equity


#: Floor below which `excess_per_exposure` refuses to divide. A card's `capital_exposure` sits in the
#: denominator, so as it approaches zero an ordinary-sized `adjusted_excess` numerator turns into an
#: arbitrarily large ratio that describes the smallness of the denominator, not the strategy -- a card
#: at 0.5% mean exposure with a perfectly unremarkable few points of adjusted excess would report a
#: ratio in the hundreds of percent. 5% is chosen as a round number comfortably below
#: `c09-convex`'s 7.5% mean exposure (round 2's smallest genuinely-traded, ranked book, per
#: `REPORT.md` §2) and high enough to exclude the sub-1-2% edge cases the ratio cannot describe
#: honestly. It is a judgement call, not a derived constant, and is documented here rather than left
#: implicit in `excess_per_exposure`'s `None` return.
MIN_EXPOSURE_FOR_RATIO = Decimal("0.05")


def excess_per_exposure(result: AgentResult) -> Decimal | None:
    """`adjusted_excess / capital_exposure` -- excess per unit of capital actually deployed.

    `adjusted_excess` answers "did the rules beat holding the benchmark at this card's own exposure",
    but the *number* it returns still scales with exposure: against a large negative benchmark, a
    45%-exposure book can reach an adjusted excess several times a 5%-exposure book's ceiling even when
    both are doing an equally good job per dollar committed (see `REPORT.md` §2's GFC table, where
    capital exposure correlates with adjusted excess at Pearson r = +0.797). Dividing by exposure asks
    the scale-free question instead: per unit of capital this card actually put at risk, how much
    excess did it produce?

    Deliberately uses `capital_exposure` directly, **not** the session-presence fallback
    `adjusted_excess` falls back to for a card that took zero trades -- a zero-trade card has no
    deployed capital to divide by, regardless of what fraction of sessions it was flat-but-present, and
    dividing by an unmeasured deployed-capital figure would misstate the ratio rather than merely
    approximate it.

    Returns `None` when `adjusted_excess` itself is `None` (unknown benchmark), when exposure is
    unmeasurable (no trades, or zero sessions), or when exposure is below `MIN_EXPOSURE_FOR_RATIO` --
    see that constant's docstring for why a near-zero denominator is refused rather than divided by.
    """
    adjusted = adjusted_excess(result)
    if adjusted is None:
        return None
    exposure = capital_exposure(result)
    if exposure is None or exposure < MIN_EXPOSURE_FOR_RATIO:
        return None
    return adjusted / exposure


#: Trading-to-calendar year conversion for `window_years`, duplicated from `strategy-program/tools/
#: windows.py`'s `_TRADING_DAYS_PER_YEAR` for the same reason `MAIN_WINDOW_TAGS` is duplicated rather
#: than imported (see this module's top-of-file comment) -- the conventional US-market trading-day
#: count per year.
_TRADING_DAYS_PER_YEAR = Decimal(252)


def window_years(result: AgentResult) -> Decimal | None:
    """Elapsed length of the window ``result`` was run over, in years.

    Round 5's 27 windows range from 125 to 2517 *sessions* (`data/rounds/r5-2026-08/windows.json`),
    and the horizon-aware metrics below need that length to turn a whole-window return into a per-year
    one. `sessions` is exactly what `AgentResult` carries here, and it is the *only* window-length
    signal available at this level: the per-card run file this module loads
    (`<window-tag>/runs/<round>-<agent_id>.json`, see `load_results`) has no window start or end date
    of its own -- confirmed by inspecting a real one (`data/rounds/r4-2026-08/results/inflation-2021/
    runs/r1-B-momentum.json`), whose keys are exactly `AgentResult`'s fields and nothing more. The
    window's calendar dates do exist, but only on the sibling per-window `tournament.json` /
    `tournament-r1.json` (`TournamentResult.trade_start` / `.trade_end`) that `load_results` never
    reads -- pulling them in would mean this module starts reading a second file per window directory
    for a length figure `sessions` already gives closely enough (see below), which is not worth the
    added surface.

    Reconstructing a length from the card's own `trades` (first `entry_date` to last `exit_date`) was
    considered and rejected: that measures how much of the window the card happened to be *active*
    in, not how long the window itself was. A card that opened one trade on day 3 and closed it on day
    10 of a 2517-session window would then report a "10 calendar day" window -- wrong in exactly the
    way a horizon-aware metric exists to avoid, and wrong worse for a card that took no trades at all
    (no dates to reconstruct from, in a window that certainly still had a length).

    So this falls back to `sessions / 252` (`_TRADING_DAYS_PER_YEAR`), the same conventional US-market
    trading-day rate `strategy-program/tools/windows.py` already uses for calendar-to-bar conversion.
    Checked against `windows.json`'s own `sessions` figures this reproduces round 5's intended horizons
    closely: 125-127 sessions -> ~0.496-0.504y (labelled "6m"), 250-254 -> ~0.992-1.008y ("1y"),
    751-756 -> ~2.98-3.00y ("3y"), 1256-1260 -> ~4.98-5.00y ("5y"), 2515-2517 -> ~9.98-9.99y ("10y") --
    every window lands closer to its own label than to either neighbouring horizon, so `R5_HORIZON`'s
    hand-assigned labels and this computed length never disagree enough to matter.

    `None` when `sessions` is not a usable window length (zero or negative) -- an unmeasurable length,
    not a zero-year one, matching this file's convention of never substituting a missing number with a
    number that looks like a real answer.
    """
    if result.sessions < 1:
        return None
    return Decimal(result.sessions) / _TRADING_DAYS_PER_YEAR


def annualized_return(result: AgentResult) -> Decimal | None:
    """`(1 + corrected_return) ** (1 / window_years) - 1` -- the card's own compounding rate, cleared
    of how long the window happened to be.

    `Decimal` has no fractional-exponent operator (`Decimal ** Decimal` only accepts an integral
    exponent), so the root is taken by round-tripping through `float` --
    ``float(base) ** (1.0 / float(years))``, then back through ``Decimal(str(...))`` -- and back into
    `Decimal` for the subtraction. This is the one inexact step in this function and the three others
    built on the same pattern (`annualized_benchmark`, `annualized_adjusted_excess`); every
    non-annualized metric earlier in this module (`corrected_return`, `excess`, `adjusted_excess`, ...)
    remains exact `Decimal` arithmetic, untouched by this -- `tests/test_score_matrix.py` asserts exact
    values against those and only checks the annualized figures to a stated tolerance, for exactly this
    reason.

    `None`, not raised, in two degenerate cases -- matching this file's convention that an
    unmeasurable number is reported as missing rather than invented or treated as an error:

    * `window_years(result) is None` -- an unusable session count, nothing to annualize against.
    * `1 + corrected_return <= 0`, i.e. a total loss of 100% or worse. A zero or negative base has no
      real-valued fractional root (`(-0.2) ** (1/3)` is complex-valued, not the real cube root of
      -0.2's magnitude negated), so there is no real number this function could return without
      arbitrarily picking one branch of a multivalued root. A wipeout is not a bug in this scorer --
      it is a real, reportable outcome for a frozen card -- so it gets `None` here rather than an
      exception, the same way `capital_exposure` and `excess` return `None` for their own
      unmeasurable inputs.
    """
    years = window_years(result)
    if years is None:
        return None
    base = Decimal(1) + corrected_return(result)
    if base <= 0:
        return None
    root = float(base) ** (1.0 / float(years))
    return Decimal(str(root)) - 1


def annualized_benchmark(result: AgentResult) -> Decimal | None:
    """`annualized_return`'s sibling computation applied to the window's benchmark return instead of
    the card's -- same window length, same float-root-and-back mechanism, same degenerate cases.

    `None` when `result.benchmark_return` is `None` (never substituted with zero -- see `excess`'s
    docstring for why an unknown benchmark is not a zero-return one), when `window_years` is `None`, or
    when the benchmark itself lost 100% or more over the window (see `annualized_return`'s docstring
    for why that has no real root to take).
    """
    if result.benchmark_return is None:
        return None
    years = window_years(result)
    if years is None:
        return None
    base = Decimal(1) + result.benchmark_return
    if base <= 0:
        return None
    root = float(base) ** (1.0 / float(years))
    return Decimal(str(root)) - 1


def annualized_adjusted_excess(result: AgentResult) -> Decimal | None:
    """`annualized_return - (capital_exposure * annualized_benchmark)` -- the horizon-comparable
    counterpart to `adjusted_excess`, and the metric round 5's per-horizon aggregates
    (`HorizonScore`) are built from.

    **Why the exposure correction lands on the annualized benchmark, and not on an annualized
    `adjusted_excess`.** The tempting shortcut is to annualize the whole-window `adjusted_excess`
    figure directly -- ``(1 + adjusted_excess) ** (1/years) - 1`` -- and stop there, treating it as
    just another return to root. It is not: `adjusted_excess = corrected_return - exposure *
    benchmark_return` is a *linear* combination of two returns, not itself the growth rate of any real
    equity curve, so raising `(1 + adjusted_excess)` to a fractional power does not undo any actual
    compounding process the way it does for `corrected_return` or `benchmark_return` on their own --
    there is nothing on the other side of that root to reconstruct.

    It also fails an ordinary case the real computation handles correctly. Take a card exposed at 50%
    against a benchmark that fell 80% over the window: the exposure term alone contributes
    `-0.5 * -0.8 = +0.40` to `adjusted_excess`, comfortably positive, even for a card whose own
    `corrected_return` was a -95% wipeout -- exactly the case `annualized_return` refuses to annualize
    and correctly reports as `None` (see its docstring). Annualizing the *blended* `adjusted_excess`
    figure instead would silently smuggle a real wipeout past that guard, because the exposure credit
    can keep the blended base positive even when the card's own return alone would not be.

    The order used here avoids both problems: annualize the card's own equity curve and the
    benchmark's own equity curve *separately* first -- each is a real compounding process with a real
    root, so each root is a real annual rate -- and only take the exposure-weighted difference
    *between* those two annual rates afterwards. That is the same order `adjusted_excess` itself
    already uses (subtract after computing each side); the only change is that both sides are put on a
    per-year basis before the subtraction instead of left as whole-window totals.

    `capital_exposure` is not itself annualized -- it is a fraction of capital deployed, not a return,
    and has no window-length dependence to correct for. Same fallback as `adjusted_excess`: the
    session-presence `exposure` figure only when a card took zero trades, where the two agree at zero
    anyway (see `adjusted_excess`'s docstring).

    `None` when either annualized component is `None` (unusable window length, unknown benchmark, or
    either side's whole-window return being -100% or worse) or when exposure cannot be measured at
    all.
    """
    ann_return = annualized_return(result)
    if ann_return is None:
        return None
    ann_bench = annualized_benchmark(result)
    if ann_bench is None:
        return None
    exposure = capital_exposure(result)
    if exposure is None:
        if result.exposure is None:
            return None
        exposure = Decimal(str(result.exposure))
    return ann_return - (exposure * ann_bench)


@dataclass(frozen=True, slots=True)
class WindowCell:
    """One (card, window) cell of the scorecard -- what happened, or why nothing did.

    ``status`` is one of:

    * ``"run"`` -- an `AgentResult` was found and loaded; `excess`/`adjusted_excess` are its metrics
      (either of which may still be `None` if the run itself lacked an exposure or benchmark figure).
    * ``"not_run"`` -- no result file exists for this (card, window) pair, and either no eligibility
      map was supplied or the map says this window *was* eligible. The runner should have produced a
      file here and did not.
    * ``"not_eligible"`` -- no result file exists, and the caller-supplied eligibility map says this
      card could not legally run in this window (`reason` carries the map's explanation, e.g. a
      `strategy_program.tools.windows.eligible_windows` string). This is the expected, unremarkable
      case for e.g. a 2023-IPO universe against `gfc`.

    A missing cell is never rendered as a zero -- see the module docstring.
    """

    status: str
    excess: Decimal | None = None
    adjusted_excess: Decimal | None = None
    trades: int | None = None
    reason: str | None = None

    #: Both exposures and both returns are carried so a reader can see the corrections rather than
    #: having to trust them. `reported_return` is the runner's defective `total_return` and
    #: `session_exposure` its session-presence figure; see `strategy-program/DEFECTS.md` D1 and D2.
    corrected_return_: Decimal | None = None
    reported_return: Decimal | None = None
    capital_exposure_: Decimal | None = None
    session_exposure: float | None = None

    #: `realised_pnl(result)` and `excess_per_exposure(result)` -- see their docstrings. Both `None`
    #: for a non-"run" cell, same as every other per-result field above.
    realised_pnl: Decimal | None = None
    excess_per_exposure: Decimal | None = None


@dataclass(frozen=True, slots=True)
class HorizonScore:
    """One card's aggregate over one horizon's windows, within one arm (see `CardScore.
    per_horizon_ladder` / `.per_horizon_bear`) -- round 5's answer to "is this card's ranking the same
    at every holding period, or does it depend on one".

    Built from `annualized_adjusted_excess`, never `adjusted_excess` -- a 6-month window's raw
    adjusted excess and a 10-year window's are not the same unit (see the module docstring), so a
    median across horizons only means something once every window has been put on a per-year basis
    first.

    `n_windows` is how many of this horizon's windows (within this arm) the card actually has a run
    result for -- present regardless of whether the gate below is cleared, so a reader can see "1 of
    2" rather than the horizon simply vanishing from the report. `gate_cleared` is `n_windows >=
    Matrix.min_ranked_per_horizon`; when `False`, `median_annualized_adjusted_excess`, `worst_
    annualized_adjusted_excess` and `hit_rate` are all `None` -- a "median" of one window is not a
    median, and this file does not report a number that looks like one under that name. When `True`
    they are computed over exactly the windows counted in `n_windows`, skipping any individual window
    where `annualized_adjusted_excess` itself returned `None` (unusable window length, unknown
    benchmark, or a -100%-or-worse total return on either side) -- the same skip-nulls convention
    `aggregate_card` already applies to the whole-matrix median.
    """

    horizon: str
    arm: str
    n_windows: int
    median_annualized_adjusted_excess: Decimal | None
    worst_annualized_adjusted_excess: Decimal | None
    hit_rate: float | None
    gate_cleared: bool


def _horizon_group_scores(
    tags: Sequence[str],
    main_run_results: Mapping[str, AgentResult],
    *,
    arm: str,
    min_per_horizon: int,
) -> dict[str, HorizonScore]:
    """Group ``tags`` (already restricted to one arm) by `R5_HORIZON`, and aggregate
    `annualized_adjusted_excess` within each group that has at least one run window.

    Only horizons the card has *some* run result for appear in the returned dict at all -- a horizon
    with zero run windows is not a `HorizonScore` with `n_windows=0`, it is simply absent, matching
    this file's convention (see `WindowCell`) that an unmeasured thing is missing, not present with a
    value of zero. A horizon that is present but below ``min_per_horizon`` is still included, with
    ``gate_cleared=False`` and the aggregate fields `None`, so a renderer can tell "no data" apart
    from "not enough data" instead of both collapsing to the same blank cell.
    """
    by_horizon: dict[str, list[str]] = {}
    for tag in tags:
        horizon = R5_HORIZON.get(tag)
        if horizon is not None:
            by_horizon.setdefault(horizon, []).append(tag)

    out: dict[str, HorizonScore] = {}
    for horizon in HORIZON_ORDER:
        run_tags = [t for t in by_horizon.get(horizon, ()) if t in main_run_results]
        n_windows = len(run_tags)
        if n_windows == 0:
            continue
        gate_cleared = n_windows >= min_per_horizon
        values = (
            [
                v
                for t in run_tags
                if (v := annualized_adjusted_excess(main_run_results[t])) is not None
            ]
            if gate_cleared
            else []
        )
        out[horizon] = HorizonScore(
            horizon=horizon,
            arm=arm,
            n_windows=n_windows,
            median_annualized_adjusted_excess=statistics.median(values) if values else None,
            worst_annualized_adjusted_excess=min(values) if values else None,
            hit_rate=(sum(1 for v in values if v > 0) / len(values)) if values else None,
            gate_cleared=gate_cleared,
        )
    return out


@dataclass(frozen=True, slots=True)
class CardScore:
    """One card's aggregate across the main windows it was actually run in, plus every window cell
    for display. See the module docstring for `ranked`.

    **The dominance fields** (`rank_median`, `rank_worst`, `rank_hit_rate`, `borda`,
    `pareto_optimal`) exist because ranking on `median_adjusted_excess` alone places a convex,
    insurance-like payoff last: round 1's `c04-riskmanaged` returned +26.03% adjusted excess in the
    GFC -- best in the field by 17 points -- while costing about 2.5 points in each ordinary window,
    and its median of -2.51% ranked it 17th of 18. The median cannot tell a card that is flat because
    it is hedged apart from one that is flat because it never traded; these fields are a second view
    built to make that distinction visible rather than a replacement for the median.

    `rank_median`, `rank_worst` and `rank_hit_rate` are each card's 1-indexed rank against every other
    *ranked* card on that one criterion (`median_adjusted_excess`, `worst_adjusted_excess`, `hit_rate`
    respectively), all descending -- rank 1 is best on that criterion. **Ties share the average of the
    ranks they span**: two cards tied for the best value on a criterion both occupy ranks 1 and 2 and
    are both recorded as 1.5, rather than one arbitrarily winning the tie. `borda` is the unweighted
    mean of those three ranks -- the Borda composite, and an alternative ordering a single-window
    payoff can survive that a median-only ranking cannot. `pareto_optimal` is `True` when no other
    ranked card is at least as good on all three of (median, worst, hit rate) *and* strictly better on
    at least one -- the non-dominated frontier, i.e. the set of cards no other card straightforwardly
    beats. All five are `None`/`False` for a card outside the comparison set: an unranked card, or a
    ranked card missing one of the three underlying values (see `aggregate_card`). See
    `compute_dominance`.

    **`provenance_violation`** is `True` when a run file exists for a window the eligibility map marks
    ineligible specifically because the card's basket was not yet knowable there (see
    `aggregate_card`) -- a stronger finding than an ordinary eligibility disagreement, and one that
    forces `ranked=False` regardless of how many other main windows the card cleared.

    **`total_realised_pnl`** is the sum of `realised_pnl(result)` (actual dollar P&L, no adjustment)
    over the card's run main windows -- see that function's docstring for why it needs to sit beside
    `adjusted_excess` rather than be left to a reader's mental arithmetic.

    **`median_excess_per_exposure`** is the median of `excess_per_exposure(result)` over the same
    windows, skipping any window where that function returned `None` (exposure unmeasurable or below
    `MIN_EXPOSURE_FOR_RATIO`) -- the scale-free companion to `median_adjusted_excess`, and a
    `--rank-by` choice in its own right (`RANK_BY_CHOICES`).

    **`incommensurable_exposure`** is `True` when this card's `mean_exposure` differs from the ranked
    field's median `mean_exposure` by more than a factor of two in either direction (see
    `flag_incommensurable_exposure`). A flagged card's `median_adjusted_excess` is not on the same
    scale as the rest of the table -- the metric scales with exposure (see `excess_per_exposure`'s
    docstring), so ranking a 45%-exposure book against a 5%-exposure one on that column compares
    quantities of different magnitude, and a reader should be told rather than left to infer it from
    the `mean_exposure` column on their own. `False` by default and for any card not yet passed through
    `flag_incommensurable_exposure`.

    **`per_horizon_ladder`** and **`per_horizon_bear`** are round 5's horizon breakdown: `{horizon:
    HorizonScore}` (see that class), one dict per arm, populated by `aggregate_card` only when scoring
    against a matrix that defines `min_ranked_per_horizon` (`R5_MATRIX`; both stay `{}` for `R2_MATRIX`
    and `R4_MATRIX`, which have no horizon concept). Kept as **two** dicts rather than one keyed by
    `(arm, horizon)` or folded together, because the ladder arm's 6-month and 1-year windows are
    sampled from ordinary calendar history while the bear arm's same-named horizons were deliberately
    selected to start near a market top and run through a real drawdown -- averaging the two together
    into one "6m" number would reintroduce, inside round 5 itself, exactly the selection effect round
    4's design (frozen cards, no window reuse) and this file's own `REPORT.md` §2 finding (exposure
    correlating with adjusted excess in a crash window) were both about: a card's 6-month number would
    silently become part-ordinary-market, part-crash, in a proportion nobody chose on purpose. Keeping
    them separate means a reader who wants "how does this card do over an ordinary 6 months" and one
    who wants "how does it do heading into a crash" each get an honest, unmixed answer.
    """

    agent_id: str
    display_name: str | None
    per_window: dict[str, WindowCell]

    median_adjusted_excess: Decimal | None
    worst_adjusted_excess: Decimal | None
    best_adjusted_excess: Decimal | None
    hit_rate: float | None
    iqr: Decimal | None

    n_windows_run: int
    n_windows_eligible: int
    total_trades: int
    mean_exposure: float | None
    worst_drawdown: Decimal | None

    ranked: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    #: See the class docstring's "dominance fields" paragraph. Populated by `compute_dominance`;
    #: `None` (or `False` for `pareto_optimal`) until then, and for any card outside the comparison
    #: set.
    rank_median: float | None = None
    rank_worst: float | None = None
    rank_hit_rate: float | None = None
    borda: float | None = None
    pareto_optimal: bool = False

    #: See the class docstring's "provenance_violation" paragraph.
    provenance_violation: bool = False

    #: See the class docstring's "total_realised_pnl", "median_excess_per_exposure" and
    #: "incommensurable_exposure" paragraphs.
    total_realised_pnl: Decimal | None = None
    median_excess_per_exposure: Decimal | None = None
    incommensurable_exposure: bool = False

    #: See the class docstring's "per_horizon_ladder" / "per_horizon_bear" paragraph. `{}` for every
    #: matrix except `R5_MATRIX`.
    per_horizon_ladder: dict[str, HorizonScore] = field(default_factory=dict)
    per_horizon_bear: dict[str, HorizonScore] = field(default_factory=dict)


def _discover_window_tags(results_root: Path, *, matrix: Matrix = R2_MATRIX) -> list[str]:
    """Every subdirectory of ``results_root`` that looks like a window's output (has a ``runs/``
    folder), ordered with the five main windows first in their canonical order, then anything else
    (e.g. ``13f-legal``) alphabetically -- so the main regimes always read left-to-right in the same
    order `strategy-program/WINDOWS.md` presents them, and a special-case window never displaces one.
    """
    if not results_root.is_dir():
        return []
    found = {p.name for p in results_root.iterdir() if p.is_dir() and (p / "runs").is_dir()}
    ordered = [tag for tag in matrix.tags if tag in found]
    ordered += sorted(found - set(matrix.tags))
    return ordered


def _discover_round_tag(results_root: Path, window_tags: list[str]) -> str | None:
    """Infer the round prefix from the run filenames actually on disk, for the CLI's `--round`,
    which the round's own README (`strategy-program/README.md`) documents as omittable -- there is
    only ever one round being scored out of a given results tree, and making an operator retype the
    round tag it can already read off the filenames is a chance to typo it into silently scoring
    nothing (see `load_results`: a wrong `round_tag` globs zero files, not an error).

    A run filename is ``<round>-<agent_id>.json`` and `agent_id` itself may contain hyphens (e.g.
    ``r1-c01-meanrev.json``), so the round tag is taken as the text before the *first* hyphen in the
    stem. Returns `None` -- not a guess -- when zero run files exist yet (a results tree still being
    written) or when more than one prefix is found (a results tree mixing two rounds' output), either
    of which the caller should surface as an actionable error rather than scoring the wrong thing.
    """
    prefixes: set[str] = set()
    for tag in window_tags:
        runs_dir = results_root / tag / "runs"
        if not runs_dir.is_dir():
            continue
        for path in runs_dir.glob("*.json"):
            prefixes.add(path.stem.split("-", 1)[0])
    return prefixes.pop() if len(prefixes) == 1 else None


def load_results(
    results_root: Path, round_tag: str, window_tags: list[str]
) -> dict[str, dict[str, AgentResult]]:
    """Every `AgentResult` actually on disk, as ``{window_tag: {agent_id: AgentResult}}``.

    Only files that exist are in the returned mapping -- a (window, agent) pair with no file simply
    has no entry, which is what lets `_cell` tell "not run" apart from a zero result later. The
    filename's own agent-id segment is not trusted as the key; `card.agent_id` from the parsed file
    is, in case the two ever disagree (a copy-paste rename, for instance) -- the file's *content* is
    the source of truth for whose result it is.
    """
    out: dict[str, dict[str, AgentResult]] = {}
    for tag in window_tags:
        runs_dir = results_root / tag / "runs"
        agents: dict[str, AgentResult] = {}
        if runs_dir.is_dir():
            for path in sorted(runs_dir.glob(f"{round_tag}-*.json")):
                result = AgentResult.model_validate_json(path.read_text(encoding="utf-8"))
                agents[result.card.agent_id] = result
        out[tag] = agents
    return out


def _load_eligibility(path: Path | None) -> dict[str, dict[str, bool | str]]:
    """Parse the optional ``--eligibility`` file: ``{agent_id: {window_tag: true | false | "reason"}}``.

    Produced by e.g. dumping `strategy_program.tools.windows.eligible_windows`'s return value per
    card to JSON. Absent entirely when no file is given -- callers of `score_round` then get
    ``"not_run"`` for every missing cell rather than ``"not_eligible"``, since without the map there
    is no way to tell the two apart (see `WindowCell`).
    """
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object of {{agent_id: {{window_tag: ...}}}}")
    return raw


def _cell(
    tag: str,
    result: AgentResult | None,
    eligibility_for_card: Mapping[str, bool | str] | None,
) -> WindowCell:
    if result is not None:
        return WindowCell(
            status="run",
            excess=excess(result),
            adjusted_excess=adjusted_excess(result),
            trades=len(result.trades),
            corrected_return_=corrected_return(result),
            reported_return=result.total_return,
            capital_exposure_=capital_exposure(result),
            session_exposure=result.exposure,
            realised_pnl=realised_pnl(result),
            excess_per_exposure=excess_per_exposure(result),
        )
    verdict = None if eligibility_for_card is None else eligibility_for_card.get(tag)
    if verdict is not None and verdict is not True:
        reason = verdict if isinstance(verdict, str) else "not eligible"
        return WindowCell(status="not_eligible", reason=reason)
    return WindowCell(status="not_run")


def aggregate_card(
    agent_id: str,
    display_name: str | None,
    per_window: dict[str, WindowCell],
    main_run_results: Mapping[str, AgentResult],
    eligibility_for_card: Mapping[str, bool | str] | None,
    *,
    matrix: Matrix = R2_MATRIX,
) -> CardScore:
    """Roll one card's main-window cells up into the numbers it is ranked and reported on.

    ``main_run_results`` is ``{window_tag: AgentResult}`` restricted to the main windows this card
    was actually run in -- the aggregate is computed over exactly that set, **not** filtered a second
    time by the eligibility map. In the well-formed case (the runner only ever attempts windows
    `strategy_program.tools.windows.eligible_windows` cleared) "run" and "eligible" are the same set
    for every main window, and the map's only job here is explaining *missing* cells (see
    `WindowCell`). A run that somehow exists for a window the map calls ineligible is ordinarily
    surfaced as a note rather than silently dropped or silently trusted -- that disagreement between
    the map and the file on disk is worth a human's attention on its own.

    **Provenance disagreements are treated more harshly.** When ``eligibility_for_card`` marks a
    window ineligible specifically because the card's basket was not yet knowable there (a reason
    string carrying `_PROVENANCE_REASON_PREFIX`, produced by
    `strategy_program.tools.windows.eligible_windows`'s `universe_knowable_from` check) and a run file
    exists for it anyway, that is not an ordinary bookkeeping mismatch -- it is basket lookahead, the
    exact failure `PROTOCOL.md` §5 describes: "a portfolio chosen with knowledge of which names would
    work." Round 1 aggregated such a card's numbers with only a note and ranked it anyway (`REPORT.md`
    §5); that is too weak a response to a lookahead violation, so here the card is forced
    ``ranked=False`` regardless of how many other main windows it cleared, `provenance_violation` is
    set, and a warning naming the card and window is printed -- in addition to, not instead of, the
    real numbers still being computed and returned (an unranked card's numbers are still reported; see
    the module docstring).
    """
    run_tags = [tag for tag in matrix.tags if tag in main_run_results]
    n_windows_run = len(run_tags)
    results = [main_run_results[tag] for tag in run_tags]

    def _provenance_reason(tag: str) -> str | None:
        if eligibility_for_card is None:
            return None
        verdict = eligibility_for_card.get(tag)
        if isinstance(verdict, str) and verdict.startswith(_PROVENANCE_REASON_PREFIX):
            return verdict
        return None

    # Scanned over every window this card has a *run* result for, main and special-case alike (a
    # provenance violation in e.g. a 13F-only special window would be just as real a lookahead as one
    # in a main window) -- not just `run_tags`, which is main-windows-only and exists for the gate math
    # above, a different concern.
    provenance_violations = {
        tag: reason
        for tag, cell in per_window.items()
        if cell.status == "run" and (reason := _provenance_reason(tag)) is not None
    }
    for tag, reason in provenance_violations.items():
        print(
            f"WARNING: {agent_id} has a run file for window '{tag}', but the eligibility map "
            f"marks it ineligible for provenance reasons ({reason}) -- this is basket lookahead, "
            f"not an ordinary eligibility mismatch; {agent_id} is reported as unranked."
        )

    notes: list[str] = []
    if provenance_violations:
        notes.append(
            "PROVENANCE VIOLATION -- run file(s) exist for window(s) the eligibility map marks "
            "ineligible because the basket was not yet knowable there: "
            + ", ".join(f"{tag} ({reason})" for tag, reason in provenance_violations.items())
            + " -- this is basket lookahead (PROTOCOL.md §5), not an ordinary eligibility "
            "disagreement; the card is unranked as a result"
        )

    if eligibility_for_card is not None:
        n_windows_eligible = sum(
            1 for tag in matrix.tags if eligibility_for_card.get(tag) is True
        )
        disagreements = [
            tag
            for tag in run_tags
            if eligibility_for_card.get(tag) is not True and tag not in provenance_violations
        ]
        if disagreements:
            notes.append(
                "ran in window(s) the eligibility map marks ineligible: "
                + ", ".join(disagreements)
                + " -- included in the aggregate anyway; the map and the run files disagree"
            )
    else:
        # No map supplied: "eligible" cannot be distinguished from "run" -- see `WindowCell` and
        # `_load_eligibility` -- so the only honest answer is to report what is actually known.
        n_windows_eligible = n_windows_run

    adjusted_values = [v for r in results if (v := adjusted_excess(r)) is not None]
    n_null_adjusted = len(results) - len(adjusted_values)
    if n_null_adjusted:
        notes.append(
            f"adjusted_excess unavailable for {n_null_adjusted} of {len(results)} run window(s) "
            "(null exposure or benchmark_return) -- excluded from median/worst/best/hit_rate/iqr"
        )

    median_adj = statistics.median(adjusted_values) if adjusted_values else None
    worst_adj = min(adjusted_values) if adjusted_values else None
    best_adj = max(adjusted_values) if adjusted_values else None
    hit_rate = (
        sum(1 for v in adjusted_values if v > 0) / len(adjusted_values) if adjusted_values else None
    )
    if len(adjusted_values) >= 2:
        q1, _q2, q3 = statistics.quantiles(adjusted_values, n=4, method="inclusive")
        iqr = q3 - q1
    else:
        iqr = None

    ratio_values = [v for r in results if (v := excess_per_exposure(r)) is not None]
    n_null_ratio = len(results) - len(ratio_values)
    if n_null_ratio:
        notes.append(
            f"excess_per_exposure unavailable for {n_null_ratio} of {len(results)} run window(s) "
            f"(exposure unmeasurable or below the {float(MIN_EXPOSURE_FOR_RATIO) * 100:.0f}% floor) -- "
            "excluded from median_excess_per_exposure"
        )
    median_ratio = statistics.median(ratio_values) if ratio_values else None

    total_realised_pnl = (
        sum((realised_pnl(r) for r in results), start=Decimal(0)) if results else None
    )

    total_trades = sum(len(r.trades) for r in results)
    # Capital-weighted, not the runner's session-presence figure -- DEFECTS.md D2. A card that held
    # one of four slots throughout would otherwise report a mean exposure of 1.0.
    capital_exposures = [
        float(ce) for r in results if (ce := capital_exposure(r)) is not None
    ]
    mean_exposure = statistics.fmean(capital_exposures) if capital_exposures else None
    # `max_drawdown` is reported negative (see `AgentResult.max_drawdown`'s docstring); the worst of
    # several drawdowns is the most negative one, i.e. the minimum.
    worst_drawdown = min((r.max_drawdown for r in results), default=None)

    ranked = (
        n_windows_run >= matrix.min_ranked
        and total_trades > 0
        and not provenance_violations
    )

    # Horizon breakdown (round 5 only -- see `Matrix.min_ranked_per_horizon`'s docstring for why this
    # is gated on that field being set rather than on `matrix is R5_MATRIX`, which would not extend to
    # a future matrix that also wants horizons). Computed over `run_tags` -- the same main-window run
    # set every other aggregate above is computed over -- split into the two arms by `_R5_TAG_ARM`.
    if matrix.min_ranked_per_horizon is not None:
        ladder_tags = [tag for tag in run_tags if _R5_TAG_ARM.get(tag) == "ladder"]
        bear_tags = [tag for tag in run_tags if _R5_TAG_ARM.get(tag) == "bear"]
        per_horizon_ladder = _horizon_group_scores(
            ladder_tags, main_run_results, arm="ladder", min_per_horizon=matrix.min_ranked_per_horizon
        )
        per_horizon_bear = _horizon_group_scores(
            bear_tags, main_run_results, arm="bear", min_per_horizon=matrix.min_ranked_per_horizon
        )
    else:
        per_horizon_ladder = {}
        per_horizon_bear = {}

    return CardScore(
        agent_id=agent_id,
        display_name=display_name,
        per_window=per_window,
        median_adjusted_excess=median_adj,
        worst_adjusted_excess=worst_adj,
        best_adjusted_excess=best_adj,
        hit_rate=hit_rate,
        iqr=iqr,
        n_windows_run=n_windows_run,
        n_windows_eligible=n_windows_eligible,
        total_trades=total_trades,
        mean_exposure=mean_exposure,
        worst_drawdown=worst_drawdown,
        ranked=ranked,
        notes=tuple(notes),
        provenance_violation=bool(provenance_violations),
        total_realised_pnl=total_realised_pnl,
        median_excess_per_exposure=median_ratio,
        per_horizon_ladder=per_horizon_ladder,
        per_horizon_bear=per_horizon_bear,
    )


#: `--rank-by` / `score_round`'s `rank_by` choices. `"median"` is the default and reproduces this
#: module's original behaviour exactly (see `reorder_by_rank_criterion`); `"worst"`, `"hit-rate"` and
#: `"borda"` are the dominance view's alternative orderings -- see `CardScore`'s docstring and
#: `compute_dominance`. `"excess-per-exposure"` orders on `median_excess_per_exposure` -- the
#: scale-free view; see `excess_per_exposure`'s docstring for why the median alone is not commensurable
#: across cards at very different exposure.
RANK_BY_CHOICES: tuple[str, ...] = ("median", "worst", "hit-rate", "borda", "excess-per-exposure")


def _average_rank_desc(values: Mapping[str, Decimal | float]) -> dict[str, float]:
    """1-indexed rank of each key's value, descending -- rank 1 is the largest value.

    Ties share the average of the ranks they span: two keys tied for the single best value occupy
    ranks 1 and 2 and are both recorded as ``1.5``, rather than an arbitrary one of them winning the
    tie -- the standard convention for a Borda count, and the one `CardScore`'s docstring promises.
    """
    ordered = sorted(values, key=lambda k: values[k], reverse=True)
    ranks: dict[str, float] = {}
    n = len(ordered)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[ordered[j + 1]] == values[ordered[i]]:
            j += 1
        avg_rank = (i + 1 + j + 1) / 2
        for key in ordered[i : j + 1]:
            ranks[key] = avg_rank
        i = j + 1
    return ranks


def compute_dominance(cards: list[CardScore]) -> list[CardScore]:
    """Attach per-criterion ranks, the Borda composite, and Pareto non-dominance to ``cards``.

    ``cards`` must already be restricted to cards with all three of `median_adjusted_excess`,
    `worst_adjusted_excess` and `hit_rate` present (non-`None`) -- typically the ranked cards that
    also cleared `MIN_RANKED_MAIN_WINDOWS` with a computable median; `score_round` does this filtering
    before calling. A card missing any of the three cannot be ranked or dominance-compared honestly,
    so it is the caller's job to exclude it rather than this function's to guess a substitute.

    Returns a new list, same order and length as ``cards`` (each element replaced via
    `dataclasses.replace`, since `CardScore` is frozen) with `rank_median`, `rank_worst`,
    `rank_hit_rate`, `borda` and `pareto_optimal` populated. `[]` in, `[]` out.

    **Ranks** are computed independently on each criterion via `_average_rank_desc`, all descending
    (rank 1 = best on that one criterion), with ties sharing the average rank they span.

    **`borda`** is the unweighted mean of a card's three ranks -- lower is better, matching the ranks
    it is built from. It is a second ordering, not a replacement for the median: see `CardScore`'s
    docstring for why a convex, insurance-like payoff needs one.

    **`pareto_optimal`** is `True` when no other card in ``cards`` dominates this one -- "dominates"
    meaning at least as good on all three of (median, worst, hit rate) and strictly better on at least
    one. The non-dominated set is every card for which that is true: the defensible choices, as
    distinct from any single ordering's idea of "the best" choice.
    """
    if not cards:
        return []

    median_ranks = _average_rank_desc({c.agent_id: c.median_adjusted_excess for c in cards})
    worst_ranks = _average_rank_desc({c.agent_id: c.worst_adjusted_excess for c in cards})
    hit_ranks = _average_rank_desc({c.agent_id: c.hit_rate for c in cards})

    def _dominates(a: CardScore, b: CardScore) -> bool:
        at_least_as_good = (
            a.median_adjusted_excess >= b.median_adjusted_excess
            and a.worst_adjusted_excess >= b.worst_adjusted_excess
            and a.hit_rate >= b.hit_rate
        )
        strictly_better = (
            a.median_adjusted_excess > b.median_adjusted_excess
            or a.worst_adjusted_excess > b.worst_adjusted_excess
            or a.hit_rate > b.hit_rate
        )
        return at_least_as_good and strictly_better

    out: list[CardScore] = []
    for card in cards:
        pareto_optimal = not any(
            _dominates(other, card) for other in cards if other.agent_id != card.agent_id
        )
        borda = (median_ranks[card.agent_id] + worst_ranks[card.agent_id] + hit_ranks[card.agent_id]) / 3
        out.append(
            replace(
                card,
                rank_median=median_ranks[card.agent_id],
                rank_worst=worst_ranks[card.agent_id],
                rank_hit_rate=hit_ranks[card.agent_id],
                borda=borda,
                pareto_optimal=pareto_optimal,
            )
        )
    return out


def flag_incommensurable_exposure(
    cards: list[CardScore], reference: list[CardScore] | None = None
) -> list[CardScore]:
    """Mark every card in ``cards`` whose `mean_exposure` differs from the *reference* field's median
    `mean_exposure` by more than a factor of two, in either direction.

    `adjusted_excess` scales with capital exposure (see `excess_per_exposure`'s docstring and
    `REPORT.md` §2's r = +0.797 finding), so a card held at 45% capital and one held at 5% do not
    produce comparable numbers on that column even though both cleared the same ranking gate. Rather
    than require a reader to eyeball the `mean_exposure` column and do that division themselves, this
    marks the row.

    ``reference`` defaults to ``cards`` itself; callers pass it explicitly to flag e.g. the unranked
    table against the *ranked* field's median rather than its own (an unranked card's own peer group is
    the ranked field it failed to clear, not other unranked cards). Cards with `mean_exposure is None`
    (no measurable trades) are never flagged -- there is no exposure figure to compare -- and if
    ``reference`` yields no cards with a measurable exposure at all (or a zero median), every card is
    returned unmarked, since "differs by a factor of two" is not answerable against nothing or against
    zero.

    Returns a new list, same order and length as ``cards`` (each element replaced via
    `dataclasses.replace` where the flag actually changes, since `CardScore` is frozen).
    """
    pool = cards if reference is None else reference
    exposures = [c.mean_exposure for c in pool if c.mean_exposure is not None]
    if not exposures:
        return cards
    field_median = statistics.median(exposures)
    if field_median <= 0:
        return cards

    out: list[CardScore] = []
    for card in cards:
        flagged = card.mean_exposure is not None and (
            card.mean_exposure > field_median * 2 or card.mean_exposure < field_median / 2
        )
        out.append(replace(card, incommensurable_exposure=flagged))
    return out


def reorder_by_rank_criterion(cards: list[CardScore], rank_by: str) -> list[CardScore]:
    """Reorder ``cards`` (assumed already dominance-decorated, or not needing to be for ``"median"``)
    by one of `RANK_BY_CHOICES`.

    A card missing the chosen criterion's value is appended at the end, in its original relative
    order, rather than sorted among the cards that have a value -- the same rule this module has
    always applied to a missing `median_adjusted_excess` (see `score_round`'s docstring on why sorting
    can't tolerate a mix of `None` and a real value). ``rank_by="median"`` -- the default everywhere
    this is called from -- reproduces `score_round`'s original, pre-dominance ordering exactly: this
    function *is* that ordering, generalised to the other three criteria rather than reimplemented
    separately for them.

    `worst` and `hit-rate` sort descending (a higher worst-window or hit-rate is better, same
    direction as `median`). `borda` sorts ascending: it is a mean of ranks, where 1 is best, so a
    *smaller* Borda number is the better card.
    """
    if rank_by not in RANK_BY_CHOICES:
        raise ValueError(f"rank_by must be one of {RANK_BY_CHOICES}, got {rank_by!r}")
    key_fn: Any
    key_fn, reverse = {
        "median": (lambda c: c.median_adjusted_excess, True),
        "worst": (lambda c: c.worst_adjusted_excess, True),
        "hit-rate": (lambda c: c.hit_rate, True),
        "borda": (lambda c: c.borda, False),
        "excess-per-exposure": (lambda c: c.median_excess_per_exposure, True),
    }[rank_by]
    with_value = sorted((c for c in cards if key_fn(c) is not None), key=key_fn, reverse=reverse)
    without_value = [c for c in cards if key_fn(c) is None]
    return with_value + without_value


def score_round(
    results_root: Path,
    round_tag: str,
    *,
    eligibility: Mapping[str, Mapping[str, bool | str]] | None = None,
    window_tags: list[str] | None = None,
    rank_by: str = "median",
    matrix: Matrix = R2_MATRIX,
) -> tuple[list[CardScore], list[CardScore], list[str]]:
    """Load every result under ``results_root`` and score every card found.

    Returns ``(ranked, unranked, window_tags)``: ``ranked`` ordered by ``rank_by`` (one of
    `RANK_BY_CHOICES`; `"median"`, the default, preserves this function's original behaviour --
    descending `median_adjusted_excess`, cards with no computable median appended last), ``unranked``
    in `agent_id` order (there is no meaningful sort key for cards excluded from the ranking --
    sorting them by a number that disqualified them from ranking would just be the ranking again
    under a different name), and the window tags actually discovered on disk, main windows first then
    any special-case windows (`_discover_window_tags`), for callers that want to render exactly the
    columns that exist rather than assuming the main tags are the whole set.

    Every card in ``ranked`` that has all three of `median_adjusted_excess`, `worst_adjusted_excess`
    and `hit_rate` gets its dominance fields populated (`compute_dominance`) regardless of
    ``rank_by`` -- ``rank_by`` only controls display order, never which columns exist, so a reader
    ordered by one criterion can still see the other two plus the Borda composite and the Pareto
    frontier.
    """
    tags = (
        window_tags
        if window_tags is not None
        else _discover_window_tags(results_root, matrix=matrix)
    )
    by_window = load_results(results_root, round_tag, tags)

    agent_ids: set[str] = set()
    for agents in by_window.values():
        agent_ids.update(agents)
    if eligibility is not None:
        agent_ids.update(eligibility)

    scores: list[CardScore] = []
    for agent_id in sorted(agent_ids):
        elig_for_card = eligibility.get(agent_id) if eligibility is not None else None
        per_window = {
            tag: _cell(tag, by_window.get(tag, {}).get(agent_id), elig_for_card) for tag in tags
        }
        main_run_results = {
            tag: by_window[tag][agent_id]
            for tag in matrix.tags
            if tag in by_window and agent_id in by_window[tag]
        }
        display_name = next(
            (r.card.display_name for r in main_run_results.values()), None
        ) or next(
            (agents[agent_id].card.display_name for agents in by_window.values() if agent_id in agents),
            None,
        )
        scores.append(
            aggregate_card(
                agent_id,
                display_name,
                per_window,
                main_run_results,
                elig_for_card,
                matrix=matrix,
            )
        )

    # A ranked card can, in principle, still have `median_adjusted_excess is None` if every run it
    # has lacked an exposure or benchmark figure -- rare, but a real possibility, not merely a
    # theoretical one: nothing about `ranked` (enough main windows run, >0 trades, no provenance
    # violation) guarantees any of those runs carried an exposure or benchmark figure. `worst_adjusted_
    # excess` and `hit_rate` are `None` in exactly the same cases (`aggregate_card` derives all three
    # from the same `adjusted_values` list), so filtering on the median alone is sufficient to also
    # guarantee the other two are present for `compute_dominance`.
    if rank_by not in RANK_BY_CHOICES:
        raise ValueError(f"rank_by must be one of {RANK_BY_CHOICES}, got {rank_by!r}")

    ranked_candidates = [s for s in scores if s.ranked]
    dominance_eligible = [s for s in ranked_candidates if s.median_adjusted_excess is not None]
    decorated_by_id = {c.agent_id: c for c in compute_dominance(dominance_eligible)}
    ranked_candidates = [decorated_by_id.get(s.agent_id, s) for s in ranked_candidates]

    ranked = reorder_by_rank_criterion(ranked_candidates, rank_by)

    unranked = sorted((s for s in scores if not s.ranked), key=lambda s: s.agent_id)

    # Incommensurable-exposure flag (see `flag_incommensurable_exposure`): computed against the
    # *ranked* field's median `mean_exposure` in both cases -- that field is the comparison set a
    # reader is actually weighing a card's `median_adjusted_excess` against, whether the card itself
    # made the cut or not.
    ranked = flag_incommensurable_exposure(ranked, reference=ranked)
    unranked = flag_incommensurable_exposure(unranked, reference=ranked)

    return ranked, unranked, tags


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _pct(value: Decimal | float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:+.2f}%"


def _money(value: Decimal | None) -> str:
    """A dollar figure -- `realised_pnl`/`total_realised_pnl` -- as `+$123.45` / `-$123.45`, never a
    percentage; distinct from `_pct` so the two are never mistaken for each other in a table cell."""
    if value is None:
        return "n/a"
    return f"{'+' if value >= 0 else '-'}${abs(value):,.2f}"


def _cell_text(cell: WindowCell) -> str:
    if cell.status == "run":
        return _pct(cell.adjusted_excess)
    if cell.status == "not_eligible":
        return "not eligible"
    return "not run"


#: Human-readable label for each `RANK_BY_CHOICES` value, used only for `render_markdown`'s section
#: header -- the underlying data and every other column are identical regardless of which is chosen
#: (see `CardScore`'s docstring: `rank_by` changes display order, never which columns exist).
_RANK_BY_LABEL: dict[str, str] = {
    "median": "median adjusted_excess",
    "worst": "worst-window adjusted_excess",
    "hit-rate": "hit_rate",
    "borda": "Borda composite (mean rank across median, worst, hit_rate -- lower is better)",
    "excess-per-exposure": "median excess_per_exposure (adjusted_excess per unit of capital deployed)",
}


def render_markdown(
    ranked: list[CardScore],
    unranked: list[CardScore],
    window_tags: list[str],
    *,
    rank_by: str = "median",
    matrix: Matrix = R2_MATRIX,
) -> str:
    """The stdout report: a ranked table, the Pareto frontier, then unranked cards in their own
    labelled section.

    Every window's `adjusted_excess` gets its own column (not just the aggregate) so a reader can see
    the distribution behind the median rather than trusting one number -- a card that is +8% in four
    windows and -40% in one has a very different risk profile from one that is +2% five times, and
    both can produce a similar median.

    ``rank_by`` (one of `RANK_BY_CHOICES`, default `"median"`, matching `score_round`'s default and
    this function's original, single-ordering behaviour) only changes the section header's wording --
    it does *not* change which columns are printed. `ranked` is assumed already sorted the way the
    caller wants (`reorder_by_rank_criterion`); this function does not sort. Every dominance column
    (`rank_median`, `rank_worst`, `rank_hit_rate`, `borda`, whether the card is on the Pareto frontier)
    is always present in the table regardless of ``rank_by``, so no ordering hides the others.
    """
    lines: list[str] = []

    def table(cards: list[CardScore], *, ranked_column: bool) -> None:
        headers = (["rank"] if ranked_column else []) + [
            "agent_id",
            "display_name",
            "median_adj_excess",
            "worst",
            "best",
            "hit_rate",
            "iqr",
            "rank_median",
            "rank_worst",
            "rank_hit_rate",
            "borda",
            "pareto",
            "windows(run/elig)",
            "trades",
            "mean_exposure",
            "incommensurable_exposure",
            "worst_dd",
            "total_realised_pnl",
            "median_excess_per_exposure",
            *window_tags,
        ]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join("---" for _ in headers) + "|")
        for i, card in enumerate(cards, start=1):
            row = ([str(i)] if ranked_column else []) + [
                card.agent_id,
                card.display_name or "?",
                _pct(card.median_adjusted_excess),
                _pct(card.worst_adjusted_excess),
                _pct(card.best_adjusted_excess),
                "n/a" if card.hit_rate is None else f"{card.hit_rate * 100:.2f}%",
                _pct(card.iqr),
                "n/a" if card.rank_median is None else f"{card.rank_median:g}",
                "n/a" if card.rank_worst is None else f"{card.rank_worst:g}",
                "n/a" if card.rank_hit_rate is None else f"{card.rank_hit_rate:g}",
                "n/a" if card.borda is None else f"{card.borda:.2f}",
                "yes" if card.pareto_optimal else "no",
                f"{card.n_windows_run}/{card.n_windows_eligible}",
                str(card.total_trades),
                "n/a" if card.mean_exposure is None else f"{card.mean_exposure * 100:.2f}%",
                "yes" if card.incommensurable_exposure else "no",
                _pct(card.worst_drawdown),
                _money(card.total_realised_pnl),
                _pct(card.median_excess_per_exposure),
                *(_cell_text(card.per_window[tag]) for tag in window_tags),
            ]
            lines.append("| " + " | ".join(row) + " |")

    label = _RANK_BY_LABEL.get(rank_by, rank_by)
    lines.append(f"## Ranked (by {label}, descending)")
    lines.append("")
    if ranked:
        table(ranked, ranked_column=True)
    else:
        lines.append("_No card cleared the ranking gate._")
    lines.append("")

    lines.append("## Pareto frontier -- the defensible choices, not a single ordering's winner")
    lines.append("")
    lines.append(
        "A card is on the frontier when no other ranked card is at least as good on all of "
        "(median, worst-window, hit-rate) *and* strictly better on at least one. This is the honest "
        "answer to \"which cards are defensible choices\" -- a single ordering, whichever criterion "
        "it uses, cannot give that answer on its own."
    )
    lines.append("")
    lines.append(
        "**Exposure caveat.** The worst-window criterion structurally favours low-exposure books -- a "
        "book that never puts much capital at risk cannot sustain a deep drawdown, so a small book "
        "reaches a shallow worst window almost for free, the same way a large negative benchmark "
        "structurally favours it on adjusted_excess (see the incommensurable-exposure flag above). "
        "Frontier membership earned mainly on the worst-window axis is not the same finding as "
        "frontier membership earned on the median, and both are weaker evidence for a card whose "
        "`mean_exposure` sits well below the field's -- read the column below beside every row rather "
        "than trusting frontier membership alone."
    )
    lines.append("")
    frontier = [c for c in ranked if c.pareto_optimal]
    if frontier:
        headers = [
            "agent_id",
            "display_name",
            "median_adj_excess",
            "worst",
            "hit_rate",
            "borda",
            "mean_exposure",
            "incommensurable_exposure",
        ]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join("---" for _ in headers) + "|")
        for card in sorted(
            frontier,
            key=lambda c: (
                c.median_adjusted_excess if c.median_adjusted_excess is not None else Decimal(0)
            ),
            reverse=True,
        ):
            lines.append(
                "| "
                + " | ".join(
                    [
                        card.agent_id,
                        card.display_name or "?",
                        _pct(card.median_adjusted_excess),
                        _pct(card.worst_adjusted_excess),
                        "n/a" if card.hit_rate is None else f"{card.hit_rate * 100:.2f}%",
                        "n/a" if card.borda is None else f"{card.borda:.2f}",
                        "n/a" if card.mean_exposure is None else f"{card.mean_exposure * 100:.2f}%",
                        "yes" if card.incommensurable_exposure else "no",
                    ]
                )
                + " |"
            )
    else:
        lines.append(
            "_No card has all three dominance values computed, or the comparison set is empty._"
        )
    lines.append("")

    lines.append(
        f"## Unranked (fewer than {matrix.min_ranked} main windows run, zero trades in every "
        "window run, or a provenance violation (a run file for a window the eligibility map marks "
        "ineligible because the basket was not yet knowable there) -- excluded from the ranking, not "
        "placed last"
    )
    lines.append("")
    if unranked:
        table(unranked, ranked_column=False)
    else:
        lines.append("_Every scored card is ranked._")

    # Horizon breakdown -- round 5 only. Gated on `matrix.min_ranked_per_horizon` being set (not on
    # `matrix is R5_MATRIX`, for the same reason `aggregate_card`'s equivalent gate is written that
    # way): rounds 2-4 have no horizon concept, and their published reports must stay byte-identical to
    # what they are today (`tests/test_score_matrix.py`'s `TestReproducibility...` guards this), so
    # nothing below this line is ever reached for `R2_MATRIX` or `R4_MATRIX`.
    if matrix.min_ranked_per_horizon is not None:
        all_cards = ranked + unranked

        def _horizon_cell(hs: HorizonScore | None) -> str:
            if hs is None:
                return "n/a"
            if not hs.gate_cleared:
                return f"below gate ({hs.n_windows}/{matrix.min_ranked_per_horizon} run)"
            return _pct(hs.median_annualized_adjusted_excess)

        def horizon_table(cards: list[CardScore], attr: str) -> None:
            headers = ["agent_id", "display_name", *HORIZON_ORDER]
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("|" + "|".join("---" for _ in headers) + "|")
            for card in cards:
                per_horizon: dict[str, HorizonScore] = getattr(card, attr)
                row = [
                    card.agent_id,
                    card.display_name or "?",
                    *(_horizon_cell(per_horizon.get(h)) for h in HORIZON_ORDER),
                ]
                lines.append("| " + " | ".join(row) + " |")

        lines.append("")
        lines.append("## Horizon breakdown -- annualized adjusted excess by holding period")
        lines.append("")
        lines.append(
            "Every column below is **annualized** adjusted excess (`annualized_adjusted_excess`), not "
            "the whole-window `adjusted_excess` the tables above report. Round 5's windows range from "
            "6 months to 10 years (`data/rounds/r5-2026-08/windows.json`), and the benchmark alone "
            "returns roughly +6% over the shortest of those and +259% over the longest -- a 10-year "
            "window's raw adjusted excess and a 6-month window's are not measured in the same unit, so "
            "a median taken across all of them, the way the tables above take one median across a "
            "single matrix's windows, would average quantities that only coincidentally share a "
            "percent sign. Annualizing puts every window on the same per-year basis before it is "
            "compared or median'd at all. A cell reading `below gate (n/k)` means the card ran fewer "
            "than `k` of that horizon's windows -- the 10-year horizon has only two windows in the "
            "entire matrix, so a single 10-year run is not a sample size this report will dress up as "
            "a median."
        )
        lines.append("")
        lines.append("### Ladder arm -- windows sampled across ordinary calendar history")
        lines.append("")
        horizon_table(all_cards, "per_horizon_ladder")
        lines.append("")
        lines.append(
            "### Bear arm -- windows deliberately chosen to start near a top and run through a "
            "drawdown"
        )
        lines.append("")
        lines.append(
            "Reported in a separate table, never merged into the ladder arm's same-named horizons "
            "(6m, 1y) above. The bear arm was selected *for* a falling benchmark -- mixing its windows "
            "into the ladder's medians would reintroduce, inside round 5 itself, the exact selection "
            "effect round 4's design and this file's exposure-correlation finding (see the module "
            "docstring) were both about: a card's 6-month number would silently become part-ordinary, "
            "part-crash, in a mix nobody chose on purpose."
        )
        lines.append("")
        horizon_table(all_cards, "per_horizon_bear")

    notable = [(c.agent_id, n) for c in (ranked + unranked) for n in c.notes]
    if notable:
        lines.append("")
        lines.append("## Notes")
        lines.append("")
        for agent_id, note in notable:
            lines.append(f"- **{agent_id}**: {note}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def _jsonable(value: Any, *, include_horizons: bool = False) -> Any:
    """``include_horizons`` adds `CardScore.per_horizon_ladder` / `.per_horizon_bear` to a serialized
    card's JSON. It defaults to `False` and is threaded in by `_build_json` only for `R5_MATRIX`
    (`matrix.min_ranked_per_horizon is not None`) so that rounds 2-4's scorecard JSON -- already
    published -- gains no new keys and stays byte-identical to what it is today; see this module's
    reproducibility test. For every matrix, `per_horizon_ladder`/`.bear` are `{}` anyway when horizons
    do not apply, so this flag is about *schema* stability (no new key appears at all), not about
    hiding a non-empty value.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, WindowCell):
        return {
            "status": value.status,
            "excess": _jsonable(value.excess),
            "adjusted_excess": _jsonable(value.adjusted_excess),
            "trades": value.trades,
            "reason": value.reason,
            "realised_pnl": _jsonable(value.realised_pnl),
            "excess_per_exposure": _jsonable(value.excess_per_exposure),
        }
    if isinstance(value, HorizonScore):
        return {
            "horizon": value.horizon,
            "arm": value.arm,
            "n_windows": value.n_windows,
            "median_annualized_adjusted_excess": _jsonable(value.median_annualized_adjusted_excess),
            "worst_annualized_adjusted_excess": _jsonable(value.worst_annualized_adjusted_excess),
            "hit_rate": value.hit_rate,
            "gate_cleared": value.gate_cleared,
        }
    if isinstance(value, CardScore):
        out = {
            "agent_id": value.agent_id,
            "display_name": value.display_name,
            "ranked": value.ranked,
            "median_adjusted_excess": _jsonable(value.median_adjusted_excess),
            "worst_adjusted_excess": _jsonable(value.worst_adjusted_excess),
            "best_adjusted_excess": _jsonable(value.best_adjusted_excess),
            "hit_rate": value.hit_rate,
            "iqr": _jsonable(value.iqr),
            "n_windows_run": value.n_windows_run,
            "n_windows_eligible": value.n_windows_eligible,
            "total_trades": value.total_trades,
            "mean_exposure": value.mean_exposure,
            "worst_drawdown": _jsonable(value.worst_drawdown),
            "notes": list(value.notes),
            "windows": {tag: _jsonable(cell) for tag, cell in value.per_window.items()},
            # Dominance view (see `CardScore`'s docstring and `compute_dominance`): `None`/`False` for
            # a card outside the comparison set (unranked, or missing one of the three metrics).
            "rank_median": value.rank_median,
            "rank_worst": value.rank_worst,
            "rank_hit_rate": value.rank_hit_rate,
            "borda": value.borda,
            "pareto_optimal": value.pareto_optimal,
            # `True` when this card is unranked specifically because a run file exists for a window
            # the eligibility map marks ineligible for provenance (basket-lookahead) reasons -- see
            # `aggregate_card`.
            "provenance_violation": value.provenance_violation,
            # See `CardScore`'s docstring: the realised-P&L decomposition, the scale-free exposure
            # ratio, and whether this card's exposure is too far from the ranked field's median to be
            # commensurable with it on `median_adjusted_excess`.
            "total_realised_pnl": _jsonable(value.total_realised_pnl),
            "median_excess_per_exposure": _jsonable(value.median_excess_per_exposure),
            "incommensurable_exposure": value.incommensurable_exposure,
        }
        if include_horizons:
            out["per_horizon_ladder"] = {
                h: _jsonable(hs) for h, hs in value.per_horizon_ladder.items()
            }
            out["per_horizon_bear"] = {
                h: _jsonable(hs) for h, hs in value.per_horizon_bear.items()
            }
        return out
    return value


def _build_json(
    ranked: list[CardScore],
    unranked: list[CardScore],
    window_tags: list[str],
    *,
    results_root: Path,
    round_tag: str,
    rank_by: str = "median",
    matrix: Matrix = R2_MATRIX,
    store_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # `include_horizons` (and the extra `min_ranked_per_horizon`/`horizon_order` keys below) are added
    # only when `matrix` actually has a horizon concept -- see `_jsonable`'s docstring. Rounds 2-4's
    # published scorecard JSON must not gain new top-level keys any more than a card's own JSON should;
    # both are the same reproducibility promise applied at a different level of the document.
    include_horizons = matrix.min_ranked_per_horizon is not None
    out: dict[str, Any] = {
        "results_root": str(results_root),
        "round": round_tag,
        "window_tags": window_tags,
        "matrix": matrix.name,
        "main_window_tags": list(matrix.tags),
        "min_ranked_main_windows": matrix.min_ranked,
        "rank_by": rank_by,
        "rank_by_choices": list(RANK_BY_CHOICES),
        "pareto_frontier": [c.agent_id for c in ranked if c.pareto_optimal],
        "ranked": [_jsonable(c, include_horizons=include_horizons) for c in ranked],
        "unranked": [_jsonable(c, include_horizons=include_horizons) for c in unranked],
    }
    if include_horizons:
        out["min_ranked_per_horizon"] = matrix.min_ranked_per_horizon
        out["horizon_order"] = list(HORIZON_ORDER)
    # `store_state` is the DEFECTS.md D6 pin: row count and last bar per symbol, measured at run
    # time, so a later round compares against a *measurement* rather than against a row count
    # transcribed from an earlier document's prose. It defaults to absent, which is what keeps the
    # promise three lines above intact -- re-scoring rounds 2-4 without `--pin-store` reproduces
    # their published JSON byte for byte, because a key nobody asked for is never added.
    if store_state is not None:
        out["store_state"] = store_state
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _load_storestate() -> Any:
    """`strategy-program/tools/storestate.py`, loaded by path, on demand.

    Lazily rather than at module import for two reasons. It keeps importing `score` free of side
    effects -- `scoreboard.py` and four test modules import it, and none of them wants a `sys.path`
    entry appearing underneath them. And it keeps `app.db.duck` (and DuckDB itself) off the import
    path of every caller that only ever wanted to rank a results tree.

    This is the `spec_from_file_location` dance `MAIN_WINDOW_TAGS`' comment calls more fragile than
    duplicating eight strings, and that judgement still holds *for eight strings*. A whole module is
    the other side of the trade: `storestate` is ~300 lines with its own tests, and a second copy of
    it living here is not a thing to keep in sync by inspection.
    """
    import importlib.util

    path = Path(__file__).resolve().parent / "storestate.py"
    spec = importlib.util.spec_from_file_location("strategy_program_tools_storestate", path)
    if spec is None or spec.loader is None:  # pragma: no cover -- only if the file is deleted
        raise ImportError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        "--results-root",  # accepted for anyone who copied the old flag name before it was renamed
        # to match strategy-program/README.md's documented invocation, which never had the "-root"
        # suffix.
        dest="results_root",
        type=Path,
        required=True,
        help="directory containing <window-tag>/runs/<round>-<agent_id>.json",
    )
    parser.add_argument(
        "--round",
        dest="round_tag",
        default=None,
        help="round prefix on each run filename, e.g. 'r1' for 'r1-<agent_id>.json'. Optional -- "
        "strategy-program/README.md's documented invocation omits it, since a results tree only "
        "ever holds one round's output; auto-detected from the run filenames on disk when omitted "
        "(see _discover_round_tag), and reported as an error rather than guessed if that is "
        "ambiguous or nothing has been written yet.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        required=True,
        help="path to write the machine-readable scorecard",
    )
    parser.add_argument(
        "--pin-store",
        dest="pin_store",
        action="store_true",
        help="record the bar store's row count and last bar date per symbol into the scorecard as "
        "'store_state' (DEFECTS.md D6). Off by default so re-scoring an already-published round "
        "reproduces its JSON exactly; on for every new round.",
    )
    parser.add_argument(
        "--compare-store",
        dest="compare_store",
        type=Path,
        default=None,
        help="path to an earlier scorecard.json carrying a 'store_state' pin. Reports which symbols "
        "moved since that round ran, and by how much, instead of comparing against a row count "
        "quoted in prose. Reports only -- it never fails the run, because whether drift can reach a "
        "round's own bounded windows is a reading of that round, not a property of the store.",
    )
    parser.add_argument(
        "--eligibility",
        type=Path,
        default=None,
        help="optional JSON {agent_id: {window_tag: true|false|reason}} (see "
        "strategy_program.tools.windows.eligible_windows) so a missing cell can be reported as "
        "'not eligible' instead of 'not run'",
    )
    parser.add_argument(
        "--windows",
        default=None,
        help="comma-separated window tags to score over, restricting the ranking to a set every "
        "card shares. Without this the median is taken over whichever windows each card happened "
        "to run in, and two cards' medians can then cover different regimes -- a card scored on "
        "{gfc, covid, bear-2022} is not comparable to one scored on {covid, bear-2022, bull-2024}, "
        "though both clear the same-size window gate. Ranking a mixed field needs this.",
    )
    parser.add_argument(
        "--matrix",
        choices=sorted(MATRICES),
        default=None,
        help="which round's window matrix to rank over: 'r2' (the eight regimes rounds 2-3 used), "
        "'r4' (round 4's six, which share none of them), or 'r5' (round 5's 27-window horizon "
        "ladder plus bear arm, which adds a per-horizon gate and a horizon breakdown to the report -- "
        "see Matrix.min_ranked_per_horizon). Auto-detected from the window directories on disk when "
        "omitted, and reported as an error rather than guessed when the tree touches more than one "
        "matrix or none -- scoring against the wrong matrix produces an empty leaderboard rather than "
        "a failure, so it must not be guessed.",
    )
    parser.add_argument(
        "--rank-by",
        dest="rank_by",
        choices=RANK_BY_CHOICES,
        default="median",
        help="which criterion orders the primary (ranked-column) table: 'median' (default, this "
        "module's original ranking key), 'worst' (the worst-window adjusted_excess -- the "
        "generalisation test), 'hit-rate', 'borda' (the mean of a card's rank on all three -- a "
        "dominance view a convex, insurance-like payoff can survive that ranking on the median alone "
        "cannot; see CardScore's docstring), or 'excess-per-exposure' (median adjusted_excess per unit "
        "of capital deployed -- the scale-free view; see excess_per_exposure's docstring for why "
        "median_adjusted_excess is not commensurable across cards at very different exposure). Every "
        "column -- including the other orderings and the Pareto frontier -- is printed regardless of "
        "which one is chosen here.",
    )
    args = parser.parse_args(argv)

    # Window discovery has to happen before round-tag auto-detection (it needs to know which
    # `<tag>/runs/` directories to look inside), and `score_round` would otherwise repeat it -- so it
    # is done once here and the result is threaded through explicitly.
    matrix = (
        MATRICES[args.matrix]
        if args.matrix
        else detect_matrix(
            [p.name for p in args.results_root.iterdir() if p.is_dir()]
            if args.results_root.is_dir()
            else []
        )
    )
    if matrix is None:
        print(
            f"could not tell which window matrix {args.results_root} belongs to (its window "
            f"directories touch both or neither of {', '.join(sorted(MATRICES))}) -- pass "
            "--matrix explicitly"
        )
        return 1

    window_tags = _discover_window_tags(args.results_root, matrix=matrix)
    if not window_tags:
        print(f"no window directories with a runs/ folder found under {args.results_root}")
        return 1

    if args.windows is not None:
        requested = [tag.strip() for tag in args.windows.split(",") if tag.strip()]
        missing = [tag for tag in requested if tag not in window_tags]
        if missing:
            print(
                f"--windows names {', '.join(missing)}, which has no runs/ directory under "
                f"{args.results_root}; found {', '.join(window_tags)}"
            )
            return 1
        window_tags = requested

    round_tag = args.round_tag
    if round_tag is None:
        round_tag = _discover_round_tag(args.results_root, window_tags)
        if round_tag is None:
            print(
                f"could not auto-detect a single round tag from run filenames under "
                f"{args.results_root} (found none, or more than one prefix) -- pass --round explicitly"
            )
            return 1

    eligibility = _load_eligibility(args.eligibility) or None
    ranked, unranked, window_tags = score_round(
        args.results_root,
        round_tag,
        eligibility=eligibility,
        window_tags=window_tags,
        rank_by=args.rank_by,
        matrix=matrix,
    )

    store_state_json: dict[str, Any] | None = None
    if args.pin_store:
        storestate = _load_storestate()
        try:
            store_state_json = storestate.state_to_json(storestate.capture())
        except Exception as exc:
            # An unpinned round is a lesser failure than an unscored one, so this does not abort.
            # What it must not do is write an *empty* pin: that would serialise as a measurement
            # saying the store held nothing, which is precisely the "empty result that reads like
            # nothing happened" mistake D6 is about. The key is omitted instead, and a later
            # `--compare-store` against this scorecard says "recorded no pin" rather than
            # "unchanged".
            print(f"warning: could not pin the bar store ({type(exc).__name__}: {exc}); "
                  f"scorecard will carry no store_state")

    report = _build_json(
        ranked,
        unranked,
        window_tags,
        results_root=args.results_root,
        round_tag=round_tag,
        rank_by=args.rank_by,
        matrix=matrix,
        store_state=store_state_json,
    )
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"matrix: {matrix.name} ({len(matrix.tags)} windows, gate {matrix.min_ranked})")
    print(
        render_markdown(
            ranked, unranked, window_tags, rank_by=args.rank_by, matrix=matrix
        )
    )
    print(f"wrote {args.json}")

    if args.compare_store is not None:
        storestate = _load_storestate()
        try:
            pinned = storestate.load_pin(args.compare_store)
        except (OSError, ValueError) as exc:
            print(f"warning: could not read a store pin from {args.compare_store}: {exc}")
        else:
            if pinned is None:
                print(
                    f"store check: {args.compare_store} records no pin -- it was scored before "
                    "--pin-store existed, so there is nothing to compare against. This is not "
                    "'unchanged'."
                )
            else:
                drift = storestate.compare(pinned, storestate.capture())
                print(f"store check: {storestate.describe_drift(drift)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
