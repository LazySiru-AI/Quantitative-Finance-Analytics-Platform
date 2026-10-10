"""Unit tests for `app.personas.ask`.

No test here makes a real model call or hits the network: `ask.run_grounded` is monkeypatched to a
fake that returns a caller-supplied `_AnswerDraft` wrapped in a `GroundedResult`, exactly the pattern
`tests/test_personas_consolidate.py` already uses for `app.personas.consolidate`; `ask.ensure_series`
is monkeypatched the same way `tests/test_personas_scoring.py` patches `scoring.ensure_series`, so the
market-snapshot path never touches `app.market.store` for real. What is asserted is this module's own
logic -- symbol-prioritised note retrieval, citation filtering (including a hallucinated note_id), the
no-profile/no-notes short circuit, degraded-verdict pass-through, stance handling, snapshot failure
tolerance, error propagation, and that `PersonaAnswer.cost_usd` reflects the budget `run_grounded`
returns.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.agentdesk.grounding import GroundedResult
from app.agentdesk.models import GroundingVerdict
from app.agents.models import AgentBudget, AgentCall, AgentUnavailable, BudgetExhausted
from app.config import Settings
from app.db.duck import Interval
from app.market.models import Bar, BarSeries, BarSource
from app.market.providers.base import ProviderUnavailable
from app.personas import ask
from app.personas.models import (
    EpisodicNote,
    PersonaProfile,
    ProfileClaim,
    RegimeView,
    TickerMention,
)

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
    draft: ask._AnswerDraft, *, budget: AgentBudget, ok: bool = True, degraded: bool = False,
) -> GroundedResult[ask._AnswerDraft]:
    verdict = GroundingVerdict(ok=ok, degraded=degraded, attempts=1)
    new_budget = AgentBudget(
        cap_usd=budget.cap_usd, spent_usd=budget.spent_usd + Decimal("0.01"), calls=budget.calls + 1,
    )
    return GroundedResult(value=draft, verdict=verdict, calls=(_fake_call(),), budget=new_budget)


def _draft(**overrides: object) -> ask._AnswerDraft:
    fields: dict[str, object] = dict(answer="This is what they'd say.", citations=(), stance=None)
    fields.update(overrides)
    return ask._AnswerDraft(**fields)  # type: ignore[arg-type]


def _stub_returning(
    monkeypatch: pytest.MonkeyPatch,
    draft: ask._AnswerDraft,
    *,
    ok: bool = True,
    degraded: bool = False,
) -> dict[str, object]:
    """Patch `ask.run_grounded` to hand back `draft` (wrapped), and capture every kwarg the call site
    passed -- `captured["system"]`, `captured["user"]`, `captured["pack"]`, etc."""
    captured: dict[str, object] = {}

    def fake_run_grounded(**kwargs: object) -> GroundedResult[ask._AnswerDraft]:
        captured.update(kwargs)
        return _grounded_result(draft, budget=kwargs["budget"], ok=ok, degraded=degraded)  # type: ignore[arg-type]

    monkeypatch.setattr(ask, "run_grounded", fake_run_grounded)
    return captured


def _note(
    note_id: str,
    *,
    persona: str = "creator-a",
    published: dt.datetime | None = None,
    ingested_at: dt.datetime | None = None,
    title: str | None = "A video",
    summary: str = "A summary.",
    mentions: tuple[TickerMention, ...] = (),
) -> EpisodicNote:
    return EpisodicNote(
        note_id=note_id,
        persona=persona,
        source_id="yt:UC1",
        published=published,
        ingested_at=ingested_at or dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        url=f"https://example.com/{note_id}",
        title=title,
        kind="video_transcript",
        transcript_source="auto",
        lang="en",
        summary=summary,
        themes=("theme one",),
        quotes=(),
        mentions=mentions,
        path=f"notes/{note_id}.md",
        degraded=False,
    )


def _profile(**overrides: object) -> PersonaProfile:
    fields: dict[str, object] = dict(
        persona="creator-a",
        version=1,
        consolidated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        note_count=3,
        summary="Trades momentum names, mostly semis.",
        beliefs=(),
        playbook=(),
        vocabulary=(),
        path="profile.md",
    )
    fields.update(overrides)
    return PersonaProfile(**fields)  # type: ignore[arg-type]


def _ask(settings: Settings, **overrides: object) -> ask.AskResult:
    fields: dict[str, object] = dict(
        persona_slug="creator-a",
        question="What do you think of NVDA?",
        symbol=None,
        profile=_profile(),
        notes=(_note("n1"),),
        settings=settings,
        budget=_budget(),
    )
    fields.update(overrides)
    return ask.ask_persona(**fields)  # type: ignore[arg-type]


def _bar_series(symbol: str, *, close: float = 191.66, ts: dt.datetime | None = None) -> BarSeries:
    bar = Bar(ts=ts or dt.datetime(2026, 8, 28, tzinfo=dt.UTC), open=190.0, high=192.0, low=189.0, close=close)
    return BarSeries(symbol=symbol, interval=Interval.DAY, source=BarSource.STORE, bars=[bar])


# ---------------------------------------------------------------------------
# Retrieval -- symbol-relevant notes come first
# ---------------------------------------------------------------------------


class TestRetrieval:
    def test_notes_mentioning_the_symbol_are_prioritised_newest_first(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        nvda_mention = (TickerMention(symbol="NVDA", stance="bullish", reasoning="guidance beat"),)
        old_nvda = _note("old-nvda", published=dt.datetime(2026, 1, 1, tzinfo=dt.UTC), mentions=nvda_mention)
        new_nvda = _note("new-nvda", published=dt.datetime(2026, 6, 1, tzinfo=dt.UTC), mentions=nvda_mention)
        unrelated = _note("unrelated", published=dt.datetime(2026, 7, 1, tzinfo=dt.UTC))
        captured = _stub_returning(monkeypatch, _draft())

        _ask(settings, symbol="NVDA", notes=(old_nvda, unrelated, new_nvda))

        user = captured["user"]
        assert isinstance(user, str)
        # Both NVDA notes (newest of them first) precede the unrelated one in the rendered prompt.
        assert user.index("note_id: new-nvda") < user.index("note_id: old-nvda") < user.index("note_id: unrelated")

    def test_symbol_is_normalised_case_insensitively_against_mentions(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mention = (TickerMention(symbol="TSLA", stance="neutral", reasoning="watching"),)
        note = _note("n1", mentions=mention)
        captured = _stub_returning(monkeypatch, _draft())

        _ask(settings, symbol="tsla", notes=(note,))

        assert "TSLA" in captured["system"]  # type: ignore[operator]

    def test_without_a_symbol_the_most_recent_notes_are_used(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        older = _note("old", published=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        newer = _note("new", published=dt.datetime(2026, 6, 1, tzinfo=dt.UTC))
        captured = _stub_returning(monkeypatch, _draft())

        _ask(settings, symbol=None, notes=(older, newer))

        user = captured["user"]
        assert isinstance(user, str)
        assert user.index("note_id: new") < user.index("note_id: old")

    def test_capped_at_max_context_notes(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        # Zero-padded ids so no note_id is a string-prefix of another (e.g. "n1" of "n10"), which
        # would otherwise make the substring-based count below overcount.
        notes = tuple(
            _note(f"n{i:02d}", published=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) + dt.timedelta(days=i))
            for i in range(ask.MAX_CONTEXT_NOTES + 5)
        )
        captured = _stub_returning(monkeypatch, _draft())

        _ask(settings, symbol=None, notes=notes)

        user = captured["user"]
        assert isinstance(user, str)
        included = sum(1 for note in notes if f"note_id: {note.note_id}" in user)
        assert included == ask.MAX_CONTEXT_NOTES


# ---------------------------------------------------------------------------
# Citation filtering -- ours to enforce, never the model's to self-police
# ---------------------------------------------------------------------------


class TestRenderProfile:
    """`_render_profile` must surface the persona's *strategy* memory -- methodology and the macro
    regime view -- not just summary/beliefs/playbook/vocabulary. These were consolidated but never
    shown to the ask model before, so a "which indicators do you use" question was answered from raw
    notes while the distilled answer sat unused. See `_render_profile`'s own docstring."""

    def test_methodology_and_regime_are_rendered(self) -> None:
        profile = _profile(
            methodology=(
                ProfileClaim(text="Reads two Bollinger bands for entries", citations=("n1",)),
            ),
            regime=RegimeView(
                risk="off",
                rates="watches the 10-year yield",
                summary="cautious into rate volatility",
                sectors_favoured=("energy",),
                has_signal=True,
            ),
        )
        rendered = ask._render_profile(profile)
        assert "two Bollinger bands" in rendered
        assert "Methodology" in rendered
        assert "10-year yield" in rendered
        assert "risk posture off" in rendered
        assert "energy" in rendered

    def test_regime_without_signal_is_omitted(self) -> None:
        profile = _profile(regime=RegimeView(risk="unclear", has_signal=False))
        rendered = ask._render_profile(profile)
        assert "Macro/regime view" not in rendered

    def test_empty_methodology_and_regime_render_nothing_extra(self) -> None:
        rendered = ask._render_profile(_profile())
        assert "Methodology" not in rendered
        assert "Macro/regime view" not in rendered


class TestCitationFiltering:
    def test_citations_within_the_input_set_are_kept(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(citations=("n1",)))
        result = _ask(settings, notes=(_note("n1"),))
        assert result.answer.citations == ("n1",)

    def test_a_citation_outside_the_input_note_id_set_is_dropped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(citations=("n1", "does-not-exist")))
        result = _ask(settings, notes=(_note("n1"),))
        assert result.answer.citations == ("n1",)

    def test_dropped_citations_are_logged(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        _stub_returning(monkeypatch, _draft(citations=("ghost-note",)))
        with caplog.at_level("WARNING", logger="app.personas.ask"):
            _ask(settings, notes=(_note("n1"),))
        assert "ghost-note" in caplog.text

    def test_a_citation_is_invalid_when_the_note_was_not_selected_into_context(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Only notes actually selected into the prompt (n1..n_cap) count as valid -- a note that
        # exists for the persona but was not shown to the model this call is not a legitimate cite.
        many_notes = tuple(
            _note(f"n{i}", published=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) + dt.timedelta(days=i))
            for i in range(ask.MAX_CONTEXT_NOTES + 1)
        )
        excluded_id = many_notes[0].note_id  # oldest, pushed out by the cap
        _stub_returning(monkeypatch, _draft(citations=(excluded_id,)))
        result = _ask(settings, symbol=None, notes=many_notes)
        assert result.answer.citations == ()


# ---------------------------------------------------------------------------
# Nothing on record -- no model call, never raised
# ---------------------------------------------------------------------------


class TestNothingOnRecord:
    def test_empty_notes_and_no_profile_returns_nothing_on_record_without_a_model_call(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_if_called(**kwargs: object) -> GroundedResult[ask._AnswerDraft]:
            raise AssertionError("run_grounded should not be called when there is nothing on record")

        monkeypatch.setattr(ask, "run_grounded", fail_if_called)

        result = _ask(settings, profile=None, notes=())

        assert result.calls == ()
        assert result.answer.citations == ()
        assert result.answer.stance is None
        assert result.answer.degraded is False
        assert result.answer.grounding.ok is True
        assert "creator-a" in result.answer.answer
        assert "nothing" in result.answer.answer.lower() or "don't have" in result.answer.answer.lower()

    def test_nothing_on_record_cost_usd_reflects_the_unspent_budget(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        result = _ask(settings, profile=None, notes=(), budget=_budget(spent="1.23"))
        assert result.answer.cost_usd == "1.23"

    def test_a_profile_with_no_notes_still_answers_from_the_profile(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Profile present but zero notes: not the "nothing on record" short circuit -- the model is
        # still asked, grounded on the profile alone.
        captured = _stub_returning(monkeypatch, _draft())
        result = _ask(settings, profile=_profile(), notes=())
        assert "run_grounded" not in captured or captured  # a call was made
        assert result.calls != ()


# ---------------------------------------------------------------------------
# Degraded verdicts pass through -- never raised
# ---------------------------------------------------------------------------


class TestDegradedPassthrough:
    def test_a_failed_grounding_verdict_is_returned_not_raised(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(), ok=False, degraded=True)
        result = _ask(settings)
        assert result.answer.grounding.ok is False
        assert result.answer.degraded is True
        assert result.answer.answer == "This is what they'd say."

    def test_citation_filtering_still_runs_on_a_degraded_answer(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(citations=("nope",)), ok=False, degraded=True)
        result = _ask(settings)
        assert result.answer.citations == ()


# ---------------------------------------------------------------------------
# Stance
# ---------------------------------------------------------------------------


class TestStance:
    def test_stance_is_filled_from_the_record_when_a_symbol_is_asked(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(stance="bullish"))
        result = _ask(settings, symbol="NVDA")
        assert result.answer.stance == "bullish"

    def test_stance_is_forced_to_none_when_no_symbol_was_asked(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Even if the model returns a stance anyway, it is discarded -- there is nothing a stance
        # could be "about" when no symbol was ever named in the question.
        _stub_returning(monkeypatch, _draft(stance="bullish"))
        result = _ask(settings, symbol=None)
        assert result.answer.stance is None

    def test_unclear_stance_from_the_model_is_preserved(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(stance="unclear"))
        result = _ask(settings, symbol="NVDA")
        assert result.answer.stance == "unclear"

    def test_the_symbol_field_on_the_answer_is_upper_cased(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft())
        result = _ask(settings, symbol="nvda")
        assert result.answer.symbol == "NVDA"


# ---------------------------------------------------------------------------
# Market snapshot -- never breaks the answer
# ---------------------------------------------------------------------------


class TestMarketSnapshot:
    def test_snapshot_is_fetched_and_added_as_evidence_when_a_symbol_is_given(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fake_ensure_series(symbol: str, interval: Interval, *, limit: int, settings: Settings) -> BarSeries:
            return _bar_series(symbol, close=191.66)

        monkeypatch.setattr(ask, "ensure_series", fake_ensure_series)
        captured = _stub_returning(monkeypatch, _draft())

        _ask(settings, symbol="NVDA")

        pack = captured["pack"]
        titles = [section.title for section in pack.sections]  # type: ignore[union-attr]
        assert "Market snapshot" in titles
        user = captured["user"]
        assert "191.66" in user  # type: ignore[operator]

    def test_snapshot_omitted_gracefully_when_ensure_series_raises_provider_error(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raiser(symbol: str, interval: Interval, *, limit: int, settings: Settings) -> BarSeries:
            raise ProviderUnavailable("no data", provider="yahoo")

        monkeypatch.setattr(ask, "ensure_series", raiser)
        captured = _stub_returning(monkeypatch, _draft())

        _ask(settings, symbol="NVDA")  # must not raise

        pack = captured["pack"]
        titles = [section.title for section in pack.sections]  # type: ignore[union-attr]
        assert "Market snapshot" not in titles

    def test_snapshot_omitted_gracefully_on_an_unexpected_exception(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raiser(symbol: str, interval: Interval, *, limit: int, settings: Settings) -> BarSeries:
            raise RuntimeError("boom")

        monkeypatch.setattr(ask, "ensure_series", raiser)
        captured = _stub_returning(monkeypatch, _draft())

        result = _ask(settings, symbol="NVDA")  # must not raise
        assert result.answer.answer == "This is what they'd say."

        pack = captured["pack"]
        titles = [section.title for section in pack.sections]  # type: ignore[union-attr]
        assert "Market snapshot" not in titles

    def test_snapshot_omitted_when_no_symbol_was_asked(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_if_called(symbol: str, interval: Interval, *, limit: int, settings: Settings) -> BarSeries:
            raise AssertionError("ensure_series should not be called without a symbol")

        monkeypatch.setattr(ask, "ensure_series", fail_if_called)
        captured = _stub_returning(monkeypatch, _draft())

        _ask(settings, symbol=None)

        pack = captured["pack"]
        titles = [section.title for section in pack.sections]  # type: ignore[union-attr]
        assert "Market snapshot" not in titles

    def test_snapshot_omitted_when_the_series_has_no_bars(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fake_ensure_series(symbol: str, interval: Interval, *, limit: int, settings: Settings) -> BarSeries:
            return BarSeries(symbol=symbol, interval=interval, source=BarSource.STORE, bars=[])

        monkeypatch.setattr(ask, "ensure_series", fake_ensure_series)
        captured = _stub_returning(monkeypatch, _draft())

        _ask(settings, symbol="NVDA")

        pack = captured["pack"]
        titles = [section.title for section in pack.sections]  # type: ignore[union-attr]
        assert "Market snapshot" not in titles


# ---------------------------------------------------------------------------
# Cost accounting
# ---------------------------------------------------------------------------


class TestCostAccounting:
    def test_cost_usd_reflects_the_budget_spend_from_run_grounded(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft())
        result = _ask(settings, budget=_budget(spent="2.00"))
        # `_grounded_result` adds $0.01 on top of whatever budget it was handed.
        assert result.answer.cost_usd == "2.01"


# ---------------------------------------------------------------------------
# AgentUnavailable / BudgetExhausted propagate unchanged
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_agent_unavailable_propagates(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raiser(**kwargs: object) -> GroundedResult[ask._AnswerDraft]:
            raise AgentUnavailable("no credential configured")

        monkeypatch.setattr(ask, "run_grounded", raiser)
        with pytest.raises(AgentUnavailable):
            _ask(settings)

    def test_budget_exhausted_propagates(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raiser(**kwargs: object) -> GroundedResult[ask._AnswerDraft]:
            raise BudgetExhausted(Decimal("5.00"), Decimal("5.00"))

        monkeypatch.setattr(ask, "run_grounded", raiser)
        with pytest.raises(BudgetExhausted):
            _ask(settings)


# ---------------------------------------------------------------------------
# Language plumbing
# ---------------------------------------------------------------------------


class TestLanguage:
    def test_default_summary_lang_reaches_the_prompt(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        assert settings.persona_summary_lang == "en"
        captured = _stub_returning(monkeypatch, _draft())
        _ask(settings)
        assert "in en" in captured["system"]  # type: ignore[operator]
