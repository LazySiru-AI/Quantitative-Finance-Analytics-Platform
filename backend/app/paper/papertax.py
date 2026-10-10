"""After-tax reporting for the paper desk, built entirely on the repo's real tax engine.

**The problem this closes.** `backend/app/tax/` and `backend/app/core/lots.py` implement a full
US cost-basis / wash-sale (IRC §1091) / holding-period engine, used today only to ingest real broker
CSVs (`app.tax.engine.report_from_ledger`). `app.paperdesk` never calls into it -- a paper trade's
`tax_treatment` is a display label, nothing more. Every closed trade on the paper cards is short-term
(the mandate's own trading horizon is 120-180 sessions and most exits are days to weeks), so the
reported returns carry a tax drag of several hundred to over 1,000 bps/yr that is nowhere on the
page, and the live record already contains real wash sales (e.g. card A-rotation: MU sold at a loss
2026-08-19, rebought 2026-08-21) that nothing today flags.

**What this module does.** Converts a sequence of :class:`app.paper.paperbroker.Fill` into the same
:class:`~app.core.models.Transaction` shape `app.tax.engine.report_from_ledger` builds from a real
broker export, then runs the *actual* engines over it: :func:`app.core.lots.build_lots` for FIFO lot
matching, :func:`app.tax.washsale.apply_wash_sales` for IRC §1091, :func:`app.tax.gains.realized_gains`
for the short/long split under the real calendar-anniversary rule. Nothing here reimplements any of
that math -- see :func:`build_paper_ledger` and :func:`summarize_paper_tax`.

**Purity.** Every function below is pure: it takes fills (and, for
:func:`summarize_paper_tax`, tax rates) and returns a value, with no file I/O, network, database
access, or mutation of module-level state. Two calls with the same input produce byte-identical
output. The one deliberate exception is :func:`resolve_configured_rates`, a separate, clearly-marked
helper that reads `app.config.get_settings()` -- see its docstring for why it is kept out of
:func:`summarize_paper_tax` itself rather than folded in as a hidden default.

**What this does NOT model**, because the thing it converts -- a
:class:`~app.paper.paperbroker.PaperBroker` run -- never produces the transaction shapes involved:

* No transfers, splits, spinoffs, or dividends. `PaperBroker` only ever emits whole-share (or, if a
  persona's mandate sets ``allow_fractional_shares``, fractional-share) BUY/SELL fills -- see
  `PaperBroker._precheck`/`_check_buy`/`_check_sell`. Every other :class:`~app.core.models.TxnAction`
  the replay understands (`TRANSFER_IN`, `SPLIT`, ...) is simply never constructed here.
* No shorting. `PaperBroker._check_sell` refuses to sell more than is held, so every disposal in the
  resulting ledger closes a genuinely long position.
* No cross-account wash sales against the user's *real* brokerage holdings. The ledger built here has
  exactly one synthetic account (see :func:`paper_account`) holding only the paper book's own trades;
  a real position in the same symbol, held in an account this module was never shown, cannot be
  matched as a replacement purchase or a replaced sale. A wash sale spanning the paper book and a real
  account is invisible here by construction, not by a bug -- combining the two ledgers, if ever
  wanted, is a decision for whatever calls this module, not something it should do silently.
* No IRA / Rev. Rul. 2008-5 permanent disallowance. The synthetic account is always
  `TaxTreatment.TAXABLE` (`PaperBroker` and `app.paper.mandate.default_mandate` model a cash account,
  never a retirement one), so `PaperTaxSummary.permanently_disallowed_total` is always zero here --
  kept on the shape for symmetry with `app.tax.models.GainsReport`, not because this module can ever
  populate it.
* No filing-grade personal tax bracket unless the caller supplies one. See
  :func:`summarize_paper_tax` and :func:`resolve_configured_rates`.
* No modelling of the $3,000/yr capital-loss limitation against ordinary income, or of loss
  carryforward. `PaperTaxSummary.tax_owed` floors each of the short- and long-term gain figures at
  zero before applying a rate -- a net loss reduces tax owed to zero, it does not produce a rebate --
  mirroring the same simplification `app.thesis.strategycard.build_tax_impact` already makes for the
  backtest-side tax-impact card.

**Two mapping decisions the paper broker's data does not settle on its own:**

1. **`Broker` is a closed enum of the three real adapters this app ingests
   (`ROBINHOOD`/`WEBULL`/`SOFI`); there is no "paper" member, and this module may not add one (it does
   not own `app.core.models`).** Every :class:`~app.core.models.Transaction` built here is stamped
   with a placeholder broker, defaulting to :data:`Broker.ROBINHOOD` -- the same choice
   `app.thesis.strategycard.build_tax_impact` already makes for its own synthetic ledger, kept for
   consistency. `Broker.WEBULL` was deliberately avoided: `app.core.lots.build_lots` special-cases it
   to raise `WarningKind.FEES_UNKNOWN` on every sale, because a real Webull export has no fee column at
   all. A paper fill's fees (`Fill.fees`) are always a real, fully-known figure computed from the
   mandate's own SEC/TAF/commission model (`PaperBroker._fees`), so tagging paper fills as Webull would
   raise a warning that misrepresents them as having an unknown fee when they do not.
2. **`Transaction.import_id`/`source_row` have no broker-CSV counterpart.** A paper fill was never a
   line in an imported file, so `import_id` is the constant :data:`PAPER_IMPORT_ID` and `source_row` /
   `replay_order` are assigned as the index of each fill in **this module's own deterministic
   chronological order** -- `(trade_date, session, order_id)`, imposed by :func:`fills_to_transactions`
   regardless of the order ``fills`` arrives in, so two calls with the same fills in different input
   orders still produce identical output.

**This is a calculation, not tax advice**, exactly as the real tax engine's own modules say of
themselves.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict

from app.core.lots import LotLedger, build_lots
from app.core.models import (
    Account,
    AccountType,
    Broker,
    Money,
    Quantity,
    TaxTreatment,
    Transaction,
    TxnAction,
)
from app.core.money import quantize_money
from app.paper.paperbroker import Fill
from app.tax.gains import realized_gains
from app.tax.models import GainsReport
from app.tax.washsale import WashSaleResult, apply_wash_sales

__all__ = [
    "DEFAULT_PAPER_ACCOUNT_ID",
    "PAPER_IMPORT_ID",
    "STATUTORY_LONG_TERM_RATE",
    "STATUTORY_SHORT_TERM_RATE",
    "PaperLedger",
    "PaperTaxSummary",
    "WashSaleFlag",
    "build_paper_ledger",
    "fills_to_transactions",
    "paper_account",
    "resolve_configured_rates",
    "summarize_paper_tax",
]

DEFAULT_PAPER_ACCOUNT_ID: Final[str] = "paper-desk"
"""Matches `app.paper.mandate.default_mandate().account_id` -- not imported from there (this module
owns none of `app.paper.mandate`'s file and must not depend on its being unchanged), just kept equal
by convention so a caller wiring this against the live desk gets a matching account id with no extra
plumbing."""

PAPER_IMPORT_ID: Final[str] = "paper-desk-synthetic"
"""`Transaction.import_id` is mandatory provenance pointing at a real imported file -- see
`app.core.models`'s module docstring, "every number in the UI can be walked back to a line in a CSV".
A paper fill has no such file; this constant is the explicit, greppable marker that a transaction
built by this module is synthetic, never a real import."""

#: Top federal ordinary-income bracket, and top federal long-term capital-gains bracket. Mirrors
#: `app.thesis.strategycard.SHORT_TERM_TAX_RATE` / `LONG_TERM_TAX_RATE` exactly (same values, same
#: rationale: a directional upper bound on tax cost for most filers, not any specific user's real
#: rate) -- defined independently here, as a plain constant, rather than imported from
#: `app.thesis.strategycard`, so this standalone paper-tax module does not pull in the unrelated
#: `app.thesis` package merely for two numbers.
STATUTORY_SHORT_TERM_RATE: Final[Decimal] = Decimal("0.37")
STATUTORY_LONG_TERM_RATE: Final[Decimal] = Decimal("0.20")


# ---------------------------------------------------------------------------
# Fill -> Transaction
# ---------------------------------------------------------------------------


def fills_to_transactions(
    fills: Sequence[Fill],
    *,
    account_id: str = DEFAULT_PAPER_ACCOUNT_ID,
    broker: Broker = Broker.ROBINHOOD,
) -> list[Transaction]:
    """Convert paper-broker fills into the canonical shape `app.core.lots.build_lots` consumes.

    Every fill becomes exactly one `BUY` or `SELL` `Transaction` -- see the module docstring for why
    no other `TxnAction` is ever produced. Fields are mapped verbatim where a fill has an equivalent:
    ``symbol`` (upper-cased, matching how `app.tax.washsale`'s equivalence table and
    `app.core.lots._instrument_key`'s symbol fallback both compare symbols), ``quantity``, ``price``,
    ``fees`` (real SEC/TAF/commission fees from `PaperBroker._fees`, never zero-as-unknown), and
    ``trade_date``. ``instrument_id`` is left unset: `PaperBroker` never resolves a CUSIP, and
    `app.core.lots._instrument_key` already falls back to the raw (here, upper-cased) symbol when
    ``instrument_id`` is ``None``, which is exactly the identity key a single-broker synthetic ledger
    needs.

    Sorted internally by ``(trade_date, session, order_id)`` before ``source_row``/``replay_order``
    are assigned as the resulting index -- **not** by the order ``fills`` was passed in. This is what
    makes the conversion, and everything built from it, independent of input ordering: the same set
    of fills produces the same `Transaction` list (and therefore the same lots, disposals, and tax
    figures) regardless of what order the caller happened to collect them in.

    Args:
        fills: Every fill to include. Typically `PaperBroker.fills` for one persona's run, or the
            concatenation of fills recovered from several `PaperBroker.to_state()` snapshots.
        account_id: The synthetic account every transaction is stamped with. Must match whatever
            `Account` a downstream call to `app.core.lots.build_lots` or
            `app.tax.washsale.apply_wash_sales` is given for this ledger -- see :func:`paper_account`.
        broker: The placeholder `Broker` value. See the module docstring's mapping-decision #1 for why
            the default is `Broker.ROBINHOOD`, never `Broker.WEBULL`.

    Returns:
        One `Transaction` per fill, in the deterministic chronological order described above.
    """
    ordered = sorted(fills, key=lambda fill: (fill.trade_date, fill.session, fill.order_id))

    transactions: list[Transaction] = []
    for index, fill in enumerate(ordered):
        action = TxnAction.BUY if fill.side == "buy" else TxnAction.SELL
        transactions.append(
            Transaction(
                txn_id=f"paper-fill-{account_id}-{fill.order_id}",
                import_id=PAPER_IMPORT_ID,
                source_row=index,
                replay_order=index,
                account_id=account_id,
                broker=broker,
                action=action,
                trade_date=fill.trade_date,
                symbol=fill.symbol.upper(),
                quantity=fill.quantity,
                price=fill.price,
                fees=fill.fees,
                description=(
                    f"paper desk fill: order {fill.order_id}, session {fill.session}, "
                    f"price_source={fill.price_source}"
                ),
                raw_code="paper_fill",
            )
        )
    return transactions


def paper_account(
    account_id: str = DEFAULT_PAPER_ACCOUNT_ID,
    *,
    broker: Broker = Broker.ROBINHOOD,
    label: str = "Paper desk (synthetic, not a real brokerage account)",
) -> Account:
    """The one synthetic `Account` the paper book's transactions are replayed against.

    Always `TaxTreatment.TAXABLE` and `AccountType.CASH` -- `PaperBroker` and
    `app.paper.mandate.default_mandate` model a cash account with settlement days, never a retirement
    one, and there is exactly one account because a paper-desk run has no notion of holding the same
    symbol split across multiple accounts.
    """
    return Account(
        account_id=account_id,
        broker=broker,
        label=label,
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=AccountType.CASH,
    )


# ---------------------------------------------------------------------------
# Ledger assembly
# ---------------------------------------------------------------------------


class PaperLedger(BaseModel):
    """The replayed, wash-sale-adjusted state for one set of paper fills.

    Bundles exactly what :func:`app.tax.gains.realized_gains` and any further reporting need:
    ``ledger`` (post :func:`~app.tax.washsale.apply_wash_sales` -- lots and disposals already carry
    any basis adjustment and holding-period toll), ``accounts`` (the single-entry mapping
    `realized_gains` requires), and ``wash_result`` (every triggered event, plus any `UnsettledPair`
    from the equivalence table -- see `app.tax.washsale`'s module docstring for what those are).
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, extra="forbid")

    ledger: LotLedger
    accounts: dict[str, Account]
    wash_result: WashSaleResult


def build_paper_ledger(
    fills: Sequence[Fill],
    *,
    account_id: str = DEFAULT_PAPER_ACCOUNT_ID,
    broker: Broker = Broker.ROBINHOOD,
) -> PaperLedger:
    """Replay paper fills into lots and disposals, then apply IRC §1091 -- the two real engine calls.

    This is the whole point of the module stated as code: `app.core.lots.build_lots` does the FIFO lot
    matching (identical to what a real broker import gets), and `app.tax.washsale.apply_wash_sales`
    mutates the resulting `ledger` in place exactly as it does for a real ledger -- see that
    function's own docstring for precisely what it writes and why it must run before any gain is
    classified. Neither is reimplemented here.

    Safe to call repeatedly on the same ``fills``: `build_lots` and `apply_wash_sales` are themselves
    deterministic pure functions over their inputs, and :func:`fills_to_transactions` already removed
    input-order as a source of variance.
    """
    transactions = fills_to_transactions(fills, account_id=account_id, broker=broker)
    accounts = {account_id: paper_account(account_id, broker=broker)}
    ledger = build_lots(transactions, accounts=accounts)
    wash_result = apply_wash_sales(ledger, accounts=accounts)
    return PaperLedger(ledger=ledger, accounts=accounts, wash_result=wash_result)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


class WashSaleFlag(BaseModel):
    """One triggered wash sale, in the shape the paper desk needs to display it.

    A thin projection of `app.tax.models.WashSaleEvent` -- see that class for the fuller detail
    (``replacement_lot_ids``, ``is_chained``, ...). ``repurchase_date`` is not a field
    `WashSaleEvent` carries directly; it is recovered here as the earliest ``acquired_date`` among the
    event's own replacement lots, i.e. the actual date shares were bought back that caused the
    disallowance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    loss_date: dt.date
    """The date the disallowed loss was realised -- `WashSaleEvent.sale_date`."""
    repurchase_date: dt.date | None
    """Earliest acquisition date among the matched replacement lots. `None` only if a replacement
    lot referenced by the event cannot be found in the ledger, which does not happen for a
    `WashSaleFlag` built from a `WashSaleResult` produced by the same `PaperLedger.ledger`."""
    quantity_sold: Quantity
    quantity_replaced: Quantity
    disallowed_amount: Money
    """Positive. Deferred, added to the replacement lot's basis (§1091) -- never the permanent,
    destroyed kind, since this module's ledger has no IRA. See ``permanently_disallowed``."""
    permanently_disallowed: bool
    """Always `False` here -- see the module docstring's third "does NOT model" bullet. Kept on the
    shape for parity with `WashSaleEvent`, not because this module can ever set it `True`."""
    disposal_id: str
    event_id: str


class PaperTaxSummary(BaseModel):
    """After-tax realised results for one paper-desk run, over one date range.

    ``gains`` is the full `app.tax.models.GainsReport` this summary was built from, kept on the shape
    so a caller that wants row-level detail (`GainsReport.rows`, one `GainRow` per disposal) does not
    have to recompute it.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, extra="forbid")

    account_id: str
    start: dt.date
    end: dt.date

    short_term_gain: Money
    long_term_gain: Money
    net_realized_gain: Money
    """``short_term_gain + long_term_gain`` -- `GainsReport.net_gain`, before tax."""

    disallowed_loss_total: Money
    """Ordinary (deferred) wash-sale disallowance over the range -- `GainsReport.disallowed_loss_total`."""
    permanently_disallowed_total: Money
    """Always zero here -- see :class:`WashSaleFlag.permanently_disallowed`."""

    wash_sales: tuple[WashSaleFlag, ...]
    """Every triggered event whose ``loss_date`` falls in ``[start, end]``, sorted the same way
    `app.tax.washsale.apply_wash_sales` sorts `WashSaleResult.events` -- by ``(sale_date, disposal_id,
    event_id)``."""

    short_term_rate: Decimal
    long_term_rate: Decimal
    rate_basis: str
    """``"explicit"`` when either rate passed to :func:`summarize_paper_tax` differs in value from
    this module's statutory defaults (:data:`STATUTORY_SHORT_TERM_RATE` /
    :data:`STATUTORY_LONG_TERM_RATE`); ``"statutory_upper_bound"`` when both rates equal those
    defaults, whether because the caller omitted them or explicitly passed the same values.
    :func:`summarize_paper_tax` never silently reads `app.config` -- see its own docstring and
    :func:`resolve_configured_rates`."""

    tax_owed: Money
    """``max(short_term_gain, 0) * short_term_rate + max(long_term_gain, 0) * long_term_rate``,
    quantized to cents. A net loss on either side contributes zero, never a rebate -- see the module
    docstring's capital-loss-limitation caveat."""
    after_tax_realized_gain: Money
    """``net_realized_gain - tax_owed``. The one figure the paper desk's cards do not show today."""

    gains: GainsReport


def summarize_paper_tax(
    fills: Sequence[Fill],
    *,
    account_id: str = DEFAULT_PAPER_ACCOUNT_ID,
    broker: Broker = Broker.ROBINHOOD,
    start: dt.date | None = None,
    end: dt.date | None = None,
    short_term_rate: Decimal = STATUTORY_SHORT_TERM_RATE,
    long_term_rate: Decimal = STATUTORY_LONG_TERM_RATE,
) -> PaperTaxSummary:
    """The one call a caller needs: realised gains, wash sales, and an after-tax figure for a paper
    book, computed entirely by the real tax engine.

    Args:
        fills: Every fill to summarise -- see :func:`fills_to_transactions`.
        account_id: The synthetic account id -- see :func:`paper_account`.
        broker: The placeholder `Broker` -- see the module docstring's mapping decision #1.
        start: Inclusive lower bound on ``disposed_date``. Defaults to the earliest ``fill.trade_date``
            across ``fills``.
        end: Inclusive upper bound on ``disposed_date``. Defaults to the latest ``fill.trade_date``.
            Passing ``fills=()`` with either bound left as `None` raises `ValueError`: there is no
            trade date to infer a range from, and defaulting to "today" would make the result depend
            on the wall clock, which nothing else in this module does.
        short_term_rate: Marginal rate applied to a positive short-term gain, as a fraction of 1
            (``0.24`` for 24%, never ``24``). Defaults to :data:`STATUTORY_SHORT_TERM_RATE`, the top
            federal bracket, used as a directional upper bound -- **not** silently read from
            `app.config.Settings.ordinary_income_tax_rate`. Call :func:`resolve_configured_rates`
            first and pass its result here if the user's actual configured rate should be used
            instead; see that function's docstring for why this module does not do so on its own.
        long_term_rate: Same as ``short_term_rate``, for a positive long-term gain. Defaults to
            :data:`STATUTORY_LONG_TERM_RATE`.

    Returns:
        A :class:`PaperTaxSummary`. Calling this twice with the same arguments returns an equal
        value every time -- no field depends on anything but the arguments given.
    """
    fills = list(fills)
    paper_ledger = build_paper_ledger(fills, account_id=account_id, broker=broker)

    if start is None or end is None:
        if not fills:
            raise ValueError(
                "cannot infer a date range from zero fills; pass start and end explicitly"
            )
        trade_dates = [fill.trade_date for fill in fills]
        if start is None:
            start = min(trade_dates)
        if end is None:
            end = max(trade_dates)
    if start > end:
        raise ValueError(f"start {start.isoformat()} is after end {end.isoformat()}")

    gains = realized_gains(paper_ledger.ledger, accounts=paper_ledger.accounts, start=start, end=end)

    # Detected by value, not identity: a caller who explicitly asks for exactly the statutory rate
    # is indistinguishable from one who let it default, and reporting "statutory_upper_bound" for
    # that case is the more conservative (and honest) of the two possible labels either way.
    explicit = short_term_rate != STATUTORY_SHORT_TERM_RATE or long_term_rate != STATUTORY_LONG_TERM_RATE
    rate_basis = "explicit" if explicit else "statutory_upper_bound"

    tax_owed = quantize_money(
        max(gains.short_term_gain, Decimal(0)) * short_term_rate
        + max(gains.long_term_gain, Decimal(0)) * long_term_rate
    )
    net_gain = gains.net_gain
    after_tax = net_gain - tax_owed

    lots_by_id = paper_ledger.ledger.lots_by_id()
    flags: list[WashSaleFlag] = []
    for event in paper_ledger.wash_result.events:
        if not (start <= event.sale_date <= end):
            continue
        repurchase_dates = [
            lots_by_id[lot_id].acquired_date
            for lot_id in event.replacement_lot_ids
            if lot_id in lots_by_id
        ]
        flags.append(
            WashSaleFlag(
                symbol=event.symbol,
                loss_date=event.sale_date,
                repurchase_date=min(repurchase_dates) if repurchase_dates else None,
                quantity_sold=event.quantity_sold,
                quantity_replaced=event.quantity_replaced,
                disallowed_amount=event.disallowed_loss,
                permanently_disallowed=event.permanently_disallowed,
                disposal_id=event.disposal_id,
                event_id=event.event_id,
            )
        )

    return PaperTaxSummary(
        account_id=account_id,
        start=start,
        end=end,
        short_term_gain=gains.short_term_gain,
        long_term_gain=gains.long_term_gain,
        net_realized_gain=net_gain,
        disallowed_loss_total=gains.disallowed_loss_total,
        permanently_disallowed_total=gains.permanently_disallowed_total,
        wash_sales=tuple(flags),
        short_term_rate=short_term_rate,
        long_term_rate=long_term_rate,
        rate_basis=rate_basis,
        tax_owed=tax_owed,
        after_tax_realized_gain=after_tax,
        gains=gains,
    )


# ---------------------------------------------------------------------------
# Optional config-reading convenience -- the one non-pure function in this module
# ---------------------------------------------------------------------------


def resolve_configured_rates(settings: object | None = None) -> tuple[Decimal, Decimal, str]:
    """Read the user's own configured tax rates, falling back to the statutory upper bound.

    **This is the one function in this module that is not a pure function of its arguments alone**
    when ``settings`` is omitted: it calls `app.config.get_settings()`, which reads process
    configuration (environment variables / `.env`). It exists as a separate, clearly-named function
    -- never called automatically by :func:`summarize_paper_tax` -- precisely so that the rest of this
    module keeps its "no global state" guarantee, and so a caller who *does* want the user's real
    bracket has to opt in explicitly by calling this first and passing its result on:

        >>> short_rate, long_rate, basis = resolve_configured_rates()
        >>> summary = summarize_paper_tax(
        ...     fills, short_term_rate=short_rate, long_term_rate=long_rate
        ... )

    Mirrors `app.thesis.strategycard.build_tax_impact`'s own fallback exactly: a rate is read from
    `Settings.ordinary_income_tax_rate` / `Settings.long_term_capital_gains_tax_rate` when the user has
    configured it, and only a bracket left unset there falls back to :data:`STATUTORY_SHORT_TERM_RATE`
    / :data:`STATUTORY_LONG_TERM_RATE`.

    Args:
        settings: An already-loaded `app.config.Settings`, for a caller that wants to avoid the
            process-wide singleton (tests, or a request handler that already has one). Defaults to
            `app.config.get_settings()`. Typed ``object`` here rather than importing `Settings` at
            module scope, so that importing this module -- almost all of which has nothing to do with
            `app.config` -- never has a reason to fail if that module's own import graph changes;
            the real type is enforced at the one call site inside this function.

    Returns:
        ``(short_term_rate, long_term_rate, rate_basis)`` where ``rate_basis`` is
        ``"user_configured"`` when both brackets came from ``settings``, or
        ``"statutory_upper_bound"`` when either one had to fall back.
    """
    from app.config import Settings, get_settings  # local import: see the `settings` arg docstring

    cfg: Settings = settings if isinstance(settings, Settings) else get_settings()

    used_fallback = False
    short_term_rate = cfg.ordinary_income_tax_rate
    if short_term_rate is None:
        resolved_short = STATUTORY_SHORT_TERM_RATE
        used_fallback = True
    else:
        resolved_short = Decimal(str(short_term_rate))

    long_term_rate = cfg.long_term_capital_gains_tax_rate
    if long_term_rate is None:
        resolved_long = STATUTORY_LONG_TERM_RATE
        used_fallback = True
    else:
        resolved_long = Decimal(str(long_term_rate))

    basis = "statutory_upper_bound" if used_fallback else "user_configured"
    return resolved_short, resolved_long, basis
