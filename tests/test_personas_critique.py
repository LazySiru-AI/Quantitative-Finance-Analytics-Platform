"""Unit tests for `app.personas.critique`.

No test here makes a real model call: `critique.run_grounded` is monkeypatched to a fake that returns a
caller-supplied `_CritiqueDraft` wrapped in a `GroundedResult`, exactly the pattern
`tests/test_personas_ask.py` already uses for `app.personas.ask`. What is asserted is this module's own
logic -- the no-profile/empty-profile short circuit (no model call), a good critique's verdict/assessment/
citations, hallucinated-citation filtering, degraded-verdict pass-through, cost accounting, and
`AgentUnavailable`/`BudgetExhausted` propagation.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.agentdesk.grounding import GroundedResult
from app.agentdesk.models import GroundingVerdict
from app.agents.models import AgentBudget, AgentCall, AgentUnavailable, BudgetExhausted
from app.config import Settings
from app.personas import critique
from app.personas.models import PersonaProfile, ProfileClaim, RegimeView

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _budget(cap: str = "5.00", spent: str = "0") -> AgentBudget:
    return AgentBudget(cap_usd=Decimal(cap), spent_usd=Decimal(spent))


def _fake_call() -> AgentCall:
    return AgentCall(
        call_id="call-1", role="swarm_worker", model="claude-haiku-4-5-20251001",
        created_at=dt.datetime.now(dt.UTC), system="s", user="u", raw_response="r",
        cost_usd=Decimal("0.01"),
    )


def _grounded_result(
    draft: critique._CritiqueDraft, *, budget: AgentBudget, ok: bool = True, degraded: bool = False,
) -> GroundedResult[critique._CritiqueDraft]:
    verdict = GroundingVerdict(ok=ok, degraded=degraded, attempts=1)
    new_budget = AgentBudget(
        cap_usd=budget.cap_usd, spent_usd=budget.spent_usd + Decimal("0.01"), calls=budget.calls + 1,
    )
    return GroundedResult(value=draft, verdict=verdict, calls=(_fake_call(),), budget=new_budget)


def _draft(**overrides: object) -> critique._CritiqueDraft:
    fields: dict[str, object] = dict(
        verdict="aligned", assessment="Yeah, this looks like something I'd run.", citations=(),
    )
    fields.update(overrides)
    return critique._CritiqueDraft(**fields)  # type: ignore[arg-type]


def _stub_returning(
    monkeypatch: pytest.MonkeyPatch,
    draft: critique._CritiqueDraft,
    *,
    ok: bool = True,
    degraded: bool = False,
) -> dict[str, object]:
    """Patch `critique.run_grounded` to hand back `draft` (wrapped), and capture every kwarg the call
    site passed -- `captured["system"]`, `captured["user"]`, `captured["pack"]`, etc."""
    captured: dict[str, object] = {}

    def fake_run_grounded(**kwargs: object) -> GroundedResult[critique._CritiqueDraft]:
        captured.update(kwargs)
        return _grounded_result(draft, budget=kwargs["budget"], ok=ok, degraded=degraded)  # type: ignore[arg-type]

    monkeypatch.setattr(critique, "run_grounded", fake_run_grounded)
    return captured


def _claim(text: str, *note_ids: str) -> ProfileClaim:
    return ProfileClaim(text=text, citations=note_ids)


def _profile(**overrides: object) -> PersonaProfile:
    fields: dict[str, object] = dict(
        persona="creator-a",
        version=1,
        consolidated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        note_count=3,
        summary="Trades momentum names, mostly semis.",
        beliefs=(_claim("Buys strength, not dips.", "n1"),),
        playbook=(),
        methodology=(_claim("Uses a 14-day RSI on the daily chart.", "n2"),),
        vocabulary=(),
        path="profile.md",
    )
    fields.update(overrides)
    return PersonaProfile(**fields)  # type: ignore[arg-type]


def _card(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = dict(
        display_name="RSI Pullback",
        discipline="technical",
        purpose="trading",
        universe=["NVDA", "AMD"],
        entry="rsi(14) < 30",
        exit="rsi(14) > 60",
        stop_loss_pct="0.08",
        max_hold_days=20,
        max_positions=4,
        position_pct="0.2",
        thesis="Buys oversold strength inside an uptrend.",
    )
    fields.update(overrides)
    return fields


def _critique(settings: Settings, **overrides: object) -> critique.CritiqueResult:
    fields: dict[str, object] = dict(
        persona_slug="creator-a", profile=_profile(), card=_card(), settings=settings, budget=_budget(),
    )
    fields.update(overrides)
    return critique.critique_card(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# No profile / empty profile -- no model call, never raised
# ---------------------------------------------------------------------------


class TestNoProfile:
    def test_none_profile_returns_cannot_say_without_a_model_call(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_if_called(**kwargs: object) -> GroundedResult[critique._CritiqueDraft]:
            raise AssertionError("run_grounded should not be called with no profile")

        monkeypatch.setattr(critique, "run_grounded", fail_if_called)

        result = _critique(settings, profile=None)

        assert result.calls == ()
        assert result.critique.verdict == "cannot_say"
        assert result.critique.citations == ()
        assert result.critique.degraded is False
        assert "creator-a" in result.critique.assessment
        assert result.critique.caveat != ""

    def test_empty_profile_with_no_beliefs_playbook_methodology_or_regime_returns_cannot_say(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_if_called(**kwargs: object) -> GroundedResult[critique._CritiqueDraft]:
            raise AssertionError("run_grounded should not be called with an empty profile")

        monkeypatch.setattr(critique, "run_grounded", fail_if_called)

        empty_profile = _profile(beliefs=(), playbook=(), methodology=(), regime=None)
        result = _critique(settings, profile=empty_profile)

        assert result.calls == ()
        assert result.critique.verdict == "cannot_say"

    def test_a_profile_with_only_regime_signal_is_not_treated_as_empty(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft())
        regime = RegimeView(risk="on", summary="Bullish on tech.", citations=("n3",), has_signal=True)
        profile = _profile(beliefs=(), playbook=(), methodology=(), regime=regime)

        result = _critique(settings, profile=profile)

        assert result.calls != ()
        assert result.critique.verdict == "aligned"

    def test_nothing_on_record_cost_usd_reflects_the_unspent_budget(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        result = _critique(settings, profile=None, budget=_budget(spent="1.23"))
        assert result.critique.cost_usd == "1.23"


# ---------------------------------------------------------------------------
# A good critique -- verdict, assessment, citations
# ---------------------------------------------------------------------------


class TestGoodCritique:
    def test_returns_verdict_assessment_and_filtered_citations(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(verdict="mixed", citations=("n1", "n2")))

        result = _critique(settings)

        assert result.critique.verdict == "mixed"
        assert result.critique.assessment == "Yeah, this looks like something I'd run."
        assert result.critique.citations == ("n1", "n2")
        assert result.critique.persona == "creator-a"
        assert result.critique.caveat != ""

    def test_the_card_and_profile_reach_the_prompt(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_returning(monkeypatch, _draft())

        _critique(settings)

        user = captured["user"]
        assert isinstance(user, str)
        assert "RSI Pullback" in user
        assert "rsi(14) < 30" in user
        assert "14-day RSI" in user
        assert "Buys strength" in user

    def test_a_model_call_is_made_and_recorded(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft())
        result = _critique(settings)
        assert len(result.calls) == 1


# ---------------------------------------------------------------------------
# Citation filtering -- ours to enforce, never the model's to self-police
# ---------------------------------------------------------------------------


class TestCitationFiltering:
    def test_a_hallucinated_citation_is_dropped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(citations=("n1", "does-not-exist")))
        result = _critique(settings)
        assert result.critique.citations == ("n1",)

    def test_dropped_citations_are_logged(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        _stub_returning(monkeypatch, _draft(citations=("ghost-note",)))
        with caplog.at_level("WARNING", logger="app.personas.critique"):
            _critique(settings)
        assert "ghost-note" in caplog.text

    def test_a_citation_not_in_the_profiles_own_claims_is_dropped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # "n2" is a real note_id in the persona's records, but it was never cited by *this* profile's
        # own claims (only "n1" was) -- not a legitimate cite for this call.
        profile = _profile(beliefs=(_claim("Buys strength.", "n1"),), playbook=(), methodology=())
        _stub_returning(monkeypatch, _draft(citations=("n1", "n2")))
        result = _critique(settings, profile=profile)
        assert result.critique.citations == ("n1",)

    def test_all_citations_valid_are_all_kept(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(citations=("n1", "n2")))
        result = _critique(settings)
        assert result.critique.citations == ("n1", "n2")


# ---------------------------------------------------------------------------
# Degraded verdicts pass through -- never raised
# ---------------------------------------------------------------------------


class TestDegradedPassthrough:
    def test_a_failed_grounding_verdict_is_returned_not_raised(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(), ok=False, degraded=True)
        result = _critique(settings)
        assert result.critique.degraded is True
        assert result.critique.assessment == "Yeah, this looks like something I'd run."

    def test_citation_filtering_still_runs_on_a_degraded_critique(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(citations=("nope",)), ok=False, degraded=True)
        result = _critique(settings)
        assert result.critique.citations == ()


# ---------------------------------------------------------------------------
# Cost accounting
# ---------------------------------------------------------------------------


class TestCostAccounting:
    def test_cost_usd_reflects_the_budget_spend_from_run_grounded(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft())
        result = _critique(settings, budget=_budget(spent="2.00"))
        # `_grounded_result` adds $0.01 on top of whatever budget it was handed.
        assert result.critique.cost_usd == "2.01"


# ---------------------------------------------------------------------------
# AgentUnavailable / BudgetExhausted propagate unchanged
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_agent_unavailable_propagates(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raiser(**kwargs: object) -> GroundedResult[critique._CritiqueDraft]:
            raise AgentUnavailable("no credential configured")

        monkeypatch.setattr(critique, "run_grounded", raiser)
        with pytest.raises(AgentUnavailable):
            _critique(settings)

    def test_budget_exhausted_propagates(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raiser(**kwargs: object) -> GroundedResult[critique._CritiqueDraft]:
            raise BudgetExhausted(Decimal("5.00"), Decimal("5.00"))

        monkeypatch.setattr(critique, "run_grounded", raiser)
        with pytest.raises(BudgetExhausted):
            _critique(settings)


# ---------------------------------------------------------------------------
# Language plumbing
# ---------------------------------------------------------------------------


class TestLanguage:
    def test_default_summary_lang_reaches_the_prompt(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        assert settings.persona_summary_lang == "en"
        captured = _stub_returning(monkeypatch, _draft())
        _critique(settings)
        assert "in en" in captured["system"]  # type: ignore[operator]
