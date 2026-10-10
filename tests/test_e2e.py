"""End-to-end verification against ``docs/PLAN.md``'s Verification checklist.

Four items, and what each test class below actually proves:

* **Portfolio holdings reconcile to broker positions** -- there is no dedicated positions/holdings
  endpoint or service function in this codebase yet (no ``app/core/holdings.py``, no
  ``/api/portfolio`` or ``/api/positions`` route -- ``app/main.py`` mounts exactly eight routers:
  backtest, health, macro, market, report, rules, tax, thesis). The nearest available mechanism is
  :func:`app.core.lots.build_lots`, whose ``open_lots()`` is what any future positions view would be
  built on. ``TestPortfolioHoldingsReconciliation`` exercises that mechanism directly, through
  synthetic transactions, and demonstrates the exact shape of the expected Webull discrepancy the
  plan describes (Orders Records carry no transfers-in, so a sale with nothing bought in that export
  reads as an oversell -- see ``data/README.md``'s "Still needed" section). This is a proxy: the
  real ledger was confirmed empty (``GET /api/health/stores`` -> ``txn: 0``) during this verification
  session, and there is no ingestion endpoint or CLI to populate it -- only ``app/ingest/adapters/*``
  and ``app/db/sqlite.py``'s write primitives exist, with no orchestrating function wiring them
  together. Hard rule 1 forbids opening the real ``data/*.csv`` files to drive that pipeline by hand,
  so this file does not attempt it. See the session report for the full finding.

* **Tax page emits Form 8949 rows.** Already covered end-to-end, including a wash-sale scenario run
  through the real HTTP boundary against a seeded SQLite ledger, by
  ``tests/test_tax_engine.py::TestTaxApi``. Nothing is duplicated here.

* **Macro page loads with the Fear & Greed source labelled.** Already covered end-to-end, both the
  CNN-success and the composite-fallback path, by ``tests/test_macro_api.py``. Confirmed live against
  the running server during this session (``GET /api/macro/fear-greed`` -> ``"source": "cnn"``).
  Nothing is duplicated here.

* **All routes answer**, including the two hazard cases the verification brief names by symbol --
  FONO (no data at the provider) and DRAM (89 stored daily bars, far under the 250 the thesis loop's
  holdout requires, see ``app.thesis.holdout.MIN_HOLDOUT_BARS``). ``TestErrorAndEmptyPaths`` pins
  both shapes, network-free, via a fake provider injected through each router's own ``_registry()``
  seam (the same pattern ``tests/test_market_api.py`` and friends already use). Both scenarios were
  also confirmed live against the running server first; see the session report for the raw output.

Every fixture here is either synthetic (built by hand, matching ``tests/conftest.py``'s
``make_txn``/``sample_account`` helpers) or points storage at ``tmp_path`` via the shared ``settings``
fixture. Nothing in this file reads ``data/*.csv``, opens ``data/store/ledger.sqlite`` directly, or
depends on network access.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.api import market as market_api
from app.api import report as report_api
from app.api import rules as rules_api
from app.api import thesis as thesis_api
from app.config import Settings
from app.core.lots import WarningKind, build_lots
from app.core.models import Account, AccountType, Broker, ImportRecord, TaxTreatment, TxnAction
from app.db import sqlite as ledger_store
from app.db.duck import Interval
from app.main import app
from app.market.models import Profile, Quote
from app.market.providers.base import SymbolNotFound
from app.market.registry import ProviderRegistry
from tests.conftest import make_txn, sample_account

# ---------------------------------------------------------------------------
# 1. Portfolio holdings reconciliation (proxy -- see module docstring)
# ---------------------------------------------------------------------------


def _webull_margin_account(account_id: str = "webull-margin") -> Account:
    return Account(
        account_id=account_id,
        broker=Broker.WEBULL,
        label="Webull Margin",
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=AccountType.MARGIN,
    )


class TestPortfolioHoldingsReconciliation:
    """``build_lots`` is the replay engine any real positions view would sit on top of. These two
    cases are the two ends of the checklist item: a clean broker reconciles exactly, and a
    Webull-shaped partial export produces a *named, machine-readable* discrepancy rather than a
    silently wrong number.
    """

    def test_clean_broker_reconciles_to_an_exact_open_position(self) -> None:
        buy = make_txn(
            txn_id="rh-buy-1",
            action=TxnAction.BUY,
            symbol="SOXL",
            quantity="50",
            price="24.10",
            amount="-1205.00",
            trade_date=dt.date(2025, 3, 1),
            account_id="rh-taxable",
        )
        result = build_lots([buy], accounts={"rh-taxable": sample_account()})

        open_by_account = {lot.account_id: lot for lot in result.open_lots()}
        assert open_by_account["rh-taxable"].quantity == Decimal("50")
        assert open_by_account["rh-taxable"].cost_basis == Decimal("1205.00")
        assert result.warnings == []

    def test_webull_orders_only_export_reconciles_partially_as_the_plan_predicts(self) -> None:
        """Webull's Orders Records omit transfers-in, dividends and fees (``data/README.md``). A
        sale with no matching buy in that export is not a replay bug -- it is the documented gap,
        and the plan records that a Webull discrepancy traceable to it is expected behaviour, not a
        defect. This reproduces exactly that shape: the excess is booked at zero basis (which
        overstates the gain -- conservative, never a fabricated favourable number) and is named by
        a ``WarningKind.OVERSOLD`` warning that identifies the account, not swallowed silently.
        """
        sell = make_txn(
            txn_id="wb-sell-1",
            action=TxnAction.SELL,
            symbol="SOXL",
            quantity="44",
            price="12.00",
            amount="528.00",
            trade_date=dt.date(2025, 6, 1),
            account_id="webull-margin",
        )
        result = build_lots([sell], accounts={"webull-margin": _webull_margin_account()})

        oversold = [w for w in result.warnings if w.kind is WarningKind.OVERSOLD]
        assert len(oversold) == 1
        assert "webull-margin" in oversold[0].detail
        assert oversold[0].quantity == Decimal("44")
        assert result.disposals[0].cost_basis == Decimal(0)
        assert result.disposals[0].proceeds == Decimal("528.00")


class TestIdempotentImport:
    """The plan requires that importing the same file twice changes nothing (``data/README.md``:
    "Re-importing is safe"). ``app/db/sqlite.py::insert_transactions`` is the service function that
    guarantees this; ``tests/test_stores.py`` already exercises it directly and thoroughly. This
    reinforces it one layer up, at the point a caller actually cares about: the ledger's fingerprint
    (``GET /api/health/stores``' staleness signal) must not move on a repeat import, because a moving
    fingerprint would mark every derived figure stale for no reason.
    """

    def test_reimport_does_not_move_the_ledger_fingerprint(self, conn) -> None:  # type: ignore[no-untyped-def]
        # `txn.import_id` is a foreign key into `raw_import` -- every transaction must trace back to
        # a file, so the provenance row is written first, matching `tests/test_tax_engine.py`'s
        # `_record_import` helper.
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
                row_count=2,
                usable_row_count=2,
                imported_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            ),
        )
        txns = [
            make_txn(txn_id="a", trade_date=dt.date(2025, 3, 1)),
            make_txn(
                txn_id="b",
                action=TxnAction.SELL,
                quantity="50",
                price="30.00",
                amount="1500.00",
                trade_date=dt.date(2025, 6, 1),
            ),
        ]

        first = ledger_store.insert_transactions(conn, txns)
        fingerprint_1, count_1 = ledger_store.ledger_fingerprint(conn)
        assert (first.inserted, first.duplicates, first.conflicts) == (2, 0, [])

        second = ledger_store.insert_transactions(conn, txns)
        fingerprint_2, count_2 = ledger_store.ledger_fingerprint(conn)
        assert (second.inserted, second.duplicates, second.conflicts) == (0, 2, [])
        assert second.is_clean

        assert (fingerprint_1, count_1) == (fingerprint_2, count_2)


# ---------------------------------------------------------------------------
# 4. All routes answer, including the FONO / DRAM hazard cases
# ---------------------------------------------------------------------------

#: Synthetic bar count for a short-history symbol: far under the 250-bar holdout floor. The fake provider
#: serves exactly this many rows, so no network or real store is touched.
_DRAM_BAR_COUNT = 89


def _ascending_daily_bars(n: int, *, end: dt.date) -> pd.DataFrame:
    """A deterministic, gently ascending daily series ending on ``end`` -- shaped like real bars,
    matching the fixture pattern ``tests/test_market_api.py`` already uses."""
    stamps = [
        dt.datetime.combine(end - dt.timedelta(days=(n - 1 - i)), dt.time.min, tzinfo=dt.UTC)
        for i in range(n)
    ]
    closes = [50.0 + i * 0.3 for i in range(n)]
    return pd.DataFrame(
        {
            "ts": pd.Series(stamps, dtype="datetime64[us, UTC]"),
            "open": [c - 0.5 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000 + i for i in range(n)],
        }
    )


class _NamedSymbolProvider:
    """Serves a fixed frame for each known symbol; raises :class:`SymbolNotFound` for anything else.

    The error text matches what Yahoo actually returned for FONO when this was checked live
    (``"yahoo has no chart data for 'FONO'"``), so this fake pins the real message, not an
    approximation of it.
    """

    name = "yahoo"
    supported_intervals = frozenset({Interval.DAY})

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def _miss(self, symbol: str) -> SymbolNotFound:
        return SymbolNotFound(f"yahoo has no chart data for {symbol!r}", provider="yahoo")

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> pd.DataFrame:
        if symbol not in self.frames:
            raise self._miss(symbol)
        return self.frames[symbol].copy()

    def fetch_quote(self, symbol: str) -> Quote:
        if symbol not in self.frames:
            raise self._miss(symbol)
        return Quote(symbol=symbol, price=50.75, ts=dt.datetime.now(dt.UTC))

    def fetch_profile(self, symbol: str) -> Profile:
        if symbol not in self.frames:
            raise self._miss(symbol)
        return Profile(symbol=symbol, name=f"{symbol} Test", instrument_type="ETF")


@pytest.fixture
def edge_client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client wired to a fake provider that knows only DRAM (89 bars, matching the real store) --
    FONO is deliberately absent, matching the real provider's 404.

    The fake is injected through every market-data-touching router's own ``_registry()`` seam
    (``app.api.market``, ``rules``, ``backtest``, ``report``, ``thesis`` each define one -- see their
    own docstrings for why each duplicates rather than imports the others'), the same mechanism
    ``tests/test_market_api.py`` and its siblings already use. Storage is redirected to ``tmp_path``
    by the shared ``settings`` fixture, so nothing here can touch the real store.
    """
    frames = {"DRAM": _ascending_daily_bars(_DRAM_BAR_COUNT, end=dt.date.today())}
    provider = _NamedSymbolProvider(frames)
    registry = ProviderRegistry(
        bar_providers=[provider], profile_providers=[provider], fundamentals_providers=[]
    )
    for module in (market_api, rules_api, backtest_api, report_api, thesis_api):
        monkeypatch.setattr(module, "_registry", lambda reg=registry: reg)
    return TestClient(app)


class TestErrorAndEmptyPaths:
    """FONO has no data at the provider; DRAM has only 89 daily bars, far below the 250 the thesis
    loop's holdout needs. Both must produce clean, explanatory refusals -- never a 500, never a
    fabricated number.
    """

    def test_unknown_symbol_is_a_clean_404_everywhere_it_is_asked_for(
        self, edge_client: TestClient
    ) -> None:
        get_paths = (
            "/api/market/bars?symbol=FONO&interval=1d",
            "/api/market/quote?symbol=FONO",
            "/api/market/profile?symbol=FONO",
            "/api/market/ticker/FONO",
            "/api/rules/decisions?symbol=FONO&interval=1d",
            "/api/backtest/drawdowns?symbol=FONO&interval=1d",
            "/api/report?symbol=FONO&interval=1d",
            "/api/report/facts?symbol=FONO&interval=1d",
        )
        for path in get_paths:
            response = edge_client.get(path)
            assert response.status_code == 404, (path, response.text)
            assert "FONO" in response.json()["detail"]

        run = edge_client.post(
            "/api/thesis/run", json={"symbol": "FONO", "interval": "1d", "budget": 1}
        )
        assert run.status_code == 404
        assert "FONO" in run.json()["detail"]

    def test_short_history_symbol_degrades_honestly_rather_than_500ing(
        self, edge_client: TestClient
    ) -> None:
        bars = edge_client.get("/api/market/bars?symbol=DRAM&interval=1d")
        assert bars.status_code == 200
        assert len(bars.json()["bars"]) == _DRAM_BAR_COUNT

        # sma:200's warmup (199) exceeds the entire 89-bar series: every point must come back as an
        # honest `null`, never a fabricated value -- and the response having parsed as JSON at all
        # already proves no bare `NaN` token leaked through (see app.market.models.jsonable_float).
        indicators = edge_client.get(
            "/api/market/indicators?symbol=DRAM&interval=1d&spec=sma:200"
        )
        assert indicators.status_code == 200
        column = indicators.json()["series"][0]["columns"]["sma_200"]
        assert len(column) == _DRAM_BAR_COUNT
        assert all(value is None for value in column)

        simple_get_paths = (
            "/api/rules/decisions?symbol=DRAM&interval=1d",
            "/api/backtest/drawdowns?symbol=DRAM&interval=1d",
            "/api/report?symbol=DRAM&interval=1d",
            "/api/report/facts?symbol=DRAM&interval=1d",
            "/api/report/export?symbol=DRAM&interval=1d",
        )
        for path in simple_get_paths:
            response = edge_client.get(path)
            assert response.status_code == 200, (path, response.text)

        posts = (
            (
                "/api/backtest/event-study",
                {"symbol": "DRAM", "interval": "1d", "conditions": ["close > sma(20)"]},
            ),
            (
                "/api/backtest/scan",
                {
                    "symbol": "DRAM",
                    "interval": "1d",
                    "expressions": ["close > sma(20)", "rsi(14) < 30"],
                },
            ),
            ("/api/backtest/reverse", {"symbol": "DRAM", "interval": "1d"}),
            (
                "/api/report/strategy",
                {
                    "symbol": "DRAM",
                    "interval": "1d",
                    "entry": "close > sma(20)",
                    "max_holding_bars": 10,
                },
            ),
        )
        for path, body in posts:
            response = edge_client.post(path, json=body)
            assert response.status_code == 200, (path, response.text)

        # The thesis loop's holdout guard is the one place 89 bars is not merely thin but genuinely
        # unprocessable: `MIN_HOLDOUT_BARS` is 250, so this must be a 422 naming the shortfall, not a
        # 200 the caller has to inspect to notice (see app.api.thesis's module docstring).
        run = edge_client.post(
            "/api/thesis/run", json={"symbol": "DRAM", "interval": "1d", "budget": 1}
        )
        assert run.status_code == 422
        assert "250" in run.json()["detail"]


def _all_route_paths() -> set[str]:
    """Every mounted path, recursing into ``_IncludedRouter``-style wrappers.

    Newer Starlette versions do not flatten an included router's routes into ``app.routes`` directly
    -- ``app.include_router(...)`` leaves a wrapper object there instead, whose real routes live on
    ``.routes`` or ``.original_router.routes`` depending on the wrapper. Walking both attributes
    (whichever is present) keeps this working across the version this app pins and older ones that
    flatten routes directly, rather than hard-coding today's internal shape.
    """
    paths: set[str] = set()

    def walk(routes: object) -> None:
        for route in routes or ():  # type: ignore[union-attr]
            path = getattr(route, "path", None)
            if path is not None:
                paths.add(path)
            nested = getattr(route, "routes", None)
            if nested is None:
                original = getattr(route, "original_router", None)
                nested = getattr(original, "routes", None) if original is not None else None
            if nested:
                walk(nested)

    walk(app.routes)
    return paths


class TestRoutersAreAllMounted:
    """A cheap guard against a router silently failing to register -- each prefix below corresponds
    to one of the eight routers `app/main.py` includes."""

    def test_every_router_prefix_is_registered(self) -> None:
        paths = _all_route_paths()
        for expected in (
            "/api/health",
            "/api/health/stores",
            "/api/macro/snapshot",
            "/api/macro/fear-greed",
            "/api/market/bars",
            "/api/market/indicators/catalog",
            "/api/report",
            "/api/rules/catalog",
            "/api/rules/decisions",
            "/api/tax/report",
            "/api/tax/form8949.csv",
            "/api/backtest/drawdowns",
            "/api/backtest/scan",
            "/api/thesis/run",
            "/api/thesis/catalogue",
        ):
            assert expected in paths, expected

    def test_parameterless_get_routes_all_respond(self, settings: Settings) -> None:
        with TestClient(app) as client:
            for path in (
                "/",
                "/api/health",
                "/api/health/stores",
                "/api/market/indicators/catalog",
                "/api/rules/catalog",
                "/api/thesis/catalogue",
            ):
                response = client.get(path)
                assert response.status_code == 200, (path, response.text)
