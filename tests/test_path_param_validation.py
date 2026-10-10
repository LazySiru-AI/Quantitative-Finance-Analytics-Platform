"""Pin the path-parameter allow-lists the 2026-09-07 security audit added.

Two read routes joined a bare `str` path parameter straight onto a directory: the dossier route
(`genome_id` -> `data/loop/generated/{id}.json` and each library tier) and two competition routes
(`round_id` -> `data/rounds/{id}/results`). A URL segment cannot carry `/`, but on Windows pathlib
treats a backslash as a separator, so `..%5C..%5Cx` matched the route and resolved *outside* the
library directory. These tests hold the boundary at the HTTP layer (a 422 before any handler runs)
and, for the dossier, at the filesystem join itself.

Auth is off for this module (the conftest `settings` fixture), so a 4xx here is validation, not
the gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.evolution import dossier as dossier_module
from app.main import app

#: Encoded forms a browser or curl would actually send. `%2F` never reaches the handler on any
#: platform (Starlette will not match it into a single segment); `%5C` did, on Windows, until the
#: pattern existed. `..` alone is a legal single segment everywhere.
TRAVERSAL_IDS = ["..", "..%5C..%5Cx", "..%2F..%2Fx", ".hidden", "a.b", "a%00b", "a%20b"]


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(app)


@pytest.mark.parametrize("bad", TRAVERSAL_IDS)
def test_dossier_rejects_ids_with_separators_or_dots(client: TestClient, bad: str) -> None:
    r = client.get(f"/api/competition/loop/candidates/{bad}/dossier")
    # 422 is the pattern refusing the segment; 404 is Starlette not matching the route at all
    # (the `%2F` case). Either way the handler -- and the filesystem join -- is never reached.
    assert r.status_code in (404, 422), r.text
    assert r.status_code != 200


@pytest.mark.parametrize("good", ["g001-24d55e81ee86", "B-momentum", "spy-schd-agg-gld-bil-atr-tilt"])
def test_dossier_still_routes_well_formed_ids(client: TestClient, good: str) -> None:
    r = client.get(f"/api/competition/loop/candidates/{good}/dossier")
    # Not 422: the pattern must admit every real id shape. 404 (no such card in the tmp tree) or 200
    # are both fine here; the shape of a dossier is another test file's job.
    assert r.status_code != 422, r.text


@pytest.mark.parametrize("bad", ["..", "..%5C..%5Cx", "R1-2026-08", "r1_2026", "a.b"])
def test_competition_round_routes_reject_malformed_round_ids(client: TestClient, bad: str) -> None:
    assert client.get(f"/api/competition/rounds/{bad}/leaderboard").status_code in (404, 422)
    assert client.get(f"/api/competition/rounds/{bad}/agents/r1-A-rotation").status_code in (404, 422)


def test_competition_round_routes_still_admit_real_round_ids(client: TestClient) -> None:
    r = client.get("/api/competition/rounds/r1-2026-08/leaderboard")
    assert r.status_code != 422, r.text


def test_card_path_under_never_escapes_its_root(tmp_path: Path) -> None:
    """The defence-in-depth half: whatever the caller, `_find_card`'s join stays inside its root."""
    root = tmp_path / "library" / "base"
    root.mkdir(parents=True)
    (root / "ok.json").write_text("{}", encoding="utf-8")
    outside = tmp_path / "library" / "secret.json"
    outside.write_text('{"api_key": "x"}', encoding="utf-8")

    assert dossier_module._card_path_under(root, "ok") == (root / "ok.json").resolve()
    for escape in ("..\\secret", "../secret", "sub/../../secret", "..\\..\\library\\secret"):
        assert dossier_module._card_path_under(root, escape) is None, escape
    # A bare `..` is *not* traversal once `.json` is appended -- `...json` is an ordinary (absent)
    # filename inside the root -- so it resolves to a path under root and simply will not exist.
    bare = dossier_module._card_path_under(root, "..")
    assert bare is not None and bare.parent == root.resolve() and not bare.exists()


def test_find_card_ignores_a_traversing_id(tmp_path: Path, settings: Settings) -> None:
    """End to end through `_find_card` against a real sibling file: the old code returned it."""
    from app.evolution.models import generated_tier_dir

    generated = generated_tier_dir(settings)
    generated.mkdir(parents=True, exist_ok=True)
    bait = generated.parent / "bait.json"
    bait.write_text('{"universe": ["ZZZ"], "purpose": "trading"}', encoding="utf-8")

    assert dossier_module._find_card("..\\bait", settings=settings) is None
    assert dossier_module._find_card("../bait", settings=settings) is None
