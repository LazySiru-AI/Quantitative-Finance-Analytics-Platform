"""Tests for :func:`app.tax.washsale_summary.build_wash_sale_summary`.

Every dollar assertion is exact ``Decimal`` equality, matching the convention in
``tests/test_washsale.py`` -- ``pytest.approx`` in a tax test is not a tax test.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.tax.models import WashSaleEvent
from app.tax.washsale_summary import (
    LossSale,
    build_wash_sale_exposure_report,
    build_wash_sale_summary,
)

# ---------------------------------------------------------------------------------------------
# Small builder -- only the fields a given test cares about differ from these defaults.
# ---------------------------------------------------------------------------------------------


def _event(
    event_id: str,
    *,
    disposal_id: str | None = None,
    symbol: str = "SOXL",
    sale_date: dt.date,
    sale_account_id: str = "rh-taxable",
    disallowed_loss: str = "100.00",
    permanently_disallowed: bool = False,
) -> WashSaleEvent:
    return WashSaleEvent(
        event_id=event_id,
        disposal_id=disposal_id or f"disp-{event_id}",
        instrument_id="instr-soxl",
        symbol=symbol,
        sale_date=sale_date,
        sale_account_id=sale_account_id,
        quantity_sold=Decimal("10"),
        loss_amount=Decimal(disallowed_loss),
        quantity_replaced=Decimal("10"),
        disallowed_loss=Decimal(disallowed_loss),
        permanently_disallowed=permanently_disallowed,
    )


def _loss_sale(
    disposal_id: str,
    *,
    symbol: str = "SOXL",
    sale_date: dt.date,
    account_id: str = "rh-taxable",
    quantity: str = "10",
    loss_amount: str = "100.00",
) -> LossSale:
    return LossSale(
        symbol=symbol,
        sale_date=sale_date,
        account_id=account_id,
        disposal_id=disposal_id,
        quantity=Decimal(quantity),
        loss_amount=Decimal(loss_amount),
    )


# ---------------------------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------------------------


class TestEmpty:
    def test_empty_events_produce_empty_zeroed_summary(self) -> None:
        summary = build_wash_sale_summary([], as_of=dt.date(2026, 6, 1))

        assert summary.symbols == ()
        assert summary.total_deferred == Decimal(0)
        assert summary.total_permanently_disallowed == Decimal(0)
        assert summary.open_window_count == 0
        assert summary.as_of == dt.date(2026, 6, 1)


# ---------------------------------------------------------------------------------------------
# The ±30 / ±31 boundary on repurchase_safe_on and window_is_open
# ---------------------------------------------------------------------------------------------


class TestRepurchaseBoundary:
    def test_repurchase_safe_on_is_sale_date_plus_31_days(self) -> None:
        sale_date = dt.date(2026, 3, 2)
        summary = build_wash_sale_summary(
            [_event("e1", sale_date=sale_date)], as_of=sale_date
        )

        [row] = summary.symbols
        assert row.repurchase_safe_on == dt.date(2026, 4, 2)  # +31 days

    def test_window_is_open_on_the_30th_day_inclusive(self) -> None:
        sale_date = dt.date(2026, 3, 2)
        as_of = sale_date + dt.timedelta(days=30)
        summary = build_wash_sale_summary([_event("e1", sale_date=sale_date)], as_of=as_of)

        [row] = summary.symbols
        assert row.window_is_open is True
        assert row.days_until_safe == 1  # safe date is day 31, one day after as_of

    def test_window_is_closed_on_the_31st_day(self) -> None:
        sale_date = dt.date(2026, 3, 2)
        as_of = sale_date + dt.timedelta(days=31)
        summary = build_wash_sale_summary([_event("e1", sale_date=sale_date)], as_of=as_of)

        [row] = summary.symbols
        assert row.window_is_open is False
        assert row.days_until_safe == 0

    def test_as_of_exactly_on_repurchase_safe_on_is_safe(self) -> None:
        sale_date = dt.date(2026, 3, 2)
        as_of = dt.date(2026, 4, 2)  # exactly repurchase_safe_on
        summary = build_wash_sale_summary([_event("e1", sale_date=sale_date)], as_of=as_of)

        [row] = summary.symbols
        assert row.repurchase_safe_on == as_of
        assert row.days_until_safe == 0
        assert row.window_is_open is False


# ---------------------------------------------------------------------------------------------
# days_until_safe clamped at zero for a long-past sale
# ---------------------------------------------------------------------------------------------


class TestClampedAtZero:
    def test_days_until_safe_never_negative_for_a_long_past_sale(self) -> None:
        sale_date = dt.date(2020, 1, 1)
        as_of = dt.date(2026, 6, 1)
        summary = build_wash_sale_summary([_event("e1", sale_date=sale_date)], as_of=as_of)

        [row] = summary.symbols
        assert row.days_until_safe == 0
        assert row.window_is_open is False


# ---------------------------------------------------------------------------------------------
# Deferred and permanent kept separate and never summed
# ---------------------------------------------------------------------------------------------


class TestDeferredVsPermanent:
    def test_deferred_and_permanent_are_split_and_not_summed(self) -> None:
        as_of = dt.date(2026, 6, 1)
        events = [
            _event(
                "e1",
                disposal_id="disp-a",
                sale_date=dt.date(2026, 1, 5),
                disallowed_loss="150.00",
                permanently_disallowed=False,
            ),
            _event(
                "e2",
                disposal_id="disp-a",  # same disposal, other half went to an IRA
                sale_date=dt.date(2026, 1, 5),
                disallowed_loss="50.00",
                permanently_disallowed=True,
            ),
        ]
        summary = build_wash_sale_summary(events, as_of=as_of)

        [row] = summary.symbols
        assert row.deferred_disallowed == Decimal("150.00")
        assert row.permanently_disallowed == Decimal("50.00")
        # Never summed into one figure anywhere on the row or the report total.
        assert row.deferred_disallowed != row.deferred_disallowed + row.permanently_disallowed
        assert summary.total_deferred == Decimal("150.00")
        assert summary.total_permanently_disallowed == Decimal("50.00")
        # One disposal, two events.
        assert row.event_count == 2
        assert row.loss_sale_count == 1

    def test_all_permanent_symbol_has_zero_deferred(self) -> None:
        summary = build_wash_sale_summary(
            [
                _event(
                    "e1",
                    symbol="TQQQ",
                    sale_date=dt.date(2026, 1, 5),
                    disallowed_loss="75.00",
                    permanently_disallowed=True,
                )
            ],
            as_of=dt.date(2026, 6, 1),
        )

        [row] = summary.symbols
        assert row.deferred_disallowed == Decimal(0)
        assert row.permanently_disallowed == Decimal("75.00")


# ---------------------------------------------------------------------------------------------
# Several events on one symbol aggregate and take the latest sale date
# ---------------------------------------------------------------------------------------------


class TestAggregationAcrossEvents:
    def test_multiple_events_aggregate_and_use_latest_sale_date(self) -> None:
        events = [
            _event(
                "e1",
                disposal_id="disp-1",
                sale_date=dt.date(2026, 1, 5),
                disallowed_loss="100.00",
            ),
            _event(
                "e2",
                disposal_id="disp-2",
                sale_date=dt.date(2026, 3, 10),  # latest -- governs repurchase_safe_on
                disallowed_loss="60.00",
            ),
            _event(
                "e3",
                disposal_id="disp-3",
                sale_date=dt.date(2026, 2, 1),
                disallowed_loss="40.00",
            ),
        ]
        summary = build_wash_sale_summary(events, as_of=dt.date(2026, 3, 10))

        [row] = summary.symbols
        assert row.deferred_disallowed == Decimal("200.00")
        assert row.event_count == 3
        assert row.loss_sale_count == 3
        assert row.first_sale_date == dt.date(2026, 1, 5)
        assert row.last_sale_date == dt.date(2026, 3, 10)
        assert row.repurchase_safe_on == dt.date(2026, 4, 10)


# ---------------------------------------------------------------------------------------------
# Multiple accounts collected and sorted
# ---------------------------------------------------------------------------------------------


class TestAccountsSorted:
    def test_accounts_are_deduplicated_and_sorted(self) -> None:
        events = [
            _event("e1", disposal_id="d1", sale_date=dt.date(2026, 1, 5), sale_account_id="webull-margin"),
            _event("e2", disposal_id="d2", sale_date=dt.date(2026, 1, 6), sale_account_id="rh-taxable"),
            _event("e3", disposal_id="d3", sale_date=dt.date(2026, 1, 7), sale_account_id="rh-taxable"),
            _event("e4", disposal_id="d4", sale_date=dt.date(2026, 1, 8), sale_account_id="sofi-taxable"),
        ]
        summary = build_wash_sale_summary(events, as_of=dt.date(2026, 6, 1))

        [row] = summary.symbols
        assert row.accounts == ("rh-taxable", "sofi-taxable", "webull-margin")


# ---------------------------------------------------------------------------------------------
# Multiple symbols: sort order and report-level totals
# ---------------------------------------------------------------------------------------------


class TestMultipleSymbolsAndTotals:
    def test_symbols_sorted_by_deferred_descending_then_symbol_ascending(self) -> None:
        events = [
            _event("e1", symbol="AAA", disposal_id="d1", sale_date=dt.date(2026, 1, 1), disallowed_loss="50.00"),
            _event("e2", symbol="BBB", disposal_id="d2", sale_date=dt.date(2026, 1, 1), disallowed_loss="200.00"),
            _event("e3", symbol="CCC", disposal_id="d3", sale_date=dt.date(2026, 1, 1), disallowed_loss="200.00"),
            _event("e4", symbol="DDD", disposal_id="d4", sale_date=dt.date(2026, 1, 1), disallowed_loss="0.00"),
        ]
        summary = build_wash_sale_summary(events, as_of=dt.date(2026, 6, 1))

        assert [row.symbol for row in summary.symbols] == ["BBB", "CCC", "AAA", "DDD"]

    def test_report_totals_sum_across_symbols_deferred_and_permanent_separately(self) -> None:
        as_of = dt.date(2026, 3, 15)
        events = [
            _event(
                "e1",
                symbol="AAA",
                disposal_id="d1",
                sale_date=dt.date(2026, 3, 1),  # window still open at as_of
                disallowed_loss="100.00",
            ),
            _event(
                "e2",
                symbol="BBB",
                disposal_id="d2",
                sale_date=dt.date(2026, 1, 1),  # window long closed at as_of
                disallowed_loss="30.00",
                permanently_disallowed=True,
            ),
        ]
        summary = build_wash_sale_summary(events, as_of=as_of)

        assert summary.total_deferred == Decimal("100.00")
        assert summary.total_permanently_disallowed == Decimal("30.00")
        assert summary.open_window_count == 1

# ---------------------------------------------------------------------------
# The loss-sale population, not the event list, anchors the window
#
# A `WashSaleEvent` exists only where a loss sale *already matched a replacement purchase* --
# `apply_wash_sales` emits nothing when `quantity_replaced_total` is zero. So a loss nobody has
# bought back yet produces no event, and that is exactly the position this panel exists to report on.
# Anchoring on events alone did not merely omit those rows; it made affirmatively false claims.
#
# Seen on a real ledger before this was fixed: several symbols with open windows were missing
# entirely, and more were reported *safe to repurchase* while their windows were genuinely open --
# a stale last-loss-sale date was shown where a later one was the true one. The open-window count
# read lower than the true count.
# ---------------------------------------------------------------------------


class TestLossSalesAnchorTheWindow:
    def test_a_loss_with_no_repurchase_yet_still_appears(self) -> None:
        """The row that matters most: nothing is deferred, and the user must not buy it back."""
        summary = build_wash_sale_summary(
            [],
            as_of=dt.date(2026, 8, 15),
            loss_sales=[LossSale("AAOI", dt.date(2026, 8, 13), "rh-taxable")],
        )
        assert len(summary.symbols) == 1
        row = summary.symbols[0]
        assert row.symbol == "AAOI"
        assert row.deferred_disallowed == Decimal(0)
        assert row.permanently_disallowed == Decimal(0)
        assert row.event_count == 0
        assert row.loss_sale_count == 1
        assert row.window_is_open is True
        assert row.repurchase_safe_on == dt.date(2026, 9, 13)
        assert row.days_until_safe == 29
        assert summary.open_window_count == 1

    def test_a_later_unreplaced_loss_moves_the_window_past_an_earlier_event(self) -> None:
        """The exact NVDL shape: an old replaced loss and a recent unreplaced one. The recent sale
        sets the safe date, and reporting the old one calls an open window closed."""
        summary = build_wash_sale_summary(
            [
                _event(
                    "e1",
                    symbol="NVDL",
                    sale_date=dt.date(2026, 5, 28),
                    disallowed_loss="507.75",
                    sale_account_id="wb-margin",
                )
            ],
            as_of=dt.date(2026, 8, 15),
            loss_sales=[
                LossSale("NVDL", dt.date(2026, 5, 28), "wb-margin"),
                LossSale("NVDL", dt.date(2026, 8, 5), "wb-margin"),
            ],
        )
        row = summary.symbols[0]
        assert row.last_sale_date == dt.date(2026, 8, 5)
        assert row.repurchase_safe_on == dt.date(2026, 9, 5)
        assert row.window_is_open is True, "an open window must never be reported as safe"
        assert row.days_until_safe == 21
        # The money still comes from the events, untouched by the wider date population.
        assert row.deferred_disallowed == Decimal("507.75")
        assert row.loss_sale_count == 2

    def test_the_money_still_comes_only_from_events(self) -> None:
        """Loss sales carry no dollar figure -- a sale never disallowed must not invent one."""
        summary = build_wash_sale_summary(
            [],
            as_of=dt.date(2026, 8, 15),
            loss_sales=[
                LossSale("IGV", dt.date(2026, 7, 21), "rh-taxable"),
                LossSale("IGV", dt.date(2026, 7, 22), "rh-taxable"),
            ],
        )
        assert summary.total_deferred == Decimal(0)
        assert summary.total_permanently_disallowed == Decimal(0)
        assert summary.symbols[0].loss_sale_count == 2

    def test_accounts_come_from_both_populations(self) -> None:
        summary = build_wash_sale_summary(
            [
                _event(
                    "e1",
                    symbol="GLD",
                    sale_date=dt.date(2026, 7, 30),
                    disallowed_loss="318.10",
                    sale_account_id="wb-margin",
                )
            ],
            as_of=dt.date(2026, 8, 15),
            loss_sales=[LossSale("GLD", dt.date(2026, 7, 30), "rh-taxable")],
        )
        assert summary.symbols[0].accounts == ("rh-taxable", "wb-margin")

    def test_omitting_loss_sales_falls_back_to_event_dates(self) -> None:
        """The degenerate path, kept working so the fold stays callable in isolation -- and pinned so
        its limitation stays visible rather than being assumed away."""
        summary = build_wash_sale_summary(
            [_event("e1", symbol="X", sale_date=dt.date(2026, 6, 1), disallowed_loss="10.00")],
            as_of=dt.date(2026, 8, 15),
        )
        assert summary.symbols[0].last_sale_date == dt.date(2026, 6, 1)


# ---------------------------------------------------------------------------------------------
# The per-symbol `sales` drill-down: one row per triggered event, plus one for every loss that
# triggered no event at all.
# ---------------------------------------------------------------------------------------------


class TestSalesDrillDown:
    def test_a_loss_with_no_event_still_gets_its_own_sale_row(self) -> None:
        """The most actionable row on the whole tracker: taken, open, not yet disallowed."""
        summary = build_wash_sale_summary(
            [],
            as_of=dt.date(2026, 8, 15),
            loss_sales=[
                _loss_sale(
                    "disp-aaoi",
                    symbol="AAOI",
                    sale_date=dt.date(2026, 8, 13),
                    account_id="rh-taxable",
                    quantity="12",
                    loss_amount="88.40",
                )
            ],
        )
        [row] = summary.symbols
        assert row.event_count == 0
        assert len(row.sales) == 1
        [sale] = row.sales
        assert sale.disposal_id == "disp-aaoi"
        assert sale.sale_date == dt.date(2026, 8, 13)
        assert sale.account_id == "rh-taxable"
        assert sale.quantity_sold == Decimal("12")
        assert sale.loss_amount == Decimal("88.40")
        # Nothing disallowed yet -- the loss is real, the disallowance is not.
        assert sale.quantity_replaced == Decimal(0)
        assert sale.disallowed_loss == Decimal(0)
        assert sale.permanently_disallowed is False
        assert sale.replacement_account_ids == ()
        assert sale.window_closes_on == dt.date(2026, 9, 13)  # sale_date + 31

    def test_a_triggered_loss_sale_is_not_duplicated(self) -> None:
        """A disposal with an event is fully represented by that event's row -- no zeroed twin."""
        summary = build_wash_sale_summary(
            [
                _event(
                    "e1",
                    disposal_id="disp-1",
                    sale_date=dt.date(2026, 3, 2),
                    disallowed_loss="26.25",
                )
            ],
            as_of=dt.date(2026, 8, 15),
            loss_sales=[
                _loss_sale("disp-1", sale_date=dt.date(2026, 3, 2), loss_amount="26.25")
            ],
        )
        [row] = summary.symbols
        assert len(row.sales) == 1
        [sale] = row.sales
        assert sale.disallowed_loss == Decimal("26.25")
        assert sale.quantity_replaced == Decimal("10")

    def test_a_disposal_split_across_taxable_and_ira_produces_two_rows(self) -> None:
        """Two events from one disposal must never fold into one row's `disallowed_loss` --
        that is exactly the deferred/permanent conflation this module refuses to perform."""
        events = [
            _event(
                "e1",
                disposal_id="disp-a",
                sale_date=dt.date(2026, 1, 5),
                disallowed_loss="150.00",
                permanently_disallowed=False,
                sale_account_id="rh-taxable",
            ),
            _event(
                "e2",
                disposal_id="disp-a",
                sale_date=dt.date(2026, 1, 5),
                disallowed_loss="50.00",
                permanently_disallowed=True,
                sale_account_id="rh-taxable",
            ),
        ]
        summary = build_wash_sale_summary(
            events,
            as_of=dt.date(2026, 6, 1),
            loss_sales=[
                _loss_sale("disp-a", sale_date=dt.date(2026, 1, 5), loss_amount="200.00")
            ],
        )
        [row] = summary.symbols
        assert len(row.sales) == 2
        assert {s.disposal_id for s in row.sales} == {"disp-a"}
        deferred_rows = [s for s in row.sales if not s.permanently_disallowed]
        permanent_rows = [s for s in row.sales if s.permanently_disallowed]
        assert [s.disallowed_loss for s in deferred_rows] == [Decimal("150.00")]
        assert [s.disallowed_loss for s in permanent_rows] == [Decimal("50.00")]

    def test_sales_length_can_exceed_event_count(self) -> None:
        summary = build_wash_sale_summary(
            [
                _event(
                    "e1", disposal_id="disp-1", sale_date=dt.date(2026, 3, 2), disallowed_loss="26.25"
                )
            ],
            as_of=dt.date(2026, 8, 15),
            loss_sales=[
                _loss_sale("disp-1", sale_date=dt.date(2026, 3, 2), loss_amount="26.25"),
                _loss_sale(
                    "disp-2", sale_date=dt.date(2026, 7, 1), loss_amount="14.00"
                ),  # never repurchased
            ],
        )
        [row] = summary.symbols
        assert row.event_count == 1
        assert len(row.sales) == 2
        assert len(row.sales) > row.event_count

    def test_sales_sorted_by_sale_date_descending(self) -> None:
        summary = build_wash_sale_summary(
            [],
            as_of=dt.date(2026, 8, 15),
            loss_sales=[
                _loss_sale("d1", sale_date=dt.date(2026, 1, 5)),
                _loss_sale("d2", sale_date=dt.date(2026, 6, 1)),
                _loss_sale("d3", sale_date=dt.date(2026, 3, 10)),
            ],
        )
        [row] = summary.symbols
        assert [s.sale_date for s in row.sales] == [
            dt.date(2026, 6, 1),
            dt.date(2026, 3, 10),
            dt.date(2026, 1, 5),
        ]

    def test_window_closes_on_differs_from_symbol_repurchase_safe_on(self) -> None:
        """`window_closes_on` is this sale's own date + 31; `repurchase_safe_on` is measured from the
        symbol's latest sale. An earlier sale's window closes first."""
        summary = build_wash_sale_summary(
            [],
            as_of=dt.date(2026, 8, 15),
            loss_sales=[
                _loss_sale("d1", sale_date=dt.date(2026, 1, 5)),
                _loss_sale("d2", sale_date=dt.date(2026, 8, 5)),
            ],
        )
        [row] = summary.symbols
        assert row.repurchase_safe_on == dt.date(2026, 9, 5)  # from the latest sale, 2026-08-05
        early_sale = next(s for s in row.sales if s.sale_date == dt.date(2026, 1, 5))
        assert early_sale.window_closes_on == dt.date(2026, 2, 5)
        assert early_sale.window_closes_on != row.repurchase_safe_on

    def test_sale_rows_reconcile_to_the_symbol_deferred_and_permanent_totals(self) -> None:
        events = [
            _event(
                "e1", disposal_id="d1", sale_date=dt.date(2026, 1, 5), disallowed_loss="100.00"
            ),
            _event(
                "e2",
                disposal_id="d2",
                sale_date=dt.date(2026, 2, 1),
                disallowed_loss="30.00",
                permanently_disallowed=True,
            ),
        ]
        summary = build_wash_sale_summary(
            events,
            as_of=dt.date(2026, 6, 1),
            loss_sales=[
                _loss_sale("d1", sale_date=dt.date(2026, 1, 5), loss_amount="100.00"),
                _loss_sale("d2", sale_date=dt.date(2026, 2, 1), loss_amount="30.00"),
                _loss_sale("d3", sale_date=dt.date(2026, 3, 1), loss_amount="12.50"),
            ],
        )
        [row] = summary.symbols
        sale_deferred = sum(
            (s.disallowed_loss for s in row.sales if not s.permanently_disallowed), Decimal(0)
        )
        sale_permanent = sum(
            (s.disallowed_loss for s in row.sales if s.permanently_disallowed), Decimal(0)
        )
        assert sale_deferred == row.deferred_disallowed == Decimal("100.00")
        assert sale_permanent == row.permanently_disallowed == Decimal("30.00")
        # Deferred and permanent never combine, on the row or the reconciled sum.
        assert sale_deferred != sale_deferred + sale_permanent


# ---------------------------------------------------------------------------------------------
# build_wash_sale_exposure_report -- the tracker's own symbol order and top-level shape
# ---------------------------------------------------------------------------------------------


class TestBuildWashSaleExposureReport:
    def test_open_windows_sort_first_ahead_of_larger_closed_ones(self) -> None:
        """The tracker's whole job is "what is still live" -- a small open window must outrank a
        large, fully-settled one, unlike `WashSaleSummary.symbols`'s own size-only order."""
        as_of = dt.date(2026, 8, 15)
        events = [
            _event(
                "e1",
                symbol="BIGCLOSED",
                disposal_id="d1",
                sale_date=dt.date(2026, 1, 1),  # long closed by as_of
                disallowed_loss="9000.00",
            ),
            _event(
                "e2",
                symbol="SMALLOPEN",
                disposal_id="d2",
                sale_date=dt.date(2026, 8, 10),  # still open
                disallowed_loss="10.00",
            ),
        ]
        summary = build_wash_sale_summary(events, as_of=as_of)
        report = build_wash_sale_exposure_report(
            summary, generated_at=dt.datetime(2026, 8, 15, 20, 0, tzinfo=dt.UTC)
        )
        assert [s.symbol for s in report.symbols] == ["SMALLOPEN", "BIGCLOSED"]

    def test_within_the_same_open_state_deferred_descending_then_symbol_breaks_ties(self) -> None:
        as_of = dt.date(2026, 6, 1)
        events = [
            _event("e1", symbol="AAA", disposal_id="d1", sale_date=dt.date(2026, 1, 1), disallowed_loss="50.00"),
            _event("e2", symbol="BBB", disposal_id="d2", sale_date=dt.date(2026, 1, 1), disallowed_loss="200.00"),
            _event("e3", symbol="CCC", disposal_id="d3", sale_date=dt.date(2026, 1, 1), disallowed_loss="200.00"),
        ]
        summary = build_wash_sale_summary(events, as_of=as_of)
        report = build_wash_sale_exposure_report(summary, generated_at=dt.datetime.now(dt.UTC))
        assert [s.symbol for s in report.symbols] == ["BBB", "CCC", "AAA"]

    def test_a_symbol_with_an_open_window_and_zero_deferred_still_appears_and_leads(self) -> None:
        as_of = dt.date(2026, 8, 15)
        summary = build_wash_sale_summary(
            [
                _event(
                    "e1",
                    symbol="SETTLED",
                    disposal_id="d1",
                    sale_date=dt.date(2026, 1, 1),
                    disallowed_loss="500.00",
                )
            ],
            as_of=as_of,
            loss_sales=[
                _loss_sale(
                    "d2", symbol="AAOI", sale_date=dt.date(2026, 8, 13), loss_amount="88.40"
                )
            ],
        )
        report = build_wash_sale_exposure_report(summary, generated_at=dt.datetime.now(dt.UTC))
        assert report.symbols[0].symbol == "AAOI"
        assert report.symbols[0].deferred_disallowed == Decimal(0)
        assert report.symbols[0].window_is_open is True
        assert len(report.symbols[0].sales) == 1

    def test_top_level_totals_and_counts_pass_through_unchanged(self) -> None:
        as_of = dt.date(2026, 6, 1)
        events = [
            _event("e1", symbol="AAA", disposal_id="d1", sale_date=dt.date(2026, 1, 1), disallowed_loss="100.00"),
            _event(
                "e2",
                symbol="BBB",
                disposal_id="d2",
                sale_date=dt.date(2026, 1, 1),
                disallowed_loss="30.00",
                permanently_disallowed=True,
            ),
        ]
        summary = build_wash_sale_summary(events, as_of=as_of)
        generated_at = dt.datetime(2026, 8, 16, 20, 0, tzinfo=dt.UTC)
        report = build_wash_sale_exposure_report(summary, generated_at=generated_at)

        assert report.as_of == summary.as_of
        assert report.generated_at == generated_at
        assert report.total_deferred == summary.total_deferred == Decimal("100.00")
        assert report.total_permanently_disallowed == summary.total_permanently_disallowed == Decimal("30.00")
        assert report.open_window_count == summary.open_window_count
        assert report.symbol_count == len(summary.symbols) == 2
        # Never summed into one figure at the report level either.
        assert report.total_deferred != report.total_deferred + report.total_permanently_disallowed

