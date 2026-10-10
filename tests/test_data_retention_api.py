"""Tests for `GET /api/data/retention` (`app.api.data_admin.data_retention`): the read-only counts
behind the Data > About panel.

**Why this file exists.** EXP-18/EXP-04 found nothing on screen tells the owner where their data
lives, whether it leaves the machine, or how long history is kept -- all of it was in `docs/`, none
of it in the product. This endpoint is the numbers half of that fix, so the tests below pin the two
things that matter most:

1. **The wire shape** -- every store the panel lists is present, with the field names the frontend
   reads (`FreshnessSource`'s own module carries the same "pin the contract" reasoning).
2. **No leak.** This route is *not* owner-only (see the module docstring), so every string value in
   the response is checked for a path separator or a literal ``"Users"`` -- the two things that would
   turn a "how much" panel into a "where exactly" panel. A count is safe; a path is not.

The test app holds only this router, the same choice `tests/test_data_freshness.py` makes and for
the same reason: a router that reaches ledger, auth, manager, personas, agentdesk and paperdesk
stores should not also have to boot every other router (and `lifespan`) to be tested.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.agentdesk.models import DeskRun
from app.agentdesk.store import RunStore
from app.agents.models import AgentBudget
from app.api import data_admin
from app.auth import store as auth_store
from app.config import Settings
from app.db import sqlite as ledger
from app.manager import models as manager_models
from app.manager import service as manager_service
from app.paperdesk import desk as paperdesk_desk
from app.personas import service as personas_service
from app.personas.models import EpisodicNote, Persona
from app.personas.store import VaultStore
from tests.conftest import make_txn, sample_account

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    """A bare app holding only this router -- `settings` redirects every store into `tmp_path`."""
    app = FastAPI()
    app.include_router(data_admin.router)
    with TestClient(app) as test_client:
        yield test_client


def _note(persona: str, note_id: str) -> EpisodicNote:
    return EpisodicNote(
        note_id=note_id,
        persona=persona,
        source_id="yt:UCtest0000000000000000",
        published=NOW,
        ingested_at=NOW,
        url=f"https://www.youtube.com/watch?v={note_id}",
        title=f"video {note_id}",
        kind="video_transcript",
        transcript_source="auto",
        lang="en",
        summary="First sentence. Second sentence.",
        themes=(),
        quotes=(),
        mentions=(),
        path="",
    )


def _persona(slug: str) -> Persona:
    return Persona(slug=slug, display_name=slug, created_at=NOW)


def _walk_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v)


# ---------------------------------------------------------------------------
# Shape + no-leak, against a completely fresh instance
# ---------------------------------------------------------------------------


class TestFreshInstance:
    def test_200_with_every_top_level_key(self, client: TestClient) -> None:
        response = client.get("/api/data/retention")

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "ledger",
            "auth",
            "manager_briefs",
            "manager_chats",
            "persona_chats",
            "persona_vault_notes",
            "desk_runs",
            "paperdesk_books",
            "i18n_cache",
            "retention_policy",
            "purge_endpoints",
        }

    def test_a_fresh_instance_reports_zero_or_empty_everywhere(self, client: TestClient) -> None:
        body = client.get("/api/data/retention").json()

        assert body["ledger"] == {"exists": False, "transactions": 0}
        assert body["auth"] == {"users": 0}
        assert body["manager_briefs"] == {"count": 0, "oldest": None, "newest": None}
        assert body["manager_chats"] == {"count": 0}
        assert body["persona_chats"] == {"count": 0}
        assert body["persona_vault_notes"] == {"count": 0}
        assert body["desk_runs"] == {
            "tradingagents": 0, "vibedesk": 0, "workflow": 0, "manager": 0,
        }
        assert body["i18n_cache"] == {"present": False}
        assert body["retention_policy"] == "manual"

    def test_paperdesk_books_counts_the_three_purposes_even_with_nothing_seeded(
        self, client: TestClient, settings: Settings
    ) -> None:
        body = client.get("/api/data/retention").json()
        assert body["paperdesk_books"]["count"] == len(paperdesk_desk.seats(settings))

    def test_purge_endpoints_are_real_delete_routes_from_manager_and_personas(
        self, client: TestClient
    ) -> None:
        body = client.get("/api/data/retention").json()
        endpoints = body["purge_endpoints"]
        assert isinstance(endpoints, list) and endpoints
        for entry in endpoints:
            assert entry.startswith("DELETE /api/manager/") or entry.startswith(
                "DELETE /api/personas/"
            )

    def test_no_string_anywhere_in_the_body_carries_a_path_or_a_username(
        self, client: TestClient
    ) -> None:
        """The hard constraint from the module docstring: this route is not owner-only, so nothing
        here may leak an absolute path or the word "Users" (a Windows home-directory segment).

        `purge_endpoints` is the one field allowed a `/`: those are generic API *route shapes*
        (`DELETE /api/personas/{slug}`), never an instantiated id or filesystem path -- checked
        separately below for the backslash/username test a real path would fail.
        """
        body = client.get("/api/data/retention").json()
        stores = {k: v for k, v in body.items() if k != "purge_endpoints"}
        for s in _walk_strings(stores):
            assert "/" not in s, s
            assert "\\" not in s, s
            assert "Users" not in s, s
        for s in body["purge_endpoints"]:
            assert "\\" not in s, s
            assert "Users" not in s, s
            assert "{" in s  # a route shape, never an instantiated id

    def test_every_count_is_a_plain_int(self, client: TestClient) -> None:
        body = client.get("/api/data/retention").json()
        assert isinstance(body["ledger"]["transactions"], int)
        assert isinstance(body["auth"]["users"], int)
        assert isinstance(body["manager_briefs"]["count"], int)
        assert isinstance(body["manager_chats"]["count"], int)
        assert isinstance(body["persona_chats"]["count"], int)
        assert isinstance(body["persona_vault_notes"]["count"], int)
        for value in body["desk_runs"].values():
            assert isinstance(value, int)
        assert isinstance(body["paperdesk_books"]["count"], int)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


class TestLedger:
    def test_transaction_count_matches_the_ledger(
        self, client: TestClient, settings: Settings
    ) -> None:
        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            ledger.upsert_account(conn, sample_account())
            # `txn.import_id` is a FOREIGN KEY onto `raw_import` -- `make_txn`'s default `import_id`
            # ("imp1") needs a matching row, the same helper `tests/test_stores.py::_import` uses.
            conn.execute(
                "INSERT OR IGNORE INTO raw_import (import_id, source_path, filename, file_sha256, "
                "content_hash, broker, account_id, adapter, adapter_version, row_count, "
                "usable_row_count, imported_at) VALUES ('imp1', 'p', 'f.csv', 'sha', 'content', "
                "'robinhood', 'rh-taxable', 'robinhood', '1', 1, 1, '2026-01-01T00:00:00Z')"
            )
            ledger.insert_transactions(
                conn, [make_txn(txn_id="a"), make_txn(txn_id="b"), make_txn(txn_id="c")]
            )

        body = client.get("/api/data/retention").json()

        assert body["ledger"] == {"exists": True, "transactions": 3}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_user_count_matches_the_auth_store(
        self, client: TestClient, settings: Settings
    ) -> None:
        auth_store.init_db(settings)
        auth_store.create_user(settings, "alice", "hash1")
        auth_store.create_user(settings, "bob", "hash2", role="member")

        body = client.get("/api/data/retention").json()

        assert body["auth"] == {"users": 2}


# ---------------------------------------------------------------------------
# Manager briefs, chats
# ---------------------------------------------------------------------------


class TestManagerBriefs:
    def test_count_and_oldest_newest_come_from_generated_at(
        self, client: TestClient, settings: Settings
    ) -> None:
        directory = manager_models.manager_dir(settings) / "briefs"
        directory.mkdir(parents=True)
        (directory / "b1.json").write_text(
            json.dumps({"generated_at": "2026-08-01T09:45:00+00:00"}), encoding="utf-8"
        )
        (directory / "b2.json").write_text(
            json.dumps({"generated_at": "2026-09-10T09:45:00+00:00"}), encoding="utf-8"
        )

        body = client.get("/api/data/retention").json()

        assert body["manager_briefs"] == {
            "count": 2,
            "oldest": "2026-08-01T09:45:00+00:00",
            "newest": "2026-09-10T09:45:00+00:00",
        }

    def test_a_corrupt_brief_file_costs_one_entry_not_the_whole_count(
        self, client: TestClient, settings: Settings
    ) -> None:
        directory = manager_models.manager_dir(settings) / "briefs"
        directory.mkdir(parents=True)
        (directory / "good.json").write_text(
            json.dumps({"generated_at": "2026-09-01T00:00:00+00:00"}), encoding="utf-8"
        )
        (directory / "bad.json").write_text("{not json", encoding="utf-8")

        body = client.get("/api/data/retention").json()

        assert body["manager_briefs"]["count"] == 1


class TestManagerChats:
    def test_count_matches_created_threads(self, client: TestClient, settings: Settings) -> None:
        manager_service.create_chat(settings)
        manager_service.create_chat(settings)

        body = client.get("/api/data/retention").json()

        assert body["manager_chats"] == {"count": 2}


# ---------------------------------------------------------------------------
# Personas: vault notes and chat threads
# ---------------------------------------------------------------------------


class TestPersonas:
    def test_notes_and_chats_are_summed_across_every_persona(
        self, client: TestClient, settings: Settings
    ) -> None:
        store = VaultStore(settings)
        store.save_persona(_persona("creatorb"))
        store.save_persona(_persona("creator-a"))
        store.write_note(_note("creatorb", "n1"))
        store.write_note(_note("creatorb", "n2"))
        store.write_note(_note("creator-a", "n3"))
        personas_service.create_chat(settings, "creatorb")
        personas_service.create_chat(settings, "creator-a")
        personas_service.create_chat(settings, "creator-a")

        body = client.get("/api/data/retention").json()

        assert body["persona_vault_notes"] == {"count": 3}
        assert body["persona_chats"] == {"count": 3}


# ---------------------------------------------------------------------------
# Desk runs, per kind
# ---------------------------------------------------------------------------


class TestDeskRuns:
    def test_counts_are_per_kind_and_do_not_cross_contaminate(
        self, client: TestClient, settings: Settings
    ) -> None:
        budget = AgentBudget(cap_usd=Decimal("5.00"))
        RunStore(settings, "tradingagents").save(
            DeskRun(run_id="r1", kind="tradingagents", created_at=NOW, budget=budget)
        )
        RunStore(settings, "tradingagents").save(
            DeskRun(run_id="r2", kind="tradingagents", created_at=NOW, budget=budget)
        )
        RunStore(settings, "vibedesk").save(
            DeskRun(run_id="r3", kind="vibedesk", created_at=NOW, budget=budget)
        )

        body = client.get("/api/data/retention").json()

        assert body["desk_runs"] == {
            "tradingagents": 2, "vibedesk": 1, "workflow": 0, "manager": 0,
        }

    def test_a_directory_without_a_run_file_is_not_counted(
        self, client: TestClient, settings: Settings
    ) -> None:
        from app.agentdesk.models import runs_dir

        stray = runs_dir(settings, "workflow") / "not-a-run"
        stray.mkdir(parents=True)

        body = client.get("/api/data/retention").json()

        assert body["desk_runs"]["workflow"] == 0


# ---------------------------------------------------------------------------
# i18n cache
# ---------------------------------------------------------------------------


class TestI18nCache:
    def test_present_flips_to_true_once_the_cache_directory_exists(
        self, client: TestClient, settings: Settings
    ) -> None:
        assert client.get("/api/data/retention").json()["i18n_cache"] == {"present": False}

        (settings.data_dir / "i18n_cache").mkdir(parents=True)

        assert client.get("/api/data/retention").json()["i18n_cache"] == {"present": True}
