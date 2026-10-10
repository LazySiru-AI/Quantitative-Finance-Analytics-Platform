"""A contribution-funded portfolio simulator, for strategies run inside a Roth IRA.

Every backtest in this programme so far has been a **lump sum at inception**: put $10,000 in on day
one, never touch it again, and measure what it became. That is the right test for ranking cards
against each other, and it is the wrong test for an account somebody actually funds.

This module models the account as it is really used: contributed on a schedule, not dropped in once.
Two cadences are supported today -- **$7,500 once a year** (the original shape, and every existing
caller's default) and **monthly** (e.g. $1,000/month), because `backend/app/tournament/purposes.py`
now names a `SAVINGS` purpose funded monthly and a `ROTH` purpose funded annually, and the two are not
interchangeable by rescaling: twelve $1,000 deposits spread through a year buy at twelve different
prices, so a monthly stream and an annual stream of the same total produce different answers by
design, not by accident. Three things change from a lump sum, and each one can reverse a conclusion
drawn from that version.

* **Sequence risk inverts.** A lump-sum investor fears a crash at the end, when the balance is
  largest. A contributor is *helped* by a crash early -- the same dollars buy more -- and hurt by one
  late. A strategy that looks defensive under a lump sum can look merely expensive under
  contributions.
* **Return is not one number any more.** Time-weighted CAGR answers "how did the strategy do";
  money-weighted IRR answers "how did *I* do", and they diverge whenever the balance is uneven
  across time -- which, with annual contributions, it always is. Both are reported. Quoting only the
  flattering one is the easiest mistake available here.
* **New cash is a rebalancing tool that costs nothing.** An underweight sleeve can be topped up with
  the contribution instead of by selling the overweight one. Inside a Roth there is no tax on the
  sale either, so the saving is only slippage -- but it is real, and a strategy that ignores it is
  leaving the cheapest trade it has on the table.

**Roth-specific.** No tax is modelled anywhere, because none is owed: no capital gains on rotation,
no wash-sale disallowance, no qualified-dividend holding period. Turnover is therefore close to free
and costs only `slippage_bps`. A strategy rejected in a taxable account for churning may be perfectly
reasonable here, and the comparison in `strategy-program/DRAWDOWN-LADDER.md` -- which assumed
turnover was a cost worth avoiding -- should be re-read with that in mind.

A strategy is expressed as a **weight function**: given the session index and the price history so
far, return the target weight of each symbol. Everything else -- contributions, drift, rebalancing,
slippage, the two return measures -- is handled here, so two strategies compared through this module
differ only in the thing being compared.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

#: Sessions per year, matching `score.py`, `windows.py` and `drawdown_ladder.py`.
TRADING_DAYS = 252

#: The 2026 Roth IRA contribution limit for a single filer under 50, which is what this models.
#: Deliberately a module constant rather than a default argument: it is a fact about the account,
#: not a knob to sweep, and a backtest that quietly used a different number would be comparing
#: strategies at different funding levels without saying so.
ANNUAL_CONTRIBUTION = 7_500.0

#: `SAVINGS`'s own contribution rate (`backend/app/tournament/purposes.py`), parallel to
#: `ANNUAL_CONTRIBUTION` above and for the identical reason: a fact about the account, not a knob.
MONTHLY_CONTRIBUTION = 1_000.0

#: How often the recurring contribution lands. `"annual"` is the default everywhere -- every existing
#: caller of `simulate` gets it implicitly and none has to name it -- `"monthly"` is opt-in via the
#: `contribution=`/`cadence=` pair (see `simulate`'s own docstring for why mixing that pair with the
#: legacy `annual_contribution=` is refused rather than silently resolved).
Cadence = Literal["annual", "monthly"]


@dataclass
class Cashflow:
    date: dt.date
    amount: float


@dataclass
class ContributionResult:
    """Everything needed to judge a contribution-funded run, and nothing derived silently."""

    dates: list[dt.date] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    #: Total contributed *so far* at each session -- the line a balance chart must be read against,
    #: since a balance that only ever rises may still be losing money against what was paid in.
    contributed: list[float] = field(default_factory=list)
    weights: list[dict[str, float]] = field(default_factory=list)
    #: Uninvested cash at the end of each session, purely observational -- recorded regardless of
    #: `cash_constrained`, so a caller can check the invariant `cash_constrained=True` exists to
    #: guarantee (`cash[i] >= 0` for every `i`) directly, instead of reconstructing it from `equity`
    #: and `weights` (which cannot be done exactly, since `weights` is normalised against each
    #: session's *pre*-trade equity while `equity` is recorded *post*-trade).
    cash: list[float] = field(default_factory=list)
    flows: list[Cashflow] = field(default_factory=list)
    rebalances: int = 0
    contribution_buys: int = 0
    turnover: float = 0.0
    cost_paid: float = 0.0
    #: Number of individual buy orders that could not be fully funded out of available cash under
    #: `cash_constrained=True` -- partially filled or, when no cash remained at all, filled for zero.
    #: Always `0` when `cash_constrained=False`, since the unconstrained path never checks cash before
    #: buying.
    underfunded_buys: int = 0
    #: Total dollars of desired-but-unfunded buying under `cash_constrained=True`: for each
    #: underfunded order, `desired move - dollars actually filled`, summed across the whole run. This
    #: is the mechanism behind a cash-constrained drag, not just its size -- pair it with
    #: `underfunded_buys` to say e.g. "214 rejected buys totalling $48,000". Always `0.0` when
    #: `cash_constrained=False`.
    underfunded_shortfall: float = 0.0

    @property
    def final_balance(self) -> float:
        return self.equity[-1]

    @property
    def total_contributed(self) -> float:
        return self.contributed[-1]

    @property
    def profit(self) -> float:
        return self.final_balance - self.total_contributed

    @property
    def multiple(self) -> float:
        """Final balance over total contributed. The number a person actually feels."""
        return self.final_balance / self.total_contributed if self.total_contributed else 0.0

    @property
    def years(self) -> float:
        return len(self.equity) / TRADING_DAYS

    @property
    def irr(self) -> float | None:
        """Money-weighted annual return: the rate that discounts every contribution to the final
        balance. This is "how did I do", and it is the honest headline for a funded account.

        Solved by bisection rather than Newton because the sign structure here is simple (all flows
        negative, one positive terminal value) and bisection cannot diverge. `None` when no bracket
        exists, which happens for a total loss -- reported as unknown rather than clamped.
        """
        flows = [(f.date, -f.amount) for f in self.flows]
        flows.append((self.dates[-1], self.final_balance))
        t0 = flows[0][0]

        def npv(rate: float) -> float:
            return sum(a / (1 + rate) ** ((d - t0).days / 365.25) for d, a in flows)

        lo, hi = -0.9999, 10.0
        if npv(lo) * npv(hi) > 0:
            return None
        for _ in range(200):
            mid = (lo + hi) / 2
            if npv(lo) * npv(mid) <= 0:
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2

    @property
    def time_weighted_cagr(self) -> float:
        """Growth of one dollar left alone, with contributions stripped out -- "how did the strategy
        do", independent of when money arrived. Computed by chain-linking each session's return on
        the balance *before* that session's contribution, so a deposit is never counted as a gain."""
        growth = 1.0
        for i in range(1, len(self.equity)):
            added = self.contributed[i] - self.contributed[i - 1]
            base = self.equity[i - 1] + added
            if base > 0:
                growth *= self.equity[i] / base
        return growth ** (1 / self.years) - 1 if self.years > 0 else 0.0

    @property
    def max_drawdown(self) -> float:
        """Peak-to-trough on the balance **net of contributions**.

        A raw balance drawdown understates the pain badly in a funded account: a deposit landing
        mid-crash lifts the balance and shrinks the measured drawdown, even though every dollar
        already invested fell just as far. This tracks the contribution-adjusted high-water mark
        instead, so the number means what a reader assumes it means.
        """
        peak_excess, worst = 0.0, 0.0
        peak_equity = 0.0
        for eq, con in zip(self.equity, self.contributed, strict=True):
            peak_equity = max(peak_equity, eq)
            if con > 0:
                # Normalise by contributions so a deposit cannot manufacture a new high.
                ratio = eq / con
                peak_excess = max(peak_excess, ratio)
                if peak_excess > 0:
                    worst = min(worst, ratio / peak_excess - 1)
        return worst

    @property
    def volatility(self) -> float:
        rets = []
        for i in range(1, len(self.equity)):
            added = self.contributed[i] - self.contributed[i - 1]
            base = self.equity[i - 1] + added
            if base > 0:
                rets.append(self.equity[i] / base - 1)
        return statistics.pstdev(rets) * (TRADING_DAYS**0.5) if len(rets) > 1 else 0.0

    @property
    def mar(self) -> float:
        return self.time_weighted_cagr / abs(self.max_drawdown) if self.max_drawdown else 0.0


#: A strategy: given the session index and every symbol's closes up to and including it, return the
#: target weight of each symbol. Weights should sum to 1; anything short is held as cash.
WeightFn = Callable[[int, Mapping[str, Sequence[float]]], dict[str, float]]


#: The engine's own business-day arithmetic, imported rather than reimplemented.
#:
#: This module and `app.paper.paperbroker` must agree on the date a sale settles, or a comparison
#: between them measures two different settlement calendars instead of the thing under test. Round 16
#: spent a follow-up establishing that settlement is the term that separates them; a second, subtly
#: different implementation of "advance N business days" here would put that back. It is a private
#: name, and importing it is a deliberate coupling to the definition the engine actually uses -- the
#: alternative is a copy that can drift silently, which is the failure this whole round is about.
from app.paper.paperbroker import _add_business_days as _settles_on  # noqa: E402


def contribution_dates(dates: Sequence[dt.date], cadence: Cadence = "annual") -> list[int]:
    """The first session of each calendar year (`cadence="annual"`, the default -- unchanged from
    this function's original signature, so every existing call site that never names `cadence` keeps
    its exact original behaviour) or the first session of each calendar month (`cadence="monthly"`),
    plus the first session overall in both cases.

    The two cadences share one rule -- "the first session of the period, whatever the period is" --
    rather than monthly being a separate function bolted on beside this one, because that is the same
    rule this function always applied to years, just with the period narrowed. A window's first
    session always funds, even when it lands mid-year or mid-month: a partial opening period is still
    a period this account is funded in, once, on the first session it is observed.

    One deposit a year has far more timing luck in it than twelve monthly ones -- annual remains the
    default for that reason, and because it is what every caller before this parameter existed was
    already relying on.
    """
    if cadence not in ("annual", "monthly"):
        raise ValueError(f"unknown cadence {cadence!r} -- must be 'annual' or 'monthly'")

    def period(d: dt.date) -> tuple[int, int] | int:
        return d.year if cadence == "annual" else (d.year, d.month)

    out = [0]
    for i in range(1, len(dates)):
        if period(dates[i]) != period(dates[i - 1]):
            out.append(i)
    return out


def simulate(
    dates: Sequence[dt.date],
    closes: Mapping[str, Sequence[float]],
    weight_fn: WeightFn,
    *,
    annual_contribution: float = ANNUAL_CONTRIBUTION,
    contribution: float | None = None,
    cadence: Cadence = "annual",
    seed: float = 0.0,
    band_pct: float = 0.05,
    slippage_bps: float = 5.0,
    use_contributions_to_rebalance: bool = True,
    cash_constrained: bool = False,
    settlement_days: int = 0,
) -> ContributionResult:
    """Run `weight_fn` against a contribution-funded account.

    Rebalances only when a symbol drifts more than `band_pct` from its target, or when the target
    itself changes. A daily reset to target would produce turnover that is an artifact of the
    simulation rather than the strategy, and with whole-dollar positions and slippage it would
    dominate the result.

    With `use_contributions_to_rebalance`, each deposit is directed at the most underweight sleeves
    first, and only the residual is spread to target. That is the cheapest rebalancing available --
    no sale, so only the buy side pays slippage -- and it is the mechanism the original ladder
    specification called out as the place most of the real-world edge lives.

    **Two ways to name the recurring deposit, and why they cannot mix.** `annual_contribution` is the
    original parameter: every caller written before this one existed already passes it (or relies on
    its default, `ANNUAL_CONTRIBUTION`), always meaning "once a year," and it keeps meaning exactly
    that -- unchanged in name, default and effect -- so none of those callers has to change a line.
    `contribution` + `cadence` is the new pair, for when the cadence itself is the thing under test:
    `contribution=1_000.0, cadence="monthly"` is not the same claim as `annual_contribution=12_000.0`,
    even though the twelve-month total is identical -- twelve deposits spread through a year buy at
    twelve different prices, and collapsing that into one bigger annual number would silently answer a
    different question than the one asked. Passing both `contribution` and a non-default
    `annual_contribution` raises `ValueError` rather than picking one silently, and passing `cadence`
    without `contribution` raises too -- `annual_contribution` alone can never fund a monthly schedule,
    so naming a monthly cadence without a monthly amount is refused instead of quietly staying annual.
    A monthly amount can therefore never be misread as an annual one, or vice versa: the two parameter
    pairs are mutually exclusive by construction, not by convention.

    **`seed`** is a lump sum credited once, at the account's opening session, alongside that session's
    own first contribution -- one combined cashflow, matching the convention `strategy-program/tools/
    savings_family.py::simulate_savings` already established for the identical shape (its own
    `seed + monthly_contribution` on session zero) before this parameter existed here. Defaults to
    `0.0`, so no existing caller's opening balance changes. A purpose's account that opens with money
    already in it (`SAVINGS`'s $20,000, `ROTH`'s $30,000, per `backend/app/tournament/purposes.py`) is
    expressed as `seed=<opening balance>` plus the ordinary recurring `contribution`/`annual_contribution`
    on top; a purpose with no recurring contribution at all (`TRADING`, lump-sum) is expressed as
    `seed=<the lump sum>, contribution=0.0` -- which funds once, at session zero, and never again,
    regardless of `cadence`, since a zero-amount deposit at every later contribution date adds nothing
    and is not recorded as a flow.

    **`cash_constrained`** (default `False`, so every existing caller and every round-15 number is
    reproduced exactly). The unconstrained default walks `symbols` in dict order and never checks that
    `cash` covers a buy before making it, so a buy can execute before the sell that funds it -- across
    the whole book the moves net out, but a real brokerage account cannot spend proceeds it has not yet
    received. With `cash_constrained=True`, a breach rebalance instead: (1) executes every sell first,
    in a fixed order (symbols sorted alphabetically, not dict-insertion order, so the result does not
    depend on `closes`'s key order), crediting `cash` before any buy is attempted; then (2) executes
    buys, also in sorted order, each capped at the cash actually on hand. An underfunded buy is
    **partially filled** -- filled for whatever `cash` allows, not skipped outright -- because that is
    the more faithful model of a real broker (a market order for $500 with $300 available buys $300 of
    stock, it does not refuse the whole order), and every family script comparing against
    `run_allocation`/`PaperBroker` should see the same partial-fill convention that engine uses. Each
    underfunded buy increments `result.underfunded_buys` once and adds its unfilled dollar amount to
    `result.underfunded_shortfall`, so the bias this models has a mechanism attached, not just a size.
    Contribution-directed pre-buying (`use_contributions_to_rebalance`) is unaffected either way: it
    already spends only `min(cash, need)`, so it was cash-safe before this parameter existed.
    Settlement lag (T+1/T+2) is deliberately not modelled by this parameter -- see
    `strategy-program/ROUND-16-PLAN.md` §3 for why.

    **`settlement_days`** (default `0`, which is a no-op, so every existing caller and every round-15
    and round-16 number reproduces exactly). This is round 16's own stated next step, in its words:
    *"give `contributions.simulate` a settlement lag, not just a cash cap, and re-run this
    comparison."*

    Round 16 built `cash_constrained` and measured it as worth **nothing** -- zero underfunded buys
    across all 31 cells -- and its follow-up explains why: the constraint it built was
    settlement-free by construction. It executes every sell before any buy and lets the proceeds fund
    the buys in the same session, so the cap could never bind. Meanwhile the real engine rejected
    **59** orders on the same card, all `insufficient_cash`, with fractional shares enabled and every
    friction zeroed. Both are true, and the only way they can both be true is that the engine's
    constraint is one a same-session cash cap cannot express.

    `app.paper.paperbroker` says what it is: sale proceeds land in `_unsettled` and become spendable
    only on `_add_business_days(trade_date, settlement_days)`; a buy checks `settled_cash`, not
    `cash`, because *"a cash account cannot rebuy with unsettled proceeds without triggering a
    good-faith violation"*. A band rebalance sells one sleeve to fund another -- exactly the trade
    that settlement blocks.

    With `settlement_days > 0`, a sale still credits `cash` (the money exists) but is recorded as
    unsettled until its settlement date, and **every buy -- the contribution pre-buy as well as the
    breach rebalance -- is capped at settled cash**. A deposit is settled on arrival; only proceeds
    wait. `settlement_days` therefore models the constraint the engine actually applies, where
    `cash_constrained` modelled a constraint no account has.

    The two are independent and compose: `cash_constrained` fixes the sells-before-buys ordering,
    `settlement_days` decides whether those sells' proceeds are yet spendable.
    """
    if contribution is not None:
        if annual_contribution != ANNUAL_CONTRIBUTION:
            raise ValueError(
                "pass either the legacy annual_contribution= or the contribution=/cadence= pair, "
                "not both -- mixing them is exactly the annual/monthly ambiguity this signature is "
                "built to make impossible"
            )
        period_contribution = contribution
    else:
        if cadence != "annual":
            raise ValueError(
                f"cadence={cadence!r} requires an explicit contribution= amount -- "
                "annual_contribution is the legacy, annual-only parameter and cannot drive a "
                "non-annual schedule"
            )
        period_contribution = annual_contribution
        cadence = "annual"

    symbols = list(closes)
    result = ContributionResult()
    contrib_at = set(contribution_dates(dates, cadence=cadence))

    holdings = dict.fromkeys(symbols, 0.0)  # dollars per sleeve
    cash = 0.0
    contributed = 0.0
    #: `(available_on, amount)` for sale proceeds not yet spendable, mirroring
    #: `app.paper.paperbroker.PaperBroker._unsettled`. Stays empty when `settlement_days == 0`.
    unsettled: list[tuple[dt.date, float]] = []

    for i, day in enumerate(dates):
        if i > 0:
            for s in symbols:
                holdings[s] *= closes[s][i] / closes[s][i - 1]

        if i in contrib_at:
            amount = period_contribution + (seed if i == 0 else 0.0)
            if amount:
                cash += amount
                contributed += amount
                result.flows.append(Cashflow(day, amount))

        equity = sum(holdings.values()) + cash
        targets = weight_fn(i, closes)
        total_target = sum(targets.values())
        if total_target > 1.0 + 1e-9:
            raise ValueError(f"weights sum to {total_target:.4f} > 1 at session {i} ({day})")

        desired = {s: targets.get(s, 0.0) * equity for s in symbols}
        drift = {s: desired[s] - holdings[s] for s in symbols}

        # Proceeds not yet spendable on this session, under `settlement_days`. Empty and therefore
        # free when settlement is off, which is what keeps the default path byte-identical.
        settled = cash - sum(amt for on, amt in unsettled if on > day)

        # Spend new cash on the underweight sleeves first: a buy funded by a deposit pays slippage
        # once, where a buy funded by a sale pays it twice.
        if use_contributions_to_rebalance and cash > 0:
            wanted = {s: d for s, d in drift.items() if d > 0}
            need = sum(wanted.values())
            if need > 0:
                # Capped at settled cash, not `cash`: a deposit is spendable on arrival, but proceeds
                # sitting in `unsettled` are not, and the pre-buy is a buy like any other.
                spend = min(settled, need)
                for s, d in wanted.items():
                    take = spend * (d / need)
                    holdings[s] += take
                    cash -= take
                    result.turnover += take
                    cost = take * slippage_bps / 10_000
                    holdings[s] -= cost
                    result.cost_paid += cost
                result.contribution_buys += 1
                settled -= spend
                drift = {s: desired[s] - holdings[s] for s in symbols}

        breach = any(abs(drift[s]) > band_pct * equity for s in symbols)
        if breach:
            if cash_constrained:
                # Sells before buys, in a fixed order that does not depend on dict-insertion order --
                # crediting every sale's cash before any buy is attempted, so a buy can never spend
                # proceeds this account has not yet received.
                cost_rate = slippage_bps / 10_000
                for s in sorted(s for s in symbols if drift[s] < -1e-9):
                    move = drift[s]  # negative
                    cost = abs(move) * cost_rate
                    holdings[s] += move
                    cash -= move + cost
                    proceeds = -move - cost
                    if settlement_days > 0 and proceeds > 0:
                        # The money exists; it is just not spendable yet. Recorded against the
                        # engine's own settlement date so the two cannot disagree.
                        unsettled.append((_settles_on(day, settlement_days), proceeds))
                    else:
                        settled += proceeds
                    result.turnover += abs(move)
                    result.cost_paid += cost
                for s in sorted(s for s in symbols if drift[s] > 1e-9):
                    move = drift[s]  # positive, the full desired buy
                    # Cap the buy at what `cash` actually covers, principal plus its own slippage:
                    # fill*(1 + cost_rate) <= cash. A buy that cannot be fully funded is partially
                    # filled -- the more faithful model of a real broker -- rather than skipped
                    # outright.
                    affordable = max(settled / (1 + cost_rate), 0.0)
                    fill = min(move, affordable)
                    shortfall = move - fill
                    if shortfall > 1e-9:
                        result.underfunded_buys += 1
                        result.underfunded_shortfall += shortfall
                    if fill < 1e-9:
                        continue
                    cost = fill * cost_rate
                    holdings[s] += fill
                    cash -= fill + cost
                    settled -= fill + cost
                    result.turnover += fill
                    result.cost_paid += cost
            else:
                for s in symbols:
                    move = desired[s] - holdings[s]
                    if abs(move) < 1e-9:
                        continue
                    cost = abs(move) * slippage_bps / 10_000
                    holdings[s] += move
                    cash -= move + cost
                    result.turnover += abs(move)
                    result.cost_paid += cost
            result.rebalances += 1

        result.dates.append(day)
        result.equity.append(sum(holdings.values()) + cash)
        result.contributed.append(contributed)
        result.weights.append({s: (holdings[s] / equity if equity else 0.0) for s in symbols})
        result.cash.append(cash)

    return result


def summarise(name: str, r: ContributionResult) -> str:
    irr = "n/a" if r.irr is None else f"{r.irr * 100:>6.2f}%"
    return (
        f"{name:32} ${r.final_balance:>11,.0f}  ${r.total_contributed:>9,.0f}  {r.multiple:>5.2f}x  "
        f"{irr}  {r.time_weighted_cagr * 100:>6.2f}%  {r.max_drawdown * 100:>7.1f}%  {r.mar:>5.2f}  "
        f"{r.rebalances:>4d}"
    )


HEADER = (
    f"{'':32} {'balance':>12}  {'paid in':>10}  {'mult':>6}  {'IRR':>7}  {'TWR':>7}  "
    f"{'maxDD':>7}  {'MAR':>5}  {'rebal':>4}"
)
