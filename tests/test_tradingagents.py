"""Unit tests for Trading Agents: `build_stage_plan`, `parse_rating`, the pipeline orchestration, the
outcome-resolved memory log, and the router's error mapping.

No test here makes a real model call. `app.tradingagents.pipeline.run_grounded` is monkeypatched to a
fake that returns a scripted `GroundedResult` per stage's `output_format`, and
`app.agentdesk.evidence.build_pack` is monkeypatched to skip the real market-data/news/macro providers
entirely -- mirroring `tests/test_vibedesk.py`'s own convention for the sibling desk.
"""

from __future__ import annotations

import datetime as dt
import threading
from decimal import Decimal

import pandas as pd
import pytest

from app.agentdesk import evidence
from app.agentdesk.grounding import GroundedResult
from app.agentdesk.models import DeskRun, EvidencePack, GroundingVerdict
from app.agentdesk.store import RunStore
from app.agents.models import AgentBudget, AgentCall, AgentUnavailable, BudgetExhausted
from app.config import Settings
from app.tradingagents import memory, pipeline, schemas, service

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


def _empty_pack(symbol: str = "", sections: object = ()) -> EvidencePack:
    return EvidencePack(symbol=symbol, sections=())


@pytest.fixture(autouse=True)
def _no_real_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test in this module may reach the real market-data/news/macro providers."""
    monkeypatch.setattr(
        evidence, "build_pack", lambda symbol, as_of, *, settings, sections: _empty_pack(symbol, sections)
    )


def _fake_call(role: str) -> AgentCall:
    return AgentCall(
        call_id=f"call-{role}",
        role=role,  # type: ignore[arg-type]
        model="claude-opus-5",
        created_at=dt.datetime.now(dt.UTC),
        system="s",
        user="u",
        raw_response="r",
        cost_usd=Decimal("0.01"),
    )


def _budget_bump(budget: AgentBudget, cost: Decimal = Decimal("0.01")) -> AgentBudget:
    return AgentBudget(cap_usd=budget.cap_usd, spent_usd=budget.spent_usd + cost, calls=budget.calls + 1)


def _value_for(output_format: type, role: str) -> object:
    if output_format is schemas.AnalystReport:
        return schemas.AnalystReport(report_md=f"report from {role}", takeaway=f"takeaway from {role}")
    if output_format is schemas.DebateArgument:
        return schemas.DebateArgument(argument_md=f"argument from {role}", takeaway=f"takeaway from {role}")
    if output_format is schemas.ResearchPlan:
        return schemas.ResearchPlan(
            recommendation="Buy", rationale="rationale text", strategic_actions="actions text"
        )
    if output_format is schemas.TraderProposal:
        return schemas.TraderProposal(action="Buy", reasoning="reasoning text", entry="100", stop="90", sizing="2%")
    if output_format is schemas.RiskArgument:
        return schemas.RiskArgument(stance_summary=f"stance from {role}", argument=f"argument from {role}")
    if output_format is schemas.PortfolioDecision:
        return schemas.PortfolioDecision(
            rating="Buy", executive_summary="summary text", investment_thesis="thesis text"
        )
    if output_format is schemas.ReflectionNote:
        return schemas.ReflectionNote(lesson="lesson text")
    raise AssertionError(f"unexpected output_format {output_format!r}")  # pragma: no cover


def _make_fake_run_grounded(*, degrade_roles: frozenset[str] = frozenset(), fail_role: str | None = None):
    def fake(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
        if fail_role is not None and role == fail_role:
            raise BudgetExhausted(budget.cap_usd, budget.cap_usd)
        value = _value_for(output_format, role)
        degraded = role in degrade_roles
        verdict = GroundingVerdict(ok=not degraded, degraded=degraded, attempts=1)
        new_budget = _budget_bump(budget)
        return GroundedResult(value=value, verdict=verdict, calls=(_fake_call(role),), budget=new_budget)

    return fake


def _seed_run(store: RunStore, config: pipeline.PipelineConfig, *, run_id: str = "run-1") -> DeskRun:
    run = DeskRun(
        run_id=run_id,
        kind="tradingagents",
        state="queued",
        created_at=dt.datetime.now(dt.UTC),
        config={
            "symbol": config.symbol,
            "trade_date": config.trade_date.isoformat() if config.trade_date else None,
            "analysts": list(config.analysts),
            "debate_rounds": config.debate_rounds,
            "risk_rounds": config.risk_rounds,
            "budget_usd": str(config.budget_usd),
            "model": config.model,
        },
        stages=pipeline.build_stage_plan(config),
        budget=AgentBudget(cap_usd=config.budget_usd),
    )
    store.save(run)
    return run


def _config(**overrides: object) -> pipeline.PipelineConfig:
    base = dict(
        symbol="AAPL",
        trade_date=None,
        analysts=("market",),
        debate_rounds=1,
        risk_rounds=1,
        budget_usd=Decimal("5.00"),
        model="claude-opus-5",
    )
    base.update(overrides)
    return pipeline.PipelineConfig(**base)  # type: ignore[arg-type]


def _bars_frame(prices: dict[dt.date, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.to_datetime(list(prices.keys())).tz_localize("UTC"),
            "close": list(prices.values()),
        }
    )


# ---------------------------------------------------------------------------
# build_stage_plan
# ---------------------------------------------------------------------------


class TestBuildStagePlan:
    def test_default_config_matches_the_contract_ids_layers_and_dependencies(self) -> None:
        config = _config(analysts=("market", "sentiment", "news", "fundamentals"))
        stages = pipeline.build_stage_plan(config)
        ids = [stage.stage_id for stage in stages]

        assert ids == [
            "market_analyst",
            "sentiment_analyst",
            "news_analyst",
            "fundamentals_analyst",
            "bull_1",
            "bear_1",
            "research_manager",
            "trader",
            "risk_aggressive_1",
            "risk_conservative_1",
            "risk_neutral_1",
            "portfolio_manager",
        ]

        by_id = {stage.stage_id: stage for stage in stages}
        assert by_id["market_analyst"].layer == 0
        assert by_id["market_analyst"].depends_on == ()
        assert by_id["sentiment_analyst"].depends_on == ("market_analyst",)
        assert by_id["bull_1"].layer == 1
        assert by_id["bear_1"].role == "bear_researcher"
        assert by_id["research_manager"].layer == 2
        assert by_id["trader"].layer == 3
        assert by_id["risk_aggressive_1"].layer == 4
        assert by_id["risk_conservative_1"].role == "risk_conservative"
        assert by_id["risk_neutral_1"].role == "risk_neutral"
        assert by_id["portfolio_manager"].layer == 5
        assert by_id["portfolio_manager"].depends_on == ("risk_neutral_1",)
        assert all(stage.state == "pending" for stage in stages)

    def test_debate_and_risk_rounds_expand_and_clamp_to_max_rounds(self) -> None:
        config = _config(analysts=(), debate_rounds=5, risk_rounds=0)
        stages = pipeline.build_stage_plan(config)
        ids = [stage.stage_id for stage in stages]

        assert ids[:6] == ["bull_1", "bear_1", "bull_2", "bear_2", "bull_3", "bear_3"]  # clamped to 3
        assert "bull_4" not in ids
        # risk_rounds=0 clamps up to 1, not down to 0
        assert "risk_aggressive_1" in ids
        assert "risk_aggressive_2" not in ids

    def test_analyst_subset_only_includes_selected_analysts(self) -> None:
        config = _config(analysts=("news",))
        stages = pipeline.build_stage_plan(config)
        ids = [stage.stage_id for stage in stages]
        assert ids[0] == "news_analyst"
        assert "market_analyst" not in ids
        by_id = {stage.stage_id: stage for stage in stages}
        assert by_id["news_analyst"].depends_on == ()
        assert by_id["bull_1"].depends_on == ("news_analyst",)


# ---------------------------------------------------------------------------
# parse_rating
# ---------------------------------------------------------------------------


class TestParseRating:
    def test_a_rating_line_wins_outright(self) -> None:
        text = "Some preamble.\n\nrating: Overweight\n\nMore prose that happens to mention Sell."
        assert schemas.parse_rating(text) == "Overweight"

    def test_falls_back_to_the_first_rating_word_with_no_rating_line(self) -> None:
        assert schemas.parse_rating("The desk recommends a Sell here given the setup.") == "Sell"

    def test_defaults_to_hold_with_no_recognizable_rating(self) -> None:
        assert schemas.parse_rating("This text carries no rating word at all.") == "Hold"

    def test_is_case_insensitive_and_canonicalizes(self) -> None:
        assert schemas.parse_rating("RATING: underweight") == "Underweight"


# ---------------------------------------------------------------------------
# run_pipeline -- happy path
# ---------------------------------------------------------------------------


class TestRunPipelineHappyPath:
    def test_reaches_succeeded_with_a_final_rating(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        config = _config()
        settings = _settings(tmp_path)
        store = RunStore(settings, "tradingagents")
        _seed_run(store, config)
        monkeypatch.setattr(pipeline, "run_grounded", _make_fake_run_grounded())

        pipeline.run_pipeline("run-1", config, settings=settings, cancel=threading.Event())

        final = store.load("run-1")
        assert final is not None
        assert final.state == "succeeded"
        assert final.final_rating == "Buy"
        assert final.final_md != ""
        assert all(stage.state == "succeeded" for stage in final.stages)
        assert final.degraded is False
        assert final.budget.calls == len(final.stages)


# ---------------------------------------------------------------------------
# run_pipeline -- a degraded stage does not block downstream
# ---------------------------------------------------------------------------


class TestRunPipelineDegraded:
    def test_a_degraded_analyst_sets_run_degraded_and_the_run_still_succeeds(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _config()
        settings = _settings(tmp_path)
        store = RunStore(settings, "tradingagents")
        _seed_run(store, config)
        monkeypatch.setattr(
            pipeline, "run_grounded", _make_fake_run_grounded(degrade_roles=frozenset({"market_analyst"}))
        )

        pipeline.run_pipeline("run-1", config, settings=settings, cancel=threading.Event())

        final = store.load("run-1")
        assert final is not None
        by_id = {stage.stage_id: stage for stage in final.stages}
        assert by_id["market_analyst"].state == "degraded"
        assert by_id["portfolio_manager"].state == "succeeded"  # ran despite the degraded upstream
        assert final.degraded is True
        assert final.state == "succeeded"


# ---------------------------------------------------------------------------
# run_pipeline -- BudgetExhausted mid-run
# ---------------------------------------------------------------------------


class TestRunPipelineBudgetExhausted:
    def test_marks_the_failing_stage_failed_and_the_rest_blocked(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _config()
        settings = _settings(tmp_path)
        store = RunStore(settings, "tradingagents")
        _seed_run(store, config)
        monkeypatch.setattr(pipeline, "run_grounded", _make_fake_run_grounded(fail_role="trader"))

        pipeline.run_pipeline("run-1", config, settings=settings, cancel=threading.Event())

        final = store.load("run-1")
        assert final is not None
        by_id = {stage.stage_id: stage for stage in final.stages}
        assert by_id["market_analyst"].state == "succeeded"
        assert by_id["research_manager"].state == "succeeded"
        assert by_id["trader"].state == "failed"
        assert by_id["trader"].error != ""
        assert by_id["risk_aggressive_1"].state == "blocked"
        assert by_id["portfolio_manager"].state == "blocked"
        assert final.state == "failed"
        assert final.error != ""


# ---------------------------------------------------------------------------
# run_pipeline -- cancellation
# ---------------------------------------------------------------------------


class TestRunPipelineCancellation:
    def test_cancellation_before_the_first_stage_skips_every_stage(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = _config()
        settings = _settings(tmp_path)
        store = RunStore(settings, "tradingagents")
        _seed_run(store, config)

        def fake_run_grounded(**kwargs):
            raise AssertionError("run_grounded must not be called once cancellation is set")

        monkeypatch.setattr(pipeline, "run_grounded", fake_run_grounded)

        cancel_event = threading.Event()
        cancel_event.set()
        pipeline.run_pipeline("run-1", config, settings=settings, cancel=cancel_event)

        final = store.load("run-1")
        assert final is not None
        assert final.state == "cancelled"
        assert all(stage.state == "skipped" for stage in final.stages)


# ---------------------------------------------------------------------------
# memory: append -> resolve round trip
# ---------------------------------------------------------------------------


class TestMemoryRoundTrip:
    def test_append_pending_then_resolve_against_realized_return(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = _settings(tmp_path)
        trade_date = dt.date.today() - dt.timedelta(days=30)
        window_end = trade_date + dt.timedelta(days=21)

        def fake_read_frame(symbol, interval, *, settings=None, start=None, end=None, limit=None):
            if symbol == "AAPL":
                return _bars_frame({trade_date: 100.0, window_end: 120.0})
            if symbol == "SPY":
                return _bars_frame({trade_date: 100.0, window_end: 105.0})
            return pd.DataFrame()

        monkeypatch.setattr(memory.market_store, "read_frame", fake_read_frame)

        def fake_reflector(*, role, system, user, output_format, prose_of, pack, settings, budget, model, max_attempts=3):
            assert role == "reflector"
            value = schemas.ReflectionNote(lesson="The bullish call was right; AAPL beat SPY by 15 points.")
            new_budget = _budget_bump(budget)
            return GroundedResult(
                value=value, verdict=GroundingVerdict(ok=True, attempts=1),
                calls=(_fake_call("reflector"),), budget=new_budget,
            )

        monkeypatch.setattr(memory, "run_grounded", fake_reflector)

        run = DeskRun(
            run_id="r1", kind="tradingagents", state="succeeded", created_at=dt.datetime.now(dt.UTC),
            final_md="rating: Buy\n\nsome thesis", final_rating="Buy", budget=AgentBudget(cap_usd=Decimal("5.00")),
        )
        config = _config(symbol="AAPL", trade_date=trade_date)
        memory.append_pending(run, config, settings=settings)

        pending = memory.read_entries("AAPL", settings=settings)
        assert len(pending) == 1
        assert pending[0].state == "pending"
        assert pending[0].raw_return_pct is None
        assert pending[0].rating == "Buy"

        new_budget = memory.resolve_pending(
            "AAPL", settings=settings, budget=AgentBudget(cap_usd=Decimal("5.00")), model="claude-opus-5"
        )
        assert new_budget.calls == 1

        resolved = memory.read_entries("AAPL", settings=settings)
        assert len(resolved) == 1
        entry = resolved[0]
        assert entry.state == "resolved"
        # Fractions, not percents -- +20% is 0.20, never 20.
        assert entry.raw_return_pct == Decimal("0.200000")
        assert entry.alpha_return_pct == Decimal("0.150000")
        assert entry.benchmark == "SPY"
        assert entry.holding_days == 21
        assert entry.reflection != ""

    def test_resolve_pending_leaves_a_too_recent_entry_untouched(self, tmp_path) -> None:
        settings = _settings(tmp_path)
        run = DeskRun(
            run_id="r2", kind="tradingagents", state="succeeded", created_at=dt.datetime.now(dt.UTC),
            final_md="rating: Hold", final_rating="Hold", budget=AgentBudget(cap_usd=Decimal("5.00")),
        )
        config = _config(symbol="MSFT", trade_date=dt.date.today())  # far too recent to resolve
        memory.append_pending(run, config, settings=settings)

        budget = memory.resolve_pending(
            "MSFT", settings=settings, budget=AgentBudget(cap_usd=Decimal("5.00")), model="claude-opus-5"
        )
        assert budget.calls == 0
        entries = memory.read_entries("MSFT", settings=settings)
        assert entries[0].state == "pending"


# ---------------------------------------------------------------------------
# service.py validation
# ---------------------------------------------------------------------------


class TestServiceValidation:
    def test_config_payload_reports_the_analyst_roster_and_round_limits(self, tmp_path) -> None:
        payload = service.config_payload(_settings(tmp_path))
        assert {a["key"] for a in payload["analysts"]} == {"market", "sentiment", "news", "fundamentals"}
        assert payload["max_rounds"] == pipeline.MAX_ROUNDS
        assert payload["default_budget_usd"] == "5.00"

    def test_config_payload_defaults_to_haiku_and_lists_selectable_models(self, tmp_path) -> None:
        payload = service.config_payload(_settings(tmp_path))
        # The desk default is the cheapest/fastest tier (Haiku 4.5), unless a run selects otherwise.
        assert payload["default_model"] == "claude-haiku-4-5-20251001"
        ids = [m["id"] for m in payload["available_models"]]
        assert ids[0] == "claude-haiku-4-5-20251001"  # default first
        assert "claude-opus-5" in ids
        assert "claude-sonnet-5" in ids  # still selectable per run
        assert payload["default_model"] in ids  # the default is always selectable
        assert all(m["id"] and m["label"] for m in payload["available_models"])

    def test_start_run_rejects_an_unknown_model(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.agents import client as agents_client

        monkeypatch.setattr(agents_client, "is_available", lambda: (True, "ok"))

        class _Req:
            symbol = "AAPL"
            trade_date = None
            analysts = None
            debate_rounds = None
            risk_rounds = None
            budget_usd = None
            model = "gpt-4o"  # not a Claude model this desk offers

        with pytest.raises(service.InvalidRequest, match="unknown model"):
            service.start_run(_Req(), settings=_settings(tmp_path))

    def test_validate_model_falls_back_to_the_desk_default(self) -> None:
        assert service._validate_model(None) == "claude-haiku-4-5-20251001"
        assert service._validate_model("claude-opus-5") == "claude-opus-5"
        assert service._validate_model("  claude-haiku-4-5-20251001  ") == "claude-haiku-4-5-20251001"

    def test_cancel_run_raises_run_not_found(self, tmp_path) -> None:
        with pytest.raises(service.RunNotFound):
            service.cancel_run("no-such-run", settings=_settings(tmp_path))

    def test_start_run_reports_agent_unavailable(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.agents import client as agents_client

        monkeypatch.setattr(agents_client, "is_available", lambda: (False, "no credential configured"))

        class _Req:
            symbol = "AAPL"
            trade_date = None
            analysts = None
            debate_rounds = None
            risk_rounds = None
            budget_usd = None
            model = None

        with pytest.raises(AgentUnavailable, match="no credential configured"):
            service.start_run(_Req(), settings=_settings(tmp_path))


# ---------------------------------------------------------------------------
# Route registration -- proves app.main actually wires the router, not just that
# a bare `import app.tradingagents` succeeds. See this project's own recorded
# scar (tests/test_tradingagents.py's sibling suite): a missing `include_router`
# can pass every unit test while the route itself is unreachable.
# ---------------------------------------------------------------------------


def test_tradingagents_router_is_registered_on_the_app() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    assert any("/api/tradingagents" in path for path in paths)
    assert "/api/tradingagents/config" in paths
    assert "/api/tradingagents/runs" in paths
    assert "/api/tradingagents/runs/{run_id}" in paths
    assert "/api/tradingagents/memory" in paths


# ---------------------------------------------------------------------------
# The `live` opt-in -- see docs/AGENT-DESK-CONTRACT.md's `StartRunRequest.live`.
#
# The first test here is the load-bearing one: a non-live run must read exactly the
# sections it read before this feature existed. Everything about a live run is
# additive, and pinning the non-live tuples is what proves it.
# ---------------------------------------------------------------------------


class TestLiveOptIn:
    def test_non_live_sections_are_unchanged(self) -> None:
        assert pipeline.analyst_sections("market_analyst") == ("price", "indicators")
        assert pipeline.analyst_sections("sentiment_analyst") == ("price", "indicators", "social")
        assert pipeline.analyst_sections("news_analyst") == ("news", "macro", "events")
        assert pipeline.analyst_sections("fundamentals_analyst") == ("fundamentals",)
        assert pipeline.union_sections() == ("price", "indicators", "news", "fundamentals")
        # ... and the same again through the explicit keyword, which is what a default run passes.
        assert pipeline.analyst_sections("market_analyst", live=False) == ("price", "indicators")
        assert pipeline.union_sections(live=False) == ("price", "indicators", "news", "fundamentals")

    def test_live_adds_the_two_live_sections_to_the_tape_analysts_only(self) -> None:
        assert pipeline.analyst_sections("market_analyst", live=True) == (
            "price",
            "indicators",
            "live_quote",
            "intraday",
        )
        assert pipeline.analyst_sections("sentiment_analyst", live=True) == (
            "price",
            "indicators",
            "social",
            "live_quote",
            "intraday",
        )
        # News and fundamentals read sources that do not move minute to minute.
        assert pipeline.analyst_sections("news_analyst", live=True) == ("news", "macro", "events")
        assert pipeline.analyst_sections("fundamentals_analyst", live=True) == ("fundamentals",)
        # The shared downstream pack gains the quote, not the intraday bar table.
        assert pipeline.union_sections(live=True) == (
            "price",
            "indicators",
            "news",
            "fundamentals",
            "live_quote",
        )

    def test_the_as_of_line_names_the_wall_clock_on_a_live_run(self) -> None:
        assert pipeline._as_of_line(None) == "the latest stored session"
        assert pipeline._as_of_line(dt.date(2026, 9, 1)) == "2026-09-01"
        live_line = pipeline._as_of_line(None, live=True)
        assert live_line.startswith("live ")
        # A full ISO-8601 UTC timestamp, which the grounding gate scrubs whole.
        parsed = dt.datetime.fromisoformat(live_line.split(" ")[-1])
        assert parsed.tzinfo is not None

    def test_a_live_run_watches_the_symbol_and_builds_live_packs(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.market import livefeed

        watched: list[list[str]] = []
        monkeypatch.setattr(livefeed, "watch", lambda symbols: watched.append(list(symbols)))

        built: list[tuple[str, ...]] = []

        def _recording_build_pack(symbol, as_of, *, settings, sections):
            built.append(tuple(sections))
            return _empty_pack(symbol, sections)

        monkeypatch.setattr(evidence, "build_pack", _recording_build_pack)

        config = _config(analysts=("market",), live=True)
        settings = _settings(tmp_path)
        store = RunStore(settings, "tradingagents")
        _seed_run(store, config)
        monkeypatch.setattr(pipeline, "run_grounded", _make_fake_run_grounded())

        pipeline.run_pipeline("run-1", config, settings=settings, cancel=threading.Event())

        assert watched == [["AAPL"]]
        assert ("price", "indicators", "news", "fundamentals", "live_quote") in built  # union pack
        assert ("price", "indicators", "live_quote", "intraday") in built  # market analyst

    def test_a_failing_watch_does_not_fail_the_run(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.market import livefeed

        def _boom(symbols: object) -> None:
            raise RuntimeError("feed down")

        monkeypatch.setattr(livefeed, "watch", _boom)
        config = _config(live=True)
        settings = _settings(tmp_path)
        store = RunStore(settings, "tradingagents")
        _seed_run(store, config)
        monkeypatch.setattr(pipeline, "run_grounded", _make_fake_run_grounded())

        pipeline.run_pipeline("run-1", config, settings=settings, cancel=threading.Event())

        final = store.load("run-1")
        assert final is not None
        assert final.state == "succeeded"

    def test_a_non_live_run_never_watches_anything(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.market import livefeed

        watched: list[list[str]] = []
        monkeypatch.setattr(livefeed, "watch", lambda symbols: watched.append(list(symbols)))

        config = _config()
        settings = _settings(tmp_path)
        store = RunStore(settings, "tradingagents")
        _seed_run(store, config)
        monkeypatch.setattr(pipeline, "run_grounded", _make_fake_run_grounded())

        pipeline.run_pipeline("run-1", config, settings=settings, cancel=threading.Event())
        assert watched == []

    def test_start_run_refuses_live_with_a_past_trade_date(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.agents import client as agents_client

        monkeypatch.setattr(agents_client, "is_available", lambda: (True, "ok"))

        class _Req:
            symbol = "AAPL"
            trade_date = dt.date(2020, 1, 2)
            analysts = None
            debate_rounds = None
            risk_rounds = None
            budget_usd = None
            model = None
            live = True

        with pytest.raises(service.InvalidRequest, match="live runs must be as of today"):
            service.start_run(_Req(), settings=_settings(tmp_path))

    def test_validate_live_accepts_today_and_no_trade_date(self) -> None:
        assert service._validate_live(True, None) is True
        assert service._validate_live(True, dt.datetime.now(dt.UTC).date()) is True
        assert service._validate_live(False, dt.date(2020, 1, 2)) is False

    def test_start_run_persists_live_on_the_run_config(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.agents import client as agents_client

        class _NoopRegistry:
            def start(self, kind: str, run_id: str, target: object) -> None:
                pass

        monkeypatch.setattr(agents_client, "is_available", lambda: (True, "ok"))
        monkeypatch.setattr(service, "registry", lambda: _NoopRegistry())

        class _Req:
            symbol = "AAPL"
            trade_date = None
            analysts = None
            debate_rounds = None
            risk_rounds = None
            budget_usd = None
            model = None
            live = True

        run = service.start_run(_Req(), settings=_settings(tmp_path))
        assert run.config["live"] is True

    def test_a_request_without_the_field_at_all_is_a_non_live_run(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`app.workflow.pipeline._TARequest` predates this field and does not carry it -- see
        `service.StartRunRequest`'s own docstring for why the Protocol does not declare it."""
        from app.agents import client as agents_client

        class _NoopRegistry:
            def start(self, kind: str, run_id: str, target: object) -> None:
                pass

        monkeypatch.setattr(agents_client, "is_available", lambda: (True, "ok"))
        monkeypatch.setattr(service, "registry", lambda: _NoopRegistry())

        class _LegacyReq:
            symbol = "AAPL"
            trade_date = None
            analysts = None
            debate_rounds = None
            risk_rounds = None
            budget_usd = None
            model = None

        run = service.start_run(_LegacyReq(), settings=_settings(tmp_path))
        assert run.config["live"] is False

    def test_the_api_body_defaults_live_to_false(self) -> None:
        from app.api.tradingagents import StartRunRequest as Body

        assert Body(symbol="AAPL").live is False
        assert Body(symbol="AAPL", live=True).live is True
