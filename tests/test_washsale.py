"""Wash-sale engine (IRC §1091 / IRS Pub 550 / Rev. Rul. 2008-5) -- the ten standing test cases.

Every case here is built by hand, not through :func:`app.core.lots.build_lots` (unimplemented as of
this writing, and the wrong tool for testing tax rules anyway: these are precise, hand-constructed
scenarios). ``Lot`` and ``Disposal`` are mutable by design, exactly so :func:`app.tax.washsale.apply_wash_sales`
can write its results back onto them -- these tests assert both the returned
:class:`~app.tax.washsale.WashSaleResult` and the mutated ledger.

Every dollar assertion is exact ``Decimal`` equality. ``pytest.approx`` in a tax test is not a tax
test.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.core.lots import Disposal, LotLedger
from app.core.models import Account, AccountType, Broker, Lot, TaxTreatment
from app.tax.models import EquivalenceDecision, EquivalenceRule
from app.tax.washsale import DEFAULT_EQUIVALENCE, apply_wash_sales

# ---------------------------------------------------------------------------------------------
# Fixtures: accounts, and small builders for Lot / Disposal / LotLedger.
# ---------------------------------------------------------------------------------------------

RH_TAXABLE = Account(
    account_id="rh-taxable",
    broker=Broker.ROBINHOOD,
    label="RH Taxable",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)
RH_ROTH = Account(
    account_id="rh-roth",
    broker=Broker.ROBINHOOD,
    label="RH Roth",
    tax_treatment=TaxTreatment.ROTH_IRA,
    account_type=AccountType.RETIREMENT,
)
RH_TRADITIONAL = Account(
    account_id="rh-traditional",
    broker=Broker.ROBINHOOD,
    label="RH Traditional",
    tax_treatment=TaxTreatment.TRADITIONAL_IRA,
    account_type=AccountType.RETIREMENT,
)
WEBULL_MARGIN = Account(
    account_id="webull-margin",
    broker=Broker.WEBULL,
    label="Webull Margin",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.MARGIN,
)
SOFI_TAXABLE = Account(
    account_id="sofi-taxable",
    broker=Broker.SOFI,
    label="SoFi Taxable",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)

ALL_ACCOUNTS = {
    a.account_id: a
    for a in (RH_TAXABLE, RH_ROTH, RH_TRADITIONAL, WEBULL_MARGIN, SOFI_TAXABLE)
}


def _lot(
    lot_id: str,
    *,
    instrument_id: str = "instr-soxl",
    account_id: str = "rh-taxable",
    acquired_date: dt.date,
    quantity: str,
    cost_basis: str,
    holding_period_start: dt.date | None = None,
    wash_sale_adjustment: str = "0",
) -> Lot:
    return Lot(
        lot_id=lot_id,
        instrument_id=instrument_id,
        account_id=account_id,
        acquired_date=acquired_date,
        acquired_txn_id=f"{lot_id}-buy",
        quantity=Decimal(quantity),
        remaining=Decimal(quantity),
        cost_basis=Decimal(cost_basis),
        wash_sale_adjustment=Decimal(wash_sale_adjustment),
        holding_period_start=holding_period_start,
    )


def _disposal(
    disposal_id: str,
    lot: Lot,
    *,
    disposed_date: dt.date,
    quantity: str,
    proceeds: str,
    fees: str = "0",
    symbol: str = "SOXL",
    cost_basis: Decimal | None = None,
) -> Disposal:
    """Build a disposal consuming ``quantity`` shares of ``lot``.

    ``cost_basis`` defaults to the lot's per-share basis *at construction time*, matching what
    ``build_lots`` would have produced before any wash-sale awareness. Passing it explicitly lets
    the chained test (case 7) simulate a disposal built before its lot was later adjusted.
    """
    qty = Decimal(quantity)
    allocated = cost_basis if cost_basis is not None else lot.basis_per_share * qty
    return Disposal(
        disposal_id=disposal_id,
        lot_id=lot.lot_id,
        instrument_id=lot.instrument_id,
        account_id=lot.account_id,
        symbol=symbol,
        sell_txn_id=f"{disposal_id}-sell",
        acquired_date=lot.acquired_date,
        holding_start=lot.effective_holding_start,
        disposed_date=disposed_date,
        quantity=qty,
        proceeds=Decimal(proceeds),
        cost_basis=allocated,
        fees=Decimal(fees),
    )


def _ledger(lots: list[Lot], disposals: list[Disposal], symbols: dict[str, str]) -> LotLedger:
    return LotLedger(lots=lots, disposals=disposals, warnings=[], symbols=symbols)


# ---------------------------------------------------------------------------------------------
# Case 1 -- loss sale, repurchase 10 days later, same account, same quantity: full disallowance.
# ---------------------------------------------------------------------------------------------


class TestCase1FullReplacementSameAccount:
    def test_full_loss_disallowed_basis_added_holding_period_tolled(self) -> None:
        sold = _lot(
            "lot-sold",
            acquired_date=dt.date(2024, 1, 2),
            quantity="50",
            cost_basis="1250.00",  # $25.00/share
        )
        disposal = _disposal(
            "disp-1", sold, disposed_date=dt.date(2026, 3, 2), quantity="50", proceeds="1000.00"
        )  # loss of $250.00

        replacement = _lot(
            "lot-replacement",
            acquired_date=dt.date(2026, 3, 12),  # 10 days after the sale
            quantity="50",
            cost_basis="1000.00",  # $20.00/share, bought back at the lower price
        )

        ledger = _ledger([sold, replacement], [disposal], {"instr-soxl": "SOXL"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert len(result.events) == 1
        event = result.events[0]
        assert event.quantity_sold == Decimal("50")
        assert event.quantity_replaced == Decimal("50")
        assert event.loss_amount == Decimal("250.00")
        assert event.disallowed_loss == Decimal("250.00")
        assert event.permanently_disallowed is False
        assert event.basis_added_to_lot_id == "lot-replacement"
        assert event.replacement_lot_ids == ("lot-replacement",)
        assert event.holding_period_tolled_to == dt.date(2024, 1, 2)
        assert event.is_chained is False

        # Mutation, asserted directly on the ledger objects.
        assert disposal.disallowed_loss == Decimal("250.00")
        assert disposal.permanently_disallowed is False
        assert replacement.wash_sale_adjustment == Decimal("250.00")
        assert replacement.cost_basis == Decimal("1250.00")  # 1000 + 250
        assert replacement.holding_period_start == dt.date(2024, 1, 2)
        assert replacement.effective_holding_start == dt.date(2024, 1, 2)

        assert result.unsettled == ()


# ---------------------------------------------------------------------------------------------
# Case 2 -- repurchase 31 days later: no wash sale (exclusive boundary).
# ---------------------------------------------------------------------------------------------


class TestCase2Day31NoWashSale:
    def test_boundary_exclusive_at_day_31_forward(self) -> None:
        sold = _lot("lot-sold", acquired_date=dt.date(2024, 1, 2), quantity="50", cost_basis="1250.00")
        disposal = _disposal(
            "disp-2", sold, disposed_date=dt.date(2026, 3, 2), quantity="50", proceeds="1000.00"
        )
        replacement = _lot(
            "lot-replacement",
            acquired_date=dt.date(2026, 4, 2),  # 31 days after 2026-03-02
            quantity="50",
            cost_basis="1000.00",
        )

        ledger = _ledger([sold, replacement], [disposal], {"instr-soxl": "SOXL"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert result.events == ()
        assert result.unsettled == ()
        assert disposal.disallowed_loss == Decimal("0")
        assert replacement.cost_basis == Decimal("1000.00")
        assert replacement.wash_sale_adjustment == Decimal("0")
        assert replacement.holding_period_start is None


# ---------------------------------------------------------------------------------------------
# Case 3 -- repurchase 30 days BEFORE the sale: the backward half of the window is real.
# ---------------------------------------------------------------------------------------------


class TestCase3BackwardWindow:
    def test_purchase_30_days_before_sale_is_a_wash_sale(self) -> None:
        # The "replacement" shares were actually bought first.
        replacement = _lot(
            "lot-replacement",
            acquired_date=dt.date(2026, 1, 31),  # 30 days before the sale below
            quantity="50",
            cost_basis="1000.00",
        )
        sold = _lot("lot-sold", acquired_date=dt.date(2024, 1, 2), quantity="50", cost_basis="1250.00")
        disposal = _disposal(
            "disp-3", sold, disposed_date=dt.date(2026, 3, 2), quantity="50", proceeds="1000.00"
        )

        ledger = _ledger([sold, replacement], [disposal], {"instr-soxl": "SOXL"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert len(result.events) == 1
        event = result.events[0]
        assert event.disallowed_loss == Decimal("250.00")
        assert event.replacement_lot_ids == ("lot-replacement",)
        assert replacement.cost_basis == Decimal("1250.00")
        assert replacement.holding_period_start == dt.date(2024, 1, 2)


# ---------------------------------------------------------------------------------------------
# Case 4 -- partial replacement: sale of 100, repurchase of 40 -> 40% disallowed, 60% allowed.
# ---------------------------------------------------------------------------------------------


class TestCase4PartialReplacement:
    def test_forty_of_one_hundred_disallows_forty_percent(self) -> None:
        sold = _lot(
            "lot-sold", acquired_date=dt.date(2024, 1, 2), quantity="100", cost_basis="2500.00"
        )  # $25/share
        disposal = _disposal(
            "disp-4", sold, disposed_date=dt.date(2026, 3, 2), quantity="100", proceeds="2000.00"
        )  # loss of $500.00

        replacement = _lot(
            "lot-replacement",
            acquired_date=dt.date(2026, 3, 10),
            quantity="40",
            cost_basis="800.00",  # $20/share
        )

        ledger = _ledger([sold, replacement], [disposal], {"instr-soxl": "SOXL"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert len(result.events) == 1
        event = result.events[0]
        assert event.quantity_sold == Decimal("100")
        assert event.quantity_replaced == Decimal("40")
        assert event.loss_amount == Decimal("500.00")
        # 40% of $500.00 = $200.00 disallowed; $300.00 (60%) remains a deductible loss.
        assert event.disallowed_loss == Decimal("200.00")
        assert disposal.disallowed_loss == Decimal("200.00")
        assert disposal.allowed_loss == Decimal("-300.00")
        assert replacement.cost_basis == Decimal("1000.00")  # 800 + 200
        assert replacement.wash_sale_adjustment == Decimal("200.00")


# ---------------------------------------------------------------------------------------------
# Case 5 -- cross-broker: loss in Webull Margin, repurchase in RH taxable, matched by CUSIP.
# ---------------------------------------------------------------------------------------------


class TestCase5CrossBroker:
    def test_matched_across_brokers_by_instrument_id_not_ticker(self) -> None:
        sold = _lot(
            "lot-sold",
            instrument_id="instr-nvda",
            account_id="webull-margin",
            acquired_date=dt.date(2024, 1, 2),
            quantity="10",
            cost_basis="1200.00",
        )
        disposal = _disposal(
            "disp-5",
            sold,
            disposed_date=dt.date(2026, 5, 1),
            quantity="10",
            proceeds="1000.00",
            symbol="NVDA",
        )

        # Same CUSIP-derived instrument_id, different broker, and even a slightly different raw
        # ticker string to prove ticker text is not what matching keys on.
        replacement = _lot(
            "lot-replacement",
            instrument_id="instr-nvda",
            account_id="rh-taxable",
            acquired_date=dt.date(2026, 5, 15),
            quantity="10",
            cost_basis="1000.00",
        )

        ledger = _ledger([sold, replacement], [disposal], {"instr-nvda": "NVDA"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert len(result.events) == 1
        event = result.events[0]
        assert event.disallowed_loss == Decimal("200.00")
        assert event.replacement_account_ids == ("rh-taxable",)
        assert event.sale_account_id == "webull-margin"
        assert replacement.cost_basis == Decimal("1200.00")  # 1000 + 200


# ---------------------------------------------------------------------------------------------
# Case 6 -- Rev. Rul. 2008-5: replacement bought inside an IRA. Permanent, no basis add-back.
# ---------------------------------------------------------------------------------------------


class TestCase6IRAPermanentDisallowance:
    def test_replacement_in_roth_ira_is_permanently_disallowed_with_no_basis_addback(self) -> None:
        sold = _lot(
            "lot-sold",
            instrument_id="instr-nvda",
            account_id="rh-taxable",
            acquired_date=dt.date(2024, 1, 2),
            quantity="10",
            cost_basis="1200.00",
        )
        disposal = _disposal(
            "disp-6",
            sold,
            disposed_date=dt.date(2026, 5, 1),
            quantity="10",
            proceeds="1000.00",
            symbol="NVDA",
        )

        roth_lot = _lot(
            "lot-roth",
            instrument_id="instr-nvda",
            account_id="rh-roth",
            acquired_date=dt.date(2026, 5, 10),
            quantity="10",
            cost_basis="1000.00",
        )

        ledger = _ledger([sold, roth_lot], [disposal], {"instr-nvda": "NVDA"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert len(result.events) == 1
        event = result.events[0]
        assert event.permanently_disallowed is True
        assert event.disallowed_loss == Decimal("200.00")
        assert event.basis_added_to_lot_id is None
        assert event.holding_period_tolled_to is None
        assert event.replacement_lot_ids == ("lot-roth",)

        assert disposal.permanently_disallowed is True
        assert disposal.disallowed_loss == Decimal("200.00")

        # The core of Rev. Rul. 2008-5: nothing is added anywhere.
        assert roth_lot.cost_basis == Decimal("1000.00")
        assert roth_lot.wash_sale_adjustment == Decimal("0")
        assert roth_lot.holding_period_start is None

    def test_traditional_ira_replacement_is_also_permanently_disallowed(self) -> None:
        sold = _lot(
            "lot-sold",
            instrument_id="instr-nvda",
            account_id="rh-taxable",
            acquired_date=dt.date(2024, 1, 2),
            quantity="10",
            cost_basis="1200.00",
        )
        disposal = _disposal(
            "disp-6b",
            sold,
            disposed_date=dt.date(2026, 5, 1),
            quantity="10",
            proceeds="1000.00",
            symbol="NVDA",
        )
        traditional_lot = _lot(
            "lot-traditional",
            instrument_id="instr-nvda",
            account_id="rh-traditional",
            acquired_date=dt.date(2026, 5, 20),
            quantity="10",
            cost_basis="1000.00",
        )

        ledger = _ledger([sold, traditional_lot], [disposal], {"instr-nvda": "NVDA"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert result.events[0].permanently_disallowed is True
        assert traditional_lot.cost_basis == Decimal("1000.00")


# ---------------------------------------------------------------------------------------------
# Case 7 -- chained: a replacement lot is itself later sold at a loss and replaced again.
# ---------------------------------------------------------------------------------------------


class TestCase7Chaining:
    def test_second_wash_sale_computed_against_the_adjusted_basis(self) -> None:
        # First sale: lot A, a loss.
        lot_a = _lot(
            "lot-a", acquired_date=dt.date(2024, 1, 1), quantity="100", cost_basis="2500.00"
        )  # $25/share
        disposal_a = _disposal(
            "disp-a", lot_a, disposed_date=dt.date(2026, 1, 10), quantity="100", proceeds="2000.00"
        )  # loss of $500.00

        # Replacement: lot B, bought 5 days later inside lot A's window.
        lot_b = _lot(
            "lot-b", acquired_date=dt.date(2026, 1, 15), quantity="100", cost_basis="2000.00"
        )  # $20/share, before any adjustment

        # Second sale: lot B sold whole, 6 weeks later. Its disposal is built with the ORIGINAL,
        # un-adjusted per-share basis -- exactly what a lot-replay pass would have produced before
        # wash-sale processing ever ran. At $24/share proceeds against the original $20/share basis
        # this would look like a *gain*; against the basis lot B is entitled to after absorbing
        # disposal A's disallowed loss ($25/share), it is a loss. Only a correctly chained engine
        # catches this.
        disposal_b = _disposal(
            "disp-b",
            lot_b,
            disposed_date=dt.date(2026, 2, 20),
            quantity="100",
            proceeds="2400.00",
            cost_basis=Decimal("2000.00"),  # stale, pre-adjustment value -- see docstring above
        )

        # Second replacement: lot C, bought 5 days after disposal B, inside lot B's window.
        lot_c = _lot(
            "lot-c", acquired_date=dt.date(2026, 2, 25), quantity="100", cost_basis="2300.00"
        )  # $23/share

        ledger = _ledger(
            [lot_a, lot_b, lot_c], [disposal_a, disposal_b], {"instr-soxl": "SOXL"}
        )
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert len(result.events) == 2
        event_a, event_b = sorted(result.events, key=lambda e: e.sale_date)

        # First event: ordinary, ties out to the naive numbers.
        assert event_a.disposal_id == "disp-a"
        assert event_a.disallowed_loss == Decimal("500.00")
        assert event_a.is_chained is False
        assert lot_b.cost_basis == Decimal("2500.00")  # 2000 + 500
        assert lot_b.wash_sale_adjustment == Decimal("500.00")
        assert lot_b.holding_period_start == dt.date(2024, 1, 1)  # tolled to lot A's start

        # Second event: the loss only exists because the engine used lot B's adjusted basis
        # (2500, i.e. $25/share) rather than the stale $2000 on the hand-built Disposal.
        assert event_b.disposal_id == "disp-b"
        assert event_b.loss_amount == Decimal("100.00")  # 2500 - 2400
        assert event_b.disallowed_loss == Decimal("100.00")
        assert event_b.is_chained is True
        assert event_b.replacement_lot_ids == ("lot-c",)

        assert lot_c.cost_basis == Decimal("2400.00")  # 2300 + 100
        assert lot_c.wash_sale_adjustment == Decimal("100.00")
        # Tolled all the way back through the chain to lot A's original holding start.
        assert lot_c.holding_period_start == dt.date(2024, 1, 1)

        assert disposal_a.disallowed_loss == Decimal("500.00")
        assert disposal_b.disallowed_loss == Decimal("100.00")


# ---------------------------------------------------------------------------------------------
# Case 8 -- gain followed by repurchase: not a wash sale. The rule applies to losses only.
# ---------------------------------------------------------------------------------------------


class TestCase8GainIsNeverAWashSale:
    def test_gain_sale_with_repurchase_produces_no_event(self) -> None:
        sold = _lot("lot-sold", acquired_date=dt.date(2024, 1, 2), quantity="50", cost_basis="1000.00")
        disposal = _disposal(
            "disp-8", sold, disposed_date=dt.date(2026, 3, 2), quantity="50", proceeds="1500.00"
        )  # a $500 gain
        replacement = _lot(
            "lot-replacement", acquired_date=dt.date(2026, 3, 10), quantity="50", cost_basis="1500.00"
        )

        ledger = _ledger([sold, replacement], [disposal], {"instr-soxl": "SOXL"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert result.events == ()
        assert result.unsettled == ()
        assert disposal.disallowed_loss == Decimal("0")
        assert replacement.cost_basis == Decimal("1500.00")
        assert replacement.wash_sale_adjustment == Decimal("0")


# ---------------------------------------------------------------------------------------------
# Case 10 -- a short-term lot tolled past the one-year mark reclassifies long-term.
# ---------------------------------------------------------------------------------------------


class TestCase10TollingCrossesTheLongTermLine:
    def test_tolled_holding_start_pushes_replacement_past_one_year(self) -> None:
        old_lot = _lot(
            "lot-old", acquired_date=dt.date(2024, 5, 1), quantity="30", cost_basis="900.00"
        )
        disposal = _disposal(
            "disp-10", old_lot, disposed_date=dt.date(2026, 1, 10), quantity="30", proceeds="600.00"
        )  # loss of $300.00

        # Bought only two days after the sale: on its own, a sale of this lot on 2026-08-01 would
        # be far short of a year held (about 6.5 months) and would be short-term.
        replacement = _lot(
            "lot-replacement", acquired_date=dt.date(2026, 1, 12), quantity="30", cost_basis="600.00"
        )

        ledger = _ledger([old_lot, replacement], [disposal], {"instr-soxl": "SOXL"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert len(result.events) == 1
        assert result.events[0].holding_period_tolled_to == dt.date(2024, 5, 1)
        assert replacement.holding_period_start == dt.date(2024, 5, 1)
        assert replacement.effective_holding_start == dt.date(2024, 5, 1)

        hypothetical_sale_date = dt.date(2026, 8, 1)

        # Without tolling: acquired 2026-01-12, sold 2026-08-01 -- about 201 days, short-term.
        untolled_days = (hypothetical_sale_date - replacement.acquired_date).days
        assert untolled_days < 365

        # With tolling: effective start 2024-05-01, sold 2026-08-01 -- more than a year,
        # long-term. (HoldingTerm: long-term requires *more than* one year, counted from the day
        # after acquisition -- app.tax.models.HoldingTerm.)
        one_year_after_tolled_start = replacement.effective_holding_start.replace(
            year=replacement.effective_holding_start.year + 1
        )
        assert hypothetical_sale_date > one_year_after_tolled_start


# ---------------------------------------------------------------------------------------------
# Additional boundary coverage: day 30 (wash) and day 31 (no wash), both directions.
# ---------------------------------------------------------------------------------------------


class TestWindowBoundaries:
    def test_exactly_30_days_forward_is_a_wash_sale(self) -> None:
        sold = _lot("lot-sold", acquired_date=dt.date(2024, 1, 2), quantity="50", cost_basis="1250.00")
        disposal = _disposal(
            "disp-b30f", sold, disposed_date=dt.date(2026, 3, 2), quantity="50", proceeds="1000.00"
        )
        replacement = _lot(
            "lot-replacement", acquired_date=dt.date(2026, 4, 1), quantity="50", cost_basis="1000.00"
        )  # exactly 30 days after 2026-03-02

        ledger = _ledger([sold, replacement], [disposal], {"instr-soxl": "SOXL"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert len(result.events) == 1
        assert result.events[0].disallowed_loss == Decimal("250.00")

    def test_exactly_31_days_backward_is_not_a_wash_sale(self) -> None:
        replacement = _lot(
            "lot-replacement", acquired_date=dt.date(2026, 1, 30), quantity="50", cost_basis="1000.00"
        )  # exactly 31 days before 2026-03-02
        sold = _lot("lot-sold", acquired_date=dt.date(2024, 1, 2), quantity="50", cost_basis="1250.00")
        disposal = _disposal(
            "disp-b31b", sold, disposed_date=dt.date(2026, 3, 2), quantity="50", proceeds="1000.00"
        )

        ledger = _ledger([sold, replacement], [disposal], {"instr-soxl": "SOXL"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert result.events == ()
        assert disposal.disallowed_loss == Decimal("0")
        assert replacement.cost_basis == Decimal("1000.00")


# ---------------------------------------------------------------------------------------------
# "Substantially identical": unsettled pairs flagged, never decided; settled negatives ignored.
# ---------------------------------------------------------------------------------------------


class TestSubstantiallyIdentical:
    def test_unsettled_pair_is_flagged_with_both_impacts_and_not_applied(self) -> None:
        sold = _lot(
            "lot-sold",
            instrument_id="instr-nvda",
            acquired_date=dt.date(2024, 1, 2),
            quantity="10",
            cost_basis="1200.00",
        )
        disposal = _disposal(
            "disp-unsettled",
            sold,
            disposed_date=dt.date(2026, 5, 1),
            quantity="10",
            proceeds="1000.00",
            symbol="NVDA",
        )
        # NVDL: a different instrument_id (different CUSIP), an UNSETTLED pair per Pub 550's
        # silence on leveraged single-stock ETFs.
        nvdl_lot = _lot(
            "lot-nvdl",
            instrument_id="instr-nvdl",
            acquired_date=dt.date(2026, 5, 10),
            quantity="10",
            cost_basis="900.00",
        )

        ledger = _ledger(
            [sold, nvdl_lot], [disposal], {"instr-nvda": "NVDA", "instr-nvdl": "NVDL"}
        )
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        # Never auto-applied: no real disallowance happens.
        assert result.events == ()
        assert disposal.disallowed_loss == Decimal("0")
        assert nvdl_lot.cost_basis == Decimal("900.00")
        assert nvdl_lot.wash_sale_adjustment == Decimal("0")

        assert len(result.unsettled) == 1
        pair = result.unsettled[0]
        assert pair.sale_disposal_id == "disp-unsettled"
        assert pair.sold_symbol == "NVDA"
        assert pair.replacement_symbol == "NVDL"
        assert pair.loss_amount == Decimal("200.00")
        assert pair.impact_if_identical == Decimal("200.00")  # full match, 10 of 10 shares
        assert pair.impact_if_distinct == Decimal("0")
        assert pair.rationale  # a real, displayable string, not empty

    def test_soxl_soxs_produces_nothing(self) -> None:
        """A fund and its inverse are settled NOT_IDENTICAL: no event, no unsettled flag."""
        sold = _lot(
            "lot-sold",
            instrument_id="instr-soxl",
            acquired_date=dt.date(2024, 1, 2),
            quantity="10",
            cost_basis="250.00",
        )
        disposal = _disposal(
            "disp-soxlsoxs",
            sold,
            disposed_date=dt.date(2026, 5, 1),
            quantity="10",
            proceeds="200.00",
            symbol="SOXL",
        )
        soxs_lot = _lot(
            "lot-soxs",
            instrument_id="instr-soxs",
            acquired_date=dt.date(2026, 5, 5),
            quantity="10",
            cost_basis="180.00",
        )

        ledger = _ledger(
            [sold, soxs_lot], [disposal], {"instr-soxl": "SOXL", "instr-soxs": "SOXS"}
        )
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert result.events == ()
        assert result.unsettled == ()
        assert disposal.disallowed_loss == Decimal("0")
        assert soxs_lot.cost_basis == Decimal("180.00")

    def test_default_equivalence_table_has_the_documented_pairs(self) -> None:
        settled_negative = {
            frozenset({r.left.upper(), r.right.upper()})
            for r in DEFAULT_EQUIVALENCE
            if r.decision.value == "not_identical"
        }
        unsettled_pairs = {
            frozenset({r.left.upper(), r.right.upper()})
            for r in DEFAULT_EQUIVALENCE
            if r.decision.value == "unsettled"
        }
        assert frozenset({"SOXL", "SOXS"}) in settled_negative
        assert frozenset({"TQQQ", "SQQQ"}) in settled_negative
        for left, right in [
            ("NVDA", "NVDL"),
            ("MU", "MUU"),
            ("MU", "MULL"),
            ("TSLA", "TSLL"),
            ("SNDK", "SNXX"),
            ("SOXL", "SOXX"),
            ("GOOG", "GOOGL"),
            ("CRDO", "CRDU"),
            ("IREN", "IREX"),
            ("GDX", "GDXU"),
            ("GDX", "NUGT"),
        ]:
            assert frozenset({left, right}) in unsettled_pairs, f"{left}/{right} missing"
        # Every rule carries a real, non-empty rationale -- it is shown in the UI.
        for rule in DEFAULT_EQUIVALENCE:
            assert rule.rationale.strip()


# ---------------------------------------------------------------------------------------------
# IRA case: no lot anywhere in the ledger ever gains basis from a permanently disallowed loss.
# ---------------------------------------------------------------------------------------------


class TestIRACaseNeverAddsBasisAnywhere:
    def test_no_lot_in_the_ledger_gains_basis_from_the_ira_case(self) -> None:
        sold = _lot(
            "lot-sold",
            instrument_id="instr-nvda",
            account_id="rh-taxable",
            acquired_date=dt.date(2024, 1, 2),
            quantity="10",
            cost_basis="1200.00",
        )
        disposal = _disposal(
            "disp-ira-basis",
            sold,
            disposed_date=dt.date(2026, 5, 1),
            quantity="10",
            proceeds="1000.00",
            symbol="NVDA",
        )
        roth_lot = _lot(
            "lot-roth",
            instrument_id="instr-nvda",
            account_id="rh-roth",
            acquired_date=dt.date(2026, 5, 10),
            quantity="10",
            cost_basis="1000.00",
        )

        lots_before = {"lot-sold": sold.cost_basis, "lot-roth": roth_lot.cost_basis}

        ledger = _ledger([sold, roth_lot], [disposal], {"instr-nvda": "NVDA"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert result.events[0].permanently_disallowed is True
        assert result.events[0].basis_added_to_lot_id is None

        # Not one lot in the entire ledger changed basis. The loss is gone, not deferred.
        for lot in ledger.lots:
            expected = lots_before.get(lot.lot_id)
            if expected is not None:
                assert lot.cost_basis == expected, f"{lot.lot_id} basis changed"
            assert lot.wash_sale_adjustment == Decimal("0")


# ---------------------------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------------------------


class TestDeterministicOrdering:
    def test_events_and_unsettled_are_sorted_by_sale_date_then_disposal_id(self) -> None:
        # Two independent loss sales, out of order relative to each other and to the disposals
        # list order, each with its own replacement.
        lot_1 = _lot(
            "lot-1", instrument_id="instr-a", acquired_date=dt.date(2024, 1, 1),
            quantity="10", cost_basis="200.00",
        )
        disposal_late = _disposal(
            "disp-late", lot_1, disposed_date=dt.date(2026, 6, 1), quantity="10", proceeds="150.00",
            symbol="AAA",
        )
        replacement_1 = _lot(
            "lot-1-rep", instrument_id="instr-a", acquired_date=dt.date(2026, 6, 5),
            quantity="10", cost_basis="150.00",
        )

        lot_2 = _lot(
            "lot-2", instrument_id="instr-b", acquired_date=dt.date(2024, 1, 1),
            quantity="10", cost_basis="200.00",
        )
        disposal_early = _disposal(
            "disp-early", lot_2, disposed_date=dt.date(2026, 1, 1), quantity="10", proceeds="150.00",
            symbol="BBB",
        )
        replacement_2 = _lot(
            "lot-2-rep", instrument_id="instr-b", acquired_date=dt.date(2026, 1, 5),
            quantity="10", cost_basis="150.00",
        )

        # Disposals list deliberately in the "wrong" (late-first) order.
        ledger = _ledger(
            [lot_1, replacement_1, lot_2, replacement_2],
            [disposal_late, disposal_early],
            {"instr-a": "AAA", "instr-b": "BBB"},
        )
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert [e.disposal_id for e in result.events] == ["disp-early", "disp-late"]


# ---------------------------------------------------------------------------------------------
# Candidate lookup: the index that replaced a full scan of the ledger per loss disposal.
#
# The scan was O(disposals x lots) and cost 2,654 ms of a 2,700 ms Portfolio rebuild on the real
# book. Replacing it changed no rule, and these cases pin the properties a faster lookup is exactly
# the kind of change that would silently break -- each one fails against a plausible wrong index.
# ---------------------------------------------------------------------------------------------


class TestCandidateLookup:
    def test_same_date_replacements_are_taken_in_replay_order_not_by_lot_id(self) -> None:
        """Which of two same-day lots absorbs a disallowance decides whose basis moves.

        ``lot_id`` is a hash in production, so it must never be the tie-break -- the ids here are
        chosen so sorting by them gives the opposite answer to replay order.
        """
        sold = _lot(
            "lot-sold", acquired_date=dt.date(2024, 1, 2), quantity="10", cost_basis="500.00"
        )
        disposal = _disposal(
            "disp-1", sold, disposed_date=dt.date(2026, 3, 2), quantity="10", proceeds="400.00"
        )  # loss of $100.00

        # Both acquired the same day, both able to satisfy the whole sale; only the first reached
        # is used. `lot-z` is first in replay order, `lot-a` first alphabetically.
        first_replayed = _lot(
            "lot-z", acquired_date=dt.date(2026, 3, 12), quantity="10", cost_basis="400.00"
        )
        later_replayed = _lot(
            "lot-a", acquired_date=dt.date(2026, 3, 12), quantity="10", cost_basis="400.00"
        )

        ledger = _ledger(
            [sold, first_replayed, later_replayed], [disposal], {"instr-soxl": "SOXL"}
        )
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert len(result.events) == 1
        assert result.events[0].replacement_lot_ids == ("lot-z",)
        assert first_replayed.wash_sale_adjustment == Decimal("100.00")
        assert later_replayed.wash_sale_adjustment == Decimal("0")

    def test_unsettled_candidate_is_in_window_at_30_days_and_out_at_31(self) -> None:
        """The IRC 1091 boundary applies to unsettled candidates exactly as to exact ones.

        A window computed by slicing a sorted index is off by one at either end if a bound is
        wrong, and the unsettled path is the one no existing case covered.
        """
        for offset, expected_pairs in ((30, 1), (31, 0)):
            sold = _lot(
                "lot-sold",
                instrument_id="instr-nvda",
                acquired_date=dt.date(2024, 1, 2),
                quantity="10",
                cost_basis="1200.00",
            )
            disposal = _disposal(
                "disp-1",
                sold,
                disposed_date=dt.date(2026, 5, 1),
                quantity="10",
                proceeds="1000.00",
                symbol="NVDA",
            )
            nvdl_lot = _lot(
                "lot-nvdl",
                instrument_id="instr-nvdl",
                acquired_date=dt.date(2026, 5, 1) + dt.timedelta(days=offset),
                quantity="10",
                cost_basis="900.00",
            )

            ledger = _ledger(
                [sold, nvdl_lot], [disposal], {"instr-nvda": "NVDA", "instr-nvdl": "NVDL"}
            )
            result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

            assert len(result.unsettled) == expected_pairs, f"{offset} days after the sale"
            assert result.events == ()

    def test_equivalence_matching_ignores_the_case_of_the_ledger_symbol(self) -> None:
        """``EquivalenceRule.matches`` upper-cased both sides, so an index keyed on the raw symbol
        would stop matching a broker that spells its tickers in lower case."""
        sold = _lot(
            "lot-sold",
            instrument_id="instr-nvda",
            acquired_date=dt.date(2024, 1, 2),
            quantity="10",
            cost_basis="1200.00",
        )
        disposal = _disposal(
            "disp-1",
            sold,
            disposed_date=dt.date(2026, 5, 1),
            quantity="10",
            proceeds="1000.00",
            symbol="nvda",
        )
        nvdl_lot = _lot(
            "lot-nvdl",
            instrument_id="instr-nvdl",
            acquired_date=dt.date(2026, 5, 10),
            quantity="10",
            cost_basis="900.00",
        )

        ledger = _ledger(
            [sold, nvdl_lot], [disposal], {"instr-nvda": "nvda", "instr-nvdl": "nvdl"}
        )
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert len(result.unsettled) == 1
        # Reported with the ledger's own spelling, not the table's -- the user reads their symbols.
        assert result.unsettled[0].replacement_symbol == "nvdl"

    def test_first_rule_for_a_pair_wins_even_when_it_settles_the_pair_negatively(self) -> None:
        """A later UNSETTLED rule must not resurrect a pair an earlier rule already ruled out.

        The scan returned the first matching rule and stopped. A partner table built by walking the
        rules and keeping the unsettled ones would invert this and flag a pair the table settles.
        """
        equivalence = (
            EquivalenceRule(
                left="NVDA",
                right="NVDL",
                decision=EquivalenceDecision.NOT_IDENTICAL,
                rationale="settled first, so this is the one that applies",
            ),
            EquivalenceRule(
                left="NVDL",
                right="NVDA",
                decision=EquivalenceDecision.UNSETTLED,
                rationale="shadowed by the rule above, and written the other way round",
            ),
        )

        sold = _lot(
            "lot-sold",
            instrument_id="instr-nvda",
            acquired_date=dt.date(2024, 1, 2),
            quantity="10",
            cost_basis="1200.00",
        )
        disposal = _disposal(
            "disp-1",
            sold,
            disposed_date=dt.date(2026, 5, 1),
            quantity="10",
            proceeds="1000.00",
            symbol="NVDA",
        )
        nvdl_lot = _lot(
            "lot-nvdl",
            instrument_id="instr-nvdl",
            acquired_date=dt.date(2026, 5, 10),
            quantity="10",
            cost_basis="900.00",
        )

        ledger = _ledger(
            [sold, nvdl_lot], [disposal], {"instr-nvda": "NVDA", "instr-nvdl": "NVDL"}
        )
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS, equivalence=equivalence)

        assert result.unsettled == ()
        assert result.events == ()

    def test_a_lot_whose_instrument_has_no_symbol_is_never_an_unsettled_candidate(self) -> None:
        """``ledger.symbols`` can be missing an entry when identity resolution left a gap. Such a
        lot is still an exact-CUSIP candidate; it just cannot be compared against a symbol table."""
        sold = _lot(
            "lot-sold",
            instrument_id="instr-nvda",
            acquired_date=dt.date(2024, 1, 2),
            quantity="10",
            cost_basis="1200.00",
        )
        disposal = _disposal(
            "disp-1",
            sold,
            disposed_date=dt.date(2026, 5, 1),
            quantity="10",
            proceeds="1000.00",
            symbol="NVDA",
        )
        unnamed = _lot(
            "lot-unnamed",
            instrument_id="instr-unknown",
            acquired_date=dt.date(2026, 5, 10),
            quantity="10",
            cost_basis="900.00",
        )
        same_instrument = _lot(
            "lot-nvda-again",
            instrument_id="instr-nvda",
            acquired_date=dt.date(2026, 5, 10),
            quantity="10",
            cost_basis="900.00",
        )

        # `instr-unknown` deliberately absent from the symbol map.
        ledger = _ledger([sold, unnamed, same_instrument], [disposal], {"instr-nvda": "NVDA"})
        result = apply_wash_sales(ledger, accounts=ALL_ACCOUNTS)

        assert result.unsettled == ()
        assert len(result.events) == 1
        assert result.events[0].replacement_lot_ids == ("lot-nvda-again",)
        assert unnamed.wash_sale_adjustment == Decimal("0")
