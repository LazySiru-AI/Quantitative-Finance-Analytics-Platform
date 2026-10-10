"""Unit tests for `app.personas.chat`.

No test here makes a real model call: `chat.run_grounded` is monkeypatched to a fake that returns a
caller-supplied `_AnswerDraft` wrapped in a `GroundedResult`, exactly the pattern
`tests/test_personas_ask.py` uses for `app.personas.ask.run_grounded`. `chat.select_notes` is
monkeypatched to a fixed return value per the worker brief -- these tests do not exercise
`app.personas.retrieval`'s own ranking quality, only that `chat_turn` calls it and uses what comes
back.

What is asserted: `ChatStore`'s on-disk round trip (save/load/list/delete, newest-first, an
unreadable file skipped rather than raised), and `chat_turn`'s own logic -- citations are always a
subset of the notes retrieved this turn, stance is `None` without a `symbol`, a degraded verdict
passes through unraised, history is capped at `MAX_HISTORY_TURNS`, and -- the guardrail the contract
names explicitly -- a degraded prior turn's answer text never reaches the evidence pack `run_grounded`
is handed, while a non-degraded one does.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import pytest

from app.agentdesk.grounding import GroundedResult
from app.agentdesk.models import GroundingVerdict
from app.agents.models import AgentBudget, AgentCall
from app.config import Settings
from app.personas import ask, chat
from app.personas.models import ChatThread, ChatTurn, EpisodicNote, PersonaProfile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _budget(cap: str = "2.00", spent: str = "0") -> AgentBudget:
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


def _stub_run_grounded(
    monkeypatch: pytest.MonkeyPatch, draft: ask._AnswerDraft, *, ok: bool = True, degraded: bool = False,
) -> dict[str, object]:
    """Patch `chat.run_grounded` to hand back `draft` (wrapped), and capture every kwarg the call
    site passed -- `captured["system"]`, `captured["user"]`, `captured["pack"]`, etc. -- the same
    pattern `tests/test_personas_ask.py`'s `_stub_returning` uses for `ask.run_grounded`."""
    captured: dict[str, object] = {}

    def fake_run_grounded(**kwargs: object) -> GroundedResult[ask._AnswerDraft]:
        captured.update(kwargs)
        return _grounded_result(draft, budget=kwargs["budget"], ok=ok, degraded=degraded)  # type: ignore[arg-type]

    monkeypatch.setattr(chat, "run_grounded", fake_run_grounded)
    return captured


def _stub_select_notes(monkeypatch: pytest.MonkeyPatch, notes: tuple[EpisodicNote, ...]) -> None:
    """Patch `chat.select_notes` to a fixed return, so a unit test of `chat_turn` never depends on
    `app.personas.retrieval`'s own ranking quality -- another worker owns that module."""

    def fake_select_notes(
        candidates: object, question: str, *, symbol: str | None, profile: object,
        cap: int = 16, char_budget: int = 40_000,
    ) -> tuple[EpisodicNote, ...]:
        return notes

    monkeypatch.setattr(chat, "select_notes", fake_select_notes)


def _note(note_id: str, *, persona: str = "creator-a", summary: str = "A summary.") -> EpisodicNote:
    return EpisodicNote(
        note_id=note_id,
        persona=persona,
        source_id="yt:UC1",
        published=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        ingested_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        url=f"https://example.com/{note_id}",
        title="A video",
        kind="video_transcript",
        transcript_source="auto",
        lang="en",
        summary=summary,
        themes=("theme one",),
        quotes=(),
        mentions=(),
        path=f"notes/{note_id}.md",
        degraded=False,
    )


def _profile(**overrides: object) -> PersonaProfile:
    fields: dict[str, object] = dict(
        persona="creator-a", version=1, consolidated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        note_count=3, summary="Trades momentum names.", beliefs=(), playbook=(), vocabulary=(),
        path="profile.md",
    )
    fields.update(overrides)
    return PersonaProfile(**fields)  # type: ignore[arg-type]


def _turn(turn_id: str, *, answer: str = "An earlier answer.", degraded: bool = False) -> ChatTurn:
    return ChatTurn(
        turn_id=turn_id,
        asked_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        question=f"question {turn_id}?",
        symbol=None,
        lang="en",
        answer=answer,
        citations=(),
        retrieved=(),
        stance=None,
        grounding=GroundingVerdict(ok=not degraded, degraded=degraded),
        degraded=degraded,
        cost_usd="0.01",
    )


def _thread(*, turns: tuple[ChatTurn, ...] = (), persona: str = "creator-a") -> ChatThread:
    return ChatThread(
        thread_id="t1", persona=persona, title="", created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        updated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC), turn_count=len(turns),
        spent_usd="0", turns=turns,
    )


def _chat_turn(
    settings: Settings, *, thread: ChatThread | None = None, symbol: str | None = None,
    lang: str = "en", notes: tuple[EpisodicNote, ...] = (), profile: PersonaProfile | None = None,
    budget: AgentBudget | None = None,
) -> chat.ChatTurnResult:
    return chat.chat_turn(
        persona_slug="creator-a",
        thread=thread if thread is not None else _thread(),
        question="What do you think of NVDA?",
        symbol=symbol,
        lang=lang,
        profile=profile,
        notes=notes,
        settings=settings,
        budget=budget if budget is not None else _budget(),
    )


# ---------------------------------------------------------------------------
# ChatStore
# ---------------------------------------------------------------------------


class TestChatStore:
    def test_round_trip_save_and_load(self, settings: Settings) -> None:
        store = chat.ChatStore(settings)
        thread = _thread(turns=(_turn("t-a"),))
        store.save_thread(thread)

        loaded = store.load_thread("creator-a", "t1")
        assert loaded is not None
        assert loaded.thread_id == "t1"
        assert loaded.turns == (_turn("t-a"),)

    def test_load_missing_thread_is_none(self, settings: Settings) -> None:
        store = chat.ChatStore(settings)
        assert store.load_thread("creator-a", "nope") is None

    def test_list_threads_strips_turns_and_orders_newest_first(self, settings: Settings) -> None:
        store = chat.ChatStore(settings)
        older = ChatThread(
            thread_id="older", persona="creator-a", title="", turns=(_turn("a"),),
            created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            updated_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        )
        newer = ChatThread(
            thread_id="newer", persona="creator-a", title="", turns=(_turn("b"),),
            created_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
            updated_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
        )
        store.save_thread(older)
        store.save_thread(newer)

        listed = store.list_threads("creator-a")
        assert [t.thread_id for t in listed] == ["newer", "older"]
        assert all(t.turns == () for t in listed)

    def test_delete_thread_returns_whether_it_existed(self, settings: Settings) -> None:
        store = chat.ChatStore(settings)
        assert store.delete_thread("creator-a", "nope") is False

        store.save_thread(_thread())
        assert store.delete_thread("creator-a", "t1") is True
        assert store.load_thread("creator-a", "t1") is None

    def test_unreadable_file_is_skipped_not_raised(
        self, settings: Settings, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from app.personas.models import persona_dir

        store = chat.ChatStore(settings)
        store.save_thread(_thread())

        chats_dir = persona_dir(settings, "creator-a") / "chats"
        (chats_dir / "corrupt.json").write_text("{not valid json", encoding="utf-8")

        with caplog.at_level("WARNING", logger="app.personas.chat"):
            listed = store.list_threads("creator-a")
        assert [t.thread_id for t in listed] == ["t1"]
        assert "corrupt" in caplog.text.lower() or "unreadable" in caplog.text.lower()

    def test_save_is_atomic_no_stray_temp_files_left(self, settings: Settings) -> None:
        from app.personas.models import persona_dir

        store = chat.ChatStore(settings)
        store.save_thread(_thread())
        chats_dir = persona_dir(settings, "creator-a") / "chats"
        names = [p.name for p in chats_dir.iterdir()]
        assert names == ["t1.json"]

    def test_thread_json_round_trips_via_pydantic(self, settings: Settings) -> None:
        store = chat.ChatStore(settings)
        thread = _thread(turns=(_turn("a"), _turn("b", degraded=True)))
        store.save_thread(thread)

        from app.personas.models import persona_dir

        raw = json.loads((persona_dir(settings, "creator-a") / "chats" / "t1.json").read_text())
        assert raw["thread_id"] == "t1"
        assert len(raw["turns"]) == 2


# ---------------------------------------------------------------------------
# chat_turn -- citations, stance, degraded passthrough
# ---------------------------------------------------------------------------


class TestChatTurnBasics:
    def test_citations_are_a_subset_of_retrieved(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"), _note("n2"))
        _stub_select_notes(monkeypatch, notes)
        _stub_run_grounded(monkeypatch, _draft(citations=("n1", "ghost")))

        result = _chat_turn(settings, notes=notes)

        assert set(result.turn.citations) <= set(result.turn.retrieved)
        assert result.turn.retrieved == ("n1", "n2")
        assert result.turn.citations == ("n1",)  # the hallucinated one is dropped

    def test_stance_is_none_without_a_symbol(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        _stub_select_notes(monkeypatch, notes)
        _stub_run_grounded(monkeypatch, _draft(stance="bullish"))

        result = _chat_turn(settings, notes=notes, symbol=None)

        assert result.turn.stance is None

    def test_stance_is_filled_when_a_symbol_is_asked(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        _stub_select_notes(monkeypatch, notes)
        _stub_run_grounded(monkeypatch, _draft(stance="bullish"))

        result = _chat_turn(settings, notes=notes, symbol="NVDA")

        assert result.turn.stance == "bullish"
        assert result.turn.symbol == "NVDA"

    def test_degraded_verdict_passes_through_unraised(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        _stub_select_notes(monkeypatch, notes)
        _stub_run_grounded(monkeypatch, _draft(), ok=False, degraded=True)

        result = _chat_turn(settings, notes=notes)

        assert result.turn.grounding.ok is False
        assert result.turn.degraded is True
        assert result.turn.answer == "This is what they'd say."

    def test_turn_id_and_asked_at_are_freshly_minted(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        _stub_select_notes(monkeypatch, notes)
        _stub_run_grounded(monkeypatch, _draft())

        result = _chat_turn(settings, notes=notes)

        assert result.turn.turn_id
        assert result.turn.asked_at.tzinfo is not None

    def test_cost_usd_reflects_the_budget_run_grounded_returns(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        _stub_select_notes(monkeypatch, notes)
        _stub_run_grounded(monkeypatch, _draft())

        result = _chat_turn(settings, notes=notes, budget=_budget(spent="1.00"))

        assert result.turn.cost_usd == "1.01"  # `_grounded_result` adds $0.01 on top


# ---------------------------------------------------------------------------
# History assembly -- the degraded-answer guardrail
# ---------------------------------------------------------------------------


class TestHistoryAssembly:
    def test_history_is_capped_at_max_history_turns(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        _stub_select_notes(monkeypatch, notes)
        captured = _stub_run_grounded(monkeypatch, _draft())

        many_turns = tuple(_turn(f"turn-{i:02d}") for i in range(chat.MAX_HISTORY_TURNS + 5))
        thread = _thread(turns=many_turns)

        _chat_turn(settings, notes=notes, thread=thread)

        user = captured["user"]
        assert isinstance(user, str)
        included = sum(1 for t in many_turns if f"question {t.turn_id}?" in user)
        assert included == chat.MAX_HISTORY_TURNS
        # And it is the *most recent* ones kept, not the oldest.
        assert f"question {many_turns[-1].turn_id}?" in user
        assert f"question {many_turns[0].turn_id}?" not in user

    def test_a_degraded_prior_answer_is_excluded_from_the_evidence_pack(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        _stub_select_notes(monkeypatch, notes)
        captured = _stub_run_grounded(monkeypatch, _draft())

        degraded_turn = _turn("d1", answer="Ungrounded figure: 424242.", degraded=True)
        good_turn = _turn("g1", answer="Grounded figure: 909090.", degraded=False)
        thread = _thread(turns=(degraded_turn, good_turn))

        _chat_turn(settings, notes=notes, thread=thread)

        pack = captured["pack"]
        history_sections = [s for s in pack.sections if s.title == "Earlier answers in this thread"]  # type: ignore[union-attr]
        assert len(history_sections) == 1
        history_text = history_sections[0].text
        assert "424242" not in history_text
        assert "909090" in history_text

    def test_a_degraded_prior_answer_still_appears_in_the_visible_history_block(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The evidence pack excludes a degraded answer's text (previous test); the *user prompt's*
        history block does not -- the model still needs to know what it actually said, in order, to
        hold a coherent conversation. See `chat._render_history_block`'s own docstring."""
        notes = (_note("n1"),)
        _stub_select_notes(monkeypatch, notes)
        captured = _stub_run_grounded(monkeypatch, _draft())

        degraded_turn = _turn("d1", answer="Ungrounded figure: 424242.", degraded=True)
        thread = _thread(turns=(degraded_turn,))

        _chat_turn(settings, notes=notes, thread=thread)

        user = captured["user"]
        assert isinstance(user, str)
        assert "424242" in user

    def test_no_history_section_when_every_prior_turn_is_degraded(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        _stub_select_notes(monkeypatch, notes)
        captured = _stub_run_grounded(monkeypatch, _draft())

        thread = _thread(turns=(_turn("d1", degraded=True),))
        _chat_turn(settings, notes=notes, thread=thread)

        pack = captured["pack"]
        titles = [s.title for s in pack.sections]  # type: ignore[union-attr]
        assert "Earlier answers in this thread" not in titles

    def test_no_history_section_for_a_fresh_thread(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        notes = (_note("n1"),)
        _stub_select_notes(monkeypatch, notes)
        captured = _stub_run_grounded(monkeypatch, _draft())

        _chat_turn(settings, notes=notes, thread=_thread(turns=()))

        pack = captured["pack"]
        titles = [s.title for s in pack.sections]  # type: ignore[union-attr]
        assert "Earlier answers in this thread" not in titles
