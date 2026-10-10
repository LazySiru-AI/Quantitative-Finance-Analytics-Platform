"""HTTP-layer tests for `app.api.workflow` -- specifically the screen-mode (dynamic universe) wiring
added to `/book`, `/book/execute`, `/study`, and the new `/candidates` route over the candidate-
observation log.

Follows `tests/test_api_agents.py`'s pattern: a bare `FastAPI()` app around just this router, not
`app.main.app`, so this file exercises only `app.api.workflow` -- the real service/study/candidates
functions underneath already have their own test coverage (`tests/test_workflow_phase_b.py` for the
book/execute fill path this file mirrors, `tests/test_workflow_candidates.py` and
`tests/test_workflow_study.py`, if either exists, for the modules themselves).

The `settings` fixture (from `tests/conftest.py`) redirects every `INVDASH_*` path into a `tmp_path`
tree; every test below takes it as a parameter (even ones that touch no files) so `get_settings()`
inside the router always resolves to that isolated tree, never the real repo's `data/` directory.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import workflow as workflow_api
from app.config import Settings
from app.db import duck
from app.db.duck import BAR_COLUMNS, Interval
from app.paper.marketdata import clear_frame_cache
from app.workflow import book as book_mod
from app.workflow import candidates as candidates_mod
from app.workflow.book_models import OrderPlan
from app.workflow.candidates import CandidateObservation, GateDecision
from app.workflow.pipeline import STARTING_CASH

_D = dt.date(2024, 3, 1)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """A bare app around just the workflow router -- `app.main` is not exercised here, matching
    `tests/test_api_agents.py`'s own `app` fixture for the same reason."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(workflow_api.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers -- mirrors tests/test_workflow_phase_b.py's own helpers exactly.
# ---------------------------------------------------------------------------


def _write_bar(settings: Settings, symbol: str, day: dt.date, *, open_: float, close: float) -> None:
    frame = pd.DataFrame(
        {
            "ts": pd.Series([dt.datetime.combine(day, dt.time.min, tzinfo=dt.UTC)], dtype="datetime64[us, UTC]"),
            "open": [open_],
            "high": [max(open_, close) + 5.0],
            "low": [min(open_, close) - 5.0],
            "close": [close],
            "adj_close": [close],
            "volume": [1_000_000],
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)
    clear_frame_cache()


def _stage_screen_order(settings: Settings, arm: str, symbol: str, *, fill_date: dt.date) -> None:
    book = book_mod.load_book(
        settings, arm, starting_cash=STARTING_CASH, card_id="c", universe_source="screen"  # type: ignore[arg-type]
    )
    plan = OrderPlan(
        agent_card_id="c", symbol=symbol, side="buy", notional=Decimal("1000.00"),
        thesis="t", invalidation="i",
    )
    book = book_mod.stage_orders(book, [plan], decision_date=fill_date, fill_date=fill_date, run_id="seed")
    book_mod.save_book(settings, book)


def _observation(
    *,
    obs_id: str,
    symbol: str,
    decision_date: dt.date,
    universe_source: str = "card",
    skip_reason: str | None = None,
    gates: tuple[GateDecision, ...] = (),
    avoided_cost_usd: Decimal = Decimal("0"),
) -> CandidateObservation:
    return CandidateObservation(
        obs_id=obs_id,
        run_id="r1",
        symbol=symbol,
        decision_date=decision_date,
        agent_card_id="c1",
        universe_source=universe_source,  # type: ignore[arg-type]
        skip_reason=skip_reason,
        gates=gates,
        avoided_cost_usd=avoided_cost_usd,
    )


# ---------------------------------------------------------------------------
# GET /book?universe_source=
# ---------------------------------------------------------------------------


class TestBookUniverseSource:
    def test_default_returns_four_card_books_only(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.get("/api/workflow/book")
        assert response.status_code == 200
        books = response.json()["books"]
        assert len(books) == 4
        assert all(b["universe_source"] == "card" for b in books)

    def test_screen_filter_is_empty_when_no_screen_book_exists(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.get("/api/workflow/book", params={"universe_source": "screen"})
        assert response.status_code == 200
        assert response.json()["books"] == []

    def test_screen_filter_returns_only_the_screen_book_that_exists(
        self, client: TestClient, settings: Settings
    ) -> None:
        _write_bar(settings, "XLK", _D, open_=100.0, close=101.0)
        _stage_screen_order(settings, "raw_signal", "XLK", fill_date=_D)

        response = client.get("/api/workflow/book", params={"universe_source": "screen"})
        assert response.status_code == 200
        books = response.json()["books"]
        assert len(books) == 1
        assert books[0]["arm"] == "raw_signal"
        assert books[0]["universe_source"] == "screen"

    def test_card_filter_returns_only_four_card_books_even_with_a_screen_book_present(
        self, client: TestClient, settings: Settings
    ) -> None:
        _write_bar(settings, "XLK", _D, open_=100.0, close=101.0)
        _stage_screen_order(settings, "raw_signal", "XLK", fill_date=_D)

        response = client.get("/api/workflow/book", params={"universe_source": "card"})
        assert response.status_code == 200
        books = response.json()["books"]
        assert len(books) == 4
        assert all(b["universe_source"] == "card" for b in books)


# ---------------------------------------------------------------------------
# POST /book/execute
# ---------------------------------------------------------------------------


class TestExecuteBookUniverseSource:
    def test_screen_fills_a_due_order_and_never_creates_a_card_book(
        self, client: TestClient, settings: Settings
    ) -> None:
        _write_bar(settings, "SPY", _D, open_=500.0, close=501.0)
        _write_bar(settings, "XLK", _D, open_=100.0, close=101.0)
        _stage_screen_order(settings, "raw_signal", "XLK", fill_date=_D)

        response = client.post(
            "/api/workflow/book/execute",
            json={"as_of": _D.isoformat(), "universe_source": "screen"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["filled"] == 1
        assert body["universe_source"] == "screen"
        assert book_mod.book_path(settings, "raw_signal", universe_source="screen").is_file()
        assert not book_mod.book_path(settings, "raw_signal", universe_source="card").is_file()

        book = book_mod.load_book(
            settings, "raw_signal", starting_cash=STARTING_CASH, card_id="", universe_source="screen"
        )
        assert any(p.date == _D for p in book.equity_curve), (
            "POST /book/execute must also mark the equity curve, not just fill orders"
        )

        # The filled position must reach the wire in the contract's `WorkflowBookPosition` shape
        # (`qty`/`avg_cost`/`market_value`), not the broker snapshot's own `quantity`/`mark` shape --
        # the page's money formatter throws on an undefined `avg_cost`, which is exactly what took
        # the Agent Workflow page down the first time a book held a position.
        view = client.get("/api/workflow/book", params={"universe_source": "screen"}).json()
        positions = view["books"][0]["positions"]
        assert len(positions) == 1
        row = positions[0]
        assert set(row) == {"symbol", "qty", "avg_cost", "market_value"}
        assert row["symbol"] == "XLK"
        assert Decimal(row["qty"]) > 0
        # 1000 notional at a 100.0 open (plus slippage) -> avg cost per share near the fill price.
        assert Decimal("99") < Decimal(row["avg_cost"]) < Decimal("102")
        assert row["market_value"] is not None and Decimal(row["market_value"]) > 0

    def test_card_fill_persists_an_equity_point(
        self, client: TestClient, settings: Settings
    ) -> None:
        _write_bar(settings, "SPY", _D, open_=500.0, close=501.0)
        _write_bar(settings, "XLK", _D, open_=100.0, close=101.0)

        book = book_mod.load_book(
            settings, "raw_signal", starting_cash=STARTING_CASH, card_id="c", card_adopted_date=_D
        )
        plan = OrderPlan(
            agent_card_id="c", symbol="XLK", side="buy", notional=Decimal("1000.00"),
            thesis="t", invalidation="i",
        )
        book = book_mod.stage_orders(book, [plan], decision_date=_D, fill_date=_D, run_id="seed")
        book_mod.save_book(settings, book)

        response = client.post(
            "/api/workflow/book/execute",
            json={"as_of": _D.isoformat(), "universe_source": "card"},
        )
        assert response.status_code == 200
        assert response.json()["filled"] == 1

        reloaded = book_mod.load_book(
            settings, "raw_signal", starting_cash=STARTING_CASH, card_id="c"
        )
        assert any(p.date == _D for p in reloaded.equity_curve)

    def test_screen_rejects_an_ineligible_arm_with_422(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.post(
            "/api/workflow/book/execute",
            json={"universe_source": "screen", "arms": ["ta_gated"]},
        )
        assert response.status_code == 422
        assert "ta_gated" in response.json()["detail"]

    def test_screen_skips_a_screen_book_that_does_not_exist(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.post(
            "/api/workflow/book/execute",
            json={"as_of": _D.isoformat(), "universe_source": "screen"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["filled"] == 0
        assert body["rejected"] == 0
        assert not book_mod.book_path(settings, "raw_signal", universe_source="screen").is_file()
        assert not book_mod.book_path(settings, "full_workflow", universe_source="screen").is_file()

    def test_card_default_echoes_universe_source(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.post("/api/workflow/book/execute", json={})
        assert response.status_code == 200
        assert response.json()["universe_source"] == "card"


# ---------------------------------------------------------------------------
# GET /study?universe_source=
# ---------------------------------------------------------------------------


class TestStudyUniverseSource:
    def test_screen_scores_only_screened_arms(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.get("/api/workflow/study", params={"universe_source": "screen"})
        assert response.status_code == 200
        arms = response.json()["arms"]
        assert {row["arm"] for row in arms} == {"raw_signal", "full_workflow"}
        assert all(row["universe_source"] == "screen" for row in arms)

    def test_default_scores_all_four_card_arms(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.get("/api/workflow/study")
        assert response.status_code == 200
        arms = response.json()["arms"]
        assert {row["arm"] for row in arms} == {
            "raw_signal", "ta_gated", "vibe_gated", "full_workflow",
        }
        assert all(row["universe_source"] == "card" for row in arms)


# ---------------------------------------------------------------------------
# GET /candidates
# ---------------------------------------------------------------------------


class TestCandidates:
    def _seed(self, settings: Settings) -> None:
        obs_screen_budget = _observation(
            obs_id="s1", symbol="AAPL", decision_date=dt.date(2024, 3, 10),
            universe_source="screen", skip_reason="budget_exhausted",
        )
        obs_screen_cached = _observation(
            obs_id="s2", symbol="MSFT", decision_date=dt.date(2024, 3, 12),
            universe_source="screen",
            gates=(GateDecision(gate="full_workflow", passed=True, verdict_source="cached"),),
            avoided_cost_usd=Decimal("4.00"),
        )
        obs_card = _observation(
            obs_id="c1", symbol="GOOG", decision_date=dt.date(2024, 3, 8),
            universe_source="card",
            gates=(GateDecision(gate="ta_gated", passed=True, verdict_source="fresh"),),
        )
        candidates_mod.append_observations(
            [obs_screen_budget, obs_screen_cached, obs_card], settings=settings
        )

    def test_screen_filter_totals_ordering_and_aggregates(
        self, client: TestClient, settings: Settings
    ) -> None:
        self._seed(settings)
        response = client.get("/api/workflow/candidates", params={"universe_source": "screen"})
        assert response.status_code == 200
        body = response.json()
        assert body["universe_source"] == "screen"
        assert body["total"] == 2
        # Newest decision_date first.
        assert [o["obs_id"] for o in body["observations"]] == ["s2", "s1"]
        assert body["skip_reasons"] == {"budget_exhausted": 1}
        assert body["verdict_sources"] == {"fresh": 0, "cached": 1, "mixed": 0}
        assert body["avoided_cost_usd"] == "4.00"

    def test_limit_truncates_observations_but_not_total(
        self, client: TestClient, settings: Settings
    ) -> None:
        self._seed(settings)
        response = client.get(
            "/api/workflow/candidates", params={"universe_source": "screen", "limit": 1}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert len(body["observations"]) == 1
        assert body["observations"][0]["obs_id"] == "s2"

    def test_card_filter_sees_only_the_card_row(
        self, client: TestClient, settings: Settings
    ) -> None:
        self._seed(settings)
        response = client.get("/api/workflow/candidates", params={"universe_source": "card"})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["observations"][0]["obs_id"] == "c1"
        assert body["verdict_sources"] == {"fresh": 1, "cached": 0, "mixed": 0}
        assert body["avoided_cost_usd"] == "0"

    def test_unfiltered_sees_all_three_rows(
        self, client: TestClient, settings: Settings
    ) -> None:
        self._seed(settings)
        response = client.get("/api/workflow/candidates")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert body["universe_source"] is None

    def test_symbol_filter(self, client: TestClient, settings: Settings) -> None:
        self._seed(settings)
        response = client.get("/api/workflow/candidates", params={"symbol": "msft"})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["observations"][0]["obs_id"] == "s2"

    def test_state_filter(self, client: TestClient, settings: Settings) -> None:
        self._seed(settings)
        response = client.get("/api/workflow/candidates", params={"state": "pending"})
        assert response.status_code == 200
        assert response.json()["total"] == 3  # every seeded row defaults to "pending"

    def test_bad_limit_is_422(self, client: TestClient, settings: Settings) -> None:
        response = client.get("/api/workflow/candidates", params={"limit": 0})
        assert response.status_code == 422
