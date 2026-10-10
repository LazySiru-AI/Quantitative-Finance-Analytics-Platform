"""Unit tests for `app.manager.chat`.

No test here makes a real model call: `chat.run_grounded` is monkeypatched to a fake that returns a
caller-supplied `_AnswerDraft` wrapped in a `GroundedResult`, the same pattern
`tests/test_personas_chat.py` uses for `app.personas.chat.run_grounded`. `collect`/`snapshots.latest`/
`rules.diff` are never called -- every `ManagerSnapshot`/`ChangeSet` is hand-built here, since `collect`
reaches real application services and is network-slow.

What is asserted: `ManagerChatStore`'s on-disk round trip (save/load/list/delete, newest-first, an
unreadable file skipped rather than raised, atomic write); `chat_turn`'s own logic -- a turn is appended
with a `ManagerChatTurn` and a cost; history is capped at `MAX_HISTORY_TURNS` and a degraded prior
answer is excluded from the evidence pack while still appearing in the visible prompt history; focus
retrieval narrows the pack to the areas a question names; citations outside this turn's source-ref
catalog are dropped, never repaired; a degraded grounded result yields `degraded=True` without raising;
and the output schema structurally carries no advice/instruction field.
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
from app.manager import chat
from app.manager.models import (
    ChangeItem,
    ChangeSet,
    ManagerChatThread,
    ManagerChatTurn,
    ManagerSnapshot,
    SectionItem,
    SnapshotSection,
    SourceRef,
)

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
    draft: chat._AnswerDraft, *, budget: AgentBudget, ok: bool = True, degraded: bool = False,
) -> GroundedResult[chat._AnswerDraft]:
    verdict = GroundingVerdict(ok=ok, degraded=degraded, attempts=1)
    new_budget = AgentBudget(
        cap_usd=budget.cap_usd, spent_usd=budget.spent_usd + Decimal("0.01"), calls=budget.calls + 1,
    )
    return GroundedResult(value=draft, verdict=verdict, calls=(_fake_call(),), budget=new_budget)


def _draft(**overrides: object) -> chat._AnswerDraft:
    fields: dict[str, object] = dict(answer="Here is the situation.", citations=())
    fields.update(overrides)
    return chat._AnswerDraft(**fields)  # type: ignore[arg-type]


def _stub_run_grounded(
    monkeypatch: pytest.MonkeyPatch, draft: chat._AnswerDraft, *, ok: bool = True, degraded: bool = False,
) -> dict[str, object]:
    """Patch `chat.run_grounded` to hand back `draft` (wrapped), and capture every kwarg the call site
    passed -- `captured["system"]`, `captured["user"]`, `captured["pack"]`, etc."""
    captured: dict[str, object] = {}

    def fake_run_grounded(**kwargs: object) -> GroundedResult[chat._AnswerDraft]:
        captured.update(kwargs)
        return _grounded_result(draft, budget=kwargs["budget"], ok=ok, degraded=degraded)  # type: ignore[arg-type]

    monkeypatch.setattr(chat, "run_grounded", fake_run_grounded)
    return captured


def _ref(kind: str, id_: str, label: str = "") -> SourceRef:
    return SourceRef(kind=kind, id=id_, label=label or id_)  # type: ignore[arg-type]


def _tax_section() -> SnapshotSection:
    return SnapshotSection(
        key="tax",
        ok=True,
        as_of="2026-09-08",
        text="Realized gains are tracked for wash-sale exposure.",
        figures={"ytd_net_gain": "1234.56"},
        items=(
            SectionItem(
                id="wash-nvda",
                label="NVDA wash window",
                figures={"days_until_safe": "3"},
                observed_at="2026-09-08",
                refs=(_ref("symbol", "NVDA", "NVDA"),),
                text="NVDA has an open wash-sale window closing in 3 days.",
            ),
        ),
    )


def _market_section() -> SnapshotSection:
    return SnapshotSection(
        key="market",
        ok=True,
        as_of="2026-09-08",
        text="Broad market levels as of yesterday's close.",
        figures={"value": "5600.12", "fear_greed": "55"},
        items=(
            SectionItem(
                id="spx",
                label="S&P 500",
                figures={"value": "5600.12"},
                observed_at="2026-09-08",
                refs=(_ref("snapshot", "market.spx", "S&P 500 snapshot"),),
                text="S&P 500 closed at 5600.12.",
            ),
        ),
    )


def _snapshot(*, sections: tuple[SnapshotSection, ...] | None = None) -> ManagerSnapshot:
    return ManagerSnapshot(
        scope="owner",
        as_of="2026-09-08",
        generated_at="2026-09-08T09:45:00+00:00",
        sections=sections if sections is not None else (_tax_section(), _market_section()),
    )


def _changes() -> ChangeSet:
    return ChangeSet(
        window="yesterday",
        since="2026-09-07",
        until="2026-09-08",
        scope="owner",
        items=(
            ChangeItem(
                id="wash-nvda-closing",
                area="tax",
                rule="wash_window_closing",
                severity="notable",
                headline="NVDA wash-sale window closes in 3 days.",
                detail="Selling NVDA at a loss again would re-open the window.",
                as_of="2026-09-08",
                figures={"days_until_safe": "3"},
                source_refs=(_ref("txn", "t-nvda-1", "NVDA sale"),),
            ),
        ),
    )


def _turn(turn_id: str, *, answer: str = "An earlier answer.", degraded: bool = False) -> ManagerChatTurn:
    return ManagerChatTurn(
        turn_id=turn_id,
        asked_at="2026-09-01T00:00:00+00:00",
        question=f"question {turn_id}?",
        answer=answer,
        source_refs=(),
        commissions=(),
        refreshed=False,
        grounding=GroundingVerdict(ok=not degraded, degraded=degraded),
        degraded=degraded,
        cost_usd="0.01",
    )


def _thread(*, turns: tuple[ManagerChatTurn, ...] = ()) -> ManagerChatThread:
    return ManagerChatThread(
        thread_id="t1", title="", created_at="2026-09-01T00:00:00+00:00",
        updated_at="2026-09-01T00:00:00+00:00", turn_count=len(turns), spent_usd="0", turns=turns,
    )


def _chat_turn(
    settings: Settings, *, thread: ManagerChatThread | None = None, question: str = "What's new?",
    snapshot: ManagerSnapshot | None = None, changes: ChangeSet | None = None,
    budget: AgentBudget | None = None,
) -> chat.ChatTurnResult:
    return chat.chat_turn(
        thread=thread if thread is not None else _thread(),
        question=question,
        snapshot=snapshot if snapshot is not None else _snapshot(),
        changes=changes if changes is not None else _changes(),
        settings=settings,
        budget=budget if budget is not None else _budget(),
    )


# ---------------------------------------------------------------------------
# ManagerChatStore
# ---------------------------------------------------------------------------


class TestManagerChatStore:
    def test_round_trip_save_and_load(self, settings: Settings) -> None:
        store = chat.ManagerChatStore(settings)
        thread = _thread(turns=(_turn("t-a"),))
        store.save_thread(thread)

        loaded = store.load_thread("t1")
        assert loaded is not None
        assert loaded.thread_id == "t1"
        assert loaded.turns == (_turn("t-a"),)

    def test_load_missing_thread_is_none(self, settings: Settings) -> None:
        store = chat.ManagerChatStore(settings)
        assert store.load_thread("nope") is None

    def test_list_threads_strips_turns_and_orders_newest_first(self, settings: Settings) -> None:
        store = chat.ManagerChatStore(settings)
        older = ManagerChatThread(
            thread_id="older", title="", turns=(_turn("a"),),
            created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
        )
        newer = ManagerChatThread(
            thread_id="newer", title="", turns=(_turn("b"),),
            created_at="2026-02-01T00:00:00+00:00", updated_at="2026-02-01T00:00:00+00:00",
        )
        store.save_thread(older)
        store.save_thread(newer)

        listed = store.list_threads()
        assert [t.thread_id for t in listed] == ["newer", "older"]
        assert all(t.turns == () for t in listed)

    def test_delete_thread_returns_whether_it_existed(self, settings: Settings) -> None:
        store = chat.ManagerChatStore(settings)
        assert store.delete_thread("nope") is False

        store.save_thread(_thread())
        assert store.delete_thread("t1") is True
        assert store.load_thread("t1") is None

    def test_unreadable_file_is_skipped_not_raised(
        self, settings: Settings, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from app.manager.models import chats_dir

        store = chat.ManagerChatStore(settings)
        store.save_thread(_thread())

        directory = chats_dir(settings)
        (directory / "corrupt.json").write_text("{not valid json", encoding="utf-8")

        with caplog.at_level("WARNING", logger="app.manager.chat"):
            listed = store.list_threads()
        assert [t.thread_id for t in listed] == ["t1"]
        assert "corrupt" in caplog.text.lower() or "unreadable" in caplog.text.lower()

    def test_save_is_atomic_no_stray_temp_files_left(self, settings: Settings) -> None:
        from app.manager.models import chats_dir

        store = chat.ManagerChatStore(settings)
        store.save_thread(_thread())
        names = [p.name for p in chats_dir(settings).iterdir()]
        assert names == ["t1.json"]

    def test_thread_json_round_trips_via_pydantic(self, settings: Settings) -> None:
        from app.manager.models import chats_dir

        store = chat.ManagerChatStore(settings)
        thread = _thread(turns=(_turn("a"), _turn("b", degraded=True)))
        store.save_thread(thread)

        raw = json.loads((chats_dir(settings) / "t1.json").read_text())
        assert raw["thread_id"] == "t1"
        assert len(raw["turns"]) == 2


# ---------------------------------------------------------------------------
# chat_turn -- basics
# ---------------------------------------------------------------------------


class TestChatTurnBasics:
    def test_turn_is_appended_with_cost(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_run_grounded(monkeypatch, _draft())

        result = _chat_turn(settings, budget=_budget(spent="1.00"))

        assert isinstance(result.turn, ManagerChatTurn)
        assert result.turn.answer == "Here is the situation."
        assert result.turn.cost_usd == "1.01"  # `_grounded_result` adds $0.01 on top
        assert result.turn.turn_id
        assert result.turn.refreshed is False

    def test_citations_outside_the_pack_are_dropped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_run_grounded(monkeypatch, _draft(citations=("symbol:NVDA", "run:ghost-invented")))

        result = _chat_turn(settings)

        kept_keys = {f"{r.kind}:{r.id}" for r in result.turn.source_refs}
        assert kept_keys == {"symbol:NVDA"}

    def test_valid_citation_resolves_to_the_real_source_ref(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_run_grounded(monkeypatch, _draft(citations=("txn:t-nvda-1",)))

        result = _chat_turn(settings)

        assert len(result.turn.source_refs) == 1
        assert result.turn.source_refs[0].kind == "txn"
        assert result.turn.source_refs[0].id == "t-nvda-1"

    def test_degraded_verdict_passes_through_unraised(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _stub_run_grounded(monkeypatch, _draft(), ok=False, degraded=True)

        result = _chat_turn(settings)

        assert result.turn.grounding.ok is False
        assert result.turn.degraded is True
        assert result.turn.answer == "Here is the situation."

    def test_answer_schema_has_no_instruction_field(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Structural half of the no-advice guarantee: the output model the manager fills in has only
        `answer` and `citations` -- there is nowhere for a stance, an action, or a recommendation to
        land, regardless of what a "should I sell NVDA?" question tempts the model to write."""
        assert set(chat._AnswerDraft.model_fields) == {"answer", "citations"}

        _stub_run_grounded(monkeypatch, _draft(answer="NVDA's wash window closes in 3 days."))
        result = _chat_turn(settings, question="Should I sell NVDA right now?")

        assert result.turn.answer == "NVDA's wash window closes in 3 days."
        assert not hasattr(result.turn, "stance")
        assert not hasattr(result.turn, "action")
        assert not hasattr(result.turn, "recommendation")


# ---------------------------------------------------------------------------
# Focus retrieval
# ---------------------------------------------------------------------------


class TestFocusRetrieval:
    def test_area_name_in_the_question_narrows_to_that_area(self) -> None:
        snapshot = _snapshot()
        focus = chat._focus_areas("What's going on with tax right now?", snapshot)
        assert focus == ("tax",)

    def test_a_term_in_a_sections_own_text_narrows_to_that_area(self) -> None:
        snapshot = _snapshot()
        focus = chat._focus_areas("Anything notable about NVDA?", snapshot)
        assert focus == ("tax",)

    def test_no_match_returns_none_for_whole_snapshot(self) -> None:
        snapshot = _snapshot()
        focus = chat._focus_areas("How are things overall?", snapshot)
        assert focus is None

    def test_chat_turn_narrows_the_pack_to_the_matched_section(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_run_grounded(monkeypatch, _draft())

        _chat_turn(settings, question="What's going on with tax right now?")

        pack = captured["pack"]
        titles = [s.title for s in pack.sections]  # type: ignore[union-attr]
        assert "State: tax" in titles
        assert "State: market" not in titles

    def test_chat_turn_keeps_whole_snapshot_when_nothing_matches(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_run_grounded(monkeypatch, _draft())

        _chat_turn(settings, question="How are things overall?")

        pack = captured["pack"]
        titles = [s.title for s in pack.sections]  # type: ignore[union-attr]
        assert "State: tax" in titles
        assert "State: market" in titles


# ---------------------------------------------------------------------------
# History assembly -- the degraded-answer guardrail
# ---------------------------------------------------------------------------


class TestHistoryAssembly:
    def test_history_is_capped_at_max_history_turns(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_run_grounded(monkeypatch, _draft())

        many_turns = tuple(_turn(f"turn-{i:02d}") for i in range(chat.MAX_HISTORY_TURNS + 5))
        thread = _thread(turns=many_turns)

        _chat_turn(settings, thread=thread)

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
        captured = _stub_run_grounded(monkeypatch, _draft())

        degraded_turn = _turn("d1", answer="Ungrounded figure: 424242.", degraded=True)
        good_turn = _turn("g1", answer="Grounded figure: 909090.", degraded=False)
        thread = _thread(turns=(degraded_turn, good_turn))

        _chat_turn(settings, thread=thread)

        pack = captured["pack"]
        history_sections = [s for s in pack.sections if s.title == "Earlier in this thread"]  # type: ignore[union-attr]
        assert len(history_sections) == 1
        history_text = history_sections[0].text
        assert "424242" not in history_text
        assert "909090" in history_text

    def test_a_degraded_prior_answer_still_appears_in_the_visible_history_block(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_run_grounded(monkeypatch, _draft())

        degraded_turn = _turn("d1", answer="Ungrounded figure: 424242.", degraded=True)
        thread = _thread(turns=(degraded_turn,))

        _chat_turn(settings, thread=thread)

        user = captured["user"]
        assert isinstance(user, str)
        assert "424242" in user

    def test_no_history_section_when_every_prior_turn_is_degraded(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_run_grounded(monkeypatch, _draft())

        thread = _thread(turns=(_turn("d1", degraded=True),))
        _chat_turn(settings, thread=thread)

        pack = captured["pack"]
        titles = [s.title for s in pack.sections]  # type: ignore[union-attr]
        assert "Earlier in this thread" not in titles

    def test_no_history_section_for_a_fresh_thread(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured = _stub_run_grounded(monkeypatch, _draft())

        _chat_turn(settings, thread=_thread(turns=()))

        pack = captured["pack"]
        titles = [s.title for s in pack.sections]  # type: ignore[union-attr]
        assert "Earlier in this thread" not in titles
