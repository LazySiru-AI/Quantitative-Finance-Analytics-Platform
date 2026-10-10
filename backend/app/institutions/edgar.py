"""Read-only SEC EDGAR client for resolving a tracked fund or manager to its filings.

This module answers two questions and no more: *which filings has this filer made*, and *where,
inside one of those filings, does the document holding its portfolio live*. It does not open that
document -- parsing a 13F information table or an NPORT-P ``primary_doc.xml`` into
:class:`~app.institutions.models.Holding` rows is a different worker's job, and keeping this module
ignorant of that format is what lets the two be built, tested and changed independently.

Four SEC quirks drive the shape of this client, each documented at its point of use because each
one silently produces a wrong or empty answer if missed:

* **A descriptive ``User-Agent`` is mandatory.** SEC's fair-access policy 403s a generic or
  default HTTP client identity.
* **The fund ticker map has no entry for every ETF.** SPY is a unit investment trust and is
  addressed by CIK alone, with no series id -- a lookup miss is the ordinary shape of that case,
  not a failure.
* **A CIK's submissions feed cannot pick one fund out of a multi-fund trust.** iShares Trust
  carries over a thousand NPORT-P filings under one CIK; only the browse-edgar Atom feed, queried
  by series id, narrows that to one fund.
* **Filing order is not period order.** iShares filed an NPORT-P on 2026-07-13 reporting the
  period ending 2025-09-30, *after* one filed 2026-05-28 reporting 2026-03-31. This module has no
  way to know a filing's reported period without opening the document -- that is the parser's job
  -- so it never claims to return "the latest" filing. It returns filing metadata in the order EDGAR
  serves it and leaves period-based ordering to the caller, after parsing.
"""

from __future__ import annotations

import datetime as dt
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Final

import httpx

from app.config import get_settings
from app.institutions.models import Source
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
)

__all__ = ["EdgarClient", "FilingRef"]


def _default_user_agent() -> str:
    """SEC's mandatory contact-address User-Agent, read from settings at call time.

    See `app.market.providers.sec_edgar._default_user_agent` for why this is a function called
    from `__init__` rather than a module-level literal or a frozen default-argument value: it lets
    each new client pick up whatever `.env`/`INVDASH_CONTACT_EMAIL` says at construction time.
    """
    return get_settings().contact_email

_TICKERS_MF_URL: Final[str] = "https://www.sec.gov/files/company_tickers_mf.json"
_SUBMISSIONS_URL: Final[str] = "https://data.sec.gov/submissions/CIK{cik10}.json"
_BROWSE_ATOM_URL: Final[str] = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcompany&CIK={series_id}&type={form}&dateb=&owner=include&count={count}&output=atom"
)
_ATOM_NS: Final[dict[str, str]] = {"atom": "http://www.w3.org/2005/Atom"}

#: Attempts and backoff for a transient EDGAR failure -- a timeout, a transport error, or a 5xx --
#: inside :meth:`EdgarClient._get`. Two tries, ~0.3s apart. See that method's docstring for the live
#: failure (a VTI `list_series_filings` call that timed out once and succeeded moments later) this
#: exists to absorb. Deliberately small and deliberately bounded: SEC's fair-access policy is the
#: reason this client exists in its current cautious form at all, so this is one extra attempt for
#: a momentary blip, not a hammering loop -- and it excludes 429 and non-429 4xx entirely (see the
#: docstring) because neither of those is the kind of failure one more try fixes.
_MAX_ATTEMPTS: Final[int] = 2
_RETRY_BACKOFF_SECONDS: Final[float] = 0.3


def _form_matches(actual: str, wanted: str) -> bool:
    """True when ``actual`` is exactly ``wanted`` or its ``/A`` amendment.

    An amendment supersedes the filing it corrects, so a caller asking for ``"13F-HR"`` almost
    always wants to see ``"13F-HR/A"`` too and decide for itself which one to use -- excluding
    amendments here would silently hide the corrected numbers and leave the caller looking at data
    the filer itself walked back.
    """
    return actual == wanted or actual == f"{wanted}/A"


@dataclass(frozen=True, slots=True)
class FilingRef:
    """One filing's identity and timing -- not its contents.

    Deliberately not in :mod:`app.institutions.models`: that module is the wire contract for
    *parsed* portfolio data, and a ``FilingRef`` carries none of that -- just enough to name a
    document on EDGAR and let the caller decide what, if anything, to do with it.
    """

    accession: str
    """Dashed, e.g. ``"0001193125-26-352200"`` -- the same form
    :attr:`app.institutions.models.Snapshot.accession` uses and that
    :meth:`EdgarClient.holdings_document_url` expects."""

    filing_date: dt.date
    """When this was filed with the SEC. **Not** the period the filing reports on -- see the
    module docstring on why filing date does not sort filings into period order."""

    form: str
    """As reported by EDGAR, e.g. ``"13F-HR"``, ``"13F-HR/A"``, ``"NPORT-P"``. An ``/A`` suffix
    marks an amendment; see :func:`_form_matches` for why this module returns both the original
    and its amendments rather than picking one."""

    report_date: dt.date | None = None
    """The period this filing reports *as of* -- the quarter end, straight from the submissions
    JSON's ``reportDate`` array (parallel to ``accessionNumber``/``filingDate``/``form``).

    Populated by :meth:`EdgarClient.list_filings` only. A Form 13F information table (what
    :func:`app.institutions.parse.parse_13f` actually reads) has no period-of-report field of its
    own -- that date lives on the filing's separate cover page, which is a different document this
    package never opens -- so without this field the caller would have no way to supply
    ``parse_13f``'s required ``period`` argument short of guessing from ``filing_date``, and the
    offset between filing date and quarter end is not fixed (45 days is a deadline, not a
    schedule).

    **Always ``None`` from :meth:`EdgarClient.list_series_filings`.** The browse-edgar Atom feed
    that method parses carries no ``reportDate``-equivalent element at all -- confirmed against the
    real ``sec_browse_atom_ivv.xml`` fixture, whose ``<content>`` blocks carry only
    ``accession-number``, ``filing-date`` and ``filing-type``. This is not a gap to close: an
    NPORT-P's period comes from ``<repPdDate>`` *inside* the document itself (see
    :func:`app.institutions.parse.parse_nport` and point 6 of that module's docstring), so a caller
    fetching NPORT filings was always going to open the document to learn the period, and there is
    nothing this method could populate here that would not be redundant with that read -- or, worse,
    wrong, since :func:`parse_nport`'s docstring documents a real filing where the fiscal
    ``repPdEnd`` and the true as-of ``repPdDate`` disagree by two fiscal quarters."""


class EdgarClient:
    """Resolves a tracked filer to its filings and to the URL of its holdings document.

    Every method maps failures onto the provider exception vocabulary from
    :mod:`app.market.providers.base` -- :class:`~app.market.providers.base.ProviderUnavailable` for
    timeouts and transport errors, :class:`~app.market.providers.base.RateLimited` for HTTP 429 (SEC
    does throttle, and honours ``Retry-After`` when it sends one), and
    :class:`~app.market.providers.base.ProviderResponseError` for any other non-200 status and for a
    response that parses but does not have the shape this client expects. That last case matters as
    much as the network ones: a payload missing an expected key must not surface as a bare
    ``KeyError`` two frames away from where the HTTP call happened.
    """

    name = "edgar"

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 15.0,
        user_agent: str | None = None,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._user_agent = user_agent if user_agent is not None else _default_user_agent()
        # ticker (upper) -> (cik10, series_id). None until the first lookup; the map is ~1.2MB and
        # changes rarely enough that refetching it per call would be pure waste.
        self._fund_map: dict[str, tuple[str, str]] | None = None

    # -- transport ------------------------------------------------------------------------------

    def _get(self, url: str) -> httpx.Response:
        """Issue one GET with SEC's mandatory ``User-Agent``, mapping transport and status failures.

        Shared by every endpoint below, JSON and Atom XML alike, so the mapping from HTTP outcome
        to provider exception lives in exactly one place rather than being re-derived per method.

        Retries :data:`_MAX_ATTEMPTS` times, with a short pause, for the failure modes that are
        ordinarily a momentary blip rather than a real outage: a timeout, a transport-level error,
        or a 5xx. A single such response used to fail the whole call outright -- and a single call
        to :func:`app.institutions.service.load_snapshots` for an NPORT filer opens *every*
        candidate's document serially (:func:`app.institutions.service._snapshots_nport`, because an
        NPORT candidate carries no period metadata the way a 13F's does -- see that function's
        docstring), up to ten HTTP round trips for the ordinary two-snapshot case. One transient SEC
        hiccup anywhere in that chain aborted the entire request with no recovery, which is exactly
        the shape of failure a live probe against VTI reproduced: `list_series_filings` timed out on
        its very first call and the whole `load_latest` failed, even though the identical call
        succeeded a few seconds later. **Not** retried: a 429 (see :class:`RateLimited` -- SEC is
        explicitly asking for less traffic, and hammering it again is the wrong response) or a
        non-429 4xx (:class:`ProviderResponseError` -- a malformed URL or a changed endpoint shape
        does not become well-formed by asking again).
        """
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = self._client.get(url, headers={"User-Agent": self._user_agent})
            except httpx.TimeoutException as exc:
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_BACKOFF_SECONDS)
                    continue
                raise ProviderUnavailable(
                    f"edgar timed out fetching {url}", provider=self.name
                ) from exc
            except httpx.TransportError as exc:
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_BACKOFF_SECONDS)
                    continue
                raise ProviderUnavailable(
                    f"edgar transport error fetching {url}: {exc}", provider=self.name
                ) from exc

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                raise RateLimited(
                    f"edgar rate-limited {url}",
                    provider=self.name,
                    retry_after=float(retry_after) if retry_after else None,
                )
            if response.status_code >= 500:
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_BACKOFF_SECONDS)
                    continue
                raise ProviderUnavailable(
                    f"edgar returned {response.status_code} for {url}", provider=self.name
                )
            if response.status_code >= 400:
                raise ProviderResponseError(
                    f"edgar returned unexpected status {response.status_code} for {url}",
                    provider=self.name,
                )
            return response

        # Unreachable: every branch inside the loop either returns, raises, or (on a
        # non-final attempt) continues. Satisfies the type checker, which cannot see that the
        # final iteration always raises rather than falling through.
        raise AssertionError(f"edgar retry loop exited without a response for {url}")  # pragma: no cover

    def _get_json(self, url: str) -> Any:
        response = self._get(url)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"edgar response from {url} was not valid JSON", provider=self.name
            ) from exc

    def _get_xml(self, url: str) -> ET.Element:
        response = self._get(url)
        try:
            return ET.fromstring(response.text)
        except ET.ParseError as exc:
            raise ProviderResponseError(
                f"edgar response from {url} was not valid XML", provider=self.name
            ) from exc

    # -- fund resolution --------------------------------------------------------------------------

    def _load_fund_map(self) -> dict[str, tuple[str, str]]:
        if self._fund_map is None:
            payload = self._get_json(_TICKERS_MF_URL)
            try:
                fields: list[str] = payload["fields"]
                rows: list[list[Any]] = payload["data"]
                cik_index = fields.index("cik")
                series_index = fields.index("seriesId")
                symbol_index = fields.index("symbol")
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderResponseError(
                    f"edgar fund ticker map at {_TICKERS_MF_URL} is missing an expected field",
                    provider=self.name,
                ) from exc

            mapping: dict[str, tuple[str, str]] = {}
            try:
                for row in rows:
                    symbol = row[symbol_index]
                    cik = row[cik_index]
                    series_id = row[series_index]
                    if not symbol or cik is None or not series_id:
                        continue
                    # `cik` arrives as a JSON int (36405, not "0000036405"). Every other EDGAR
                    # endpoint this client calls is keyed on the 10-digit zero-padded string form --
                    # `data.sec.gov/submissions/CIK36405.json` 404s where
                    # `CIK0000036405.json` succeeds -- so the padding happens once, here, rather
                    # than being re-derived (or forgotten) at every call site.
                    mapping[str(symbol).upper()] = (f"{int(cik):010d}", str(series_id))
            except (TypeError, IndexError, ValueError) as exc:
                raise ProviderResponseError(
                    f"edgar fund ticker map at {_TICKERS_MF_URL} has a malformed row",
                    provider=self.name,
                ) from exc
            self._fund_map = mapping
        return self._fund_map

    def resolve_fund(self, ticker: str) -> tuple[str, str] | None:
        """Ticker to ``(cik10, series_id)`` via ``company_tickers_mf.json``.

        Returns ``None`` when the ticker is absent from the map, and that is the expected outcome
        for some real, actively-tracked ETFs -- not an error condition to raise on. SPY is the
        clearest case: it is a unit investment trust, not a registered fund with a series, so it
        never appears on this endpoint at all and is instead addressed by CIK alone (``0000884394``)
        with no series id. A caller resolving SPY must fall back to a hardcoded or separately
        configured CIK; this method's job stops at reporting that the map has nothing to offer.
        """
        return self._load_fund_map().get(ticker.upper())

    # -- filing listings --------------------------------------------------------------------------

    def list_filings(self, cik: str, form: str, *, limit: int = 8) -> list[FilingRef]:
        """Filings for a CIK (typically a 13F-filing manager), via the submissions API.

        ``cik`` must already be the 10-digit zero-padded form (:attr:`FundRef.cik
        <app.institutions.models.FundRef.cik>` is documented to carry exactly that).

        The submissions JSON carries **no series id**, so this method cannot pick one fund out of a
        multi-fund trust -- iShares Trust alone carries over a thousand NPORT-P filings under one
        CIK. Use :meth:`list_series_filings` for that case instead.

        The ``filings.recent`` page is a truncation of the full filing history, not the whole of
        it (older filings move to the paginated ``filings.files`` entries this method does not
        follow); for locating a *recent* holdings document -- the only use this package has for it
        -- that truncation is not a problem.

        Results preserve the order EDGAR returns them in (newest filed first), never re-sorted by
        this method. See the module docstring: filing order is not period order, and this method
        has no way to know a filing's reported period without opening the document -- except for
        the period itself, which the submissions JSON's ``reportDate`` array gives for free; see
        :attr:`FilingRef.report_date`.
        """
        url = _SUBMISSIONS_URL.format(cik10=cik)
        payload = self._get_json(url)
        try:
            recent = payload["filings"]["recent"]
            accession_numbers: list[str] = recent["accessionNumber"]
            filing_dates: list[str] = recent["filingDate"]
            report_dates: list[str] = recent["reportDate"]
            forms: list[str] = recent["form"]
        except (KeyError, TypeError) as exc:
            raise ProviderResponseError(
                f"edgar submissions at {url} is missing the expected filings.recent arrays",
                provider=self.name,
            ) from exc

        results: list[FilingRef] = []
        try:
            rows = zip(accession_numbers, filing_dates, report_dates, forms, strict=True)
        except ValueError as exc:
            raise ProviderResponseError(
                f"edgar submissions at {url} has mismatched filings.recent arrays",
                provider=self.name,
            ) from exc

        for accession, filing_date, report_date, filed_form in rows:
            if not _form_matches(filed_form, form):
                continue
            try:
                parsed_filing_date = dt.date.fromisoformat(filing_date)
            except ValueError as exc:
                raise ProviderResponseError(
                    f"edgar submissions at {url} has an unparseable filingDate {filing_date!r}",
                    provider=self.name,
                ) from exc
            # `reportDate` is `""` for filing types that have no period of report -- not observed
            # for a 13F-HR in a real submissions payload, but the field's own JSON schema allows an
            # empty string generically, and this method must not crash on it just because every
            # fixture and every filer probed so far happens to fill it in.
            parsed_report_date = None
            if report_date:
                try:
                    parsed_report_date = dt.date.fromisoformat(report_date)
                except ValueError as exc:
                    raise ProviderResponseError(
                        f"edgar submissions at {url} has an unparseable reportDate {report_date!r}",
                        provider=self.name,
                    ) from exc
            results.append(
                FilingRef(
                    accession=accession,
                    filing_date=parsed_filing_date,
                    form=filed_form,
                    report_date=parsed_report_date,
                )
            )
            if len(results) >= limit:
                break
        return results

    def list_series_filings(self, series_id: str, form: str, *, limit: int = 8) -> list[FilingRef]:
        """Filings for one fund series (an ETF inside a multi-fund trust), via the browse-edgar
        Atom feed.

        This is the only endpoint that can isolate one series' filings: the submissions JSON used
        by :meth:`list_filings` has no concept of a series at all.

        Same non-guarantee as :meth:`list_filings` on ordering: results come back in EDGAR's own
        (newest-filed-first) order and are not re-sorted by reported period.
        """
        url = _BROWSE_ATOM_URL.format(series_id=series_id, form=form, count=limit)
        root = self._get_xml(url)

        results: list[FilingRef] = []
        for entry in root.findall("atom:entry", _ATOM_NS):
            content = entry.find("atom:content", _ATOM_NS)
            if content is None:
                continue

            filing_type_el = content.find("atom:filing-type", _ATOM_NS)
            if filing_type_el is None or filing_type_el.text is None:
                continue
            filed_form = filing_type_el.text
            if not _form_matches(filed_form, form):
                continue

            # `accession-nunber` (missing the second `m`) is a misspelling long reported in
            # EDGAR's Atom output. It is **not** what SEC serves today: three live feeds probed on
            # 2026-08-18 -- this series' NPORT-P feed, a by-CIK feed, and the current-filings
            # feed -- carry only the correct spelling, as does the captured fixture. The fallback
            # stays because it costs one dictionary lookup on a path that has already failed, and
            # the failure it guards is silent: a feed served with the typo would parse cleanly and
            # yield zero filings, which this client cannot distinguish from "this fund has not
            # filed". It is deliberately unproven defensiveness, not an observed bug.
            accession_el = content.find("atom:accession-number", _ATOM_NS)
            if accession_el is None:
                accession_el = content.find("atom:accession-nunber", _ATOM_NS)
            if accession_el is None or accession_el.text is None:
                continue

            date_el = content.find("atom:filing-date", _ATOM_NS)
            if date_el is None or date_el.text is None:
                continue
            try:
                parsed_date = dt.date.fromisoformat(date_el.text)
            except ValueError as exc:
                raise ProviderResponseError(
                    f"edgar atom feed at {url} has an unparseable filing-date {date_el.text!r}",
                    provider=self.name,
                ) from exc

            results.append(
                FilingRef(accession=accession_el.text, filing_date=parsed_date, form=filed_form)
            )
            if len(results) >= limit:
                break
        return results

    # -- holdings document location ----------------------------------------------------------------

    def holdings_document_url(self, cik: str, accession: str, source: Source) -> str:
        """The URL of the document, inside one filing, that actually holds the portfolio.

        ``cik`` is the zero-padded 10-digit string; the directory listing itself is addressed by
        the CIK with leading zeros stripped, which this method does internally. ``accession`` may
        be dashed or not -- the directory listing itself is addressed without dashes, which this
        method also does internally.

        The rule differs by :class:`~app.institutions.models.Source` because the two filing types
        lay out their holdings document differently:

        * **NPORT**: the holdings live directly in ``primary_doc.xml``. The submissions JSON's
          ``primaryDocument`` field points at ``"xslFormNPORT-P_X01/primary_doc.xml"`` instead --
          an XSL-rendered *HTML* view meant for a person reading it in a browser, not the
          machine-readable XML a parser wants. Following that path hands the parser an HTML page
          it cannot read as NPORT data; the raw file sits at the top of the same directory under
          the same filename, which is what this method returns instead.
        * **13F**: ``primary_doc.xml`` is the cover page only -- filer identity, no positions. The
          actual information table is a *second*, arbitrarily-named XML file in the same directory
          (a real one: ``56757.xml``). Returning ``primary_doc.xml`` here would hand the parser a
          filing with zero holdings in it.
        """
        cik_int = int(cik)
        accession_no_dashes = accession.replace("-", "")
        base_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_no_dashes}"
        index_url = f"{base_url}/index.json"

        payload = self._get_json(index_url)
        try:
            items = payload["directory"]["item"]
            names = [str(item["name"]) for item in items]
        except (KeyError, TypeError) as exc:
            raise ProviderResponseError(
                f"edgar filing index at {index_url} is missing the expected directory.item listing",
                provider=self.name,
            ) from exc

        if source is Source.NPORT:
            if "primary_doc.xml" not in names:
                raise ProviderResponseError(
                    f"edgar filing index at {index_url} has no primary_doc.xml for an NPORT filing",
                    provider=self.name,
                )
            filename = "primary_doc.xml"
        elif source is Source.THIRTEEN_F:
            candidates = sorted(
                name for name in names if name.endswith(".xml") and name != "primary_doc.xml"
            )
            if not candidates:
                raise ProviderResponseError(
                    f"edgar filing index at {index_url} has no non-primary XML document for a "
                    "13F filing",
                    provider=self.name,
                )
            filename = candidates[0]
        else:
            raise ProviderResponseError(
                f"edgar has no holdings-document rule for source {source!r}", provider=self.name
            )

        return f"{base_url}/{filename}"
