"""Unit tests for `app.personas.consolidate`.

No test here makes a real model call: `consolidate.run_grounded` is monkeypatched to a fake that
returns a caller-supplied `ProfileDraft` wrapped in a `GroundedResult`, exactly the pattern
`tests/test_personas_summarize.py` already uses for the same reason. What is asserted is this
module's own logic -- citation filtering (including a hallucinated note_id), per-symbol thesis
grouping and newest-stance-wins, truncation, the empty-input `ValueError`, degraded-verdict
pass-through, error propagation, and that `ProfileClaim`'s own non-empty-citations validator is
respected by both this module and the pinned model it builds on.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.agentdesk.grounding import GroundedResult
from app.agentdesk.models import GroundingVerdict
from app.agents.models import AgentBudget, AgentCall, AgentUnavailable, BudgetExhausted
from app.config import Settings
from app.personas import consolidate
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


def _budget(cap: str = "5.00") -> AgentBudget:
    return AgentBudget(cap_usd=Decimal(cap))


def _fake_call() -> AgentCall:
    return AgentCall(
        call_id="call-1", role="swarm_worker", model="claude-haiku-4-5-20251001",
        created_at=dt.datetime.now(dt.UTC), system="s", user="u", raw_response="r",
        cost_usd=Decimal("0.01"),
    )


def _grounded_result(
    draft: consolidate.ProfileDraft, *, budget: AgentBudget, ok: bool = True, degraded: bool = False,
) -> GroundedResult[consolidate.ProfileDraft]:
    verdict = GroundingVerdict(ok=ok, degraded=degraded, attempts=1)
    new_budget = AgentBudget(
        cap_usd=budget.cap_usd, spent_usd=budget.spent_usd + Decimal("0.01"), calls=budget.calls + 1,
    )
    return GroundedResult(value=draft, verdict=verdict, calls=(_fake_call(),), budget=new_budget)


def _draft(**overrides: object) -> consolidate.ProfileDraft:
    fields: dict[str, object] = dict(
        summary="A summary of who they are.",
        beliefs=(),
        playbook=(),
        methodology=(),
        vocabulary=(),
    )
    fields.update(overrides)
    return consolidate.ProfileDraft(**fields)  # type: ignore[arg-type]


def _stub_returning(
    monkeypatch: pytest.MonkeyPatch,
    draft: consolidate.ProfileDraft,
    *,
    ok: bool = True,
    degraded: bool = False,
) -> dict[str, object]:
    """Patch `consolidate.run_grounded` to hand back `draft` (wrapped), and capture every kwarg the
    call site passed -- `captured["system"]`, `captured["user"]`, `captured["pack"]`, etc -- so a
    test can inspect the exact prompt/pack this module built without needing a real model call."""
    captured: dict[str, object] = {}

    def fake_run_grounded(**kwargs: object) -> GroundedResult[consolidate.ProfileDraft]:
        captured.update(kwargs)
        return _grounded_result(draft, budget=kwargs["budget"], ok=ok, degraded=degraded)  # type: ignore[arg-type]

    monkeypatch.setattr(consolidate, "run_grounded", fake_run_grounded)
    return captured


def _note(
    note_id: str,
    *,
    persona: str = "creator-a",
    published: dt.datetime | None = None,
    ingested_at: dt.datetime | None = None,
    title: str | None = "A video",
    summary: str = "A summary.",
    themes: tuple[str, ...] = ("theme one",),
    quotes: tuple[str, ...] = (),
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
        themes=themes,
        quotes=quotes,
        mentions=mentions,
        path=f"notes/{note_id}.md",
        degraded=False,
    )


def _consolidate(settings: Settings, **overrides: object) -> consolidate.ConsolidationResult:
    fields: dict[str, object] = dict(
        persona_slug="creator-a",
        notes=(_note("n1"),),
        settings=settings,
        budget=_budget(),
    )
    fields.update(overrides)
    return consolidate.consolidate_notes(**fields)  # type: ignore[arg-type]


def _prior_profile(**overrides: object) -> PersonaProfile:
    fields: dict[str, object] = dict(
        persona="creator-a",
        version=1,
        consolidated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        note_count=5,
        summary="An existing standing summary.",
        path="personas/creator-a/profile.md",
    )
    fields.update(overrides)
    return PersonaProfile(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ProfileDraft schema
# ---------------------------------------------------------------------------


class TestProfileDraft:
    def test_accepts_the_documented_fields(self) -> None:
        draft = _draft(summary="who they are")
        assert draft.summary == "who they are"
        assert draft.beliefs == ()

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            consolidate.ProfileDraft(
                summary="s", beliefs=(), playbook=(), methodology=(), vocabulary=(),
                extra_field="not allowed",
            )

    def test_is_frozen(self) -> None:
        draft = _draft()
        with pytest.raises(ValidationError):
            draft.summary = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ProfileClaim's own non-empty-citations validator -- pinned, never redefined here, but this
# module's whole citation-filtering design depends on it being enforced at construction time.
# ---------------------------------------------------------------------------


class TestProfileClaimValidatorIsRespected:
    def test_empty_citations_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValidationError):
            ProfileClaim(text="a belief with no citation", citations=())

    def test_a_profile_draft_cannot_smuggle_an_uncited_claim_past_the_model(self) -> None:
        # Even a hand-built ProfileDraft cannot carry an uncited claim -- ProfileClaim's own
        # validator runs regardless of who constructs it, model or test.
        with pytest.raises(ValidationError):
            _draft(beliefs=(ProfileClaim(text="x", citations=()),))

    def test_theses_built_by_this_module_only_ever_use_real_non_empty_citations(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mentions = (TickerMention(symbol="NVDA", stance="bullish", reasoning="strong guidance"),)
        notes = (_note("n1", mentions=mentions),)
        _stub_returning(monkeypatch, _draft())

        result = _consolidate(settings, notes=notes)
        thesis = result.theses[0]
        assert thesis.claims[0].citations == ("n1",)


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_empty_notes_raises_value_error_rather_than_returning_an_empty_profile(
        self, settings: Settings,
    ) -> None:
        with pytest.raises(ValueError, match="at least one note"):
            _consolidate(settings, notes=())


# ---------------------------------------------------------------------------
# Citation filtering -- ours to enforce, never the model's to self-police
# ---------------------------------------------------------------------------


class TestCitationFiltering:
    def test_a_claim_citing_only_real_note_ids_is_kept(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"), _note("n2"))
        good = ProfileClaim(text="a real belief", citations=("n1", "n2"))
        _stub_returning(monkeypatch, _draft(beliefs=(good,)))

        result = _consolidate(settings, notes=notes)
        assert result.draft.beliefs == (good,)

    def test_a_claim_citing_a_hallucinated_note_id_is_dropped_whole(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        hallucinated = ProfileClaim(text="a fabricated belief", citations=("n1", "does-not-exist"))
        _stub_returning(monkeypatch, _draft(beliefs=(hallucinated,)))

        result = _consolidate(settings, notes=notes)
        # Dropped whole -- not repaired down to its one valid citation.
        assert result.draft.beliefs == ()

    def test_a_claim_citing_only_a_hallucinated_note_id_is_dropped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        hallucinated = ProfileClaim(text="entirely made up", citations=("ghost-note",))
        _stub_returning(monkeypatch, _draft(playbook=(hallucinated,)))

        result = _consolidate(settings, notes=notes)
        assert result.draft.playbook == ()

    def test_dropping_a_claim_can_leave_a_section_empty_without_backfilling(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        only_bad = ProfileClaim(text="junk", citations=("ghost",))
        _stub_returning(monkeypatch, _draft(beliefs=(only_bad,), playbook=(only_bad,)))

        result = _consolidate(settings, notes=notes)
        assert result.draft.beliefs == ()
        assert result.draft.playbook == ()
        # The rest of the draft is untouched.
        assert result.draft.summary == "A summary of who they are."

    def test_dropped_claims_are_logged_not_silently_discarded(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        notes = (_note("n1"),)
        hallucinated = ProfileClaim(text="junk claim", citations=("fake-id",))
        _stub_returning(monkeypatch, _draft(beliefs=(hallucinated,)))

        with caplog.at_level("WARNING", logger="app.personas.consolidate"):
            _consolidate(settings, notes=notes)
        assert "fake-id" in caplog.text

    def test_mixed_valid_and_invalid_claims_keep_only_the_valid_ones(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"), _note("n2"))
        good = ProfileClaim(text="good", citations=("n1",))
        bad = ProfileClaim(text="bad", citations=("n1", "phantom"))
        _stub_returning(monkeypatch, _draft(beliefs=(good, bad)))

        result = _consolidate(settings, notes=notes)
        assert result.draft.beliefs == (good,)


# ---------------------------------------------------------------------------
# Methodology -- the mechanical toolkit, distinct from the strategic playbook (Phase 7a)
# ---------------------------------------------------------------------------


class TestMethodology:
    def test_a_methodology_claim_citing_only_real_note_ids_is_kept(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        good = ProfileClaim(text="Uses a 14-day RSI on the daily chart to time entries.", citations=("n1",))
        _stub_returning(monkeypatch, _draft(methodology=(good,)))

        result = _consolidate(settings, notes=notes)
        assert result.draft.methodology == (good,)

    def test_a_methodology_claim_citing_a_hallucinated_note_id_is_dropped_whole(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        hallucinated = ProfileClaim(
            text="Trades MACD crossovers on the weekly chart.", citations=("n1", "does-not-exist"),
        )
        _stub_returning(monkeypatch, _draft(methodology=(hallucinated,)))

        result = _consolidate(settings, notes=notes)
        # Dropped whole -- not repaired down to its one valid citation, same rule as beliefs/playbook.
        assert result.draft.methodology == ()

    def test_a_methodology_claim_citing_only_a_hallucinated_note_id_is_dropped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        hallucinated = ProfileClaim(text="entirely made up toolkit", citations=("ghost-note",))
        _stub_returning(monkeypatch, _draft(methodology=(hallucinated,)))

        result = _consolidate(settings, notes=notes)
        assert result.draft.methodology == ()

    def test_dropped_methodology_claims_are_logged(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        notes = (_note("n1"),)
        hallucinated = ProfileClaim(text="junk toolkit claim", citations=("fake-id",))
        _stub_returning(monkeypatch, _draft(methodology=(hallucinated,)))

        with caplog.at_level("WARNING", logger="app.personas.consolidate"):
            _consolidate(settings, notes=notes)
        assert "fake-id" in caplog.text
        assert "methodology" in caplog.text

    def test_empty_methodology_passes_through_as_an_honest_signal_not_an_error(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A pure macro commentator whose notes never discuss technique -- the model returns an empty
        # methodology list and this module must not invent, backfill, or reject it.
        _stub_returning(monkeypatch, _draft())  # methodology=() by default via the _draft helper
        result = _consolidate(settings)
        assert result.draft.methodology == ()

    def test_beliefs_and_playbook_are_unaffected_by_methodology_filtering(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        good_belief = ProfileClaim(text="a real belief", citations=("n1",))
        good_playbook = ProfileClaim(text="a real playbook habit", citations=("n1",))
        hallucinated_methodology = ProfileClaim(text="fake toolkit", citations=("ghost",))
        _stub_returning(
            monkeypatch,
            _draft(
                beliefs=(good_belief,), playbook=(good_playbook,), methodology=(hallucinated_methodology,),
            ),
        )

        result = _consolidate(settings, notes=notes)
        assert result.draft.beliefs == (good_belief,)
        assert result.draft.playbook == (good_playbook,)
        assert result.draft.methodology == ()

    def test_system_prompt_instructs_extraction_of_the_mechanical_toolkit(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_returning(monkeypatch, _draft())
        _consolidate(settings)

        system = captured["system"]
        assert isinstance(system, str)
        assert "METHODOLOGY" in system
        # The technique vocabulary the task requires the prompt to name.
        for term in ("indicator", "timeframe", "entry", "exit", "position-sizing", "risk", "tool"):
            assert term in system.lower(), f"expected {term!r} in the system prompt"
        # Distinct from the strategic playbook -- the prompt must draw the boundary explicitly.
        assert "playbook" in system.lower()

    def test_user_prompt_asks_for_methodology_entries_in_the_summary_language(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_returning(monkeypatch, _draft())
        _consolidate(settings)
        assert "methodology" in captured["user"]  # type: ignore[operator]

    def test_methodology_prose_is_folded_into_what_the_grounding_gate_checks(self) -> None:
        """`_draft_prose` -- the text `run_grounded`'s gate scans for ungrounded numbers -- must
        include methodology claim text, so a fabricated stop/size level slips past neither the
        prompt-building nor the gate itself.

        Deliberately not an indicator window like "14-day RSI": `numeric_tokens` exempts parameterised
        indicator periods everywhere (they name a parameter, not a measurement -- see its own
        docstring), so a stop-loss price level is used here instead, the same kind of figure a
        fabricated belief or playbook claim would be caught on.
        """
        from app.agentdesk.grounding import check

        draft = _draft(
            methodology=(
                ProfileClaim(text="Sets a stop-loss at 145.50 below entry.", citations=("n1",)),
            ),
        )
        prose = consolidate._draft_prose(draft)
        assert "145.50" in prose

        # The evidence pack built from the notes never mentions "145.50" -- a fabricated stop level in
        # the model's methodology text must be caught exactly like a fabricated belief/playbook number.
        notes_text = "The influencer discussed NVDA guidance up 12.3% according to the note."
        pack = consolidate._build_evidence_pack(notes_text)
        verdict = check(prose, pack)
        assert verdict.ok is False
        assert verdict.issues[0].kind == "ungrounded_number"


# ---------------------------------------------------------------------------
# Per-symbol thesis grouping and newest-stance-wins
# ---------------------------------------------------------------------------


class TestThesisGrouping:
    def test_newest_stance_wins_even_when_input_order_is_not_newest_first(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        older = _note(
            "old",
            published=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="guidance beat"),),
        )
        newer = _note(
            "new",
            published=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
            mentions=(TickerMention(symbol="NVDA", stance="bearish", reasoning="valuation concern"),),
        )
        _stub_returning(monkeypatch, _draft())

        # Deliberately passed oldest-first, to prove the module sorts defensively rather than
        # trusting caller order.
        result = _consolidate(settings, notes=(older, newer))

        theses = {t.symbol: t for t in result.theses}
        assert theses["NVDA"].stance == "bearish"
        assert theses["NVDA"].updated_at == dt.datetime(2026, 6, 1, tzinfo=dt.UTC)

    def test_claims_cite_every_note_that_named_the_symbol(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        n1 = _note(
            "n1",
            published=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            mentions=(TickerMention(symbol="TSLA", stance="neutral", reasoning="watching delivery numbers"),),
        )
        n2 = _note(
            "n2",
            published=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
            mentions=(TickerMention(symbol="TSLA", stance="bullish", reasoning="delivery beat"),),
        )
        _stub_returning(monkeypatch, _draft())

        result = _consolidate(settings, notes=(n1, n2))
        thesis = next(t for t in result.theses if t.symbol == "TSLA")

        cited_note_ids = {citation for claim in thesis.claims for citation in claim.citations}
        assert cited_note_ids == {"n1", "n2"}
        assert thesis.stance == "bullish"  # n2 is newer

    def test_mention_with_blank_reasoning_affects_stance_but_not_claims(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        older = _note(
            "old",
            published=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            mentions=(TickerMention(symbol="AAPL", stance="neutral", reasoning="a real reason"),),
        )
        newer = _note(
            "new",
            published=dt.datetime(2026, 3, 1, tzinfo=dt.UTC),
            mentions=(TickerMention(symbol="AAPL", stance="bearish", reasoning=""),),
        )
        _stub_returning(monkeypatch, _draft())

        result = _consolidate(settings, notes=(older, newer))
        thesis = next(t for t in result.theses if t.symbol == "AAPL")

        assert thesis.stance == "bearish"  # blank reasoning still counts for stance
        assert len(thesis.claims) == 1  # but contributes no claim
        assert thesis.claims[0].citations == ("old",)

    def test_multiple_symbols_produce_separate_theses_sorted_by_symbol(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        note = _note(
            "n1",
            mentions=(
                TickerMention(symbol="TSLA", stance="bullish", reasoning="a"),
                TickerMention(symbol="AAPL", stance="neutral", reasoning="b"),
            ),
        )
        _stub_returning(monkeypatch, _draft())

        result = _consolidate(settings, notes=(note,))
        assert [t.symbol for t in result.theses] == ["AAPL", "TSLA"]

    def test_no_mentions_anywhere_yields_no_theses(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft())
        result = _consolidate(settings, notes=(_note("n1", mentions=()),))
        assert result.theses == ()

    def test_theses_are_not_asked_of_the_model(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # ProfileDraft has no field for theses at all -- this is really just documentation that the
        # schema enforces the "never ask the model" rule structurally, not just by convention.
        assert "theses" not in consolidate.ProfileDraft.model_fields
        assert "thesis" not in consolidate.ProfileDraft.model_fields


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    def test_over_long_input_is_truncated_with_an_explicit_marker(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        big_summary = "x" * 10_000
        notes = tuple(
            _note(f"n{i}", published=dt.datetime(2026, 1, i + 1, tzinfo=dt.UTC), summary=big_summary)
            for i in range(1, 9)  # 8 notes x ~10k chars > MAX_INPUT_CHARS (60k)
        )
        captured = _stub_returning(monkeypatch, _draft())

        _consolidate(settings, notes=notes)

        user = captured["user"]
        pack = captured["pack"]
        assert isinstance(user, str)
        assert "TRUNCATED" in user
        assert "TRUNCATED" in pack.sections[0].text  # type: ignore[union-attr]

    def test_truncation_drops_the_oldest_notes_first(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        big_summary = "x" * 10_000
        newest = _note("newest", published=dt.datetime(2026, 12, 31, tzinfo=dt.UTC), summary=big_summary)
        oldest = _note("oldest", published=dt.datetime(2020, 1, 1, tzinfo=dt.UTC), summary=big_summary)
        notes = (
            *(
                _note(f"mid{i}", published=dt.datetime(2026, 1, i + 1, tzinfo=dt.UTC), summary=big_summary)
                for i in range(1, 8)
            ),
            newest,
            oldest,
        )
        captured = _stub_returning(monkeypatch, _draft())

        _consolidate(settings, notes=notes)

        user = captured["user"]
        assert isinstance(user, str)
        assert "note_id: newest" in user
        assert "note_id: oldest" not in user

    def test_short_input_is_not_truncated(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_returning(monkeypatch, _draft())
        _consolidate(settings, notes=(_note("n1", summary="a short note"),))
        assert "TRUNCATED" not in captured["user"]  # type: ignore[operator]

    def test_a_single_oversized_note_is_still_included_alone(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        huge = _note("n1", summary="x" * (consolidate.MAX_INPUT_CHARS + 5_000))
        captured = _stub_returning(monkeypatch, _draft())
        _consolidate(settings, notes=(huge,))
        assert "note_id: n1" in captured["user"]  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Degraded verdicts pass through -- never raised
# ---------------------------------------------------------------------------


class TestDegradedPassthrough:
    def test_a_failed_grounding_verdict_is_returned_not_raised(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(), ok=False, degraded=True)
        result = _consolidate(settings)
        assert result.verdict.ok is False
        assert result.verdict.degraded is True
        assert result.draft.summary == "A summary of who they are."

    def test_citation_filtering_still_runs_on_a_degraded_draft(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        hallucinated = ProfileClaim(text="junk", citations=("nope",))
        _stub_returning(monkeypatch, _draft(beliefs=(hallucinated,)), ok=False, degraded=True)
        result = _consolidate(settings)
        assert result.draft.beliefs == ()


# ---------------------------------------------------------------------------
# AgentUnavailable / BudgetExhausted propagate unchanged
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_agent_unavailable_propagates(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raiser(**kwargs: object) -> GroundedResult[consolidate.ProfileDraft]:
            raise AgentUnavailable("no credential configured")

        monkeypatch.setattr(consolidate, "run_grounded", raiser)
        with pytest.raises(AgentUnavailable):
            _consolidate(settings)

    def test_budget_exhausted_propagates(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raiser(**kwargs: object) -> GroundedResult[consolidate.ProfileDraft]:
            raise BudgetExhausted(Decimal("5.00"), Decimal("5.00"))

        monkeypatch.setattr(consolidate, "run_grounded", raiser)
        with pytest.raises(BudgetExhausted):
            _consolidate(settings)


# ---------------------------------------------------------------------------
# Language plumbing
# ---------------------------------------------------------------------------


class TestLanguage:
    def test_default_summary_lang_reaches_the_prompt(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        assert settings.persona_summary_lang == "en"
        captured = _stub_returning(monkeypatch, _draft())
        _consolidate(settings)
        assert "in en" in captured["system"]  # type: ignore[operator]

    def test_custom_summary_lang_setting_flows_into_the_system_prompt(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data", persona_summary_lang="ko")
        with pytest.MonkeyPatch.context() as mp:
            captured = _stub_returning(mp, _draft())
            _consolidate(settings)
        assert "in ko" in captured["system"]  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Evidence pack / grounding -- pure-function tests, no mocking at all
# ---------------------------------------------------------------------------


class TestEvidencePackGrounding:
    def test_a_number_present_in_the_notes_is_grounded(self) -> None:
        from app.agentdesk.grounding import check

        notes_text = "NVDA guidance was up 12.3% according to the note."
        pack = consolidate._build_evidence_pack(notes_text)
        verdict = check("Guidance was up 12.3%.", pack)
        assert verdict.ok is True

    def test_a_number_absent_from_the_notes_is_rejected(self) -> None:
        from app.agentdesk.grounding import check

        notes_text = "NVDA guidance was up 12.3% according to the note."
        pack = consolidate._build_evidence_pack(notes_text)
        verdict = check("Their price target is 999.99.", pack)
        assert verdict.ok is False
        assert verdict.issues[0].kind == "ungrounded_number"


# ---------------------------------------------------------------------------
# Regime extraction -- the macro-posture counterpart to methodology
# ---------------------------------------------------------------------------


class TestRegimeExtraction:
    def test_profile_draft_regime_defaults_to_an_empty_no_signal_view(self) -> None:
        draft = _draft()
        assert draft.regime == RegimeView()
        assert draft.regime.has_signal is False

    def test_a_regime_citing_a_valid_and_a_bogus_note_id_keeps_only_the_valid_one(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        regime = RegimeView(
            risk="off",
            rates="Expects the Fed to hold rates steady.",
            summary="Cautious on risk assets broadly.",
            sectors_favoured=("utilities",),
            sectors_avoided=("high-beta tech",),
            citations=("n1", "does-not-exist"),
            has_signal=True,
        )
        _stub_returning(monkeypatch, _draft(regime=regime))

        result = _consolidate(settings, notes=notes)
        # Kept whole (unlike a ProfileClaim), but with the bogus citation stripped.
        assert result.draft.regime.citations == ("n1",)
        assert result.draft.regime.risk == "off"
        assert result.draft.regime.has_signal is True

    def test_a_regime_citing_only_a_hallucinated_note_id_loses_its_signal(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        regime = RegimeView(
            risk="on", summary="Broadly risk-on.", citations=("ghost-note",), has_signal=True,
        )
        _stub_returning(monkeypatch, _draft(regime=regime))

        result = _consolidate(settings, notes=notes)
        assert result.draft.regime.citations == ()
        # No surviving citation -- has_signal is recomputed False regardless of what the model sent.
        assert result.draft.regime.has_signal is False

    def test_a_purely_technical_persona_yields_has_signal_false(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The model returns the honest-empty default regime for a trader with no macro view.
        _stub_returning(monkeypatch, _draft())
        result = _consolidate(settings)
        assert result.draft.regime == RegimeView()
        assert result.draft.regime.has_signal is False

    def test_dropped_regime_citation_is_logged(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        notes = (_note("n1"),)
        regime = RegimeView(risk="on", summary="x", citations=("fake-regime-id",), has_signal=True)
        _stub_returning(monkeypatch, _draft(regime=regime))

        with caplog.at_level("WARNING", logger="app.personas.consolidate"):
            _consolidate(settings, notes=notes)
        assert "fake-regime-id" in caplog.text

    def test_system_prompt_instructs_regime_extraction(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_returning(monkeypatch, _draft())
        _consolidate(settings)

        system = captured["system"]
        assert isinstance(system, str)
        assert "REGIME" in system
        for term in ("risk", "rates", "sectors"):
            assert term in system.lower()
        # Honest-empty instruction for a purely technical trader.
        assert "has_signal" in system

    def test_user_prompt_asks_for_a_regime_entry_in_the_summary_language(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_returning(monkeypatch, _draft())
        _consolidate(settings)
        assert "regime" in captured["user"]  # type: ignore[operator]

    def test_regime_textual_fields_are_folded_into_the_grounding_gate(self) -> None:
        """`_draft_prose` must include regime's `rates`/`summary`/sector text so a fabricated macro
        figure is caught exactly like a fabricated belief/playbook/methodology number."""
        from app.agentdesk.grounding import check

        draft = _draft(
            regime=RegimeView(
                risk="off",
                rates="Sees the Fed cutting to 3.25% by year end.",
                citations=("n1",),
                has_signal=True,
            ),
        )
        prose = consolidate._draft_prose(draft)
        assert "3.25" in prose

        notes_text = "The influencer discussed NVDA guidance up 12.3% according to the note."
        pack = consolidate._build_evidence_pack(notes_text)
        verdict = check(prose, pack)
        assert verdict.ok is False
        assert verdict.issues[0].kind == "ungrounded_number"


# ---------------------------------------------------------------------------
# Incremental consolidation -- folding new notes into a standing profile
# ---------------------------------------------------------------------------


class TestIncrementalConsolidation:
    def test_default_no_prior_profile_behaves_exactly_as_before(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_returning(monkeypatch, _draft())
        _consolidate(settings)

        assert "STANDING PROFILE" not in captured["user"]  # type: ignore[operator]
        assert "INCREMENTAL UPDATE" not in captured["system"]  # type: ignore[operator]

    def test_prior_profile_is_rendered_into_the_user_prompt(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        prior = _prior_profile(
            beliefs=(ProfileClaim(text="Bullish on semis.", citations=("old-note",)),),
        )
        captured = _stub_returning(monkeypatch, _draft())
        _consolidate(settings, prior_profile=prior)

        user = captured["user"]
        system = captured["system"]
        assert isinstance(user, str)
        assert isinstance(system, str)
        assert "STANDING PROFILE" in user
        assert "Bullish on semis." in user
        assert "old-note" in user
        assert "INCREMENTAL UPDATE" in system

    def test_incremental_mode_keeps_a_claim_citing_an_older_note_not_in_the_new_batch(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        prior = _prior_profile(
            beliefs=(ProfileClaim(text="Still bullish on semis.", citations=("old-note",)),),
        )
        # The new batch of notes handed to this call never includes "old-note".
        new_notes = (_note("n2"),)
        kept_claim = ProfileClaim(text="Still bullish on semis.", citations=("old-note",))
        _stub_returning(monkeypatch, _draft(beliefs=(kept_claim,)))

        result = _consolidate(settings, notes=new_notes, prior_profile=prior)
        assert result.draft.beliefs == (kept_claim,)

    def test_without_a_prior_profile_the_same_older_citation_is_dropped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Same claim, same missing note -- but no prior_profile given, so "old-note" is not in the
        # valid set and the claim must be dropped exactly as ordinary hallucinated-citation handling.
        new_notes = (_note("n2"),)
        claim = ProfileClaim(text="Still bullish on semis.", citations=("old-note",))
        _stub_returning(monkeypatch, _draft(beliefs=(claim,)))

        result = _consolidate(settings, notes=new_notes)
        assert result.draft.beliefs == ()

    def test_prior_regime_citations_also_extend_the_valid_set(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        prior = _prior_profile(
            regime=RegimeView(
                risk="off", summary="Cautious on risk assets.", citations=("old-note",), has_signal=True,
            ),
        )
        new_notes = (_note("n2"),)
        kept_regime = RegimeView(
            risk="off", summary="Cautious on risk assets.", citations=("old-note",), has_signal=True,
        )
        _stub_returning(monkeypatch, _draft(regime=kept_regime))

        result = _consolidate(settings, notes=new_notes, prior_profile=prior)
        assert result.draft.regime.citations == ("old-note",)
        assert result.draft.regime.has_signal is True

    def test_prior_profile_with_no_prior_citations_does_not_widen_the_valid_set(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A prior_profile with no claims at all contributes no ids -- an unrelated hallucinated
        # citation is still dropped, proving the union only ever adds real prior citations.
        prior = _prior_profile()
        new_notes = (_note("n2"),)
        claim = ProfileClaim(text="fabricated", citations=("never-existed",))
        _stub_returning(monkeypatch, _draft(beliefs=(claim,)))

        result = _consolidate(settings, notes=new_notes, prior_profile=prior)
        assert result.draft.beliefs == ()
