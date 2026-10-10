"""Integration tests for the persona feature's HTTP surface and card assembly.

**Nothing here touches the network.** `add_persona` resolves a handle upstream in production, so every
test that creates a persona monkeypatches `app.personas.sources.youtube.resolve_handle`. A test that
reached YouTube would be slow, flaky, and would fail in CI for reasons that have nothing to do with
this code.

Route *registration* is checked via ``app.openapi()["paths"]`` rather than ``app.routes``: FastAPI
0.141 does not list these routes on the latter, a false negative that has cost this repo real time
before.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.personas.models import EpisodicNote, TickerMention, slugify
from app.personas.sources.base import ResolvedChannel, SourceNotFound
from app.personas.store import VaultStore

NOW = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """Client whose vault and stores are redirected into the test's tmp dir by the `settings`
    fixture, so reads and writes hit an empty temporary vault, never the developer's real one."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fake_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve any handle offline, mimicking a real Korean channel: a non-latin display name and a
    latin channel id. `service._resolve_source` is the code under test in the slug-fallback case."""
    from app.personas.sources import youtube

    def _resolve(handle: str, *, client: object | None = None) -> ResolvedChannel:
        clean = handle.strip().lstrip("@")
        if clean == "nosuch":
            raise SourceNotFound("no such channel", provider="youtube")
        names = {
            "creator-a": ("UCaaaaaaaaaaaaaaaaaaaaaa", "Creator A"),
            "creatorb": ("UCbbbbbbbbbbbbbbbbbbbbbb", "Creator B"),
        }
        channel_id, display = names.get(clean, ("UCtest0000000000000000", clean))
        return ResolvedChannel(
            channel_id=channel_id,
            display_name=display,
            handle=clean,
            url=f"https://www.youtube.com/@{clean}",
        )

    monkeypatch.setattr(youtube, "resolve_handle", _resolve)


@pytest.fixture
def fake_summarize(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the one step that would otherwise call a model.

    `app.personas.service._run_ingest` imports `summarize_item` from the module at call time, so
    patching the module attribute is enough -- there is no bound reference captured at import.
    """
    from decimal import Decimal

    from app.agentdesk.models import GroundingVerdict
    from app.agents.models import AgentBudget
    from app.personas import summarize as summarize_module

    def _fake(**kwargs: object) -> summarize_module.SummaryResult:
        return summarize_module.SummaryResult(
            draft=summarize_module.NoteDraft(
                summary="그는 엔비디아 강세를 전망했다.",
                themes=("반도체",),
                quotes=("엔비디아",),
                mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="AI 수요"),),
            ),
            verdict=GroundingVerdict(ok=True),
            budget=AgentBudget(cap_usd=Decimal("2"), spent_usd=Decimal("0.01"), calls=1),
            calls=(),
        )

    monkeypatch.setattr(summarize_module, "summarize_item", _fake)


def _note(persona: str, note_id: str, *, published: dt.datetime | None, **over: object) -> EpisodicNote:
    base: dict[str, object] = {
        "note_id": note_id,
        "persona": persona,
        "source_id": "yt:UCaaaaaaaaaaaaaaaaaaaaaa",
        "published": published,
        "ingested_at": NOW,
        "url": f"https://www.youtube.com/watch?v={note_id}",
        "title": f"video {note_id}",
        "kind": "video_transcript",
        "transcript_source": "auto",
        "lang": "ko",
        "summary": "첫 문장입니다. 두 번째 문장입니다.",
        "themes": ("반도체 사이클", "금리"),
        "quotes": ("9월 시작입니다",),
        "mentions": (),
        "path": "",
    }
    base.update(over)
    return EpisodicNote.model_validate(base)


# --- registration and empty state -----------------------------------------


def test_persona_routes_are_registered() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    for path in (
        "/api/personas",
        "/api/personas/cards",
        "/api/personas/{slug}",
        "/api/personas/{slug}/notes",
        "/api/personas/{slug}/ingest",
    ):
        assert path in paths, f"{path} is not registered"


def test_empty_vault_reads_are_empty_not_errors(client: TestClient) -> None:
    assert client.get("/api/personas").json() == []
    assert client.get("/api/personas/cards").json() == []


def test_unknown_persona_is_404(client: TestClient) -> None:
    assert client.get("/api/personas/nobody").status_code == 404
    assert client.get("/api/personas/nobody/notes").status_code == 404
    assert client.delete("/api/personas/nobody").status_code == 404


def test_slug_path_rejects_bad_input(client: TestClient) -> None:
    assert client.get("/api/personas/Bad_Slug").status_code == 422


def test_slugify() -> None:
    assert slugify("@creator-a") == "creator-a"
    assert slugify("Bullish Bee 11") == "bullish-bee-11"
    assert slugify("홍길동") == ""  # non-latin collapses; the resolver falls back to the channel id


# --- creating personas -----------------------------------------------------


def test_add_persona_creates_it(client: TestClient, fake_resolve: None) -> None:
    created = client.post("/api/personas", json={"handle": "@creator-a"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["slug"] == "creator-a"
    assert body["display_name"] == "Creator A"
    assert body["note_count"] == 0
    assert body["sources"][0]["source_id"] == "yt:UCaaaaaaaaaaaaaaaaaaaaaa"

    assert [p["slug"] for p in client.get("/api/personas").json()] == ["creator-a"]
    assert client.get("/api/personas/creator-a").status_code == 200


def test_a_persona_with_no_notes_gets_an_empty_card_not_an_error(
    client: TestClient, fake_resolve: None
) -> None:
    """The state right after adding a persona. It must render, not error and not spin."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    cards = client.get("/api/personas/cards").json()
    assert len(cards) == 1
    card = cards[0]
    assert card["note_count"] == 0
    assert card["headline"] == ""
    assert card["latest_note"] is None
    assert card["as_of"] is None
    assert card["grounding"]["degraded"] is False


def test_adding_the_same_persona_twice_is_409(client: TestClient, fake_resolve: None) -> None:
    assert client.post("/api/personas", json={"handle": "@creator-a"}).status_code == 201
    assert client.post("/api/personas", json={"handle": "@creator-a"}).status_code == 409


def test_unresolvable_handle_is_404(client: TestClient, fake_resolve: None) -> None:
    assert client.post("/api/personas", json={"handle": "@nosuch"}).status_code == 404


def test_unsupported_platform_is_422(client: TestClient, fake_resolve: None) -> None:
    assert client.post(
        "/api/personas", json={"handle": "@x", "platform": "telegram"}
    ).status_code == 422


def test_delete_removes_the_persona(client: TestClient, fake_resolve: None) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    assert client.delete("/api/personas/creator-a").status_code == 204
    assert client.get("/api/personas").json() == []


# --- card assembly ---------------------------------------------------------


def test_card_folds_notes_newest_first(
    client: TestClient, settings: Settings, fake_resolve: None
) -> None:
    """The card's stance for a symbol must come from the most recent note that named it.

    This is the rule that decides what the owner reads before trading: if they were bullish on a name
    in July and bearish yesterday, a card showing "bullish" is actively misleading.
    """
    client.post("/api/personas", json={"handle": "@creator-a"})
    store = VaultStore(settings)

    store.write_note(
        _note(
            "creator-a",
            "oldvideo001",
            published=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
            summary="Older take.",
            themes=("옛날 주제",),
            mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="old view"),),
        ),
        transcript_text="old transcript",
    )
    store.write_note(
        _note(
            "creator-a",
            "newvideo002",
            published=dt.datetime(2026, 8, 30, tzinfo=dt.UTC),
            summary="첫 문장입니다. 두 번째 문장입니다.",
            mentions=(TickerMention(symbol="NVDA", stance="bearish", reasoning="new view"),),
        ),
        transcript_text="new transcript",
    )

    card = client.get("/api/personas/cards").json()[0]
    assert card["note_count"] == 2
    assert card["latest_note"]["note_id"] == "newvideo002"
    # Headline is the newest summary's FIRST sentence, split on the Korean full stop.
    assert card["headline"] == "첫 문장입니다."
    nvda = [m for m in card["mentions"] if m["symbol"] == "NVDA"]
    assert len(nvda) == 1, "a symbol must appear once, not once per note"
    assert nvda[0]["stance"] == "bearish", "the most recent stance must win"


def test_card_surfaces_a_degraded_note(
    client: TestClient, settings: Settings, fake_resolve: None
) -> None:
    """A summary released despite failing the grounding gate must be visible on the card."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    store = VaultStore(settings)
    store.write_note(
        _note("creator-a", "degraded001", published=NOW, degraded=True),
        transcript_text="t",
    )
    card = client.get("/api/personas/cards").json()[0]
    assert card["grounding"]["degraded"] is True
    assert card["grounding"]["ok"] is False
    assert card["latest_note"]["degraded"] is True


def test_note_round_trips_through_the_api(
    client: TestClient, settings: Settings, fake_resolve: None
) -> None:
    """Korean summary, themes and quotes survive the vault and come back over HTTP intact."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    store = VaultStore(settings)
    store.write_note(
        _note(
            "creator-a",
            "roundtrip01",
            published=NOW,
            mentions=(TickerMention(symbol="NVDA", stance="unclear", reasoning="언급만 함"),),
        ),
        transcript_text="전체 자막",
    )

    notes = client.get("/api/personas/creator-a/notes").json()
    assert len(notes) == 1
    note = notes[0]
    assert note["summary"] == "첫 문장입니다. 두 번째 문장입니다."
    assert note["themes"] == ["반도체 사이클", "금리"]
    assert note["quotes"] == ["9월 시작입니다"]
    assert note["mentions"][0]["stance"] == "unclear"
    assert note["lang"] == "ko"

    one = client.get("/api/personas/creator-a/notes/roundtrip01").json()
    assert one["note_id"] == "roundtrip01"
    assert client.get("/api/personas/creator-a/notes/missing").status_code == 404


def test_a_note_id_is_matched_whole_not_as_a_suffix(
    client: TestClient, settings: Settings, fake_resolve: None
) -> None:
    """A note whose id contains a hyphen must not answer to the fragment after it.

    Real YouTube ids are drawn from `[A-Za-z0-9_-]` and routinely contain hyphens (`vidB-bbbbb2`),
    and a manual drop's id is `drop-<hex>`. The note filename is `<date>-<note_id>.md`, so a naive
    `*-<note_id>.md` glob lets the wildcard swallow the date *and* the head of a real id -- which
    made `GET /notes/bbbbb2` serve the `vidB-bbbbb2` note, and made `has_note` claim a video was
    already ingested when it never was, permanently skipping it.
    """
    client.post("/api/personas", json={"handle": "@creator-a"})
    store = VaultStore(settings)
    store.write_note(_note("creator-a", "vidB-bbbbb2", published=NOW), transcript_text="t")

    assert store.has_note("creator-a", "vidB-bbbbb2") is True
    assert store.has_note("creator-a", "bbbbb2") is False
    assert store.load_note("creator-a", "bbbbb2") is None

    assert client.get("/api/personas/creator-a/notes/vidB-bbbbb2").status_code == 200
    assert client.get("/api/personas/creator-a/notes/bbbbb2").status_code == 404


def test_a_note_with_no_upload_date_keeps_published_null(
    client: TestClient, settings: Settings, fake_resolve: None
) -> None:
    """`published` is nullable because the flat channel listing genuinely has no upload date. It must
    survive as null rather than being backfilled from `ingested_at`."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    VaultStore(settings).write_note(
        _note("creator-a", "nodate00001", published=None), transcript_text="t"
    )
    note = client.get("/api/personas/creator-a/notes").json()[0]
    assert note["published"] is None


# --- ingest ----------------------------------------------------------------


def test_ingest_for_unknown_persona_is_404(client: TestClient) -> None:
    assert client.post("/api/personas/nobody/ingest", json={}).status_code == 404


def test_ingest_of_a_bare_url_drop_is_rejected(client: TestClient, fake_resolve: None) -> None:
    """Dropping a link with no text is refused explicitly rather than silently ingesting nothing."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    response = client.post(
        "/api/personas/creator-a/ingest",
        json={"drop": {"url": "https://example.com/post"}},
    )
    assert response.status_code == 422
    assert "text" in response.json()["detail"]


def test_ingest_of_a_javascript_url_drop_is_rejected_with_422(
    client: TestClient, fake_resolve: None
) -> None:
    """`DropSpec.url` now rejects anything but `http(s)://` at this request boundary -- this value
    flows through to `EpisodicNote.url` (`app.personas.service.start_ingest` ->
    `app.personas.summarize`), and a `javascript:`/`data:` link must never even reach the ingest
    job, let alone a stored note."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    response = client.post(
        "/api/personas/creator-a/ingest",
        json={"drop": {"url": "javascript:alert(1)", "text": "some text"}},
    )
    assert response.status_code == 422


def test_ingesting_a_text_drop_writes_a_note_end_to_end(
    client: TestClient, fake_summarize: None, fake_resolve: None
) -> None:
    """A drop goes all the way through: plan one item, summarise it (stubbed), write the note, update
    the persona, finish the job. The summariser is stubbed because a real model call in the suite
    would be slow, costly and non-deterministic -- everything either side of it is real."""
    from app.personas import jobs as jobs_module

    client.post("/api/personas", json={"handle": "@creator-a"})
    response = client.post(
        "/api/personas/creator-a/ingest",
        json={"drop": {"text": "그는 엔비디아에 대해 강세를 전망했다.", "title": "a post"}},
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["persona"] == "creator-a"
    assert job["items_total"] == 1

    # The work runs on a daemon thread; join it rather than sleeping on a guess.
    jobs_module.registry().join(job["job_id"], timeout=30)

    finished = client.get(f"/api/personas/creator-a/ingest/{job['job_id']}").json()
    assert finished["state"] == "succeeded", finished
    assert finished["items_done"] == 1
    assert finished["items_failed"] == 0

    notes = client.get("/api/personas/creator-a/notes").json()
    assert len(notes) == 1
    assert notes[0]["summary"] == "그는 엔비디아 강세를 전망했다."
    assert notes[0]["kind"] == "manual"
    assert [m["symbol"] for m in notes[0]["mentions"]] == ["NVDA"]

    persona = client.get("/api/personas/creator-a").json()
    assert persona["note_count"] == 1
    assert persona["tickers"] == ["NVDA"]


def test_a_second_ingest_while_one_is_running_is_409(
    client: TestClient, fake_resolve: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two ingests of the same persona would race on the same note filenames and persona.json."""
    from app.personas import jobs as jobs_module

    client.post("/api/personas", json={"handle": "@creator-a"})
    registry = jobs_module.registry()
    monkeypatch.setattr(registry, "active", lambda slug: "already-running-job")
    response = client.post(
        "/api/personas/creator-a/ingest", json={"drop": {"text": "x"}}
    )
    assert response.status_code == 409


# --- QA defect regressions -------------------------------------------------


def _video_ref(video_id: str, title: str):  # type: ignore[no-untyped-def]
    from app.personas.sources.base import VideoRef

    return VideoRef(
        video_id=video_id,
        title=title,
        url=f"https://www.youtube.com/watch?v={video_id}",
        duration_s=600,
        published=None,
    )


def test_plan_attributes_each_video_to_the_source_it_came_from(
    client: TestClient, settings: Settings, fake_resolve: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect 1: a persona following two channels must not stamp every note with sources[0].

    Attribution is decided when the plan is built, where the producing channel is still known; if it
    were read off `persona.sources[0]` at write time the second channel's videos would carry the
    first channel's id, corrupting the pinned `source_id` field for any multi-source persona.
    """
    from app.personas import service
    from app.personas.sources import youtube

    client.post("/api/personas", json={"handle": "@creator-a"})  # yt:UCaaa...
    client.post("/api/personas/creator-a/sources", json={"handle": "@creatorb"})  # yt:UCbbb...
    persona = service.get_persona(settings, "creator-a")
    assert persona is not None

    def _list(key: str, *, limit: int):  # type: ignore[no-untyped-def]
        if key == "UCaaaaaaaaaaaaaaaaaaaaaa":
            return (_video_ref("vidFromA001", "A one"),)
        if key == "UCbbbbbbbbbbbbbbbbbbbbbb":
            return (_video_ref("vidFromB001", "B one"),)
        raise AssertionError(f"unexpected channel key {key!r}")

    monkeypatch.setattr(youtube, "list_videos", _list)

    plan = service._plan_items(
        settings, service._store(settings), persona, limit=20, video_urls=None, drop=None
    )
    by_id = {item.note_id: item.source_id for item in plan}
    assert by_id == {
        "vidFromA001": "yt:UCaaaaaaaaaaaaaaaaaaaaaa",
        "vidFromB001": "yt:UCbbbbbbbbbbbbbbbbbbbbbb",
    }


def test_one_unreachable_source_degrades_rather_than_failing_the_whole_plan(
    client: TestClient, settings: Settings, fake_resolve: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect 2: a dead channel must cost only that channel's videos, not 502 the whole ingest and
    discard the videos a healthy channel already listed -- the `app.api.news` degrade-not-5xx rule."""
    from app.personas import service
    from app.personas.sources import youtube
    from app.personas.sources.base import SourceUnavailable

    client.post("/api/personas", json={"handle": "@creator-a"})
    client.post("/api/personas/creator-a/sources", json={"handle": "@creatorb"})
    persona = service.get_persona(settings, "creator-a")
    assert persona is not None

    def _list(key: str, *, limit: int):  # type: ignore[no-untyped-def]
        if key == "UCaaaaaaaaaaaaaaaaaaaaaa":
            return (_video_ref("goodvid0001", "good"),)
        raise SourceUnavailable("rate limited", provider="youtube")

    monkeypatch.setattr(youtube, "list_videos", _list)

    plan = service._plan_items(
        settings, service._store(settings), persona, limit=20, video_urls=None, drop=None
    )
    assert [i.note_id for i in plan] == ["goodvid0001"], "the healthy source's video survives"

    # But when EVERY source is unreachable, there is genuinely nothing to do -- that is a 502.
    def _all_fail(key: str, *, limit: int):  # type: ignore[no-untyped-def]
        raise SourceUnavailable("down", provider="youtube")

    monkeypatch.setattr(youtube, "list_videos", _all_fail)
    with pytest.raises(service.PersonaError) as excinfo:
        service._plan_items(
            settings, service._store(settings), persona, limit=20, video_urls=None, drop=None
        )
    assert excinfo.value.status_code == 502


def test_record_note_does_not_revert_a_concurrent_source_change(
    client: TestClient, settings: Settings, fake_resolve: None
) -> None:
    """Defect 3: an `add_source`/`remove_source` during an ingest must survive the worker's next
    persona write. The worker holds a stale in-memory persona; folding the note into that and saving
    it would silently undo the owner's edit (a lost update)."""
    from app.personas import service

    client.post("/api/personas", json={"handle": "@creator-a"})
    store = service._store(settings)
    stale = service.get_persona(settings, "creator-a")
    assert stale is not None and len(stale.sources) == 1

    # The owner adds a second source AFTER the worker captured `stale`.
    client.post("/api/personas/creator-a/sources", json={"handle": "@creatorb"})

    note = _note("creator-a", "recordnote1", published=NOW,
                 mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="r"),))
    updated = service._record_note(store, stale, note)

    assert updated.note_count == 1
    assert "NVDA" in updated.tickers
    assert len(updated.sources) == 2, "the concurrently-added source must not be reverted"
    on_disk = service.get_persona(settings, "creator-a")
    assert on_disk is not None and len(on_disk.sources) == 2


def test_budget_exhaustion_reconciles_spend_and_stops(
    client: TestClient, settings: Settings, fake_resolve: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect 4: when the cap is hit, the recorded spend must be the true figure the exception
    carries (including a retry whose result never came back), and the backfill must stop rather than
    silently exceeding the cap on every subsequent item."""
    from decimal import Decimal

    from app.agents.models import BudgetExhausted
    from app.personas import jobs as jobs_module
    from app.personas import summarize as summarize_module

    client.post("/api/personas", json={"handle": "@creator-a"})

    def _raise(**kwargs: object):  # type: ignore[no-untyped-def]
        raise BudgetExhausted(spent_usd=Decimal("2.50"), cap_usd=Decimal("2"))

    monkeypatch.setattr(summarize_module, "summarize_item", _raise)

    response = client.post(
        "/api/personas/creator-a/ingest", json={"drop": {"text": "일부 텍스트"}}
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    jobs_module.registry().join(job_id, timeout=30)

    finished = client.get(f"/api/personas/creator-a/ingest/{job_id}").json()
    # done == 0 here, so the run failed -- but the spend is the accurate 2.50, not 0.
    assert finished["state"] == "failed"
    assert finished["spent_usd"] == "2.50"
    assert client.get("/api/personas/creator-a/notes").json() == []


# --- Phase 2: consolidation ------------------------------------------------


@pytest.fixture
def fake_consolidate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the one consolidation model call; everything either side of it (profile store round trip,
    persona bump, routing) stays real. `service.consolidate` imports `consolidate_notes` from the
    module at call time, so patching the module attribute is enough."""
    from decimal import Decimal

    from app.agentdesk.models import GroundingVerdict
    from app.agents.models import AgentBudget
    from app.personas import consolidate as consolidate_module
    from app.personas.models import ProfileClaim, RegimeView, TickerThesis

    def _fake(*, persona_slug: str, notes, settings, budget, model="", prior_profile=None):  # type: ignore[no-untyped-def]
        draft = consolidate_module.ProfileDraft(
            summary="반도체 사이클에 집중하는 트레이더.",
            beliefs=(ProfileClaim(text="AI 수요가 반도체를 이끈다", citations=("v1",)),),
            playbook=(ProfileClaim(text="박스권 상단 돌파에 진입", citations=("v1", "v2")),),
            methodology=(ProfileClaim(text="20일 이동평균선과 RSI(14)로 진입", citations=("v1",)),),
            regime=RegimeView(
                risk="on", rates="완화적", summary="위험자산 선호",
                sectors_favoured=("반도체",), citations=("v1",), has_signal=True,
            ),
            vocabulary=("박스권", "눌림목"),
        )
        thesis = TickerThesis(
            persona=persona_slug, symbol="NVDA", stance="bullish",
            updated_at=NOW, claims=(ProfileClaim(text="강세 유지", citations=("v1",)),), path="",
        )
        return consolidate_module.ConsolidationResult(
            draft=draft, theses=(thesis,), verdict=GroundingVerdict(ok=True),
            budget=AgentBudget(cap_usd=Decimal("5"), spent_usd=Decimal("0.20"), calls=1), calls=(),
        )

    monkeypatch.setattr(consolidate_module, "consolidate_notes", _fake)


def _seed_notes(settings: Settings) -> None:
    store = VaultStore(settings)
    store.write_note(
        _note("creator-a", "v1", published=NOW,
              mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="AI"),)),
        transcript_text="t1")
    store.write_note(_note("creator-a", "v2", published=NOW), transcript_text="t2")


def test_consolidate_writes_a_cited_profile_end_to_end(
    client: TestClient, settings: Settings, fake_resolve: None, fake_consolidate: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    _seed_notes(settings)

    resp = client.post("/api/personas/creator-a/consolidate")
    assert resp.status_code == 200, resp.text
    profile = resp.json()
    assert profile["version"] == 1
    assert profile["note_count"] == 2
    assert profile["beliefs"][0]["citations"] == ["v1"]
    assert profile["playbook"][0]["citations"] == ["v1", "v2"]
    assert profile["methodology"][0]["text"] == "20일 이동평균선과 RSI(14)로 진입"
    assert profile["vocabulary"] == ["박스권", "눌림목"]

    # GET /profile reads it back from the vault (methodology survives the profile.md round trip).
    got = client.get("/api/personas/creator-a/profile").json()
    assert got["summary"] == "반도체 사이클에 집중하는 트레이더."
    assert got["methodology"][0]["text"] == "20일 이동평균선과 RSI(14)로 진입"
    assert got["beliefs"][0]["text"] == "AI 수요가 반도체를 이끈다"

    # The persona record reflects the new version.
    persona = client.get("/api/personas/creator-a").json()
    assert persona["profile_version"] == 1
    assert persona["consolidated_at"] is not None

    # Re-consolidating bumps the version and archives the prior one.
    resp2 = client.post("/api/personas/creator-a/consolidate")
    assert resp2.json()["version"] == 2


def test_theses_round_trip_and_link(
    client: TestClient, settings: Settings, fake_resolve: None, fake_consolidate: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    _seed_notes(settings)
    client.post("/api/personas/creator-a/consolidate")

    theses = client.get("/api/personas/creator-a/theses").json()
    assert [t["symbol"] for t in theses] == ["NVDA"]
    assert theses[0]["stance"] == "bullish"
    assert theses[0]["claims"][0]["citations"] == ["v1"]

    one = client.get("/api/personas/creator-a/theses/NVDA").json()
    assert one["symbol"] == "NVDA"
    assert client.get("/api/personas/creator-a/theses/TSLA").status_code == 404


def test_consolidate_with_no_notes_is_409(
    client: TestClient, fake_resolve: None, fake_consolidate: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    resp = client.post("/api/personas/creator-a/consolidate")
    assert resp.status_code == 409


def test_profile_and_consolidate_404_for_unknown_persona(client: TestClient) -> None:
    assert client.get("/api/personas/nobody/profile").status_code == 404
    assert client.post("/api/personas/nobody/consolidate").status_code == 404
    assert client.get("/api/personas/nobody/theses").status_code == 404


def test_profile_404_before_first_consolidation(
    client: TestClient, fake_resolve: None
) -> None:
    """A persona that exists but was never consolidated: /profile is 404 (the frontend's empty
    state), /theses is an empty list, not an error."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    assert client.get("/api/personas/creator-a/profile").status_code == 404
    assert client.get("/api/personas/creator-a/theses").json() == []


# --- Phase 3a: scorecard ---------------------------------------------------


@pytest.fixture
def fake_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the market-data primitive so the scorecard endpoint scores against a deterministic series
    instead of the network. One rising series: entry ~100, latest ~130 (+30%)."""
    import datetime as _dt

    from app.db.duck import Interval
    from app.market.models import Bar, BarSeries, BarSource
    from app.personas import backtest as backtest_module
    from app.personas import scoring as scoring_module

    def _series(symbol: str, interval: Interval, *, start=None, settings=None, **kw):  # type: ignore[no-untyped-def]
        base = _dt.datetime(2026, 8, 1, tzinfo=_dt.UTC)
        bars = [
            Bar(ts=base + _dt.timedelta(days=i), open=100.0 + i, high=100.0 + i,
                low=100.0 + i, close=100.0 + i, adj_close=100.0 + i)
            for i in range(31)  # Aug 1..Aug 31, close 100..130
        ]
        return BarSeries(symbol=symbol, interval=interval, source=BarSource.STORE, bars=bars)

    # Both the scorer and the backtest lens fetch bars through their own module-level `ensure_series`
    # reference (SPY, in the backtest's case), so both must be patched or the backtest silently hits
    # the real store for SPY -- which both breaks hermeticity and makes the excess-vs-SPY non-zero.
    monkeypatch.setattr(scoring_module, "ensure_series", _series)
    monkeypatch.setattr(backtest_module, "ensure_series", _series)


def test_scorecard_scores_dated_calls(
    client: TestClient, settings: Settings, fake_resolve: None, fake_bars: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    store = VaultStore(settings)
    aug = dt.datetime(2026, 8, 2, tzinfo=dt.UTC)
    store.write_note(
        _note("creator-a", "callbull01", published=aug,
              mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="up"),)),
        transcript_text="t")
    store.write_note(
        _note("creator-a", "callbear01", published=aug,
              mentions=(TickerMention(symbol="TSLA", stance="bearish", reasoning="down"),)),
        transcript_text="t")

    sc = client.get("/api/personas/creator-a/scorecard")
    assert sc.status_code == 200, sc.text
    body = sc.json()
    by_sym = {c["symbol"]: c for c in body["scored_calls"]}
    # Rising series: the bullish call played out, the bearish call went against.
    assert by_sym["NVDA"]["outcome"] == "played_out"
    assert by_sym["NVDA"]["return_pct"] > 0
    assert by_sym["NVDA"]["basis"] == "adjusted"
    assert by_sym["TSLA"]["outcome"] == "went_against"
    # Both are directional and priced -> denominator 2, one played out.
    assert body["directional_count"] == 2
    assert body["played_out"] == 1
    assert body["hit_rate"] == 0.5


def test_scorecard_unknown_persona_is_404(client: TestClient) -> None:
    assert client.get("/api/personas/nobody/scorecard").status_code == 404


def test_scorecard_with_no_notes_is_empty_not_error(
    client: TestClient, fake_resolve: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    body = client.get("/api/personas/creator-a/scorecard").json()
    assert body["scored_calls"] == []
    assert body["hit_rate"] is None   # undefined over zero calls, never 0


# --- Phase 3b: horizons + timeline -----------------------------------------


def test_scorecard_carries_fixed_horizon_stats(
    client: TestClient, settings: Settings, fake_resolve: None, fake_bars: None
) -> None:
    """The window-independent measure: each call gets 5/20/60-day horizon returns, and the scorecard
    aggregates them. fake_bars is a 31-bar rising series (Aug 1..31, +1/day)."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    VaultStore(settings).write_note(
        _note("creator-a", "hz01", published=dt.datetime(2026, 8, 2, tzinfo=dt.UTC),
              mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="up"),)),
        transcript_text="t")

    body = client.get("/api/personas/creator-a/scorecard").json()
    call = body["scored_calls"][0]
    horizons = {h["days"]: h for h in call["horizons"]}
    assert set(horizons) == {5, 20, 60}
    # Entry ~Aug 3; +5 trading bars exists in a 31-bar series -> complete, positive.
    assert horizons[5]["complete"] is True
    assert horizons[5]["return_pct"] > 0
    # +60 bars does not exist in a 31-bar series -> incomplete, no number.
    assert horizons[60]["complete"] is False
    assert horizons[60]["return_pct"] is None

    stats = {s["days"]: s for s in body["horizon_stats"]}
    assert stats[5]["directional_count"] == 1
    assert stats[5]["played_out"] == 1
    assert stats[5]["hit_rate"] == 1.0
    # No call reaches a complete 60-day horizon -> undefined, not zero.
    assert stats[60]["directional_count"] == 0
    assert stats[60]["hit_rate"] is None


def test_timeline_orders_notes_and_tracks_stance_evolution(
    client: TestClient, settings: Settings, fake_resolve: None
) -> None:
    """The chronological view: notes newest-first, and a symbol whose stance flipped shows its
    evolution oldest-first and sorts ahead of a never-changing symbol."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    store = VaultStore(settings)
    store.write_note(
        _note("creator-a", "tl_jul", published=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
              mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="early"),
                        TickerMention(symbol="MSFT", stance="bullish", reasoning="steady"),)),
        transcript_text="t")
    store.write_note(
        _note("creator-a", "tl_aug", published=dt.datetime(2026, 8, 30, tzinfo=dt.UTC),
              mentions=(TickerMention(symbol="NVDA", stance="bearish", reasoning="turned"),
                        TickerMention(symbol="MSFT", stance="bullish", reasoning="steady"),)),
        transcript_text="t")

    tl = client.get("/api/personas/creator-a/timeline").json()
    assert [e["note_id"] for e in tl["entries"]] == ["tl_aug", "tl_jul"]  # newest first

    timelines = {t["symbol"]: t for t in tl["stance_timelines"]}
    # NVDA changed stance -> sorts ahead of MSFT (never changed).
    assert next(iter(timelines)) == "NVDA"
    nvda_points = timelines["NVDA"]["points"]
    assert [p["stance"] for p in nvda_points] == ["bullish", "bearish"]  # oldest first: evolution
    assert timelines["MSFT"]["points"][0]["stance"] == "bullish"


def test_timeline_unknown_persona_is_404_and_empty_when_no_notes(
    client: TestClient, fake_resolve: None
) -> None:
    assert client.get("/api/personas/nobody/timeline").status_code == 404
    client.post("/api/personas", json={"handle": "@creator-a"})
    tl = client.get("/api/personas/creator-a/timeline").json()
    assert tl["entries"] == [] and tl["stance_timelines"] == []


# --- Phase 4: ask the persona ----------------------------------------------


@pytest.fixture
def fake_ask(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the ask model call. `service.ask` imports `ask_persona` from the module at call time, so
    patching the module attribute suffices."""
    from app.agentdesk.models import GroundingVerdict
    from app.personas import ask as ask_module
    from app.personas.models import PersonaAnswer

    def _fake(*, persona_slug, question, symbol, profile, notes, settings, budget, model=""):  # type: ignore[no-untyped-def]
        cited = tuple(n.note_id for n in notes[:1])
        return ask_module.AskResult(
            answer=PersonaAnswer(
                persona=persona_slug,
                question=question,
                symbol=symbol,
                answer="제 기록상 엔비디아에 대해 강세로 봤습니다." if symbol else "기록 기반 답변.",
                citations=cited,
                stance="bullish" if symbol else None,
                grounding=GroundingVerdict(ok=True),
                degraded=False,
                cost_usd="0.03",
            ),
            calls=(),
        )

    monkeypatch.setattr(ask_module, "ask_persona", _fake)


def test_ask_returns_grounded_answer(
    client: TestClient, settings: Settings, fake_resolve: None, fake_ask: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    VaultStore(settings).write_note(
        _note("creator-a", "asknote01", published=NOW,
              mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="AI"),)),
        transcript_text="t")

    resp = client.post(
        "/api/personas/creator-a/ask", json={"question": "엔비디아 어떻게 봐요?", "symbol": "nvda"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["symbol"] == "NVDA"  # normalised uppercase
    assert body["stance"] == "bullish"
    assert body["citations"] == ["asknote01"]
    assert body["cost_usd"] == "0.03"


def test_ask_unknown_persona_is_404(client: TestClient, fake_ask: None) -> None:
    assert client.post(
        "/api/personas/nobody/ask", json={"question": "hi"}
    ).status_code == 404


def test_ask_with_no_notes_is_409(client: TestClient, fake_resolve: None, fake_ask: None) -> None:
    """A persona with nothing on record cannot be asked -- 409, not a fabricated answer."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    resp = client.post("/api/personas/creator-a/ask", json={"question": "엔비디아?"})
    assert resp.status_code == 409


def test_ask_rejects_empty_question(client: TestClient, fake_resolve: None) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    assert client.post(
        "/api/personas/creator-a/ask", json={"question": ""}
    ).status_code == 422


# --- Phase 4b: backtest lens -----------------------------------------------


def test_backtest_compares_calls_to_spy(
    client: TestClient, settings: Settings, fake_resolve: None, fake_bars: None
) -> None:
    """The lens: follow the persona's bullish call and compare to SPY over the same window. fake_bars
    is a rising series for every symbol INCLUDING SPY, so the excess is ~0 (they matched the market),
    which is the honest, correct answer for identical series -- the point is the shape, not a win."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    VaultStore(settings).write_note(
        _note("creator-a", "bt01", published=dt.datetime(2026, 8, 2, tzinfo=dt.UTC),
              mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="up"),)),
        transcript_text="t")

    body = client.get("/api/personas/creator-a/backtest").json()
    assert body["benchmark"] == "SPY"
    assert body["call_count"] == 1
    assert body["caveat"]  # the non-empty honesty disclaimer must be present
    h5 = next(h for h in body["horizons"] if h["days"] == 5)
    assert h5["n"] == 1
    assert h5["mean_return_pct"] is not None
    assert h5["mean_benchmark_pct"] is not None
    # NVDA and SPY use the same synthetic rising series here, so excess is ~0.
    assert abs(h5["excess_pct"]) < 1e-6
    # A horizon no call reaches is undefined, not zero.
    h60 = next(h for h in body["horizons"] if h["days"] == 60)
    assert h60["n"] == 0 and h60["excess_pct"] is None


def test_backtest_unknown_persona_is_404(client: TestClient) -> None:
    assert client.get("/api/personas/nobody/backtest").status_code == 404


def test_backtest_no_directional_calls_is_empty_not_error(
    client: TestClient, settings: Settings, fake_resolve: None, fake_bars: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    # A note with no mentions -> no directional calls.
    VaultStore(settings).write_note(_note("creator-a", "btempty01", published=NOW), transcript_text="t")
    body = client.get("/api/personas/creator-a/backtest").json()
    assert body["call_count"] == 0
    assert all(h["n"] == 0 and h["excess_pct"] is None for h in body["horizons"])


# --- Phase 6: persona paper book (Paper Desk) ------------------------------


def test_persona_book_holds_current_bullish_names(
    client: TestClient, settings: Settings, fake_resolve: None, fake_bars: None
) -> None:
    """The persona's paper book: a cash-constrained replay of its dated calls. NVDA is bought and
    still bullish -> stays an open holding. TSLA is bought then flipped bearish -> closed, realised as
    a trade, and no longer in `holdings`."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    store = VaultStore(settings)
    aug = dt.datetime(2026, 8, 2, tzinfo=dt.UTC)
    later = dt.datetime(2026, 8, 20, tzinfo=dt.UTC)
    # NVDA: bullish and still bullish -> held. TSLA: bullish then bearish -> bought, then closed.
    store.write_note(
        _note("creator-a", "bk_old", published=aug,
              mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="a"),
                        TickerMention(symbol="TSLA", stance="bullish", reasoning="b"),)),
        transcript_text="t")
    store.write_note(
        _note("creator-a", "bk_new", published=later,
              mentions=(TickerMention(symbol="TSLA", stance="bearish", reasoning="turned"),)),
        transcript_text="t")

    book = client.get("/api/personas/creator-a/book").json()
    assert book["inception"] == "2026-01-01"
    syms = {h["symbol"] for h in book["holdings"]}
    assert "NVDA" in syms
    assert "TSLA" not in syms, "a name whose latest stance is bearish is not a current holding"
    nvda = next(h for h in book["holdings"] if h["symbol"] == "NVDA")
    assert nvda["stance"] == "bullish"
    # Rising synthetic series -> positive unrealised P&L; money fields are strings on the wire.
    assert isinstance(nvda["market_value"], str)
    # `return_pct` is a 0-1 FRACTION, not a pre-multiplied percent -- a synthetic series that moves a
    # few tens of percent must never read back as "6427".
    assert 0 < float(nvda["return_pct"]) < 5
    assert "last_bullish_on" in nvda

    # TSLA was bought and then closed on the bearish flip -- it shows up as a realised trade, not a
    # phantom "never held" exclusion.
    tsla_trades = [t for t in book["trades"] if t["symbol"] == "TSLA"]
    assert len(tsla_trades) == 1
    assert tsla_trades[0]["reason"] == "flip_bearish"

    # New cash-replay envelope fields: money on the wire as strings, and the book's own invariants.
    assert isinstance(book["cash"], str)
    assert isinstance(book["starting_cash"], str)
    assert isinstance(book["equity"], str)
    assert float(book["cash"]) >= 0
    assert abs(float(book["equity"]) - (float(book["cash"]) + float(book["market_value_total"]))) < 0.01
    assert book["trade_count"] == len(book["trades"])
    assert book["open_count"] == len(book["holdings"])


def test_books_collection_lists_every_persona(
    client: TestClient, fake_resolve: None, fake_bars: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    client.post("/api/personas", json={"handle": "@creatorb"})
    books = client.get("/api/personas/books").json()
    assert {b["persona"] for b in books} == {"creator-a", "creatorb"}
    # "books" is not captured as a persona slug (route ordering) -> not a 404/persona lookup.


def test_persona_book_unknown_persona_is_404(client: TestClient) -> None:
    assert client.get("/api/personas/nobody/book").status_code == 404


def test_persona_book_empty_when_no_current_bullish(
    client: TestClient, settings: Settings, fake_resolve: None, fake_bars: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    VaultStore(settings).write_note(_note("creator-a", "bk_empty", published=NOW), transcript_text="t")
    book = client.get("/api/personas/creator-a/book").json()
    assert book["holdings"] == []
    assert book["trades"] == []
    assert book["skipped"] == []
    assert book["as_of"] is None
    # An untouched book still starts and ends at the same $100,000 -- nothing bought, nothing sold.
    assert book["cash"] == book["starting_cash"] == book["equity"]
    assert float(book["return_pct"]) == 0


# --- Phase 7b: consensus watchlist -----------------------------------------


def test_watchlist_aggregates_current_bullish_across_personas(
    client: TestClient, settings: Settings, fake_resolve: None
) -> None:
    """Two influencers currently bullish on the same name -> one entry, bullish_count 2. A name whose
    latest stance flipped bearish is excluded. Ranked by backing count."""
    store = VaultStore(settings)
    for handle in ("@creator-a", "@creatorb"):
        client.post("/api/personas", json={"handle": handle})
    store.write_note(
        _note("creator-a", "wl_a", published=NOW,
              mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="soso likes it"),
                        TickerMention(symbol="TSLA", stance="bullish", reasoning="x"),)),
        transcript_text="t")
    store.write_note(
        _note("creator-a", "wl_a2", published=dt.datetime(2026, 9, 2, tzinfo=dt.UTC),
              mentions=(TickerMention(symbol="TSLA", stance="bearish", reasoning="turned"),)),
        transcript_text="t")
    store.write_note(
        _note("creatorb", "wl_b", published=NOW,
              mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="creatorb too"),)),
        transcript_text="t")

    wl = client.get("/api/personas/watchlist").json()
    assert wl["caveat"]
    by = {e["symbol"]: e for e in wl["entries"]}
    assert by["NVDA"]["bullish_count"] == 2
    assert sorted(by["NVDA"]["personas"]) == ["creator-a", "creatorb"]
    assert "TSLA" not in by, "a name whose latest stance is bearish is off the watchlist"
    # NVDA (2 backers) ranks first.
    assert wl["entries"][0]["symbol"] == "NVDA"


def test_watchlist_empty_when_no_personas(client: TestClient) -> None:
    wl = client.get("/api/personas/watchlist").json()
    assert wl["entries"] == []
    assert wl["caveat"]


# --- Phase 7c: persona -> strategy card ------------------------------------


@pytest.fixture
def fake_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the model+card_for mapping so the endpoint test stays offline and deterministic.
    `service.strategy_card` imports `draft_strategy_card` from the module at call time."""
    from app.personas import strategy as strategy_module
    from app.personas.models import StrategyCardDraft

    def _fake(*, persona_slug, profile, bullish_tickers, settings, budget, model=""):  # type: ignore[no-untyped-def]
        return strategy_module.DraftResult(
            draft=StrategyCardDraft(
                persona=persona_slug,
                mapped=True,
                rule_shape="ma-crossover",
                card={"agent_id": f"persona-{persona_slug}", "universe": list(bullish_tickers),
                      "entry": "ema(20) crosses_above ema(50)", "designed_through": "2026-02-13"},
                rationale="maps their MA-pullback method",
                citations=("v1",),
                caveat="Inspired by, not faithful; an exploration lens, not advice.",
                cost_usd="0.05",
            ),
            calls=(),
        )

    monkeypatch.setattr(strategy_module, "draft_strategy_card", _fake)


def _seed_profile_with_methodology(settings: Settings, slug: str) -> None:
    """A consolidated profile WITH methodology + a current-bullish note -- the precondition for 7c."""

    from app.personas.models import PersonaProfile, ProfileClaim
    from app.personas.profile_store import ProfileStore

    VaultStore(settings).write_note(
        _note(slug, "v1", published=NOW,
              mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="a"),)),
        transcript_text="t")
    ProfileStore(settings).save_profile(PersonaProfile(
        persona=slug, version=1, consolidated_at=NOW, note_count=1, summary="s",
        methodology=(ProfileClaim(text="20/50 EMA crossover with pullback entry", citations=("v1",)),),
        path=""))


def test_strategy_card_maps_a_persona_with_methodology(
    client: TestClient, settings: Settings, fake_resolve: None, fake_strategy: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    _seed_profile_with_methodology(settings, "creator-a")
    resp = client.post("/api/personas/creator-a/strategy-card")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mapped"] is True
    assert body["rule_shape"] == "ma-crossover"
    assert body["card"]["universe"] == ["NVDA"]
    assert body["caveat"]


def test_strategy_card_409_without_methodology(
    client: TestClient, settings: Settings, fake_resolve: None, fake_strategy: None
) -> None:
    """A pure commentator (no methodology) cannot be mapped -- 409, never an invented card."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    VaultStore(settings).write_note(_note("creator-a", "v1", published=NOW), transcript_text="t")
    # No profile / no methodology consolidated.
    resp = client.post("/api/personas/creator-a/strategy-card")
    assert resp.status_code == 409


def test_strategy_card_unknown_persona_is_404(client: TestClient) -> None:
    assert client.post("/api/personas/nobody/strategy-card").status_code == 404


# --- Phase 8: rigor + auditability endpoints -------------------------------


def test_strategy_card_persists_and_is_listed(
    client: TestClient, settings: Settings, fake_resolve: None, fake_strategy: None
) -> None:
    """A mapped draft is saved (versioned) and comes back from the list endpoint."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    _seed_profile_with_methodology(settings, "creator-a")
    made = client.post("/api/personas/creator-a/strategy-card")
    assert made.status_code == 200, made.text
    assert made.json()["version"] == 1
    made2 = client.post("/api/personas/creator-a/strategy-card")
    assert made2.json()["version"] == 2
    listed = client.get("/api/personas/creator-a/strategy-cards")
    assert listed.status_code == 200
    rows = listed.json()
    assert [r["draft"]["version"] for r in rows] == [2, 1]  # newest first
    assert rows[0]["draft"]["card"]["universe"] == ["NVDA"]


def test_strategy_cards_list_unknown_persona_404(client: TestClient) -> None:
    assert client.get("/api/personas/nobody/strategy-cards").status_code == 404


def test_regime_reports_consolidated_view(
    client: TestClient, settings: Settings, fake_resolve: None, fake_consolidate: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    _seed_notes(settings)
    assert client.post("/api/personas/creator-a/consolidate").status_code == 200
    resp = client.get("/api/personas/regime")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["risk_on"] == 1
    row = next(p for p in body["personas"] if p["persona"] == "creator-a")
    assert row["has_view"] is True
    assert row["view"]["risk"] == "on"
    assert body["caveat"]


def test_profile_carries_regime_after_consolidation(
    client: TestClient, settings: Settings, fake_resolve: None, fake_consolidate: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    _seed_notes(settings)
    client.post("/api/personas/creator-a/consolidate")
    profile = client.get("/api/personas/creator-a/profile").json()
    assert profile["regime"] is not None
    assert profile["regime"]["risk"] == "on"
    assert profile["regime"]["has_signal"] is True


def test_profile_diff_between_two_versions(
    client: TestClient, settings: Settings, fake_resolve: None, fake_consolidate: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    _seed_notes(settings)
    client.post("/api/personas/creator-a/consolidate")
    client.post("/api/personas/creator-a/consolidate")  # v2 (same fake content)
    resp = client.get("/api/personas/creator-a/profile/diff", params={"from": 1, "to": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["from_version"] == 1
    assert body["to_version"] == 2
    # Identical fake content across versions -> no added/removed claims.
    assert body["added"] == 0
    assert body["removed"] == 0


def test_profile_diff_unknown_version_is_404(
    client: TestClient, settings: Settings, fake_resolve: None, fake_consolidate: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    _seed_notes(settings)
    client.post("/api/personas/creator-a/consolidate")
    assert client.get(
        "/api/personas/creator-a/profile/diff", params={"from": 1, "to": 9}
    ).status_code == 404


def test_watchlist_as_of_is_point_in_time(
    client: TestClient, settings: Settings, fake_resolve: None
) -> None:
    """A bullish call made after the as_of date must not appear in the point-in-time watchlist."""
    import datetime as _dt

    client.post("/api/personas", json={"handle": "@creator-a"})
    early = _dt.datetime(2026, 3, 1, tzinfo=_dt.UTC)
    late = _dt.datetime(2026, 8, 1, tzinfo=_dt.UTC)
    store = VaultStore(settings)
    store.write_note(_note("creator-a", "e1", published=early,
                           mentions=(TickerMention(symbol="NVDA", stance="bullish", reasoning="a"),)),
                     transcript_text="t")
    store.write_note(_note("creator-a", "l1", published=late,
                           mentions=(TickerMention(symbol="PLTR", stance="bullish", reasoning="b"),)),
                     transcript_text="t")
    now_syms = {e["symbol"] for e in client.get("/api/personas/watchlist").json()["entries"]}
    assert {"NVDA", "PLTR"} <= now_syms
    pit = client.get("/api/personas/watchlist", params={"as_of": "2026-04-01"}).json()
    pit_syms = {e["symbol"] for e in pit["entries"]}
    assert "NVDA" in pit_syms
    assert "PLTR" not in pit_syms  # its bullish call came after the cutoff


def test_book_exclude_intraday_and_as_of_accepted(
    client: TestClient, settings: Settings, fake_resolve: None
) -> None:
    """The new book query params are wired and accepted (empty vault -> empty book, not an error)."""
    client.post("/api/personas", json={"handle": "@creator-a"})
    resp = client.get("/api/personas/creator-a/book",
                      params={"as_of": "2026-06-01", "exclude_intraday": "true"})
    assert resp.status_code == 200, resp.text


def test_consolidate_incremental_is_accepted(
    client: TestClient, settings: Settings, fake_resolve: None, fake_consolidate: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    _seed_notes(settings)
    assert client.post("/api/personas/creator-a/consolidate").status_code == 200
    resp = client.post("/api/personas/creator-a/consolidate", params={"incremental": "true"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2


@pytest.fixture
def fake_critique(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.personas import critique as critique_module
    from app.personas.models import CardCritique

    def _fake(*, persona_slug, profile, card, settings, budget, model=""):  # type: ignore[no-untyped-def]
        return critique_module.CritiqueResult(
            critique=CardCritique(
                persona=persona_slug, verdict="aligned",
                assessment="This fits how they trade.", citations=("v1",),
                caveat="An impression of their view, not advice.", cost_usd="0.03",
            ),
            calls=(),
        )

    monkeypatch.setattr(critique_module, "critique_card", _fake)


def test_critique_endpoint(
    client: TestClient, settings: Settings, fake_resolve: None, fake_critique: None
) -> None:
    client.post("/api/personas", json={"handle": "@creator-a"})
    _seed_profile_with_methodology(settings, "creator-a")
    resp = client.post("/api/personas/creator-a/critique",
                       json={"card": {"agent_id": "x", "universe": ["NVDA"]}})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] == "aligned"
    assert body["citations"] == ["v1"]
    assert body["caveat"]


def test_critique_unknown_persona_404(client: TestClient) -> None:
    assert client.post("/api/personas/nobody/critique", json={"card": {}}).status_code == 404
