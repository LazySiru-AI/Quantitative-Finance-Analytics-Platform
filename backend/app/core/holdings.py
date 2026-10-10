"""Holdings aggregation: open lots -> current positions, across accounts.

Pure aggregation over a :class:`~app.core.lots.LotLedger`, mirroring how :mod:`app.tax.gains` sits
over the same ledger to produce realised-gains figures. This module produces the complementary,
unrealised, currently-held picture instead: what is still open, rolled up per instrument across
every account.

No I/O, no network, no pricing. Pricing is a boundary concern (a daily-bar-store lookup per symbol,
which can fail per symbol) and belongs to the API layer that calls this module, exactly as
:mod:`app.tax.engine` composes :mod:`app.tax.gains` with the ledger read from SQLite rather than
that module doing its own reads.

**Term classification reuses :func:`app.tax.gains.classify_term`** rather than re-implementing the
short/long anniversary rule. It is called with ``as_of`` in the ``disposed_date`` slot: "held more
than one year as of today" is exactly the same anniversary comparison as "held more than one year as
of the sale date", against the same possibly wash-sale-tolled
:attr:`~app.core.models.Lot.effective_holding_start` in both cases.

**Warning propagation is position-scoped, not lot-scoped**, for both ``basis_uncertain`` and
``fees_unknown``: an open lot is flagged if *any* warning of the relevant kind was raised anywhere
against its ``(account_id, instrument_id)`` pair, not only if a warning names that lot's own
transaction. This mirrors the deliberate over-scoping :mod:`app.tax.gains` already applies to
``WarningKind.UNMATCHED_TRANSFER_IN`` (see that module's docstring) and extends it uniformly to
``FEES_UNKNOWN``: both warning kinds are in practice raised only against ``SELL`` transactions
(an unmatched *inbound* transfer aside), so a currently open lot can never carry one on its own
acquisition -- the only way a still-held position can honestly reflect "this account/instrument had
a data-quality problem" is by looking at the position it belongs to, not the individual lot.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.core.lots import LotLedger, WarningKind
from app.core.models import Account, Lot
from app.tax.gains import classify_term
from app.tax.models import HoldingTerm

__all__ = ["AccountHolding", "InstrumentHolding", "build_positions"]

#: Warning kinds that mean some part of a position's cost basis was invented rather than
#: established -- an unmatched ACAT leg opened at zero basis, or a disposal (of shares since sold)
#: drew on such a lot. Either one means the account/instrument pair has at least one lot whose basis
#: cannot be trusted.
_BASIS_UNCERTAIN_KINDS = frozenset({WarningKind.MISSING_BASIS, WarningKind.UNMATCHED_TRANSFER_IN})

#: Fees, not basis -- kept separate exactly as `app.tax.gains` keeps them separate. See that
#: module's `_FEES_UNKNOWN_KINDS` docstring: a position can have a fully known basis and still carry
#: this flag, or vice versa.
_FEES_UNKNOWN_KINDS = frozenset({WarningKind.FEES_UNKNOWN})


@dataclass(frozen=True)
class AccountHolding:
    """One instrument's open position within one account."""

    account_id: str
    account_label: str
    broker: str
    quantity: Decimal
    cost_basis: Decimal
    lot_count: int
    basis_uncertain: bool
    fees_unknown: bool


@dataclass(frozen=True)
class InstrumentHolding:
    """One instrument's open position, rolled up across every account that holds it."""

    instrument_id: str
    symbol: str
    quantity: Decimal
    cost_basis: Decimal
    short_term_quantity: Decimal
    long_term_quantity: Decimal
    earliest_acquired: dt.date
    latest_acquired: dt.date
    lot_count: int
    basis_uncertain: bool
    fees_unknown: bool
    wash_sale_adjustment: Decimal
    """Total wash-sale-disallowed loss embedded in the *remaining* shares' basis, prorated per lot
    by ``remaining / quantity`` -- a partially sold lot only carries forward the adjustment
    proportional to what is still held, not the whole adjustment that applied when the lot was
    whole."""
    accounts: tuple[AccountHolding, ...]

    @property
    def basis_per_share(self) -> Decimal:
        if self.quantity == 0:
            raise ZeroDivisionError(f"position {self.instrument_id!r} has zero quantity")
        return self.cost_basis / self.quantity


def _flagged_keys(ledger: LotLedger, kinds: frozenset[WarningKind]) -> set[tuple[str, str]]:
    """``(account_id, instrument_id)`` pairs carrying a warning of one of ``kinds``.

    Every :class:`~app.core.lots.WarningKind` in either kind set this module consults is always
    raised with a concrete ``instrument_id`` (never ``None``) -- see the raise sites in
    :func:`app.core.lots.build_lots` -- so the ``None`` filter below is defensive rather than
    load-bearing.
    """
    return {
        (warning.account_id, warning.instrument_id)
        for warning in ledger.warnings
        if warning.kind in kinds and warning.instrument_id is not None
    }


def build_positions(
    ledger: LotLedger,
    *,
    accounts: Mapping[str, Account],
    as_of: dt.date,
) -> list[InstrumentHolding]:
    """Roll open lots up into one :class:`InstrumentHolding` per instrument.

    Args:
        ledger: A replayed ledger. Pass one that has already been through
            :func:`app.tax.washsale.apply_wash_sales` if wash-sale tolling and basis adjustment
            should be reflected -- this function only reads what is already on the lots, it does not
            run the wash-sale pass itself (same division of labour as :mod:`app.tax.gains`).
        accounts: ``account_id`` -> account, for the label and broker shown per account and to
            resolve every lot's tax-advantaged status is *not* needed here (unlike
            :func:`app.tax.gains.realized_gains`, holdings are not restricted to taxable accounts --
            a user's IRA holdings are real holdings).
        as_of: The date term classification is measured against. Pass the ledger's last transaction
            date, not "today" -- a stale portfolio should classify terms as of the data it actually
            has, not the wall clock.

    Returns:
        Positions for every instrument with at least one open lot (``remaining > 0``), sorted by
        symbol. An instrument with no open lots produces no entry at all -- there is nothing to
        divide zero quantity by, and nothing for a user to see.
    """
    open_lots = ledger.open_lots()

    basis_uncertain_keys = _flagged_keys(ledger, _BASIS_UNCERTAIN_KINDS)
    fees_unknown_keys = _flagged_keys(ledger, _FEES_UNKNOWN_KINDS)

    by_instrument: dict[str, list[Lot]] = defaultdict(list)
    for lot in open_lots:
        by_instrument[lot.instrument_id].append(lot)

    holdings: list[InstrumentHolding] = []
    for instrument_id, lots in by_instrument.items():
        symbol = ledger.symbols.get(instrument_id, instrument_id)

        by_account: dict[str, list[Lot]] = defaultdict(list)
        for lot in lots:
            by_account[lot.account_id].append(lot)

        account_holdings: list[AccountHolding] = []
        for account_id, account_lots in sorted(by_account.items()):
            account = accounts.get(account_id)
            if account is None:
                raise KeyError(
                    f"no account for id {account_id!r}; cannot build holdings for instrument "
                    f"{instrument_id!r}"
                )
            quantity = sum((lot.remaining for lot in account_lots), Decimal(0))
            cost_basis = sum(
                (lot.basis_per_share * lot.remaining for lot in account_lots), Decimal(0)
            )
            key = (account_id, instrument_id)
            account_holdings.append(
                AccountHolding(
                    account_id=account_id,
                    account_label=account.label,
                    broker=account.broker.value,
                    quantity=quantity,
                    cost_basis=cost_basis,
                    lot_count=len(account_lots),
                    basis_uncertain=key in basis_uncertain_keys,
                    fees_unknown=key in fees_unknown_keys,
                )
            )

        quantity = sum((lot.remaining for lot in lots), Decimal(0))
        cost_basis = sum((lot.basis_per_share * lot.remaining for lot in lots), Decimal(0))
        short_qty = Decimal(0)
        long_qty = Decimal(0)
        wash_adjustment = Decimal(0)
        for lot in lots:
            term = classify_term(lot.effective_holding_start, as_of)
            if term is HoldingTerm.SHORT:
                short_qty += lot.remaining
            else:
                long_qty += lot.remaining
            if lot.quantity != 0:
                wash_adjustment += lot.wash_sale_adjustment * (lot.remaining / lot.quantity)

        holdings.append(
            InstrumentHolding(
                instrument_id=instrument_id,
                symbol=symbol,
                quantity=quantity,
                cost_basis=cost_basis,
                short_term_quantity=short_qty,
                long_term_quantity=long_qty,
                earliest_acquired=min(lot.acquired_date for lot in lots),
                latest_acquired=max(lot.acquired_date for lot in lots),
                lot_count=len(lots),
                basis_uncertain=any(ah.basis_uncertain for ah in account_holdings),
                fees_unknown=any(ah.fees_unknown for ah in account_holdings),
                wash_sale_adjustment=wash_adjustment,
                accounts=tuple(account_holdings),
            )
        )

    holdings.sort(key=lambda h: h.symbol)
    return holdings
