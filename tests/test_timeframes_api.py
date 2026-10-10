"""Integration tests for the multi-timeframe rule-accuracy HTTP layer (`app.api.timeframes`) and its
background sweep job (`app.timeframes.jobs`).

This is the HTTP layer and the job machinery, not the statistics -- every test here fakes
`app.timeframes.service` (`compute_cells`/`aggregate`/`signal_trace`) rather than importing the real
module, the same way `tests/test_rules_api.py` fakes `app.rules.grammar`/`app.rules.evaluate`. That
module is being written concurrently against the frozen contract in `app.timeframes.models`
(`docs/research/timeframes/06-interface-contract.md`) and may not exist, or may not be complete, at
any point while this file runs -- nothing here depends on it.

`app.main` already wires this router (`app.include_router(timeframes.router)`), but the `app` fixture
below builds its own minimal `FastAPI` app around `timeframes_api.router`, matching
`tests/test_rules_api.py` and `tests/test_competition_jobs.py`'s identical choice: these tests only
depend on the router object and the modules it calls into, not on the rest of the application wiring.

Polling is bounded everywhere `_poll_until` is used: it sleeps in short increments up to a fixed
timeout and fails with a clear message rather than hanging if a sweep never reaches the expected
state.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from typing import Any, Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import timeframes as timeframes_api
from app.db.duck import Interval
from app.timeframes import jobs
from app.timeframes.models import (
    DEFAULT_COST_BPS,
    MIN_INDEPENDENT,
    RESEARCH_UNIVERSE,
    RuleAccuracyCell,
)

_UTC = dt.UTC
_FIRST_BAR = dt.datetime(2024, 1, 1, tzinfo=_UTC)
_LAST_BAR = dt.datetime(2026, 1, 1, tzinfo=_UTC)


# ---------------------------------------------------------------------------
# Cell factory -- builds real, validator-passing `RuleAccuracyCell`s
# ---------------------------------------------------------------------------


def _make_cell(
    *,
    symbol: str,
    interval: Interval,
    rule_id: str = "rsi_oversold",
    sufficient: bool = True,
    cost_bps: float = DEFAULT_COST_BPS,
) -> RuleAccuracyCell:
    """A minimal, invariant-satisfying cell for `symbol`/`interval`/`rule_id`. `sufficient=False`
    produces a cell with every statistic `None`, exercising `RuleAccuracyCell`'s own gate."""
    if sufficient:
        n_independent = MIN_INDEPENDENT + 5
        stats: dict[str, Any] = {
            "hit_rate": 0.55,
            "base_rate": 0.50,
            "lift": 0.05,
            "lift_ci_low": 0.01,
            "lift_ci_high": 0.09,
            "median_return": 0.001,
            "baseline_median_return": 0.0005,
            "p_value": 0.03,
            "q_value": 0.05,
            "cost_adjusted_edge": 0.03,
        }
    else:
        n_independent = MIN_INDEPENDENT - 5
        stats = {}

    return RuleAccuracyCell(
        rule_id=rule_id,
        interval=interval,
        scope="symbol",
        scope_key=symbol,
        horizon_bars=1,
        horizon_minutes=5,
        horizon_label="~1 bar",
        n_raw=n_independent + 10,
        n_episodes=n_independent + 3,
        n_independent=n_independent,
        sufficient=sufficient,
        cost_bps_assumed=cost_bps,
        regime="all",
        first_bar=_FIRST_BAR,
        last_bar=_LAST_BAR,
        warnings=(),
        **stats,
    )


# ---------------------------------------------------------------------------
# Fake service -- the only thing standing between these tests and a real, minutes-long sweep
# ---------------------------------------------------------------------------


class FakeService:
    """Stands in for `app.timeframes.service`. Records every `compute_cells` call it sees, raises
    for any symbol listed in `fail_symbols` (exercising the per-pair-failure path), and pools
    naively for `aggregate` -- these tests never inspect real pooling statistics, only that the
    HTTP/job layer calls through and carries the result."""

    def __init__(
        self,
        *,
        fail_symbols: frozenset[str] = frozenset(),
        delay: float = 0.0,
        rule_ids_when_none: tuple[str, ...] = ("rsi_oversold",),
    ) -> None:
        self.calls: list[tuple[tuple[str, ...], tuple[Interval, ...]]] = []
        self._fail_symbols = fail_symbols
        self._delay = delay
        self._rule_ids_when_none = rule_ids_when_none

    def compute_cells(
        self,
        *,
        symbols: list[str],
        intervals: list[Interval],
        rule_ids: list[str] | None = None,
        horizons: Any = None,
        cost_bps: float = DEFAULT_COST_BPS,
        regimes: bool = False,
        settings: Any,
    ) -> list[RuleAccuracyCell]:
        if self._delay:
            time.sleep(self._delay)
        self.calls.append((tuple(symbols), tuple(intervals)))
        ids = list(rule_ids) if rule_ids else list(self._rule_ids_when_none)
        cells: list[RuleAccuracyCell] = []
        for symbol in symbols:
            if symbol in self._fail_symbols:
                raise RuntimeError(f"synthetic fetch failure for {symbol}")
            for interval in intervals:
                for rule_id in ids:
                    cells.append(
                        _make_cell(
                            symbol=symbol, interval=interval, rule_id=rule_id, cost_bps=cost_bps
                        )
                    )
        return cells

    def aggregate(
        self, cells: list[RuleAccuracyCell], *, to: Literal["sector", "universe"]
    ) -> list[RuleAccuracyCell]:
        # Naive stand-in: one pooled cell per (rule_id, interval), summing the sample counts.
        # Real pooling semantics belong to the (separately owned) service layer; this only proves
        # the HTTP/job layer calls `aggregate` and forwards its result.
        buckets: dict[tuple[str, Interval], list[RuleAccuracyCell]] = {}
        for cell in cells:
            buckets.setdefault((cell.rule_id, cell.interval), []).append(cell)
        pooled: list[RuleAccuracyCell] = []
        for (rule_id, interval), group in buckets.items():
            n_independent = sum(c.n_independent for c in group)
            pooled.append(
                _make_cell(
                    symbol="ALL" if to == "universe" else group[0].scope_key,
                    interval=interval,
                    rule_id=rule_id,
                    sufficient=n_independent >= MIN_INDEPENDENT,
                ).model_copy(update={"scope": to, "scope_key": "ALL" if to == "universe" else "Technology"})
            )
        return pooled

    def signal_trace(self, *, symbol: str, interval: Interval, rule_id: str, settings: Any):
        from app.timeframes.models import SignalTrace

        return SignalTrace(
            symbol=symbol,
            interval=interval,
            rule_id=rule_id,
            expression=f"{rule_id}()",
            bars=[],
            indicators=[],
            fired_at=[_FIRST_BAR],
            warmup_until=None,
        )


def _poll_until(
    fetch: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    timeout: float = 5.0,
    interval: float = 0.05,
) -> Any:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fetch()
        if predicate(last):
            return last
        time.sleep(interval)
    pytest.fail(f"timed out after {timeout}s waiting for condition; last observed value: {last!r}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """A bare app around just the timeframes router -- see the module docstring."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(timeframes_api.router)
    return fastapi_app


@pytest.fixture
def fake_service() -> FakeService:
    return FakeService()


@pytest.fixture
def client(
    app: FastAPI, fake_service: FakeService, monkeypatch: pytest.MonkeyPatch, settings
) -> TestClient:
    monkeypatch.setattr(timeframes_api, "_service", lambda: fake_service)
    monkeypatch.setattr(jobs, "_service", lambda: fake_service)
    jobs.reset_registry()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_registry_after_every_test() -> None:
    """Belt and braces, matching `tests/test_competition_jobs.py`'s identical fixture: whatever a
    test leaves behind (a still-sleeping fake in a daemon thread, a populated registry) must not
    leak into the next test."""
    yield
    jobs.reset_registry()


# ---------------------------------------------------------------------------
# 1. Static metadata
# ---------------------------------------------------------------------------


class TestIntervalsEndpoint:
    def test_returns_all_seven_intervals(self, client: TestClient) -> None:
        response = client.get("/api/timeframes/intervals")
        assert response.status_code == 200
        body = response.json()
        assert [row["interval"] for row in body] == [
            "5m",
            "15m",
            "30m",
            "1h",
            "4h",
            "1d",
            "1w",
        ]
        # 1w has no native session bar count and unbounded retention -- both null, not zero.
        weekly = body[-1]
        assert weekly["bars_per_session"] is None
        assert weekly["retention_days"] is None
        assert weekly["bars_per_year"] == 52

    def test_no_service_call_required(self, client: TestClient, fake_service: FakeService) -> None:
        client.get("/api/timeframes/intervals")
        assert fake_service.calls == []


class TestUniverseEndpoint:
    def test_returns_all_twenty_symbols_with_sectors(self, client: TestClient) -> None:
        response = client.get("/api/timeframes/universe")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == len(RESEARCH_UNIVERSE) == 20
        assert {(row["symbol"], row["sector"]) for row in body} == set(RESEARCH_UNIVERSE)


# ---------------------------------------------------------------------------
# 2. GET /matrix -- synchronous slice
# ---------------------------------------------------------------------------


class TestMatrixEndpoint:
    def test_small_slice_happy_path(self, client: TestClient) -> None:
        response = client.get(
            "/api/timeframes/matrix",
            params={"symbols": "SPY", "intervals": "1d,1h", "scope": "symbol"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["coverage"]["symbols"] == 1
        assert body["coverage"]["intervals"] == 2
        assert body["coverage"]["cells_total"] == 2  # 1 symbol x 2 intervals x 1 rule
        assert body["coverage"]["cells_sufficient"] == 2
        assert body["generated_at"]
        cell = body["cells"][0]
        assert cell["scope"] == "symbol"
        assert cell["scope_key"] == "SPY"

    def test_default_scope_aggregates_to_sector(
        self, client: TestClient, fake_service: FakeService
    ) -> None:
        response = client.get(
            "/api/timeframes/matrix", params={"symbols": "SPY", "intervals": "1d"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["cells"][0]["scope"] == "sector"

    def test_21_pairs_is_422_and_names_the_pair_count(self, client: TestClient) -> None:
        # 3 symbols x default (all 7) intervals = 21 pairs, one over MAX_SYNC_PAIRS.
        response = client.get(
            "/api/timeframes/matrix", params={"symbols": "SPY,QQQ,AAPL", "scope": "symbol"}
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "21" in detail
        assert "MAX_SYNC_PAIRS" in detail or "20" in detail
        assert "/matrix/jobs" in detail

    def test_20_pairs_is_not_rejected(self, client: TestClient) -> None:
        # 2 symbols x default (all 7) intervals x ... needs exactly 20: use 4 symbols x 5 intervals.
        response = client.get(
            "/api/timeframes/matrix",
            params={
                "symbols": "SPY,QQQ,AAPL,MSFT",
                "intervals": "5m,15m,30m,1h,4h",
                "scope": "symbol",
            },
        )
        assert response.status_code == 200
        assert response.json()["coverage"]["cells_total"] == 20

    def test_unknown_interval_is_422_not_500(self, client: TestClient) -> None:
        response = client.get(
            "/api/timeframes/matrix", params={"symbols": "SPY", "intervals": "1d,3m"}
        )
        assert response.status_code == 422
        assert "3m" in response.json()["detail"]

    def test_unknown_symbol_is_422(self, client: TestClient) -> None:
        response = client.get("/api/timeframes/matrix", params={"symbols": "NOTREAL"})
        assert response.status_code == 422
        assert "NOTREAL" in response.json()["detail"]

    def test_horizon_minutes_filters_cells(self, client: TestClient) -> None:
        response = client.get(
            "/api/timeframes/matrix",
            params={"symbols": "SPY", "intervals": "1d", "horizon_minutes": 999, "scope": "symbol"},
        )
        assert response.status_code == 200
        assert response.json()["cells"] == []


# ---------------------------------------------------------------------------
# 3. GET /signal
# ---------------------------------------------------------------------------


class TestSignalEndpoint:
    def test_happy_path(self, client: TestClient) -> None:
        response = client.get(
            "/api/timeframes/signal",
            params={"symbol": "aapl", "interval": "1d", "rule_id": "rsi_oversold"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "AAPL"
        assert body["interval"] == "1d"
        assert body["rule_id"] == "rsi_oversold"
        assert len(body["fired_at"]) == 1

    def test_unknown_interval_is_422(self, client: TestClient) -> None:
        response = client.get(
            "/api/timeframes/signal",
            params={"symbol": "AAPL", "interval": "3m", "rule_id": "rsi_oversold"},
        )
        assert response.status_code == 422

    def test_an_overlong_symbol_is_422(self, client: TestClient) -> None:
        """`symbol` used to be a bare `str` here -- the only market route without
        `app.api.market.SymbolParam`'s bound. Now shares that same alphabet/length constraint."""
        response = client.get(
            "/api/timeframes/signal",
            params={"symbol": "A" * 20, "interval": "1d", "rule_id": "rsi_oversold"},
        )
        assert response.status_code == 422

    def test_a_path_traversal_shaped_symbol_is_422(self, client: TestClient) -> None:
        response = client.get(
            "/api/timeframes/signal",
            params={"symbol": "../x", "interval": "1d", "rule_id": "rsi_oversold"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# 4. POST /matrix/jobs + GET /matrix/jobs/{job_id} -- the sweep
# ---------------------------------------------------------------------------


class TestSweepCreateAndPoll:
    def test_post_returns_202_and_polling_reaches_succeeded(self, client: TestClient) -> None:
        response = client.post(
            "/api/timeframes/matrix/jobs",
            json={"symbols": ["SPY", "QQQ"], "intervals": ["1d", "1h"], "scope": "symbol"},
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] in ("queued", "running")
        assert body["total_pairs"] == 4
        job_id = body["job_id"]
        assert job_id

        final = _poll_until(
            lambda: client.get(f"/api/timeframes/matrix/jobs/{job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
        )
        assert final["status"] == "succeeded"
        assert final["completed_pairs"] == final["total_pairs"] == 4
        assert final["failed_pairs"] == 0
        assert final["current"] is None
        assert final["finished_at"] is not None
        assert len(final["cells"]) == 4  # 2 symbols x 2 intervals x 1 rule, scope=symbol
        assert final["log"]

    def test_empty_request_defaults_to_whole_universe_and_all_intervals(
        self, client: TestClient
    ) -> None:
        response = client.post("/api/timeframes/matrix/jobs", json={})
        assert response.status_code == 202
        assert response.json()["total_pairs"] == 20 * 7

        job_id = response.json()["job_id"]
        # The fake service is instant, so this drains almost immediately -- this test is about
        # resolution/defaulting (whole universe x all seven intervals), not about timing.
        final = _poll_until(
            lambda: client.get(f"/api/timeframes/matrix/jobs/{job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
        )
        assert final["status"] == "succeeded"
        assert final["completed_pairs"] == 20 * 7

    def test_get_unknown_job_id_is_404(self, client: TestClient) -> None:
        response = client.get("/api/timeframes/matrix/jobs/not-a-real-job-id")
        assert response.status_code == 404

    def test_progress_is_observable_while_running(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch, settings
    ) -> None:
        slow_service = FakeService(delay=0.2)
        monkeypatch.setattr(timeframes_api, "_service", lambda: slow_service)
        monkeypatch.setattr(jobs, "_service", lambda: slow_service)
        jobs.reset_registry()
        client = TestClient(app)

        response = client.post(
            "/api/timeframes/matrix/jobs",
            json={"symbols": ["SPY", "QQQ", "AAPL"], "intervals": ["1d"], "scope": "symbol"},
        )
        job_id = response.json()["job_id"]

        observed_running = _poll_until(
            lambda: client.get(f"/api/timeframes/matrix/jobs/{job_id}").json(),
            lambda s: s["status"] == "running" and s["current"] is not None,
        )
        assert observed_running["current"]["symbol"] in ("SPY", "QQQ", "AAPL")
        assert observed_running["total_pairs"] == 3

        _poll_until(
            lambda: client.get(f"/api/timeframes/matrix/jobs/{job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
            timeout=5.0,
        )


class TestSweepFailureIsolation:
    def test_one_pair_failing_does_not_abort_the_sweep(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch, settings
    ) -> None:
        flaky_service = FakeService(fail_symbols=frozenset({"TSLA"}))
        monkeypatch.setattr(timeframes_api, "_service", lambda: flaky_service)
        monkeypatch.setattr(jobs, "_service", lambda: flaky_service)
        jobs.reset_registry()
        client = TestClient(app)

        response = client.post(
            "/api/timeframes/matrix/jobs",
            json={"symbols": ["SPY", "TSLA"], "intervals": ["1d"], "scope": "symbol"},
        )
        job_id = response.json()["job_id"]

        final = _poll_until(
            lambda: client.get(f"/api/timeframes/matrix/jobs/{job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
        )

        assert final["status"] == "succeeded"
        assert final["completed_pairs"] == 1
        assert final["failed_pairs"] == 1
        assert len(final["failures"]) == 1
        assert final["failures"][0]["symbol"] == "TSLA"
        assert "synthetic fetch failure" in final["failures"][0]["error"]
        # SPY's cell is still there -- one symbol's failure did not lose the other's result.
        assert any(c["scope_key"] == "SPY" for c in final["cells"])


class TestSweepConcurrencyLock:
    def test_second_post_while_one_is_running_is_409_naming_the_live_job(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch, settings
    ) -> None:
        slow_service = FakeService(delay=0.3)
        monkeypatch.setattr(timeframes_api, "_service", lambda: slow_service)
        monkeypatch.setattr(jobs, "_service", lambda: slow_service)
        jobs.reset_registry()
        client = TestClient(app)

        first = client.post(
            "/api/timeframes/matrix/jobs",
            json={"symbols": ["SPY"], "intervals": ["1d"], "scope": "symbol"},
        )
        assert first.status_code == 202
        first_job_id = first.json()["job_id"]

        second = client.post(
            "/api/timeframes/matrix/jobs",
            json={"symbols": ["QQQ"], "intervals": ["1d"], "scope": "symbol"},
        )
        assert second.status_code == 409
        assert first_job_id in second.json()["detail"]

        _poll_until(
            lambda: client.get(f"/api/timeframes/matrix/jobs/{first_job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
        )

    def test_cancellation_actually_stops_the_sweep(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch, settings
    ) -> None:
        # A real, small per-pair sleep so cancellation has a window to land between pairs rather
        # than racing the whole (fake, otherwise-instant) sweep to completion.
        slow_service = FakeService(delay=0.15)
        monkeypatch.setattr(timeframes_api, "_service", lambda: slow_service)
        monkeypatch.setattr(jobs, "_service", lambda: slow_service)
        jobs.reset_registry()
        client = TestClient(app)

        response = client.post(
            "/api/timeframes/matrix/jobs",
            json={
                "symbols": ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"],
                "intervals": ["1d"],
                "scope": "symbol",
            },
        )
        job_id = response.json()["job_id"]
        assert response.json()["total_pairs"] == 5

        # Let exactly one pair complete, then cancel.
        _poll_until(
            lambda: client.get(f"/api/timeframes/matrix/jobs/{job_id}").json(),
            lambda s: s["completed_pairs"] >= 1,
        )
        status = jobs.request_cancel(job_id)
        assert status.status in ("running", "cancelled")

        final = _poll_until(
            lambda: client.get(f"/api/timeframes/matrix/jobs/{job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
        )
        assert final["status"] == "cancelled"
        # Stopped before doing all 5 -- cancellation actually cut the sweep short.
        assert final["completed_pairs"] < final["total_pairs"]


class TestSweepLockIsAllIndependentOfTournament:
    def test_a_sweep_running_does_not_block_a_tournament_job(
        self,
        app: FastAPI,
        monkeypatch: pytest.MonkeyPatch,
        settings,
        tmp_path,
    ) -> None:
        """Proves `app.timeframes.jobs`'s lock is a genuinely separate object from
        `app.tournament.jobs`'s: with a timeframes sweep still `running`, a tournament job must
        still be acceptable -- if the two shared a lock, this `start_job` call would raise
        `JobAlreadyRunning` immediately.
        """
        from decimal import Decimal

        from app.tournament import jobs as tournament_jobs
        from app.tournament.models import AgentResult, StrategyCard

        tournament_jobs.reset_registry(output_root=tmp_path)

        def _fake_run_card(
            card: StrategyCard, *, settings: object, mandate: object, start, end
        ) -> AgentResult:
            time.sleep(0.2)
            return AgentResult(
                card=card,
                sessions=1,
                starting_equity=Decimal("10000.00"),
                ending_equity=Decimal("10100.00"),
                total_return=Decimal("0.01"),
                max_drawdown=Decimal("0"),
                trades=(),
                benchmark_return=Decimal("0.0"),
                capital_exposure=0.1,
            )

        monkeypatch.setattr(tournament_jobs, "run_card", _fake_run_card)

        slow_service = FakeService(delay=0.3)
        monkeypatch.setattr(timeframes_api, "_service", lambda: slow_service)
        monkeypatch.setattr(jobs, "_service", lambda: slow_service)
        jobs.reset_registry()
        client = TestClient(app)

        sweep_response = client.post(
            "/api/timeframes/matrix/jobs",
            json={"symbols": ["SPY"], "intervals": ["1d"], "scope": "symbol"},
        )
        assert sweep_response.status_code == 202
        sweep_job_id = sweep_response.json()["job_id"]
        assert jobs.get_sweep(sweep_job_id).status == "running"

        # The tournament registry's own lock must still be free -- this must NOT raise
        # `tournament_jobs.JobAlreadyRunning`.
        accepted = tournament_jobs.start_job(
            tournament_jobs.JobCreateRequest(
                round_id="r-independent-lock-check", cards=["B-momentum"], windows=["covid"]
            )
        )
        assert accepted.status in ("queued", "running")

        _poll_until(
            lambda: client.get(f"/api/timeframes/matrix/jobs/{sweep_job_id}").json(),
            lambda s: s["status"] in ("succeeded", "failed", "cancelled"),
        )
        _poll_until(
            lambda: tournament_jobs.get_job(accepted.job_id).status,
            lambda status: status in ("succeeded", "failed", "cancelled"),
        )
        tournament_jobs.reset_registry()
