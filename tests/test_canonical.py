"""Cross-broker instrument identity (``app.core.canonical``) -- the wash-sale tax-correctness fix.

``app.core.ids.instrument_id`` keys on CUSIP when a broker supplies one and falls back to the
normalised symbol otherwise. Robinhood supplies CUSIPs; Webull does not. One security held at both
brokers therefore gets two ``instrument_id`` values until something merges them, and
``app.tax.washsale`` matches wash sales on ``instrument_id`` -- so every cross-broker wash-sale pair
for a split security was invisible to the engine before this fix.

Every dollar assertion is exact ``Decimal`` equality, matching the standing rule for tax tests.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.canonical import (
    ConflictingCusipError,
    build_canonical_instrument_map,
    canonicalize_ledger,
)
from app.core.ids import instrument_id as compute_instrument_id
from app.core.lots import LotLedger, WarningKind, build_lots
from app.core.models import (
    Account,
    AccountType,
    Broker,
    ImportRecord,
    Instrument,
    TaxTreatment,
    Transaction,
    TxnAction,
)
from app.db import sqlite as ledger_store
from app.tax.engine import build_tax_report, report_from_ledger
from app.tax.models import GainRow, TaxReport, WashSaleEvent
from tests.conftest import DATA_DIR, requires_real_data
from tests.fixtures.synthetic_ledger import (
    ACCOUNTS as SYNTHETIC_ACCOUNTS,
)
from tests.fixtures.synthetic_ledger import (
    AS_OF as SYNTHETIC_AS_OF,
)
from tests.fixtures.synthetic_ledger import (
    TAX_YEAR as SYNTHETIC_TAX_YEAR,
)
from tests.fixtures.synthetic_ledger import (
    build_synthetic_ledger,
    qrva_round_trip_in_file_order,
)

RH_TAXABLE = Account(
    account_id="rh-taxable",
    broker=Broker.ROBINHOOD,
    label="RH Taxable",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)
WB_MARGIN = Account(
    account_id="wb-margin",
    broker=Broker.WEBULL,
    label="Webull Margin",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.MARGIN,
)
ACCOUNTS = {a.account_id: a for a in (RH_TAXABLE, WB_MARGIN)}


def _txn(
    *,
    txn_id: str,
    broker: Broker,
    account_id: str,
    action: TxnAction,
    trade_date: dt.date,
    symbol: str,
    cusip: str | None,
    quantity: str,
    price: str,
    amount: str,
    sequence: int = 0,
) -> Transaction:
    """A transaction with ``instrument_id`` computed exactly the way an adapter would compute it --
    CUSIP-keyed when a CUSIP is given, symbol-keyed otherwise."""
    return Transaction(
        txn_id=txn_id,
        import_id="imp1",
        source_row=sequence,
        account_id=account_id,
        broker=broker,
        action=action,
        trade_date=trade_date,
        sequence=sequence,
        symbol=symbol,
        cusip=cusip,
        instrument_id=compute_instrument_id(cusip=cusip, symbol=symbol),
        quantity=Decimal(quantity),
        price=Decimal(price),
        amount=Decimal(amount),
    )


# ---------------------------------------------------------------------------
# 1. The wash sale this fix exists to catch
# ---------------------------------------------------------------------------


class TestCrossBrokerWashSale:
    """A loss sold at Robinhood (CUSIP-keyed) replaced at Webull (symbol-keyed, same security) --
    the exact split identity described in the module docstring."""

    def _transactions(self) -> list[Transaction]:
        buy = _txn(
            txn_id="rh-buy",
            broker=Broker.ROBINHOOD,
            account_id="rh-taxable",
            action=TxnAction.BUY,
            trade_date=dt.date(2026, 1, 5),
            symbol="ZQXW",
            cusip="Z0000A101",
            quantity="100",
            price="50.00",
            amount="-5000.00",
        )
        sell = _txn(
            txn_id="rh-sell",
            broker=Broker.ROBINHOOD,
            account_id="rh-taxable",
            action=TxnAction.SELL,
            trade_date=dt.date(2026, 6, 1),
            symbol="ZQXW",
            cusip="Z0000A101",
            quantity="100",
            price="30.00",
            amount="3000.00",
        )
        replacement = _txn(
            txn_id="wb-buy",
            broker=Broker.WEBULL,
            account_id="wb-margin",
            action=TxnAction.BUY,
            trade_date=dt.date(2026, 6, 15),
            symbol="ZQXW",  # Webull: no CUSIP, so this alone would hash to a different instrument_id
            cusip=None,
            quantity="100",
            price="32.00",
            amount="-3200.00",
        )
        return [buy, sell, replacement]

    def test_missed_before_canonicalization(self) -> None:
        """Before the fix, the Robinhood disposal and the Webull replacement carry different
        instrument_id values, ZQXW is not in DEFAULT_EQUIVALENCE, so the pair is not even flagged
        as unsettled -- it is completely invisible, which is the bug."""
        report = build_tax_report(self._transactions(), accounts=ACCOUNTS, tax_year=2026)
        assert report.wash_sales == ()
        assert report.unsettled == ()

    def test_detected_after_canonicalization(self) -> None:
        transactions, instruments = canonicalize_ledger(self._transactions(), {})
        report = build_tax_report(
            transactions, accounts=ACCOUNTS, tax_year=2026, instruments=instruments
        )

        assert len(report.wash_sales) == 1
        event = report.wash_sales[0]
        assert event.symbol == "ZQXW"
        assert event.loss_amount == Decimal("2000.00")
        assert event.quantity_replaced == Decimal("100")
        assert event.disallowed_loss == Decimal("2000.00")
        assert event.permanently_disallowed is False
        assert event.replacement_account_ids == ("wb-margin",)


# ---------------------------------------------------------------------------
# 2. Import order must not matter
# ---------------------------------------------------------------------------


def test_merge_result_is_identical_regardless_of_import_order() -> None:
    """Webull imported before Robinhood must produce exactly the same canonical ids as the reverse
    order -- the whole point of resolving identity at derive time rather than ingest time."""
    robinhood_buy = _txn(
        txn_id="rh-buy",
        broker=Broker.ROBINHOOD,
        account_id="rh-taxable",
        action=TxnAction.BUY,
        trade_date=dt.date(2026, 1, 5),
        symbol="AVGO",
        cusip="11135F101",
        quantity="10",
        price="200.00",
        amount="-2000.00",
    )
    webull_buy = _txn(
        txn_id="wb-buy",
        broker=Broker.WEBULL,
        account_id="wb-margin",
        action=TxnAction.BUY,
        trade_date=dt.date(2026, 2, 1),
        symbol="AVGO",
        cusip=None,
        quantity="5",
        price="210.00",
        amount="-1050.00",
    )

    webull_first, _ = canonicalize_ledger([webull_buy, robinhood_buy], {})
    robinhood_first, _ = canonicalize_ledger([robinhood_buy, webull_buy], {})

    ids_webull_first = {t.txn_id: t.instrument_id for t in webull_first}
    ids_robinhood_first = {t.txn_id: t.instrument_id for t in robinhood_first}

    assert ids_webull_first == ids_robinhood_first
    # And they actually merged onto the CUSIP-keyed id, not just onto each other by coincidence.
    assert ids_webull_first["rh-buy"] == ids_webull_first["wb-buy"]
    assert ids_webull_first["rh-buy"] == compute_instrument_id(cusip="11135F101", symbol="AVGO")


# ---------------------------------------------------------------------------
# 3. Conflicting CUSIPs must never be silently merged
# ---------------------------------------------------------------------------


def test_two_distinct_cusips_sharing_a_symbol_are_not_merged() -> None:
    """A ticker can be reused after a delisting. Two different CUSIPs claiming the same normalised
    symbol is a real, dangerous condition -- it must raise, never pick one."""
    first = _txn(
        txn_id="a",
        broker=Broker.ROBINHOOD,
        account_id="rh-taxable",
        action=TxnAction.BUY,
        trade_date=dt.date(2020, 1, 1),
        symbol="DUP",
        cusip="111111111",
        quantity="1",
        price="10.00",
        amount="-10.00",
    )
    second = _txn(
        txn_id="b",
        broker=Broker.ROBINHOOD,
        account_id="rh-taxable",
        action=TxnAction.BUY,
        trade_date=dt.date(2026, 1, 1),
        symbol="DUP",
        cusip="222222222",
        quantity="1",
        price="10.00",
        amount="-10.00",
    )

    with pytest.raises(ConflictingCusipError) as excinfo:
        build_canonical_instrument_map([first, second], {})

    assert excinfo.value.normalized_symbol == "DUP"
    assert excinfo.value.cusips == ["111111111", "222222222"]

    # canonicalize_ledger must propagate the same refusal, not swallow it.
    with pytest.raises(ConflictingCusipError):
        canonicalize_ledger([first, second], {})


# ---------------------------------------------------------------------------
# 4. A symbol seen at only one broker is unaffected
# ---------------------------------------------------------------------------


def test_symbol_at_only_one_broker_is_unaffected() -> None:
    cusip_only = _txn(
        txn_id="solo-cusip",
        broker=Broker.ROBINHOOD,
        account_id="rh-taxable",
        action=TxnAction.BUY,
        trade_date=dt.date(2026, 1, 1),
        symbol="ONLYRH",
        cusip="C1111111",
        quantity="1",
        price="10.00",
        amount="-10.00",
    )
    symbol_only = _txn(
        txn_id="solo-symbol",
        broker=Broker.WEBULL,
        account_id="wb-margin",
        action=TxnAction.BUY,
        trade_date=dt.date(2026, 1, 1),
        symbol="ONLYWB",
        cusip=None,
        quantity="1",
        price="10.00",
        amount="-10.00",
    )

    canonical = build_canonical_instrument_map([cusip_only, symbol_only], {})
    assert canonical == {}

    transactions, _instruments = canonicalize_ledger([cusip_only, symbol_only], {})
    ids = {t.txn_id: t.instrument_id for t in transactions}
    assert ids["solo-cusip"] == cusip_only.instrument_id
    assert ids["solo-symbol"] == symbol_only.instrument_id


# ---------------------------------------------------------------------------
# 5. symbol_alias round-trips
# ---------------------------------------------------------------------------


def _instrument(instrument_id: str, symbol: str, cusip: str | None = None) -> Instrument:
    return Instrument(instrument_id=instrument_id, primary_symbol=symbol, cusip=cusip)


class TestSymbolAliasTable:
    def test_upsert_and_fetch_round_trip(self, conn) -> None:  # type: ignore[no-untyped-def]
        # symbol_alias.instrument_id is a foreign key into instrument, like txn.instrument_id.
        ledger_store.upsert_instrument(conn, _instrument("inst-x", "BRK.B", "084670702"))
        ledger_store.upsert_instrument(conn, _instrument("inst-y", "BRK-B"))

        ledger_store.upsert_symbol_alias(
            conn, symbol="BRK.B", broker="robinhood", instrument_id="inst-x"
        )
        ledger_store.upsert_symbol_alias(
            conn, symbol="BRK-B", broker="webull", instrument_id="inst-y"
        )

        aliases = ledger_store.fetch_symbol_aliases(conn)
        assert ("BRK.B", "robinhood", "inst-x") in aliases
        assert ("BRK-B", "webull", "inst-y") in aliases

    def test_upsert_on_the_same_key_updates_rather_than_duplicates(self, conn) -> None:  # type: ignore[no-untyped-def]
        ledger_store.upsert_instrument(conn, _instrument("inst-old", "BRK.B"))
        ledger_store.upsert_instrument(conn, _instrument("inst-new", "BRK.B"))

        ledger_store.upsert_symbol_alias(
            conn, symbol="BRK.B", broker="robinhood", instrument_id="inst-old"
        )
        ledger_store.upsert_symbol_alias(
            conn, symbol="BRK.B", broker="robinhood", instrument_id="inst-new"
        )

        aliases = ledger_store.fetch_symbol_aliases(conn)
        matching = [a for a in aliases if a[:2] == ("BRK.B", "robinhood")]
        assert matching == [("BRK.B", "robinhood", "inst-new")]

    def test_insert_transactions_populates_symbol_alias(self, conn) -> None:  # type: ignore[no-untyped-def]
        """The ingestion-time write-through: every transaction insert_transactions sees records its
        (symbol, broker) -> instrument_id, which is what app.core.canonical's module docstring
        describes symbol_alias as being for."""
        ledger_store.record_import(
            conn,
            ImportRecord(
                import_id="imp1",
                source_path="p",
                filename="f.csv",
                file_sha256="sha",
                content_hash="content",
                broker=Broker.ROBINHOOD,
                account_id="rh-taxable",
                adapter="robinhood",
                adapter_version="1",
                row_count=1,
                usable_row_count=1,
                imported_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            ),
        )
        txn = _txn(
            txn_id="a",
            broker=Broker.ROBINHOOD,
            account_id="rh-taxable",
            action=TxnAction.BUY,
            trade_date=dt.date(2026, 1, 1),
            symbol="SOXL",
            cusip="83088V102",
            quantity="10",
            price="5.00",
            amount="-50.00",
        )
        ledger_store.upsert_instrument(
            conn, _instrument(txn.instrument_id, "SOXL", "83088V102")
        )

        ledger_store.insert_transactions(conn, [txn])

        aliases = ledger_store.fetch_symbol_aliases(conn)
        assert ("SOXL", "robinhood", txn.instrument_id) in aliases


# ---------------------------------------------------------------------------
# 6. Synthetic ledger: exact tax-year-2026 figures, frozen and safe to commit
# ---------------------------------------------------------------------------
#
# `TestRealLedgerCorrectedFigures` below used to pin these same kinds of figures against the user's
# live `data/store/ledger.sqlite`. That went red on every import -- the ledger is mutable personal
# data, re-pinned three times in one day -- and it was the densest source of real financial figures in
# the repository (see `docs/BEFORE-PUBLISHING.md`). This class pins exact `Decimal` figures instead
# against `tests/fixtures/synthetic_ledger.py`, a small, invented, frozen ledger written through the
# same production write path (`app.db.sqlite.migrate` / `upsert_account` / `upsert_instrument` /
# `insert_transactions`) and read through the same production entry point
# (`app.tax.engine.report_from_ledger`) that both `app.api.tax` and `app.mcp.tools` call. Always
# runs -- nothing here is gitignored, so there is no `requires_real_data` skip and nothing to
# re-pin after a real import.
#
# See that module's docstring for why each of its five cases exists; the test names below match.


class TestSyntheticLedgerFigures:
    @pytest.fixture
    def ledger_path(self, tmp_path: Path) -> Path:
        path = tmp_path / "synthetic-ledger.sqlite"
        build_synthetic_ledger(path)
        return path

    @pytest.fixture
    def report(self, ledger_path: Path) -> TaxReport:
        with ledger_store.connect(ledger_path, read_only=True) as conn:
            return report_from_ledger(conn, tax_year=SYNTHETIC_TAX_YEAR, as_of=SYNTHETIC_AS_OF)

    @pytest.fixture
    def lot_ledger(self, ledger_path: Path) -> LotLedger:
        """The replayed, canonicalised, wash-sale-adjusted lots -- everything
        `report_from_ledger` computes internally on its way to a `TaxReport`, exposed here because
        `TaxReport` itself carries no lot detail and case 1's "zero open lots" assertion needs it."""
        with ledger_store.connect(ledger_path, read_only=True) as conn:
            accounts = {a.account_id: a for a in ledger_store.fetch_accounts(conn)}
            instruments = {
                i.instrument_id: i for i in ledger_store.fetch_instruments(conn)
            }
            transactions = [
                ledger_store.transaction_from_row(row)
                for row in ledger_store.fetch_transactions(conn)
            ]
        transactions, instruments = canonicalize_ledger(transactions, instruments)
        return build_lots(transactions, accounts=accounts, instruments=instruments)

    @staticmethod
    def _wash_sale(report: TaxReport, symbol: str) -> WashSaleEvent:
        matches = [e for e in report.wash_sales if e.symbol == symbol]
        assert len(matches) == 1, f"expected exactly one {symbol} wash-sale event, got {matches}"
        return matches[0]

    @staticmethod
    def _gain_row(report: TaxReport, symbol: str, disposed_date: dt.date) -> GainRow:
        matches = [
            r
            for r in report.gains.rows
            if r.symbol == symbol and r.disposed_date == disposed_date
        ]
        assert len(matches) == 1, (
            f"expected exactly one {symbol} row disposed on {disposed_date}, got {matches}"
        )
        return matches[0]

    # -- Case 1: newest-first export ordering (QRVA) ------------------------------------------

    def test_same_day_round_trip_orders_correctly(self, report: TaxReport) -> None:
        assert not any(w.kind == "oversold" for w in report.warnings)
        row = self._gain_row(report, "QRVA", dt.date(2026, 3, 2))
        assert row.proceeds == Decimal("1250.00")
        assert row.cost_basis == Decimal("1000.00")
        assert row.gain_loss == Decimal("250.00")
        assert row.reportable_gain_loss == Decimal("250.00")
        assert row.disallowed_loss == Decimal("0")
        assert row.term.value == "short"

    def test_same_day_round_trip_leaves_no_open_lot(self, lot_ledger: LotLedger) -> None:
        qrva_open = [
            lot
            for lot in lot_ledger.open_lots()
            if lot_ledger.symbols.get(lot.instrument_id) == "QRVA"
        ]
        assert qrva_open == []
        assert not any(w.kind is WarningKind.OVERSOLD for w in lot_ledger.warnings)

    def test_same_day_round_trip_reproduces_the_phantom_bug_in_file_order(self) -> None:
        """Not a test of production code -- proof that the two assertions above are not vacuous.

        Feeding `build_lots` the same QRVA buy/sell pair in the file's own `source_row` order (the
        pre-fix tie-break `fetch_transactions` used to apply) reproduces exactly the phantom-open-lot
        bug case 1 exists to catch: the sale finds no lot, books a zero-basis disposal and raises
        `oversold`, and the purchase opens a lot nothing closes. `report_from_ledger` never hits this
        path itself -- `fetch_transactions` orders on `replay_order` now -- which is exactly what
        `test_same_day_round_trip_leaves_no_open_lot` is asserting.
        """
        wrong_order = qrva_round_trip_in_file_order()
        assert [t.action.value for t in wrong_order] == ["sell", "buy"]

        result = build_lots(wrong_order, accounts=SYNTHETIC_ACCOUNTS)

        oversold = [w for w in result.warnings if w.kind is WarningKind.OVERSOLD]
        assert len(oversold) == 1
        assert oversold[0].quantity == Decimal("50")
        assert len(result.open_lots()) == 1
        assert result.open_lots()[0].remaining == Decimal("50")
        assert result.open_lots()[0].cost_basis == Decimal("1000.00")

    # -- Case 2: cross-broker instrument identity (KLDX) ---------------------------------------

    def test_cross_broker_wash_sale_disallows_the_full_loss(self, report: TaxReport) -> None:
        event = self._wash_sale(report, "KLDX")
        assert event.permanently_disallowed is False
        assert event.quantity_sold == Decimal("100")
        assert event.quantity_replaced == Decimal("100")
        assert event.loss_amount == Decimal("2000.00")
        assert event.disallowed_loss == Decimal("2000.00")
        assert event.sale_account_id == "rh-taxable"
        assert event.replacement_account_ids == ("wb-margin",)

        row = self._gain_row(report, "KLDX", dt.date(2026, 2, 1))
        assert row.proceeds == Decimal("3000.00")
        assert row.cost_basis == Decimal("5000.00")
        assert row.gain_loss == Decimal("-2000.00")
        assert row.disallowed_loss == Decimal("2000.00")
        assert row.permanently_disallowed_loss == Decimal("0")
        assert row.reportable_gain_loss == Decimal("0")

    # -- Case 3: disallowance spread across two replacement lots (TRVK) ------------------------

    def test_multi_lot_disallowance_spreads_across_both_replacement_lots(self, report: TaxReport) -> None:
        event = self._wash_sale(report, "TRVK")
        assert event.permanently_disallowed is False
        assert event.quantity_sold == Decimal("100")
        assert event.quantity_replaced == Decimal("100")
        assert event.loss_amount == Decimal("2000.00")
        assert event.disallowed_loss == Decimal("2000.00")
        assert len(event.replacement_lot_ids) == 2
        assert event.basis_added_to_lot_id in event.replacement_lot_ids

        original = self._gain_row(report, "TRVK", dt.date(2026, 2, 1))
        assert original.gain_loss == Decimal("-2000.00")
        assert original.disallowed_loss == Decimal("2000.00")
        assert original.reportable_gain_loss == Decimal("0")

        # The larger replacement lot (60 of 100 shares) -- `basis_added_to_lot_id` under the old,
        # singular-only `_sync_disposals`. Its basis was always re-synced even before the fix, so this
        # row alone would not have caught the bug; it is here for the contrast with the row below.
        lot1_sale = self._gain_row(report, "TRVK", dt.date(2026, 6, 1))
        assert lot1_sale.cost_basis == Decimal("3120.00")  # 1920.00 + 1200.00 wash-sale adjustment
        assert lot1_sale.gain_loss == Decimal("-720.00")
        assert lot1_sale.reportable_gain_loss == Decimal("-720.00")
        assert lot1_sale.disallowed_loss == Decimal("0")

        # The row this fix exists for: the smaller replacement lot (40 of 100 shares), which
        # `WashSaleEvent.basis_added_to_lot_id` never names because that field is singular. Its raised
        # basis (2120.00 = 1320.00 + 800.00, not the pre-adjustment 1320.00) is what makes this a
        # $520.00 loss instead of a fabricated $280.00 gain -- see
        # `test_multi_lot_disallowance_is_not_vacuous` for the proof that this line is load-bearing.
        lot2_sale = self._gain_row(report, "TRVK", dt.date(2026, 6, 5))
        assert lot2_sale.cost_basis == Decimal("2120.00")
        assert lot2_sale.gain_loss == Decimal("-520.00")
        assert lot2_sale.reportable_gain_loss == Decimal("-520.00")
        assert lot2_sale.disallowed_loss == Decimal("0")

    # -- Case 4: IRA replacement, permanently disallowed (MRDX) --------------------------------

    def test_ira_replacement_is_permanently_disallowed_and_kept_separate(self, report: TaxReport) -> None:
        event = self._wash_sale(report, "MRDX")
        assert event.permanently_disallowed is True
        assert event.basis_added_to_lot_id is None
        assert event.holding_period_tolled_to is None
        assert event.disallowed_loss == Decimal("450.00")
        assert event.replacement_account_ids == ("rh-roth",)

        row = self._gain_row(report, "MRDX", dt.date(2026, 3, 1))
        assert row.gain_loss == Decimal("-450.00")
        assert row.disallowed_loss == Decimal("450.00")
        assert row.permanently_disallowed_loss == Decimal("450.00")
        assert row.permanently_disallowed is True
        assert row.reportable_gain_loss == Decimal("0")

    # -- Case 5: sub-cent, fractional-share figures (FLNT) --------------------------------------

    def test_fractional_share_disposal_reconciles_to_the_cent(self, report: TaxReport) -> None:
        row = self._gain_row(report, "FLNT", dt.date(2026, 3, 20))
        assert row.proceeds == Decimal("1182.35")
        assert row.cost_basis == Decimal("1002.84")
        assert row.gain_loss == Decimal("179.51")
        assert row.reportable_gain_loss == Decimal("179.51")

    # -- Whole-report totals and cross-checks ----------------------------------------------------

    def test_wash_sale_event_count_and_cross_broker_count(self, report: TaxReport) -> None:
        # Three events: cross-broker KLDX (case 2), two-lot TRVK (case 3), IRA MRDX (case 4).
        assert len(report.wash_sales) == 3

        cross_broker = 0
        for event in report.wash_sales:
            sale_account = SYNTHETIC_ACCOUNTS[event.sale_account_id]
            replacement_brokers = {
                SYNTHETIC_ACCOUNTS[a].broker for a in event.replacement_account_ids
            }
            if any(broker != sale_account.broker for broker in replacement_brokers):
                cross_broker += 1
        assert cross_broker == 1  # only KLDX crosses brokers; TRVK and MRDX stay within Robinhood

    def test_no_warnings(self, report: TaxReport) -> None:
        # In particular: no `oversold` from case 1, and no `backward_basis_attachment` from case 3 --
        # both TRVK replacement lots are sold well after the loss sale that triggered their
        # adjustment, so `_sync_disposals` has nothing to flag.
        assert report.warnings == ()

    def test_gains_totals(self, report: TaxReport) -> None:
        assert report.gains.short_term_gain == Decimal("429.51")  # QRVA + KLDX + MRDX + FLNT
        assert report.gains.long_term_gain == Decimal("-1240.00")  # TRVK original + lot1 + lot2
        assert report.gains.disallowed_loss_total == Decimal("4000.00")  # KLDX 2000 + TRVK 2000
        assert report.gains.permanently_disallowed_total == Decimal("450.00")  # MRDX only
        assert len(report.gains.rows) == 7
        assert report.gains.rows_with_uncertain_basis == 0
        assert report.gains.excluded_account_ids == ()

    def test_form8949_reconciles_to_the_gains_report(self, report: TaxReport) -> None:
        assert report.form8949.short_term_total_gain == report.gains.short_term_gain
        assert report.form8949.long_term_total_gain == report.gains.long_term_gain
        for form_row in report.form8949.rows:
            # Column (h) = (d) - (e) + (g), exactly -- see app.tax.form8949's module docstring.
            assert (
                form_row.proceeds - form_row.cost_basis + form_row.adjustment_amount
                == form_row.gain_loss
            )

    def test_no_gain_row_carries_a_disallowance_while_reporting_a_gain(self, report: TaxReport) -> None:
        for row in report.gains.rows:
            if row.disallowed_loss > 0:
                assert row.gain_loss < 0, (
                    f"{row.symbol} disposed {row.disposed_date} carries disallowed_loss "
                    f"{row.disallowed_loss} but reports gain_loss {row.gain_loss} >= 0"
                )

    def test_multi_lot_disallowance_is_not_vacuous(self, report: TaxReport) -> None:
        """Documents the non-vacuity proof for case 3 rather than re-running it: temporarily
        narrowing `app.tax.engine._sync_disposals`'s loop from `event.replacement_lot_ids` to
        just `(event.basis_added_to_lot_id,)` -- the pre-fix, singular-only behaviour -- and rerunning
        this class turns three assertions red, confirmed by hand while writing this file:

        * Here: `lot2_sale.cost_basis` reverts from `2120.00` to the pre-adjustment `1320.00`, and
          `lot2_sale.gain_loss` flips from the true `-520.00` loss to a fabricated `280.00` gain.
        * `test_multi_lot_disallowance_spreads_across_both_replacement_lots`'s identical assertions on
          `lot2_sale` fail the same way.
        * `test_gains_totals`'s `long_term_gain` moves by exactly `800.00` (`-1240.00` ->
          `-440.00`) -- lot2's own wash-sale adjustment, silently dropped.

        `test_no_gain_row_carries_a_disallowance_while_reporting_a_gain` does **not** fail under this
        break, and that is worth stating rather than leaving to be discovered: `lot2_sale` itself never
        carries a *new* disallowance (`disallowed_loss` stays `0` -- nothing replaces the June sale),
        so that invariant, which only looks at `row.disallowed_loss`, cannot see a lot that is
        wash-sale-adjusted but whose *own* disposal was never flagged. It is a real, general
        invariant and worth keeping, but it is not what catches this specific bug -- the exact-value
        pins on `lot2_sale` above are.

        Not re-run on every CI pass, because it requires editing production code rather than test
        data -- the same reason `tests/test_replay_order_integration.py` documents its own non-vacuity
        proof in prose instead of executing it.
        """
        lot2_sale = self._gain_row(report, "TRVK", dt.date(2026, 6, 5))
        assert lot2_sale.cost_basis == Decimal("2120.00")
        assert lot2_sale.gain_loss == Decimal("-520.00")


# ---------------------------------------------------------------------------
# 7. Real data: invariants that hold at any ledger size
# ---------------------------------------------------------------------------

#: `data/store/ledger.sqlite`, a developer's live ledger. Read-only, and never hand-edited.
_LEDGER_PATH = DATA_DIR / "store" / "ledger.sqlite"


@requires_real_data
class TestRealLedgerCorrectedFigures:
    """Invariants against a live ledger that must hold regardless of its current size.

    This class used to pin the exact tax-year-2026 figures measured from `data/store/ledger.sqlite` --
    realised gains, wash-sale totals, transaction counts. Every one of those pins broke on the user's
    next import, because the ledger is mutable personal data that cannot be committed (see
    `.gitignore`): there was nothing stable to pin against, and the pins were re-derived three times in
    one day. Those absolute figures now live in `tests/fixtures/synthetic_ledger.py` and
    `TestSyntheticLedgerFigures` above, which exercise the identical code paths against a small, frozen,
    invented ledger that needs no re-pinning. What remains here is everything that must hold no matter
    what the user has imported since -- structural and cross-report consistency, not dollar amounts.
    """

    @pytest.fixture(autouse=True)
    def _skip_without_ledger(self) -> None:
        if not _LEDGER_PATH.exists():
            pytest.skip("data/store/ledger.sqlite not present")

    def _report(self):  # type: ignore[no-untyped-def]
        with ledger_store.connect(_LEDGER_PATH, read_only=True) as conn:
            accounts = {a.account_id: a for a in ledger_store.fetch_accounts(conn)}
            return report_from_ledger(conn, tax_year=2026, as_of=dt.date(2026, 12, 31)), accounts

    def test_deferred_and_permanent_are_separate_and_match_the_gains_report(self) -> None:
        report, _accounts = self._report()

        deferred = sum(
            (e.disallowed_loss for e in report.wash_sales if not e.permanently_disallowed),
            Decimal(0),
        )
        permanent = sum(
            (e.disallowed_loss for e in report.wash_sales if e.permanently_disallowed),
            Decimal(0),
        )
        assert deferred >= 0
        assert permanent >= 0

        # True at any ledger size: a triggering disposal's `disallowed_loss` is the sum of every
        # event drawn from it (app.tax.washsale._build_events splits one disposal into an ordinary
        # and an IRA event when the replacement spans both), and GainsReport accumulates the same
        # split independently, per disposal rather than per event. The two totals must therefore
        # reconcile exactly regardless of what has been imported.
        assert deferred == report.gains.disallowed_loss_total
        assert permanent == report.gains.permanently_disallowed_total

        # Structural, not a measurement: `basis_added_to_lot_id` is `None` if and only if the event
        # is the IRA case (Rev. Rul. 2008-5 adds basis nowhere) -- see `_build_events`.
        for event in report.wash_sales:
            assert (event.basis_added_to_lot_id is None) == event.permanently_disallowed

    def test_form8949_reconciles_to_the_gains_report(self) -> None:
        report, _accounts = self._report()
        assert report.form8949.short_term_total_gain == report.gains.short_term_gain
        assert report.form8949.long_term_total_gain == report.gains.long_term_gain
        for row in report.form8949.rows:
            # Column (h) = (d) - (e) + (g), exactly -- see app.tax.form8949's module docstring. A
            # violation here is a defective form regardless of what the underlying figures are.
            assert row.proceeds - row.cost_basis + row.adjustment_amount == row.gain_loss

    def test_no_gain_row_carries_a_disallowance_while_reporting_a_gain(self) -> None:
        report, _accounts = self._report()
        for row in report.gains.rows:
            if row.disallowed_loss > 0:
                assert row.gain_loss < 0, (
                    f"{row.symbol} disposed {row.disposed_date} carries disallowed_loss "
                    f"{row.disallowed_loss} but reports gain_loss {row.gain_loss} >= 0"
                )
            assert Decimal(0) <= row.permanently_disallowed_loss <= row.disallowed_loss

    def test_counts_and_totals_are_internally_consistent(self) -> None:
        report, _accounts = self._report()
        assert 0 <= report.gains.rows_with_uncertain_basis <= len(report.gains.rows)
        assert 0 <= report.gains.rows_with_unknown_fees <= len(report.gains.rows)
        assert report.gains.short_term_proceeds >= 0
        assert report.gains.long_term_proceeds >= 0
        assert report.gains.short_term_basis >= 0
        assert report.gains.long_term_basis >= 0
        assert report.gains.disallowed_loss_total >= 0
        assert report.gains.permanently_disallowed_total >= 0
        assert report.permanent_disallowance_count <= len(report.wash_sales)

    def test_cross_broker_wash_sales_are_a_subset_of_all_wash_sales(self) -> None:
        report, accounts = self._report()

        cross_broker = 0
        for event in report.wash_sales:
            sale_account = accounts.get(event.sale_account_id)
            if sale_account is None:
                continue
            replacement_brokers = {
                accounts[a].broker for a in event.replacement_account_ids if a in accounts
            }
            if any(broker != sale_account.broker for broker in replacement_brokers):
                cross_broker += 1

        assert 0 <= cross_broker <= len(report.wash_sales)

    def test_canonical_instrument_map_only_merges_symbol_keyed_ids_onto_cusip_keyed_ones(self) -> None:
        """The split-identity map (`app.core.canonical.build_canonical_instrument_map`) may only ever
        remap a symbol-keyed id onto a *different*, CUSIP-backed id -- never onto itself, and never
        onto something with no CUSIP -- regardless of how many instruments or transactions the ledger
        currently holds. See that module's docstring: "merge direction is one-way."
        """
        with ledger_store.connect(_LEDGER_PATH, read_only=True) as conn:
            instruments = {i.instrument_id: i for i in ledger_store.fetch_instruments(conn)}
            transactions = [
                ledger_store.transaction_from_row(row)
                for row in ledger_store.fetch_transactions(conn)
            ]

        canonical = build_canonical_instrument_map(transactions, instruments)
        cusips_by_instrument = {i.instrument_id: i.cusip for i in instruments.values()}
        for txn in transactions:
            if txn.cusip and txn.instrument_id:
                cusips_by_instrument.setdefault(txn.instrument_id, txn.cusip)

        for symbol_keyed_id, cusip_keyed_id in canonical.items():
            assert symbol_keyed_id != cusip_keyed_id
            assert cusips_by_instrument.get(cusip_keyed_id)
