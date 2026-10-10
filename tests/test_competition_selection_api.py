"""`GET /api/competition/rounds/{round_id}/selection`.

The router is thin over `app.tournament.selection`, which has its own tests for the rule itself
(`tests/test_tournament_selection.py`). What is left to cover here is the part the router actually
decides: which "no selection" cases become a 404, and that nothing is silently reshaped on the way
out.

**The 404 cases are the point of this file.** `selection.select` does not raise for a round it cannot
find -- it returns a degenerate result with an empty ranking and `ladder-qld-schd` still seated,
because that card is seated outside the competition and survives having nothing to compete against.
Served unguarded that is a 200 carrying a one-card roster for a round that does not exist, which is a
fabricated answer wearing the shape of a real one. Two of the tests below exist specifically to keep
that from coming back.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import competition_selection
from app.config import get_settings
from tests.conftest import requires_real_store


@pytest.fixture
def app() -> FastAPI:
    """Only the router under test is mounted, matching `tests/test_competition_api.py`.

    Mounting the whole application would make a failure here ambiguous between this router and any
    other startup work `app.main` does."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(competition_selection.router)
    return fastapi_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)

SELECTION = "/api/competition/rounds/{round_id}/selection"

#: The one round with a live out-of-sample matrix on disk. Skipped rather than failed when absent:
#: the round directories are data, not fixtures, and a checkout without them should not report a
#: broken router.
LIVE_ROUND = "r11-2026-08"


def _has_live_matrix(round_id: str) -> bool:
    return (get_settings().rounds_dir / round_id / "results" / "live-1").is_dir()


class TestMissingSelection:
    """A round with no live matrix is a 404, not a 200 with a roster in it."""

    def test_unknown_round_is_404_not_a_fabricated_roster(self, client: TestClient) -> None:
        """The regression this router's existence check was written for.

        `selection.select("does-not-exist")` returns a result carrying one seat. If that reached the
        wire, the Selection view would render a roster for a round nobody ever ran -- and it would
        look exactly like a real one, because every field would be populated.
        """
        response = client.get(SELECTION.format(round_id="does-not-exist"))
        assert response.status_code == 404
        assert "does-not-exist" in response.json()["detail"]

    def test_a_real_round_without_a_live_matrix_is_also_404(self, client: TestClient) -> None:
        """Round 1 exists on disk and predates the live matrix entirely.

        The current rule ranks on the live out-of-sample record, so there is genuinely nothing to
        rank -- which is the same answer a reader needs as for an unknown round, and is deliberately
        not split into a different status.
        """
        response = client.get(SELECTION.format(round_id="r1-2026-08"))
        assert response.status_code == 404
        assert "live-1" in response.json()["detail"]

    def test_a_path_traversal_attempt_is_rejected_by_the_pattern(self, client: TestClient) -> None:
        """`round_id` is interpolated into a filesystem path, so the pattern is a boundary, not
        cosmetics. FastAPI rejects it before any handler code runs."""
        response = client.get("/api/competition/rounds/..%2F..%2Fetc/selection")
        assert response.status_code in {404, 422}


@requires_real_store
class TestSelectionPayload:
    """The shape the Selection view is built against."""

    @pytest.fixture(autouse=True)
    def _skip_without_data(self) -> None:
        if not _has_live_matrix(LIVE_ROUND):
            pytest.skip(f"{LIVE_ROUND} has no live matrix in this checkout")

    def test_returns_the_gates_ranking_seats_and_notes(self, client: TestClient) -> None:
        response = client.get(SELECTION.format(round_id=LIVE_ROUND))
        assert response.status_code == 200
        body = response.json()

        assert body["round_id"] == LIVE_ROUND
        assert body["rule_version"]
        assert set(body["gates"]) >= {"A", "L", "C"}
        assert body["ranking"], "a round with a live matrix must rank something"
        assert body["seats"]

    def test_every_seat_says_what_seated_it(self, client: TestClient) -> None:
        """`seated_by` distinguishes a card that won its seat on the rule from one seated outside the
        competition or against the rule. A reader who cannot tell those apart is being told the
        evidence is stronger than it is."""
        body = client.get(SELECTION.format(round_id=LIVE_ROUND)).json()
        for seat in body["seats"]:
            assert seat["seated_by"] in {"rule", "outside-competition", "owner-override"}
            assert seat["note"], f"{seat['agent_id']} has no note explaining its seat"

    def test_the_standing_caveats_travel_with_the_roster(self, client: TestClient) -> None:
        """`notes` is part of the payload rather than frontend copy, because the limitations are
        properties of the evidence and not of the page. A roster served without them overstates what
        it establishes -- so their absence is a failure here, not a cosmetic gap."""
        notes = client.get(SELECTION.format(round_id=LIVE_ROUND)).json()["notes"]
        assert notes
        joined = " ".join(notes).lower()
        assert "one market environment" in joined
        assert "127 sessions" in joined
        assert "no live record" in joined

    def test_a_ranked_but_unseated_card_is_still_reported(self, client: TestClient) -> None:
        """The ranking carries cards the seating walk rejected, with a note saying why. Dropping them
        would hide the rule's exclusions, which are the part worth auditing."""
        body = client.get(SELECTION.format(round_id=LIVE_ROUND)).json()
        unseated = [row for row in body["ranking"] if not row["seated"]]
        assert unseated, "round 11's field has cards the distinctness walk rejects"
        for row in unseated:
            assert row["note"]
