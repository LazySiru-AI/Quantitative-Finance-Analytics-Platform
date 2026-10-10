"""Pulling fresh daily bars for everything the paper desk prices, on demand.

**Why this exists.** ``POST /api/paperdesk/refresh`` used to do exactly one thing: drop both cache
tiers and recompute every book off whatever was already in the store. That is the right primitive
when the store is current, and it is useless when it is not -- the page's own header says the mark
is *N* days stale, the reader presses the only button on the page, and the desk dutifully recomputes
the identical figures off the identical bars and still says *N* days stale. The button that a person
presses to make the page current has to be the button that fetches. This module is that half; the
recompute half stays where it was, in :func:`app.paperdesk.desk.refresh`.

**Scope: the desk's own symbols, at daily interval, incrementally.**
:func:`app.paperdesk.desk.universe_symbols` decides the list -- every card on every book's roster
plus every benchmark, about forty symbols today -- and this module fetches all of them, every press,
with no staleness gate. That is a deliberate difference from :mod:`app.market.refresh`, whose
background startup sweep covers ~650 symbols and *must* skip the fresh ones to finish at all. Here
the list is one-sixteenth the size, the caller is a person who pressed a button on purpose, and a
skip is the one outcome they cannot check: "I fetched it and nothing had changed" and "I decided not
to ask" are the same screen. So this asks about every symbol and reports the answer per symbol.

**"Did anything change" is answered by the store, not by the response size.** Each symbol's newest
stored session is read before and after its sync, and only a session that actually moved counts as
``advanced`` -- see :class:`~app.paperdesk.models.FetchSummary`, whose docstring records the version
of this that reported every symbol as updated on every press because ``sync_bars`` always re-sends a
short overlap.

Incremental (``full=False``) is not a hedge against that: :func:`app.market.store.sync_bars` reads
the newest stored bar and requests only what follows it, so asking about all forty symbols costs
forty small requests, not forty full histories.

**One bad symbol never aborts the sweep.** A provider outage, a rate limit, a symbol the provider
has never heard of -- each is recorded against that symbol in
:attr:`~app.paperdesk.models.FetchSummary.failures` and the sweep moves on. The alternative, raising
on the first failure, would let one delisted ticker on one card block the other thirty-nine symbols
from ever refreshing, and would do it while reporting a ``502`` that names the wrong problem.

**Pacing.** :data:`_REQUEST_DELAY_SECONDS` mirrors ``app.market.refresh``'s own constant and exists
for the same reason: forty back-to-back requests is exactly the shape that trips Yahoo's rate
limiter for every other request the app has in flight. Forty symbols at 300ms is twelve seconds of
pacing on top of the network time, which is why the caller shows a busy state rather than pretending
this is instant.

**Timestamps are ``dt.datetime.now(dt.UTC)``, never ``dt.datetime.utcnow()``** -- the latter is
deprecated and ``pytest.ini`` turns that deprecation into a hard test failure. Same rule
``app.market.calendar`` and ``app.market.macro`` state for their own ``generated_at`` fields.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Final

from app.config import Settings, get_settings
from app.market import store
from app.market.models import Interval
from app.market.providers.base import ProviderError
from app.market.registry import ProviderRegistry
from app.paperdesk import desk
from app.paperdesk.models import FetchSummary

__all__ = ["fetch_all"]

logger = logging.getLogger(__name__)

#: Delay between successive provider requests -- see the module docstring's "Pacing" section. Kept
#: as this module's own constant rather than imported from `app.market.refresh`, whose value is
#: tuned for a ~650-symbol background sweep and is private to that module; the two happen to agree
#: today and are free to diverge, since one is paced against a wall-time cap and this one is paced
#: against a person waiting for a page.
_REQUEST_DELAY_SECONDS: Final[float] = 0.3


def _last_session(cfg: Settings, symbol: str) -> dt.date | None:
    """One symbol's newest stored session, or ``None`` if it has none stored (or cannot be read).

    Read defensively: a store that cannot answer for one symbol is reported as "no bars" rather than
    taking down a fetch whose other thirty-nine syncs may all have succeeded. The cost of getting
    this wrong is one symbol counted as ``unchanged`` when it did advance -- a miscount in the
    conservative direction, never a fetch that fails.
    """
    try:
        coverage = store.coverage(symbol, Interval.DAY, settings=cfg)
    except Exception:  # a diagnostic read must never fail the sweep it describes
        logger.warning("paperdesk fetch: could not read coverage for %s", symbol, exc_info=True)
        return None
    if coverage.last_ts is None:
        return None
    return coverage.last_ts.date()


def _latest_bar(cfg: Settings) -> dt.date | None:
    """The newest stored session for the desk's primary benchmark.

    This is what `app.paperdesk.desk._trading_window` derives `as_of` from, so it is the honest
    answer to "did this fetch move the page's mark" -- a different and stricter question than
    whether any individual symbol advanced.
    """
    return _last_session(cfg, desk._BENCHMARK)


def fetch_all(
    settings: Settings | None = None,
    *,
    registry: ProviderRegistry | None = None,
) -> FetchSummary:
    """Sync daily bars for every symbol the desk prices, and report what came back.

    Args:
        settings: Defaults to :func:`app.config.get_settings`. Threaded through explicitly so one
            settings object pins the whole sweep, matching `app.market.calendar.build_calendar`.
        registry: Provider registry, for tests that want a fake upstream without patching module
            globals. ``None`` lets :func:`app.market.store.sync_bars` build the default one per
            symbol, which is what production does.

    Returns:
        A :class:`~app.paperdesk.models.FetchSummary`. Never raises for a provider failure -- see
        the module docstring. A failure that is *not* a provider failure (a corrupt store, a disk
        error mid-merge) is caught per symbol too, for the same reason: the caller's next step is a
        recompute that will surface a genuinely broken store on its own, and losing thirty-nine
        good syncs to report one bad one earlier is a bad trade.
    """
    cfg = settings or get_settings()
    symbols = desk.universe_symbols(cfg)

    started_at = dt.datetime.now(dt.UTC)
    before = _latest_bar(cfg)
    monotonic_start = time.monotonic()

    advanced = 0
    unchanged = 0
    rows_merged = 0
    failures: list[str] = []

    for index, symbol in enumerate(symbols):
        if index:
            time.sleep(_REQUEST_DELAY_SECONDS)
        # Read before the sync, so "did this symbol gain a session" is answered by the store rather
        # than by the size of the response. `sync_bars` re-requests a short overlap behind the newest
        # stored bar every single time (`app.market.store._OVERLAP`), so a row count is never zero
        # and can never distinguish a genuine new session from the same two bars sent again. See
        # `FetchSummary`'s docstring for the draft that got this wrong.
        before_session = _last_session(cfg, symbol)
        try:
            outcome = store.sync_bars(symbol, Interval.DAY, registry=registry, settings=cfg)
        except ProviderError as exc:
            failures.append(f"{symbol}: {exc}")
            logger.warning("paperdesk fetch: %s failed: %s", symbol, exc)
            continue
        except Exception as exc:  # see the docstring; one symbol never aborts forty
            failures.append(f"{symbol}: {type(exc).__name__}: {exc}")
            logger.warning("paperdesk fetch: %s failed", symbol, exc_info=True)
            continue
        rows_merged += outcome.rows_written
        after_ts = outcome.coverage.last_ts
        after_session = after_ts.date() if after_ts is not None else None
        if after_session is not None and after_session != before_session:
            advanced += 1
        else:
            unchanged += 1

    finished_at = dt.datetime.now(dt.UTC)
    return FetchSummary(
        requested=len(symbols),
        advanced=advanced,
        unchanged=unchanged,
        failed=len(failures),
        rows_merged=rows_merged,
        failures=failures,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=round(time.monotonic() - monotonic_start, 1),
        latest_bar_before=before,
        latest_bar_after=_latest_bar(cfg),
    )
