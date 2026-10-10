"""HTTP surface for one route: `GET /api/competition/loop/candidates/{genome_id}/dossier`.

A separate router file, not a route added to `app.api.evolution`, because that module is owned by a
different, concurrently-running session for this same task (see this programme's own brief) -- adding
a route there would mean two sessions editing the same file. FastAPI has no trouble with two
`APIRouter`s sharing one `prefix` string, as long as their route paths don't collide; this router's
only path (`/candidates/{genome_id}/dossier`) does not exist anywhere in `app.api.evolution` today.

Thin on purpose, the same way every other router in `app.api` is thin over its own package: every
real decision -- finding the card, composing plain English from its rule, computing field context,
evaluating every caution -- lives in `app.evolution.dossier.compose_dossier`. This router's whole job
is resolving `Settings` and turning `None` into the documented `404`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path

from app.config import Settings as _Settings
from app.evolution import loop as loop_module
from app.evolution.dossier import Dossier, compose_dossier

router = APIRouter(prefix="/api/competition/loop", tags=["competition"])

#: A genome id is a filename stem -- `g001-24d55e81ee86` for a generated card, or a library card's
#: stem such as `spy-schd-agg-gld-bil-atr-tilt` once promoted -- and `app.evolution.dossier._find_card`
#: joins it straight onto a directory. Constrained here, at the HTTP boundary, so a value carrying a
#: path separator or `..` never reaches that join: a bare `str` let `..%5C..%5Cx` match this route and
#: walk out of the library directory on Windows, where pathlib treats a backslash as a separator
#: (2026-09-07 security audit). No dots at all, since no real id has one and excluding them rules
#: out `..` by construction rather than by a second rule.
GenomeIdPath = Annotated[
    str, Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
]


def _settings() -> _Settings:
    """`loop_module.get_settings()`, read at call time rather than imported directly.

    Mirrors `app.api.evolution._settings` exactly, and for the identical reason stated in that
    function's own docstring: `tests/test_api_evolution.py`'s `client` fixture monkeypatches
    `app.evolution.loop.get_settings` (not `app.config.get_settings`) before building the
    `TestClient`, so a route that wants to see the same patched, `tmp_path`-backed `Settings` every
    other route in this loop's HTTP surface sees has to read it off `loop_module` at request time too.
    Duplicated rather than imported from `app.api.evolution` because that module is a sibling file
    under concurrent edit by a different session for this same task -- see this module's own docstring.
    """
    return loop_module.get_settings()  # type: ignore[attr-defined]


@router.get("/candidates/{genome_id}/dossier", response_model=Dossier)
def get_dossier(genome_id: GenomeIdPath) -> Dossier:
    """Everything needed to shelve or reject `genome_id`: plain-English rule, origin, every
    generation's evidence, field-wide context (so a card's own number is never shown without what the
    same number looks like across the whole search), every caution that fires, and ticker overlap
    against the current shelf. See `app.evolution.dossier`'s module docstring for the full contract.

    `404` when no card exists for `genome_id` anywhere this loop keeps one -- neither a not-yet-
    promoted genome under `data/loop/generated/` nor any promoted library tier. Never `500`s for a
    malformed or missing supporting file (a corrupt `PLAN.md`, an unreadable sibling card for the
    overlap/label checks): `compose_dossier` and everything it calls degrade those to "no evidence"
    rather than raising, so one bad file never takes the whole dossier down -- see
    `app.evolution.dossier`'s own docstring for the house rule this follows.
    """
    dossier = compose_dossier(genome_id, settings=_settings())
    if dossier is None:
        raise HTTPException(status_code=404, detail=f"no such candidate: {genome_id!r}")
    return dossier
