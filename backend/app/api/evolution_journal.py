"""HTTP surface for the rolling digest journal: `GET /api/competition/loop/journal`.

A router of its own, deliberately separate from `app.api.evolution` -- see `SPEC.md`'s workstream
split for why (that file has its own concurrent editors) and `app.evolution.digest`'s own module
docstring for what a digest is and why it exists. This file is as thin as `app.api.evolution` already
is over `app.evolution.loop`: the one real decision here (newest-first pagination, reading
`gen{N:04d}/DIGEST.md` files directly rather than re-parsing `JOURNAL.md`) is made by
`app.evolution.digest.read_journal_entries`, not by this router.

**Never 404s.** A loop that has never written a single digest yet (a fresh checkout, or a loop that
has not reached its first `write_digest` call) is not an error state for this endpoint any more than
it is for `GET /api/competition/loop/generations` -- both answer `{"total": 0, ...}` for an absent or
empty tree. See `app.evolution.digest.read_journal_entries`'s own docstring for the matching rule
`app.evolution.history.list_generations` already established.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.config import Settings as _Settings
from app.evolution import digest
from app.evolution import loop as loop_module

router = APIRouter(prefix="/api/competition/loop", tags=["competition"])


def _settings() -> _Settings:
    """`loop_module.get_settings()`, accessed as an attribute rather than imported directly --
    the identical pattern `app.api.evolution._settings` uses, and for the identical reason: the test
    client fixture patches `loop_module.get_settings` (a `tmp_path`-backed `Settings`), and reading it
    off `loop_module` at call time, not via a top-level `from app.config import get_settings` bound at
    import time, is what lets this router see that patch too.
    """
    return loop_module.get_settings()  # type: ignore[attr-defined]


class JournalEntryResponse(BaseModel):
    generation: int
    markdown: str


class JournalResponse(BaseModel):
    """`GET /journal`'s body: `SPEC.md`'s `{"total": int, "entries": [{"generation", "markdown"}]}`
    exactly, `total` counting every generation with a `DIGEST.md` on disk (not just the page
    returned) -- the same `total`-is-the-full-filtered-count convention
    `app.evolution.history.GenerationsListResponse.total` already uses."""

    total: int
    entries: list[JournalEntryResponse]


@router.get("/journal", response_model=JournalResponse)
def get_journal(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JournalResponse:
    """The newest `limit` digests, newest generation first, skipping `offset`.

    Reads `gen{N:04d}/DIGEST.md` files written by `app.evolution.digest.write_digest` (backfilled, for
    every existing generation, by `tools/backfill_digests.py`, and -- per this workstream's own report
    to the orchestrator -- meant to be called by `app.evolution.loop` once per generation going
    forward). A generation with no `DIGEST.md` yet (not backfilled, or written before this feature
    existed and not yet caught up) is simply absent from `entries`, not a `null` placeholder or a
    partial row -- there is nothing partial to show for it.
    """
    settings = _settings()
    entries, total = digest.read_journal_entries(settings, limit=limit, offset=offset)
    return JournalResponse(
        total=total,
        entries=[
            JournalEntryResponse(generation=entry.generation, markdown=entry.markdown)
            for entry in entries
        ],
    )
