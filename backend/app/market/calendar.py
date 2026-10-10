"""The event-calendar aggregation layer: joins FOMC meetings, scheduled federal economic
releases, and this portfolio's earnings dates.

:mod:`app.market.calendar_models` already states the design rules the response has to honour --
dates over fake-precise instants, confirmed vs. estimated never blended, the ledger doing the
relevance join rather than the UI. This module is where those rules get executed. Four decisions
carry most of the design:

**One dead source degrades its own third of the page, never the other two.** FOMC meetings,
economic releases and portfolio earnings come from three structurally unrelated upstreams (the
Federal Reserve's own calendar, FRED's republication of the statistical agencies' schedules, and
Nasdaq's). :func:`app.market.fomc.fomc_events` already never raises -- it falls back to a bundled
snapshot on its own -- and :func:`app.market.releases.release_events` never raises either, returning
a ``config`` or ``provider_fallback`` warning plus whatever parsed. The earnings sweep below is the
one whose failure this module has to contain itself (a Nasdaq outage, a rate limit), and
:func:`build_calendar` never lets that escape: a failed sweep produces an empty earnings
contribution plus a ``provider_fallback`` warning, while the FOMC and release events collected
moments earlier are returned untouched. A user checking "when does the Fed meet next" or "when is
the next PCE print" must not lose that answer because Nasdaq is down.

**Economic releases span the whole window, like FOMC and unlike earnings.** Six requests total, one
per release, regardless of how many days were asked for -- so a ``days=180`` request gets every
scheduled PCE, CPI, jobs, GDP, PPI and retail-sales date in that span. Only the earnings sweep is
capped, for the per-day-request reason below. See :mod:`app.market.releases` for which releases are
carried, why weekly jobless claims are not, and why a missing FRED key omits these rows rather than
guessing them.

**The earnings sweep is one HTTP call per day, and that has a real cost.** There is no Nasdaq
endpoint that answers "earnings for these 40 tickers over the next 60 days" in one request; the only
surface :class:`~app.market.providers.nasdaq_earnings.NasdaqEarningsProvider` exposes is "everything
Nasdaq lists for one day" (see its docstring), so covering a window means one request per calendar
day in it. That is cheap once the on-disk HTTP cache (:class:`~app.market.cache.CachingTransport`) is
warm, but a cold cache turns a 60-day request into 60 sequential round trips before the page can
render. :data:`_EARNINGS_HORIZON_CAP` bounds that at 45 regardless of what ``days`` asks for, and a
request that actually wanted more emits a ``partial_window`` warning naming the horizon that was
really covered -- see the module docstring of ``calendar_models`` on why a calendar that silently
searched a shorter window than it advertised is a worse defect than an honest, capped one. FOMC
coverage is unaffected by the cap: it is one call regardless of window length, so a caller asking for
``days=180`` still gets every scheduled meeting in that span, just earnings capped at 45 days out.

**Earnings eligibility is decided here, against the ledger, once -- not per event.** Only an
individual company files quarterly results; a fund does not, and neither does a position with no
public financials at all. :data:`_NOT_EARNINGS_ELIGIBLE` excludes :class:`~app.core.models.
InstrumentKind.CASH`, ``ETF``, ``ETN``, ``CRYPTO`` and ``PRIVATE`` from the held-ticker set before the
sweep even starts, which is also what keeps :attr:`~app.market.calendar_models.EventCalendar.
holdings_total` honest: it must mean "tickers that could plausibly have an earnings date", and
counting a money-market fund against that denominator would make a calendar with three matches out of
forty *look* worse than one with three out of three actual candidates, exactly the failure the
denominator exists to prevent. A held instrument this codebase has not yet classified
(:class:`~app.core.models.InstrumentKind.UNKNOWN`, or -- defensively -- one with no instrument record
at all) is treated as *eligible* rather than excluded: silently shrinking the denominator over missing
metadata is a worse failure than sweeping a few extra symbols that simply come back with no earnings
event. There is no distinct "option" instrument kind in this codebase's vocabulary to exclude
separately; options are not held as their own ledger positions here.

**Timestamps are ``dt.datetime.now(dt.UTC)``, never ``dt.datetime.utcnow()``.** The latter is
deprecated and ``pytest.ini`` turns that deprecation into a hard test failure -- see the sibling
``app.market.macro`` module for the same rule stated against ``generated_at``/``fetched_at``.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import threading
from typing import Final

import httpx

from app.config import Settings, get_settings
from app.core.canonical import canonicalize_ledger
from app.core.holdings import build_positions
from app.core.lots import build_lots
from app.core.models import Instrument, InstrumentKind
from app.datasource import ledger_db_path
from app.db import sqlite
from app.market.cache import CachingTransport
from app.market.calendar_models import CalendarEvent, EventCalendar
from app.market.fomc import fomc_events
from app.market.models import MarketWarning
from app.market.providers.base import ProviderResponseError, ProviderUnavailable, RateLimited
from app.market.providers.nasdaq_earnings import NasdaqEarningsProvider
from app.market.releases import release_events

__all__ = ["build_calendar", "warm"]

#: Hard ceiling on how many days the earnings sweep walks, independent of the requested `days` --
#: see the module docstring's "the earnings sweep is one HTTP call per day" section. FOMC coverage is
#: never capped: `fomc_events` is one call regardless of window length.
_EARNINGS_HORIZON_CAP: Final[int] = 45

#: Errors the sweep treats as "this upstream is unwell right now" rather than "this codebase is
#: broken" -- the same three the registry's own walk logic (`app.market.registry`) retries on.
#: `ProviderResponseError` is already a `ProviderUnavailable` subclass and `RateLimited` too, but both
#: are listed explicitly because that subclass relationship is `app.market.providers.base`'s contract
#: to keep, not something this module should rely on silently.
_EARNINGS_FAILURES: Final[tuple[type[Exception], ...]] = (
    ProviderUnavailable,
    RateLimited,
    ProviderResponseError,
)

#: Instrument kinds that cannot plausibly report quarterly earnings -- see the module docstring's
#: "earnings eligibility is decided here" section. `UNKNOWN` (the default for an unclassified
#: instrument, and for a symbol with no instrument record at all) is deliberately *not* in this set.
_NOT_EARNINGS_ELIGIBLE: Final[frozenset[InstrumentKind]] = frozenset(
    {
        InstrumentKind.CASH,
        InstrumentKind.ETF,
        InstrumentKind.ETN,
        InstrumentKind.CRYPTO,
        InstrumentKind.PRIVATE,
    }
)


def build_calendar(
    *,
    days: int = 60,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
    today: dt.date | None = None,
) -> EventCalendar:
    """Join FOMC meetings and this portfolio's earnings dates into one response.

    Args:
        days: Size of the requested window in days; the response covers ``[today, today + days]``
            inclusive. FOMC coverage spans the whole window; the earnings sweep is capped at
            :data:`_EARNINGS_HORIZON_CAP` days regardless -- see the module docstring.
        settings: Defaults to :func:`app.config.get_settings`. Threaded through explicitly (rather
            than called at the top of every helper) so a caller -- a test, or a future batch job --
            can pin one settings object across the whole build.
        client: An `httpx.Client` used for both the FOMC fetch and the earnings sweep. Defaults to a
            fresh client wrapping the shared on-disk :class:`~app.market.cache.CachingTransport`,
            built once per call rather than as a module-level singleton -- the same reasoning
            `app.market.macro.build_snapshot` gives for its own client construction: one built at
            import time can outlive the event loop it was constructed against.
        today: Injectable "now", for deterministic tests. Defaults to the real `dt.date.today()`.

    Returns:
        An :class:`~app.market.calendar_models.EventCalendar`. Never raises for a degraded upstream --
        the worst case is FOMC-only coverage with `holdings_covered=0` and warnings naming why, never
        an exception the API layer has to translate into a 5xx. See the module docstring.
    """
    cfg = settings or get_settings()
    window_start = today or dt.date.today()
    window_end = window_start + dt.timedelta(days=days)
    http_client = client or _cached_client(cfg)

    warnings: list[MarketWarning] = []

    fomc, fomc_warnings = fomc_events(start=window_start, end=window_end, client=http_client)
    events: list[CalendarEvent] = list(fomc)
    warnings.extend(fomc_warnings)

    # Shares `http_client`, and therefore the same on-disk HTTP cache, as the other two sources. A
    # release schedule changes a handful of times a year, so six cached reads per page load is the
    # right cost for it -- and a `refresh=true` request pins that cache's TTL to zero the same way it
    # does for FOMC and Nasdaq, with no special case here.
    releases, release_warnings = release_events(
        start=window_start, end=window_end, settings=cfg, client=http_client
    )
    events.extend(releases)
    warnings.extend(release_warnings)

    held_symbols = _eligible_held_symbols(cfg)
    holdings_total = len(held_symbols)

    earnings_span = min(days, _EARNINGS_HORIZON_CAP)
    earnings_end = window_start + dt.timedelta(days=earnings_span)
    if days > _EARNINGS_HORIZON_CAP:
        warnings.append(
            # One plain sentence, no module path. This string is rendered to the reader above the
            # fold on the Overview page, and a name only a developer can act on is noise there. The
            # reason the cap exists -- one Nasdaq request per calendar day on a cold cache, so the
            # earnings horizon cannot track the wider FOMC/macro window -- stays in this module's
            # own docstring, where the person who needs it is already looking.
            MarketWarning(
                kind="partial_window",
                message=(
                    f"Earnings shown through {earnings_end.isoformat()} only, "
                    f"not the full {days} days requested."
                ),
            )
        )

    earnings_events, holdings_covered = _sweep_earnings(
        held_symbols, start=window_start, end=earnings_end, client=http_client, warnings=warnings
    )
    events.extend(earnings_events)

    events.sort(key=_event_sort_key)

    return EventCalendar(
        generated_at=dt.datetime.now(dt.UTC),
        start=window_start,
        end=window_end,
        events=tuple(events),
        holdings_total=holdings_total,
        holdings_covered=holdings_covered,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# Earnings sweep
# ---------------------------------------------------------------------------


def _sweep_earnings(
    symbols: frozenset[str],
    *,
    start: dt.date,
    end: dt.date,
    client: httpx.Client,
    warnings: list[MarketWarning],
) -> tuple[list[CalendarEvent], int]:
    """One `fetch_earnings_for_day` call per day in `[start, end]`, filtered to `symbols`.

    Failure is per-day, not per-sweep: a single bad day (a rate limit, a transient 503) does not
    abort the days around it, and every day's own `last_skipped` count is accumulated into one
    `partial_parse` warning rather than one warning per day, which would be noise for a 45-day sweep.
    An empty `symbols` set skips the network entirely -- there is nothing to match against, so paying
    for the sweep would only warm a cache nobody asked for.
    """
    if not symbols:
        return [], 0

    provider = NasdaqEarningsProvider(client)
    events: list[CalendarEvent] = []
    covered: set[str] = set()
    total_skipped = 0
    failed_days = 0
    swept_days = 0
    last_failure: Exception | None = None

    day = start
    while day <= end:
        swept_days += 1
        try:
            day_events = provider.fetch_earnings_for_day(day)
        except _EARNINGS_FAILURES as exc:
            failed_days += 1
            last_failure = exc
            day += dt.timedelta(days=1)
            continue

        total_skipped += provider.last_skipped
        for event in day_events:
            if event.symbol is not None and event.symbol.upper() in symbols:
                events.append(event)
                covered.add(event.symbol.upper())
        day += dt.timedelta(days=1)

    if failed_days:
        warnings.append(
            MarketWarning(
                kind="provider_fallback",
                message=(
                    f"nasdaq earnings sweep failed for {failed_days} of {swept_days} day(s): "
                    f"{last_failure}"
                ),
            )
        )
    if total_skipped:
        warnings.append(
            MarketWarning(
                kind="partial_parse",
                message=(
                    f"nasdaq earnings sweep skipped {total_skipped} unparsable row(s) across "
                    f"{swept_days} day(s)"
                ),
            )
        )

    return events, len(covered)


# ---------------------------------------------------------------------------
# Held-ticker set -- the ledger replay chain, mirroring app.api.portfolio._build_report
# ---------------------------------------------------------------------------


def _eligible_held_symbols(cfg: Settings) -> frozenset[str]:
    """Every currently-held ticker that could plausibly report earnings.

    Follows the exact replay chain `app.api.portfolio._build_report` uses to derive current
    positions -- there is no holdings table, only a transaction ledger to replay -- with two
    deliberate differences. First, this never raises: a missing or empty ledger is a legitimate
    "nothing held yet" state for a calendar (the portfolio page's 404 is right for *that* page, which
    has nothing else to show; this page still has FOMC meetings to show regardless). Second, this
    reads no prices and applies no wash-sale pass: both exist to produce dollar figures this function
    never needs, only the set of symbols with an open position.
    """
    ledger_file = ledger_db_path(cfg)
    if not ledger_file.exists():
        return frozenset()

    with sqlite.connect(ledger_file, read_only=True) as conn:
        accounts = {account.account_id: account for account in sqlite.fetch_accounts(conn)}
        instruments = {
            instrument.instrument_id: instrument for instrument in sqlite.fetch_instruments(conn)
        }
        transactions = [sqlite.transaction_from_row(row) for row in sqlite.fetch_transactions(conn)]

    if not transactions:
        return frozenset()

    as_of = max(txn.trade_date for txn in transactions)
    transactions, instruments = canonicalize_ledger(transactions, instruments)
    lot_ledger = build_lots(transactions, accounts=accounts, instruments=instruments)
    holdings = build_positions(lot_ledger, accounts=accounts, as_of=as_of)

    eligible: set[str] = set()
    for holding in holdings:
        if _is_earnings_eligible(instruments.get(holding.instrument_id)):
            eligible.add(holding.symbol.upper())
    return frozenset(eligible)


def _is_earnings_eligible(instrument: Instrument | None) -> bool:
    """Whether a held instrument belongs in the earnings sweep's ticker set.

    `instrument is None` covers a held `instrument_id` with no row in the `instrument` table at all
    (defensively -- every adapter-driven import writes one, see `app.db.sqlite.upsert_instrument`,
    so this should not occur against the real ledger) and is treated the same as `UNKNOWN`: eligible
    by default, for the reason `_NOT_EARNINGS_ELIGIBLE` documents.
    """
    kind = instrument.kind if instrument is not None else InstrumentKind.UNKNOWN
    return kind not in _NOT_EARNINGS_ELIGIBLE


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def _event_sort_key(event: CalendarEvent) -> tuple[dt.date, str, tuple[bool, str]]:
    """`date` ascending, then `kind`, then `symbol` with `None` sorted last -- see
    `EventCalendar.events`'s own docstring for this contract. `(symbol is None, symbol or "")` puts
    every `None` after every real symbol regardless of what `""` would otherwise sort as, since
    `False < True` and no real symbol is the empty string."""
    return (event.date, event.kind.value, (event.symbol is None, event.symbol or ""))


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

#: A day's Nasdaq earnings listing for a date that has already happened does not change; even the
#: near-future end of the sweep window is not worth re-fetching within the same hour. Matches
#: `Interval.DAY`'s own TTL in `app.market.cache` for the same reason that TTL was chosen: a
#: completed session's data is not going to move.
_CACHE_TTL: Final[float] = 3600.0


def _cached_client(cfg: Settings) -> httpx.Client:
    """The default `httpx.Client`, built the way `app.market.registry.default_registry` builds its
    own: one `CachingTransport` wrapping a real `httpx.HTTPTransport`, over the same on-disk cache
    every other provider in this application shares."""
    transport = CachingTransport(httpx.HTTPTransport(), cfg.cache_dir / "http", ttl=_CACHE_TTL)
    return httpx.Client(transport=transport, timeout=10.0)


# ---------------------------------------------------------------------------
# Startup warm
# ---------------------------------------------------------------------------

#: The window `warm` primes, matched to the frontend's own default (`calendarApi`'s `DEFAULT_DAYS`
#: in `frontend/src/api/calendar.ts`, which the Overview page's `useEventCalendar` uses). Warming a
#: different span than the first request asks for would leave that request paying a cold Nasdaq sweep
#: for the days the warm missed, so the two are pinned to the same number on purpose.
_WARM_DAYS: Final[int] = 60


def warm(settings: Settings | None = None) -> None:
    """Prime the calendar's on-disk HTTP cache in the background, so the first person to open the
    Overview page after a server start does not wait on a cold FOMC/Nasdaq/FRED sweep.

    The same shape as `app.paperdesk.desk.warm` and `app.market.refresh._warm_macro_snapshot`: a
    daemon thread that returns immediately and swallows everything, so a slow or dead upstream delays
    startup by nothing and `/api/calendar/events` still builds on demand exactly as it did before.
    One best-effort `build_calendar` at the frontend's default `_WARM_DAYS` window leaves a warm
    `CachingTransport` entry behind for that first request to read -- a cold 60-day earnings sweep is
    one Nasdaq round trip per day (see the module docstring), which is precisely the latency this
    removes from the Overview page's cold open.

    Gated by the caller on `Settings.refresh_on_startup`, the same switch the bar sweep and macro
    warm sit behind: this makes real network requests to the Fed, Nasdaq and FRED, so the test suite
    -- which sets `INVDASH_REFRESH_ON_STARTUP=0` in `tests/conftest.py` -- must never inherit it.
    """

    def _run() -> None:
        # Suppressing everything is the point: this thread has no caller to raise to, and a warm that
        # fails must leave the server started and the next request building as it always did.
        # `build_calendar` already never raises for a degraded upstream (see its docstring); this
        # guard covers only the genuine remainder.
        with contextlib.suppress(Exception):
            build_calendar(days=_WARM_DAYS, settings=settings)

    threading.Thread(target=_run, name="calendar-warm", daemon=True).start()
