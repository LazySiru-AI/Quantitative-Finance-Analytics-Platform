"""Fetch, parse and diff a tracked filer's holdings -- the thin layer between the router and the
package the rest of ``app.institutions`` already builds.

This module holds no state beyond what is injected into it per call. It composes four things that
are each independently correct and independently tested (:mod:`app.institutions.edgar`,
:mod:`app.institutions.parse`, :mod:`app.institutions.deltas`, :mod:`app.institutions.catalog`) and
adds exactly what none of them can do alone: deciding *which* filings on EDGAR are worth opening,
and in what order the results should come back.

**Why the raw document fetch lives here, not in ``edgar.py``.** :class:`~app.institutions.edgar.
EdgarClient` deliberately exposes no "fetch a document's bytes" method -- see that module's
docstring: it answers *where* a filing's holdings document lives, parsing what is at that URL is a
different worker's job. This module is that job's caller, so it is the one that issues the final
GET, via :func:`_fetch_document` below, which reuses ``EdgarClient``'s own private ``_get`` rather
than re-deriving its four-way status mapping (429 / 5xx / other 4xx / transport) a second time. That
also keeps every HTTP call for one fund -- listing *and* documents -- on the exact same
``httpx.Client``, hence the exact same cache and the exact same transport a test swaps in.

**Why candidates are over-fetched before being reduced.** EDGAR returns filings in filing-date
order, and filing date is not period order -- a real iShares NPORT-P filed 2026-07-13 reports the
quarter ending 2025-09-30, months *older* than one filed 2026-05-28 reporting 2026-03-31 (see
:mod:`app.institutions.edgar`'s module docstring, and :attr:`~app.institutions.edgar.FilingRef.
report_date`). Asking EDGAR for exactly as many filings as periods are wanted therefore risks
handing :func:`app.institutions.deltas.latest_pair` fewer usable periods than filings fetched, or
missing that an amendment restates a period already seen. :func:`load_snapshots` asks for
:data:`_CANDIDATE_SLACK` more raw filings than the caller wants snapshots for, then reduces: for a
13F, using :attr:`~app.institutions.edgar.FilingRef.report_date` (known from the submissions JSON
without opening a single document) to pick, per period, the candidate with the latest ``filing_date``
-- an amendment supersedes the filing it corrects -- and opening documents only for the periods that
survive that reduction; for an NPORT, which carries no such metadata field, by opening every
candidate's document (there is no way to learn its period otherwise) and applying the same
later-filed-wins rule to the parsed :class:`~app.institutions.models.Snapshot` objects. Either way,
the final list is sorted by :attr:`~app.institutions.models.Snapshot.period`, never by filing date.

**Why the HTTP cache TTL is hours, and why the listing endpoints share it with the documents.** A
filed accession's document is immutable -- SEC does not rewrite history -- so there is no
correctness reason to ever refetch one within a session; a long TTL costs nothing. The *listing*
calls (the submissions JSON, the browse-edgar Atom feed) do change over time -- a new quarter's
filing eventually appears -- but giving them a short TTL "so a new filing shows up sooner" would
turn "check whether a tracked fund has filed yet" into a request that hammers ``data.sec.gov`` every
few minutes across every open tab and every page reload. SEC's fair-access policy blocks abusive
clients outright, and this whole feature depends on staying inside it; a new filing surfacing up to
a few hours late is a far smaller cost than being rate-limited off the endpoint entirely. See
``app/market/cache.py``'s module docstring: this cache is disposable and not a source of truth.

**Why there is no persistence beyond the HTTP cache.** This repository deliberately recomputes
derived state on read rather than materialising it -- see ``_migrate_drop_derived_build`` in
``app/db/sqlite.py`` for the precedent, which removed exactly such a table. A snapshot or a delta
computed here is cheap to recompute (the cache absorbs the network cost) and never drifts from what
EDGAR currently serves, which a stored copy could.
"""

from __future__ import annotations

import datetime as dt

import httpx

from app.config import Settings
from app.institutions import catalog
from app.institutions.deltas import diff, latest_pair
from app.institutions.edgar import EdgarClient, FilingRef
from app.institutions.models import FundRef, PortfolioDelta, Snapshot, Source
from app.institutions.parse import parse_13f, parse_nport
from app.market.providers.base import ProviderResponseError

__all__ = [
    "InsufficientHistory",
    "PeriodNotFound",
    "build_client",
    "load_delta",
    "load_latest",
    "load_snapshots",
]

#: How many *more* raw filings this module asks EDGAR for than the number of snapshots a caller
#: ultimately wants, so a duplicated period (an amendment) or an out-of-order filing never leaves
#: fewer than the requested count of usable periods. See the module docstring's second point. The
#: brief that shaped this module suggested "say limit=6" for the ordinary two-snapshot case
#: (`load_delta`'s `load_snapshots(limit=2)` call) -- `2 + 4 == 6` reproduces that exactly.
_CANDIDATE_SLACK = 4

#: How many snapshots `load_latest` asks `load_snapshots` for by default -- enough quarters of
#: history that a `?period=` query naming one of the fund's last several filings has a real chance
#: of landing inside the window, without this endpoint pretending to be a full point-in-time
#: archive (see `PeriodNotFound`).
_DEFAULT_HOLDINGS_HISTORY = 6

#: When ``as_of`` bounds the candidate window (see :func:`load_snapshots`) and the caller left
#: ``candidate_limit`` at its auto-computed default, the auto-computed count is multiplied by this
#: factor before asking EDGAR for filings. Filtering on ``as_of`` happens *after* the fetch, never
#: before -- see :func:`load_snapshots`'s docstring -- so a window sized for the unfiltered case can
#: otherwise discard exactly the filings a bounded caller most wants: the ones between ``as_of`` and
#: today are dropped, but the window was never asked to reach far enough past them to still find two
#: usable periods underneath. Three widens the ordinary two-snapshot window (``2 + 4 == 6``, see
#: `_CANDIDATE_SLACK`) to 18, and the ordinary holdings window (``6 + 4 == 10``) to 30 -- enough that
#: an ``as_of`` several quarters behind a fund's most recent filing still lands inside the fetched
#: window for every fund in :mod:`app.institutions.catalog`, without asking EDGAR for an unbounded
#: amount of history on every bounded request. This is a heuristic, not a guarantee: a caller needing
#: more control passes ``candidate_limit`` explicitly, which bypasses this widening entirely (an
#: explicit window is a pinned window, bound or not); and a bound old enough to still come up short
#: raises :class:`PeriodNotFound` or :class:`InsufficientHistory`, both worded to say a date bound
#: was applied, rather than this module pretending to guarantee an answer no fixed window ever could.
_AS_OF_CANDIDATE_MULTIPLIER = 3

#: Cache TTL for both the listing calls and the holdings documents, in seconds. See the module
#: docstring for why these two very different kinds of request share one number.
_CACHE_TTL_SECONDS = 6 * 3600.0

_THIRTEEN_F_FORM = "13F-HR"
_NPORT_FORM = "NPORT-P"


class PeriodNotFound(ValueError):
    """The requested ``period`` has no snapshot among the filings this service looked at.

    Not a claim that the filer never reported that period -- only that it did not appear inside the
    deliberately bounded window of recent filings :func:`load_latest` fetched (see
    :data:`_DEFAULT_HOLDINGS_HISTORY`). This module is a recent-quarters viewer, not a full
    point-in-time archive: honouring an arbitrarily old ``period`` would mean fetching and parsing
    an unbounded number of historical filings on every request that asks for one.

    Also raised -- with a message that says so explicitly -- when an ``as_of`` bound (see
    :func:`load_snapshots`) filters every candidate filing out. That is a different reason for the
    same outcome ("nothing to return") and deliberately reuses this exception rather than inventing
    a third one: a caller only ever needs to know that no snapshot is available and why, not a new
    vocabulary for "no snapshot because of a date bound" versus "no snapshot because none exist".
    """


class InsufficientHistory(ValueError):
    """Fewer than two usable periods are on record for this fund -- a delta cannot be computed.

    Deliberately a distinct outcome from returning an empty
    :class:`~app.institutions.models.PortfolioDelta`. A fund with exactly one filing on record (a
    freshly tracked fund, or a filer that only recently started reporting) is a real, honest state,
    and rendering it as "nothing changed" would tell the user a false story -- there is no "before"
    to compare against, not a before identical to the after. See
    :func:`app.institutions.deltas.latest_pair`, which returns ``None`` for exactly this case and is
    the thing this exception is raised in response to.

    Also raised, with a message naming the bound, when an ``as_of`` bound (see
    :func:`load_snapshots`) leaves fewer than two periods -- whether because the fund genuinely has
    fewer than two, or because more recent filings exist but postdate ``as_of``. Both are "cannot
    compute a change" in the same way, and the message says which one applies rather than this
    module guessing a reader's intent.
    """


def build_client(settings: Settings) -> EdgarClient:
    """An :class:`~app.institutions.edgar.EdgarClient` backed by a disposable, long-TTL HTTP cache.

    Built the same way :func:`app.market.registry.default_registry` builds its client: one
    :class:`httpx.Client` wrapping :class:`~app.market.cache.CachingTransport` over a real
    :class:`httpx.HTTPTransport`, rooted under ``settings.cache_dir`` so this cache's lifetime and
    location are governed by the same knob as every other provider's. See the module docstring for
    why the TTL is measured in hours rather than minutes.
    """
    from app.market.cache import CachingTransport

    inner = httpx.HTTPTransport()
    transport = CachingTransport(inner, settings.cache_dir / "edgar", ttl=_CACHE_TTL_SECONDS)
    http_client = httpx.Client(transport=transport, timeout=15.0)
    return EdgarClient(client=http_client)


def _fetch_document(client: EdgarClient, url: str) -> str:
    """The raw text of one filing's holdings document.

    See the module docstring for why this calls ``EdgarClient``'s private ``_get`` rather than
    duplicating its status-code mapping: doing so keeps that mapping defined in exactly one place
    and guarantees this fetch goes through the same ``httpx.Client`` -- same transport, same cache,
    same SEC-mandated ``User-Agent`` -- the caller's ``client`` was built with. That matters most for
    tests: one that monkeypatches :func:`build_client` to return an ``EdgarClient`` wrapping an
    ``httpx.MockTransport`` gets that same mock used here too, with no second, unmocked client that
    could reach the real network by accident.
    """
    return client._get(url).text


def _form_for(fund: FundRef) -> str:
    return _THIRTEEN_F_FORM if fund.source is Source.THIRTEEN_F else _NPORT_FORM


def _list_candidates(
    fund: FundRef, *, client: EdgarClient, candidate_limit: int
) -> list[FilingRef]:
    """Raw filing metadata for ``fund``, newest filed first -- EDGAR's own order, unmodified.

    Dispatches on :attr:`~app.institutions.models.FundRef.source` to the one EDGAR endpoint that can
    actually answer for that kind of filer: a 13F manager has no series and is listed by CIK alone
    (:meth:`~app.institutions.edgar.EdgarClient.list_filings`); an ETF is addressed by series id
    (:meth:`~app.institutions.edgar.EdgarClient.list_series_filings`), since the submissions API used
    for the manager case cannot isolate one fund out of a multi-fund trust.
    """
    form = _form_for(fund)
    if fund.source is Source.THIRTEEN_F:
        return client.list_filings(fund.cik, form, limit=candidate_limit)
    if fund.series_id is None:
        # Every ETF in `app.institutions.catalog._ETFS` carries a `series_id` -- this is a defence
        # against a future catalog entry that forgets to set one, not a case any current fund hits.
        # Without it, `list_series_filings` has no id to query and this function would otherwise
        # have to hand back an empty list that silently reads as "this fund has never filed".
        raise ProviderResponseError(
            f"institutions catalog entry {fund.key!r} is an NPORT filer with no series_id -- "
            "cannot list its filings",
            provider="edgar",
        )
    return client.list_series_filings(fund.series_id, form, limit=candidate_limit)


def _snapshots_13f(
    fund: FundRef, refs: list[FilingRef], *, client: EdgarClient, limit: int
) -> list[Snapshot]:
    """Reduce 13F candidates to snapshots, fetching a document only for periods that survive.

    Every ``ref`` here came from :meth:`~app.institutions.edgar.EdgarClient.list_filings`, which
    populates :attr:`~app.institutions.edgar.FilingRef.report_date` from the submissions JSON's
    ``reportDate`` array -- so the period each candidate reports is already known *before* any
    document is opened. That lets this function pick the winning candidate per period (the one with
    the latest ``filing_date`` -- an amendment restating a period supersedes the filing it corrects,
    the same rule :func:`app.institutions.deltas.latest_pair` applies) using only the metadata
    already in hand, and fetch the actual holdings document only for the periods that make the final
    cut. Fetching (and parsing) every candidate regardless, the way :func:`_snapshots_nport` has to,
    would cost a document round trip this function does not need.
    """
    best_by_period: dict[dt.date, FilingRef] = {}
    for ref in refs:
        if ref.report_date is None:
            # `list_filings` always populates this field (see its docstring); a `None` here means
            # something upstream of this module changed in a way its own contract forbids, and
            # silently skipping the filing would understate the fund's history without saying why.
            raise ProviderResponseError(
                f"edgar list_filings returned 13F filing {ref.accession!r} with no reportDate",
                provider="edgar",
            )
        current = best_by_period.get(ref.report_date)
        if current is None or ref.filing_date > current.filing_date:
            best_by_period[ref.report_date] = ref

    chosen_periods = sorted(best_by_period)[-limit:]
    snapshots: list[Snapshot] = []
    for period in chosen_periods:
        ref = best_by_period[period]
        url = client.holdings_document_url(fund.cik, ref.accession, fund.source)
        xml = _fetch_document(client, url)
        snapshots.append(
            parse_13f(xml, fund=fund, period=period, filed=ref.filing_date, accession=ref.accession)
        )
    return snapshots


def _snapshots_nport(
    fund: FundRef, refs: list[FilingRef], *, client: EdgarClient, limit: int
) -> list[Snapshot]:
    """Reduce NPORT candidates to snapshots by opening every candidate's document.

    Unlike :func:`_snapshots_13f`, there is no metadata shortcut here: the browse-edgar Atom feed
    :meth:`~app.institutions.edgar.EdgarClient.list_series_filings` reads carries no period field at
    all (see :attr:`~app.institutions.edgar.FilingRef.report_date`'s docstring), so the only way to
    learn what period a candidate reports is to open its ``primary_doc.xml`` and read
    ``<repPdDate>``. Every candidate is therefore fetched and parsed before the later-filed-wins
    reduction (identical in rule to :func:`_snapshots_13f`'s, applied here to the parsed
    :class:`~app.institutions.models.Snapshot`'s own ``filed``/``period`` rather than to
    unopened filing metadata) picks the periods that make the final cut.
    """
    parsed: list[Snapshot] = []
    for ref in refs:
        url = client.holdings_document_url(fund.cik, ref.accession, fund.source)
        xml = _fetch_document(client, url)
        parsed.append(parse_nport(xml, fund=fund, filed=ref.filing_date, accession=ref.accession))

    best_by_period: dict[dt.date, Snapshot] = {}
    for snap in parsed:
        current = best_by_period.get(snap.period)
        if current is None or snap.filed > current.filed:
            best_by_period[snap.period] = snap

    chosen_periods = sorted(best_by_period)[-limit:]
    return [best_by_period[period] for period in chosen_periods]


def load_snapshots(
    fund: FundRef,
    *,
    client: EdgarClient,
    settings: Settings,
    limit: int = 2,
    candidate_limit: int | None = None,
    as_of: dt.date | None = None,
) -> list[Snapshot]:
    """The most recent ``limit`` distinct-period snapshots for ``fund``, ascending by period.

    ``candidate_limit`` is how many raw filings are asked for before reduction; ``None`` (the
    default used by the router) computes it as ``limit + _CANDIDATE_SLACK``, per the module
    docstring. Tests pass it explicitly to pin exactly which fixtures a candidate window covers,
    without depending on this default.

    ``as_of``, when given, bounds every candidate filing to ones whose
    :attr:`~app.institutions.edgar.FilingRef.filing_date` is on or before it. This is a *filing*
    date bound, not a period bound, and the distinction is the whole reason this parameter exists: a
    filing reporting quarter-end 2026-06-30 but filed 2026-08-14 is excluded by
    ``as_of=2026-08-13`` regardless of how old the period it describes is, because nobody could have
    read that filing on 2026-08-13 -- see this module's docstring, second point, on why filing date
    and period do not even sort alike. The filter runs on the raw :class:`~app.institutions.edgar.
    FilingRef` list, *before* :func:`_snapshots_13f`/:func:`_snapshots_nport` fetch or parse a single
    document, so a filing that postdates ``as_of`` never costs a network round trip it could not
    possibly contribute to the answer.

    ``None`` (the default) applies no bound at all -- every existing caller's behaviour is
    unchanged, byte for byte, since the filter step is simply skipped.

    When ``as_of`` is active *and* the caller left ``candidate_limit`` at its auto-computed default,
    the window asked of EDGAR is widened by :data:`_AS_OF_CANDIDATE_MULTIPLIER` before that default
    is computed, since the ``as_of`` filter runs after the fetch and would otherwise shrink a window
    sized for the unfiltered case -- see that constant's docstring for why. An explicit
    ``candidate_limit`` is never widened: a caller pinning it exactly is asking for that precise
    window, bound or not.

    Ticker resolution (:func:`app.institutions.catalog.ledger_cusip_tickers` and
    :func:`~app.institutions.catalog.apply_tickers`) happens once here, after the snapshots are
    built, rather than inside either per-source helper -- one ledger read per request regardless of
    how many snapshots are returned.
    """
    if candidate_limit is not None:
        candidates = candidate_limit
    else:
        candidates = limit + _CANDIDATE_SLACK
        if as_of is not None:
            candidates *= _AS_OF_CANDIDATE_MULTIPLIER

    refs = _list_candidates(fund, client=client, candidate_limit=candidates)
    if as_of is not None:
        refs = [ref for ref in refs if ref.filing_date <= as_of]

    if fund.source is Source.THIRTEEN_F:
        snapshots = _snapshots_13f(fund, refs, client=client, limit=limit)
    else:
        snapshots = _snapshots_nport(fund, refs, client=client, limit=limit)

    tickers = catalog.ledger_cusip_tickers(settings)
    ordered = sorted(snapshots, key=lambda snap: snap.period)
    return [catalog.apply_tickers(snap, tickers) for snap in ordered]


def load_latest(
    fund: FundRef,
    *,
    client: EdgarClient,
    settings: Settings,
    period: dt.date | None = None,
    limit: int = _DEFAULT_HOLDINGS_HISTORY,
    as_of: dt.date | None = None,
) -> Snapshot:
    """One snapshot for ``fund`` -- the most recent by period, or the one matching ``period``.

    ``as_of``, when given, is passed straight through to :func:`load_snapshots`: only filings that
    were public on or before that date can be returned at all, so both "the most recent" and "the
    one matching ``period``" are answered relative to that bound rather than to today. ``None`` (the
    default) applies no bound -- unchanged behaviour for every existing caller.

    Raises :class:`PeriodNotFound` both when ``fund`` has no filings at all within the fetched
    window and when ``period`` is given but does not match any of them -- see that exception's
    docstring for why this is not the same thing as "this fund never reported that period". When
    ``as_of`` filtered every candidate out, the message says so explicitly, so a reader does not
    conclude the filer has simply never filed.
    """
    snapshots = load_snapshots(fund, client=client, settings=settings, limit=limit, as_of=as_of)
    if not snapshots:
        if as_of is not None:
            raise PeriodNotFound(
                f"{fund.key!r} has no filings on record at or before as_of={as_of.isoformat()} -- "
                "either the filer has no filings yet, or none of its recent filings were public by "
                "that date"
            )
        raise PeriodNotFound(f"{fund.key!r} has no filings on record")

    if period is None:
        return snapshots[-1]

    for snap in snapshots:
        if snap.period == period:
            return snap

    available = ", ".join(snap.period.isoformat() for snap in snapshots)
    bound_note = f" -- as_of={as_of.isoformat()} bound applied" if as_of is not None else ""
    raise PeriodNotFound(
        f"{fund.key!r} has no snapshot for period {period.isoformat()} among its "
        f"{len(snapshots)} most recently fetched filing periods ({available}){bound_note}"
    )


def load_delta(
    fund: FundRef,
    *,
    client: EdgarClient,
    settings: Settings,
    candidate_limit: int | None = None,
    as_of: dt.date | None = None,
) -> PortfolioDelta:
    """What changed for ``fund`` between its two most recent distinct reporting periods.

    ``as_of``, when given, bounds both periods to filings that were public on or before that date --
    see :func:`load_snapshots`'s docstring. ``None`` (the default) applies no bound -- unchanged
    behaviour for every existing caller. This parameter is what closes the lookahead hole confirmed
    against the live endpoint: a caller replaying a past session can pass that session's date and no
    longer see a filing that had not yet been made public as of it.

    Raises :class:`InsufficientHistory` -- never an empty
    :class:`~app.institutions.models.PortfolioDelta` -- when fewer than two usable periods are on
    record; see that exception's docstring for why the distinction matters. When ``as_of`` is the
    reason fewer than two periods survived, the message names the bound, so a reader does not
    conclude the filer has too little history rather than that the bound excluded some of it.
    """
    snapshots = load_snapshots(
        fund,
        client=client,
        settings=settings,
        limit=2,
        candidate_limit=candidate_limit,
        as_of=as_of,
    )
    pair = latest_pair(snapshots)
    if pair is None:
        count = len(snapshots)
        bound_note = (
            f" as_of={as_of.isoformat()} bound applied -- more recent filings may exist but were "
            "not yet public by that date."
            if as_of is not None
            else ""
        )
        raise InsufficientHistory(
            f"{fund.key!r} has only {count} usable filing period{'s' if count != 1 else ''} on "
            "record -- at least 2 are required to compute a change; check back after the next "
            f"quarterly filing.{bound_note}"
        )

    before, after = pair
    return diff(before, after)
