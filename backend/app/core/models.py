"""Canonical domain models.

Every broker export normalises into these shapes. Adapters are the only code that knows what a
Robinhood or Webull row looks like; everything downstream sees a :class:`Transaction`.

Two invariants are enforced here rather than by convention:

* **No floats.** The :data:`Money` and :data:`Quantity` annotations reject :class:`float` outright.
  Pydantic would happily coerce ``0.1`` into ``Decimal('0.1000000000000000055511151231257827021181583404541015625')``,
  and that error compounds through lot matching into a wrong tax figure.
* **Provenance is mandatory on transactions.** A :class:`Transaction` cannot be constructed without
  the import and row it came from, so every number in the UI can be walked back to a line in a CSV.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

__all__ = [
    "Account",
    "AccountType",
    "Broker",
    "CorporateAction",
    "CorporateActionType",
    "ImportRecord",
    "Instrument",
    "InstrumentKind",
    "Lot",
    "LotStatus",
    "Money",
    "Position",
    "Quantity",
    "TaxTreatment",
    "Transaction",
    "TxnAction",
]


def _reject_float(value: Any) -> Any:
    """Refuse binary floats in monetary and quantity fields."""
    if isinstance(value, float):
        raise ValueError(
            f"float {value!r} is not permitted in a monetary or quantity field; "
            "pass a Decimal or a string"
        )
    return value


Money = Annotated[Decimal, BeforeValidator(_reject_float)]
"""A currency amount. Rejects float at the boundary."""

Quantity = Annotated[Decimal, BeforeValidator(_reject_float)]
"""A share count. Decimal because fractional shares are pervasive in this data."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Broker(StrEnum):
    ROBINHOOD = "robinhood"
    WEBULL = "webull"
    SOFI = "sofi"


class TaxTreatment(StrEnum):
    """How gains in an account are taxed.

    Drives two distinct behaviours that must both hold: tax-advantaged accounts are excluded from
    taxable gain reporting, *and* they are still scanned for wash-sale replacement purchases, because
    a repurchase inside an IRA permanently disallows the loss (Rev. Rul. 2008-5).
    """

    TAXABLE = "taxable"
    ROTH_IRA = "roth_ira"
    TRADITIONAL_IRA = "traditional_ira"

    @property
    def is_tax_advantaged(self) -> bool:
        return self is not TaxTreatment.TAXABLE


class AccountType(StrEnum):
    """Settlement structure, orthogonal to tax treatment."""

    CASH = "cash"
    MARGIN = "margin"
    RETIREMENT = "retirement"


class AccountStatus(StrEnum):
    """Whether an account is still active. Orthogonal to tax treatment and account type."""

    OPEN = "open"
    CLOSED = "closed"


class InstrumentKind(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    ETN = "etn"
    CRYPTO = "crypto"
    PRIVATE = "private"
    """Pre-IPO vehicles such as SPCX. No reliable market quote exists."""
    CASH = "cash"
    UNKNOWN = "unknown"


class TxnAction(StrEnum):
    """Normalised transaction actions.

    Covers every code observed across the three brokers' real exports. Adapters map their native
    vocabulary onto this set and **raise on anything unrecognised** -- a silently dropped row is
    invisible in the UI and wrong in the tax output.
    """

    BUY = "buy"
    SELL = "sell"

    DIVIDEND = "dividend"
    INTEREST = "interest"
    STOCK_LENDING_INCOME = "stock_lending_income"
    """Robinhood ``SLIP``. Ordinary income, not a capital gain."""

    FEE = "fee"
    SUBSCRIPTION_FEE = "subscription_fee"
    """Robinhood ``GOLD``. Not deductible against capital gains."""

    TRANSFER_IN = "transfer_in"
    """Position arriving via ACAT. **Not** an acquisition: basis and holding period carry over."""
    TRANSFER_OUT = "transfer_out"
    """Position leaving via ACAT. **Not** a disposal: no taxable event."""

    CASH_IN = "cash_in"
    CASH_OUT = "cash_out"
    INTERNAL_TRANSFER = "internal_transfer"
    """Robinhood ``ITRF``: movement between the user's own accounts at the same broker."""

    IRA_MATCH = "ira_match"
    """Robinhood ``MTCH``: broker contribution to a retirement account."""

    SPLIT = "split"
    SPINOFF = "spinoff"

    ADJUSTMENT = "adjustment"
    MISC = "misc"

    @property
    def is_trade(self) -> bool:
        return self in (TxnAction.BUY, TxnAction.SELL)

    @property
    def is_position_transfer(self) -> bool:
        """True for ACAT position movements, which preserve basis and holding period."""
        return self in (TxnAction.TRANSFER_IN, TxnAction.TRANSFER_OUT)

    @property
    def affects_position(self) -> bool:
        """True when the lot engine must examine this action.

        ``INTERNAL_TRANSFER`` is included even though some ``ITRF`` rows move only cash. Robinhood
        uses the one code for both, so the replay cannot know which it has without looking; a
        cash-only row is then a no-op. Excluding the code here would silently skip the 65 ``ITRF``
        rows in this dataset, and the position-moving ones carry basis and holding period across
        accounts -- dropping those restarts a holding period and misstates the tax output.
        """
        return self in (
            TxnAction.BUY,
            TxnAction.SELL,
            TxnAction.TRANSFER_IN,
            TxnAction.TRANSFER_OUT,
            TxnAction.INTERNAL_TRANSFER,
            TxnAction.SPLIT,
            TxnAction.SPINOFF,
        )


class LotStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    PARTIAL = "partial"


class CorporateActionType(StrEnum):
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    SPINOFF = "spinoff"
    MERGER = "merger"
    SYMBOL_CHANGE = "symbol_change"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class ImportRecord(_Frozen):
    """One ingested file. The root of the provenance chain."""

    import_id: str
    source_path: str
    filename: str
    file_sha256: str
    """Raw bytes. Changes if the broker switches line endings without changing data."""
    content_hash: str
    """Parsed content. Stable across encoding and line-ending changes -- use this to detect a
    genuine re-import of the same data."""
    broker: Broker
    account_id: str
    adapter: str
    adapter_version: str
    row_count: int
    """Rows present in the file."""
    usable_row_count: int
    """Rows that became transactions. The gap is cancellations, footers and non-events, and it is a
    regression signal: Webull drops its cancelled and failed orders, SoFi its cancellations."""
    imported_at: dt.datetime


class Account(_Frozen):
    """A brokerage account. Eight of these exist across three brokers."""

    account_id: str
    broker: Broker
    label: str
    """Human name, e.g. ``"Roth IRA"``."""
    tax_treatment: TaxTreatment
    account_type: AccountType = AccountType.CASH
    status: AccountStatus = AccountStatus.OPEN

    @property
    def is_tax_advantaged(self) -> bool:
        return self.tax_treatment.is_tax_advantaged


class Instrument(_Frozen):
    """A tradeable instrument, identified by CUSIP where available.

    CUSIP is the identity key because it reconciles ``BRK.B`` (Robinhood) against ``BRK-B`` (Webull)
    and because wash-sale matching on ticker alone is wrong.
    """

    instrument_id: str
    primary_symbol: str
    cusip: str | None = None
    name: str | None = None
    kind: InstrumentKind = InstrumentKind.UNKNOWN
    is_priceable: bool = True
    """False for instruments with no reliable quote (SPCX, some crypto). Such holdings must surface
    as explicitly unpriced rather than silently valued at zero."""


class Transaction(_Frozen):
    """A single normalised ledger event.

    Provenance (``import_id`` + ``source_row``) is required. Any figure displayed anywhere in the
    application must be traceable back through these two fields to a line in a broker CSV.
    """

    txn_id: str
    import_id: str
    source_row: int
    """Zero-based row index within the source file, excluding the header. **Provenance only** -- it
    says which line this came from, never which event happened first. See :attr:`replay_order`."""
    replay_order: int = 0
    """Chronological rank within the source file, ascending = earlier.

    Distinct from :attr:`source_row` because a broker is free to write its export newest-first, and
    all three of these do. Assigned by the adapter, which is the only code that knows the file's
    direction -- see :class:`app.ingest.adapters.base.ExportOrder` for what reading it backwards
    cost. Not part of ``txn_id``: it orders replay, it does not identify a transaction, so correcting
    it never invalidates a stored row.
    """

    account_id: str
    broker: Broker
    action: TxnAction

    trade_date: dt.date
    settle_date: dt.date | None = None
    executed_at: dt.datetime | None = None
    """Timezone-aware execution time where the broker supplies one. Webull does; Robinhood and SoFi
    do not, which is why :attr:`replay_order` has to be right for them."""
    sequence: int = 0
    """Ordinal among a row's exact duplicates, for identity only -- see
    :class:`app.core.ids.TransactionSequencer`. Almost always ``0`` and never an ordering signal."""

    symbol: str | None = None
    """As written by the broker, before normalisation."""
    cusip: str | None = None
    instrument_id: str | None = None

    quantity: Quantity | None = None
    price: Money | None = None
    fees: Money = Decimal(0)
    amount: Money | None = None
    """Net cash effect, signed: negative for outflows."""

    currency: str = "USD"
    description: str | None = None
    transfer_group: str | None = None
    """ACAT ``control_num``. Links the per-symbol position rows to the cash row of one transfer."""
    raw_code: str | None = None
    """The broker's own code (``SLIP``, ``ACATI``, ...), retained for auditability."""

    @model_validator(mode="after")
    def _check_trade_completeness(self) -> Transaction:
        """A trade without quantity or symbol is a parse failure, not a valid transaction."""
        if self.action.is_trade:
            if self.quantity is None:
                raise ValueError(f"{self.action} transaction {self.txn_id} has no quantity")
            if self.quantity == 0:
                raise ValueError(f"{self.action} transaction {self.txn_id} has zero quantity")
            if not self.symbol:
                raise ValueError(f"{self.action} transaction {self.txn_id} has no symbol")
        return self


class Lot(BaseModel):
    """An acquisition parcel with its own basis and holding period.

    Mutable, unlike the other models: wash-sale processing adjusts basis and tolls the holding period
    in place during a rebuild. Lots are always derived -- never hand-edited, never persisted across a
    rebuild.
    """

    model_config = ConfigDict(extra="forbid")

    lot_id: str
    instrument_id: str
    account_id: str

    acquired_date: dt.date
    """Original acquisition. Survives ACAT transfers: a transferred lot keeps this date, because
    treating a transfer as a new purchase would restart the holding period."""
    acquired_txn_id: str

    quantity: Quantity
    remaining: Quantity
    cost_basis: Money
    """Total basis for ``quantity`` shares, inclusive of fees and any wash-sale adjustment."""

    wash_sale_adjustment: Money = Decimal(0)
    """Disallowed loss rolled into this lot's basis. Zero for lots that are not wash-sale replacements."""
    holding_period_start: dt.date | None = None
    """Set when a wash sale tolls the holding period, i.e. this lot inherits an earlier start than
    ``acquired_date``. ``None`` means the two coincide."""

    closed_date: dt.date | None = None
    status: LotStatus = LotStatus.OPEN

    @property
    def effective_holding_start(self) -> dt.date:
        """The date from which the holding period runs, accounting for wash-sale tolling."""
        return self.holding_period_start or self.acquired_date

    @property
    def basis_per_share(self) -> Decimal:
        """Unrounded. Rounding here would drift across partial disposals."""
        if self.quantity == 0:
            raise ZeroDivisionError(f"lot {self.lot_id} has zero quantity")
        return self.cost_basis / self.quantity


class Position(_Frozen):
    """A consolidated holding.

    Consolidation is across accounts by default. The same ticker can be held in several accounts
    across several brokers -- many symbols appear at more than one broker -- so per-account concentration
    badly understates exposure.
    """

    instrument_id: str
    symbol: str
    quantity: Quantity
    cost_basis: Money
    accounts: tuple[str, ...] = ()
    lot_ids: tuple[str, ...] = ()
    as_of: dt.date | None = None

    @property
    def average_cost(self) -> Decimal | None:
        if self.quantity == 0:
            return None
        return self.cost_basis / self.quantity


class CorporateAction(_Frozen):
    """A split, spinoff or symbol change requiring lot adjustment during replay."""

    action_id: str
    instrument_id: str
    kind: CorporateActionType
    effective_date: dt.date
    ratio: Decimal | None = Field(
        default=None,
        description="New shares per old share. 4-for-1 split is Decimal('4').",
    )
    new_symbol: str | None = None
    note: str | None = None
