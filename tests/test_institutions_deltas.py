"""Tests for the institutions delta engine (`app.institutions.deltas`) and catalog
(`app.institutions.catalog`).

Snapshots are built inline, field by field, rather than through the parser: the parser is being
written concurrently by another worker and this suite must not couple to it. Two real-filing cases
from Berkshire Hathaway's 13F-HR history anchor the share-vs-value distinction that is the point of
this feature -- see `app.institutions.deltas`'s module docstring for the sourcing of those figures.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from decimal import Decimal

from app.config import Settings
from app.core.models import Instrument, InstrumentKind
from app.db import sqlite as ledger
from app.institutions import catalog, deltas
from app.institutions.models import (
    Action,
    FundRef,
    Holding,
    HoldingChange,
    PortfolioDelta,
    Snapshot,
    Source,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _fund(
    key: str = "BRK",
    *,
    name: str = "Berkshire Hathaway Inc",
    source: Source = Source.THIRTEEN_F,
    cik: str = "0001067983",
) -> FundRef:
    return FundRef(key=key, name=name, source=source, cik=cik)


def _holding(
    cusip: str,
    issuer: str,
    *,
    shares: str,
    value: str,
    weight: str = "0.05",
    ticker: str | None = None,
) -> Holding:
    return Holding(
        cusip=cusip,
        issuer=issuer,
        value=Decimal(value),
        shares=Decimal(shares),
        weight=Decimal(weight),
        ticker=ticker,
    )


def _snapshot(
    fund: FundRef,
    *,
    period: dt.date,
    filed: dt.date,
    accession: str,
    total_value: str,
    holdings: tuple[Holding, ...],
) -> Snapshot:
    return Snapshot(
        fund=fund,
        period=period,
        filed=filed,
        accession=accession,
        total_value=Decimal(total_value),
        holdings=holdings,
    )


# ---------------------------------------------------------------------------
# Action classification -- the five values
# ---------------------------------------------------------------------------


def test_action_new_when_absent_then_present() -> None:
    fund = _fund()
    before = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="0001-26-000001",
        total_value="1000",
        holdings=(),
    )
    after = _snapshot(
        fund,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="0001-26-000002",
        total_value="1000",
        holdings=(_holding("111111111", "NEW CO", shares="100", value="1000"),),
    )
    result = deltas.diff(before, after)
    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.action is Action.NEW
    assert change.shares_before == Decimal(0)
    assert change.shares_after == Decimal(100)
    assert change.value_before == Decimal(0)
    assert change.value_after == Decimal(1000)


def test_action_exit_when_present_then_absent() -> None:
    fund = _fund()
    before = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="1000",
        holdings=(_holding("222222222", "GONE CO", shares="50", value="500"),),
    )
    after = _snapshot(
        fund,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="B",
        total_value="1000",
        holdings=(),
    )
    result = deltas.diff(before, after)
    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.action is Action.EXIT
    # EXIT reports zero, never None, for the absent side.
    assert change.shares_after == Decimal(0)
    assert change.value_after == Decimal(0)
    assert change.weight_after == Decimal(0)
    assert change.shares_before == Decimal(50)


def test_action_add_when_shares_rise() -> None:
    fund = _fund()
    before = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="1000",
        holdings=(_holding("333333333", "GROWER CO", shares="100", value="1000"),),
    )
    after = _snapshot(
        fund,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="B",
        total_value="1200",
        holdings=(_holding("333333333", "GROWER CO", shares="150", value="1200"),),
    )
    change = deltas.diff(before, after).changes[0]
    assert change.action is Action.ADD
    assert change.shares_delta == Decimal(50)


def test_action_trim_when_shares_fall_but_not_to_zero() -> None:
    fund = _fund()
    before = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="1000",
        holdings=(_holding("444444444", "SHRINKER CO", shares="100", value="1000"),),
    )
    after = _snapshot(
        fund,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="B",
        total_value="800",
        holdings=(_holding("444444444", "SHRINKER CO", shares="60", value="800"),),
    )
    change = deltas.diff(before, after).changes[0]
    assert change.action is Action.TRIM
    assert change.shares_delta == Decimal(-40)


def test_action_hold_when_shares_identical() -> None:
    fund = _fund()
    before = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="1000",
        holdings=(_holding("555555555", "STEADY CO", shares="100", value="1000"),),
    )
    after = _snapshot(
        fund,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="B",
        total_value="1100",
        holdings=(_holding("555555555", "STEADY CO", shares="100", value="1100"),),
    )
    change = deltas.diff(before, after).changes[0]
    assert change.action is Action.HOLD
    assert change.shares_delta == Decimal(0)


# ---------------------------------------------------------------------------
# The real Berkshire figures: Chevron (HOLD despite a $3.47bn value move) and
# Bank of America (one TRIM row across an issuer-name change on the same CUSIP)
# ---------------------------------------------------------------------------


def test_chevron_identical_shares_large_value_change_is_hold() -> None:
    """Chevron: 84,375,856 shares in both quarters; disclosed value fell $3.47bn. A value-based
    classifier calls this a large sale. Berkshire did not trade a single share, and the classifier
    here never looks at .value, so it must report HOLD."""
    fund = _fund()
    chevron_before = _holding(
        "166764100",
        "CHEVRON CORP",
        shares="84375856",
        value="17457364606",
        weight="0.10",
    )
    chevron_after = _holding(
        "166764100",
        "CHEVRON CORP",
        shares="84375856",
        value="13986141890",
        weight="0.08",
    )
    before = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="174573646060",
        holdings=(chevron_before,),
    )
    after = _snapshot(
        fund,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="B",
        total_value="174826773625",
        holdings=(chevron_after,),
    )
    change = deltas.diff(before, after).changes[0]
    assert change.action is Action.HOLD
    assert change.shares_before == Decimal("84375856")
    assert change.shares_after == Decimal("84375856")
    assert change.shares_delta == Decimal(0)
    assert change.shares_pct_change == Decimal(0)
    assert change.value_before == Decimal("17457364606")
    assert change.value_after == Decimal("13986141890")
    assert change.value_delta == Decimal("13986141890") - Decimal("17457364606")
    assert change.value_delta == Decimal("-3471222716")
    # weight can move even on a HOLD, because the denominator (total book value) moved too.
    assert change.weight_delta == Decimal("0.08") - Decimal("0.10")


def test_bank_of_america_issuer_name_change_is_one_trim_not_new_and_exit() -> None:
    """Berkshire reported CUSIP 060505104 as 'BANK AMERICA CORP' for the quarter ending
    2026-03-31 and as 'BANK OF AMER CORP' for the quarter ending 2026-06-30. Matching on name
    would fabricate an EXIT of the old name and a NEW of the new one; matching on CUSIP (as
    `diff` does) must produce exactly one TRIM row, with no NEW/EXIT pair anywhere in the
    output."""
    fund = _fund()
    before = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="60000000000",
        holdings=(
            _holding(
                "060505104",
                "BANK AMERICA CORP",
                shares="513624165",
                value="19500000000",
                weight="0.325",
            ),
        ),
    )
    after = _snapshot(
        fund,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="B",
        total_value="55000000000",
        holdings=(
            _holding(
                "060505104",
                "BANK OF AMER CORP",
                shares="483394015",
                value="18300000000",
                weight="0.333",
            ),
        ),
    )
    result = deltas.diff(before, after)
    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.cusip == "060505104"
    assert change.action is Action.TRIM
    assert change.shares_before == Decimal("513624165")
    assert change.shares_after == Decimal("483394015")
    assert change.shares_delta == Decimal("483394015") - Decimal("513624165")
    assert change.shares_delta == Decimal("-30230150")
    # The display name follows the later period's disclosure.
    assert change.issuer == "BANK OF AMER CORP"
    counts = result.counts
    assert counts[Action.NEW] == 0
    assert counts[Action.EXIT] == 0
    assert counts[Action.TRIM] == 1


# ---------------------------------------------------------------------------
# shares_pct_change, and division safety
# ---------------------------------------------------------------------------


def test_shares_pct_change_is_none_for_new_position() -> None:
    fund = _fund()
    before = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="0",
        holdings=(),
    )
    after = _snapshot(
        fund,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="B",
        total_value="1000",
        holdings=(_holding("666666666", "FRESH CO", shares="10", value="1000"),),
    )
    change = deltas.diff(before, after).changes[0]
    assert change.action is Action.NEW
    assert change.shares_pct_change is None


def test_empty_snapshots_do_not_raise_division_by_zero() -> None:
    fund = _fund()
    before = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="0",
        holdings=(),
    )
    after = _snapshot(
        fund,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="B",
        total_value="0",
        holdings=(),
    )
    result = deltas.diff(before, after)
    assert result.changes == ()
    assert result.total_value_before == Decimal(0)
    assert result.total_value_after == Decimal(0)


def test_zero_share_holding_in_both_periods_does_not_raise() -> None:
    """A holding disclosed with zero shares in the earlier period is not a case that happens in
    practice, but the guard in `_change_for` is unconditional (it checks the denominator, not the
    action), and this proves it holds even off the NEW path."""
    fund = _fund()
    zero_before = _holding("777777777", "ODD CO", shares="0", value="0", weight="0")
    zero_after = _holding("777777777", "ODD CO", shares="0", value="0", weight="0")
    before = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="0",
        holdings=(zero_before,),
    )
    after = _snapshot(
        fund,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="B",
        total_value="0",
        holdings=(zero_after,),
    )
    change = deltas.diff(before, after).changes[0]
    assert change.action is Action.HOLD
    assert change.shares_pct_change is None


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def test_changes_sorted_by_absolute_value_delta_descending_then_cusip() -> None:
    fund = _fund()
    before = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="10000",
        holdings=(
            _holding("100000001", "SMALL MOVE", shares="10", value="100"),
            _holding("100000002", "BIG MOVE", shares="10", value="100"),
        ),
    )
    after = _snapshot(
        fund,
        period=dt.date(2026, 6, 30),
        filed=dt.date(2026, 8, 14),
        accession="B",
        total_value="10000",
        holdings=(
            _holding("100000001", "SMALL MOVE", shares="10", value="110"),
            _holding("100000002", "BIG MOVE", shares="10", value="5000"),
        ),
    )
    result = deltas.diff(before, after)
    assert [c.cusip for c in result.changes] == ["100000002", "100000001"]


# ---------------------------------------------------------------------------
# latest_pair
# ---------------------------------------------------------------------------


def test_latest_pair_orders_by_period_not_filed() -> None:
    """A real iShares NPORT-P filed 2026-07-13 reports the period ending 2025-09-30 -- months
    older than one filed 2026-05-28 reporting 2026-03-31. Sorting on filed date would run this
    pair backwards."""
    fund = _fund(key="IVV", name="iShares Core S&P 500 ETF", source=Source.NPORT)
    stale_but_late_filed = _snapshot(
        fund,
        period=dt.date(2025, 9, 30),
        filed=dt.date(2026, 7, 13),
        accession="A",
        total_value="1000",
        holdings=(),
    )
    fresh_but_early_filed = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 28),
        accession="B",
        total_value="1100",
        holdings=(),
    )
    result = deltas.latest_pair([stale_but_late_filed, fresh_but_early_filed])
    assert result is not None
    before, after = result
    assert before.period == dt.date(2025, 9, 30)
    assert after.period == dt.date(2026, 3, 31)


def test_latest_pair_prefers_later_filed_for_amended_filing_of_same_period() -> None:
    fund = _fund()
    original = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="ORIGINAL",
        total_value="1000",
        holdings=(),
    )
    amended = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 6, 1),
        accession="AMENDED",
        total_value="1050",
        holdings=(),
    )
    another_period = _snapshot(
        fund,
        period=dt.date(2025, 12, 31),
        filed=dt.date(2026, 2, 12),
        accession="C",
        total_value="900",
        holdings=(),
    )
    result = deltas.latest_pair([original, amended, another_period])
    assert result is not None
    before, after = result
    assert after.accession == "AMENDED"
    assert before.period == dt.date(2025, 12, 31)


def test_latest_pair_none_for_fewer_than_two_distinct_periods() -> None:
    assert deltas.latest_pair([]) is None
    fund = _fund()
    only = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="1000",
        holdings=(),
    )
    assert deltas.latest_pair([only]) is None
    same_period_twice = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 20),
        accession="B",
        total_value="1000",
        holdings=(),
    )
    assert deltas.latest_pair([only, same_period_twice]) is None


# ---------------------------------------------------------------------------
# catalog.find / default_catalog
# ---------------------------------------------------------------------------


def test_find_is_case_insensitive() -> None:
    lower = catalog.find("qqq")
    upper = catalog.find("QQQ")
    mixed = catalog.find("QqQ")
    assert lower is not None
    assert lower.key == "QQQ"
    assert lower is upper is mixed


def test_find_returns_none_for_unknown_key() -> None:
    assert catalog.find("NOT_A_REAL_FUND") is None


def test_default_catalog_every_entry_has_a_ten_digit_cik() -> None:
    entries = catalog.default_catalog()
    assert len(entries) > 0
    for fund in entries:
        assert fund.cik, f"{fund.key} has an empty cik"
        assert len(fund.cik) == 10, f"{fund.key} cik {fund.cik!r} is not 10 characters"
        assert fund.cik.isdigit(), f"{fund.key} cik {fund.cik!r} is not all digits"


def test_default_catalog_keys_are_unique() -> None:
    entries = catalog.default_catalog()
    keys = [fund.key for fund in entries]
    assert len(keys) == len(set(keys))


def test_spy_is_absent_from_default_catalog() -> None:
    assert catalog.find("SPY") is None


# ---------------------------------------------------------------------------
# ledger_cusip_tickers
# ---------------------------------------------------------------------------


def test_ledger_cusip_tickers_missing_file_returns_empty_dict(settings: Settings) -> None:
    assert not settings.ledger_path.exists()
    assert catalog.ledger_cusip_tickers(settings) == {}


def test_ledger_cusip_tickers_reads_cusips_and_skips_null(settings: Settings) -> None:
    with ledger.connect(settings.ledger_path) as conn:
        ledger.migrate(conn)
        ledger.upsert_instrument(
            conn,
            Instrument(
                instrument_id="i-googl",
                primary_symbol="GOOGL",
                cusip="02079K305",
                name="Alphabet Class A",
                kind=InstrumentKind.EQUITY,
                is_priceable=True,
            ),
        )
        ledger.upsert_instrument(
            conn,
            Instrument(
                instrument_id="i-nvda",
                primary_symbol="NVDA",
                cusip="67066G104",
                name="NVIDIA Corp",
                kind=InstrumentKind.EQUITY,
                is_priceable=True,
            ),
        )
        # No CUSIP at all -- must not appear in the result, not even as a None value.
        ledger.upsert_instrument(
            conn,
            Instrument(
                instrument_id="i-private",
                primary_symbol="PRIVATECO",
                cusip=None,
                name="Some Private Co",
                kind=InstrumentKind.PRIVATE,
                is_priceable=False,
            ),
        )

    tickers = catalog.ledger_cusip_tickers(settings)
    assert tickers == {"02079K305": "GOOGL", "67066G104": "NVDA"}
    assert "PRIVATECO" not in tickers.values()


def test_ledger_cusip_tickers_duplicate_symbol_rows_across_accounts(settings: Settings) -> None:
    """Two instrument_id rows sharing one primary_symbol (imported from different brokers before
    cross-broker canonicalisation) must not confuse the CUSIP-keyed result -- each CUSIP maps to
    its own symbol independently of how many other rows happen to share that symbol text."""
    with ledger.connect(settings.ledger_path) as conn:
        ledger.migrate(conn)
        ledger.upsert_instrument(
            conn,
            Instrument(
                instrument_id="rh-brkb",
                primary_symbol="BRK.B",
                cusip="084670207",
                name="Berkshire Hathaway Class B",
                kind=InstrumentKind.EQUITY,
                is_priceable=True,
            ),
        )
        ledger.upsert_instrument(
            conn,
            Instrument(
                instrument_id="webull-brkb",
                primary_symbol="BRK.B",
                cusip="084670859",
                name="Berkshire Hathaway Class B (alt CUSIP)",
                kind=InstrumentKind.EQUITY,
                is_priceable=True,
            ),
        )

    tickers = catalog.ledger_cusip_tickers(settings)
    assert tickers["084670207"] == "BRK.B"
    assert tickers["084670859"] == "BRK.B"


def test_ledger_cusip_tickers_duplicate_cusip_resolves_deterministically(
    settings: Settings,
) -> None:
    """The live schema's unique index on `instrument.cusip` means two rows cannot in practice
    share one non-null CUSIP, but `ledger_cusip_tickers` does not assume that invariant holds --
    it reads ordered by (cusip, primary_symbol) and keeps the first symbol seen. This test builds
    a raw table without that constraint to exercise the tie-break directly."""
    settings.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.ledger_path)
    try:
        conn.execute(
            "CREATE TABLE instrument (instrument_id TEXT PRIMARY KEY, primary_symbol TEXT, "
            "cusip TEXT, name TEXT, kind TEXT, is_priceable INTEGER)"
        )
        conn.execute("INSERT INTO instrument VALUES ('a', 'ZZZ', 'ABC123456', 'Z Co', 'equity', 1)")
        conn.execute("INSERT INTO instrument VALUES ('b', 'AAA', 'ABC123456', 'A Co', 'equity', 1)")
        conn.commit()
    finally:
        conn.close()

    tickers = catalog.ledger_cusip_tickers(settings)
    assert tickers["ABC123456"] == "AAA"


def test_apply_tickers_fills_known_cusips_and_leaves_others_none(settings: Settings) -> None:
    fund = _fund(key="IVV", name="iShares Core S&P 500 ETF", source=Source.NPORT)
    snapshot = _snapshot(
        fund,
        period=dt.date(2026, 3, 31),
        filed=dt.date(2026, 5, 15),
        accession="A",
        total_value="2000",
        holdings=(
            _holding("02079K305", "ALPHABET INC-CL A", shares="10", value="1000"),
            _holding("999999999", "UNRESOLVED CO", shares="10", value="1000"),
        ),
    )
    result = catalog.apply_tickers(snapshot, {"02079K305": "GOOGL"})
    by_cusip = {h.cusip: h for h in result.holdings}
    assert by_cusip["02079K305"].ticker == "GOOGL"
    assert by_cusip["999999999"].ticker is None
    # Original snapshot is untouched (models are frozen, but confirm the builder does not mutate).
    original_by_cusip = {h.cusip: h for h in snapshot.holdings}
    assert original_by_cusip["02079K305"].ticker is None


class TestMedianSharesPctChange:
    """The statistic that separates a stock picker from a fund that merely changed size.

    Real figures, from the live endpoints on 2026-08-18: QQQ's Q4-2025 to Q1-2026 diff moved 99
    positions with a median of -6.07%, 75% of them inside a -5% to -7% band, while Berkshire's
    moved 13 with a median of +3.65% spanning -58.04% to +658.35%. The first is a fund shrinking;
    the second is a manager deciding. Without this figure the page reported 95 ``TRIM`` rows for
    QQQ and implied ninety-five sales that never happened.
    """

    def _delta(self, *changes: HoldingChange) -> PortfolioDelta:
        return PortfolioDelta(
            fund=FundRef(key="X", name="X", source=Source.NPORT, cik="0000000001"),
            from_period=dt.date(2025, 12, 31),
            to_period=dt.date(2026, 3, 31),
            from_accession="a",
            to_accession="b",
            total_value_before=Decimal(100),
            total_value_after=Decimal(90),
            changes=changes,
        )

    def _change(self, action: Action, pct: str | None, cusip: str) -> HoldingChange:
        return HoldingChange(
            cusip=cusip,
            issuer=cusip,
            action=action,
            shares_before=Decimal(100),
            shares_after=Decimal(100),
            shares_delta=Decimal(0),
            shares_pct_change=None if pct is None else Decimal(pct),
            value_before=Decimal(1),
            value_after=Decimal(1),
            value_delta=Decimal(0),
            weight_before=Decimal(0),
            weight_after=Decimal(0),
            weight_delta=Decimal(0),
        )

    def test_odd_count_takes_the_middle_value(self) -> None:
        delta = self._delta(
            self._change(Action.TRIM, "-0.07", "a"),
            self._change(Action.TRIM, "-0.06", "b"),
            self._change(Action.ADD, "0.01", "c"),
        )
        assert delta.median_shares_pct_change == Decimal("-0.06")

    def test_even_count_averages_the_two_middle_values(self) -> None:
        delta = self._delta(
            self._change(Action.TRIM, "-0.08", "a"),
            self._change(Action.TRIM, "-0.06", "b"),
            self._change(Action.TRIM, "-0.04", "c"),
            self._change(Action.ADD, "0.02", "d"),
        )
        assert delta.median_shares_pct_change == Decimal("-0.05")

    def test_exits_and_holds_are_excluded(self) -> None:
        """An EXIT is always exactly -100% and a HOLD exactly 0%.

        Including either measures something other than trading: a book that sold one position
        outright and trimmed nine by 6% would report a median dragged toward the single exit, and a
        book that mostly sat still would report exactly zero however hard it traded the rest.
        """
        delta = self._delta(
            self._change(Action.EXIT, "-1", "a"),
            self._change(Action.EXIT, "-1", "b"),
            self._change(Action.HOLD, "0", "c"),
            self._change(Action.HOLD, "0", "d"),
            self._change(Action.TRIM, "-0.06", "e"),
        )
        assert delta.median_shares_pct_change == Decimal("-0.06")

    def test_new_positions_carry_no_percentage_and_are_skipped(self) -> None:
        delta = self._delta(
            self._change(Action.NEW, None, "a"),
            self._change(Action.ADD, "0.25", "b"),
        )
        assert delta.median_shares_pct_change == Decimal("0.25")

    def test_none_when_nothing_was_traded(self) -> None:
        delta = self._delta(
            self._change(Action.HOLD, "0", "a"),
            self._change(Action.NEW, None, "b"),
        )
        assert delta.median_shares_pct_change is None

    def test_it_crosses_the_wire_as_a_decimal_string(self) -> None:
        """A ``computed_field``, so the page reads one implementation rather than writing a second
        median in TypeScript over decimal strings."""
        delta = self._delta(self._change(Action.TRIM, "-0.0607", "a"))
        body = json.loads(delta.model_dump_json())
        assert body["median_shares_pct_change"] == "-0.0607"
        assert Decimal(body["median_shares_pct_change"]) == Decimal("-0.0607")


class TestCatalogPrincipals:
    """The editorial `principal` field, and the restraint it is supposed to show."""

    def test_every_named_principal_belongs_to_a_13f_filer(self) -> None:
        """An ETF has no principal. `principal` names the person behind a *manager*, and attaching
        one to a passive index fund would imply a discretion that does not exist."""
        for fund in catalog.default_catalog():
            if fund.source is Source.NPORT:
                assert fund.principal is None, fund.key

    def test_the_requested_names_are_present_and_correctly_attached(self) -> None:
        """Cathie Wood was asked for by name. ARK's *manager* 13F is a different filing from the
        ARKK ETF's NPORT-P -- the first is every account ARK manages, the second is one fund -- so
        both exist and must not be conflated."""
        by_key = {fund.key: fund for fund in catalog.default_catalog()}

        assert by_key["ARKINVEST"].principal == "Cathie Wood"
        assert by_key["ARKINVEST"].source is Source.THIRTEEN_F
        assert by_key["ARKINVEST"].cik == "0001697748"

        assert by_key["ARKK"].source is Source.NPORT
        assert by_key["ARKK"].principal is None
        assert by_key["ARKK"].cik != by_key["ARKINVEST"].cik

    def test_principals_are_omitted_where_naming_one_would_be_a_claim_about_the_past(self) -> None:
        """Renaissance's founder died in 2024; Lone Pine's stopped managing money in 2019. Both
        firms still file, and both books are somebody else's work now."""
        by_key = {fund.key: fund for fund in catalog.default_catalog()}
        assert by_key["RENTECH"].principal is None
        assert by_key["LONEPINE"].principal is None

    def test_every_catalog_entry_has_a_plausible_cik_and_a_unique_key(self) -> None:
        """A wrong CIK does not fail -- it shows a stranger's book under a famous name."""
        entries = catalog.default_catalog()
        keys = [fund.key for fund in entries]
        assert len(keys) == len(set(keys))
        for fund in entries:
            assert len(fund.cik) == 10 and fund.cik.isdigit(), fund.key
            assert fund.key == fund.key.strip() and " " not in fund.key, fund.key
            assert fund.name.strip(), fund.key
