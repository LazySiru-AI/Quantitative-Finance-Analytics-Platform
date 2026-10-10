"""Assembles :class:`~app.thesis.models.StrategyCard`: the deliverable of the thesis loop.

This module computes nothing that a Phase 6/7 engine already computes. Where a number already exists
on the :class:`~app.thesis.models.Evidence` the loop measured, or on the
:class:`~app.backtest.models.StrategyResult` a backtest produced, this module transcribes it -- the
same discipline :mod:`app.report.builder` follows for the per-holding report, and for the identical
reason: a card that recomputed a statistic would be a second implementation of it, and two
implementations agreeing today is not a property either can promise tomorrow.

Four things here are genuinely new arithmetic, because no existing engine produces them, and each is
kept to the smallest computation that will do:

* **Regime slices** re-run the *same* statistical primitives :func:`app.thesis.loop.evaluate_thesis`
  calls (:func:`~app.backtest.forward.forward_returns`, :func:`~app.backtest.forward.hit_rate`,
  :func:`~app.backtest.forward.describe`, :func:`~app.backtest.forward.independent_count`,
  :func:`~app.backtest.scan.binomial_p_value`) with an extra boolean mask applied *after* the signal
  and forward-return arrays are computed over the full, contiguous bar history. Masking the *bars*
  themselves first -- filtering to only the high-volatility rows, say -- would corrupt every rolling
  indicator in the entry rule (a moving average needs its preceding bars, regime label or not) and
  would silently redefine "20-bar horizon" as "20 rows of a discontiguous subset" rather than 20
  trading bars. So the mask is applied last, exactly where :func:`app.thesis.loop.evaluate_thesis`
  applies its own ``evaluable`` mask -- this is that same step, parameterised.

* **The baseline distribution** (:attr:`~app.thesis.models.StrategyCard.baseline_return`) is a genuine
  gap in :class:`~app.thesis.models.Evidence`: the model carries ``baseline_hit_rate`` and
  ``baseline_median_return`` but no full :class:`~app.backtest.models.Distribution` for the
  unconditional sample, and ``models.py`` is not a file this package may edit. It is recovered the
  same way -- :func:`~app.backtest.forward.forward_returns` then
  :func:`~app.backtest.forward.describe` over the evaluable (not triggered) mask -- which is exactly
  what produced ``baseline_median_return`` in the first place, just without throwing the rest of the
  distribution away.

* **Holding-period, worst-trade and in-position-drawdown statistics** are descriptive summaries of a
  :class:`~app.backtest.models.StrategyResult`'s own ``trades`` and ``equity_curve`` -- percentiles and
  a minimum, not a significance test -- computed once here because no existing model field carries
  them.

* **Tax impact** replays the strategy's own closed trades through the real Phase 3 engines
  (:mod:`app.tax.washsale`, :mod:`app.tax.gains`) against a synthetic single-account ledger built for
  this purpose alone. See :func:`build_tax_impact` for exactly what that does and does not model, and
  the top-level report for what was wired up versus assumed.

**Every card is produced.** :func:`build_card` takes no branch on ``record.verdict`` other than to
copy it: a rejected or inconclusive thesis gets the same figures a survivor does, which is the entire
point of :class:`~app.thesis.models.StrategyCard`'s own docstring.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Protocol

import numpy as np
import pandas as pd

from app.backtest.forward import describe as describe_returns
from app.backtest.forward import forward_returns, hit_rate, independent_count
from app.backtest.models import BARS_PER_YEAR, Distribution, EquityPoint, StrategyResult, Trade
from app.backtest.scan import binomial_p_value
from app.config import Settings, get_settings
from app.core.lots import Disposal, LotLedger
from app.core.models import Account, AccountType, Broker, Lot, LotStatus, TaxTreatment
from app.db.duck import Interval
from app.market.models import MarketWarning
from app.report.models import Fact, FactBundle, FactKind
from app.rules.models import Entry
from app.rules.nodes import BoolExpr
from app.tax.gains import realized_gains
from app.tax.washsale import apply_wash_sales
from app.thesis import instruments, preregister
from app.thesis.models import (
    Evidence,
    HoldoutState,
    LedgerStats,
    RegimeSlice,
    StrategyCard,
    TaxImpact,
    TaxRateBasis,
    Thesis,
    ThesisRecord,
    Verdict,
)

__all__ = [
    "LONG_TERM_TAX_RATE",
    "SHORT_TERM_TAX_RATE",
    "TREND_WINDOW_BARS",
    "VOLATILITY_WINDOW_BARS",
    "Evaluator",
    "Grammar",
    "build_card",
    "build_tax_impact",
]


# ---------------------------------------------------------------------------------------------
# Injectable collaborators -- the identical seam app.thesis.loop and app.backtest.strategy use.
# ---------------------------------------------------------------------------------------------


class Grammar(Protocol):
    """The subset of `app.rules.grammar` this module calls."""

    def parse(self, expression: str) -> BoolExpr: ...


class Evaluator(Protocol):
    """The subset of `app.rules.evaluate` this module calls."""

    def evaluate(self, node: BoolExpr, bars: pd.DataFrame, *, interval: Interval) -> pd.Series: ...


def _default_grammar() -> Grammar:
    from app.rules import grammar

    return grammar


def _default_evaluator() -> Evaluator:
    from app.rules import evaluate

    return evaluate


# ---------------------------------------------------------------------------------------------
# Regime definitions
# ---------------------------------------------------------------------------------------------
#
# Both splits are defined from price and return history alone, computed before the entry rule is
# ever evaluated against them, and use fixed windows declared as module constants rather than
# anything derived from this thesis or this ticker's results. That is what keeps the definition from
# being tunable after the fact: the same 20-bar volatility window and 200-bar trend window apply to
# every symbol and every thesis this module ever cards, so there is no dial available to turn until a
# regime split happens to favour the effect under test.
#
# **High/low volatility**: rolling `VOLATILITY_WINDOW_BARS`-bar realised volatility (sample stdev of
# close-to-close returns), split at its own median across the whole series. The median is a property
# of this instrument's own history, not a threshold chosen to make one half interesting.
#
# **Uptrend/downtrend**: close above or below its own trailing `TREND_WINDOW_BARS`-bar simple moving
# average -- the conventional 200-day-average trend filter.
#
# A bar before either lookback window has filled is excluded from *both* of that window's labels
# (neither True), matching the warmup-is-not-false convention `app.backtest.events` and
# `app.thesis.loop` apply throughout: an indicator with no value yet is not evidence of anything.

TREND_WINDOW_BARS: int = 200
VOLATILITY_WINDOW_BARS: int = 20

_REGIME_PAIRS: tuple[tuple[str, str], ...] = (
    ("high_volatility", "low_volatility"),
    ("uptrend", "downtrend"),
)


def _regime_masks(bars: pd.DataFrame) -> dict[str, np.ndarray]:
    """One boolean mask per regime label, aligned with ``bars``. See the section docstring above for
    the exact definitions and why they cannot be tuned after seeing a thesis's results."""
    n = len(bars)
    closes = bars["close"].to_numpy(dtype=float) if n else np.array([], dtype=float)

    returns = np.full(n, np.nan, dtype=float)
    if n > 1:
        returns[1:] = closes[1:] / closes[:-1] - 1.0
    vol = (
        pd.Series(returns)
        .rolling(VOLATILITY_WINDOW_BARS, min_periods=VOLATILITY_WINDOW_BARS)
        .std(ddof=1)
        .to_numpy()
    )
    finite_vol = vol[~np.isnan(vol)]
    vol_median = float(np.median(finite_vol)) if finite_vol.size else np.nan
    has_vol = ~np.isnan(vol)
    high_vol = has_vol & (vol > vol_median)
    low_vol = has_vol & (vol <= vol_median)

    sma = (
        pd.Series(closes)
        .rolling(TREND_WINDOW_BARS, min_periods=TREND_WINDOW_BARS)
        .mean()
        .to_numpy()
    )
    has_sma = ~np.isnan(sma)
    uptrend = has_sma & (closes > sma)
    downtrend = has_sma & (closes <= sma)

    return {
        "high_volatility": high_vol,
        "low_volatility": low_vol,
        "uptrend": uptrend,
        "downtrend": downtrend,
    }


def _evidence_for_mask(
    thesis: Thesis,
    bars: pd.DataFrame,
    mask: np.ndarray,
    *,
    grammar: Grammar,
    evaluator: Evaluator,
) -> Evidence:
    """:func:`app.thesis.loop.evaluate_thesis`'s body, parameterised by an extra ``mask`` applied to
    the ``evaluable`` set after the signal and forward returns are computed on the full, contiguous
    ``bars`` -- see the module docstring for why the mask cannot be applied any earlier. Every
    statistic below is produced by the identical function `evaluate_thesis` calls; nothing here is a
    new implementation of hit rate, hpercentiles or the binomial test."""
    if bars.empty or not mask.any():
        return Evidence(horizon=thesis.horizon)

    node = grammar.parse(thesis.entry)
    signal = evaluator.evaluate(node, bars, interval=thesis.interval)

    returns = forward_returns(bars, horizon=thesis.horizon, entry=Entry.NEXT_OPEN)
    known = signal.notna().to_numpy(dtype=bool)
    fired = signal.fillna(False).to_numpy(dtype=bool)

    evaluable = known & ~np.isnan(returns) & mask
    triggered = evaluable & fired

    trigger_returns = returns[triggered]
    baseline_returns = returns[evaluable]
    positions = np.flatnonzero(triggered)
    independent = independent_count(positions, thesis.horizon)

    rate = hit_rate(trigger_returns)
    baseline = hit_rate(baseline_returns)

    p_value: float | None = None
    if rate is not None and baseline is not None and independent > 0:
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


def _build_regimes(
    thesis: Thesis, bars: pd.DataFrame, *, grammar: Grammar, evaluator: Evaluator
) -> list[RegimeSlice]:
    masks = _regime_masks(bars)
    slices: list[RegimeSlice] = []
    for label, mask in masks.items():
        evidence = _evidence_for_mask(thesis, bars, mask, grammar=grammar, evaluator=evaluator)
        slices.append(RegimeSlice(label=label, bars=int(mask.sum()), evidence=evidence))
    return slices


#: Minimum edge magnitude (in hit-rate points) worth comparing across a regime pair at all. Below
#: this, both sides are close enough to zero that calling either "the edge" would overstate a
#: difference that is mostly noise -- the pair is simply not flagged.
_MEANINGFUL_EDGE: float = 0.05

#: How much smaller the weaker side's edge must be than the stronger side's, as a fraction, before
#: the pair counts as lopsided. One half: the weaker side has to be at most half the stronger side's
#: magnitude, not merely somewhat smaller, before this module calls the difference "conditional"
#: rather than "the same effect, measured with more noise on one side."
_LOPSIDED_RATIO: float = 0.5


def _conditional_edge_warning(regimes: list[RegimeSlice]) -> MarketWarning | None:
    """Flags the card when the measured edge is not comparable on both sides of a regime pair -- one
    side has it and the other does not, the signs disagree, or one side's magnitude is less than half
    the other's while the stronger side clears :data:`_MEANINGFUL_EDGE`. An edge present only in one
    market condition is conditional, and a card that does not say so promises in a calm market what it
    measured in a volatile one (or vice versa).

    This is a descriptive screen over the already-computed regime evidence, not a second significance
    test: it looks only at the sign and relative magnitude of :attr:`~app.thesis.models.Evidence.edge`
    on each side, the same way :class:`~app.backtest.models.IndicatorProfile` is descriptive rather
    than confirmatory. The regime slices themselves carry the p-values and independent sample sizes a
    reader would need to judge whether either side is itself trustworthy.
    """
    by_label = {r.label: r for r in regimes}
    flagged: list[str] = []
    for left, right in _REGIME_PAIRS:
        left_slice, right_slice = by_label.get(left), by_label.get(right)
        if left_slice is None or right_slice is None:
            continue
        left_edge = left_slice.evidence.edge if left_slice.evidence is not None else None
        right_edge = right_slice.evidence.edge if right_slice.evidence is not None else None
        if left_edge is None and right_edge is None:
            continue

        one_sided = (left_edge is None) != (right_edge is None)
        opposite_signs = False
        lopsided = False
        if left_edge is not None and right_edge is not None:
            opposite_signs = left_edge * right_edge < 0
            bigger, smaller = sorted((abs(left_edge), abs(right_edge)), reverse=True)
            lopsided = bigger >= _MEANINGFUL_EDGE and smaller < bigger * _LOPSIDED_RATIO

        if one_sided or opposite_signs or lopsided:
            flagged.append(f"{left}/{right}")
    if not flagged:
        return None
    return MarketWarning(
        kind="conditional_edge",
        message=(
            "The measured edge is not consistent across both sides of at least one regime split "
            f"({', '.join(flagged)}): this is a conditional edge, present in some market conditions "
            "and not others, not an unconditional one. See the regime slices for the numbers behind "
            "each side."
        ),
    )


def _baseline_distribution(
    thesis: Thesis, bars: pd.DataFrame, *, grammar: Grammar, evaluator: Evaluator
) -> Distribution:
    """The instrument's unconditional forward-return distribution over ``bars`` -- what
    :func:`app.thesis.loop.evaluate_thesis` measures to produce ``baseline_median_return``, without
    discarding the rest of the distribution the way that function does. See the module docstring."""
    if bars.empty:
        return Distribution()
    node = grammar.parse(thesis.entry)
    signal = evaluator.evaluate(node, bars, interval=thesis.interval)
    returns = forward_returns(bars, horizon=thesis.horizon, entry=Entry.NEXT_OPEN)
    known = signal.notna().to_numpy(dtype=bool)
    evaluable = known & ~np.isnan(returns)
    return describe_returns(returns[evaluable])


# ---------------------------------------------------------------------------------------------
# Trading frequency
# ---------------------------------------------------------------------------------------------


def _triggers_per_year(
    bars: pd.DataFrame,
    interval: Interval,
    evidence: Evidence,
    holdout_evidence: Evidence | None,
) -> float | None:
    """Trigger count (in-sample plus holdout, when both exist) divided by years of history in
    ``bars``. Uses :attr:`~app.thesis.models.Evidence.sample_size` -- every evaluable trigger, not the
    independence-adjusted count -- because "how often can I actually act on this" is a question about
    raw occurrence, not about how many of those occurrences count as separate statistical evidence.
    """
    n = len(bars)
    if n == 0:
        return None
    years = n / BARS_PER_YEAR[interval]
    if years <= 0:
        return None
    total = evidence.sample_size + (holdout_evidence.sample_size if holdout_evidence else 0)
    return total / years


# ---------------------------------------------------------------------------------------------
# Trade-level descriptive statistics
# ---------------------------------------------------------------------------------------------


def _closed_trades(strategy_result: StrategyResult | None) -> list[Trade]:
    if strategy_result is None:
        return []
    return [t for t in strategy_result.trades if not t.open_at_end]


def _holding_period_stats(trades: list[Trade]) -> tuple[float | None, tuple[float, float] | None]:
    """Median and (p25, p75) of ``bars_held`` over closed trades. Measured directly from the
    backtest's own trade sequence, never assumed from ``max_holding_bars`` or any other spec field."""
    if not trades:
        return None, None
    holds = np.array([t.bars_held for t in trades], dtype=float)
    median = float(np.median(holds))
    p25, p75 = (float(v) for v in np.percentile(holds, [25, 75]))
    return median, (p25, p75)


def _worst_trade(trades: list[Trade]) -> float | None:
    if not trades:
        return None
    return min(t.return_pct for t in trades)


def _max_drawdown_in_position(equity_curve: list[EquityPoint]) -> float | None:
    """The deepest peak-to-trough decline experienced *while a position was open*, as distinct from
    :attr:`~app.backtest.models.StrategyMetrics.max_drawdown`, which is measured on the whole equity
    curve and can be dominated by a decline that happened while flat between trades (impossible for a
    long-only, no-pyramiding spec, but the two numbers still answer different questions once a
    strategy sits out long stretches).

    The running peak resets at the start of every contiguous in-position run rather than carrying over
    from a peak achieved on an earlier trade: what matters here is what a position holder actually
    experienced from their own entry, not a peak the equity curve happened to touch while flat.
    """
    if not equity_curve:
        return None
    worst: float | None = None
    running_peak: float | None = None
    was_in_position = False
    for point in equity_curve:
        if point.in_position:
            if not was_in_position or running_peak is None:
                running_peak = point.equity
            else:
                running_peak = max(running_peak, point.equity)
            drawdown = point.equity / running_peak - 1.0
            if worst is None or drawdown < worst:
                worst = drawdown
        was_in_position = point.in_position
    return worst


# ---------------------------------------------------------------------------------------------
# Tax impact
# ---------------------------------------------------------------------------------------------
#
# What this wires up: the strategy's own closed trades are replayed as a synthetic, single-account,
# one-share-per-trade LotLedger -- entry becomes a one-share buy lot, exit becomes the disposal that
# closes it -- and run through the *real* Phase 3 engines: `app.tax.washsale.apply_wash_sales` for
# IRC §1091 (this is what makes "the rule triggers its own wash sales" a computed fact rather than a
# claim), then `app.tax.gains.realized_gains` for the short/long split under the actual calendar-
# anniversary rule in `app.tax.gains.classify_term`. Neither statistic is reimplemented here.
#
# What this does not, and cannot, wire up:
#
# * **A filing-grade personal tax rate, unless the user supplies one.** `app.config.Settings` carries
#   two optional fields, `ordinary_income_tax_rate` and `long_term_capital_gains_tax_rate`, and
#   `build_tax_impact` below uses them when set. Both default to `None`: nothing forces a real person
#   to disclose their tax bracket to run a backtest, and a wrong guess at it would be worse than an
#   honest fallback. When either is unset, this function falls back to `SHORT_TERM_TAX_RATE` /
#   `LONG_TERM_TAX_RATE` below -- the top federal statutory brackets (ordinary income and long-term
#   capital gains) -- used only to turn a wash-sale-adjusted dollar gain into a *directional*
#   after-tax drag: an upper bound on the tax cost for most filers, not this user's actual rate.
#   Which basis produced the number, and the two rates actually multiplied, travel with the figure on
#   `TaxImpact.rate_basis` / `short_term_rate_applied` / `long_term_rate_applied`, so
#   `TaxImpact.after_tax_return` can never be rendered as a filing-grade number the way
#   `app.tax.engine.build_tax_report` is by a UI that only sees the float.
# * **`ira_exposure`.** This ledger is synthetic and single-account by construction -- it has no
#   knowledge of the user's real accounts under `data/`, which this package is forbidden to read.
#   `TaxImpact.ira_exposure` is tri-state (`bool | None`) for exactly this reason and is always
#   `None` -- unknown, not checked -- here: `False` would be a positive claim of no IRA exposure this
#   module has no basis for. A real cross-account check, and the only code path allowed to set this
#   field to `True` or `False`, belongs to whatever assembles the card from the actual portfolio
#   ledger, not to a hypothetical backtest replay.
# * **A fully compounded after-tax equity curve.** The wash-sale and gains engines operate on dollar
#   lots, not on the strategy's unitless compounding equity curve, so the tax drag below is expressed
#   as a fraction of total capital deployed (the sum of each trade's entry price, one share each) and
#   subtracted from `StrategyMetrics.total_return` -- an approximation for typical trade sizing, not a
#   second, dollar-accurate backtest.

SHORT_TERM_TAX_RATE: float = 0.37
"""Top federal ordinary-income bracket. The fallback `build_tax_impact` uses when
`Settings.ordinary_income_tax_rate` is unset -- see the section docstring: a directional
assumption, not this user's actual rate."""

LONG_TERM_TAX_RATE: float = 0.20
"""Top federal long-term capital-gains bracket. The fallback `build_tax_impact` uses when
`Settings.long_term_capital_gains_tax_rate` is unset. Same caveat as :data:`SHORT_TERM_TAX_RATE`."""


def _sync_wash_sale_adjustments(ledger: LotLedger) -> None:
    """Re-read each lot's (possibly wash-sale-adjusted) basis and holding start back onto its
    disposal.

    Mirrors `app.tax.engine._sync_disposals`'s essential step -- duplicated rather than imported
    because that function is private to a module this package may not edit, and because the two lines
    that matter are simple enough to state directly. `apply_wash_sales` mutates the *lot*, not the
    disposal snapshot taken when the disposal was built; skipping this is the exact bug that module's
    docstring names: a chained wash sale's gain comes out overstated and its holding period
    misclassified, because `app.tax.gains.classify_term` reads the disposal, not the lot.
    """
    lots = ledger.lots_by_id()
    for disposal in ledger.disposals:
        lot = lots.get(disposal.lot_id)
        if lot is None:
            continue
        disposal.holding_start = lot.effective_holding_start
        if lot.wash_sale_adjustment != 0:
            disposal.cost_basis = lot.basis_per_share * disposal.quantity


def build_tax_impact(
    symbol: str,
    strategy_result: StrategyResult | None,
    *,
    settings: Settings | None = None,
) -> TaxImpact:
    """What the strategy's own trade sequence would have cost in tax. See the section docstring above
    for exactly what is and is not modelled.

    Args:
        symbol: The instrument the synthetic ledger is built against.
        strategy_result: The backtest whose closed trades are replayed. ``None`` and "no closed
            trades" both return an explanatory ``unavailable_reason``, never fabricated zeros.
        settings: Where the user's own marginal rates are read from, when configured -- defaults to
            :func:`app.config.get_settings`. Injectable the same way every other leaf function in
            this codebase takes its `Settings` (see `app.thesis.ledger.ledger_path`), so a test can
            pin a configured rate without touching the process-wide singleton or `.env`.

    Returns a :class:`~app.thesis.models.TaxImpact` with ``unavailable_reason`` set, never fabricated
    zeros, when there is no backtest or no closed trade to replay.
    """
    if strategy_result is None:
        return TaxImpact(
            unavailable_reason="no backtest was run for this thesis; strategy_result was not supplied"
        )

    closed = _closed_trades(strategy_result)
    if not closed:
        return TaxImpact(
            unavailable_reason="the strategy produced no closed trades over this window"
        )

    account_id = "synthetic-strategy-ledger"
    upper = symbol.upper()
    account = Account(
        account_id=account_id,
        broker=Broker.ROBINHOOD,
        label="Synthetic strategy ledger (hypothetical trade sequence, not a real account)",
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=AccountType.CASH,
    )
    accounts = {account_id: account}

    lots: list[Lot] = []
    disposals: list[Disposal] = []
    total_basis = Decimal(0)
    for index, trade in enumerate(closed):
        entry_price = Decimal(str(trade.entry_price))
        exit_price = Decimal(str(trade.exit_price))
        total_basis += entry_price
        lot = Lot(
            lot_id=f"synthetic-lot-{index}",
            instrument_id=upper,
            account_id=account_id,
            acquired_date=trade.entry_date,
            acquired_txn_id=f"synthetic-buy-{index}",
            quantity=Decimal(1),
            remaining=Decimal(0),
            cost_basis=entry_price,
            status=LotStatus.CLOSED,
            closed_date=trade.exit_date,
        )
        lots.append(lot)
        disposals.append(
            Disposal(
                disposal_id=f"synthetic-disposal-{index}",
                lot_id=lot.lot_id,
                instrument_id=upper,
                account_id=account_id,
                symbol=upper,
                sell_txn_id=f"synthetic-sell-{index}",
                acquired_date=trade.entry_date,
                holding_start=trade.entry_date,
                disposed_date=trade.exit_date,
                quantity=Decimal(1),
                proceeds=exit_price,
                cost_basis=entry_price,
                fees=Decimal(0),
            )
        )

    ledger = LotLedger(lots=lots, disposals=disposals, warnings=[], symbols={upper: upper})
    wash_result = apply_wash_sales(ledger, accounts=accounts)
    _sync_wash_sale_adjustments(ledger)

    start = min(t.entry_date for t in closed)
    end = max(t.exit_date for t in closed)
    gains = realized_gains(ledger, accounts=accounts, start=start, end=end)

    if total_basis <= 0:
        return TaxImpact(
            unavailable_reason=(
                "every trade's entry price was zero or negative; no basis to compute a tax impact "
                "against"
            )
        )

    basis = float(total_basis)
    short_term_gains = float(gains.short_term_gain) / basis
    long_term_gains = float(gains.long_term_gain) / basis
    disallowed_loss = float(gains.disallowed_loss_total) / basis

    cfg = settings or get_settings()
    short_term_rate = cfg.ordinary_income_tax_rate
    long_term_rate = cfg.long_term_capital_gains_tax_rate
    rate_basis = (
        TaxRateBasis.USER_CONFIGURED
        if short_term_rate is not None and long_term_rate is not None
        else TaxRateBasis.STATUTORY_UPPER_BOUND
    )
    if short_term_rate is None:
        short_term_rate = SHORT_TERM_TAX_RATE
    if long_term_rate is None:
        long_term_rate = LONG_TERM_TAX_RATE

    tax_owed = (
        max(gains.short_term_gain, Decimal(0)) * Decimal(str(short_term_rate))
        + max(gains.long_term_gain, Decimal(0)) * Decimal(str(long_term_rate))
    )
    after_tax_drag = float(tax_owed) / basis

    gross_return = strategy_result.metrics.total_return
    after_tax_return = gross_return - after_tax_drag if gross_return is not None else None

    return TaxImpact(
        gross_return=gross_return,
        after_tax_return=after_tax_return,
        short_term_gains=short_term_gains,
        long_term_gains=long_term_gains,
        wash_sales_triggered=len(wash_result.events),
        disallowed_loss=disallowed_loss,
        rate_basis=rate_basis,
        short_term_rate_applied=short_term_rate,
        long_term_rate_applied=long_term_rate,
        ira_exposure=None,
        unavailable_reason=None,
    )


# ---------------------------------------------------------------------------------------------
# Unlevered comparison
# ---------------------------------------------------------------------------------------------


def _unlevered_comparison(
    symbol: str,
    thesis: Thesis,
    verdict: Verdict,
    *,
    unlevered_bars: pd.DataFrame | None,
    grammar: Grammar,
    evaluator: Evaluator,
    generated_at: dt.datetime,
) -> tuple[StrategyCard | None, list[MarketWarning]]:
    """The nested unlevered card, or ``None`` plus the warning explaining why not.

    Three outcomes, matching `app.thesis.instruments`'s own three-way split:

    * Not a leveraged product at all -- no card, no warning.
    * Leveraged with no mapped equivalent (`entry.underlying is None`) -- no card, and the warning
      carries `instruments.describe`.
    * Leveraged with an equivalent, but the caller did not supply bars for it -- no card, and a
      warning naming the gap (distinct from the "no equivalent" case, which is a data limitation
      versus a caller-supplied-nothing limitation).
    * Leveraged with an equivalent and bars supplied -- a nested card, built by evaluating the
      *identical* thesis (same rules, horizon, direction) against the underlying's bars, with its own
      `unlevered_comparison` forced to `None` so the recursion is exactly one level deep.

    The nested card is not a new registered trial: no `ThesisRecord` exists for the underlying under
    this thesis, no holdout was claimed for it, and its evidence is a single pass over whatever bars
    were supplied rather than a pre-registered in-sample/holdout split. Its `verdict` is inherited
    from the parent's own verdict (the parent record's screen/confirm decision) because comparing the
    same rules on the underlying is descriptive, not a second confirmatory test.
    """
    entry = instruments.lookup(symbol)
    if entry is None:
        return None, []

    if entry.underlying is None:
        return None, [
            MarketWarning(kind="leveraged_no_equivalent", message=instruments.describe(symbol) or "")
        ]

    if unlevered_bars is None or unlevered_bars.empty:
        return None, [
            MarketWarning(
                kind="unlevered_bars_missing",
                message=(
                    f"{symbol}: {instruments.describe(symbol)} No bars for {entry.underlying} were "
                    "supplied to build the comparison."
                ),
            )
        ]

    nested_thesis = thesis.model_copy(update={"symbol": entry.underlying})
    nested_evidence = _evidence_for_mask(
        nested_thesis,
        unlevered_bars,
        np.ones(len(unlevered_bars), dtype=bool),
        grammar=grammar,
        evaluator=evaluator,
    )
    baseline = _baseline_distribution(nested_thesis, unlevered_bars, grammar=grammar, evaluator=evaluator)
    triggers = _triggers_per_year(unlevered_bars, thesis.interval, nested_evidence, None)

    nested_card = StrategyCard(
        symbol=entry.underlying,
        interval=thesis.interval,
        generated_at=generated_at,
        thesis=nested_thesis,
        thesis_hash=preregister.content_hash(nested_thesis),
        verdict=verdict,
        entry_rule=nested_thesis.entry,
        exit_rule=nested_thesis.exit,
        triggers_per_year=triggers,
        holding_period_median=None,
        holding_period_iqr=None,
        expected_return=nested_evidence.distribution,
        baseline_return=baseline,
        worst_trade=None,
        max_drawdown_in_position=None,
        in_sample=nested_evidence,
        holdout=None,
        holdout_state=None,
        ledger=None,
        regimes=[],
        tax=TaxImpact(
            unavailable_reason=(
                "no backtest was run for the unlevered comparison; only entry-rule evidence is "
                "available"
            )
        ),
        unlevered_comparison=None,
        hourly_substudy=None,
        strategy_result=None,
        bundle=None,
        warnings=[],
    )
    return nested_card, []


# ---------------------------------------------------------------------------------------------
# Fact bundle
# ---------------------------------------------------------------------------------------------


def _fact(
    fact_id: str,
    label: str,
    value: float | str | int | None,
    kind: FactKind,
    source: str,
) -> Fact:
    resolved: float | str | None = float(value) if isinstance(value, int) else value
    return Fact(id=fact_id, label=label, value=resolved, kind=kind, source=source)


def _distribution_facts(prefix: str, label_prefix: str, dist: Distribution, source: str) -> list[Fact]:
    return [
        _fact(f"{prefix}.count", f"{label_prefix} sample size", dist.count, FactKind.COUNT, source),
        _fact(f"{prefix}.median", f"{label_prefix} median", dist.median, FactKind.SIGNED_PERCENT, source),
        _fact(f"{prefix}.p05", f"{label_prefix} 5th percentile", dist.p05, FactKind.SIGNED_PERCENT, source),
        _fact(f"{prefix}.p25", f"{label_prefix} 25th percentile", dist.p25, FactKind.SIGNED_PERCENT, source),
        _fact(f"{prefix}.p75", f"{label_prefix} 75th percentile", dist.p75, FactKind.SIGNED_PERCENT, source),
        _fact(f"{prefix}.p95", f"{label_prefix} 95th percentile", dist.p95, FactKind.SIGNED_PERCENT, source),
        _fact(f"{prefix}.minimum", f"{label_prefix} minimum", dist.minimum, FactKind.SIGNED_PERCENT, source),
        _fact(f"{prefix}.maximum", f"{label_prefix} maximum", dist.maximum, FactKind.SIGNED_PERCENT, source),
    ]


def _evidence_facts(prefix: str, label_prefix: str, evidence: Evidence, source: str) -> list[Fact]:
    return [
        _fact(f"{prefix}.hit_rate", f"{label_prefix} hit rate", evidence.hit_rate, FactKind.PERCENT, source),
        _fact(
            f"{prefix}.baseline_hit_rate",
            f"{label_prefix} baseline hit rate",
            evidence.baseline_hit_rate,
            FactKind.PERCENT,
            source,
        ),
        _fact(f"{prefix}.edge", f"{label_prefix} edge", evidence.edge, FactKind.SIGNED_PERCENT, source),
        _fact(f"{prefix}.p_value", f"{label_prefix} p-value", evidence.p_value, FactKind.RATIO, source),
        _fact(f"{prefix}.q_value", f"{label_prefix} q-value", evidence.q_value, FactKind.RATIO, source),
        _fact(
            f"{prefix}.independent_n",
            f"{label_prefix} independent observations",
            evidence.independent_sample_size,
            FactKind.COUNT,
            source,
        ),
        _fact(f"{prefix}.sample_size", f"{label_prefix} triggers", evidence.sample_size, FactKind.COUNT, source),
    ]


def _build_bundle(
    *,
    card: StrategyCard,
    ledger_stats: LedgerStats | None,
    window: str,
) -> FactBundle:
    """Every figure the card's debate (and any narrative built on top of it) may cite, under the
    Phase 8 citation contract: one :class:`~app.report.models.Fact` per figure, each with a ``source``
    naming the engine and window it came from, exactly as :func:`app.report.builder.build_bundle`
    does for the per-holding report."""
    loop_source = f"app.thesis.loop.evaluate_thesis/in_sample/{window}"
    holdout_source = f"app.thesis.loop.evaluate_thesis/holdout/{window}"
    baseline_source = f"app.backtest.forward/baseline/{window}"
    strategy_source = f"app.backtest.strategy.backtest/{window}"
    regime_source = f"app.thesis.strategycard._evidence_for_mask/{window}"
    tax_source = f"app.tax.washsale+app.tax.gains/synthetic_ledger/{card.symbol}"
    ledger_source = f"app.thesis.ledger.stats_for/{card.symbol}"
    instrument_source = f"app.thesis.instruments/{card.symbol}"

    facts: list[Fact] = [
        _fact("thesis.symbol", "Symbol", card.symbol, FactKind.TEXT, f"thesis/{window}"),
        _fact("thesis.hypothesis", "Hypothesis", card.thesis.hypothesis, FactKind.TEXT, f"thesis/{window}"),
        _fact("thesis.entry", "Entry rule", card.entry_rule, FactKind.TEXT, f"thesis/{window}"),
        _fact("thesis.horizon", "Horizon (bars)", card.thesis.horizon, FactKind.COUNT, f"thesis/{window}"),
        _fact("thesis.direction", "Predicted direction", card.thesis.direction.value, FactKind.TEXT, f"thesis/{window}"),
        _fact("thesis.falsifies_if", "Falsification criterion", card.thesis.falsifies_if, FactKind.TEXT, f"thesis/{window}"),
        _fact("thesis.verdict", "Verdict", card.verdict.value, FactKind.TEXT, f"thesis/{window}"),
    ]
    if card.exit_rule is not None:
        facts.append(_fact("thesis.exit", "Exit rule", card.exit_rule, FactKind.TEXT, f"thesis/{window}"))

    if card.in_sample is not None:
        facts += _evidence_facts("evidence", "In-sample", card.in_sample, loop_source)
    if card.holdout is not None:
        facts += _evidence_facts("holdout", "Holdout", card.holdout, holdout_source)

    facts += _distribution_facts("expected_return", "Expected return", card.expected_return, loop_source)
    facts += _distribution_facts("baseline_return", "Baseline return", card.baseline_return, baseline_source)

    facts.append(
        _fact("triggers_per_year", "Triggers per year", card.triggers_per_year, FactKind.RATIO, loop_source)
    )
    facts.append(
        _fact(
            "holding_period.median",
            "Median holding period (bars)",
            card.holding_period_median,
            FactKind.COUNT,
            strategy_source,
        )
    )
    if card.holding_period_iqr is not None:
        facts.append(
            _fact(
                "holding_period.p25",
                "Holding period 25th percentile (bars)",
                card.holding_period_iqr[0],
                FactKind.COUNT,
                strategy_source,
            )
        )
        facts.append(
            _fact(
                "holding_period.p75",
                "Holding period 75th percentile (bars)",
                card.holding_period_iqr[1],
                FactKind.COUNT,
                strategy_source,
            )
        )
    facts.append(_fact("worst_trade", "Worst trade", card.worst_trade, FactKind.SIGNED_PERCENT, strategy_source))
    facts.append(
        _fact(
            "max_drawdown_in_position",
            "Max drawdown while in position",
            card.max_drawdown_in_position,
            FactKind.PERCENT,
            strategy_source,
        )
    )

    for regime in card.regimes:
        if regime.evidence is None:
            continue
        prefix = f"regime.{regime.label}"
        facts.append(_fact(f"{prefix}.bars", f"{regime.label} bars", regime.bars, FactKind.COUNT, regime_source))
        facts += _evidence_facts(prefix, regime.label.replace("_", " ").title(), regime.evidence, regime_source)

    if card.tax is not None:
        tax = card.tax
        facts.append(_fact("tax.gross_return", "Gross return", tax.gross_return, FactKind.SIGNED_PERCENT, tax_source))
        facts.append(
            _fact("tax.after_tax_return", "After-tax return", tax.after_tax_return, FactKind.SIGNED_PERCENT, tax_source)
        )
        facts.append(
            _fact("tax.short_term_gains", "Short-term gains (fraction of basis)", tax.short_term_gains, FactKind.SIGNED_PERCENT, tax_source)
        )
        facts.append(
            _fact("tax.long_term_gains", "Long-term gains (fraction of basis)", tax.long_term_gains, FactKind.SIGNED_PERCENT, tax_source)
        )
        facts.append(
            _fact("tax.wash_sales_triggered", "Wash sales triggered", tax.wash_sales_triggered, FactKind.COUNT, tax_source)
        )
        facts.append(
            _fact("tax.disallowed_loss", "Disallowed loss (fraction of basis)", tax.disallowed_loss, FactKind.SIGNED_PERCENT, tax_source)
        )
        if tax.unavailable_reason is not None:
            facts.append(
                _fact("tax.unavailable_reason", "Why tax figures are absent", tax.unavailable_reason, FactKind.TEXT, tax_source)
            )

    if ledger_stats is not None:
        facts.append(_fact("ledger.total_trials", "Total trials for this ticker", ledger_stats.total_trials, FactKind.COUNT, ledger_source))
        facts.append(_fact("ledger.survived", "Survived", ledger_stats.survived, FactKind.COUNT, ledger_source))
        facts.append(_fact("ledger.rejected", "Rejected", ledger_stats.rejected, FactKind.COUNT, ledger_source))
        facts.append(_fact("ledger.inconclusive", "Inconclusive", ledger_stats.inconclusive, FactKind.COUNT, ledger_source))

    entry = instruments.lookup(card.symbol)
    if entry is not None:
        facts.append(_fact("unlevered.factor", "Daily-reset multiple", entry.factor, FactKind.RATIO, instrument_source))
        if entry.underlying is not None:
            facts.append(_fact("unlevered.symbol", "Unlevered equivalent", entry.underlying, FactKind.TEXT, instrument_source))
        note = instruments.describe(card.symbol)
        if note is not None:
            facts.append(_fact("unlevered.note", "Leveraged-product note", note, FactKind.TEXT, instrument_source))

    collected = {fact.id: fact for fact in facts}
    return FactBundle(
        symbol=card.symbol,
        interval=card.interval,
        generated_at=card.generated_at,
        facts=collected,
        warnings=[],
    )


# ---------------------------------------------------------------------------------------------
# build_card
# ---------------------------------------------------------------------------------------------


def build_card(
    thesis: Thesis,
    record: ThesisRecord,
    *,
    bars: pd.DataFrame,
    evidence: Evidence,
    holdout_evidence: Evidence | None = None,
    ledger_stats: LedgerStats | None = None,
    holdout_state: HoldoutState | None = None,
    strategy_result: StrategyResult | None = None,
    unlevered_bars: pd.DataFrame | None = None,
    tax: TaxImpact | None = None,
    grammar: Grammar | None = None,
    evaluator: Evaluator | None = None,
    generated_at: dt.datetime | None = None,
) -> StrategyCard:
    """Assemble the deliverable card for one thesis, whatever its verdict.

    Args:
        thesis: The frozen claim. Must match ``record.thesis`` -- see the ``ValueError`` below.
        record: The registered thesis's result. ``record.verdict`` must be set (i.e. the loop got at
            least as far as the in-sample screen); a card for a still-``REGISTERED`` or ``ABANDONED``
            record is not meaningful and this function refuses to build one.
        bars: The full frame the evidence was measured over -- in-sample and holdout bars combined,
            in their original calendar order. Used for the baseline distribution, trigger frequency
            and regime segmentation, all of which need contiguous history; see the module docstring.
        evidence: The in-sample :class:`~app.thesis.models.Evidence` the loop already computed.
            Consumed, not recomputed.
        holdout_evidence: The holdout evidence, when the thesis survived the in-sample screen and the
            holdout was claimed. ``None`` for a thesis that never reached it.
        ledger_stats: The ticker's trial-family statistics, for the bundle and the debate's
            selection-effect caution.
        holdout_state: Carried straight onto the card.
        strategy_result: A full entry/exit backtest of the same rules, when one was run. Optional
            because not every card-building caller has one (a still-inconclusive thesis may never get
            a full backtest) -- when absent, ``triggers_per_year``, ``expected_return`` and
            ``baseline_return`` are still populated from ``evidence``/``bars`` alone, but
            ``holding_period_median``, ``holding_period_iqr``, ``worst_trade``,
            ``max_drawdown_in_position`` and the tax impact are not.
        unlevered_bars: Bars for the unlevered equivalent, when ``thesis.symbol`` is a daily-reset
            leveraged or inverse product with one mapped. See :func:`_unlevered_comparison`.
        tax: A precomputed :class:`~app.thesis.models.TaxImpact`, when the caller already has one
            (for instance, computed against a real portfolio ledger this package may not read).
            Computed from ``strategy_result`` via :func:`build_tax_impact` otherwise.
        grammar, evaluator: Injectable collaborators for the regime and baseline recomputation --
            identical seam to :mod:`app.thesis.loop` and :mod:`app.backtest.strategy`.
        generated_at: Defaults to now (UTC).

    Note on the signature versus the sketch in the phase brief: this function does not take a
    ``settings: Settings | None`` parameter. Nothing in this module touches storage, the market
    provider registry or any other setting-gated resource -- every input is supplied directly by the
    caller, which is also what keeps this package's "never read `data/`" constraint mechanically true
    rather than merely honoured by convention. If a future caller needs settings-driven behaviour
    here, that is a deliberate signature change for whoever owns this file next, not an oversight.
    """
    if record.thesis_hash != preregister.content_hash(thesis):
        raise ValueError(
            "thesis does not match record.thesis_hash; a card must describe the exact thesis that "
            "was registered, not a reworded one"
        )
    if record.verdict is None:
        raise ValueError(
            f"record {record.thesis_hash[:12]} has no verdict yet (status={record.status.value}); "
            "a card can only be built once the loop has produced at least an in-sample screen"
        )
    verdict: Verdict = record.verdict

    grammar_mod = grammar or _default_grammar()
    evaluator_mod = evaluator or _default_evaluator()
    when = generated_at or dt.datetime.now(dt.UTC)

    first_bar = bars["ts"].dt.date.iloc[0].isoformat() if len(bars) else "no bars"
    last_bar = bars["ts"].dt.date.iloc[-1].isoformat() if len(bars) else "no bars"
    window = f"{thesis.symbol} {thesis.interval.value} {first_bar}..{last_bar}"

    expected_return = (
        holdout_evidence.distribution
        if holdout_evidence is not None and holdout_evidence.distribution.count > 0
        else evidence.distribution
    )
    baseline_return = _baseline_distribution(thesis, bars, grammar=grammar_mod, evaluator=evaluator_mod)

    closed_trades = _closed_trades(strategy_result)
    holding_median, holding_iqr = _holding_period_stats(closed_trades)
    worst_trade = _worst_trade(closed_trades)
    max_dd_in_position = (
        _max_drawdown_in_position(strategy_result.equity_curve) if strategy_result is not None else None
    )
    triggers_per_year = _triggers_per_year(bars, thesis.interval, evidence, holdout_evidence)

    regimes = _build_regimes(thesis, bars, grammar=grammar_mod, evaluator=evaluator_mod)
    conditional_warning = _conditional_edge_warning(regimes)

    tax_impact = tax if tax is not None else build_tax_impact(thesis.symbol, strategy_result)

    nested_card, unlevered_warnings = _unlevered_comparison(
        thesis.symbol,
        thesis,
        verdict,
        unlevered_bars=unlevered_bars,
        grammar=grammar_mod,
        evaluator=evaluator_mod,
        generated_at=when,
    )

    warnings: list[MarketWarning] = list(unlevered_warnings)
    if conditional_warning is not None:
        warnings.append(conditional_warning)

    card = StrategyCard(
        symbol=thesis.symbol.upper(),
        interval=thesis.interval,
        generated_at=when,
        thesis=thesis,
        thesis_hash=record.thesis_hash,
        verdict=verdict,
        entry_rule=thesis.entry,
        exit_rule=thesis.exit,
        triggers_per_year=triggers_per_year,
        holding_period_median=holding_median,
        holding_period_iqr=holding_iqr,
        expected_return=expected_return,
        baseline_return=baseline_return,
        worst_trade=worst_trade,
        max_drawdown_in_position=max_dd_in_position,
        in_sample=evidence,
        holdout=holdout_evidence,
        holdout_state=holdout_state,
        ledger=ledger_stats,
        regimes=regimes,
        tax=tax_impact,
        unlevered_comparison=nested_card,
        hourly_substudy=None,
        strategy_result=strategy_result,
        bundle=None,
        warnings=warnings,
    )
    bundle = _build_bundle(card=card, ledger_stats=ledger_stats, window=window)
    return card.model_copy(update={"bundle": bundle})
