"""Unit tests for `app.personas.strategy`.

No test here makes a real model call: `strategy.call_structured` is monkeypatched to return a
caller-built `_CardMapping`, exactly the pattern `tests/test_agents_designer.py`'s
`TestDesignGeneration` uses for `app.agents.designer.call_structured`. `app.evolution.genome.
Genome`/`app.evolution.proposer.card_for` are the REAL functions, never mocked -- they are
deterministic and hit no network, so a test that exercises them proves an actual, validated
`StrategyCard` came out the other end, not just that this module called something.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.agents.models import AgentBudget, AgentCall
from app.config import Settings
from app.evolution.models import ProposalRejected
from app.personas import strategy
from app.personas.models import PersonaProfile, ProfileClaim

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _budget(cap: str = "5.00") -> AgentBudget:
    return AgentBudget(cap_usd=Decimal(cap))


def _call() -> AgentCall:
    return AgentCall(
        call_id="call-1", role="swarm_worker", model="claude-haiku-4-5-20251001",
        created_at=dt.datetime.now(dt.UTC), system="s", user="u", raw_response="r",
        cost_usd=Decimal("0.02"),
    )


def _claim(text: str = "Uses a 14-day RSI on the daily chart.", citations: tuple[str, ...] = ("n1",)) -> ProfileClaim:
    return ProfileClaim(text=text, citations=citations)


def _profile(**overrides: object) -> PersonaProfile:
    fields: dict[str, object] = dict(
        persona="creator-a",
        version=1,
        consolidated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        note_count=1,
        summary="A trader.",
        beliefs=(),
        playbook=(),
        methodology=(_claim(),),
        vocabulary=(),
        degraded=False,
        path="profile.md",
    )
    fields.update(overrides)
    return PersonaProfile(**fields)  # type: ignore[arg-type]


def _mapping(**overrides: object) -> strategy._CardMapping:
    fields: dict[str, object] = dict(
        rule_shape="rsi-pullback",
        fast=14,
        slow=30,
        regime_ma=100,
        stop_loss_pct=Decimal("0.08"),
        take_profit_pct=None,
        max_hold_days=90,
        max_positions=4,
        position_pct=Decimal("0.20"),
        rank_key=None,
        rationale="The persona described a 14-day RSI dip-buy above the long-run trend.",
        citations=("n1",),
        techniques_total=1,
        unrepresentable=(),
    )
    fields.update(overrides)
    return strategy._CardMapping(**fields)  # type: ignore[arg-type]


def _stub_call_structured(
    monkeypatch: pytest.MonkeyPatch,
    mapping: strategy._CardMapping,
    *,
    budget: AgentBudget | None = None,
) -> dict[str, object]:
    """Patch `strategy.call_structured` to hand back `mapping`, capturing every kwarg the call site
    passed -- mirrors `test_agents_designer.py`'s `fake_call_structured` pattern."""
    captured: dict[str, object] = {}
    spent = (budget or _budget()).spent_usd + Decimal("0.02")
    new_budget = AgentBudget(cap_usd=(budget or _budget()).cap_usd, spent_usd=spent, calls=1)

    def fake_call_structured(**kwargs: object) -> tuple[strategy._CardMapping, AgentCall, AgentBudget]:
        captured.update(kwargs)
        return mapping, _call(), new_budget

    monkeypatch.setattr(strategy, "call_structured", fake_call_structured)
    return captured


def _draft(
    *,
    profile: PersonaProfile | None,
    bullish_tickers: tuple[str, ...],
    settings: Settings,
    budget: AgentBudget | None = None,
) -> strategy.DraftResult:
    return strategy.draft_strategy_card(
        persona_slug="creator-a",
        profile=profile,
        bullish_tickers=bullish_tickers,
        settings=settings,
        budget=budget or _budget(),
    )


# ---------------------------------------------------------------------------
# No methodology -> unmapped, no model call
# ---------------------------------------------------------------------------


class TestNoMethodology:
    def test_none_profile_is_unmapped_with_no_call(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(**kwargs: object) -> object:
            raise AssertionError("call_structured must not be called when there is no methodology")

        monkeypatch.setattr(strategy, "call_structured", boom)

        result = _draft(profile=None, bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.mapped is False
        assert result.draft.reason == "this persona describes no mechanical methodology to translate"
        assert result.draft.card is None
        assert result.draft.rule_shape is None
        assert result.calls == ()

    def test_empty_methodology_tuple_is_unmapped_with_no_call(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(**kwargs: object) -> object:
            raise AssertionError("call_structured must not be called when methodology is empty")

        monkeypatch.setattr(strategy, "call_structured", boom)

        result = _draft(profile=_profile(methodology=()), bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.mapped is False
        assert result.draft.reason == "this persona describes no mechanical methodology to translate"
        assert result.calls == ()

    def test_caveat_is_always_present_even_when_unmapped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(strategy, "call_structured", lambda **kw: (_ for _ in ()).throw(AssertionError()))
        result = _draft(profile=None, bullish_tickers=(), settings=settings)
        assert result.draft.caveat == strategy._CAVEAT
        assert result.draft.caveat != ""


# ---------------------------------------------------------------------------
# No bullish tickers -> unmapped, no model call
# ---------------------------------------------------------------------------


class TestNoBullishTickers:
    def test_empty_bullish_tickers_is_unmapped_with_no_call(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(**kwargs: object) -> object:
            raise AssertionError("call_structured must not be called with no bullish tickers")

        monkeypatch.setattr(strategy, "call_structured", boom)

        result = _draft(profile=_profile(), bullish_tickers=(), settings=settings)

        assert result.draft.mapped is False
        assert result.draft.reason == "no current-bullish tickers to trade"
        assert result.calls == ()

    def test_blank_only_bullish_tickers_is_unmapped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(strategy, "call_structured", lambda **kw: (_ for _ in ()).throw(AssertionError()))
        result = _draft(profile=_profile(), bullish_tickers=("  ", ""), settings=settings)
        assert result.draft.mapped is False
        assert result.draft.reason == "no current-bullish tickers to trade"


# ---------------------------------------------------------------------------
# A good mapping -> a real, validated StrategyCard round-tripping through card_for
# ---------------------------------------------------------------------------


class TestGoodMapping:
    def test_valid_mapping_produces_a_mapped_card_with_the_right_universe_and_shape(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(monkeypatch, _mapping())

        result = _draft(
            profile=_profile(), bullish_tickers=("nvda", "tsm", "nvda"), settings=settings,
        )

        assert result.draft.mapped is True
        assert result.draft.reason == ""
        assert result.draft.rule_shape == "rsi-pullback"
        assert result.draft.card is not None
        assert tuple(result.draft.card["universe"]) == ("NVDA", "TSM")  # uppercased, deduped
        assert result.draft.card["desk_only"] is False
        assert result.draft.card["designed_through"] == "2026-02-13"
        assert result.draft.caveat == strategy._CAVEAT
        assert result.draft.degraded is False
        assert len(result.calls) == 1

    def test_universe_is_capped_at_twelve_and_the_rest_dropped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(monkeypatch, _mapping())
        tickers = tuple(f"T{i}" for i in range(20))

        result = _draft(profile=_profile(), bullish_tickers=tickers, settings=settings)

        assert result.draft.mapped is True
        assert len(result.draft.card["universe"]) == 12
        assert tuple(result.draft.card["universe"]) == tickers[:12]

    def test_the_model_is_never_asked_to_choose_the_universe(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_call_structured(monkeypatch, _mapping())
        _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)
        # _CardMapping itself has no universe field -- proof the schema structurally cannot carry one.
        assert "universe" not in strategy._CardMapping.model_fields
        assert captured["role"] == "swarm_worker"

    def test_rationale_flows_through_to_the_draft(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(
            monkeypatch, _mapping(rationale="Because they said they buy dips under a rising trend."),
        )
        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)
        assert result.draft.rationale == "Because they said they buy dips under a rising trend."


# ---------------------------------------------------------------------------
# A bad mapping -> mapped=False with the rejection reason, never patched
# ---------------------------------------------------------------------------


class TestBadMapping:
    def test_fast_greater_than_slow_is_rejected_not_repaired(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(monkeypatch, _mapping(fast=50, slow=20, regime_ma=100))

        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.mapped is False
        assert result.draft.card is None
        assert "mapping rejected" in result.draft.reason
        assert "fast" in result.draft.reason
        # The call still happened and still cost money -- recorded even though the mapping failed.
        assert len(result.calls) == 1
        assert result.draft.cost_usd != "0"

    def test_period_out_of_bounds_is_rejected(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(monkeypatch, _mapping(fast=1, slow=2, regime_ma=3))

        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.mapped is False
        assert "mapping rejected" in result.draft.reason

    def test_oversized_position_sizing_is_rejected(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # position_pct * max_positions > 1 -- StrategyCard's own validator refuses this.
        _stub_call_structured(
            monkeypatch, _mapping(max_positions=8, position_pct=Decimal("0.50")),
        )

        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.mapped is False
        assert "mapping rejected" in result.draft.reason

    def test_never_raises_proposal_rejected_to_the_caller(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(monkeypatch, _mapping(fast=50, slow=20, regime_ma=100))
        # Should return a draft, never propagate ProposalRejected.
        try:
            result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)
        except ProposalRejected:
            pytest.fail("ProposalRejected must be caught and reported as mapped=False")
        assert result.draft.mapped is False


# ---------------------------------------------------------------------------
# Citation filtering -- ours to enforce, never the model's to self-police
# ---------------------------------------------------------------------------


class TestCitationFiltering:
    def test_citations_are_kept_when_they_appear_in_the_methodology(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        profile = _profile(methodology=(_claim(citations=("n1", "n2")),))
        _stub_call_structured(monkeypatch, _mapping(citations=("n1", "n2")))

        result = _draft(profile=profile, bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.citations == ("n1", "n2")

    def test_a_hallucinated_citation_is_dropped_not_the_whole_mapping(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        profile = _profile(methodology=(_claim(citations=("n1",)),))
        _stub_call_structured(monkeypatch, _mapping(citations=("n1", "does-not-exist")))

        result = _draft(profile=profile, bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.mapped is True
        assert result.draft.citations == ("n1",)

    def test_citations_outside_methodology_are_all_dropped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        profile = _profile(methodology=(_claim(citations=("n1",)),))
        _stub_call_structured(monkeypatch, _mapping(citations=("ghost-1", "ghost-2")))

        result = _draft(profile=profile, bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.citations == ()

    def test_citations_are_filtered_across_multiple_methodology_claims(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        profile = _profile(
            methodology=(
                _claim(text="Uses RSI.", citations=("n1",)),
                _claim(text="Cuts losses at 8%.", citations=("n2", "n3")),
            ),
        )
        _stub_call_structured(monkeypatch, _mapping(citations=("n1", "n3", "n4")))

        result = _draft(profile=profile, bullish_tickers=("NVDA",), settings=settings)

        assert set(result.draft.citations) == {"n1", "n3"}


# ---------------------------------------------------------------------------
# Cost accounting
# ---------------------------------------------------------------------------


class TestCostAccounting:
    def test_cost_usd_reflects_the_budget_spent_on_a_mapped_card(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        budget = _budget()
        _stub_call_structured(monkeypatch, _mapping(), budget=budget)

        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings, budget=budget)

        assert result.draft.cost_usd == str(budget.spent_usd + Decimal("0.02"))

    def test_cost_usd_defaults_to_zero_when_no_call_was_made(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(strategy, "call_structured", lambda **kw: (_ for _ in ()).throw(AssertionError()))
        result = _draft(profile=None, bullish_tickers=(), settings=settings)
        assert result.draft.cost_usd == "0"


# ---------------------------------------------------------------------------
# _CardMapping schema
# ---------------------------------------------------------------------------


class TestCardMappingSchema:
    def test_rejects_an_unknown_rule_shape(self) -> None:
        with pytest.raises(ValidationError):
            _mapping(rule_shape="bollinger-bounce")

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            strategy._CardMapping(
                rule_shape="rsi-pullback", fast=14, slow=30, regime_ma=100,
                stop_loss_pct=Decimal("0.08"), max_hold_days=90, max_positions=4,
                position_pct=Decimal("0.20"), rationale="r", extra_field="nope",
            )

    def test_is_frozen(self) -> None:
        mapping = _mapping()
        with pytest.raises(ValidationError):
            mapping.fast = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Instrument filter -- non-equity/ETF tickers dropped before any model call
# ---------------------------------------------------------------------------


class TestInstrumentFilter:
    def test_a_universe_of_only_futures_is_unmapped_with_no_call_and_names_proxies(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(**kwargs: object) -> object:
            raise AssertionError("call_structured must not be called when nothing is tradeable")

        monkeypatch.setattr(strategy, "call_structured", boom)

        result = _draft(profile=_profile(), bullish_tickers=("GC", "CL"), settings=settings)

        assert result.draft.mapped is False
        assert result.draft.card is None
        assert "GC" in result.draft.reason
        assert "GLD" in result.draft.reason
        assert "CL" in result.draft.reason
        assert "USO" in result.draft.reason
        assert result.calls == ()

    def test_a_mixed_universe_proceeds_on_the_tradeable_subset_only(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(monkeypatch, _mapping())

        result = _draft(profile=_profile(), bullish_tickers=("NVDA", "GC"), settings=settings)

        assert result.draft.mapped is True
        assert tuple(result.draft.card["universe"]) == ("NVDA",)

    def test_a_symbol_with_no_curated_proxy_says_so(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(strategy, "call_structured", lambda **kw: (_ for _ in ()).throw(AssertionError()))
        result = _draft(profile=_profile(), bullish_tickers=("SOL",), settings=settings)
        assert result.draft.mapped is False
        assert "SOL" in result.draft.reason
        assert "no tradeable proxy available" in result.draft.reason


# ---------------------------------------------------------------------------
# Fidelity -- how much of the methodology the fixed rule vocabulary could express
# ---------------------------------------------------------------------------


class TestFidelity:
    def test_fidelity_is_computed_from_the_mapping(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(
            monkeypatch, _mapping(techniques_total=4, unrepresentable=("opening-range box",)),
        )
        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.mapped is True
        assert result.draft.techniques_total == 4
        assert result.draft.techniques_represented == 3
        assert result.draft.fidelity == pytest.approx(0.75)

    def test_fidelity_is_none_when_total_is_zero(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(monkeypatch, _mapping(techniques_total=0, unrepresentable=()))
        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.fidelity is None
        assert result.draft.techniques_represented == 0

    def test_low_fidelity_mapping_lists_unrepresentable_techniques(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        unrepresentable = (
            "opening-range box", "multi-timeframe confirmation", "options overlay", "discretionary exit",
        )
        _stub_call_structured(monkeypatch, _mapping(techniques_total=5, unrepresentable=unrepresentable))

        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.fidelity == pytest.approx(0.2)
        assert result.draft.unrepresentable == unrepresentable

    def test_fidelity_is_populated_even_when_the_mapping_is_rejected(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(
            monkeypatch,
            _mapping(fast=50, slow=20, regime_ma=100, techniques_total=2, unrepresentable=("x",)),
        )

        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)

        assert result.draft.mapped is False
        assert result.draft.techniques_total == 2
        assert result.draft.techniques_represented == 1
        assert result.draft.fidelity == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Persistence -- strategy/<version>.json, so a mapped draft can be reopened exactly
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_save_draft_writes_strategy_1_json_then_strategy_2_json_and_stamps_versions(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(monkeypatch, _mapping())
        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)

        first = strategy.save_draft("creator-a", result.draft, settings)
        second = strategy.save_draft("creator-a", result.draft, settings)

        assert first.filename == "1.json"
        assert first.draft.version == 1
        assert second.filename == "2.json"
        assert second.draft.version == 2

        directory = strategy._strategy_dir(settings, "creator-a")
        assert (directory / "1.json").is_file()
        assert (directory / "2.json").is_file()

    def test_list_saved_drafts_returns_newest_first_and_round_trips_the_draft(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(monkeypatch, _mapping())
        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)

        strategy.save_draft("creator-a", result.draft, settings)
        strategy.save_draft("creator-a", result.draft, settings)

        listed = strategy.list_saved_drafts("creator-a", settings)

        assert [saved.draft.version for saved in listed] == [2, 1]
        assert listed[0].filename == "2.json"
        assert listed[0].draft.rule_shape == result.draft.rule_shape
        assert listed[0].draft.card == result.draft.card

    def test_list_saved_drafts_is_empty_when_nothing_saved(self, settings: Settings) -> None:
        assert strategy.list_saved_drafts("nobody", settings) == ()

    def test_draft_strategy_card_never_writes_a_file(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(monkeypatch, _mapping())
        _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)

        assert strategy.list_saved_drafts("creator-a", settings) == ()


# ---------------------------------------------------------------------------
# DraftResult shape
# ---------------------------------------------------------------------------


class TestDraftResult:
    def test_is_a_frozen_dataclass_with_draft_and_calls(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_call_structured(monkeypatch, _mapping())
        result = _draft(profile=_profile(), bullish_tickers=("NVDA",), settings=settings)
        assert hasattr(result, "draft")
        assert hasattr(result, "calls")
        with pytest.raises(AttributeError):
            result.draft = result.draft  # type: ignore[misc]
