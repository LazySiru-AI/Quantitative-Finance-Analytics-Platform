"""Audit the opening-position cost bases a report is built on, for two silent-failure patterns.

:func:`app.core.lots.build_lots` already warns loudly when an opening position is declared with **no**
cost basis (:data:`app.core.lots.WarningKind.MISSING_BASIS`): the lot opens at zero basis and any gain
against it is a bound, not a figure. Two things it cannot catch, both of which this module reports so
that every figure resting on an assumption rather than a fill is visible in one place:

* :class:`SuspectBasis` -- an opening lot whose declared basis sits within a dollar of the proceeds of
  the sale that closed it **and carries no note explaining why**. A basis reverse-engineered to
  proceeds reports ~$0 gain while hiding whatever the true gain or loss was, and passes every existing
  check (present, positive, plausible). The note gate matters: on a real ledger *every*
  basis-near-proceeds lot was legitimate and documented -- broker-reported transfer bases on near-flat
  leveraged-ETF round-trips, and estimate-to-silence-the-warning lots on tax-neutral IRA
  shortfalls (each annotated as an estimate). Flagging those would be noise, so
  a documented basis is trusted and only an *undocumented* coincidence with proceeds is surfaced.
  Scoped to **opening** lots regardless: a genuine intraday round-trip bought and sold near flat has
  basis ~= proceeds too and is not a defect.
* :class:`UnbasedDisposal` -- a realised disposal that booked its entire proceeds as gain because the
  lot behind it had zero basis (a ``cost_basis``-less opening, an oversold shortfall, or an unmatched
  transfer in). The proceeds *are* the overstatement, and this is where the real, tax-relevant work
  is: on a real ledger this was a large phantom gain across the taxable accounts, awaiting basis
  from the 1099-Bs.

Everything here is derived, never stored, and reads the same merged/canonicalized ledger the tax
report does. **It reconciles a calculation against itself; it is not tax advice.**
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.core.canonical import canonicalize_ledger
from app.core.ids import stable_id
from app.core.lots import (
    Disposal,
    LotLedger,
    LotMethod,
    OpeningPosition,
    TransferBasis,
    build_lots,
)
from app.core.lots import _resolve_opening_keys as resolve_opening_keys
from app.core.models import Account, Money, Transaction
from app.core.money import quantize_money
from app.db import sqlite as ledger_store

__all__ = [
    "BasisAuditReport",
    "SuspectBasis",
    "UnbasedDisposal",
    "audit_basis",
    "audit_basis_from_ledger",
    "format_report",
    "main",
]

#: A declared opening basis reads as "reverse-engineered to proceeds" when it lands within this band
#: of the proceeds of the disposals that closed the lot. Absolute floor plus a relative term so it
#: holds across a $500 lot and a $50,000 one; deliberately tight -- a legitimate pre-window lot
#: matching its own sale price to 0.15% with no note explaining the coincidence is what this looks for.
_SUSPECT_ABS: Money = Decimal("2.00")
_SUSPECT_REL: Decimal = Decimal("0.0015")


@dataclass(frozen=True)
class SuspectBasis:
    """An opening lot whose *undocumented* declared basis is within a dollar of its sale proceeds.

    A note on the opening position (recording where the basis came from -- a broker transfer figure,
    an explicit estimate) clears the suspicion: the coincidence is then explained. This flags only the
    unexplained case, where a basis equal to proceeds most likely means it was set *from* the proceeds.
    """

    account_id: str
    symbol: str
    quantity: Decimal
    declared_basis: Money
    proceeds: Money
    is_tax_advantaged: bool

    @property
    def gap(self) -> Money:
        """How far declared basis sits from proceeds -- near zero is the whole tell."""
        return quantize_money(abs(self.proceeds - self.declared_basis))


@dataclass(frozen=True)
class UnbasedDisposal:
    """A realised disposal that booked its full proceeds as gain because its lot had no basis."""

    account_id: str
    symbol: str
    quantity: Decimal
    proceeds: Money
    is_tax_advantaged: bool
    declared_opening: bool
    """True when a ``cost_basis``-less opening position was declared for this (account, symbol);
    False when the zero-basis lot was invented by the replay (an oversold shortfall or a transfer in
    the export never showed being funded), which is undeclared and easy to miss entirely."""

    @property
    def phantom_gain(self) -> Money:
        """The overstatement: the entire proceeds are counted as gain against zero basis."""
        return quantize_money(self.proceeds)


@dataclass(frozen=True)
class BasisAuditReport:
    """Every figure in the ledger that rests on an assumed basis rather than a real fill."""

    suspect: tuple[SuspectBasis, ...]
    unbased: tuple[UnbasedDisposal, ...]

    @property
    def phantom_gain_taxable(self) -> Money:
        """Total proceeds booked at zero basis in **taxable** accounts -- the tax-relevant overstatement."""
        return quantize_money(
            sum((r.phantom_gain for r in self.unbased if not r.is_tax_advantaged), Decimal(0))
        )

    @property
    def phantom_gain_tax_advantaged(self) -> Money:
        """Same, in tax-advantaged accounts: wrong P&L display, no tax consequence."""
        return quantize_money(
            sum((r.phantom_gain for r in self.unbased if r.is_tax_advantaged), Decimal(0))
        )

    @property
    def suspect_proceeds_taxable(self) -> Money:
        """Proceeds of suspect-basis lots in taxable accounts -- the gain/loss possibly hidden sits here."""
        return quantize_money(
            sum((r.proceeds for r in self.suspect if not r.is_tax_advantaged), Decimal(0))
        )

    @property
    def is_clean(self) -> bool:
        return not self.suspect and not self.unbased


def _is_near_proceeds(proceeds: Money, declared_basis: Money) -> bool:
    if proceeds <= 0:
        return False
    band = max(_SUSPECT_ABS, proceeds * _SUSPECT_REL)
    return abs(proceeds - declared_basis) <= band


def audit_basis(
    ledger: LotLedger,
    *,
    accounts: Mapping[str, Account],
    opening: Sequence[OpeningPosition],
    transactions: Sequence[Transaction],
) -> BasisAuditReport:
    """Audit an already-built ledger against the opening positions it was built from.

    ``transactions`` must be the same (canonicalized) sequence passed to
    :func:`app.core.lots.build_lots`, because opening lots are located by re-deriving their id the
    way ``build_lots`` did -- through the account's own rows -- rather than by guessing a symbol key.
    """
    tax_adv = {aid: acct.is_tax_advantaged for aid, acct in accounts.items()}

    # Locate each opening lot by reconstructing the deterministic id build_lots assigned it, so the
    # near-proceeds test can compare a lot's declared basis against exactly the disposals that drew
    # from it (not every disposal in that symbol, which would fold in-window round-trips into it).
    disposals_by_lot: dict[str, list[Disposal]] = {}
    for disposal in ledger.disposals:
        disposals_by_lot.setdefault(disposal.lot_id, []).append(disposal)

    suspect: list[SuspectBasis] = []
    declared_unbased_keys: set[tuple[str, str]] = set()
    for (account_id, instrument_key), position in resolve_opening_keys(opening, transactions):
        symbol = position.symbol.upper()
        if position.cost_basis is None:
            declared_unbased_keys.add((account_id, symbol))
            continue
        # A documented basis is trusted -- the note is where it came from. Only an unexplained basis
        # that happens to equal proceeds is suspicious.
        if (position.note or "").strip():
            continue
        opening_lot_id = stable_id(
            "opening-lot", account_id, instrument_key, str(position.as_of)
        )
        closed = disposals_by_lot.get(opening_lot_id, [])
        proceeds = quantize_money(sum((d.proceeds for d in closed), Decimal(0)))
        sold_qty = sum((d.quantity for d in closed), Decimal(0))
        declared_basis = quantize_money(position.cost_basis)
        if sold_qty > 0 and _is_near_proceeds(proceeds, declared_basis):
            suspect.append(
                SuspectBasis(
                    account_id=account_id,
                    symbol=symbol,
                    quantity=sold_qty,
                    declared_basis=declared_basis,
                    proceeds=proceeds,
                    is_tax_advantaged=tax_adv.get(account_id, False),
                )
            )

    # Ledger-wide phantom gain: every realised disposal whose lot carried zero basis, whatever opened
    # it. Aggregated per (account, symbol) so several disposals of one symbol read as one line.
    unbased_acc: dict[tuple[str, str], list[Decimal]] = {}
    for disposal in ledger.disposals:
        if disposal.cost_basis == 0 and disposal.proceeds > 0:
            key = (disposal.account_id, disposal.symbol.upper())
            unbased_acc.setdefault(key, [Decimal(0), Decimal(0)])
            unbased_acc[key][0] += disposal.quantity
            unbased_acc[key][1] += disposal.proceeds

    unbased: list[UnbasedDisposal] = []
    for (account_id, symbol), (qty, proceeds) in unbased_acc.items():
        unbased.append(
            UnbasedDisposal(
                account_id=account_id,
                symbol=symbol,
                quantity=qty,
                proceeds=quantize_money(proceeds),
                is_tax_advantaged=tax_adv.get(account_id, False),
                declared_opening=(account_id, symbol) in declared_unbased_keys,
            )
        )

    suspect.sort(key=lambda r: (not r.is_tax_advantaged, -r.proceeds, r.account_id, r.symbol))
    unbased.sort(key=lambda r: (r.is_tax_advantaged, -r.proceeds, r.account_id, r.symbol))
    return BasisAuditReport(suspect=tuple(suspect), unbased=tuple(unbased))


def audit_basis_from_ledger(
    conn: sqlite3.Connection,
    *,
    opening: Sequence[OpeningPosition] = (),
    transfer_basis: Sequence[TransferBasis] = (),
    method: LotMethod = LotMethod.FIFO,
) -> BasisAuditReport:
    """Load the ledger from SQLite, replay it exactly as the tax report does, and audit the bases.

    Mirrors :func:`app.tax.engine.report_from_ledger` up to (and including) canonicalization, because
    an audit run against un-canonicalized transactions would resolve opening keys differently from the
    report it is meant to be checking.
    """
    accounts = {account.account_id: account for account in ledger_store.fetch_accounts(conn)}
    instruments = {
        instrument.instrument_id: instrument
        for instrument in ledger_store.fetch_instruments(conn)
    }
    transactions = [
        ledger_store.transaction_from_row(row) for row in ledger_store.fetch_transactions(conn)
    ]
    transactions, instruments = canonicalize_ledger(transactions, instruments)
    ledger = build_lots(
        transactions,
        accounts=accounts,
        instruments=instruments,
        method=method,
        opening=opening,
        transfer_basis=transfer_basis,
    )
    return audit_basis(
        ledger, accounts=accounts, opening=opening, transactions=transactions
    )


def format_report(report: BasisAuditReport) -> str:
    """A plain-text rendering for the CLI. Money is already quantized on the report objects."""
    lines: list[str] = []
    lines.append("=== Opening-basis audit ===")
    if report.is_clean:
        lines.append("No undocumented near-proceeds bases and no unbased disposals found.")
        return "\n".join(lines)

    lines.append("")
    lines.append(
        f"Suspect basis (undocumented, declared ~= proceeds -> ~$0 gain): {len(report.suspect)}"
    )
    if report.suspect:
        lines.append(f"  {'account':14}{'sym':8}{'qty':>8}{'declared':>12}{'proceeds':>12}  tax?")
        for r in report.suspect:
            tag = "ROTH" if r.is_tax_advantaged else "TAX"
            lines.append(
                f"  {r.account_id:14}{r.symbol:8}{r.quantity:>8}"
                f"{r.declared_basis:>12}{r.proceeds:>12}  {tag}"
            )
        lines.append(
            f"  taxable proceeds possibly hiding a true gain/loss: ${report.suspect_proceeds_taxable}"
        )

    lines.append("")
    lines.append(
        f"Unbased disposals (proceeds booked at $0 basis = phantom gain): {len(report.unbased)}"
    )
    if report.unbased:
        lines.append(f"  {'account':14}{'sym':8}{'qty':>8}{'proceeds':>12}  tax?  declared-opening?")
        for u in report.unbased:
            tag = "ROTH" if u.is_tax_advantaged else "TAX"
            dec = "yes" if u.declared_opening else "NO (oversold/transfer)"
            lines.append(
                f"  {u.account_id:14}{u.symbol:8}{u.quantity:>8}{u.proceeds:>12}  {tag:4}  {dec}"
            )
    lines.append("")
    lines.append(f"TOTAL phantom gain (taxable)         : ${report.phantom_gain_taxable}")
    lines.append(f"TOTAL phantom gain (tax-advantaged)  : ${report.phantom_gain_tax_advantaged}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m app.tax.basis_audit`` -- print the audit for the configured ledger.

    Loads opening positions from the same manifest the ingest and tax paths use, so the audit sees
    exactly the declarations the report is built on. With ``--strict`` the exit code is ``1`` when
    anything is flagged, so the command is usable as a CI/pre-commit guard against an undocumented
    near-proceeds basis or a new unbased lot slipping in.
    """
    import argparse

    from app.config import get_settings
    from app.datasource import ledger_db_path
    from app.db import sqlite as sqlite_conn
    from app.ingest.manifest import load_declarations

    parser = argparse.ArgumentParser(
        prog="python -m app.tax.basis_audit",
        description="Audit opening-position cost bases for undocumented near-proceeds bases and "
        "unbased ($0-basis) lots.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if anything is flagged (for CI/pre-commit).",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    ledger_file = ledger_db_path(settings)
    if not ledger_file.exists():
        print("no ledger yet; import broker exports first")
        return 1
    manifest = load_declarations(settings)
    opening = manifest.opening_positions if manifest else ()
    transfer_basis = manifest.transfer_bases if manifest else ()
    with sqlite_conn.connect(ledger_file, read_only=True) as conn:
        report = audit_basis_from_ledger(conn, opening=opening, transfer_basis=transfer_basis)
    print(format_report(report))
    return 1 if (args.strict and not report.is_clean) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
