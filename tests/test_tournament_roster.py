"""Tests for `app.tournament.roster.tradeable_universe`.

Every ledger and bar-store fixture here is synthetic, built directly against `tmp_path` through the
`settings` fixture -- never the user's real ledger or real bar store, per this module's scope. The
point of each test is to isolate exactly one of the four gates in `tradeable_universe` so a failure
here says unambiguously which rule broke.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Sequence

import pandas as pd

from app.config import Settings
from app.core.models import TxnAction
from app.db import duck
from app.db import sqlite as ledger
from app.tournament.models import DESIGN_THROUGH, TRADE_END
from app.tournament.roster import (
    RosterEntry,
    format_roster,
    qualified_symbols,
    tradeable_universe,
)
from tests.conftest import make_txn


def _business_days(start: str, end: str, *, skip: tuple[str, str] | None = None) -> list[dt.date]:
    """Business-day dates in ``[start, end]``, optionally dropping a contiguous inclusive range.

    ``skip`` carves a hole out of otherwise-continuous coverage -- how the gap-exclusion test builds
    a symbol whose bars stop and then resume mid-trading-window.
    """
    dates = [ts.date() for ts in pd.bdate_range(start=start, end=end)]
    if skip is not None:
        skip_start = dt.date.fromisoformat(skip[0])
        skip_end = dt.date.fromisoformat(skip[1])
        dates = [d for d in dates if not (skip_start <= d <= skip_end)]
    return dates


def _frame(dates: Sequence[dt.date], close: float = 100.0) -> pd.DataFrame:
    ts = pd.to_datetime(list(dates), utc=True)
    n = len(dates)
    return pd.DataFrame(
        {
            "ts": ts,
            "open": [close] * n,
            "high": [close + 1] * n,
            "low": [close - 1] * n,
            "close": [close] * n,
            "adj_close": [close] * n,
            "volume": [1_000] * n,
        }
    )


def _write(settings: Settings, symbol: str, dates: Sequence[dt.date]) -> None:
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, duck.Interval.DAY, _frame(dates))


def _ensure_raw_import(conn: sqlite3.Connection, import_id: str = "imp1") -> None:
    """`txn.import_id` is a foreign key into `raw_import` -- every transaction must trace back to
    one, so each test that inserts transactions needs a matching row first. `INSERT OR IGNORE` makes
    this safe to call once per symbol even though every `make_txn` call shares the same import id."""
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, "
        "usable_row_count, imported_at) VALUES (?, 'p', 'f.csv', 'sha', 'content', "
        "'robinhood', 'rh-taxable', 'robinhood', '1', 1, 1, '2026-01-01T00:00:00Z')",
        (import_id,),
    )


def _insert_txns(conn: sqlite3.Connection, symbol: str, count: int) -> None:
    _ensure_raw_import(conn)
    txns = [
        make_txn(
            txn_id=f"{symbol}-{i}",
            symbol=symbol,
            trade_date=dt.date(2026, 3, 1) + dt.timedelta(days=i),
        )
        for i in range(count)
    ]
    report = ledger.insert_transactions(conn, txns)
    assert not report.conflicts


#: Full, gapless coverage spanning well before DESIGN_THROUGH through TRADE_END -- 402 design bars,
#: 131 trading-window bars, both comfortably clearing the defaults. Used as the "everything is fine"
#: baseline that every exclusion test starts from, so a test that expects one specific rejection
#: reason cannot be passing because of some other rule firing instead.
_FULL_COVERAGE_START = "2024-08-01"


def _find(entries: tuple[RosterEntry, ...], symbol: str) -> RosterEntry:
    for e in entries:
        if e.symbol == symbol:
            return e
    raise AssertionError(f"{symbol} missing from roster entries: {[e.symbol for e in entries]}")


class TestQualifies:
    def test_full_coverage_and_enough_transactions_qualifies(
        self, settings: Settings, conn: sqlite3.Connection
    ) -> None:
        _insert_txns(conn, "GOOD", 8)
        _write(settings, "GOOD", _business_days(_FULL_COVERAGE_START, TRADE_END.isoformat()))

        entries = tradeable_universe(settings)
        entry = _find(entries, "GOOD")

        assert entry.qualifies is True
        assert entry.reasons == ()
        assert entry.txn_count == 8
        assert entry.first_bar == dt.date.fromisoformat(_FULL_COVERAGE_START)
        assert entry.last_bar == TRADE_END
        assert entry.design_bars >= 250
        assert entry.trading_bars > 100
        assert "GOOD" in qualified_symbols(entries)

    def test_exclusions_are_reported_not_dropped(
        self, settings: Settings, conn: sqlite3.Connection
    ) -> None:
        """The headline requirement: every symbol the ledger ever saw comes back, and a rejected
        one carries the reason -- an analyst (or this test) never has to re-derive why."""
        _insert_txns(conn, "GOOD", 8)
        _write(settings, "GOOD", _business_days(_FULL_COVERAGE_START, TRADE_END.isoformat()))
        _insert_txns(conn, "THIN", 2)
        _write(settings, "THIN", _business_days(_FULL_COVERAGE_START, TRADE_END.isoformat()))

        entries = tradeable_universe(settings)

        assert {e.symbol for e in entries} == {"GOOD", "THIN"}
        thin = _find(entries, "THIN")
        assert thin.qualifies is False
        assert thin.reasons != ()
        assert any("transaction" in reason for reason in thin.reasons)
        assert "THIN" not in qualified_symbols(entries)


class TestMinTxnsExclusion:
    def test_below_min_txns_is_excluded_with_reason(
        self, settings: Settings, conn: sqlite3.Connection
    ) -> None:
        _insert_txns(conn, "RARE", 2)
        _write(settings, "RARE", _business_days(_FULL_COVERAGE_START, TRADE_END.isoformat()))

        entries = tradeable_universe(settings, min_txns=5)
        entry = _find(entries, "RARE")

        assert entry.qualifies is False
        assert entry.txn_count == 2
        assert any("min_txns=5" in reason for reason in entry.reasons)
        # Bars were fine -- this symbol must not also be rejected for a reason it did not earn.
        assert not any("gap" in reason or "DESIGN_THROUGH" in reason for reason in entry.reasons)


class TestGapExclusion:
    def test_gap_mid_trading_window_is_excluded_with_reason(
        self, settings: Settings, conn: sqlite3.Connection
    ) -> None:
        _insert_txns(conn, "GAPPY", 8)
        dates = _business_days(
            _FULL_COVERAGE_START, TRADE_END.isoformat(), skip=("2026-04-01", "2026-04-20")
        )
        _write(settings, "GAPPY", dates)

        entries = tradeable_universe(settings)
        entry = _find(entries, "GAPPY")

        assert entry.qualifies is False
        assert entry.design_bars >= 250  # design history itself was untouched by the skip
        assert any("gap" in reason and "calendar-day" in reason for reason in entry.reasons)
        assert entry.max_gap_days is not None
        assert entry.max_gap_days > 10

    def test_bars_ending_before_trade_end_is_excluded_with_reason(
        self, settings: Settings, conn: sqlite3.Connection
    ) -> None:
        """Distinct failure mode from an interior gap: the symbol simply stopped trading (or being
        fetched) before the tournament's last session -- delisted or stale, not merely gappy."""
        _insert_txns(conn, "STALE", 8)
        dates = _business_days(_FULL_COVERAGE_START, "2026-06-01")
        _write(settings, "STALE", dates)

        entries = tradeable_universe(settings)
        entry = _find(entries, "STALE")

        assert entry.qualifies is False
        assert entry.last_bar == dt.date(2026, 6, 1)
        assert any("before TRADE_END" in reason or "delisted" in reason for reason in entry.reasons)


class TestDesignHistoryExclusion:
    def test_too_little_design_history_is_excluded_with_reason(
        self, settings: Settings, conn: sqlite3.Connection
    ) -> None:
        _insert_txns(conn, "NEWLISTING", 8)
        # Bars start two and a half weeks before DESIGN_THROUGH and run gaplessly through
        # TRADE_END, so this symbol fails *only* the design-history gate.
        dates = _business_days("2026-01-26", TRADE_END.isoformat())
        assert dt.date(2026, 1, 26) < DESIGN_THROUGH
        _write(settings, "NEWLISTING", dates)

        entries = tradeable_universe(settings)
        entry = _find(entries, "NEWLISTING")

        assert entry.qualifies is False
        assert entry.design_bars < 250
        assert any("min_design_bars=250" in reason for reason in entry.reasons)
        assert not any("gap" in reason or "TRADE_END" in reason for reason in entry.reasons)


class TestLeveragedExclusion:
    def test_leveraged_etf_is_excluded(self, settings: Settings, conn: sqlite3.Connection) -> None:
        """SOXL is in `app.thesis.instruments.REGISTRY` -- a daily-reset 3x fund excluded on that
        repository data, independent of whether its own bars/transactions would otherwise qualify."""
        _insert_txns(conn, "SOXL", 8)
        _write(settings, "SOXL", _business_days(_FULL_COVERAGE_START, TRADE_END.isoformat()))

        entries = tradeable_universe(settings)
        entry = _find(entries, "SOXL")

        assert entry.qualifies is False
        assert any("leveraged" in reason.lower() for reason in entry.reasons)
        assert any("REGISTRY" in reason for reason in entry.reasons)

    def test_brief_asserted_leveraged_symbol_is_excluded(
        self, settings: Settings, conn: sqlite3.Connection
    ) -> None:
        """QLD is not in `app.thesis.instruments.REGISTRY` but is still excluded, on the weaker,
        explicitly-labelled basis recorded in `roster._BRIEF_ASSERTED_LEVERAGED`."""
        _insert_txns(conn, "QLD", 8)
        _write(settings, "QLD", _business_days(_FULL_COVERAGE_START, TRADE_END.isoformat()))

        entries = tradeable_universe(settings)
        entry = _find(entries, "QLD")

        assert entry.qualifies is False
        assert any("leveraged" in reason.lower() for reason in entry.reasons)
        assert any("not in app.thesis.instruments.REGISTRY" in reason for reason in entry.reasons)


class TestNoBars:
    def test_no_stored_bars_is_excluded_with_reason(
        self, settings: Settings, conn: sqlite3.Connection
    ) -> None:
        _insert_txns(conn, "NODATA", 8)
        # No call to _write: nothing is stored for this symbol at all.

        entries = tradeable_universe(settings)
        entry = _find(entries, "NODATA")

        assert entry.qualifies is False
        assert entry.first_bar is None
        assert entry.last_bar is None
        assert entry.design_bars == 0
        assert entry.trading_bars == 0
        assert any("no daily bars stored" in reason for reason in entry.reasons)


class TestHelpers:
    def test_format_roster_shows_qualified_and_excluded_with_reasons(
        self, settings: Settings, conn: sqlite3.Connection
    ) -> None:
        _insert_txns(conn, "GOOD", 8)
        _write(settings, "GOOD", _business_days(_FULL_COVERAGE_START, TRADE_END.isoformat()))
        _insert_txns(conn, "RARE", 1)
        _write(settings, "RARE", _business_days(_FULL_COVERAGE_START, TRADE_END.isoformat()))

        entries = tradeable_universe(settings)
        text = format_roster(entries)

        assert "QUALIFIED" in text
        assert "EXCLUDED" in text
        assert "GOOD" in text
        assert "RARE" in text
        assert "min_txns=5" in text  # the exclusion reason itself must be visible in the listing

    def test_qualified_symbols_excludes_rejected(
        self, settings: Settings, conn: sqlite3.Connection
    ) -> None:
        _insert_txns(conn, "GOOD", 8)
        _write(settings, "GOOD", _business_days(_FULL_COVERAGE_START, TRADE_END.isoformat()))
        _insert_txns(conn, "RARE", 1)
        _write(settings, "RARE", _business_days(_FULL_COVERAGE_START, TRADE_END.isoformat()))

        entries = tradeable_universe(settings)

        assert qualified_symbols(entries) == ("GOOD",)


class TestActionCoverage:
    """Sanity check that `make_txn`'s default action produces rows the ledger schema accepts, so a
    failure in the tests above is never actually a fixture-setup problem in disguise."""

    def test_insert_txns_helper_writes_buys(self, conn: sqlite3.Connection) -> None:
        _insert_txns(conn, "GOOD", 3)
        rows = conn.execute("SELECT COUNT(*) AS n FROM txn WHERE symbol = 'GOOD'").fetchone()
        assert rows["n"] == 3
        action = conn.execute("SELECT action FROM txn WHERE symbol = 'GOOD' LIMIT 1").fetchone()
        assert action["action"] == TxnAction.BUY.value
