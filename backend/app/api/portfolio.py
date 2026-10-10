"""Portfolio endpoint: everything currently held, aggregated across accounts and priced.

Composes the same pieces the tax endpoints do, in the same order, for the same reason (see
:mod:`app.tax.engine`'s module docstring): replay the ledger, apply wash sales *before* anything
downstream reads a lot's basis or holding-period start, then aggregate. The one addition here is
pricing, which is deliberately kept out of :mod:`app.core.holdings` -- that module stays pure so it
can be unit-tested without a market-data dependency, and this module owns the one part of the
request that talks to the outside world (by way of the local daily-bar store).

**Cash is withheld rather than guessed.** Positions come from the lot replay; cash comes from
:mod:`app.core.cash`, which sums the ledger's cash movements *and* judges whether the export behind
them could support a balance at all. Two of the three broker adapters cannot: Webull exports order
history with no funding rows, and several Robinhood exports begin after the account was funded. An
account that fails those checks contributes nothing and is named in
:attr:`PortfolioReport.accounts_without_cash`, exactly as an unpriceable symbol is named in
``unpriced_symbols`` -- the same partial-total convention, applied to the other half of the book.
:attr:`PortfolioReport.total_equity` is ``None`` unless both halves are available, because an equity
figure that silently omits either one is the single most misleading number this endpoint could
produce.

**Pricing never fails the request.** Each open position is priced independently from
``app.market.store.ensure_series(symbol, Interval.DAY)`` -- the last stored daily close, never a
live quote (this project made that call for the whole app: see the store module's docstring). A
symbol the provider refuses, or that simply has no stored bars, lands in
:attr:`PortfolioReport.unpriced_symbols` with a ``null`` price and market value on its
:class:`Position`; the rest of the portfolio still prices. Totals are the sum over priced positions
only, so one bad symbol never blanks the whole total, and ``unpriced_symbols`` being non-empty is the
signal to the caller that the total is partial rather than complete.

Like the tax report, nothing here is cached or persisted: the ledger is replayed and re-aggregated on
every request.

**This is a calculation, not investment advice.**
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict

from app.api.market import SymbolPath
from app.config import Settings, get_settings
from app.core.canonical import canonicalize_ledger
from app.core.cash import AccountCash, build_cash
from app.core.holdings import AccountHolding, InstrumentHolding, build_positions
from app.core.lots import LotLedger, build_lots
from app.core.models import Account, AccountStatus, Money, Quantity, Transaction
from app.core.money import quantize_money
from app.datasource import ledger_db_path
from app.db import sqlite
from app.ingest.manifest import Manifest, load_declarations
from app.market import store
from app.market.models import Bar, Interval
from app.market.providers.base import ProviderError
from app.market.registry import ProviderRegistry, default_registry
from app.market.sectors import (
    SECTOR_VOCABULARY,
    load_sector_map,
    sector_for,
    set_sector,
)
from app.tax import engine as tax_engine
from app.tax.models import GainRow, TaxWarning, WarningGroup
from app.tax.washsale import apply_wash_sales

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

#: How many trailing bars to pull per symbol. Only the last close is used; a small limit keeps the
#: per-symbol store read (and any provider round-trip behind it) cheap without changing which bar
#: wins -- `ensure_series` still syncs the full incremental history, this only trims what is read
#: back for the response.
_PRICE_LOOKBACK = 5


# ---------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------


class AccountPosition(BaseModel):
    """One instrument's open position within one account. See the module docstring for how
    ``basis_uncertain``/``fees_unknown`` are decided."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str
    account_label: str
    broker: str
    quantity: Quantity
    cost_basis: Money
    lot_count: int
    basis_uncertain: bool
    fees_unknown: bool


class Position(BaseModel):
    """One instrument, rolled up across every account that holds it, with today's pricing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    instrument_id: str
    symbol: str
    quantity: Quantity
    cost_basis: Money
    basis_per_share: Money
    price: Money | None = None
    price_as_of: dt.date | None = None
    market_value: Money | None = None
    unrealized: Money | None = None
    unrealized_pct: float | None = None
    """Fraction, not a 0-100 percentage -- ``0.15`` is a 15% gain. Matches the convention already
    used by ``ReturnPct`` figures in the backtest engine."""
    weight_pct: float | None = None
    """This position's share of :attr:`PortfolioReport.total_market_value`, as a fraction of 1.
    ``null`` when this position itself is unpriced -- it has no market value to take a share of."""
    sector: str
    """Never null -- ``"Unclassified"`` (:data:`app.market.sectors.UNCLASSIFIED`) when this symbol has
    no entry in ``data/sectors.toml``. See :mod:`app.market.sectors`."""
    previous_close: Money | None = None
    """The session before :attr:`price_as_of`'s close, quantized to cents like :attr:`price`.
    ``null`` when the store holds only one bar for this symbol -- not enough history yet for a
    day-over-day comparison."""
    day_change: Money | None = None
    """``(price - previous_close) * quantity``. ``null`` whenever :attr:`previous_close` is."""
    day_change_pct: float | None = None
    """``(price - previous_close) / previous_close``. Fraction, not a 0-100 percentage, matching
    :attr:`unrealized_pct`. ``null`` whenever :attr:`previous_close` is ``null`` or ``0``."""
    short_term_quantity: Quantity
    long_term_quantity: Quantity
    earliest_acquired: dt.date
    latest_acquired: dt.date
    lot_count: int
    basis_uncertain: bool
    fees_unknown: bool
    wash_sale_adjustment: Money
    accounts: list[AccountPosition]


class AccountCashBalance(BaseModel):
    """One account's cash, or the reason there isn't one. See :mod:`app.core.cash`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str
    account_label: str
    broker: str
    tax_treatment: str
    """``taxable``, ``roth_ira`` or ``traditional_ira``.

    Here because this is the only per-account row the report sends, and the per-account view needs
    it: unrealized gain inside a Roth is never taxed, and summing it into one headline with taxable
    gain states something false about both. ``AccountPosition`` deliberately does not carry it --
    that would repeat one account's treatment on every instrument it holds and invite the two copies
    to disagree."""
    verdict: str
    """``derived``, ``declared``, ``no_funding_rows``, ``negative_in_cash_account`` or
    ``no_transactions``. A client must not treat this as a boolean: ``derived`` and ``declared`` both
    carry a balance and are both totalled, but they fail in different ways -- see ``declared_as_of``.
    """
    balance: Money | None = None
    """``null`` unless ``verdict`` is ``derived`` or ``declared``. The figure is withheld rather than
    returned with a warning flag, so a client cannot render a fabricated balance by forgetting to
    check."""
    settled: Money | None = None
    unsettled: Money | None = None
    unsettled_next_date: dt.date | None = None
    """The soonest ``settle_date`` behind ``unsettled`` -- when the first of it clears. See
    ``app.core.cash.AccountCash.unsettled_next_date`` for the full argument; in short, pending
    inflows can carry different settle dates, so this is paired with ``unsettled_full_date`` rather
    than standing alone as "the" settlement date. ``null`` either when nothing is pending
    (``unsettled`` is a real ``0``) or when ``unsettled`` itself is withheld (``null``) -- a client
    that needs to tell those apart checks ``unsettled`` alongside this field."""
    unsettled_full_date: dt.date | None = None
    """The date by which *every* dollar behind ``unsettled`` has cleared. Equal to
    ``unsettled_next_date`` whenever every pending row shares one settle date. Same ``null`` rule."""
    reason: str | None = None
    """Display-ready explanation. Normally why a balance is *absent* -- but on ``declared`` it
    accompanies a figure that is present, saying where it came from and that it does not move."""
    missing_opening_balance: Money | None = None
    """Lower bound on the opening cash the export omits, when that is why it was withheld."""
    coverage_start: dt.date | None = None
    coverage_end: dt.date | None = None

    declared_as_of: dt.date | None = None
    """When the user read a ``declared`` balance off their broker. Never null on that verdict, and a
    client showing the balance must show this too: a declared figure is a snapshot that drifts
    silently, and nothing here can detect it going stale."""
    declared_note: str | None = None
    derived_balance: Money | None = None
    """What the ledger would have said, where a declaration overrode a *trustworthy* derivation. Its
    presence means the two disagree, which is worth a look in both directions. ``null`` when the
    derivation was withheld -- that is not agreement, just an absence."""


class AccountSummary(BaseModel):
    """One account's identity, status and all-time realized result.

    Every account appears here, open and closed alike -- unlike :attr:`Position.accounts`, which
    only ever names accounts still holding open positions. This is the one place on the report a
    closed account's disposals are still visible after its holdings drop out of everything else.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: str
    label: str
    broker: str
    tax_treatment: str
    """``taxable``, ``roth_ira`` or ``traditional_ira``. See :class:`app.core.models.TaxTreatment`."""
    account_type: str
    """``cash``, ``margin`` or ``retirement``. See :class:`app.core.models.AccountType`."""
    status: str
    """``open`` or ``closed``. See :class:`app.core.models.AccountStatus`."""
    realized_gain: Money
    """All-time realized gain/loss for this account, defined as :attr:`realized_proceeds` minus
    :attr:`disposed_cost_basis` so the three figures on this row always reconcile to the cent --
    summed across every tax year the ledger spans. This is the portfolio's gross realized P&L, **not**
    the tax-reportable figure: it does not net out selling fees (including the regulatory sell fee
    reconstructed for a Webull sale) or wash-sale disallowance. Those adjustments belong to the tax
    report (:mod:`app.tax.gains`), which is where a filer's post-disallowance number lives. Zero for
    an account with no disposals, including every tax-advantaged account: :mod:`app.tax.gains` never
    produces a gain row for one (no loss is ever recognised inside an IRA), so this is
    indistinguishable here from "never sold anything"."""
    realized_proceeds: Money
    disposed_cost_basis: Money
    position_count: int
    """Open positions the ledger still shows for this account, counted **before** the closed-account
    exclusion below runs -- an account's own position count reflects what it actually holds,
    regardless of whether this report's totals still include it."""


class PortfolioReport(BaseModel):
    """Everything the Portfolio page needs from one rebuild."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    as_of: dt.date
    generated_at: dt.datetime
    positions: list[Position]
    total_cost_basis: Money
    """Sum over every open position, priced or not -- basis is always known from the ledger, unlike
    market value."""
    total_market_value: Money | None = None
    """Sum over priced positions only. ``null`` only when *no* position could be priced; otherwise a
    partial sum, with the gap named in :attr:`unpriced_symbols`."""
    total_unrealized: Money | None = None
    total_unrealized_pct: float | None = None
    priced_position_count: int
    unpriced_symbols: list[str]

    cash_balance: Money | None = None
    """Sum over accounts whose cash is derivable. ``null`` when none are -- otherwise a partial sum,
    with the gap named in :attr:`accounts_without_cash`."""
    settled_cash: Money | None = None
    unsettled_cash: Money | None = None
    """Proceeds not yet settled as of :attr:`as_of`. Not spendable in a cash account, which is why
    it is broken out rather than folded into :attr:`cash_balance`."""
    unsettled_next_date: dt.date | None = None
    """The ledger-wide soonest settle date behind :attr:`unsettled_cash` -- see
    :attr:`app.core.cash.CashLedger.unsettled_next_date`. ``null`` when :attr:`unsettled_cash` is
    ``null`` (a contributing account's split was withheld) or a real ``0`` (nothing pending)."""
    unsettled_full_date: dt.date | None = None
    """The ledger-wide date by which everything behind :attr:`unsettled_cash` has cleared. Same
    ``null`` rule as :attr:`unsettled_next_date`."""
    total_equity: Money | None = None
    """:attr:`cash_balance` plus :attr:`total_market_value`.

    ``null`` unless **both** are available. A partial market value or a partial cash figure each
    make this wrong by an unknown amount, and unlike the two components -- where a partial sum plus
    a named gap is still useful -- an equity number is read as *the* answer to "what is this worth".
    There is no honest way to render it partially, so it is withheld instead."""
    equity_is_complete: bool = False
    """True only when every position priced and every account's cash derived. When false, either
    :attr:`unpriced_symbols` or :attr:`accounts_without_cash` says which half is missing."""
    accounts_without_cash: list[str] = []
    """Account ids excluded from :attr:`cash_balance`. The cash counterpart of
    :attr:`unpriced_symbols`."""
    cash_by_account: list[AccountCashBalance] = []

    positions_with_uncertain_basis: int
    positions_with_unknown_fees: int
    warnings: list[TaxWarning]
    warning_groups: list[WarningGroup]

    accounts: list[AccountSummary] = []
    """Every account, open and closed, sorted by :attr:`AccountSummary.label`."""
    open_account_count: int = 0
    total_day_change: Money | None = None
    """Sum of every priced position's :attr:`Position.day_change`. ``null`` only when *no* priced
    position had a previous close to compare against -- the day-change counterpart of
    :attr:`total_market_value`'s own partial-sum convention."""
    total_day_change_pct: float | None = None
    """``total_day_change / (total_market_value - total_day_change)`` -- the denominator is
    yesterday's priced market value, reconstructed by backing today's change out of today's total.
    ``null`` whenever :attr:`total_day_change` is, or that denominator is zero."""
    excluded_closed_positions: int = 0
    """Account-level positions dropped because their account's :class:`~app.core.models.AccountStatus`
    is ``closed`` -- a count of :class:`AccountHolding` slices, not of instruments. See the module
    docstring's closed-account exclusion section."""
    excluded_closed_symbols: list[str] = []
    """Symbols dropped entirely because every account holding them was closed. Sorted, deduped."""


# ---------------------------------------------------------------------------
# Warnings: converted straight from the ledger, same shape the tax report uses
# ---------------------------------------------------------------------------


def _convert_warnings(ledger: LotLedger, accounts: Mapping[str, Account]) -> list[TaxWarning]:
    """Every warning the replay produced, structured for display -- unscoped by year, unlike the
    tax report, because a portfolio has no year of its own."""
    return [
        TaxWarning(
            kind=warning.kind.value,
            account_id=warning.account_id,
            broker=(
                accounts[warning.account_id].broker.value
                if warning.account_id in accounts
                else None
            ),
            symbol=warning.symbol,
            trade_date=warning.trade_date,
            detail=warning.detail,
        )
        for warning in ledger.warnings
    ]


def _summarize_warnings(warnings: Sequence[TaxWarning]) -> list[WarningGroup]:
    """Collapse to one row per ``(kind, account_id)``, sorted by count descending. A small copy of
    the equivalent helper in ``app.tax.engine`` -- not imported from there so this module has no
    dependency on the tax report's private internals, and duplicating ~10 lines of display grouping
    is cheaper than coupling two otherwise-independent endpoints to the same non-exported helper."""
    groups: dict[tuple[str, str | None], list[TaxWarning]] = defaultdict(list)
    for warning in warnings:
        groups[(warning.kind, warning.account_id)].append(warning)

    result = [
        WarningGroup(
            kind=kind,
            account_id=account_id,
            broker=items[0].broker,
            count=len(items),
            sample_detail=items[0].detail,
        )
        for (kind, account_id), items in groups.items()
    ]
    result.sort(key=lambda g: (-g.count, g.kind, g.account_id or ""))
    return result


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def _registry() -> ProviderRegistry:
    """One registry per request -- see the identical helper and its docstring in `app.api.market`."""
    return default_registry()


def _price_from_bar(bar: Bar) -> tuple[Decimal, dt.date]:
    """Convert one stored daily bar into the (price, as-of-date) pair the report renders.

    `Bar.close` is a market float by design (see app.market.models). Going through `str` gets the
    shortest repr that round-trips the float -- which is **not** the same as getting the price
    back. A close of $777.88 stored as a 32-bit float reads back as `777.8800048828125`, and
    `Decimal(str(...))` preserves every one of those digits faithfully. The comment that used to
    sit here claimed this step "avoids importing the float's binary imprecision"; it converts the
    imprecision, it does not remove it, and the result was `"market_value": "1555.7600097656250"`
    crossing the API. A UAT persona caught it and named the cost exactly: a raw pull from this
    endpoint cannot be trusted without re-rounding it first, in an application whose first
    standing decision is that money is never a float.

    Quantizing to cents is what actually recovers the price. US daily closes are quoted to the
    cent, so the twelve trailing digits are pure float32 quantisation noise and rounding them off
    restores $777.88 rather than discarding real precision. This is an output boundary --
    `quantize_money`'s docstring permits rounding here and forbids it mid-calculation.
    """
    return quantize_money(Decimal(str(bar.close))), bar.ts.date()


def _price(symbol: str, *, registry: ProviderRegistry) -> tuple[Decimal, dt.date] | None:
    """The last stored daily close for ``symbol``, or ``None`` if it cannot be priced.

    Never raises: a provider refusal (`ProviderError` -- not found, rate-limited, unavailable) and an
    empty result (a symbol the store has no bars for at all, e.g. a private pre-IPO holding) both
    degrade to ``None`` so the caller can put the symbol in ``unpriced_symbols`` and move on to the
    next position rather than failing the whole report.

    Retained as a single-symbol entry point (used by callers that only need one price); `_build_report`
    itself prices every open position in one call to `store.latest_two_bars` instead of calling this
    in a loop -- see that function's docstring for why.
    """
    try:
        series = store.ensure_series(
            symbol.upper(), Interval.DAY, limit=_PRICE_LOOKBACK, registry=registry
        )
    except ProviderError:
        return None
    if series.is_empty:
        return None
    return _price_from_bar(series.bars[-1])


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def _build_report() -> PortfolioReport:
    settings = get_settings()
    ledger_file = ledger_db_path(settings)
    if not ledger_file.exists():
        raise HTTPException(status_code=404, detail="no ledger yet; import broker exports first")

    with sqlite.connect(ledger_file, read_only=True) as conn:
        accounts = {account.account_id: account for account in sqlite.fetch_accounts(conn)}
        instruments = {
            instrument.instrument_id: instrument for instrument in sqlite.fetch_instruments(conn)
        }
        transactions = [
            sqlite.transaction_from_row(row) for row in sqlite.fetch_transactions(conn)
        ]

    if not transactions:
        # A migrated-but-empty ledger has no last transaction date to report `as_of` against --
        # the same genuinely-different-from-"nothing to show" condition `app.api.tax` treats as a
        # 404 for a missing ledger file entirely.
        raise HTTPException(status_code=404, detail="no ledger yet; import broker exports first")

    as_of = max(txn.trade_date for txn in transactions)

    # See app.core.canonical's module docstring: Webull never supplies a CUSIP, so the same security
    # held at Robinhood and Webull can carry two distinct instrument_id values until this runs. Must
    # happen before build_lots -- this is also what fixes the symbol appearing twice on this page.
    transactions, instruments = canonicalize_ledger(transactions, instruments)

    # Both declaration kinds the manifest carries must reach the replay, not just `opening`. A
    # `[[transfer_basis]]` entry seeds the basis an inbound ACAT leg cannot draw from the ledger
    # (see app.core.lots.TransferBasis); without it that leg opens a zero-basis lot, its later sale
    # books a phantom gain instead of a loss, and the wash-sale pass never fires on it -- so this
    # page and the Tax page (`app.api.tax._build`, which does pass it) disagreed on a real ledger by
    # a wash-sale event and its disallowed loss from the same database.
    manifest = load_declarations(settings)
    lot_ledger = build_lots(
        transactions,
        accounts=accounts,
        instruments=instruments,
        opening=manifest.opening_positions if manifest else (),
        transfer_basis=manifest.transfer_bases if manifest else (),
    )
    apply_wash_sales(lot_ledger, accounts=accounts)

    holdings = build_positions(lot_ledger, accounts=accounts, as_of=as_of)

    # `position_count` on `AccountSummary` counts open positions **before** the closed-account
    # exclusion below runs -- an account's own position count reflects what it actually holds, not
    # what survives into this report's totals.
    open_position_counts: dict[str, int] = defaultdict(int)
    for holding in holdings:
        for account_holding in holding.accounts:
            open_position_counts[account_holding.account_id] += 1

    holdings, excluded_closed_positions, excluded_closed_symbols = _exclude_closed_accounts(
        holdings, accounts
    )

    # One batched call prices every open position instead of `_price` in a loop. `store.
    # latest_two_bars` opens a single shared DuckDB connection to read every symbol's stored bars,
    # syncing only the (normally zero) symbols that are missing or stale -- see its docstring in
    # `app.market.store` for why that matters: connecting costs ~23ms on this machine regardless of
    # what is queried, so 67 positions each opening their own connection cost well over a second
    # before a single row was read. It also carries the session *before* the latest one, so the same
    # batch supplies both today's price and yesterday's close for the day-over-day columns below. A
    # symbol simply absent from the returned dict (unstored and the provider refuses it too) lands in
    # `unpriced_symbols`, exactly as a `None` result from `_price` used to.
    bars_by_symbol: dict[str, tuple[Bar, Bar | None]] = store.latest_two_bars(
        [holding.symbol for holding in holdings], Interval.DAY, registry=_registry()
    )

    priced: dict[str, tuple[Decimal, dt.date]] = {}
    previous_close_by_id: dict[str, Decimal | None] = {}
    priced_cost_basis = Decimal(0)
    total_market_value = Decimal(0)
    unpriced_symbols: list[str] = []

    for holding in holdings:
        pair = bars_by_symbol.get(holding.symbol.upper())
        if pair is None:
            unpriced_symbols.append(holding.symbol)
            continue
        latest_bar, previous_bar = pair
        result = _price_from_bar(latest_bar)
        price, _price_as_of = result
        priced[holding.instrument_id] = result
        previous_close_by_id[holding.instrument_id] = (
            quantize_money(Decimal(str(previous_bar.close))) if previous_bar is not None else None
        )
        priced_cost_basis += holding.cost_basis
        total_market_value += price * holding.quantity

    priced_position_count = len(priced)

    positions = [
        _to_position(
            holding,
            priced.get(holding.instrument_id),
            previous_close_by_id.get(holding.instrument_id),
            total_market_value,
        )
        for holding in holdings
    ]

    # The running sum above stays unrounded so the totals are not the sum of seven rounded rows;
    # they are quantized once, here, where they become reported figures.
    total_market_value = quantize_money(total_market_value)
    # Quantized like every other total here. It was the one figure this comment did not actually
    # cover: it reached the wire unrounded, `"196646.9808333334"` against siblings carrying two
    # decimals, because a fractional-share lot divides basis into a repeating decimal and nothing
    # rounded it afterwards. Invisible on the page, which formats to cents, and wrong for anyone
    # consuming the API -- summing the raw positions gave an answer a third of a cent away from
    # summing the displayed ones.
    total_cost_basis = quantize_money(sum((holding.cost_basis for holding in holdings), Decimal(0)))
    total_unrealized = (
        quantize_money(total_market_value - priced_cost_basis) if priced_position_count else None
    )
    total_unrealized_pct = (
        float(total_unrealized / priced_cost_basis)
        if total_unrealized is not None and priced_cost_basis != 0
        else None
    )

    # `total_day_change` sums each position's own `day_change`, already quantized -- `None` only when
    # not one priced position had a previous close to compare against. The percent's denominator
    # reconstructs yesterday's priced market value by backing today's change out of today's total,
    # per the module contract: a position with no previous close contributes 0 to `total_day_change`
    # and is therefore implicitly treated as unchanged in both today's and yesterday's sum.
    total_day_change_raw = Decimal(0)
    any_day_change = False
    for position in positions:
        if position.day_change is not None:
            total_day_change_raw += position.day_change
            any_day_change = True
    total_day_change = quantize_money(total_day_change_raw) if any_day_change else None
    total_day_change_pct: float | None = None
    if total_day_change is not None:
        yesterday_market_value = total_market_value - total_day_change
        if yesterday_market_value != 0:
            total_day_change_pct = float(total_day_change / yesterday_market_value)

    warnings = _convert_warnings(lot_ledger, accounts)

    # Cash is derived from the transaction ledger rather than the lot ledger -- lots know about
    # instruments, not about deposits -- so it takes the transactions directly. `as_of` is shared
    # with everything else on the report so that "unsettled" is unsettled as of the same instant the
    # positions are stated as of. Deliberately **not** filtered by account status: a closed account's
    # cash is exactly as real as an open one's, and `cash_by_account` names every account either way.
    cash_ledger = build_cash(
        transactions,
        accounts=accounts,
        as_of=as_of,
        declared=manifest.declared_cash if manifest else {},
    )

    market_value = total_market_value if priced_position_count else None
    everything_priced = not unpriced_symbols and market_value is not None
    equity_is_complete = everything_priced and cash_ledger.is_complete and cash_ledger.total is not None
    total_equity = (
        cash_ledger.total + market_value
        if equity_is_complete and cash_ledger.total is not None and market_value is not None
        else None
    )

    account_summaries, open_account_count = _account_summaries(
        accounts,
        settings=settings,
        transactions=transactions,
        manifest=manifest,
        as_of=as_of,
        position_counts=open_position_counts,
    )

    return PortfolioReport(
        as_of=as_of,
        generated_at=dt.datetime.now(dt.UTC),
        positions=positions,
        total_cost_basis=total_cost_basis,
        total_market_value=market_value,
        total_unrealized=total_unrealized,
        total_unrealized_pct=total_unrealized_pct,
        priced_position_count=priced_position_count,
        unpriced_symbols=unpriced_symbols,
        cash_balance=cash_ledger.total,
        settled_cash=cash_ledger.settled_total,
        unsettled_cash=cash_ledger.unsettled_total,
        unsettled_next_date=cash_ledger.unsettled_next_date,
        unsettled_full_date=cash_ledger.unsettled_full_date,
        total_equity=total_equity,
        equity_is_complete=equity_is_complete,
        accounts_without_cash=list(cash_ledger.accounts_without_cash),
        cash_by_account=[_to_account_cash(entry) for entry in cash_ledger.accounts],
        positions_with_uncertain_basis=sum(1 for h in holdings if h.basis_uncertain),
        positions_with_unknown_fees=sum(1 for h in holdings if h.fees_unknown),
        warnings=warnings,
        warning_groups=_summarize_warnings(warnings),
        accounts=account_summaries,
        open_account_count=open_account_count,
        total_day_change=total_day_change,
        total_day_change_pct=total_day_change_pct,
        excluded_closed_positions=excluded_closed_positions,
        excluded_closed_symbols=excluded_closed_symbols,
    )


# ---------------------------------------------------------------------------
# Closed-account exclusion
# ---------------------------------------------------------------------------


def _exclude_closed_accounts(
    holdings: Sequence[InstrumentHolding], accounts: Mapping[str, Account]
) -> tuple[list[InstrumentHolding], int, list[str]]:
    """Drop closed-account slices from every holding, and the holding itself if nothing survives.

    An unknown ``account_id`` (should not happen -- `build_positions` already requires one) is
    treated as open rather than dropped silently, matching that function's own "raise, don't guess"
    posture being unavailable to us here; in practice every ``account_id`` on a holding resolves.

    Returns the filtered holdings (roll-up fields recomputed from the surviving slices only), the
    count of dropped `AccountHolding` slices across every holding, and the sorted, deduped symbols of
    holdings left with no surviving slice at all.
    """
    filtered: list[InstrumentHolding] = []
    excluded_positions = 0
    excluded_symbols: set[str] = set()

    for holding in holdings:
        surviving = tuple(
            account_holding
            for account_holding in holding.accounts
            if accounts.get(account_holding.account_id) is None
            or accounts[account_holding.account_id].status is not AccountStatus.CLOSED
        )
        dropped = len(holding.accounts) - len(surviving)
        excluded_positions += dropped

        if not surviving:
            excluded_symbols.add(holding.symbol)
            continue

        if dropped:
            holding = dataclasses.replace(
                holding,
                accounts=surviving,
                quantity=sum((a.quantity for a in surviving), Decimal(0)),
                cost_basis=sum((a.cost_basis for a in surviving), Decimal(0)),
                lot_count=sum(a.lot_count for a in surviving),
                basis_uncertain=any(a.basis_uncertain for a in surviving),
                fees_unknown=any(a.fees_unknown for a in surviving),
            )

        filtered.append(holding)

    return filtered, excluded_positions, sorted(excluded_symbols)


# ---------------------------------------------------------------------------
# Realized gains, all-time, per account
# ---------------------------------------------------------------------------


def _account_summaries(
    accounts: Mapping[str, Account],
    *,
    settings: Settings,
    transactions: Sequence[Transaction],
    manifest: Manifest | None,
    as_of: dt.date,
    position_counts: Mapping[str, int],
) -> tuple[list[AccountSummary], int]:
    """One :class:`AccountSummary` per account, label-sorted, plus the count of open accounts.

    Realized figures are all-time: :func:`app.tax.engine.report_from_ledger` only ever reports one
    tax year, so every year the ledger spans is replayed and its :class:`~app.tax.models.GainRow`\\s
    are summed per account. **Not filtered by account status** -- a closed account's realized history
    is exactly as real as an open one's, which is the entire reason this table still names it.

    Performance note: each year replays the full lot ledger and wash-sale pass (~290ms on a real
    ledger of roughly a thousand transactions, per `app.tax.engine`'s own docstring), because wash-sale matching
    is whole-ledger regardless of the year requested. A ledger spanning N years therefore costs
    roughly N times that on every portfolio request. Correct first, as instructed; a ledger spanning
    many years would be the point to memoize this per year or restrict it to years actually touched.
    """
    # [proceeds, disposed_cost_basis]. Realized gain is derived as their difference (below), not
    # summed from the per-row `reportable_gain_loss`: that column is net of the reconstructed
    # regulatory sell fee and of wash-sale disallowance, so summing it would make this summary's
    # own `realized_gain` disagree with its own `realized_proceeds - disposed_cost_basis` by those
    # amounts -- e.g. a $60 proceeds / $40 basis disposal carrying a 1-cent estimated Webull fee
    # reports gain 19.99 against proceeds 60.00 and basis 40.00. The three figures this summary
    # publishes must reconcile to the cent; the net-of-fees, post-disallowance figure is the tax
    # report's job (`app.tax.gains`), not the portfolio summary's.
    gain_totals: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])

    if transactions:
        years = sorted({txn.trade_date.year for txn in transactions})
        opening = manifest.opening_positions if manifest else ()
        # Same declarations `_build_report` hands `build_lots`: the per-account realized figures
        # here must come from the same replay the Tax page runs, or a declared ACAT basis would
        # change one page's realized gain and not the other's.
        transfer_basis = manifest.transfer_bases if manifest else ()
        with sqlite.connect(ledger_db_path(settings), read_only=True) as conn:
            for year in range(years[0], years[-1] + 1):
                report = tax_engine.report_from_ledger(
                    conn,
                    tax_year=year,
                    opening=opening,
                    transfer_basis=transfer_basis,
                    as_of=as_of,
                )
                for row in report.gains.rows:
                    bucket = gain_totals[row.account_id]
                    _accumulate_gain_row(bucket, row)

    summaries = [
        AccountSummary(
            account_id=account_id,
            label=account.label,
            broker=account.broker.value,
            tax_treatment=account.tax_treatment.value,
            account_type=account.account_type.value,
            status=account.status.value,
            realized_gain=quantize_money(gain_totals[account_id][0] - gain_totals[account_id][1]),
            realized_proceeds=quantize_money(gain_totals[account_id][0]),
            disposed_cost_basis=quantize_money(gain_totals[account_id][1]),
            position_count=position_counts.get(account_id, 0),
        )
        for account_id, account in accounts.items()
    ]
    summaries.sort(key=lambda a: a.label)
    open_account_count = sum(1 for account in accounts.values() if account.status is AccountStatus.OPEN)
    return summaries, open_account_count


def _accumulate_gain_row(bucket: list[Decimal], row: GainRow) -> None:
    # [proceeds, cost_basis]. Both are already cent-quantized per row by `app.tax.gains`, so their
    # running sums stay exact; the derived `realized_gain = proceeds - basis` is quantized once at
    # the output boundary. `reportable_gain_loss` is deliberately not summed here -- see the note on
    # `gain_totals` in `_account_summaries`.
    bucket[0] += row.proceeds
    bucket[1] += row.cost_basis


def _to_position(
    holding: InstrumentHolding,
    priced: tuple[Decimal, dt.date] | None,
    previous_close: Decimal | None,
    total_market_value: Decimal,
) -> Position:
    price: Decimal | None = None
    price_as_of: dt.date | None = None
    market_value: Decimal | None = None
    unrealized: Decimal | None = None
    unrealized_pct: float | None = None
    weight_pct: float | None = None
    day_change: Decimal | None = None
    day_change_pct: float | None = None

    if priced is not None:
        price, price_as_of = priced
        # Quantized at the point they become reported figures. `price` is already clean, but a
        # fractional share multiplied by a cent-precise price still lands between cents, and these
        # two fields are what a caller sums. The percentages below deliberately use the unrounded
        # products: a ratio has no cent to round to, and rounding its inputs first is how a weight
        # column stops adding to 100%.
        computed_value = price * holding.quantity
        computed_unrealized = computed_value - holding.cost_basis
        market_value = quantize_money(computed_value)
        unrealized = quantize_money(computed_unrealized)
        if holding.cost_basis != 0:
            unrealized_pct = float(computed_unrealized / holding.cost_basis)
        if total_market_value != 0:
            weight_pct = float(computed_value / total_market_value)
        if previous_close is not None:
            day_change = quantize_money((price - previous_close) * holding.quantity)
            if previous_close != 0:
                day_change_pct = float((price - previous_close) / previous_close)

    return Position(
        instrument_id=holding.instrument_id,
        symbol=holding.symbol,
        quantity=holding.quantity,
        # Reported figure, so quantized here like `market_value` and `unrealized` above.
        # `basis_per_share` deliberately is not: it is a rate, and rounding it to cents would make
        # `basis_per_share * quantity` disagree with the basis on the same row.
        cost_basis=quantize_money(holding.cost_basis),
        basis_per_share=holding.basis_per_share,
        price=price,
        price_as_of=price_as_of,
        market_value=market_value,
        unrealized=unrealized,
        unrealized_pct=unrealized_pct,
        weight_pct=weight_pct,
        sector=sector_for(holding.symbol),
        previous_close=previous_close,
        day_change=day_change,
        day_change_pct=day_change_pct,
        short_term_quantity=holding.short_term_quantity,
        long_term_quantity=holding.long_term_quantity,
        earliest_acquired=holding.earliest_acquired,
        latest_acquired=holding.latest_acquired,
        lot_count=holding.lot_count,
        basis_uncertain=holding.basis_uncertain,
        fees_unknown=holding.fees_unknown,
        wash_sale_adjustment=holding.wash_sale_adjustment,
        accounts=[_to_account_position(a) for a in holding.accounts],
    )


def _to_account_cash(entry: AccountCash) -> AccountCashBalance:
    return AccountCashBalance(
        account_id=entry.account_id,
        account_label=entry.account_label,
        broker=entry.broker,
        tax_treatment=entry.tax_treatment.value,
        verdict=entry.verdict.value,
        balance=entry.balance,
        settled=entry.settled,
        unsettled=entry.unsettled,
        unsettled_next_date=entry.unsettled_next_date,
        unsettled_full_date=entry.unsettled_full_date,
        reason=entry.reason,
        missing_opening_balance=entry.missing_opening_balance,
        coverage_start=entry.first_transaction,
        coverage_end=entry.last_transaction,
        declared_as_of=entry.declared_as_of,
        declared_note=entry.declared_note or None,
        derived_balance=entry.derived_balance,
    )


def _to_account_position(account: AccountHolding) -> AccountPosition:
    return AccountPosition(
        account_id=account.account_id,
        account_label=account.account_label,
        broker=account.broker,
        quantity=account.quantity,
        cost_basis=quantize_money(account.cost_basis),
        lot_count=account.lot_count,
        basis_uncertain=account.basis_uncertain,
        fees_unknown=account.fees_unknown,
    )


@router.get("")
def get_portfolio() -> PortfolioReport:
    """Every currently held position, aggregated across accounts and priced from the daily bar
    store. Derived state, rebuilt on every request -- see the module docstring."""
    return _build_report()


# ---------------------------------------------------------------------------
# Sector classification: read + write path over `data/sectors.toml`
# ---------------------------------------------------------------------------


class SectorMapResponse(BaseModel):
    """The frozen sector vocabulary a client may offer, plus the current symbol -> label map --
    everything a "reclassify this symbol" control needs to render itself. See
    :mod:`app.market.sectors`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vocabulary: list[str]
    map: dict[str, str]


class SectorUpdateRequest(BaseModel):
    """Body of `PUT /api/portfolio/sectors/{symbol}`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sector: str


class SectorUpdateResponse(BaseModel):
    """The symbol (upper-cased) and the label actually stored for it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    sector: str


@router.get("/sectors")
def get_sectors() -> SectorMapResponse:
    """The frozen sector vocabulary and the current symbol -> label classification, straight from
    `data/sectors.toml`. Read-only counterpart to `PUT /api/portfolio/sectors/{symbol}` below."""
    settings = get_settings()
    sector_map = load_sector_map(settings=settings)
    return SectorMapResponse(vocabulary=list(SECTOR_VOCABULARY), map=dict(sector_map))


@router.put("/sectors/{symbol}")
def put_sector(symbol: SymbolPath, body: SectorUpdateRequest) -> SectorUpdateResponse:
    """Reclassify `symbol` into `body.sector`, upserting `data/sectors.toml`.

    `sector` must be one of `SECTOR_VOCABULARY` -- anything else is a 422, not a 500, since this is
    a client-supplied value rejected by validation rather than an internal failure. Setting `sector`
    to `"Unclassified"` removes the symbol's entry rather than writing it out explicitly; see
    `app.market.sectors.set_sector`.

    `symbol` is constrained to the same alphabet `app.api.market.SymbolPath` uses -- a symbol never
    legitimately contains anything else, and without this bound an arbitrary string (a `%0A`, a
    stray `"`) reaches `set_sector`'s TOML writer, where correctness depends on `_quote` escaping
    everything that alphabet cannot already rule out at the boundary.
    """
    settings = get_settings()
    try:
        stored = set_sector(symbol, body.sector, settings=settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SectorUpdateResponse(symbol=symbol.upper(), sector=stored)


# ---------------------------------------------------------------------------
# Statement export
# ---------------------------------------------------------------------------


def _statement_markdown(report: PortfolioReport) -> str:
    """Render a portfolio statement: what is held, what it cost, what it is worth, what is in cash.

    The artifact a professional produces at the end of a period, and until cash existed it could not
    be produced at all -- a statement that omits 40% of the account is not a statement. Markdown
    rather than CSV, matching ``/api/report/export``: this is a document to read or archive, not a
    table to paste into a spreadsheet (Form 8949 already covers that need).

    **Every caveat travels with the figures.** An exported document outlives the screen it was
    generated from, so the unpriced symbols and the accounts whose cash could not be derived are
    written into the file itself rather than left behind in the UI. A reader months from now must be
    able to tell a complete statement from a partial one without access to this application.
    """
    lines: list[str] = [
        "# Portfolio statement",
        "",
        f"*Ledger as of {report.as_of.isoformat()} · "
        f"generated {report.generated_at:%Y-%m-%d %H:%M UTC}*",
        "",
        "> This is a calculation from imported brokerage history, not a broker statement and not "
        "investment advice. Reconcile against your broker's own records.",
        "",
    ]

    # -- completeness, first --------------------------------------------------
    caveats: list[str] = []
    if report.unpriced_symbols:
        caveats.append(
            f"**{len(report.unpriced_symbols)} position(s) could not be priced** and are excluded "
            f"from market value and unrealized totals: {', '.join(report.unpriced_symbols)}. They "
            "still hold real shares at a real cost basis."
        )
    for entry in report.cash_by_account:
        if entry.verdict != "derived" and entry.verdict != "no_transactions":
            caveats.append(
                f"**Cash unavailable for {entry.account_label} ({entry.broker})** — {entry.reason}"
            )
    if not report.equity_is_complete:
        caveats.append(
            "**No total equity is stated.** It is withheld unless every position prices and every "
            "account's cash derives, because a partial equity figure reads as a complete one."
        )
    if caveats:
        lines += ["## Completeness", ""]
        lines += [f"- {caveat}" for caveat in caveats]
        lines += [""]

    # -- totals ---------------------------------------------------------------
    lines += [
        "## Totals",
        "",
        "| Figure | Amount |",
        "| --- | ---: |",
        f"| Cost basis | {_money_md(report.total_cost_basis)} |",
        f"| Market value{' (partial)' if report.unpriced_symbols else ''} | "
        f"{_money_md(report.total_market_value)} |",
        f"| Unrealized gain/loss | {_money_md(report.total_unrealized)} |",
        f"| Cash{' (partial)' if report.accounts_without_cash else ''} | "
        f"{_money_md(report.cash_balance)} |",
        f"| — settled | {_money_md(report.settled_cash)} |",
        f"| — unsettled{_settlement_label_suffix(report.unsettled_next_date, report.unsettled_full_date)} "
        f"| {_money_md(report.unsettled_cash)} |",
        f"| **Total equity** | **{_money_md(report.total_equity)}** |",
        "",
    ]

    # -- holdings -------------------------------------------------------------
    lines += [
        "## Holdings",
        "",
        "| Symbol | Qty | Cost basis | Price | Priced as of | Market value | Unrealized | Weight |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for position in report.positions:
        weight = (
            f"{position.weight_pct * 100:.1f}%" if position.weight_pct is not None else "—"
        )
        lines.append(
            f"| {position.symbol} | {position.quantity} | {_money_md(position.cost_basis)} | "
            f"{_money_md(position.price)} | "
            f"{position.price_as_of.isoformat() if position.price_as_of else '—'} | "
            f"{_money_md(position.market_value)} | {_money_md(position.unrealized)} | {weight} |"
        )
    lines += [
        "",
        "Weight is a share of priced market value, not of total equity — cash sits outside it.",
        "",
    ]

    # -- cash -----------------------------------------------------------------
    derived = [entry for entry in report.cash_by_account if entry.verdict == "derived"]
    if derived:
        lines += [
            "## Cash by account",
            "",
            "| Account | Broker | Settled | Unsettled | Clears | Balance | Derived from |",
            "| --- | --- | ---: | ---: | --- | ---: | --- |",
        ]
        for entry in derived:
            window = (
                f"{entry.coverage_start} → {entry.coverage_end}"
                if entry.coverage_start and entry.coverage_end
                else "—"
            )
            clears_cell = (
                _settlement_text(entry.unsettled_next_date, entry.unsettled_full_date) or "—"
            )
            lines.append(
                f"| {entry.account_label} | {entry.broker} | {_money_md(entry.settled)} | "
                f"{_money_md(entry.unsettled)} | {clears_cell} | {_money_md(entry.balance)} | "
                f"{window} |"
            )
        lines += [
            "",
            "The window is the export's coverage, not necessarily the account's whole life.",
            "",
        ]

    return "\n".join(lines) + "\n"


def _money_md(value: Decimal | None) -> str:
    """Money for a Markdown cell. ``—`` for absent, never ``$0.00`` -- the distinction between "no
    figure" and "zero" is exactly what this statement exists to preserve."""
    if value is None:
        return "—"
    return f"${value:,.2f}"


def _settlement_text(next_date: dt.date | None, full_date: dt.date | None) -> str:
    """A single settle date, an explicit range, or `""` when there is nothing pending to date.

    Collapses to one date when `next_date == full_date` (the ordinary single-settle-date case) and
    states the range explicitly otherwise, for the same reason `AccountCash.unsettled_next_date`
    keeps both ends rather than picking one: a reader who sees one date and assumes it covers the
    whole figure would be wrong on any account with more than one pending settle date. Callers wrap
    this for their own context (a row-label suffix, a table cell); the text itself does not assume
    either.
    """
    if next_date is None or full_date is None:
        return ""
    if next_date == full_date:
        return next_date.isoformat()
    return f"{next_date.isoformat()} → {full_date.isoformat()}"


def _settlement_label_suffix(next_date: dt.date | None, full_date: dt.date | None) -> str:
    """`_settlement_text` wrapped as a `" (clears ...)"` suffix for the "— unsettled" row label in the
    totals table, or `""` when there is nothing pending -- so the row reads exactly like the plain
    "— unsettled" label it replaces on an account with nothing pending, rather than gaining a trailing
    "(clears)" with nothing after it."""
    text = _settlement_text(next_date, full_date)
    return f" (clears {text})" if text else ""


@router.get("/statement.md", response_class=PlainTextResponse)
def statement() -> PlainTextResponse:
    """The portfolio as a Markdown statement: holdings, cost basis, valuation, cash and equity."""
    report = _build_report()
    return PlainTextResponse(
        content=_statement_markdown(report),
        media_type="text/markdown",
        headers={
            "Content-Disposition": (
                f'attachment; filename="portfolio-statement-{report.as_of.isoformat()}.md"'
            )
        },
    )
