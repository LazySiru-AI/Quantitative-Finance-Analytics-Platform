"""Tests for `app.agents.spend` (the aggregate rolling-window spend ledger) and its wiring into
`POST /api/i18n/translate` (`app.api.i18n`) and the persona routes (`app.personas.service`).

`app.agents.spend.LEDGER` is a module-level singleton, so every test that touches it resets it both
before and after via the `_clean_ledger` autouse fixture -- otherwise one test's recorded spend would
leak into the next.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents import spend as spend_module
from app.agents.spend import LEDGER, SpendCapExceeded, SpendLedger
from app.api import i18n as i18n_router
from app.config import Settings, get_settings
from app.i18n import narrative as narrative_module
from app.personas import service
from app.personas.models import EpisodicNote, FollowedSource, Persona
from app.personas.store import VaultStore

_UTC = dt.UTC


@pytest.fixture(autouse=True)
def _clean_ledger() -> Iterator[None]:
    LEDGER.reset()
    yield
    LEDGER.reset()


# ---------------------------------------------------------------------------
# SpendLedger arithmetic
# ---------------------------------------------------------------------------


class TestLedgerArithmetic:
    def test_record_accumulates_into_spent_last_24h(self) -> None:
        ledger = SpendLedger()
        ledger.record(Decimal("1.50"), now=1000.0)
        ledger.record(Decimal("2.25"), now=1001.0)

        assert ledger.spent_last_24h(now=1002.0) == Decimal("3.75")

    def test_no_entries_means_zero_spend(self) -> None:
        ledger = SpendLedger()
        assert ledger.spent_last_24h(now=0.0) == Decimal(0)

    def test_entries_older_than_the_window_are_pruned(self) -> None:
        ledger = SpendLedger(window_seconds=100)
        ledger.record(Decimal("5.00"), now=0.0)

        # Still inside the window.
        assert ledger.spent_last_24h(now=99.0) == Decimal("5.00")
        # Now outside it.
        assert ledger.spent_last_24h(now=101.0) == Decimal(0)

    def test_reset_clears_all_state(self) -> None:
        ledger = SpendLedger()
        ledger.record(Decimal("9.99"), now=0.0)
        ledger.reset()
        assert ledger.spent_last_24h(now=0.0) == Decimal(0)

    def test_default_window_is_24_hours(self) -> None:
        assert spend_module.WINDOW_SECONDS == 24 * 60 * 60


# ---------------------------------------------------------------------------
# SpendLedger.check
# ---------------------------------------------------------------------------


class TestLedgerCheck:
    def test_check_does_not_raise_when_spend_is_below_cap(self) -> None:
        ledger = SpendLedger()
        ledger.record(Decimal("1.00"), now=0.0)
        ledger.check(Decimal("5.00"), now=1.0)  # must not raise

    def test_check_raises_when_spend_is_at_the_cap(self) -> None:
        ledger = SpendLedger()
        ledger.record(Decimal("5.00"), now=0.0)
        with pytest.raises(SpendCapExceeded) as exc_info:
            ledger.check(Decimal("5.00"), now=1.0)
        assert exc_info.value.spent_usd == Decimal("5.00")
        assert exc_info.value.cap_usd == Decimal("5.00")

    def test_check_raises_when_spend_exceeds_the_cap(self) -> None:
        ledger = SpendLedger()
        ledger.record(Decimal("6.00"), now=0.0)
        with pytest.raises(SpendCapExceeded):
            ledger.check(Decimal("5.00"), now=1.0)

    def test_zero_cap_means_unlimited(self) -> None:
        ledger = SpendLedger()
        ledger.record(Decimal("1000.00"), now=0.0)
        ledger.check(Decimal(0), now=1.0)  # must not raise

    def test_negative_cap_also_means_unlimited(self) -> None:
        ledger = SpendLedger()
        ledger.record(Decimal("1000.00"), now=0.0)
        ledger.check(Decimal("-1"), now=1.0)  # must not raise

    def test_retry_after_seconds_reflects_when_the_oldest_entry_ages_out(self) -> None:
        ledger = SpendLedger(window_seconds=100)
        ledger.record(Decimal("5.00"), now=0.0)
        with pytest.raises(SpendCapExceeded) as exc_info:
            ledger.check(Decimal("5.00"), now=40.0)
        # Window is 100s, oldest entry at t=0, checked at t=40 -> ~60s left.
        assert exc_info.value.retry_after_seconds == pytest.approx(60, abs=1)

    def test_spend_that_ages_out_of_the_window_no_longer_trips_the_cap(self) -> None:
        ledger = SpendLedger(window_seconds=100)
        ledger.record(Decimal("5.00"), now=0.0)
        ledger.check(Decimal("5.00"), now=101.0)  # aged out -- must not raise


# ---------------------------------------------------------------------------
# POST /api/i18n/translate -- aggregate cap -> 429
# ---------------------------------------------------------------------------


def _i18n_app(settings_obj: Settings) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(i18n_router.router)
    fastapi_app.dependency_overrides[get_settings] = lambda: settings_obj
    return fastapi_app


class TestTranslateRouteSpendCap:
    def test_translate_returns_429_once_the_aggregate_cap_is_already_spent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        settings_on = Settings(
            repo_root=tmp_path,
            data_dir=tmp_path / "data",
            store_dir=tmp_path / "store",
            cache_dir=tmp_path / "cache",
            translate_narratives=True,
            translate_budget_usd=Decimal("2.00"),
            model_spend_daily_cap_usd=Decimal("1.00"),
        )
        # The aggregate ledger is already past the cap from some earlier, unrelated call.
        LEDGER.record(Decimal("1.00"))

        def fail_if_called(**kwargs: object) -> object:
            raise AssertionError("call_structured must not be called once the spend cap is hit")

        monkeypatch.setattr(narrative_module, "call_structured", fail_if_called)

        client = TestClient(_i18n_app(settings_on))
        response = client.post(
            "/api/i18n/translate",
            json={"locale": "ko", "texts": ["A brand-new, never-cached sentence."]},
        )

        assert response.status_code == 429
        body = response.json()
        assert body["detail"] == "spend_cap"
        assert body["spent_usd"] == "1.00"
        assert body["cap_usd"] == "1.00"
        assert "retry_after_seconds" in body

    def test_translate_succeeds_when_under_the_aggregate_cap(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        settings_on = Settings(
            repo_root=tmp_path,
            data_dir=tmp_path / "data",
            store_dir=tmp_path / "store",
            cache_dir=tmp_path / "cache",
            translate_narratives=True,
            translate_budget_usd=Decimal("2.00"),
            model_spend_daily_cap_usd=Decimal("25.00"),
        )

        monkeypatch.setattr(
            i18n_router,
            "translate_texts",
            lambda texts, *, locale, settings: ["번역됨" for _ in texts],
        )

        client = TestClient(_i18n_app(settings_on))
        response = client.post(
            "/api/i18n/translate", json={"locale": "ko", "texts": ["Hello there."]}
        )

        assert response.status_code == 200
        assert response.json() == {"results": ["번역됨"]}

    def test_a_batch_that_is_entirely_cache_hits_is_never_rejected_by_the_cap(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        settings_on = Settings(
            repo_root=tmp_path,
            data_dir=tmp_path / "data",
            store_dir=tmp_path / "store",
            cache_dir=tmp_path / "cache",
            translate_narratives=True,
            translate_budget_usd=Decimal("2.00"),
            model_spend_daily_cap_usd=Decimal("1.00"),
        )
        LEDGER.record(Decimal("1.00"))  # already at the cap

        monkeypatch.setattr(
            narrative_module,
            "get_cached",
            lambda text, *, locale, data_dir: "cached-value",
        )

        def fail_if_called(**kwargs: object) -> object:
            raise AssertionError("call_structured must not be called for a cache hit")

        monkeypatch.setattr(narrative_module, "call_structured", fail_if_called)

        results = narrative_module.translate_texts(
            ["Already cached."], locale="ko", settings=settings_on
        )

        assert results == ["cached-value"]


class TestTranslateTextLengthLimit:
    def test_a_string_over_4000_characters_is_rejected_with_422(self, tmp_path: Path) -> None:
        settings_off = Settings(
            repo_root=tmp_path,
            data_dir=tmp_path / "data",
            store_dir=tmp_path / "store",
            cache_dir=tmp_path / "cache",
            translate_narratives=False,
        )
        client = TestClient(_i18n_app(settings_off))

        response = client.post(
            "/api/i18n/translate", json={"locale": "ko", "texts": ["x" * 4001]}
        )

        assert response.status_code == 422

    def test_a_string_at_exactly_4000_characters_is_accepted(self, tmp_path: Path) -> None:
        settings_off = Settings(
            repo_root=tmp_path,
            data_dir=tmp_path / "data",
            store_dir=tmp_path / "store",
            cache_dir=tmp_path / "cache",
            translate_narratives=False,
        )
        client = TestClient(_i18n_app(settings_off))

        response = client.post(
            "/api/i18n/translate", json={"locale": "ko", "texts": ["x" * 4000]}
        )

        assert response.status_code == 200
        assert response.json() == {"results": [None]}  # flag off -- a true no-op


# ---------------------------------------------------------------------------
# Persona service routes -- aggregate cap raises SpendCapExceeded
# ---------------------------------------------------------------------------


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
                added_at=dt.datetime(2026, 1, 1, tzinfo=_UTC),
            ),
        ),
        created_at=dt.datetime(2026, 1, 1, tzinfo=_UTC),
    )
    store.save_persona(persona)
    return persona


def _write_note(store: VaultStore, *, slug: str, note_id: str = "n1") -> None:
    store.write_note(
        EpisodicNote(
            note_id=note_id,
            persona=slug,
            source_id="yt:UCabc",
            published=dt.datetime(2026, 1, 1, tzinfo=_UTC),
            ingested_at=dt.datetime(2026, 1, 1, tzinfo=_UTC),
            url=f"https://www.youtube.com/watch?v={note_id}",
            title="A video",
            kind="video_transcript",
            transcript_source="auto",
            lang="en",
            summary="A summary.",
            themes=(),
            quotes=(),
            mentions=(),
            path=f"notes/{note_id}.md",
            degraded=False,
        ),
        transcript_text="transcript",
    )


class TestPersonaAskSpendCap:
    def test_ask_raises_spend_cap_exceeded_without_calling_the_model(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = VaultStore(settings)
        _persona(store)
        _write_note(store, slug="creator-a")

        capped_settings = settings.model_copy(
            update={"model_spend_daily_cap_usd": Decimal("1.00")}
        )
        LEDGER.record(Decimal("1.00"))  # already at the cap

        def fail_if_called(**kwargs: object) -> object:
            raise AssertionError("ask_persona must not be called once the spend cap is hit")

        from app.personas import ask as ask_module

        monkeypatch.setattr(ask_module, "run_grounded", fail_if_called)

        with pytest.raises(SpendCapExceeded):
            service.ask(
                capped_settings, "creator-a", question="What do you think of NVDA?", symbol=None
            )

    def test_ask_succeeds_when_under_the_aggregate_cap(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = VaultStore(settings)
        _persona(store)
        _write_note(store, slug="creator-a")

        uncapped_settings = settings.model_copy(
            update={"model_spend_daily_cap_usd": Decimal("25.00")}
        )

        from app.agentdesk.grounding import GroundedResult
        from app.agentdesk.models import GroundingVerdict
        from app.agents.models import AgentBudget, AgentCall
        from app.personas import ask as ask_module

        def fake_run_grounded(**kwargs: object) -> GroundedResult[ask_module._AnswerDraft]:
            budget: AgentBudget = kwargs["budget"]  # type: ignore[assignment]
            call = AgentCall(
                call_id="call-1", role="swarm_worker", model="claude-haiku-4-5-20251001",
                created_at=dt.datetime.now(_UTC), system="s", user="u", raw_response="r",
                cost_usd=Decimal("0.01"),
            )
            new_budget = AgentBudget(
                cap_usd=budget.cap_usd, spent_usd=budget.spent_usd + Decimal("0.01"),
                calls=budget.calls + 1,
            )
            draft = ask_module._AnswerDraft(answer="They'd say buy.", citations=(), stance=None)
            return GroundedResult(
                value=draft, verdict=GroundingVerdict(ok=True, degraded=False, attempts=1),
                calls=(call,), budget=new_budget,
            )

        monkeypatch.setattr(ask_module, "run_grounded", fake_run_grounded)

        result = service.ask(
            uncapped_settings, "creator-a", question="What do you think of NVDA?", symbol=None
        )
        assert result.answer == "They'd say buy."


class TestPersonaStartIngestSpendCap:
    def test_start_ingest_raises_spend_cap_exceeded_before_spawning_the_job(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store = VaultStore(settings)
        _persona(store)

        from app.personas import jobs as jobs_module
        from app.personas.sources import youtube as youtube_mod
        from app.personas.sources.base import VideoRef

        monkeypatch.setattr(
            youtube_mod,
            "list_videos",
            lambda key, *, limit: [
                VideoRef(
                    video_id="v1", title="t", url="https://www.youtube.com/watch?v=v1",
                    duration_s=None, published=None,
                )
            ],
        )

        # A fresh registry, isolated from the process-wide singleton and from any other test's
        # state -- see `tests/test_personas_jobs.py`'s own docstring for why every test does this
        # rather than touching `jobs_module.registry()` directly.
        fresh_registry = jobs_module.IngestRegistry()
        monkeypatch.setattr(jobs_module, "registry", lambda: fresh_registry)

        capped_settings = settings.model_copy(
            update={"model_spend_daily_cap_usd": Decimal("1.00")}
        )
        LEDGER.record(Decimal("1.00"))  # already at the cap

        with pytest.raises(SpendCapExceeded):
            service.start_ingest(
                capped_settings, "creator-a", limit=None, video_urls=None, drop=None
            )

        # The job was never scheduled -- the cap check ran before `registry.start` was reached.
        assert fresh_registry.active("creator-a") is None


# ---------------------------------------------------------------------------
# The app-level handler `app.main` registers for the persona routes: a `SpendCapExceeded` escaping
# `app.personas.service` must reach the client as the same 429 body the translate route builds by
# hand, not as a 500. Pinned through the real `app.main.app` because that registration line is the
# one piece of this feature that lives outside `app.agents.spend*` and could be dropped in a refactor.
# ---------------------------------------------------------------------------


def test_persona_route_maps_spend_cap_to_429(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.main import app

    def _over_cap(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise SpendCapExceeded(Decimal("25.50"), Decimal("25"), retry_after_seconds=1234)

    # `app.api.personas` calls `service.ask(...)` through the module attribute at request time.
    monkeypatch.setattr(service, "ask", _over_cap)

    with TestClient(app) as client:
        resp = client.post("/api/personas/anyone/ask", json={"question": "what now?"})

    assert resp.status_code == 429
    body = resp.json()
    assert body["detail"] == "spend_cap"
    assert Decimal(str(body["spent_usd"])) == Decimal("25.50")
    assert Decimal(str(body["cap_usd"])) == Decimal("25")
    assert body["retry_after_seconds"] == 1234
