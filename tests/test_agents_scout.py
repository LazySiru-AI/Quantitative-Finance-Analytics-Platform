"""Unit tests for `app.agents.scout`.

**`app.agents.client` does not necessarily exist yet.** It is another worker's concurrently-written
module (see `backend/app/agents/scout.py`'s own module docstring), so every test here injects a fake
directly into `sys.modules["app.agents.client"]` rather than importing the real thing -- exactly the
mechanism `scout_symbols` itself is written to rely on (`importlib.import_module`, not a plain
`import`, specifically so a test double dropped into `sys.modules` is picked up the same way a real
submodule would be). `sys.modules["app.agents.client"] = None` is the standard trick to force
`ModuleNotFoundError` for a module that is not actually absent from the filesystem, used below to
prove the "SDK/module not importable" path degrades the same way "no credentials" does.

**Fully offline.** No test here reaches a real news provider or a real Anthropic endpoint:
`app.market.news.build_ticker_panel` is monkeypatched directly (it is a real, already-landed module,
so patching its attribute on the real module object is enough -- `scout.py` imports it fresh inside
each call, so the patched attribute is what every call sees), and the model call is always a fake
`call_structured` under the test's own control.
"""

from __future__ import annotations

import datetime as dt
import sys
import types
from decimal import Decimal
from typing import Any

import pytest

import app.market.news as news_module
from app.agents.models import AgentBudget, AgentCall
from app.agents.scout import scout_symbols
from app.evolution.models import LoopConfig
from app.market.news_models import NewsItem, SocialSnapshot, SocialSummary, TickerNewsPanel
from app.tournament.purposes import Purpose

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _fresh_budget(*, cap: str = "10.00", spent: str = "0.00") -> AgentBudget:
    return AgentBudget(cap_usd=Decimal(cap), spent_usd=Decimal(spent))


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    available: bool = True,
    availability_reason: str = "ANTHROPIC_API_KEY set",
    call_structured: Any = None,
) -> list[dict[str, Any]]:
    """Drop a fake `app.agents.client` into `sys.modules` and return the list `call_structured`
    (when not overridden) appends its kwargs to, so a test can assert whether -- and how -- the model
    was actually called."""
    calls: list[dict[str, Any]] = []

    def default_call_structured(**kwargs: Any) -> Any:
        calls.append(kwargs)
        raise AssertionError("call_structured invoked with no fake response configured")

    fake = types.ModuleType("app.agents.client")
    fake.is_available = lambda: (available, availability_reason)  # type: ignore[attr-defined]
    fake.call_structured = call_structured or default_call_structured  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.agents.client", fake)
    return calls


def _fake_panel(symbol: str, *, headline: str = "headline") -> TickerNewsPanel:
    now = dt.datetime.now(dt.UTC)
    return TickerNewsPanel(
        symbol=symbol,
        generated_at=now,
        news=(
            NewsItem(
                title=headline,
                url=f"https://example.com/{symbol}",
                published=now,
                source="fake_provider",
                publisher="Fake Wire",
            ),
        ),
        news_source="fake_provider",
        social=SocialSummary.of(
            SocialSnapshot(symbol=symbol, source="fake_social", as_of=now, bullish=3, bearish=1, neutral=6)
        ),
    )


def _patch_build_ticker_panel(monkeypatch: pytest.MonkeyPatch, fn: Any) -> None:
    monkeypatch.setattr(news_module, "build_ticker_panel", fn)


def _config() -> LoopConfig:
    return LoopConfig()


# ---------------------------------------------------------------------------
# Availability / degrade-without-raising
# ---------------------------------------------------------------------------


class TestDegradesWithoutRaising:
    def test_no_credentials_returns_empty_picks_and_never_calls_the_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _install_fake_client(monkeypatch, available=False, availability_reason="no credential found")
        _patch_build_ticker_panel(monkeypatch, lambda settings, symbol, **kw: _fake_panel(symbol))

        report, returned_budget = scout_symbols(
            purpose=Purpose.TRADING,
            config=_config(),
            settings=object(),  # never touched -- the availability check short-circuits first
            budget=_fresh_budget(),
            candidates=("SPY", "QQQ"),
        )

        assert report.picks == ()
        assert "no credential found" in (report.call.stop_reason or "")
        assert calls == [], "the model must never be called when credentials are unavailable"
        assert returned_budget == _fresh_budget(), "an unattempted call must pass the budget through unchanged"

    def test_app_agents_client_not_importable_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The standard trick to force ModuleNotFoundError for a module Python could otherwise import.
        monkeypatch.setitem(sys.modules, "app.agents.client", None)
        _patch_build_ticker_panel(monkeypatch, lambda settings, symbol, **kw: _fake_panel(symbol))

        report, returned_budget = scout_symbols(
            purpose=Purpose.TRADING,
            config=_config(),
            settings=object(),
            budget=_fresh_budget(),
            candidates=("SPY",),
        )

        assert report.picks == ()
        assert "not importable" in (report.call.stop_reason or "")
        assert returned_budget == _fresh_budget()

    def test_exhausted_budget_returns_empty_without_calling_the_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _install_fake_client(monkeypatch)
        _patch_build_ticker_panel(monkeypatch, lambda settings, symbol, **kw: _fake_panel(symbol))
        exhausted = AgentBudget(cap_usd=Decimal("1.00"), spent_usd=Decimal("1.00"))

        report, returned_budget = scout_symbols(
            purpose=Purpose.TRADING,
            config=_config(),
            settings=object(),
            budget=exhausted,
            candidates=("SPY",),
        )

        assert report.picks == ()
        assert "budget" in (report.call.stop_reason or "")
        assert calls == []
        assert returned_budget == exhausted

    def test_no_candidates_returns_empty_without_calling_the_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _install_fake_client(monkeypatch)

        report, returned_budget = scout_symbols(
            purpose=Purpose.TRADING,
            config=_config(),
            settings=object(),
            budget=_fresh_budget(),
            candidates=(),
        )

        assert report.picks == ()
        assert calls == []
        assert returned_budget == _fresh_budget()

    def test_news_layer_throwing_for_every_candidate_returns_empty_without_calling_the_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(d) The scout must return empty rather than raise when the news layer throws."""
        calls = _install_fake_client(monkeypatch)

        def _raising_panel(settings: Any, symbol: str, **kwargs: Any) -> TickerNewsPanel:
            raise RuntimeError(f"synthetic news outage for {symbol}")

        _patch_build_ticker_panel(monkeypatch, _raising_panel)

        report, returned_budget = scout_symbols(
            purpose=Purpose.TRADING,
            config=_config(),
            settings=object(),
            budget=_fresh_budget(),
            candidates=("SPY", "QQQ"),
        )

        assert report.picks == ()
        assert calls == [], "no model call should be attempted with zero usable news sections"
        assert returned_budget == _fresh_budget()

    def test_one_bad_candidate_does_not_block_the_others(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A partial news outage (some candidates fail, at least one succeeds) is not the same failure
        as (d) -- the scout still has something worth showing the model, so it proceeds to call it."""

        def _flaky_panel(settings: Any, symbol: str, **kwargs: Any) -> TickerNewsPanel:
            if symbol == "QQQ":
                raise RuntimeError("synthetic outage for QQQ only")
            return _fake_panel(symbol)

        _patch_build_ticker_panel(monkeypatch, _flaky_panel)

        invocations: list[dict[str, Any]] = []

        def call_structured(**kwargs: Any) -> Any:
            invocations.append(kwargs)
            assert "SPY" in kwargs["user"]
            return (
                types.SimpleNamespace(picks=(), theme="quiet"),
                AgentCall(
                    call_id="call-1",
                    role="scout",
                    model=kwargs["model"],
                    created_at=dt.datetime.now(dt.UTC),
                    system=kwargs["system"],
                    user=kwargs["user"],
                    raw_response="{}",
                ),
                _fresh_budget(spent="0.01"),
            )

        # `_install_fake_client`'s own returned list is only ever appended to by its *default*
        # `call_structured` stub -- this test supplies its own, so invocation is tracked separately.
        _install_fake_client(monkeypatch, call_structured=call_structured)

        _report, _budget = scout_symbols(
            purpose=Purpose.TRADING,
            config=_config(),
            settings=object(),
            budget=_fresh_budget(),
            candidates=("SPY", "QQQ"),
        )

        assert len(invocations) == 1


# ---------------------------------------------------------------------------
# The model call itself
# ---------------------------------------------------------------------------


class TestModelCall:
    def _call_structured_returning(self, picks: tuple[Any, ...], theme: str = "") -> Any:
        def call_structured(**kwargs: Any) -> Any:
            output = types.SimpleNamespace(picks=picks, theme=theme)
            call = AgentCall(
                call_id="call-1",
                role="scout",
                model=kwargs["model"],
                created_at=dt.datetime.now(dt.UTC),
                system=kwargs["system"],
                user=kwargs["user"],
                raw_response="{}",
            )
            return output, call, _fresh_budget(spent="0.02")

        return call_structured

    def test_drops_a_hallucinated_symbol(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """(c) A pick naming a symbol outside the candidate list must never reach the caller."""
        from app.agents.models import ScoutPick

        picks = (
            ScoutPick(symbol="SPY", why="heavy coverage this week"),
            ScoutPick(symbol="TSLA", why="a symbol the model invented, not in the candidate list"),
        )
        _install_fake_client(monkeypatch, call_structured=self._call_structured_returning(picks))
        _patch_build_ticker_panel(monkeypatch, lambda settings, symbol, **kw: _fake_panel(symbol))

        report, _budget = scout_symbols(
            purpose=Purpose.TRADING,
            config=_config(),
            settings=object(),
            budget=_fresh_budget(),
            candidates=("SPY", "QQQ"),
        )

        assert [pick.symbol for pick in report.picks] == ["SPY"]

    def test_truncates_to_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.agents.models import ScoutPick

        picks = tuple(ScoutPick(symbol=sym, why="coverage") for sym in ("SPY", "QQQ", "SOXX", "SMH"))
        _install_fake_client(monkeypatch, call_structured=self._call_structured_returning(picks))
        _patch_build_ticker_panel(monkeypatch, lambda settings, symbol, **kw: _fake_panel(symbol))

        report, _budget = scout_symbols(
            purpose=Purpose.TRADING,
            config=_config(),
            settings=object(),
            budget=_fresh_budget(),
            limit=2,
            candidates=("SPY", "QQQ", "SOXX", "SMH"),
        )

        assert len(report.picks) == 2

    def test_returns_the_budget_the_client_reports(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.agents.models import ScoutPick

        picks = (ScoutPick(symbol="SPY", why="coverage"),)
        _install_fake_client(monkeypatch, call_structured=self._call_structured_returning(picks))
        _patch_build_ticker_panel(monkeypatch, lambda settings, symbol, **kw: _fake_panel(symbol))

        _report, budget = scout_symbols(
            purpose=Purpose.TRADING,
            config=_config(),
            settings=object(),
            budget=_fresh_budget(),
            candidates=("SPY",),
        )

        assert budget.spent_usd == Decimal("0.02")

    def test_client_raising_degrades_to_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def call_structured(**kwargs: Any) -> Any:
            raise RuntimeError("refusal or malformed response")

        _install_fake_client(monkeypatch, call_structured=call_structured)
        _patch_build_ticker_panel(monkeypatch, lambda settings, symbol, **kw: _fake_panel(symbol))

        report, returned_budget = scout_symbols(
            purpose=Purpose.TRADING,
            config=_config(),
            settings=object(),
            budget=_fresh_budget(),
            candidates=("SPY",),
        )

        assert report.picks == ()
        assert "RuntimeError" in (report.call.stop_reason or "")
        assert returned_budget == _fresh_budget()


# ---------------------------------------------------------------------------
# Candidate resolution
# ---------------------------------------------------------------------------


class TestCandidateResolution:
    def test_explicit_candidates_bypass_the_pool_lookup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.evolution.universe as universe_module

        def _pool_for_must_not_be_called(purpose: Purpose) -> Any:
            raise AssertionError("pool_for must not be called when candidates is passed explicitly")

        monkeypatch.setattr(universe_module, "pool_for", _pool_for_must_not_be_called)
        _install_fake_client(monkeypatch, available=False)  # short-circuits before any model call

        report, _budget = scout_symbols(
            purpose=Purpose.ROTH,
            config=_config(),
            settings=object(),
            budget=_fresh_budget(),
            candidates=("SSO", "VUG"),
        )

        assert report.picks == ()  # unavailable client -- but no AssertionError means pool_for was skipped
