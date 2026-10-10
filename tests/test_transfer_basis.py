"""Declared transfer basis: giving an inbound ACAT leg the cost basis its outbound counterpart
cannot supply, without inventing shares.

Two shapes seen in practice, both of which otherwise sell at zero basis (phantom gain):

* the sending account is not in the dataset at all (a Webull account never imported), so the inbound
  leg has no queue to draw from; and
* the sending account *is* in the dataset but the legs never pair -- a cross-broker ACAT where the
  outbound leg (SoFi) carries no ``transfer_group`` while the inbound leg carries the receiving
  broker's control number.

Both reduce to an inbound ``TRANSFER_IN`` reading an empty queue, and a :class:`TransferBasis`
declaration seeds exactly that queue. See app.core.lots.TransferBasis.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.core.lots import OpeningPosition, TransferBasis, WarningKind, build_lots
from app.core.models import Account, AccountType, Broker, TaxTreatment
from app.ingest.manifest import ManifestError, load_manifest
from tests.conftest import make_txn

RH = Account(
    account_id="rh-taxable",
    broker=Broker.ROBINHOOD,
    label="Robinhood Individual",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)
SOFI = Account(
    account_id="sofi-taxable",
    broker=Broker.SOFI,
    label="SoFi taxable",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)
ACCOUNTS = {a.account_id: a for a in (RH, SOFI)}


def _transfer(action: str, *, account_id: str, symbol: str, qty: str, date: dt.date, group=None):
    txn = make_txn(
        txn_id=f"{action}-{symbol}-{account_id}",
        account_id=account_id,
        broker=RH.broker if account_id == "rh-taxable" else SOFI.broker,
        action=action,
        symbol=symbol,
        quantity=qty,
        price=None,
        amount=None,
        trade_date=date,
    )
    return txn.model_copy(update={"transfer_group": group}) if group else txn


def _disposal(ledger, symbol: str):  # type: ignore[no-untyped-def]
    rows = [d for d in ledger.disposals if d.symbol == symbol]
    assert rows, f"no disposal for {symbol}"
    return rows


class TestSourceNotInDataset:
    """The Webull-into-Robinhood case: no outbound leg exists anywhere in the ledger."""

    def _txns(self):
        return [
            _transfer(
                "transfer_in",
                account_id="rh-taxable",
                symbol="QZMR",
                qty="150",
                date=dt.date(2026, 6, 18),
                group="20261670037489",
            ),
            make_txn(
                txn_id="sell-dram",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                action="sell",
                symbol="QZMR",
                quantity="150",
                price="76.95",
                trade_date=dt.date(2026, 6, 23),
            ),
        ]

    def test_without_declaration_it_is_a_zero_basis_phantom_gain(self) -> None:
        ledger = build_lots(self._txns(), accounts=ACCOUNTS)
        (disposal,) = _disposal(ledger, "QZMR")
        assert disposal.cost_basis == 0
        assert disposal.proceeds == Decimal("11542.50")
        assert any(w.kind is WarningKind.UNMATCHED_TRANSFER_IN for w in ledger.warnings)

    def test_declaration_supplies_the_carried_basis(self) -> None:
        declared = [
            TransferBasis(
                account_id="rh-taxable",
                symbol="QZMR",
                quantity=Decimal("150"),
                as_of=dt.date(2026, 6, 18),
                cost_basis=Decimal("10518.50"),
                acquired_date=dt.date(2026, 6, 12),
            )
        ]
        ledger = build_lots(self._txns(), accounts=ACCOUNTS, transfer_basis=declared)
        (disposal,) = _disposal(ledger, "QZMR")
        assert disposal.cost_basis == Decimal("10518.50")
        assert disposal.gain_loss == Decimal("1024.00")
        assert not any(w.kind is WarningKind.UNMATCHED_TRANSFER_IN for w in ledger.warnings)


class TestSourcePresentButUnpaired:
    """The SoFi-into-Robinhood case: the outbound leg exists but carries no group, so the legs never
    pair. The declaration must both supply basis and not conjure extra shares."""

    def _txns(self):
        return [
            make_txn(
                txn_id="buy-spcx",
                account_id="sofi-taxable",
                broker=Broker.SOFI,
                action="buy",
                symbol="XPCX",
                quantity="31",
                price="100.00",
                trade_date=dt.date(2026, 6, 12),
            ),
            _transfer(
                "transfer_out",
                account_id="sofi-taxable",
                symbol="XPCX",
                qty="31",
                date=dt.date(2026, 6, 19),  # no group -- this is why the legs never pair
            ),
            _transfer(
                "transfer_in",
                account_id="rh-taxable",
                symbol="XPCX",
                qty="31",
                date=dt.date(2026, 6, 18),
                group="20261670037489",
            ),
            make_txn(
                txn_id="sell-spcx",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                action="sell",
                symbol="XPCX",
                quantity="31",
                price="120.00",
                trade_date=dt.date(2026, 6, 20),
            ),
        ]

    def _held(self, ledger, account_id, symbol):  # type: ignore[no-untyped-def]
        return sum(
            (
                lot.remaining
                for lot in ledger.lots_by_id().values()
                if lot.account_id == account_id
                and ledger.symbols.get(lot.instrument_id, lot.instrument_id) == symbol
            ),
            Decimal(0),
        )

    def test_declaration_carries_basis_and_conserves_shares(self) -> None:
        declared = [
            TransferBasis(
                account_id="rh-taxable",
                symbol="XPCX",
                quantity=Decimal("31"),
                as_of=dt.date(2026, 6, 18),
                cost_basis=Decimal("3100.00"),
            )
        ]
        plain = build_lots(self._txns(), accounts=ACCOUNTS)
        seeded = build_lots(self._txns(), accounts=ACCOUNTS, transfer_basis=declared)

        (plain_sale,) = _disposal(plain, "XPCX")
        assert plain_sale.cost_basis == 0  # unpaired -> phantom without the declaration

        (sale,) = _disposal(seeded, "XPCX")
        assert sale.cost_basis == Decimal("3100.00")
        assert sale.gain_loss == Decimal("620.00")

        # No shares invented: SoFi emptied by its outbound leg, Robinhood emptied by the sale,
        # identical with and without the declaration.
        for ledger in (plain, seeded):
            assert self._held(ledger, "sofi-taxable", "XPCX") == 0
            assert self._held(ledger, "rh-taxable", "XPCX") == 0


class TestDeclarationMatching:
    def test_a_declaration_that_matches_no_inbound_leg_is_inert(self) -> None:
        txns = [
            _transfer(
                "transfer_in",
                account_id="rh-taxable",
                symbol="QZMR",
                qty="150",
                date=dt.date(2026, 6, 18),
            ),
            make_txn(
                txn_id="sell-dram",
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                action="sell",
                symbol="QZMR",
                quantity="150",
                price="76.95",
                trade_date=dt.date(2026, 6, 23),
            ),
        ]
        # Right symbol/account, wrong date -> matches nothing, so the lot stays unbased.
        declared = [
            TransferBasis(
                account_id="rh-taxable",
                symbol="QZMR",
                quantity=Decimal("150"),
                as_of=dt.date(2026, 6, 17),
                cost_basis=Decimal("10518.50"),
            )
        ]
        ledger = build_lots(txns, accounts=ACCOUNTS, transfer_basis=declared)
        (disposal,) = _disposal(ledger, "QZMR")
        assert disposal.cost_basis == 0


class TestManifestParsing:
    _ACCOUNT = (
        '[[account]]\n'
        'file = "RH.csv"\n'
        'account_id = "rh-taxable"\n'
        'label = "RH"\n'
        'tax_treatment = "taxable"\n'
        'account_type = "cash"\n'
    )

    def _write(self, tmp_path, body: str):  # type: ignore[no-untyped-def]
        path = tmp_path / "accounts.toml"
        path.write_text(self._ACCOUNT + body, encoding="utf-8")
        return path

    def test_valid_transfer_basis_round_trips(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = self._write(
            tmp_path,
            "\n[[transfer_basis]]\n"
            'account_id = "rh-taxable"\n'
            'symbol = "QZMR"\n'
            'quantity = "150"\n'
            "as_of = 2026-06-18\n"
            "acquired_date = 2026-06-12\n"
            'cost_basis = "10518.50"\n'
            'note = "ACAT in from Webull"\n',
        )
        manifest = load_manifest(path)
        assert len(manifest.transfer_bases) == 1
        tb = manifest.transfer_bases[0]
        assert (tb.account_id, tb.symbol, tb.quantity) == ("rh-taxable", "QZMR", Decimal("150"))
        assert tb.cost_basis == Decimal("10518.50")
        assert tb.as_of == dt.date(2026, 6, 18)
        assert tb.acquired_date == dt.date(2026, 6, 12)

    def test_cost_basis_is_required(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = self._write(
            tmp_path,
            "\n[[transfer_basis]]\n"
            'account_id = "rh-taxable"\n'
            'symbol = "QZMR"\n'
            'quantity = "150"\n'
            "as_of = 2026-06-18\n",
        )
        with pytest.raises(ManifestError, match="cost_basis"):
            load_manifest(path)

    def test_duplicate_account_symbol_date_is_fatal(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        entry = (
            "\n[[transfer_basis]]\n"
            'account_id = "rh-taxable"\n'
            'symbol = "QZMR"\n'
            'quantity = "150"\n'
            "as_of = 2026-06-18\n"
            'cost_basis = "10518.50"\n'
        )
        path = self._write(tmp_path, entry + entry)
        with pytest.raises(ManifestError, match="more than one transfer basis"):
            load_manifest(path)

    def test_unknown_account_is_fatal(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = self._write(
            tmp_path,
            "\n[[transfer_basis]]\n"
            'account_id = "nope"\n'
            'symbol = "QZMR"\n'
            'quantity = "150"\n'
            "as_of = 2026-06-18\n"
            'cost_basis = "10518.50"\n',
        )
        with pytest.raises(ManifestError, match="no \\[\\[account\\]\\] entry describes"):
            load_manifest(path)


def test_opening_position_and_transfer_basis_coexist() -> None:
    """A sanity check that the two declaration kinds do not interfere in one build."""
    txns = [
        _transfer(
            "transfer_in",
            account_id="rh-taxable",
            symbol="QZMR",
            qty="150",
            date=dt.date(2026, 6, 18),
        ),
        make_txn(
            txn_id="sell-dram",
            account_id="rh-taxable",
            broker=Broker.ROBINHOOD,
            action="sell",
            symbol="QZMR",
            quantity="150",
            price="76.95",
            trade_date=dt.date(2026, 6, 23),
        ),
    ]
    opening = [
        OpeningPosition(
            account_id="rh-taxable",
            symbol="GLD",
            quantity=Decimal("5"),
            as_of=dt.date(2026, 1, 5),
            cost_basis=Decimal("2000.00"),
        )
    ]
    declared = [
        TransferBasis(
            account_id="rh-taxable",
            symbol="QZMR",
            quantity=Decimal("150"),
            as_of=dt.date(2026, 6, 18),
            cost_basis=Decimal("10518.50"),
        )
    ]
    ledger = build_lots(txns, accounts=ACCOUNTS, opening=opening, transfer_basis=declared)
    (disposal,) = [d for d in ledger.disposals if d.symbol == "QZMR"]
    assert disposal.cost_basis == Decimal("10518.50")
