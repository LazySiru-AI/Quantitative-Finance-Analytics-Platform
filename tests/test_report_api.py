"""The report service, its endpoints, and the export.

The properties under test are all about refusal: prose that cannot be grounded is withheld rather
than repaired, an engine that fails costs its section rather than the request, and a strategy whose
guard did not pass carries no metrics.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.backtest.models import (
    Costs,
    DrawdownBasis,
    DrawdownEpisode,
    DrawdownProfile,
    GuardReport,
    GuardStatus,
    StrategySpec,
)
from app.config import Settings
from app.db.duck import Interval
from app.main import app
from app.market.models import Bar, BarSeries, BarSource
from app.market.providers.base import ProviderUnavailable, SymbolNotFound
from app.report import service
from app.report.models import FactKind
from app.rules.models import DecisionTable


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _frame(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    close = 100.0 + rng.normal(0.0, 1.0, size=n).cumsum()
    close = np.maximum(close, 5.0)
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


def _series(n: int = 300) -> BarSeries:
    frame = _frame(n)
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
    def ensure_series(symbol: str, interval: Interval, **kwargs: object) -> BarSeries:
        if isinstance(series, Exception):
            raise series
        return series

    monkeypatch.setattr(service.store, "ensure_series", ensure_series)


def _drawdown(symbol: str = "TEST") -> DrawdownProfile:
    episode = DrawdownEpisode(
        peak_date=dt.date(2020, 3, 1),
        peak_value=120.0,
        trough_date=dt.date(2020, 6, 1),
        trough_value=60.0,
        depth=-0.5,
        bars_to_trough=60,
        recovery_date=dt.date(2021, 1, 4),
        bars_to_recovery=210,
        bars_underwater=210,
        still_underwater=False,
    )
    return DrawdownProfile(
        symbol=symbol,
        interval=Interval.DAY,
        basis=DrawdownBasis.CLOSE,
        generated_at=dt.datetime.now(dt.UTC),
        bars=300,
        first_bar=dt.date(2020, 1, 1),
        last_bar=dt.date(2020, 10, 26),
        episodes=[episode],
        episodes_considered=4,
        current=None,
    )


def _drawdown_with_live_episode(symbol: str = "TEST") -> DrawdownProfile:
    """A profile whose episode is still open, with the low and the latest print far apart.

    The gap between them is the whole point: -50% at the trough against -5% today. A fixture where
    the two coincide cannot tell the two definitions apart, which is how the original defect
    survived.
    """
    episode = DrawdownEpisode(
        peak_date=dt.date(2020, 3, 1),
        peak_value=120.0,
        trough_date=dt.date(2020, 6, 1),
        trough_value=60.0,
        depth=-0.5,
        bars_to_trough=60,
        bars_underwater=170,
        still_underwater=True,
        depth_now=-0.05,
        last_value=114.0,
        last_value_date=dt.date(2020, 10, 26),
    )
    profile = _drawdown(symbol)
    return profile.model_copy(update={"episodes": [episode], "current": episode})


class _FakeBacktest:
    def __init__(self, profile: DrawdownProfile | None = None) -> None:
        self._profile = profile

    def build_drawdown_profile(self, cfg, symbol, interval, **kwargs):  # type: ignore[no-untyped-def]
        return self._profile if self._profile is not None else _drawdown(symbol)


class _BrokenBacktest:
    def build_drawdown_profile(self, cfg, symbol, interval, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("drawdown engine exploded")


class _FakeRules:
    def build_decision_table(self, cfg, symbol, interval, **kwargs):  # type: ignore[no-untyped-def]
        return DecisionTable(
            symbol=symbol,
            interval=interval,
            generated_at=dt.datetime.now(dt.UTC),
            bars_evaluated=300,
            first_bar=dt.date(2020, 1, 1),
            last_bar=dt.date(2020, 10, 26),
            rows=[],
        )


class TestTheBundleIsTheVocabulary:
    def test_facts_carry_a_source_naming_the_engine_and_window(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A figure whose origin cannot be stated is one nobody should have put in a report."""
        _stub_store(monkeypatch, _series())
        built = service.build_report(
            settings, "TEST", Interval.DAY, backtest=_FakeBacktest(), rules=_FakeRules()
        )

        assert built.bundle.facts
        for fact in built.bundle.facts.values():
            assert fact.source, fact.id
        assert "drawdown" in built.bundle.facts["drawdown.max_depth"].source

    def test_a_failed_engine_contributes_no_facts_and_leaves_a_warning(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The failure is visible as an absence of numbers, not as plausible invented ones."""
        _stub_store(monkeypatch, _series())
        built = service.build_report(
            settings, "TEST", Interval.DAY, backtest=_BrokenBacktest(), rules=_FakeRules()
        )

        assert not any(k.startswith("drawdown.") for k in built.bundle.facts)
        assert any(w.kind == "engine_failed" for w in built.warnings)

    def test_a_failed_engine_does_not_empty_the_report(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())
        built = service.build_report(
            settings, "TEST", Interval.DAY, backtest=_BrokenBacktest(), rules=_FakeRules()
        )
        assert built.sections
        assert any(s.narrative is not None for s in built.sections)

    def test_the_drawdown_sentence_disappears_with_its_facts(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rather than rendering "the deepest decline was —"."""
        _stub_store(monkeypatch, _series())
        built = service.build_report(
            settings, "TEST", Interval.DAY, backtest=_BrokenBacktest(), rules=_FakeRules()
        )
        drawdown_section = next(s for s in built.sections if s.section_id == "drawdown")
        text = drawdown_section.narrative.text if drawdown_section.narrative else ""
        assert "deepest decline" not in text

    def test_a_boolean_fact_renders_as_a_word_not_as_true(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """"the decline has not recovered (True)" is not a sentence."""
        _stub_store(monkeypatch, _series())
        built = service.build_report(
            settings, "TEST", Interval.DAY, backtest=_FakeBacktest(), rules=_FakeRules()
        )
        fact = built.bundle.facts["drawdown.still_underwater"]
        assert fact.kind is FactKind.TEXT
        assert fact.value in {"yes", "no"}

    def test_current_drawdown_is_the_live_gap_not_the_episode_low(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fact a reader takes at face value, on the page the persona was reading.

        `drawdown.current_depth` cited the ongoing episode's *worst bar*: -15.6% for XLE while the
        gap from its peak was -1.04%, and -16.0% for XLK against -4.13%. The id is unchanged --
        a fact id is a citation key and prose written against it must keep resolving -- so this
        pins the value it now carries, and pins that the low is still reported beside it under a
        label that says which is which.
        """
        _stub_store(monkeypatch, _series())
        built = service.build_report(
            settings,
            "TEST",
            Interval.DAY,
            backtest=_FakeBacktest(profile=_drawdown_with_live_episode()),
            rules=_FakeRules(),
        )
        facts = built.bundle.facts

        # Peak 120, episode low 60 (-50%), latest print 114 (-5%).
        assert float(facts["drawdown.current_depth"].value) == pytest.approx(-0.05)
        assert float(facts["drawdown.current_episode_worst"].value) == pytest.approx(-0.5)
        assert facts["drawdown.current_depth_as_of"].value == "2020-10-26"
        assert facts["drawdown.current_depth"].label == "Current drawdown"
        assert facts["drawdown.current_episode_worst"].label == "Current episode worst"


class TestProseIsVerifiedBeforeItShips:
    def test_every_rendered_section_carries_a_passing_grounding_report(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())
        built = service.build_report(
            settings, "TEST", Interval.DAY, backtest=_FakeBacktest(), rules=_FakeRules()
        )
        rendered = [s for s in built.sections if s.narrative is not None]
        assert rendered
        for section in rendered:
            assert section.narrative is not None
            assert section.narrative.grounding.grounded is True

    def test_no_rendered_section_contains_an_unsubstituted_token(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())
        built = service.build_report(
            settings, "TEST", Interval.DAY, backtest=_FakeBacktest(), rules=_FakeRules()
        )
        for section in built.sections:
            if section.narrative is not None:
                assert "{{" not in section.narrative.text

    def test_an_ungrounded_section_is_withheld_with_its_reason_not_replaced(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No fallback sentence: substituting one would hide the only interesting thing about the
        failure, which is that the intended sentence could not be supported."""
        _stub_store(monkeypatch, _series())
        monkeypatch.setattr(
            service.narrative_module,
            "DEFAULT_NARRATORS",
            {"rogue": lambda bundle: __import__(
                "app.report.models", fromlist=["NarrativeDraft"]
            ).NarrativeDraft(text="The return was 42%.", source="test")},
        )
        built = service.build_report(
            settings, "TEST", Interval.DAY, backtest=_FakeBacktest(), rules=_FakeRules()
        )
        section = next(s for s in built.sections if s.section_id == "rogue")
        assert section.narrative is None
        assert any(w.kind == "ungrounded_narrative" for w in section.warnings)
        assert "bare_numeral" in section.warnings[0].message

    def test_the_section_keeps_its_place_when_its_prose_fails(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dropping it would leave a document whose contents silently change with the data."""
        _stub_store(monkeypatch, _series())
        monkeypatch.setattr(
            service.narrative_module,
            "DEFAULT_NARRATORS",
            {"rogue": lambda bundle: __import__(
                "app.report.models", fromlist=["NarrativeDraft"]
            ).NarrativeDraft(text="The return was 42%.", source="test")},
        )
        built = service.build_report(
            settings, "TEST", Interval.DAY, backtest=_FakeBacktest(), rules=_FakeRules()
        )
        assert [s.section_id for s in built.sections] == ["rogue"]


class TestStrategyGuarding:
    def test_a_failed_guard_produces_no_metrics(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())

        class _Rejecting:
            def check(self, expression, bars, *, interval):  # type: ignore[no-untyped-def]
                return GuardReport(status=GuardStatus.FAILED, expression=expression)

        class _NeverCalled:
            def backtest(self, *a, **k):  # type: ignore[no-untyped-def]
                raise AssertionError("the backtest must not run behind a failed guard")

        result = service.build_strategy_result(
            settings,
            "TEST",
            Interval.DAY,
            StrategySpec(entry="close > sma(20)", max_holding_bars=10),
            guards=_Rejecting(),
            strategy=_NeverCalled(),
        )
        assert result.guard.status is GuardStatus.FAILED
        assert result.metrics.total_return is None
        assert result.trades == []

    def test_the_exit_expression_is_guarded_too(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exit rule that peeks at the future is exactly as dangerous as an entry rule that does,
        and it is the one people forget to check."""
        _stub_store(monkeypatch, _series())
        checked: list[str] = []

        class _Recording:
            def check(self, expression, bars, *, interval):  # type: ignore[no-untyped-def]
                checked.append(expression)
                return GuardReport(
                    status=GuardStatus.PASSED if "close" in expression else GuardStatus.FAILED,
                    expression=expression,
                )

        class _NeverCalled:
            def backtest(self, *a, **k):  # type: ignore[no-untyped-def]
                raise AssertionError("must not run")

        result = service.build_strategy_result(
            settings,
            "TEST",
            Interval.DAY,
            StrategySpec(entry="close > sma(20)", exit="rsi(14) > 70"),
            guards=_Recording(),
            strategy=_NeverCalled(),
        )
        assert checked == ["close > sma(20)", "rsi(14) > 70"]
        assert result.guard.status is GuardStatus.FAILED
        assert result.guard.expression == "rsi(14) > 70"

    def test_unverified_is_treated_as_a_failure(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())

        class _Unverified:
            def check(self, expression, bars, *, interval):  # type: ignore[no-untyped-def]
                return GuardReport(status=GuardStatus.UNVERIFIED, expression=expression)

        class _NeverCalled:
            def backtest(self, *a, **k):  # type: ignore[no-untyped-def]
                raise AssertionError("must not run")

        result = service.build_strategy_result(
            settings,
            "TEST",
            Interval.DAY,
            StrategySpec(entry="close > sma(20)", max_holding_bars=5),
            guards=_Unverified(),
            strategy=_NeverCalled(),
        )
        assert result.metrics.total_return is None

    def test_an_empty_store_is_a_warning_not_an_error(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series(0))
        result = service.build_strategy_result(
            settings,
            "TEST",
            Interval.DAY,
            StrategySpec(entry="close > sma(20)", max_holding_bars=5),
        )
        assert result.bars == 0
        assert any(w.kind == "short_history" for w in result.warnings)


class TestEndpoints:
    def test_report_returns_its_shape(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())
        response = client.get("/api/report?symbol=TEST")
        assert response.status_code == 200
        body = response.json()
        assert {"symbol", "bundle", "sections", "disclaimer"} <= set(body)
        assert body["disclaimer"]

    def test_facts_returns_the_bundle_alone(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, _series())
        response = client.get("/api/report/facts?symbol=TEST")
        assert response.status_code == 200
        assert "facts" in response.json()

    def test_export_is_markdown_with_a_fact_table(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fact table is what makes the exported document checkable away from this app."""
        _stub_store(monkeypatch, _series())
        response = client.get("/api/report/export?symbol=TEST")
        assert response.status_code == 200
        assert "text/markdown" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]
        text = response.text
        assert text.startswith("# TEST")
        assert "| Figure | Value | Source |" in text
        assert "{{" not in text  # nothing unsubstituted escapes into a document

    def test_a_strategy_with_no_exit_and_no_horizon_is_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/report/strategy", json={"symbol": "TEST", "entry": "close > sma(20)"}
        )
        assert response.status_code == 422
        assert "exit rule" in response.json()["detail"]

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"symbol": "T", "entry": "x", "stop_loss_pct": 0.0}, id="stop 0"),
            pytest.param({"symbol": "T", "entry": "x", "stop_loss_pct": 1.0}, id="stop 1"),
            pytest.param({"symbol": "T", "entry": "x" * 501}, id="entry too long"),
            pytest.param({"symbol": "T", "entry": "x", "max_holding_bars": 0}, id="zero horizon"),
            pytest.param({"symbol": "T", "entry": "x", "slippage_bps": -1}, id="negative slippage"),
            pytest.param({"symbol": "../x", "entry": "x"}, id="path in symbol"),
            pytest.param({"symbol": "T"}, id="no entry"),
        ],
    )
    def test_strategy_input_is_bounded(self, client: TestClient, body: dict[str, object]) -> None:
        assert client.post("/api/report/strategy", json=body).status_code == 422

    def test_an_unknown_symbol_is_404(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, SymbolNotFound("NOPE", provider="test"))
        assert client.get("/api/report?symbol=NOPE").status_code == 404

    def test_every_provider_down_is_503(
        self, client: TestClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub_store(monkeypatch, ProviderUnavailable("down", provider="test"))
        assert client.get("/api/report?symbol=TEST").status_code == 503

    def test_a_malformed_interval_never_reaches_the_handler(self, client: TestClient) -> None:
        assert client.get("/api/report?symbol=T&interval=3y").status_code == 422

    def test_the_openapi_schema_lists_every_endpoint(self, client: TestClient) -> None:
        paths = set(client.get("/openapi.json").json()["paths"])
        assert {
            "/api/report",
            "/api/report/facts",
            "/api/report/strategy",
            "/api/report/export",
        } <= paths


class TestCostsDefault:
    def test_slippage_defaults_to_non_zero(self) -> None:
        """Zero-cost is a choice a caller may make; it should not be what happens when nobody thought
        about it."""
        assert Costs().slippage_bps > 0
