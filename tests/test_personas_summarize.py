"""Unit tests for `app.personas.summarize`.

No test here makes a real model call: `summarize.run_grounded` is monkeypatched to a fake that
returns a caller-supplied `NoteDraft` wrapped in a `GroundedResult`, exactly the pattern
`tests/test_vibedesk.py` already uses for the same reason. What is asserted is this module's own
logic -- ticker validation, language plumbing into the prompt, degraded-verdict pass-through,
truncation, and the schema's `extra="forbid"` -- plus, without any mocking at all, the grounding-pack
construction itself (`app.agentdesk.grounding.check` is a pure function).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.agentdesk.grounding import GroundedResult, check
from app.agentdesk.models import GroundingVerdict
from app.agents.models import AgentBudget, AgentCall, AgentUnavailable, BudgetExhausted
from app.config import Settings
from app.personas import summarize
from app.personas.models import TickerMention

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
    draft: summarize.NoteDraft, *, budget: AgentBudget, ok: bool = True, degraded: bool = False,
) -> GroundedResult[summarize.NoteDraft]:
    verdict = GroundingVerdict(ok=ok, degraded=degraded, attempts=1)
    new_budget = AgentBudget(
        cap_usd=budget.cap_usd, spent_usd=budget.spent_usd + Decimal("0.01"), calls=budget.calls + 1,
    )
    return GroundedResult(value=draft, verdict=verdict, calls=(_fake_call(),), budget=new_budget)


def _draft(**overrides: object) -> summarize.NoteDraft:
    fields: dict[str, object] = dict(
        summary="A summary.",
        themes=("theme one", "theme two"),
        quotes=("a verbatim quote",),
        mentions=(),
    )
    fields.update(overrides)
    return summarize.NoteDraft(**fields)  # type: ignore[arg-type]


def _stub_returning(
    monkeypatch: pytest.MonkeyPatch, draft: summarize.NoteDraft, *, ok: bool = True, degraded: bool = False,
) -> dict[str, object]:
    """Patch `summarize.run_grounded` to hand back `draft` (wrapped), and capture every kwarg the
    call site passed -- `captured["system"]`, `captured["user"]`, `captured["pack"]`, etc -- so a test
    can inspect the exact prompt/pack this module built without needing a real model call."""
    captured: dict[str, object] = {}

    def fake_run_grounded(**kwargs: object) -> GroundedResult[summarize.NoteDraft]:
        captured.update(kwargs)
        return _grounded_result(draft, budget=kwargs["budget"], ok=ok, degraded=degraded)  # type: ignore[arg-type]

    monkeypatch.setattr(summarize, "run_grounded", fake_run_grounded)
    return captured


def _summarize(settings: Settings, **overrides: object) -> summarize.SummaryResult:
    fields: dict[str, object] = dict(
        text="some text", title=None, url="https://example.com/x", settings=settings, budget=_budget(),
    )
    fields.update(overrides)
    return summarize.summarize_item(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# NoteDraft schema
# ---------------------------------------------------------------------------


class TestNoteDraft:
    def test_accepts_the_documented_fields(self) -> None:
        draft = _draft()
        assert draft.summary == "A summary."
        assert draft.themes == ("theme one", "theme two")

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            summarize.NoteDraft(
                summary="s", themes=("a", "b"), quotes=(), mentions=(), extra_field="not allowed",
            )

    def test_is_frozen(self) -> None:
        draft = _draft()
        with pytest.raises(ValidationError):
            draft.summary = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Ticker validation -- this module's own job, never the model's
# ---------------------------------------------------------------------------


class TestTickerValidation:
    def test_default_validator_drops_shapes_a_real_symbol_cannot_have(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mentions = (
            TickerMention(symbol="NVDA", stance="bullish", reasoning="strong guidance"),
            # Too long for any real ticker -- a hallucinated caption artefact.
            TickerMention(symbol="MARKETCRASH", stance="bearish", reasoning="junk"),
            # Contains a character the conservative shape check does not allow.
            TickerMention(symbol="N/A", stance="unclear", reasoning="junk"),
        )
        _stub_returning(monkeypatch, _draft(mentions=mentions))

        result = _summarize(settings)
        assert {m.symbol for m in result.draft.mentions} == {"NVDA"}

    def test_default_validator_keeps_a_plausible_symbol_with_punctuation(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        mentions = (TickerMention(symbol="BRK.B", stance="neutral", reasoning="holding"),)
        _stub_returning(monkeypatch, _draft(mentions=mentions))

        result = _summarize(settings)
        assert {m.symbol for m in result.draft.mentions} == {"BRK.B"}

    def test_custom_validator_is_the_real_instrument_table_stand_in(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # "LITE" is exactly the brief's own example of an auto-caption mangling a real ticker into an
        # ordinary-looking word; the conservative default shape check cannot catch it (it looks like a
        # perfectly good symbol), which is precisely why a real instrument-table validator is a
        # separate, caller-supplied concern this module never tries to fake.
        mentions = (
            TickerMention(symbol="NVDA", stance="bullish", reasoning="a"),
            TickerMention(symbol="LITE", stance="unclear", reasoning="b"),
        )
        _stub_returning(monkeypatch, _draft(mentions=mentions))

        result = _summarize(settings, symbol_validator=lambda s: s == "NVDA")
        assert {m.symbol for m in result.draft.mentions} == {"NVDA"}

    def test_dropped_mentions_are_logged_not_silently_discarded(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        mentions = (TickerMention(symbol="GARBAGE1", stance="unclear", reasoning="x"),)
        _stub_returning(monkeypatch, _draft(mentions=mentions))

        with caplog.at_level("WARNING", logger="app.personas.summarize"):
            _summarize(settings)
        assert "GARBAGE1" in caplog.text

    def test_no_mentions_is_fine(self, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_returning(monkeypatch, _draft(mentions=()))
        result = _summarize(settings)
        assert result.draft.mentions == ()

    def test_horizon_survives_validation_unchanged(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A kept mention's `horizon` (and `instrument`) must pass through `_validate_mentions`
        # untouched -- if that function ever rebuilt a `TickerMention` from its bare positional
        # fields instead of filtering the model's own instances, these would silently reset to
        # their defaults.
        mentions = (
            TickerMention(symbol="NVDA", stance="bullish", reasoning="a day-trade scalp", horizon="intraday"),
            TickerMention(symbol="AAPL", stance="bullish", reasoning="core holding", horizon="long_term"),
        )
        _stub_returning(monkeypatch, _draft(mentions=mentions))

        result = _summarize(settings)

        by_symbol = {m.symbol: m for m in result.draft.mentions}
        assert by_symbol["NVDA"].horizon == "intraday"
        assert by_symbol["AAPL"].horizon == "long_term"


class TestSystemPromptHorizon:
    def test_system_prompt_names_the_horizon_options(self) -> None:
        assert "horizon" in summarize._SYSTEM_PROMPT
        for option in ("intraday", "swing", "position", "long_term", "unclear"):
            assert option in summarize._SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Language plumbing
# ---------------------------------------------------------------------------


class TestLanguage:
    def test_korean_source_and_english_default_output_lang_reach_the_prompt(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        assert settings.persona_summary_lang == "en"
        korean_text = "안녕하세요 이것은 테스트 스크립트입니다. 저는 NVDA에 대해 이야기하겠습니다."
        captured = _stub_returning(monkeypatch, _draft())

        _summarize(settings, text=korean_text, title="한국어 영상", lang="ko")

        system = captured["system"]
        user = captured["user"]
        assert isinstance(system, str) and isinstance(user, str)
        # Output-language instruction names the settings-configured language...
        assert "in en" in system
        # ...while the source-language hint and the untouched Korean source both reach the user turn.
        assert "Source language hint: ko" in user
        assert korean_text in user

    def test_lang_hint_defaults_to_unknown_when_not_supplied(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_returning(monkeypatch, _draft())
        _summarize(settings)
        assert "unknown" in captured["user"]  # type: ignore[operator]

    def test_custom_summary_lang_setting_flows_into_the_system_prompt(self, tmp_path) -> None:
        settings = Settings(data_dir=tmp_path / "data", persona_summary_lang="ko")
        with pytest.MonkeyPatch.context() as mp:
            captured = _stub_returning(mp, _draft())
            _summarize(settings)
        assert "in ko" in captured["system"]  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Degraded verdicts pass through -- never raised
# ---------------------------------------------------------------------------


class TestDegradedPassthrough:
    def test_a_failed_grounding_verdict_is_returned_not_raised(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_returning(monkeypatch, _draft(), ok=False, degraded=True)
        result = _summarize(settings)
        assert result.verdict.ok is False
        assert result.verdict.degraded is True
        assert result.draft.summary == "A summary."


# ---------------------------------------------------------------------------
# AgentUnavailable / BudgetExhausted propagate unchanged
# ---------------------------------------------------------------------------


class TestErrorPropagation:
    def test_agent_unavailable_propagates(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raiser(**kwargs: object) -> GroundedResult[summarize.NoteDraft]:
            raise AgentUnavailable("no credential configured")

        monkeypatch.setattr(summarize, "run_grounded", raiser)
        with pytest.raises(AgentUnavailable):
            _summarize(settings)

    def test_budget_exhausted_propagates(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def raiser(**kwargs: object) -> GroundedResult[summarize.NoteDraft]:
            raise BudgetExhausted(Decimal("5.00"), Decimal("5.00"))

        monkeypatch.setattr(summarize, "run_grounded", raiser)
        with pytest.raises(BudgetExhausted):
            _summarize(settings)


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    def test_over_long_input_is_truncated_with_an_explicit_marker(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        long_text = "x" * (summarize.MAX_SOURCE_CHARS + 5_000)
        captured = _stub_returning(monkeypatch, _draft())

        _summarize(settings, text=long_text)

        user = captured["user"]
        pack = captured["pack"]
        assert isinstance(user, str)
        assert "TRUNCATED" in user
        # The tail was cut, not silently dropped without a trace, and the pack's own evidence text
        # (what the grounding check reads) reflects the same truncated text, not the raw original.
        assert "TRUNCATED" in pack.sections[0].text  # type: ignore[union-attr]
        assert len(pack.sections[0].text) < len(long_text)  # type: ignore[union-attr]

    def test_short_input_is_not_truncated(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_returning(monkeypatch, _draft())
        _summarize(settings, text="a short transcript")
        assert "TRUNCATED" not in captured["user"]  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Grounding pack construction -- pure-function tests, no mocking at all
# ---------------------------------------------------------------------------


class TestEvidencePackGrounding:
    def test_a_number_present_in_the_source_is_grounded(self) -> None:
        source = "NVDA closed at 187.45 today, up 12.3% from last week."
        pack = summarize._build_evidence_pack(source)
        verdict = check("The close was 187.45.", pack)
        assert verdict.ok is True

    def test_a_number_absent_from_the_source_is_rejected(self) -> None:
        source = "NVDA closed at 187.45 today, up 12.3% from last week."
        pack = summarize._build_evidence_pack(source)
        verdict = check("The price target is 999.99.", pack)
        assert verdict.ok is False
        assert verdict.issues[0].kind == "ungrounded_number"

    def test_source_text_is_carried_verbatim_for_the_model_to_read(self) -> None:
        source = "Some source text with a number 42.5 in it."
        pack = summarize._build_evidence_pack(source)
        assert pack.sections[0].text == source
