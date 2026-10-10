"""Integration tests for the event calendar HTTP API (`app.api.calendar` over `app.market.calendar`).

`app.main` does not wire this router yet, the same situation `tests/test_macro_api.py` documents for
`app.api.macro` -- see that file's module docstring for why the `app` fixture below builds its own
minimal `FastAPI` app around `calendar_api.router` rather than importing `app.main`.

`app.market.fomc` and `app.market.providers.nasdaq_earnings` are pinned interfaces this module's
aggregator (`app.market.calendar`) imports directly and calls by their module-level names
(`fomc_events`, `NasdaqEarningsProvider`), the same way `app.market.macro` calls `_default_fred` /
`_default_cnn` by name. Every test below replaces those two names on the `app.market.calendar` module
object via `monkeypatch`, so nothing here makes a network call and nothing here depends on either
upstream module's own implementation -- only on the pinned signatures both were built against.

The ledger is seeded through the real SQLite write path (`app.db.sqlite.migrate` /
`upsert_account` / `upsert_instrument` / `insert_transactions`), mirroring
`tests/test_portfolio_api.py`'s pattern, because `app.market.calendar._eligible_held_symbols` replays
that same ledger through `app.core.canonical.canonicalize_ledger` / `app.core.lots.build_lots` /
`app.core.holdings.build_positions` -- there is no shortcut that writes an `InstrumentHolding`
directly without going through the real replay.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import calendar as calendar_api
from app.config import Settings
from app.core.models import (
    Account,
    AccountType,
    Broker,
    Instrument,
    InstrumentKind,
    TaxTreatment,
    TxnAction,
)
from app.db import sqlite as ledger
from app.market import calendar as calendar_module
from app.market.calendar_models import (
    CalendarEvent,
    EventConfidence,
    EventKind,
    EventSource,
    SessionTiming,
)
from app.market.models import MarketWarning
from app.market.providers.base import ProviderUnavailable
from tests.conftest import make_txn

TODAY = dt.date.today()

RH_TAXABLE = Account(
    account_id="rh-taxable",
    broker=Broker.ROBINHOOD,
    label="RH Taxable",
    tax_treatment=TaxTreatment.TAXABLE,
    account_type=AccountType.CASH,
)


# ---------------------------------------------------------------------------
# Fakes -- see the module docstring for why these are not the real fomc/nasdaq modules
# ---------------------------------------------------------------------------


def _fomc_event(day: dt.date, *, title: str = "FOMC meeting") -> CalendarEvent:
    return CalendarEvent(
        kind=EventKind.FOMC,
        title=title,
        date=day,
        timing=SessionTiming.DURING_SESSION,
        confidence=EventConfidence.CONFIRMED,
        source=EventSource.FEDERAL_RESERVE,
    )


def _earnings_event(day: dt.date, symbol: str) -> CalendarEvent:
    return CalendarEvent(
        kind=EventKind.EARNINGS,
        title=f"{symbol} earnings",
        date=day,
        timing=SessionTiming.AFTER_CLOSE,
        confidence=EventConfidence.CONFIRMED,
        source=EventSource.NASDAQ,
        symbol=symbol,
        detail="consensus EPS $1.23",
    )


def fake_fomc(
    events: tuple[CalendarEvent, ...] = (), warnings: tuple = ()
):
    """A drop-in replacement for `app.market.fomc.fomc_events`, matching its pinned signature."""

    def _fake(*, start: dt.date, end: dt.date, client: object) -> tuple[tuple, tuple]:
        return events, warnings

    return _fake


def fake_releases(events: tuple[CalendarEvent, ...] = (), warnings: tuple = ()):
    """A drop-in replacement for `app.market.releases.release_events`, matching its signature."""

    def _fake(
        *, start: dt.date, end: dt.date, settings: object, client: object
    ) -> tuple[tuple, tuple]:
        return events, warnings

    return _fake


@pytest.fixture(autouse=True)
def _no_live_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the economic-release source out of every test in this file by default.

    Autouse and unconditional, for the same reason `tests/conftest.py` pins
    `INVDASH_REFRESH_ON_STARTUP` rather than trusting the model default: `release_events` returns
    nothing without a FRED key, and `_detach_dotenv` normally guarantees there is none -- but it
    deliberately leaves `os.environ` alone, so a developer who exported `INVDASH_FRED_API_KEY` in
    their shell would otherwise have every test in this file make six live requests to FRED. The
    tests that are *about* releases override this with their own `fake_releases`.
    """
    monkeypatch.setattr(calendar_module, "release_events", fake_releases())


def _release_event(day: dt.date, title: str = "PCE inflation (Personal Income and Outlays)") -> CalendarEvent:
    return CalendarEvent(
        kind=EventKind.ECONOMIC_RELEASE,
        title=title,
        date=day,
        timing=SessionTiming.BEFORE_OPEN,
        confidence=EventConfidence.CONFIRMED,
        source=EventSource.FRED,
        detail="BEA -- the Fed's preferred inflation gauge",
    )


def make_fake_earnings_provider(
    events_by_day: dict[dt.date, tuple[CalendarEvent, ...]] | None = None,
    *,
    skipped_by_day: dict[dt.date, int] | None = None,
    fail_on: set[dt.date] | None = None,
    fail_exc: type[Exception] = ProviderUnavailable,
    calls: list[dt.date] | None = None,
) -> type:
    """Builds a fresh fake `NasdaqEarningsProvider` class.

    A class, not an instance, because `app.market.calendar._sweep_earnings` constructs
    `NasdaqEarningsProvider(client)` itself -- the fake must be substitutable at that call site.
    `calls` (if supplied) is appended to on every `fetch_earnings_for_day`, which is what lets a test
    assert exactly how many sweep days ran without needing to reach into the aggregator's internals.
    """
    events_by_day = events_by_day or {}
    skipped_by_day = skipped_by_day or {}
    fail_on = fail_on or set()
    call_log = calls if calls is not None else []

    class _FakeNasdaqEarningsProvider:
        name = "nasdaq"

        def __init__(self, client: object) -> None:
            self.client = client
            self.last_skipped = 0

        def fetch_earnings_for_day(self, day: dt.date) -> tuple[CalendarEvent, ...]:
            call_log.append(day)
            if day in fail_on:
                raise fail_exc(f"nasdaq unavailable for {day.isoformat()}", provider="nasdaq")
            self.last_skipped = skipped_by_day.get(day, 0)
            return events_by_day.get(day, ())

    _FakeNasdaqEarningsProvider.calls = call_log  # type: ignore[attr-defined]
    return _FakeNasdaqEarningsProvider


# ---------------------------------------------------------------------------
# Ledger seeding -- mirrors tests/test_portfolio_api.py
# ---------------------------------------------------------------------------


def _record_import(conn: sqlite3.Connection, import_id: str = "imp-rh") -> None:
    """Satisfy the provenance foreign key `insert_transactions` requires."""
    conn.execute(
        "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
        "content_hash, broker, account_id, adapter, adapter_version, row_count, "
        "usable_row_count, imported_at) VALUES (?, 'p', 'f.csv', ?, ?, 'robinhood', "
        "'rh-taxable', 'robinhood', '1', 1, 1, '2026-01-01T00:00:00Z')",
        (import_id, f"sha-{import_id}", f"content-{import_id}"),
    )


def _seed_holdings(settings: Settings, holdings: dict[str, InstrumentKind]) -> None:
    """One open BUY position per `(symbol, kind)` pair, all in one taxable account.

    `instrument_id` is left unset on every transaction (matching `tests/conftest.make_txn`'s
    default), which means `app.core.lots.build_lots` falls back to the transaction's own `symbol` as
    the instrument id -- see `app.core.lots`'s `instrument_id or symbol` resolution. The instrument
    row upserted below therefore has to be keyed by that same symbol for the eligibility lookup in
    `app.market.calendar._is_earnings_eligible` to find it at all.
    """
    with ledger.connect(settings.ledger_path) as conn:
        ledger.migrate(conn)
        ledger.upsert_account(conn, RH_TAXABLE)
        _record_import(conn)
        for symbol, kind in holdings.items():
            ledger.upsert_instrument(
                conn, Instrument(instrument_id=symbol, primary_symbol=symbol, kind=kind)
            )
        transactions = [
            make_txn(
                txn_id=f"buy-{symbol.lower()}",
                action=TxnAction.BUY,
                symbol=symbol,
                quantity="10",
                price="100",
                amount="-1000",
                trade_date=dt.date(2024, 1, 1),
                account_id="rh-taxable",
                broker=Broker.ROBINHOOD,
                import_id="imp-rh",
                source_row=i,
            )
            for i, symbol in enumerate(holdings)
        ]
        ledger.insert_transactions(conn, transactions)


# ---------------------------------------------------------------------------
# App + client
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(calendar_api.router)
    return fastapi_app


@pytest.fixture
def client(settings: Settings, app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_sorted_events_and_coverage_within_total(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_holdings(
            settings, {"AAPL": InstrumentKind.EQUITY, "MSFT": InstrumentKind.EQUITY}
        )

        fomc_day = TODAY + dt.timedelta(days=10)
        aapl_day = TODAY + dt.timedelta(days=5)  # MSFT reports the same day: exercises the tiebreak

        monkeypatch.setattr(
            calendar_module, "fomc_events", fake_fomc(events=(_fomc_event(fomc_day),))
        )
        earnings_by_day = {
            aapl_day: (_earnings_event(aapl_day, "MSFT"), _earnings_event(aapl_day, "AAPL")),
        }
        monkeypatch.setattr(
            calendar_module,
            "NasdaqEarningsProvider",
            make_fake_earnings_provider(earnings_by_day),
        )

        response = client.get("/api/calendar/events?days=60")

        assert response.status_code == 200
        body = response.json()
        assert body["holdings_total"] == 2
        assert body["holdings_covered"] <= body["holdings_total"]
        assert body["holdings_covered"] == 2

        dates = [e["date"] for e in body["events"]]
        assert dates == sorted(dates)
        # Same-day tiebreak: kind ("earnings" < "fomc" alphabetically) is not in play here since both
        # earnings events share `aapl_day` and the fomc event is on a later date -- so within
        # `aapl_day`, symbol order (AAPL before MSFT) is what is actually being checked.
        same_day = [e for e in body["events"] if e["date"] == aapl_day.isoformat()]
        assert [e["symbol"] for e in same_day] == ["AAPL", "MSFT"]

    def test_response_matches_the_event_calendar_shape(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_holdings(settings, {})
        monkeypatch.setattr(calendar_module, "fomc_events", fake_fomc())
        monkeypatch.setattr(
            calendar_module, "NasdaqEarningsProvider", make_fake_earnings_provider()
        )

        body = client.get("/api/calendar/events").json()
        assert set(body) == {
            "generated_at",
            "start",
            "end",
            "events",
            "holdings_total",
            "holdings_covered",
            "warnings",
        }


# ---------------------------------------------------------------------------
# 2. Earnings provider failure is non-fatal
# ---------------------------------------------------------------------------


class TestEarningsProviderFailure:
    def test_provider_unavailable_still_returns_200_with_fomc_intact(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_holdings(settings, {"AAPL": InstrumentKind.EQUITY})
        fomc_day = TODAY + dt.timedelta(days=3)
        monkeypatch.setattr(
            calendar_module, "fomc_events", fake_fomc(events=(_fomc_event(fomc_day),))
        )

        # Every day in the sweep window fails -- the fake raises unconditionally regardless of `day`.
        class _AlwaysDown:
            name = "nasdaq"

            def __init__(self, client: object) -> None:
                self.last_skipped = 0

            def fetch_earnings_for_day(self, day: dt.date) -> tuple[CalendarEvent, ...]:
                raise ProviderUnavailable("nasdaq is down", provider="nasdaq")

        monkeypatch.setattr(calendar_module, "NasdaqEarningsProvider", _AlwaysDown)

        response = client.get("/api/calendar/events?days=30")

        assert response.status_code == 200
        body = response.json()
        assert len(body["events"]) == 1
        assert body["events"][0]["kind"] == "fomc"
        assert body["holdings_covered"] == 0
        assert any(w["kind"] == "provider_fallback" for w in body["warnings"])
        assert any("nasdaq" in w["message"] for w in body["warnings"])


# ---------------------------------------------------------------------------
# 3. The 45-day earnings cap
# ---------------------------------------------------------------------------


class TestEarningsHorizonCap:
    def test_days_90_caps_the_sweep_at_45_days_and_warns(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_holdings(settings, {"AAPL": InstrumentKind.EQUITY})
        monkeypatch.setattr(calendar_module, "fomc_events", fake_fomc())
        calls: list[dt.date] = []
        monkeypatch.setattr(
            calendar_module,
            "NasdaqEarningsProvider",
            make_fake_earnings_provider(calls=calls),
        )

        response = client.get("/api/calendar/events?days=90")

        assert response.status_code == 200
        body = response.json()
        assert any(w["kind"] == "partial_window" for w in body["warnings"])
        # Inclusive [today, today+45]: 46 distinct calendar days, never 90+1.
        assert len(calls) == 46
        assert (max(calls) - min(calls)).days == 45

    def test_days_within_the_cap_does_not_warn(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_holdings(settings, {"AAPL": InstrumentKind.EQUITY})
        monkeypatch.setattr(calendar_module, "fomc_events", fake_fomc())
        calls: list[dt.date] = []
        monkeypatch.setattr(
            calendar_module,
            "NasdaqEarningsProvider",
            make_fake_earnings_provider(calls=calls),
        )

        response = client.get("/api/calendar/events?days=30")

        assert response.status_code == 200
        body = response.json()
        assert not any(w["kind"] == "partial_window" for w in body["warnings"])
        assert len(calls) == 31


# ---------------------------------------------------------------------------
# 4. Held vs. not-held filtering
# ---------------------------------------------------------------------------


class TestHoldingsFilter:
    def test_unheld_symbol_dropped_held_symbol_kept(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_holdings(settings, {"AAPL": InstrumentKind.EQUITY})
        monkeypatch.setattr(calendar_module, "fomc_events", fake_fomc())
        day = TODAY + dt.timedelta(days=2)
        earnings_by_day = {
            day: (_earnings_event(day, "AAPL"), _earnings_event(day, "GOOG")),
        }
        monkeypatch.setattr(
            calendar_module,
            "NasdaqEarningsProvider",
            make_fake_earnings_provider(earnings_by_day),
        )

        response = client.get("/api/calendar/events?days=30")

        assert response.status_code == 200
        body = response.json()
        symbols = {e["symbol"] for e in body["events"] if e["kind"] == "earnings"}
        assert symbols == {"AAPL"}
        assert body["holdings_covered"] == 1
        assert body["holdings_total"] == 1


# ---------------------------------------------------------------------------
# 5. `days` validation
# ---------------------------------------------------------------------------


class TestDaysValidation:
    @pytest.mark.parametrize("days", [0, 400])
    def test_out_of_range_days_is_422(self, client: TestClient, days: int) -> None:
        response = client.get(f"/api/calendar/events?days={days}")
        assert response.status_code == 422

    def test_boundary_values_are_accepted(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_holdings(settings, {})
        monkeypatch.setattr(calendar_module, "fomc_events", fake_fomc())
        monkeypatch.setattr(
            calendar_module, "NasdaqEarningsProvider", make_fake_earnings_provider()
        )
        assert client.get("/api/calendar/events?days=1").status_code == 200
        assert client.get("/api/calendar/events?days=365").status_code == 200


# ---------------------------------------------------------------------------
# 6. Empty ledger
# ---------------------------------------------------------------------------


class TestEmptyLedger:
    def test_no_ledger_file_at_all(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No _seed_holdings call at all: settings.ledger_path never gets created.
        assert not settings.ledger_path.exists()
        fomc_day = TODAY + dt.timedelta(days=1)
        monkeypatch.setattr(
            calendar_module, "fomc_events", fake_fomc(events=(_fomc_event(fomc_day),))
        )
        calls: list[dt.date] = []
        monkeypatch.setattr(
            calendar_module,
            "NasdaqEarningsProvider",
            make_fake_earnings_provider(calls=calls),
        )

        response = client.get("/api/calendar/events?days=30")

        assert response.status_code == 200
        body = response.json()
        assert body["holdings_total"] == 0
        assert body["holdings_covered"] == 0
        assert [e for e in body["events"] if e["kind"] == "earnings"] == []
        assert len(body["events"]) == 1
        assert body["events"][0]["kind"] == "fomc"
        # No holdings at all -- the sweep must not even hit the network for nothing.
        assert calls == []

    def test_ledger_exists_but_has_no_transactions(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            ledger.upsert_account(conn, RH_TAXABLE)
        monkeypatch.setattr(calendar_module, "fomc_events", fake_fomc())
        monkeypatch.setattr(
            calendar_module, "NasdaqEarningsProvider", make_fake_earnings_provider()
        )

        response = client.get("/api/calendar/events")

        assert response.status_code == 200
        body = response.json()
        assert body["holdings_total"] == 0


# ---------------------------------------------------------------------------
# Not-earnings-eligible instrument kinds are excluded from the denominator
# ---------------------------------------------------------------------------


class TestEligibilityFilter:
    def test_etf_and_cash_are_excluded_equity_is_kept(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_holdings(
            settings,
            {
                "AAPL": InstrumentKind.EQUITY,
                "SPY": InstrumentKind.ETF,
                "USDX": InstrumentKind.CASH,
            },
        )
        monkeypatch.setattr(calendar_module, "fomc_events", fake_fomc())
        calls: list[dt.date] = []
        monkeypatch.setattr(
            calendar_module,
            "NasdaqEarningsProvider",
            make_fake_earnings_provider(calls=calls),
        )

        response = client.get("/api/calendar/events?days=1")

        assert response.status_code == 200
        assert response.json()["holdings_total"] == 1


# ---------------------------------------------------------------------------
# partial_parse aggregation
# ---------------------------------------------------------------------------


class TestPartialParse:
    def test_last_skipped_is_aggregated_into_one_warning(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_holdings(settings, {"AAPL": InstrumentKind.EQUITY})
        monkeypatch.setattr(calendar_module, "fomc_events", fake_fomc())
        # Read the clock here, not from this module's import-time `TODAY`. `app.market.calendar`
        # computes `window_start = today or dt.date.today()` when the request arrives, and this test
        # asks for a one-day window -- the narrowest there is. A suite run that crosses local
        # midnight between import and this request would leave `day1` naming yesterday, which then
        # falls outside the sweep entirely: its 2 skipped rows would be silently absent and the
        # aggregate would read "3" instead of "5". The other `TODAY` tests in this file use windows
        # of thirty days or more, where a one-day shift never reaches a boundary, so they are left
        # alone.
        day1 = dt.date.today()
        day2 = day1 + dt.timedelta(days=1)
        monkeypatch.setattr(
            calendar_module,
            "NasdaqEarningsProvider",
            make_fake_earnings_provider(skipped_by_day={day1: 2, day2: 3}),
        )

        response = client.get("/api/calendar/events?days=1")

        assert response.status_code == 200
        body = response.json()
        parse_warnings = [w for w in body["warnings"] if w["kind"] == "partial_parse"]
        assert len(parse_warnings) == 1
        assert "5" in parse_warnings[0]["message"]


# ---------------------------------------------------------------------------
# Economic releases (PCE, CPI, jobs, GDP, PPI, retail sales)
# ---------------------------------------------------------------------------


class TestEconomicReleases:
    def test_releases_are_merged_into_the_one_date_ordered_list(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not a separate section of the response -- one chronological list, which is the whole
        reason a reader can see that the CPI print lands four days before the FOMC meeting."""
        _seed_holdings(settings, {})
        pce_day = TODAY + dt.timedelta(days=2)
        fomc_day = TODAY + dt.timedelta(days=10)
        cpi_day = TODAY + dt.timedelta(days=16)

        monkeypatch.setattr(
            calendar_module, "fomc_events", fake_fomc(events=(_fomc_event(fomc_day),))
        )
        monkeypatch.setattr(
            calendar_module,
            "release_events",
            fake_releases(events=(_release_event(pce_day), _release_event(cpi_day, "CPI"))),
        )
        monkeypatch.setattr(
            calendar_module, "NasdaqEarningsProvider", make_fake_earnings_provider()
        )

        body = client.get("/api/calendar/events?days=60").json()

        rows = [(e["date"], e["kind"], e["title"]) for e in body["events"]]
        assert rows == [
            (pce_day.isoformat(), "economic_release", "PCE inflation (Personal Income and Outlays)"),
            (fomc_day.isoformat(), "fomc", "FOMC meeting"),
            (cpi_day.isoformat(), "economic_release", "CPI"),
        ]

    def test_a_release_carries_no_symbol_and_is_confirmed(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A macro print is not tied to a position, and its date comes from the agency's own
        published schedule -- so `symbol` is null and the confidence is `confirmed`, not the
        `estimated` a vendor-projected earnings date carries."""
        _seed_holdings(settings, {})
        monkeypatch.setattr(calendar_module, "fomc_events", fake_fomc())
        monkeypatch.setattr(
            calendar_module,
            "release_events",
            fake_releases(events=(_release_event(TODAY + dt.timedelta(days=1)),)),
        )
        monkeypatch.setattr(
            calendar_module, "NasdaqEarningsProvider", make_fake_earnings_provider()
        )

        [row] = client.get("/api/calendar/events").json()["events"]

        assert row["symbol"] is None
        assert row["confidence"] == "confirmed"
        assert row["source"] == "fred"
        assert row["timing"] == "before_open"

    def test_release_warnings_reach_the_response_and_cost_nothing_else(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The third source degrading must look like the other two degrading: its own warning, and
        every other source's events returned untouched. A missing FRED key must not cost a reader
        the FOMC date."""
        _seed_holdings(settings, {})
        fomc_day = TODAY + dt.timedelta(days=10)
        monkeypatch.setattr(
            calendar_module, "fomc_events", fake_fomc(events=(_fomc_event(fomc_day),))
        )
        monkeypatch.setattr(
            calendar_module,
            "release_events",
            fake_releases(
                warnings=(
                    MarketWarning(kind="config", message="economic release dates need a FRED key"),
                )
            ),
        )
        monkeypatch.setattr(
            calendar_module, "NasdaqEarningsProvider", make_fake_earnings_provider()
        )

        body = client.get("/api/calendar/events?days=60").json()

        # `in`, not `==`: `days=60` also emits the earnings horizon's own `partial_window` warning,
        # and pinning the whole list here would make this test about that unrelated cap.
        assert "config" in [w["kind"] for w in body["warnings"]]
        assert [e["kind"] for e in body["events"]] == ["fomc"]
