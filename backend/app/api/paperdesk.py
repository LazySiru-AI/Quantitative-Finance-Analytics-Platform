"""HTTP surface for the live paper desk: current balances, holdings, decisions and trade history
for ``B-momentum`` and ``C-trend``.

Thin on purpose, matching ``app.api.macro``'s convention: every real decision -- where the cards
live, how the mandate is built, how the trading window is derived from the store, how a run is
cached, how a fee-adjusted trade turns into a holding or a decision row -- is made in
:mod:`app.paperdesk.desk` and :mod:`app.paperdesk.models`. This router only wires four routes to
that module's entry points, translating :class:`~app.paperdesk.desk.InceptionRejected` into a `422`
the way every other router in this application maps a domain exception onto the right HTTP status
(see e.g. ``app.api.competition_jobs``). Every route returns the same shape
(:class:`~app.paperdesk.models.PaperDeskState`), by design: a client can render any response with the
same code.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.paperdesk import desk, fetch
from app.paperdesk.models import InceptionUpdateRequest, PaperDeskState

router = APIRouter(prefix="/api/paperdesk", tags=["paperdesk"])


@router.get("/state", response_model=PaperDeskState)
def get_state() -> PaperDeskState:
    """The current paper desk: both strategies' balances, holdings, decisions and trade history as
    of the most recent stored session.

    Served from :mod:`app.paperdesk.desk`'s in-process cache when the trading window has not moved
    since the last call -- a page load never re-runs either book. See that module's docstring for
    exactly what "as of" means here (never live intraday data) and what the cache key is.
    """
    return desk.state()


@router.post("/refresh", response_model=PaperDeskState)
def post_refresh(fetch_data: bool = Query(False, alias="fetch")) -> PaperDeskState:
    """Optionally pull fresh bars, then bust the cache and recompute every book.

    Same response shape as :func:`get_state`, with one field this route alone ever populates:
    ``fetch`` carries :class:`~app.paperdesk.models.FetchSummary` when ``fetch=true`` and stays
    ``None`` otherwise.

    **``fetch=true`` is what the page's button sends, and it is the whole point of this route.**
    Without it this endpoint recomputes off whatever the store already holds -- correct, and no help
    at all to a reader looking at a header that says the mark is three days stale, since the
    recompute produces the identical figures off the identical bars. With it,
    :func:`app.paperdesk.fetch.fetch_all` first syncs daily bars for every symbol on every book's
    roster plus the benchmarks (see that module for pacing, per-symbol failure handling and why
    there is no staleness gate), and only then is the cache dropped -- so the recompute below reads
    bars that are new rather than the ones it just discarded.

    **It defaults to ``False``, not ``True``.** A fetch is forty paced network round trips; making
    that the default would mean any caller who typed ``POST /api/paperdesk/refresh`` for its
    documented cache-busting behaviour -- including this repository's own tests -- silently started
    reaching for the network instead. The network call is opted into by the caller that wants it.

    A fetch never fails this request. Every per-symbol failure is recorded in the returned summary's
    ``failures`` and the recompute runs regardless; a desk that still has yesterday's bars is worth
    serving, and burying that behind a 502 because one ticker was rate-limited would hide it.
    """
    summary = fetch.fetch_all() if fetch_data else None
    return desk.refresh().model_copy(update={"fetch": summary})


@router.put("/inception", response_model=PaperDeskState)
def put_inception(body: InceptionUpdateRequest) -> PaperDeskState:
    """Set the desk's inception override and re-run every book from it.

    ``PUT``, not ``POST``: setting a date is idempotent, and sending the same body twice must leave
    the desk in the same state rather than reading as "set it again". A date this desk cannot
    actually trade from -- after the benchmark's latest stored bar, before its earliest, or one
    ``SessionCalendar`` itself would yield zero sessions for -- is refused as a ``422`` naming the
    specific reason (:attr:`~app.paperdesk.desk.InceptionRejected.reason`), never a bare ``500`` and
    never silently clamped to something tradeable; see :func:`~app.paperdesk.desk.set_inception`'s
    own docstring for why a desk quietly trading a different window than the one asked for is worse
    than an error.

    Returns the freshly recomputed state rather than the stale one the caller last saw:
    :func:`~app.paperdesk.desk.set_inception` only writes the override file, so this route still has
    to call :func:`~app.paperdesk.desk.state` itself, which -- because the cache key already covers
    ``window.inception`` -- genuinely re-runs every book against the new window rather than serving
    anything cached under the old one. That cost is real (seconds per card, the same
    :func:`~app.paperdesk.desk.warm` exists to hide on startup) and is the correct trade for a date a
    person changed on purpose.
    """
    settings = get_settings()
    try:
        desk.set_inception(body.inception, settings=settings)
    except desk.InceptionRejected as exc:
        raise HTTPException(status_code=422, detail=exc.reason) from exc
    return desk.state(settings)


@router.delete("/inception", response_model=PaperDeskState)
def delete_inception() -> PaperDeskState:
    """Clear the inception override, restoring ``app.paperdesk.desk.INCEPTION`` as the effective
    inception, and re-run every book from it. Same recompute-and-return shape as :func:`put_inception`
    -- deleting an override that was never set is a no-op that still returns the (already default)
    state, not an error."""
    settings = get_settings()
    desk.clear_inception(settings=settings)
    return desk.state(settings)
