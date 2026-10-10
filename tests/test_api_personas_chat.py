"""Integration tests for the persona chat HTTP surface (Phase 9).

**Nothing here makes a real model call.** `app.personas.chat.chat_turn` is monkeypatched to a fake
that returns a fixed `ChatTurn`, the same pattern `tests/test_api_personas.py`'s `fake_ask` fixture
uses for `app.personas.ask.ask_persona` -- `app.personas.service.chat_turn` imports
`app.personas.chat.chat_turn` from the module at call time, so patching the module attribute is
enough.

Route *registration* is checked via ``app.openapi()["paths"]`` rather than ``app.routes``: FastAPI
0.141 does not list these routes on the latter (see `tests/test_api_personas.py`'s own module
docstring, which documents the same false negative).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.agentdesk.models import GroundingVerdict
from app.config import Settings
from app.personas.models import ChatThread, EpisodicNote, TickerMention
from app.personas.sources.base import ResolvedChannel, SourceNotFound
from app.personas.store import VaultStore

NOW = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Client whose vault and stores are redirected into the test's tmp dir by the `settings`
    fixture, so reads and writes hit an empty temporary vault, never the developer's real one --
    mirrors `tests/test_api_personas.py`'s own `client` fixture."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fake_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve any handle offline. Copied from `tests/test_api_personas.py`'s own fixture of the same
    name -- that file is owned by another worker and must not be imported from or edited."""
    from app.personas.sources import youtube

    def _resolve(handle: str, *, client: object | None = None) -> ResolvedChannel:
        clean = handle.strip().lstrip("@")
        if clean == "nosuch":
            raise SourceNotFound("no such channel", provider="youtube")
        channel_id = "UCaaaaaaaaaaaaaaaaaaaaaa" if clean == "creator-a" else "UCtest0000000000000000"
        return ResolvedChannel(
            channel_id=channel_id, display_name=clean, handle=clean,
            url=f"https://www.youtube.com/@{clean}",
        )

    monkeypatch.setattr(youtube, "resolve_handle", _resolve)


@pytest.fixture
def fake_chat_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the chat model call. `service.chat_turn` imports `chat_turn` from
    `app.personas.chat` at call time, so patching the module attribute suffices -- the same pattern
    `tests/test_api_personas.py`'s `fake_ask` fixture uses one level up."""
    from app.personas import chat as chat_module
    from app.personas.models import ChatTurn

    def _fake(
        *, persona_slug: str, thread: ChatThread, question: str, symbol: str | None, lang: str,
        profile: object, notes: object, settings: Settings, budget: object, model: str = "",
    ) -> chat_module.ChatTurnResult:
        retrieved = tuple(n.note_id for n in notes)  # type: ignore[union-attr]
        cited = retrieved[:1]
        symbol_norm = symbol.strip().upper() if symbol else None
        turn = ChatTurn(
            turn_id=f"turn-{len(thread.turns)}",
            asked_at=dt.datetime.now(dt.UTC),
            question=question,
            symbol=symbol_norm,
            lang=lang if lang in ("en", "ko") else "en",
            answer=f"In response to: {question}",
            citations=cited,
            retrieved=retrieved,
            stance="bullish" if symbol_norm else None,
            grounding=GroundingVerdict(ok=True),
            degraded=False,
            cost_usd="0.05",
        )
        return chat_module.ChatTurnResult(turn=turn, calls=())

    monkeypatch.setattr(chat_module, "chat_turn", _fake)


def _note(persona: str, note_id: str, **over: object) -> EpisodicNote:
    base: dict[str, object] = {
        "note_id": note_id,
        "persona": persona,
        "source_id": "yt:UCaaaaaaaaaaaaaaaaaaaaaa",
        "published": NOW,
        "ingested_at": NOW,
        "url": f"https://www.youtube.com/watch?v={note_id}",
        "title": f"video {note_id}",
        "kind": "video_transcript",
        "transcript_source": "auto",
        "lang": "en",
        "summary": "First sentence. Second sentence.",
        "themes": ("semis",),
        "quotes": ("quote",),
        "mentions": (),
        "path": "",
    }
    base.update(over)
    return EpisodicNote.model_validate(base)


def _seed_persona_with_note(client: TestClient, settings: Settings, slug: str = "creator-a") -> None:
    client.post("/api/personas", json={"handle": f"@{slug}"})
    VaultStore(settings).write_note(
        _note(slug, "note1", mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="x"),)),
        transcript_text="t",
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_chat_routes_are_registered() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    for path in (
        "/api/personas/{slug}/chats",
        "/api/personas/{slug}/chats/{thread_id}",
        "/api/personas/{slug}/chats/{thread_id}/turns",
        "/api/personas/{slug}/chat-context",
    ):
        assert path in paths, f"{path} is not registered"


# ---------------------------------------------------------------------------
# Lifecycle: create -> list -> get -> turn -> delete
# ---------------------------------------------------------------------------


def test_create_list_get_turn_delete_lifecycle(
    client: TestClient, settings: Settings, fake_resolve: None, fake_chat_turn: None,
) -> None:
    _seed_persona_with_note(client, settings)

    created = client.post("/api/personas/creator-a/chats")
    assert created.status_code == 201, created.text
    thread = created.json()
    thread_id = thread["thread_id"]
    assert thread["persona"] == "creator-a"
    assert thread["title"] == ""
    assert thread["turns"] == []
    assert thread["turn_count"] == 0
    assert thread["spent_usd"] == "0"

    listed = client.get("/api/personas/creator-a/chats").json()
    assert [t["thread_id"] for t in listed] == [thread_id]
    assert listed[0]["turns"] == []

    turn_resp = client.post(
        f"/api/personas/creator-a/chats/{thread_id}/turns",
        json={"question": "What do you think of NVDA?", "symbol": "nvda"},
    )
    assert turn_resp.status_code == 200, turn_resp.text
    turn = turn_resp.json()
    assert turn["symbol"] == "NVDA"
    assert turn["stance"] == "bullish"
    assert set(turn["citations"]) <= set(turn["retrieved"])
    assert turn["cost_usd"] == "0.05"

    got = client.get(f"/api/personas/creator-a/chats/{thread_id}").json()
    assert got["turn_count"] == 1
    assert len(got["turns"]) == 1
    assert got["title"] == "What do you think of NVDA?"  # filled from the first question
    assert got["spent_usd"] == "0.05"

    deleted = client.delete(f"/api/personas/creator-a/chats/{thread_id}")
    assert deleted.status_code == 204

    assert client.get(f"/api/personas/creator-a/chats/{thread_id}").status_code == 404
    assert client.get("/api/personas/creator-a/chats").json() == []


def test_second_turn_appends_and_accumulates_spend(
    client: TestClient, settings: Settings, fake_resolve: None, fake_chat_turn: None,
) -> None:
    _seed_persona_with_note(client, settings)
    thread_id = client.post("/api/personas/creator-a/chats").json()["thread_id"]

    client.post(
        f"/api/personas/creator-a/chats/{thread_id}/turns", json={"question": "First question?"},
    )
    second = client.post(
        f"/api/personas/creator-a/chats/{thread_id}/turns", json={"question": "Second question?"},
    )
    assert second.status_code == 200, second.text

    thread = client.get(f"/api/personas/creator-a/chats/{thread_id}").json()
    assert thread["turn_count"] == 2
    assert thread["spent_usd"] == "0.10"
    assert thread["title"] == "First question?"  # title only ever set from the FIRST question


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_unknown_persona_is_404_on_every_chat_route(client: TestClient, fake_chat_turn: None) -> None:
    assert client.get("/api/personas/nobody/chats").status_code == 404
    assert client.post("/api/personas/nobody/chats").status_code == 404
    assert client.get("/api/personas/nobody/chats/whatever").status_code == 404
    assert client.delete("/api/personas/nobody/chats/whatever").status_code == 404
    assert client.get("/api/personas/nobody/chat-context").status_code == 404
    assert client.post(
        "/api/personas/nobody/chats/whatever/turns", json={"question": "hi"},
    ).status_code == 404


def test_unknown_thread_is_404(
    client: TestClient, fake_resolve: None, fake_chat_turn: None,
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    assert client.get("/api/personas/creator-a/chats/nope").status_code == 404
    assert client.delete("/api/personas/creator-a/chats/nope").status_code == 404
    assert client.post(
        "/api/personas/creator-a/chats/nope/turns", json={"question": "hi"},
    ).status_code == 404


def test_turn_with_no_notes_is_409(
    client: TestClient, fake_resolve: None, fake_chat_turn: None,
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})  # no notes ingested
    thread_id = client.post("/api/personas/creator-a/chats").json()["thread_id"]

    resp = client.post(
        f"/api/personas/creator-a/chats/{thread_id}/turns", json={"question": "hi"},
    )
    assert resp.status_code == 409


def test_turn_cap_is_409(
    client: TestClient, settings: Settings, fake_resolve: None, fake_chat_turn: None,
) -> None:
    """`app.personas.chat.MAX_TURNS` is a hard per-thread ceiling, enforced before ever calling the
    model -- a thread already at the cap is seeded directly through `ChatStore` rather than by making
    40 real turn requests."""
    from app.personas.chat import MAX_TURNS, ChatStore
    from app.personas.models import ChatTurn

    _seed_persona_with_note(client, settings)
    thread_id = client.post("/api/personas/creator-a/chats").json()["thread_id"]

    store = ChatStore(settings)
    thread = store.load_thread("creator-a", thread_id)
    assert thread is not None
    padded_turns = tuple(
        ChatTurn(
            turn_id=f"pad-{i}", asked_at=NOW, question=f"q{i}", symbol=None, lang="en",
            answer="a", citations=(), retrieved=(), stance=None,
            grounding=GroundingVerdict(ok=True), degraded=False, cost_usd="0",
        )
        for i in range(MAX_TURNS)
    )
    store.save_thread(thread.model_copy(update={"turns": padded_turns, "turn_count": MAX_TURNS}))

    resp = client.post(
        f"/api/personas/creator-a/chats/{thread_id}/turns", json={"question": "one more?"},
    )
    assert resp.status_code == 409


def test_thread_budget_cap_is_409(
    client: TestClient, settings: Settings, fake_resolve: None, fake_chat_turn: None,
) -> None:
    """A thread whose accumulated `spent_usd` has already reached `persona_chat_cap_usd` is refused
    before the model is ever called, regardless of how many turns it holds."""
    from app.personas.chat import ChatStore

    _seed_persona_with_note(client, settings)
    thread_id = client.post("/api/personas/creator-a/chats").json()["thread_id"]

    store = ChatStore(settings)
    thread = store.load_thread("creator-a", thread_id)
    assert thread is not None
    store.save_thread(thread.model_copy(update={"spent_usd": settings.persona_chat_cap_usd}))

    resp = client.post(
        f"/api/personas/creator-a/chats/{thread_id}/turns", json={"question": "one more?"},
    )
    assert resp.status_code == 409


def test_turn_rejects_empty_question(
    client: TestClient, settings: Settings, fake_resolve: None, fake_chat_turn: None,
) -> None:
    _seed_persona_with_note(client, settings)
    thread_id = client.post("/api/personas/creator-a/chats").json()["thread_id"]
    resp = client.post(
        f"/api/personas/creator-a/chats/{thread_id}/turns", json={"question": ""},
    )
    assert resp.status_code == 422


def test_turn_rejects_unknown_fields(
    client: TestClient, settings: Settings, fake_resolve: None, fake_chat_turn: None,
) -> None:
    _seed_persona_with_note(client, settings)
    thread_id = client.post("/api/personas/creator-a/chats").json()["thread_id"]
    resp = client.post(
        f"/api/personas/creator-a/chats/{thread_id}/turns",
        json={"question": "hi", "not_a_field": True},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Chat context
# ---------------------------------------------------------------------------


def test_chat_context_before_any_consolidation(
    client: TestClient, settings: Settings, fake_resolve: None,
) -> None:
    _seed_persona_with_note(client, settings)
    ctx = client.get("/api/personas/creator-a/chat-context")
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    assert body["profile_version"] == 0
    assert body["profile_note_count"] == 0
    assert body["note_count"] == 1
    assert body["stale"] is True  # never consolidated
