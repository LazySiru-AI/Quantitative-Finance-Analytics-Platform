"""Integration tests for the influencer-backfill HTTP surface (`app.api.backfill`).

**Nothing here touches YouTube or a model.** `discover_tasks` is patched to return ready-made
`BackfillTask`s (the generate test), and `build_symbol_validator` is patched to a small allowlist at
its definition site (`app.personas.tickers`), which both the validate endpoint and `ingest_result`
import at call time -- so no ledger/market/provider lookup runs.

**The tasks dir is redirected into `tmp_path`.** `Settings.backfill_tasks_dir` defaults to
`REPO_ROOT/.backfill-tasks`; the conftest `settings` fixture redirects the vault and stores but not
this dir, so a naive test would read and write the developer's real repo folder. The `cfg` fixture
below sets `INVDASH_BACKFILL_TASKS_DIR` the same way conftest sets its other `INVDASH_*` vars (env var
+ `get_settings.cache_clear()`) before the `TestClient` is built.

Route *registration* is asserted via `app.openapi()["paths"]`, not `app.routes` -- FastAPI 0.141 does
not list these routes on the latter, a false negative that has cost this repo real time.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.personas.backfill import BackfillTask, write_task_files
from app.personas.models import FollowedSource, Persona
from app.personas.store import VaultStore

_UTC = dt.UTC
_NOW = dt.datetime(2026, 9, 1, tzinfo=_UTC)

#: The reference transcript every grounding assertion is made against. It states 950 and 12.5%, and
#: nothing else a `numeric_tokens` sweep would consider groundable.
_TRANSCRIPT = (
    "Nvidia is trading around 950 dollars today and I think it runs further. "
    "Tesla deliveries fell 12.5% and I am staying out of it."
)


@pytest.fixture
def cfg(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with `backfill_tasks_dir` redirected into `tmp_path`.

    Built on top of the conftest `settings` fixture (which redirects the vault and stores), then adds
    the one env var conftest does not set, clears the cache and returns the fresh settings -- so the
    app, whose handlers call `get_settings()` at request time, sees the redirected dir too.
    """
    tasks_dir = tmp_path / "backfill-tasks"
    monkeypatch.setenv("INVDASH_BACKFILL_TASKS_DIR", str(tasks_dir))
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def client(cfg: Settings) -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def stub_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the symbol validator to a small allowlist at its definition site.

    Both the validate endpoint and `ingest_result` import `build_symbol_validator` from
    `app.personas.tickers` at call time, so patching the module attribute reaches both without a
    ledger/universe/provider lookup."""
    from app.personas import tickers

    def _validator(symbol: str) -> bool:
        return symbol.strip().upper() in {"NVDA", "TSLA"}

    monkeypatch.setattr(tickers, "build_symbol_validator", lambda settings, **_: _validator)


def _task(
    *,
    slug: str = "creator-a",
    name: str = "Creator A",
    video_id: str = "vid123",
    generated: bool = False,
) -> BackfillTask:
    return BackfillTask(
        persona_slug=slug,
        persona_name=name,
        source_id="yt:UCabc",
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title=f"Video {video_id}",
        published=_NOW,
        lang="en",
        transcript=_TRANSCRIPT,
        generated=generated,
    )


def _persona(store: VaultStore, *, slug: str = "creator-a") -> Persona:
    persona = Persona(
        slug=slug,
        display_name="Creator A",
        sources=(
            FollowedSource(
                source_id="yt:UCabc",
                platform="youtube",
                handle=slug,
                channel_id="UCabc",
                url=f"https://www.youtube.com/@{slug}",
                added_at=_NOW,
            ),
        ),
        created_at=_NOW,
    )
    store.save_persona(persona)
    return persona


def _reply(**overrides: object) -> str:
    """A well-formed reply body whose every number appears in `_TRANSCRIPT`, as a JSON string."""
    body: dict[str, object] = {
        "summary": "The speaker is bullish on Nvidia around 950 and cautious on Tesla.",
        "themes": ["AI capex", "EV demand"],
        "quotes": ["I think it runs further."],
        "mentions": [
            {"symbol": "NVDA", "stance": "bullish", "horizon": "swing", "reasoning": "Momentum."},
        ],
    }
    body.update(overrides)
    return json.dumps(body)


# --- registration -----------------------------------------------------------------


def test_all_five_routes_are_registered(client: TestClient) -> None:
    from app.main import app

    paths = set(app.openapi()["paths"])
    assert {
        "/api/backfill/tasks",
        "/api/backfill/tasks/{video_id}",
        "/api/backfill/generate",
        "/api/backfill/validate",
        "/api/backfill/tasks/{video_id}/result",
    } <= paths


# --- GET /tasks -------------------------------------------------------------------


def test_list_tasks_empty_when_no_dir(client: TestClient) -> None:
    resp = client.get("/api/backfill/tasks")
    assert resp.status_code == 200
    assert resp.json() == {"tasks": []}


def test_list_tasks_returns_written_packets(client: TestClient, cfg: Settings) -> None:
    write_task_files(
        [_task(video_id="vaaa"), _task(video_id="vbbb")],
        cfg.backfill_tasks_dir,
        summary_lang="en",
    )
    resp = client.get("/api/backfill/tasks")
    assert resp.status_code == 200
    tasks = resp.json()["tasks"]
    assert {t["video_id"] for t in tasks} == {"vaaa", "vbbb"}
    one = next(t for t in tasks if t["video_id"] == "vaaa")
    assert one["persona_slug"] == "creator-a"
    assert one["persona_name"] == "Creator A"
    assert one["title"] == "Video vaaa"
    assert one["url"].endswith("vaaa")
    assert one["published"] == "2026-09-01"
    assert one["filename"] == "creator-a__vaaa.md"


# --- GET /tasks/{video_id} --------------------------------------------------------


def test_get_task_returns_markdown(client: TestClient, cfg: Settings) -> None:
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    resp = client.get("/api/backfill/tasks/vaaa")
    assert resp.status_code == 200
    body = resp.json()
    assert body["video_id"] == "vaaa"
    assert body["filename"] == "creator-a__vaaa.md"
    assert "## Transcript" in body["markdown"]
    assert "Nvidia is trading around 950" in body["markdown"]


def test_get_task_unknown_id_is_404(client: TestClient) -> None:
    resp = client.get("/api/backfill/tasks/nosuch")
    assert resp.status_code == 404


# --- POST /generate ---------------------------------------------------------------


def test_generate_writes_files(
    client: TestClient, cfg: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = [_task(video_id="vgen1"), _task(video_id="vgen2")]
    # Patch where the router looks the name up (imported into `app.api.backfill`), so the endpoint
    # never reaches YouTube.
    import app.api.backfill as backfill_api

    monkeypatch.setattr(backfill_api, "discover_tasks", lambda *a, **k: tasks)

    resp = client.post("/api/backfill/generate", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["written"] == 2
    assert {t["video_id"] for t in body["tasks"]} == {"vgen1", "vgen2"}
    assert (cfg.backfill_tasks_dir / "creator-a__vgen1.md").exists()
    assert (cfg.backfill_tasks_dir / "creator-a__vgen2.md").exists()


# --- POST /validate ---------------------------------------------------------------


def test_validate_ok_for_grounded_reply(
    client: TestClient, cfg: Settings, stub_validator: None
) -> None:
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    resp = client.post("/api/backfill/validate", json={"video_id": "vaaa", "text": _reply()})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "reasons": [], "dropped_symbols": [], "ungrounded_numbers": []}


def test_validate_reports_a_dropped_symbol_without_failing(
    client: TestClient, cfg: Settings, stub_validator: None
) -> None:
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    reply = _reply(
        mentions=[{"symbol": "FAKE", "stance": "bullish", "horizon": "swing", "reasoning": "x"}]
    )
    resp = client.post("/api/backfill/validate", json={"video_id": "vaaa", "text": reply})
    assert resp.status_code == 200
    body = resp.json()
    # An unvalidatable ticker is dropped, not a rejection: ok stays True, it is only reported.
    assert body["ok"] is True
    assert body["dropped_symbols"] == ["FAKE"]


def test_validate_unparseable_text_is_422(
    client: TestClient, cfg: Settings, stub_validator: None
) -> None:
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    resp = client.post(
        "/api/backfill/validate", json={"video_id": "vaaa", "text": "no json here, sorry"}
    )
    assert resp.status_code == 422
    assert "detail" in resp.json()


def test_validate_unknown_video_id_is_404(
    client: TestClient, cfg: Settings, stub_validator: None
) -> None:
    resp = client.post("/api/backfill/validate", json={"video_id": "nosuch", "text": _reply()})
    assert resp.status_code == 404


def test_validate_glob_video_id_is_422_not_a_directory_listing(
    client: TestClient, cfg: Settings, stub_validator: None
) -> None:
    """`video_id` reaches `find_task_packet`, which used to glob on it directly
    (`*__{video_id}.md`). A caller-supplied `*` must be rejected at the request-validation boundary
    -- `ValidateRequest.video_id` now carries the same pattern `VideoIdPath` does -- rather than
    silently becoming a glob pattern that could match every packet in the directory."""
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    resp = client.post("/api/backfill/validate", json={"video_id": "*", "text": _reply()})
    assert resp.status_code == 422


def test_validate_oversized_text_is_422(
    client: TestClient, cfg: Settings, stub_validator: None
) -> None:
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    huge = "x" * 400_001
    resp = client.post("/api/backfill/validate", json={"video_id": "vaaa", "text": huge})
    assert resp.status_code == 422


# --- POST /tasks/{video_id}/result ------------------------------------------------


def test_result_happy_path(client: TestClient, cfg: Settings, stub_validator: None) -> None:
    _persona(VaultStore(cfg))
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    resp = client.post("/api/backfill/tasks/vaaa/result", json={"text": _reply()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["note_id"] == "vaaa"
    assert body["persona_slug"] == "creator-a"
    assert body["mention_count"] == 1
    assert body["summary_source"] == "external"
    assert VaultStore(cfg).has_note("creator-a", "vaaa")


def test_result_drops_invalid_symbol_and_succeeds(
    client: TestClient, cfg: Settings, stub_validator: None
) -> None:
    _persona(VaultStore(cfg))
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    reply = _reply(
        mentions=[
            {"symbol": "NVDA", "stance": "bullish", "horizon": "swing", "reasoning": "ok"},
            {"symbol": "FAKE", "stance": "bullish", "horizon": "swing", "reasoning": "mangled"},
        ]
    )
    resp = client.post("/api/backfill/tasks/vaaa/result", json={"text": reply})
    # The unvalidatable ticker is dropped, not a rejection -- the note is written with the rest.
    assert resp.status_code == 200
    body = resp.json()
    assert body["mention_count"] == 1
    assert VaultStore(cfg).has_note("creator-a", "vaaa")


def test_result_validation_failure_is_422_with_reasons_and_writes_nothing(
    client: TestClient, cfg: Settings, stub_validator: None
) -> None:
    _persona(VaultStore(cfg))
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    # A number the transcript never stated (777) makes validation fail after a clean parse.
    reply = _reply(summary="Nvidia has a price target of 777 dollars.")
    resp = client.post("/api/backfill/tasks/vaaa/result", json={"text": reply})
    assert resp.status_code == 422
    body = resp.json()
    # Top-level `detail` + `reasons`, exactly what the frontend reads.
    assert set(body) == {"detail", "reasons"}
    assert isinstance(body["detail"], str)
    assert body["reasons"]  # non-empty
    assert not VaultStore(cfg).has_note("creator-a", "vaaa")


def test_result_unparseable_is_422_with_empty_reasons(
    client: TestClient, cfg: Settings, stub_validator: None
) -> None:
    _persona(VaultStore(cfg))
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    resp = client.post("/api/backfill/tasks/vaaa/result", json={"text": "not json at all"})
    assert resp.status_code == 422
    body = resp.json()
    assert set(body) == {"detail", "reasons"}
    assert body["reasons"] == []


def test_result_duplicate_is_409(client: TestClient, cfg: Settings, stub_validator: None) -> None:
    _persona(VaultStore(cfg))
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    first = client.post("/api/backfill/tasks/vaaa/result", json={"text": _reply()})
    assert first.status_code == 200
    second = client.post("/api/backfill/tasks/vaaa/result", json={"text": _reply()})
    assert second.status_code == 409


def test_result_unknown_id_is_404(client: TestClient, cfg: Settings, stub_validator: None) -> None:
    resp = client.post("/api/backfill/tasks/nosuch/result", json={"text": _reply()})
    assert resp.status_code == 404


def test_result_oversized_text_is_422(client: TestClient, cfg: Settings, stub_validator: None) -> None:
    _persona(VaultStore(cfg))
    write_task_files([_task(video_id="vaaa")], cfg.backfill_tasks_dir, summary_lang="en")
    huge = "x" * 400_001
    resp = client.post("/api/backfill/tasks/vaaa/result", json={"text": huge})
    assert resp.status_code == 422
    assert not VaultStore(cfg).has_note("creator-a", "vaaa")
