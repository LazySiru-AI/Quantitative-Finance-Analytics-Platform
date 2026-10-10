"""Ten independent :class:`~app.tournament.models.AgentResult` into one
:class:`~app.tournament.models.TournamentResult`, corrected for the fact that ten strategies were
tried.

**What this module adds on top of a single agent's numbers.** `app.backtest.scan` already proved,
for a scan over rule conditions, that testing many hypotheses and reporting the ones that cleared
``p <= 0.05`` overstates the evidence unless the comparison is corrected across every hypothesis
attempted -- including the ones that could not be tested at all. A tournament of ten analysts is the
same shape of problem wearing a different costume: :func:`score` runs `app.backtest.scan`'s exact
`binomial_p_value` and `benjamini_hochberg` -- unchanged, not reimplemented -- across the ten agents
instead of across ten rule conditions, and fills in the four fields
`app.tournament.runner` deliberately leaves `None` on each `AgentResult`: `profit_factor`,
`realised_reward_risk`, `p_value`, `q_value`.

**Every derived statistic here distinguishes "zero" from "cannot be measured."** A strategy with no
losing trades does not have infinite profit factor; a strategy with three closed trades does not have
a meaningful p-value; a strategy with zero trades has no realised reward:risk at all. Each is `None`,
not `0` or `1.0`, and each `None` is explained where it is produced -- collapsing "no data" into a
number that looks like a measurement is exactly the kind of error the rest of this package (see
`app.tournament.models`'s module docstring) is built to keep out of the report.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from decimal import Decimal

from app.backtest.scan import benjamini_hochberg, binomial_p_value
from app.tournament.models import (
    TRADE_END,
    TRADE_START,
    AgentResult,
    RealisedTrade,
    TournamentResult,
)

__all__ = ["score"]


MIN_CLOSED_TRADES_FOR_P_VALUE = 10
"""Floor below which no p-value is computed, rather than computing one from a handful of trades.

At `trials=10`, the most extreme possible outcome (10 wins, 0 losses) against a 0.5 null has p =
0.001953125 -- comfortably below any alpha this tournament would use. At `trials=5`, the same most
extreme outcome has p = 0.0625, which is already close to `alpha=0.10`: a strategy that happened to
close five trades and win (or lose) every one of them would look like weak-to-moderate evidence
purely from having almost no data, before Benjamini-Hochberg even runs. Ten is not a principled
threshold in the way the binomial test itself is exact -- any floor here is a judgment call -- but it
puts the *ceiling* of what a minimal sample can claim (the all-wins or all-losses p-value) an order of
magnitude below alpha rather than sitting right on top of it, which three or five trades cannot do.
Below the floor, `p_value` and therefore `q_value` are `None`: the agent still occupies a slot in
`benjamini_hochberg`'s denominator (see its docstring), it just contributes no evidence either way.
"""

NULL_WIN_PROBABILITY = 0.5
"""The null hypothesis behind `p_value`: that each closed trade is a fair coin flip, independent of
whether the strategy has any skill.

**What this does and does not test.** Rejecting this null means the strategy's win rate is unlikely
to have arisen from a fair coin -- nothing more. It is *not* a test of skill relative to the market,
and a long-only strategy trading a rising benchmark can clear it with no edge whatsoever: a
buy-and-hold position in a security that is up over the window wins more than half of any reasonably
sampled sub-periods by construction, not by forecasting anything. A market-relative null (win
probability conditioned on the benchmark's own realised path) would be the more honest test for a
long-only strategy, but building it needs a session-by-session hit-rate for the benchmark over the
same window that neither `AgentResult` nor this module's inputs carry, and manufacturing one here
would be inventing data this module was not given rather than scoring what was. 0.5 is used with that
limitation stated rather than hidden: a `p_value <= alpha` here says the win/loss record is unlikely
under a coin flip, and the report that consumes this module's output is required to say so rather
than imply "beats the market."

**Trades are treated as i.i.d. Bernoulli draws**, which is also an approximation this module does not
attempt to correct further. `app.backtest.forward.independent_count` de-overlaps triggers that share
a fixed forward-return window and a common bar index, which is the right tool for a rule scan over
one symbol's history -- but a `RealisedTrade` log here spans up to `StrategyCard.max_positions`
concurrent symbols with a holding period that varies trade to trade (`bars_held` is realised, not a
fixed horizon), and carries dates rather than bar indices. There is no session calendar available to
this module to translate `entry_date`/`exit_date` into the bar positions `independent_count` needs,
so forcing that machinery on would substitute a wrong adaptation for an honest, stated approximation.
The correlation this leaves uncorrected -- concurrent positions sharing one market regime, one
six-month window -- is the same "one regime, not a sample of regimes" caveat `app.tournament.models`
already states must travel with every report this package produces.
"""


def _profit_factor(trades: Sequence[RealisedTrade]) -> Decimal | None:
    """Gross winning P&L over gross losing P&L. `None`, never an infinite value, when there were no
    losing trades -- a strategy that has not yet lost a trade has not demonstrated it never will, it
    has simply not traded enough to meet a loss, and reporting `inf` would present a sample-size
    artefact as a property of the strategy. Also `None` with no closed trades at all, since gross
    winning and gross losing P&L are both undefined rather than both zero.
    """
    if not trades:
        return None
    winners = [t.pnl for t in trades if t.pnl > 0]
    losers = [t.pnl for t in trades if t.pnl < 0]
    if not losers:
        return None
    gross_win = sum(winners, start=Decimal(0))
    gross_loss = -sum(losers, start=Decimal(0))
    return gross_win / gross_loss


def _realised_reward_risk(trades: Sequence[RealisedTrade]) -> Decimal | None:
    """Mean winning return over mean losing return, as it actually happened -- sits beside
    `StrategyCard.reward_risk`, which is the analyst's planned ratio computed from `stop_loss_pct`
    and `take_profit_pct` alone. The two are expected to diverge: most trades exit on the discretionary
    exit rule or a time stop, not on either bracket, so the planned ratio is rarely what traded.
    `None` when there is nothing to divide -- no closed trades, no winners, or no losers -- rather
    than a ratio computed from an empty mean on either side.
    """
    if not trades:
        return None
    winners = [t.return_pct for t in trades if t.return_pct > 0]
    losers = [t.return_pct for t in trades if t.return_pct < 0]
    if not winners or not losers:
        return None
    mean_win = sum(winners, start=Decimal(0)) / len(winners)
    mean_loss = sum(losers, start=Decimal(0)) / len(losers)
    return mean_win / -mean_loss


def _p_value(result: AgentResult) -> float | None:
    """Two-sided exact binomial p-value on `result.trades`' win/loss record against
    `NULL_WIN_PROBABILITY`, via `app.backtest.scan.binomial_p_value` -- unmodified. `None` below
    `MIN_CLOSED_TRADES_FOR_P_VALUE` closed trades; see that constant's docstring for why. A trade
    counts as a win when `pnl > 0`, strictly -- a breakeven trade is not a win, matching
    `app.backtest.forward.hit_rate`'s convention elsewhere in this codebase -- and losses are every
    other closed trade, so `trials` is always `len(result.trades)` and `successes` is always
    countable without an intermediate "neither" bucket.
    """
    trades = result.trades
    if len(trades) < MIN_CLOSED_TRADES_FOR_P_VALUE:
        return None
    successes = sum(1 for t in trades if t.pnl > 0)
    return binomial_p_value(successes, len(trades), NULL_WIN_PROBABILITY)


def _rank_key(result: AgentResult) -> tuple[float, float, str]:
    """Sort key for the tournament ranking: ascending `q_value`, then ascending `p_value`, then
    `agent_id` for a stable, deterministic order when both are equal or both are `None`.

    **Deliberately not `total_return`.** Ranking by return turns the tournament into exactly the
    return-maximising contest the Benjamini-Hochberg correction exists to counteract: the top
    returner among ten is the maximum of ten noisy draws and would be the top returner whether or
    not any of the ten strategies has genuine edge. Ranking by `q_value` instead orders agents by how
    unlikely their win/loss record is to be noise, which is the quantity this module was built to
    compute and the one the report should lead with.

    Untestable agents (`q_value is None`, below the closed-trade floor) sort *last*, not first.
    `None` is an absence of evidence, not evidence of a strong result, and placing them at the top of
    a ranked list would visually read as the opposite of what the `None` means.
    """
    q = result.q_value if result.q_value is not None else math.inf
    p = result.p_value if result.p_value is not None else math.inf
    return (q, p, result.card.agent_id)


def score(
    results: Sequence[AgentResult],
    *,
    alpha: float = 0.10,
    benchmark_return: Decimal | None = None,
    trade_start: dt.date = TRADE_START,
    trade_end: dt.date = TRADE_END,
) -> TournamentResult:
    """Turn independent per-agent runs into one corrected, ranked `TournamentResult`.

    Per agent: `profit_factor` and `realised_reward_risk` are computed from that agent's own
    `trades` alone (no cross-agent comparison needed for either). `p_value` is computed per agent and
    then all ten (or however many `results` holds) are corrected together via
    `app.backtest.scan.benjamini_hochberg` in one call -- **including** agents whose `p_value` is
    `None`, because `benjamini_hochberg`'s denominator `m = len(p_values)` always, and dropping an
    untestable agent before that call would shrink `m` and mechanically flatter every other agent's
    `q_value`. This is the same rule `app.backtest.scan.scan` follows for untestable rule conditions,
    applied here across agents instead of conditions.

    `discoveries` counts agents with `q_value <= alpha`. Zero is not a failure of this function or a
    reason to widen `alpha` after the fact -- ten strategies over one six-month regime finding zero
    surviving discoveries is the modal, honest outcome the module docstring in
    `app.tournament.models` says to expect, and `discoveries == 0` produces a completely well-formed
    `TournamentResult`, not an error.

    The returned `agents` tuple is ordered by `_rank_key` -- see its docstring for why that is
    `q_value`, not `total_return`. `trade_start`/`trade_end` default to `app.tournament.models`'
    `TRADE_START`/`TRADE_END` but are accepted as parameters -- not read from the module constants
    unconditionally -- because a `TournamentResult` that reports a window it did not actually run is
    worse than useless: `sessions` (measured from the real runs) would silently contradict
    `trade_start`/`trade_end` (the wrong window) in the same object, and nothing downstream would
    notice. `sessions` is the largest `sessions` value across `results` (0 for an empty tournament)
    rather than an arbitrary single agent's, so a defect that shortened one agent's run does not
    silently understate the window for the whole report.

    `benchmark_return`: if not supplied, this function looks for a single consistent value across
    `results`' own `AgentResult.benchmark_return` fields (each agent already carries the same
    buy-and-hold figure computed over its own run) and uses that if every agent agrees; otherwise, or
    with no agents, the tournament-level `benchmark_return` is `None` rather than an arbitrarily
    chosen agent's figure.
    """
    p_values = [_p_value(result) for result in results]
    q_values = benjamini_hochberg(p_values)

    scored = [
        result.model_copy(
            update={
                "profit_factor": _profit_factor(result.trades),
                "realised_reward_risk": _realised_reward_risk(result.trades),
                "p_value": p_value,
                "q_value": q_value,
            }
        )
        for result, p_value, q_value in zip(results, p_values, q_values, strict=True)
    ]

    discoveries = sum(1 for q in q_values if q is not None and q <= alpha)
    ranked = tuple(sorted(scored, key=_rank_key))

    resolved_benchmark_return = benchmark_return
    if resolved_benchmark_return is None and results:
        distinct = {result.benchmark_return for result in results}
        if len(distinct) == 1:
            resolved_benchmark_return = next(iter(distinct))

    sessions = max((result.sessions for result in results), default=0)

    return TournamentResult(
        generated_at=dt.datetime.now(dt.UTC),
        trade_start=trade_start,
        trade_end=trade_end,
        sessions=sessions,
        agents=ranked,
        alpha=alpha,
        discoveries=discoveries,
        benchmark_return=resolved_benchmark_return,
    )
