"""Tax-aware switch gate: whether an Agent Workflow desk may drop its incumbent strategy card for a
different one.

A regime-driven strategy switch is a liquidation event for every symbol the new card does not want.
Liquidating realises gains and losses, and three things can make that realisation cost more than the
switch is worth: an IRC §1091 wash sale that disallows a loss you were counting on, a gain sold days
before it would have qualified for the long-term rate, and a desk that changes its mind so often every
switch is a fresh short-term realisation. This module decides all three, reusing the repo's real tax
engines rather than re-deriving any of the arithmetic:

* :func:`app.core.lots.build_lots` -- FIFO lot replay, to turn a projected buy/sell ledger into lots
  and disposals exactly the way a real broker import would.
* :func:`app.tax.washsale.apply_wash_sales` -- IRC §1091, applied to that projected ledger. The 30-day
  window arithmetic lives there and is never reproduced here.
* :func:`app.tax.gains.classify_term` -- the calendar-anniversary short/long test, so "close to
  long-term" is computed the same way a filed return would be, not approximated with 365 days.
* :func:`app.paper.papertax.resolve_configured_rates` -- the user's configured short/long rates,
  falling back to the statutory upper bound. Never hardcoded here.

**Scope and its gaps.** This module owns exactly one ledger: the desk's own paper/live book, exactly
as :mod:`app.paper.papertax` owns exactly the paper book's. The same gaps that module's docstring
lists apply here for the same reason -- this is a projection built the same way, not a broader engine
-- and they matter to a switch decision specifically, not just to a filing:

* **No cross-account wash-sale detection against the user's real brokerage.** A symbol this desk sells
  at a loss and a symbol held in an outside account this module was never shown cannot be matched as a
  replacement purchase or a replaced sale. A switch this gate allows can still be a real wash sale once
  the user's whole portfolio is considered.
* **No $3,000/yr capital-loss limitation or loss carryforward.** ``st_premium_cost`` and the wash-sale
  figures below are gross, pre-limitation numbers, exactly the simplification
  :class:`app.paper.papertax.PaperTaxSummary.tax_owed` already documents.
* **No IRA / Rev. Rul. 2008-5 permanent disallowance beyond what the caller declares.** A
  :class:`PositionLot` not marked ``is_tax_advantaged=True`` is replayed as an ordinary taxable
  account; if the real lot sits in an IRA and the caller does not say so, a permanent disallowance
  will be silently modelled as an ordinary, recoverable one.

A gate that quietly ignored any of the above would let a switch through that a real tax bill later
punishes, which is worse than no gate at all -- so a caller integrating this must not read ``allowed``
as "costs nothing" beyond what is enumerated here.

**Inputs are deliberately not the real ledger.** ``backend/app/workflow/book.py``,
``book_models.py`` and ``regime.py`` are being written by other workers concurrently and their exact
shapes are not final. :class:`PositionLot`, :class:`RecentSale` and :class:`TargetCardSpec` below are
this module's own minimal, frozen input types; the orchestrator is responsible for projecting whatever
the real ledger and card registry end up looking like into these shapes.

**This is a calculation, not tax advice**, exactly as the engines it calls already say of themselves.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from app.core.lots import build_lots
from app.core.models import (
    Account,
    AccountType,
    Broker,
    Lot,
    TaxTreatment,
    Transaction,
    TxnAction,
)
from app.core.money import quantize_money
from app.paper.papertax import resolve_configured_rates

# `_add_one_year` computes the IRC §1222 calendar anniversary (Rev. Rul. 66-7: same month/day one
# year on, Feb-29 falls back to Feb-28 in a non-leap year). It is not part of `app.tax.gains`'s
# public surface, but this module must use the exact same rule the real gains report uses -- "do not
# approximate with 365 days" -- and duplicating five lines of calendar arithmetic is exactly the kind
# of drift the rest of this codebase's docstrings warn about. Importing it, rather than copying it, is
# the one guarantee that the two can never disagree.
from app.tax.gains import _add_one_year, classify_term
from app.tax.models import HoldingTerm, WashSaleEvent
from app.tax.washsale import apply_wash_sales

__all__ = [
    "LONG_TERM_HORIZON_DAYS",
    "MIN_DAYS_BETWEEN_SWITCHES",
    "SWITCH_TAX_COST_CAP_FRACTION",
    "LongTermHorizonLot",
    "PositionLot",
    "RecentSale",
    "SwitchOutcome",
    "SwitchVerdict",
    "TargetCardSpec",
    "evaluate_switch",
]

# ---------------------------------------------------------------------------
# Thresholds -- pre-registered judgements, not values fitted to any backtest.
# ---------------------------------------------------------------------------

LONG_TERM_HORIZON_DAYS: Final[int] = 45
"""How close to its one-year anniversary a gain lot has to be before the short-vs-long rate delta is
even examined. 45 days is roughly two of this system's own decision cadences (a workflow desk is not
expected to re-evaluate its regime more than a few times a month), so a lot this close to qualifying
for the long-term rate is one the desk itself was about to hold across the boundary anyway -- the
switch, not the tax code, is what would be cutting it short."""

SWITCH_TAX_COST_CAP_FRACTION: Final[Decimal] = Decimal("0.01")
"""The short-vs-long tax premium on a near-long-term gain is tolerated up to this fraction of the
position's own market value before it blocks a switch. 1% is a materiality floor, not a fitted
number: below it, the premium is smaller than ordinary slippage on re-entering the position later, so
blocking the switch over it would be optimizing a decimal a signal was never going to be that precise
about."""

MIN_DAYS_BETWEEN_SWITCHES: Final[int] = 7
"""Minimum days between two card switches when the regime label has not changed. A desk that
reconsiders its own card daily is not running a strategy, it is churning, and every unforced switch
realises tax on shares that an unchanged regime gave no new reason to sell. Seven days is one trading
week -- long enough that a switch inside it has to be justified by an actual regime change, not by the
same regime being re-scored slightly differently overnight."""

#: Synthetic account ids for the projected ledger this module builds. Never a real account -- see the
#: module docstring's cross-account-wash-sale gap.
_TAXABLE_ACCOUNT_ID: Final[str] = "workflow-switch-eval-taxable"
_TAX_ADVANTAGED_ACCOUNT_ID: Final[str] = "workflow-switch-eval-tax-advantaged"

#: `Transaction.import_id` provenance marker for every synthetic row this module builds -- mirrors
#: `app.paper.papertax.PAPER_IMPORT_ID`'s role exactly: a greppable sign that the row was never a line
#: in a broker export.
_IMPORT_ID: Final[str] = "workflow-taxcheck-synthetic"

#: How far before a `RecentSale`'s own sale date to backdate its reconstructed acquisition. Only has
#: to be older than any wash-sale window this module ever opens (61 days); comfortably larger so it
#: can never itself land inside one by construction.
_RECENT_SALE_LOOKBACK_PADDING_DAYS: Final[int] = 400

#: IRC §1091's window, restated only for the docstrings above and the `RecentSale` filter below --
#: `apply_wash_sales` owns the actual boundary arithmetic and this constant is never used to compute a
#: date range fed into it.
_WASH_SALE_WINDOW_DAYS: Final[int] = 30


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Inputs -- this module's own minimal shapes. See the module docstring: the real ledger and card
# registry are owned by other, concurrently-written modules and are adapted into these by the caller.
# ---------------------------------------------------------------------------


class PositionLot(_Frozen):
    """One currently-held tax lot, projected into exactly what this gate needs to reason about it.

    ``acquired_date`` is treated as the lot's *effective* holding-period start. If a real wash sale
    already tolled this lot's holding period backwards (see `app.tax.washsale`), the caller must pass
    the tolled date here, not the literal purchase date -- this module has no earlier ledger to
    re-derive that from.
    """

    symbol: str
    quantity: Decimal
    cost_basis: Decimal
    """Total basis for the whole lot (not per share)."""
    acquired_date: dt.date
    current_price: Decimal
    """Per-share. Drives both the lot's unrealized gain and its market value."""
    account_id: str = _TAXABLE_ACCOUNT_ID
    is_tax_advantaged: bool = False
    """True for a lot sitting in an IRA or similar. See the module docstring's IRA gap: a taxable lot
    left at the default here that is really tax-advantaged will be evaluated as ordinary, recoverable
    disallowance rather than the permanent Rev. Rul. 2008-5 kind."""

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.current_price

    @property
    def unrealized_gain(self) -> Decimal:
        """Positive for a gain, negative for a loss. Before any fee or wash-sale adjustment -- this
        module projects a sale, it does not replay one, so there are no fees to net out yet."""
        return self.market_value - self.cost_basis


class RecentSale(_Frozen):
    """A loss sale this desk already realised, recent enough that a same-symbol repurchase today --
    typically because the target card's universe wants to hold that symbol again -- would still fall
    inside IRC §1091's 61-day window and (re)trigger disallowance.

    This is the forward half of the wash-sale rule: :class:`PositionLot` alone can only show a
    *currently held* lot bought inside the window (the backward half, satisfied by passing more than
    one lot of the same symbol). A symbol sold at a loss and no longer held at all needs this type
    instead, because it has already left ``positions`` entirely.
    """

    symbol: str
    sale_date: dt.date
    quantity: Decimal
    loss_amount: Decimal
    """The realised loss on that sale, positive."""
    account_id: str = _TAXABLE_ACCOUNT_ID


class TargetCardSpec(_Frozen):
    """The card being switched to, reduced to exactly what this gate needs: which symbols it would
    hold afterward. Everything else about a strategy card (its rules, its scoring) is irrelevant to a
    tax decision."""

    card_id: str
    universe: frozenset[str]
    """Symbols (any case; compared upper-cased) the desk would hold once the switch completes. A
    symbol in both the current positions and this set is *kept*, never liquidated -- see the module
    docstring's overlap rule."""


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

SwitchOutcome = Literal[
    "allowed", "blocked_wash_sale", "blocked_near_long_term", "blocked_churn"
]


class LongTermHorizonLot(_Frozen):
    """One lot whose near-long-term gain is expensive enough to block the switch."""

    symbol: str
    days_remaining: int
    """Calendar days from ``today`` to this lot's one-year anniversary. Zero or positive -- a lot
    already past its anniversary is long-term already and never appears here."""
    unrealized_gain: Decimal


class SwitchVerdict(_Frozen):
    """Whether the switch is allowed, and everything needed to show why."""

    allowed: bool
    outcome: SwitchOutcome
    projected_wash_disallowance: Decimal = Decimal(0)
    """Sum of every §1091 disallowance the projected switch would trigger, ordinary and permanent
    together. Positive; zero unless ``outcome == "blocked_wash_sale"``."""
    st_premium_cost: Decimal = Decimal(0)
    """Sum, over every blocking lot in :attr:`days_to_long_term`, of the extra tax paid by realising
    the gain short-term today instead of waiting for the long-term rate. Zero unless
    ``outcome == "blocked_near_long_term"``."""
    days_to_long_term: tuple[LongTermHorizonLot, ...] = ()
    reason: str
    """Names the specific blocking lot(s) and figures. Shown to the user and quoted into a workflow
    stage's evidence, so a bare "blocked" is not an acceptable value here."""


# ---------------------------------------------------------------------------
# Projected-ledger construction
# ---------------------------------------------------------------------------


def _account_for(is_tax_advantaged: bool) -> Account:
    if is_tax_advantaged:
        return Account(
            account_id=_TAX_ADVANTAGED_ACCOUNT_ID,
            broker=Broker.ROBINHOOD,
            label="Workflow switch evaluation (synthetic, tax-advantaged)",
            tax_treatment=TaxTreatment.TRADITIONAL_IRA,
            account_type=AccountType.RETIREMENT,
        )
    return Account(
        account_id=_TAXABLE_ACCOUNT_ID,
        broker=Broker.ROBINHOOD,
        label="Workflow switch evaluation (synthetic, taxable)",
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=AccountType.CASH,
    )


def _resolve_account_id(is_tax_advantaged: bool) -> str:
    return _TAX_ADVANTAGED_ACCOUNT_ID if is_tax_advantaged else _TAXABLE_ACCOUNT_ID


def _build_projected_wash_sale_events(
    *,
    liquidated: Sequence[PositionLot],
    kept: Sequence[PositionLot],
    new_buy_symbols: frozenset[str],
    recent_sales: Sequence[RecentSale],
    today: dt.date,
) -> tuple[tuple[WashSaleEvent, ...], dict[str, Lot]]:
    """Replay a projected buy/sell ledger and apply IRC §1091 to it.

    Builds one BUY per currently-held lot (so every lot, sold or kept, is a legitimate replacement
    candidate for another disposal of the same symbol), one SELL dated ``today`` for every lot being
    liquidated, and -- for the forward direction of the rule -- a reconstructed loss sale plus a
    projected repurchase for every :class:`RecentSale` whose symbol the target card would newly buy
    and whose window still reaches ``today``.

    Returns the tuple of triggered :class:`~app.tax.models.WashSaleEvent` from
    :func:`app.tax.washsale.apply_wash_sales`, together with the lots-by-id map needed to describe
    which purchase caused each one. Nothing here computes a 30-day boundary itself -- that arithmetic
    belongs to ``apply_wash_sales`` alone.
    """
    transactions: list[Transaction] = []
    txn_index = 0

    def add(
        *,
        action: TxnAction,
        account_id: str,
        trade_date: dt.date,
        symbol: str,
        quantity: Decimal,
        price: Decimal,
        label: str,
    ) -> None:
        nonlocal txn_index
        transactions.append(
            Transaction(
                txn_id=f"{label}-{txn_index}",
                import_id=_IMPORT_ID,
                source_row=txn_index,
                replay_order=txn_index,
                account_id=account_id,
                broker=Broker.ROBINHOOD,
                action=action,
                trade_date=trade_date,
                symbol=symbol.upper(),
                quantity=quantity,
                price=price,
                fees=Decimal(0),
                description=f"workflow switch evaluation: {label}",
                raw_code="workflow_switch_eval",
            )
        )
        txn_index += 1

    accounts_present: set[bool] = set()

    for lot in (*liquidated, *kept):
        accounts_present.add(lot.is_tax_advantaged)
        cost_per_share = lot.cost_basis / lot.quantity if lot.quantity else Decimal(0)
        add(
            action=TxnAction.BUY,
            account_id=_resolve_account_id(lot.is_tax_advantaged),
            trade_date=lot.acquired_date,
            symbol=lot.symbol,
            quantity=lot.quantity,
            price=cost_per_share,
            label="position-buy",
        )

    for lot in liquidated:
        add(
            action=TxnAction.SELL,
            account_id=_resolve_account_id(lot.is_tax_advantaged),
            trade_date=today,
            symbol=lot.symbol,
            quantity=lot.quantity,
            price=lot.current_price,
            label="position-sell",
        )

    new_buy_upper = {s.upper() for s in new_buy_symbols}
    for sale in recent_sales:
        if sale.symbol.upper() not in new_buy_upper:
            continue  # not a symbol the switch would newly acquire -- no repurchase to project
        window_close = sale.sale_date + dt.timedelta(days=_WASH_SALE_WINDOW_DAYS)
        if today > window_close:
            continue  # the window has already closed; a repurchase today cannot reach back to it
        accounts_present.add(False)
        # Reconstruct a buy/sell pair whose realised loss is exactly `sale.loss_amount`, dated far
        # enough before `sale.sale_date` that it can never itself land inside any window this module
        # opens. The absolute price level is arbitrary -- only the loss and the dates matter to
        # `apply_wash_sales` -- so an arbitrary basis is chosen and the sale price solved backward
        # from it, rather than inventing a basis for `RecentSale` that nothing else needs.
        basis_price = Decimal(100)
        loss_per_share = sale.loss_amount / sale.quantity if sale.quantity else Decimal(0)
        add(
            action=TxnAction.BUY,
            account_id=_TAXABLE_ACCOUNT_ID,
            trade_date=sale.sale_date - dt.timedelta(days=_RECENT_SALE_LOOKBACK_PADDING_DAYS),
            symbol=sale.symbol,
            quantity=sale.quantity,
            price=basis_price,
            label="recent-sale-buy",
        )
        add(
            action=TxnAction.SELL,
            account_id=_TAXABLE_ACCOUNT_ID,
            trade_date=sale.sale_date,
            symbol=sale.symbol,
            quantity=sale.quantity,
            price=basis_price - loss_per_share,
            label="recent-sale-sell",
        )
        add(
            action=TxnAction.BUY,
            account_id=_TAXABLE_ACCOUNT_ID,
            trade_date=today,
            symbol=sale.symbol,
            quantity=sale.quantity,
            price=basis_price,
            label="recent-sale-repurchase",
        )

    if not transactions:
        return (), {}

    accounts = {_resolve_account_id(flag): _account_for(flag) for flag in accounts_present}
    ledger = build_lots(transactions, accounts=accounts)
    wash_result = apply_wash_sales(ledger, accounts=accounts)
    return wash_result.events, ledger.lots_by_id()


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def evaluate_switch(
    *,
    positions: Sequence[PositionLot],
    target_card: TargetCardSpec,
    incumbent_card_id: str,
    today: dt.date,
    card_adopted_date: dt.date,
    settings: object | None = None,
    recent_sales: Sequence[RecentSale] = (),
    regime_changed: bool = False,
) -> SwitchVerdict:
    """Decide whether a desk may switch from ``incumbent_card_id`` to ``target_card`` today.

    Args:
        positions: Every lot currently held by the desk. A symbol held in more than one lot (e.g. one
            bought long ago, one bought recently) is how the wash-sale check's backward direction is
            expressed -- pass every lot separately, never pre-netted.
        target_card: The card being switched to, reduced to its post-switch symbol universe.
        incumbent_card_id: The card currently running. Not otherwise consulted -- only used to name it
            in ``reason`` -- because everything this gate needs from "what would change" is already
            captured by ``positions`` (what is held now) and ``target_card.universe`` (what would be
            held after).
        today: The date the switch would execute and the projected sales would be dated.
        card_adopted_date: When ``incumbent_card_id`` itself was adopted, for the churn limiter.
        settings: Passed straight to :func:`app.paper.papertax.resolve_configured_rates` to get the
            user's real short/long tax rates where configured, falling back to the statutory upper
            bound. ``None`` reads the process-wide settings singleton.
        recent_sales: Loss sales this desk already realised whose IRC §1091 window can still reach
            ``today`` -- see :class:`RecentSale`. Only consulted for a symbol the switch would newly
            acquire (one not currently held); a symbol already held falls under the ordinary
            wash-sale path via ``positions`` instead.
        regime_changed: Whether the market regime that justifies ``target_card`` differs from the one
            that was active when ``incumbent_card_id`` was adopted. Defaults to ``False`` -- the
            conservative reading when the caller has not determined this, since it is the reading that
            can only make the churn limiter stricter, never looser.

    Returns:
        A :class:`SwitchVerdict`. Rules are checked in order -- a guaranteed §1091 disallowance first,
        then a soft near-long-term cost cap, then the churn limiter -- and the first that blocks wins;
        a switch with more than one problem is still reported as one outcome, the most concrete one.
    """
    target_universe = {s.upper() for s in target_card.universe}
    current_symbols = {p.symbol.upper() for p in positions}

    liquidated = [p for p in positions if p.symbol.upper() not in target_universe]
    kept = [p for p in positions if p.symbol.upper() in target_universe]
    new_buy_symbols = frozenset(target_universe - current_symbols)

    # --- 1. Wash-sale block: a hard, guaranteed IRS disallowance outranks a soft cost estimate. -----
    events, lots_by_id = _build_projected_wash_sale_events(
        liquidated=liquidated,
        kept=kept,
        new_buy_symbols=new_buy_symbols,
        recent_sales=recent_sales,
        today=today,
    )
    if events:
        total_disallowed = sum((event.disallowed_loss for event in events), Decimal(0))
        parts = []
        for event in events:
            replacement_dates = sorted(
                lots_by_id[lot_id].acquired_date
                for lot_id in event.replacement_lot_ids
                if lot_id in lots_by_id
            )
            replacement_note = (
                f"replacement bought {replacement_dates[0].isoformat()}"
                if replacement_dates
                else "replacement purchase inside the window"
            )
            parts.append(
                f"{event.symbol}: selling {event.quantity_sold} shares realises a "
                f"${event.loss_amount} loss on {event.sale_date.isoformat()}, of which "
                f"${event.disallowed_loss} is disallowed under IRC §1091 "
                f"({event.quantity_replaced} shares replaced; {replacement_note})"
            )
        reason = (
            f"Switch from {incumbent_card_id} to {target_card.card_id} blocked: "
            + "; ".join(parts)
            + f". Total projected disallowance ${quantize_money(total_disallowed)}."
        )
        return SwitchVerdict(
            allowed=False,
            outcome="blocked_wash_sale",
            projected_wash_disallowance=quantize_money(total_disallowed),
            reason=reason,
        )

    # --- 2. Near-long-term block: a soft cap on the cost of realising a gain short-term. -------------
    short_rate, long_rate, _rate_basis = resolve_configured_rates(settings)
    rate_delta = short_rate - long_rate

    blocking_lots: list[LongTermHorizonLot] = []
    blocking_details: list[str] = []
    total_premium = Decimal(0)
    for lot in liquidated:
        if lot.unrealized_gain <= 0:
            continue  # the rate delta only ever costs money on a gain; a loss has nothing to defer
        term = classify_term(lot.acquired_date, today)
        if term is not HoldingTerm.SHORT:
            continue  # already long-term as of today; no premium to weigh
        anniversary = _add_one_year(lot.acquired_date)
        days_remaining = (anniversary - today).days
        if days_remaining > LONG_TERM_HORIZON_DAYS:
            continue  # not close enough to the anniversary to be worth pricing at all
        premium = quantize_money(lot.unrealized_gain * rate_delta)
        cap = quantize_money(SWITCH_TAX_COST_CAP_FRACTION * lot.market_value)
        if premium <= cap:
            continue  # within the cap: the delta is smaller than ordinary re-entry slippage
        blocking_lots.append(
            LongTermHorizonLot(
                symbol=lot.symbol,
                days_remaining=days_remaining,
                unrealized_gain=lot.unrealized_gain,
            )
        )
        blocking_details.append(
            f"{lot.symbol}: {days_remaining} day(s) short of long-term (anniversary "
            f"{anniversary.isoformat()}) with a ${lot.unrealized_gain} unrealized gain; the "
            f"short-vs-long premium (${premium}) exceeds the "
            f"{SWITCH_TAX_COST_CAP_FRACTION * 100}% cost cap (${cap} of a "
            f"${lot.market_value} position)"
        )
        total_premium += premium

    if blocking_lots:
        reason = (
            f"Switch from {incumbent_card_id} to {target_card.card_id} blocked: "
            + "; ".join(blocking_details)
            + "."
        )
        return SwitchVerdict(
            allowed=False,
            outcome="blocked_near_long_term",
            st_premium_cost=quantize_money(total_premium),
            days_to_long_term=tuple(blocking_lots),
            reason=reason,
        )

    # --- 3. Churn limiter: no realised tax cost is guaranteed here, but an unforced, frequent switch
    # realises one anyway, so it is checked last rather than skipped. -------------------------------
    days_since_adoption = (today - card_adopted_date).days
    if not regime_changed and days_since_adoption < MIN_DAYS_BETWEEN_SWITCHES:
        reason = (
            f"Switch from {incumbent_card_id} to {target_card.card_id} blocked: only "
            f"{days_since_adoption} day(s) have passed since {incumbent_card_id} was adopted on "
            f"{card_adopted_date.isoformat()} (minimum {MIN_DAYS_BETWEEN_SWITCHES}) and the regime "
            "has not changed."
        )
        return SwitchVerdict(allowed=False, outcome="blocked_churn", reason=reason)

    reason = (
        f"Switch from {incumbent_card_id} to {target_card.card_id} allowed: no wash-sale, "
        "near-long-term, or churn constraint applies."
    )
    return SwitchVerdict(allowed=True, outcome="allowed", reason=reason)
