"""The backtest workbench endpoints and the service layer beneath them.

Two things are load-bearing here and are tested against fakes rather than real data, because the
point is the *seam*, not the arithmetic: a condition whose guard did not pass must never carry
numbers, and an unbounded request must be refused before a single bar is read.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.backtest import service
from app.backtest.models import (
    ConditionArm,
    Distribution,
    DrawdownBasis,
    GuardFinding,
    GuardReport,
    GuardStatus,
    HorizonStats,
    ScanResult,
)
from app.config import Settings
from app.db.duck import Interval
from app.main import app
from app.market.models import Bar, BarSeries, BarSource
from app.market.providers.base import ProviderUnavailable, SymbolNotFound


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _bars(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(4)
    close = 100.0 + rng.normal(0.0, 1.0, size=n).cumsum()
    return pd.DataFrame(
        {
            "ts": pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC"),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "adj_close": close,
            "volume": np.full(n, 1e6),
        }
    )


def _series(n: int = 200) -> BarSeries:
    frame = _bars(n)
    return BarSeries(
        symbol="TEST",
        interval=Interval.DAY,
        source=BarSource.STORE,
        bars=[
            Bar(
                ts=row.ts.to_pydatetime(),
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                adj_close=row.adj_close,
                volume=row.volume,
            )
            for row in frame.itertuples()
        ],
    )


def _stub_store(monkeypatch: pytest.MonkeyPatch, series: BarSeries | Exception) -> None:
    """Replace the one store call every builder makes. Patched on `app.backtest.service`'s own
    reference so nothing else in the process is affected."""

    def ensure_series(symbol: str, interval: Interval, **kwargs: object) -> BarSeries:
        if isinstance(series, Exception):
            raise series
        return series

    monkeypatch.setattr(service.store, "ensure_series", ensure_series)


class _PassingGuards:
    def check(self, expression: str, bars: pd.DataFrame, *, interval: Interval) -> GuardReport:
        return GuardReport(status=GuardStatus.PASSED, expression=expression, findings=[])


class _RejectingGuards:
    def __init__(self, status: GuardStatus = GuardStatus.FAILED) -> None:
        self._status = status

    def check(self, expression: str, bars: pd.DataFrame, *, interval: Interval) -> GuardReport:
        return GuardReport(
            status=self._status,
            expression=expression,
            findings=[GuardFinding(check="causality", passed=False, detail="peeks at bar t+1")],
        )


class _FakeEvents:
    def event_study(self, bars, conditions, *, interval, horizons, entry, indicator_cache=None):  # type: ignore[no-untyped-def]
        arms = [
            ConditionArm(
                label=c,
                expression=c,
                stats=[
                    HorizonStats(
                        horizon=h,
                        entry=entry,
                        hit_rate=0.6,
                        baseline_hit_rate=0.5,
                        distribution=Distribution(count=40, median=0.01),
                        baseline_distribution=Distribution(count=180, median=0.002),
                        sample_size=40,
                        independent_sample_size=35,
                        baseline_sample_size=180,
                    )
                    for h in horizons
                ],
                trigger_dates=[dt.date(2020, 6, 1)],
                triggers=40,
                evaluable_bars=180,
            )
            for c in conditions
        ]
        return arms, []

    def reverse_conditioning(self, bars, indicators, *, interval, horizon, quantile, lookback, entry):  # type: ignore[no-untyped-def]
        return [dt.date(2020, 6, 1)], 12, 3, []


class _NoRunCards:
    """Every write fails. Used to prove a study degrades to a warning rather than a 500."""

    def make(self, kind, *, symbol, interval, params, bars, results):  # type: ignore[no-untyped-def]
        raise OSError("disk full")

    def write(self, card, *, settings=None):  # type: ignore[no-untyped-def]
        raise OSError("disk full")


# ---------------------------------------------------------------------------
# The guard seam -- the property this layer exists to enforce
# ---------------------------------------------------------------------------


class TestAFailedGuardMeansNoNumbers:
    def test_a_rejected_condition_appears_with_its_report_and_no_statistics(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())
        study = service.build_event_study(
            settings,
            "TEST",
            Interval.DAY,
            ["close > 1"],
            horizons=[5],
            events=_FakeEvents(),
            guards=_RejectingGuards(),
            runcards=_NoRunCards(),
        )

        assert len(study.arms) == 1
        arm = study.arms[0]
        assert arm.guard.status is GuardStatus.FAILED
        assert arm.stats == []
        assert arm.triggers == 0
        assert any(w.kind == "guard_failed" for w in arm.warnings)

    def test_unverified_is_treated_as_a_failure_not_a_neutral_default(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The contract is explicit that `UNVERIFIED` is a failure state. A study whose guard did
        not run must not render numbers."""
        _stub_store(monkeypatch, _series())
        study = service.build_event_study(
            settings,
            "TEST",
            Interval.DAY,
            ["close > 1"],
            horizons=[5],
            events=_FakeEvents(),
            guards=_RejectingGuards(GuardStatus.UNVERIFIED),
            runcards=_NoRunCards(),
        )
        assert study.arms[0].stats == []

    def test_a_cleared_condition_does_carry_statistics(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The control for the two tests above -- otherwise they would pass against a builder that
        never produces numbers at all."""
        _stub_store(monkeypatch, _series())
        study = service.build_event_study(
            settings,
            "TEST",
            Interval.DAY,
            ["close > 1"],
            horizons=[5],
            events=_FakeEvents(),
            guards=_PassingGuards(),
            runcards=_NoRunCards(),
        )
        assert study.arms[0].guard.status is GuardStatus.PASSED
        assert study.arms[0].stats[0].hit_rate == 0.6

    def test_a_mixed_study_keeps_both_arms_in_the_order_asked_for(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())

        class _Selective:
            def check(self, expression, bars, *, interval):  # type: ignore[no-untyped-def]
                ok = expression == "good"
                return GuardReport(
                    status=GuardStatus.PASSED if ok else GuardStatus.FAILED,
                    expression=expression,
                    findings=[],
                )

        study = service.build_event_study(
            settings, "TEST", Interval.DAY, ["bad", "good"], horizons=[5],
            events=_FakeEvents(), guards=_Selective(), runcards=_NoRunCards(),
        )
        assert [a.expression for a in study.arms] == ["bad", "good"]
        assert study.arms[0].stats == []
        assert study.arms[1].stats != []

    def test_a_guard_that_raises_becomes_a_failure_not_an_exception(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())

        class _Exploding:
            def check(self, expression, bars, *, interval):  # type: ignore[no-untyped-def]
                raise RuntimeError("boom")

        study = service.build_event_study(
            settings, "TEST", Interval.DAY, ["close > 1"], horizons=[5],
            events=_FakeEvents(), guards=_Exploding(), runcards=_NoRunCards(),
        )
        assert study.arms[0].stats == []


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


class TestDegradesRatherThanFailing:
    def test_an_empty_store_is_a_warning_not_an_error(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series(0))
        study = service.build_event_study(
            settings, "TEST", Interval.DAY, ["close > 1"],
            events=_FakeEvents(), guards=_PassingGuards(), runcards=_NoRunCards(),
        )
        assert study.bars == 0
        assert study.arms == []
        assert any(w.kind == "short_history" for w in study.warnings)

    def test_a_run_card_failure_degrades_to_a_warning(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A study that computed correctly must not 500 because its audit file could not be
        written -- but it must also not claim to have been recorded."""
        _stub_store(monkeypatch, _series())
        study = service.build_event_study(
            settings, "TEST", Interval.DAY, ["close > 1"], horizons=[5],
            events=_FakeEvents(), guards=_PassingGuards(), runcards=_NoRunCards(),
        )
        assert study.run_id is None
        assert any(w.kind == "runcard_failed" for w in study.warnings)
        assert study.arms[0].stats[0].hit_rate == 0.6

    def test_a_failing_event_study_does_not_lose_the_arms(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())

        class _Broken:
            def event_study(self, *a, **k):  # type: ignore[no-untyped-def]
                raise RuntimeError("nope")

            def reverse_conditioning(self, *a, **k):  # type: ignore[no-untyped-def]
                raise RuntimeError("nope")

        study = service.build_event_study(
            settings, "TEST", Interval.DAY, ["close > 1"], horizons=[5],
            events=_Broken(), guards=_PassingGuards(), runcards=_NoRunCards(),
        )
        assert len(study.arms) == 1
        assert any(w.kind == "study_failed" for w in study.warnings)


# ---------------------------------------------------------------------------
# Scan accounting
# ---------------------------------------------------------------------------


class TestScanAccounting:
    def test_every_expression_and_horizon_consumes_a_trial(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())
        result = service.build_scan(
            settings, "TEST", Interval.DAY, ["a", "b", "c"], horizons=[5, 20],
            events=_FakeEvents(), guards=_PassingGuards(), runcards=_NoRunCards(),
        )
        assert result.trials == 6
        assert len(result.entries) == 6

    def test_guard_rejections_still_consume_their_trials(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Removing them would shrink the denominator every surviving q-value depends on."""
        _stub_store(monkeypatch, _series())
        result = service.build_scan(
            settings, "TEST", Interval.DAY, ["a", "b"], horizons=[5, 20],
            events=_FakeEvents(), guards=_RejectingGuards(), runcards=_NoRunCards(),
        )
        assert result.trials == 4
        assert all(e.stats is None and e.p_value is None for e in result.entries)
        assert result.discoveries == 0

    def test_a_filtered_entry_list_cannot_be_constructed(self) -> None:
        """Pins the model validator that makes the trial count unfakeable."""
        with pytest.raises(ValueError, match="every evaluated"):
            ScanResult(
                symbol="TEST",
                interval=Interval.DAY,
                generated_at=dt.datetime.now(dt.UTC),
                trials=40,
                entries=[],
            )


# ---------------------------------------------------------------------------
# IndicatorCache actually reaches the backtest path -- the acceptance test for the defect where
# `build_scan` constructed a cache, threaded it through `scan_mod.scan`, and then `del`'d it in the
# `evaluate` closure before it ever reached `events_mod.event_study`. `_FakeEvents` above cannot
# prove anything here -- it does no indicator computation -- so this uses the real
# `app.backtest.events` / `app.rules.evaluate` / `app.indicators.registry` collaborators end to end.
# ---------------------------------------------------------------------------


class TestIndicatorCacheReachesBuildScan:
    def _count_compute_calls(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
        """Wrap the real `app.indicators.registry.compute` to count calls without changing what it
        returns -- every caller that reaches it (guards, the evaluator) still gets real values."""
        from app.indicators import registry as indicator_registry

        calls = {"n": 0}
        real_compute = indicator_registry.compute

        def counting_compute(bars_arg, requests):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            return real_compute(bars_arg, requests)

        monkeypatch.setattr(indicator_registry, "compute", counting_compute)
        return calls

    def test_expressions_sharing_an_indicator_compute_it_once_through_build_scan(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Three expressions that all reference `rsi:14` must cost one `compute` call through
        `build_scan` (the real production entry point), not three -- otherwise the cache
        `build_scan` builds is present but inert, exactly the defect this test guards against."""
        _stub_store(monkeypatch, _series())
        calls = self._count_compute_calls(monkeypatch)
        expressions = ["rsi(14) < 30", "rsi(14) > 70", "rsi(14) < 50"]

        service.build_scan(
            settings,
            "TEST",
            Interval.DAY,
            expressions,
            horizons=[5],
            guards=_PassingGuards(),
            runcards=_NoRunCards(),
        )

        cached_calls = calls["n"]
        assert cached_calls == 1

        # Paired no-cache baseline: the same real `event_study` call `build_scan`'s `evaluate`
        # closure makes, once per expression, with no cache threaded across the calls -- exactly
        # what the closure did before this fix (`indicator_cache` was constructed and then `del`'d).
        # Measured, not asserted, so this proves a reduction rather than assuming one.
        from app.backtest import events as events_mod

        calls["n"] = 0
        bars = service._bars_frame(_series())
        for expression in expressions:
            events_mod.event_study(bars, [expression], interval=Interval.DAY, horizons=[5])
        uncached_calls = calls["n"]

        assert uncached_calls == len(expressions)
        assert cached_calls < uncached_calls


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class TestEndpoints:
    def test_drawdowns_returns_its_basis(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())
        response = client.get("/api/backtest/drawdowns?symbol=TEST&basis=intraday&top=3")
        assert response.status_code == 200
        assert response.json()["basis"] == DrawdownBasis.INTRADAY.value

    def test_event_study_returns_the_documented_shape(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())
        response = client.post(
            "/api/backtest/event-study",
            json={"symbol": "TEST", "conditions": ["close > sma(20)"], "horizons": [5, 20]},
        )
        assert response.status_code == 200
        body = response.json()
        assert {"symbol", "arms", "deltas", "horizons", "run_id"} <= set(body)

    def test_reverse_is_always_flagged_exploratory(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())
        response = client.post("/api/backtest/reverse", json={"symbol": "TEST", "horizon": 20})
        assert response.status_code == 200
        body = response.json()
        assert body["exploratory"] is True
        assert not {"hit_rate", "p_value", "q_value"} & set(body)

    def test_scan_reports_its_trial_count(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())
        response = client.post(
            "/api/backtest/scan",
            json={"symbol": "TEST", "expressions": ["close > sma(20)"], "horizons": [5]},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["trials"] == len(body["entries"])

    def test_an_unknown_symbol_is_404(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, SymbolNotFound("NOPE: no such symbol", provider="test"))
        assert client.get("/api/backtest/drawdowns?symbol=NOPE").status_code == 404

    def test_every_provider_down_is_503(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, ProviderUnavailable("all providers down", provider="test"))
        assert client.get("/api/backtest/drawdowns?symbol=TEST").status_code == 503

    def test_an_unknown_run_id_is_404(self, client: TestClient, settings: Settings) -> None:
        assert client.get("/api/backtest/runs/" + "a" * 64).status_code == 404


class TestInputBounds:
    """Expensive endpoints must refuse before reading a bar. A scan is
    `len(expressions) * len(horizons)` guarded evaluations, and each guard recomputes indicators on
    eight leading slices."""

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"symbol": "T", "expressions": []}, id="no expressions"),
            pytest.param({"symbol": "T", "expressions": ["a"] * 51}, id="too many expressions"),
            pytest.param({"symbol": "T", "expressions": ["a" * 501]}, id="expression too long"),
            pytest.param({"symbol": "T", "expressions": ["a"], "alpha": 0.0}, id="alpha 0"),
            pytest.param({"symbol": "T", "expressions": ["a"], "alpha": 1.0}, id="alpha 1"),
            pytest.param({"symbol": "T", "expressions": ["a"], "horizons": [-5]}, id="negative horizon"),
            pytest.param({"symbol": "T", "expressions": ["a"], "horizons": [0]}, id="zero horizon"),
            pytest.param({"symbol": "T", "expressions": ["a"], "horizons": [5000]}, id="huge horizon"),
            pytest.param({"symbol": "T", "expressions": ["a"], "horizons": []}, id="no horizons"),
            pytest.param({"symbol": "../etc", "expressions": ["a"]}, id="path in symbol"),
        ],
    )
    def test_scan_rejects(self, client: TestClient, body: dict[str, object]) -> None:
        assert client.post("/api/backtest/scan", json=body).status_code == 422

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"symbol": "T", "quantile": 0.0}, id="quantile 0"),
            pytest.param({"symbol": "T", "quantile": 1.0}, id="quantile 1"),
            pytest.param({"symbol": "T", "horizon": 0}, id="zero horizon"),
            pytest.param({"symbol": "T", "lookback": -1}, id="negative lookback"),
            pytest.param({"symbol": "T", "indicators": ["x"] * 21}, id="too many indicators"),
        ],
    )
    def test_reverse_rejects(self, client: TestClient, body: dict[str, object]) -> None:
        assert client.post("/api/backtest/reverse", json=body).status_code == 422

    def test_event_study_caps_the_arm_count(self, client: TestClient) -> None:
        """More than a handful of arms is an uncorrected scan wearing a friendlier name."""
        response = client.post(
            "/api/backtest/event-study",
            json={"symbol": "T", "conditions": ["a", "b", "c", "d", "e"]},
        )
        assert response.status_code == 422

    def test_a_malformed_interval_never_reaches_the_handler(self, client: TestClient) -> None:
        assert client.get("/api/backtest/drawdowns?symbol=T&interval=3y").status_code == 422

    def test_top_is_bounded(self, client: TestClient) -> None:
        assert client.get("/api/backtest/drawdowns?symbol=T&top=0").status_code == 422
        assert client.get("/api/backtest/drawdowns?symbol=T&top=101").status_code == 422


class TestRouterIsMounted:
    def test_the_openapi_schema_lists_every_endpoint(self, client: TestClient) -> None:
        """A router that is not included fails silently -- every request 404s and looks like a
        client mistake."""
        paths = set(client.get("/openapi.json").json()["paths"])
        assert {
            "/api/backtest/drawdowns",
            "/api/backtest/event-study",
            "/api/backtest/reverse",
            "/api/backtest/scan",
            "/api/backtest/runs/{run_id}",
        } <= paths
