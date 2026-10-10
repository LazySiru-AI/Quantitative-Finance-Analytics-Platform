"""The catalog of tracked filers, and the CUSIP-to-ticker bridge built from the user's own ledger.

Two independent things live here because they are both small, static-ish lookups that the rest of
the package needs before it can do anything useful: which filers this app knows how to fetch (this
module's :data:`_DEFAULT_CATALOG`), and how to put a ticker on a CUSIP the SEC itself never labels
with one (:func:`ledger_cusip_tickers`).

**Why the CUSIP-to-ticker bridge is the user's ledger and not a lookup table.** Neither a 13F nor an
NPORT-P filing carries a ticker -- see :attr:`app.institutions.models.Holding.ticker` -- and there is
no free SEC endpoint that maps CUSIP to ticker; the mapping is commercial data guarded by the exact
identifier this problem needs. What the user's own broker exports *do* carry, because every broker
sends both, is a CUSIP next to the ticker they used for it -- but only for the securities the user
has actually traded. That is a narrow bridge, not a general one, and it is deliberately narrow: it
answers "which of *my* holdings did this institution just buy or sell", not "what is the ticker for
any CUSIP in the world". A CUSIP the user has never owned legitimately has no answer here, and
:func:`ledger_cusip_tickers` returns nothing for it rather than guessing from the issuer name -- see
that function's docstring for why fuzzy name matching is the wrong fallback, not a missing feature.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.config import Settings
from app.datasource import ledger_db_path
from app.db import sqlite as ledger
from app.institutions.models import FundRef, Holding, Snapshot, Source

__all__ = ["apply_tickers", "default_catalog", "find", "ledger_cusip_tickers"]


#: ETFs, addressed by (cik, series_id) -- an NPORT-P filer files one report per series, and a trust
#: like iShares Trust carries over a thousand of them, so the series id is what actually picks out
#: the fund. Every cik/series_id pair below was checked against a live SEC endpoint on 2026-08-18:
#: QQQ, IVV, VOO, SCHD and ARKK against the SEC's own filing history; VTI, IWM and XLE against
#: `tests/fixtures/institutions/sec_company_tickers_mf.json`, a real slice of
#: https://www.sec.gov/files/company_tickers_mf.json (columns `["cik","seriesId","classId","symbol"]`,
#: `cik` an int that needs zero-padding to 10 characters). See this module's docstring for `SPY`,
#: which is deliberately absent.
_ETFS: tuple[FundRef, ...] = (
    FundRef(
        key="QQQ",
        name="Invesco QQQ Trust",
        source=Source.NPORT,
        cik="0001067839",
        series_id="S000101292",
        ticker="QQQ",
    ),
    FundRef(
        key="IVV",
        name="iShares Core S&P 500 ETF",
        source=Source.NPORT,
        cik="0001100663",
        series_id="S000004310",
        ticker="IVV",
    ),
    FundRef(
        key="VOO",
        name="Vanguard S&P 500 ETF",
        source=Source.NPORT,
        cik="0000036405",
        series_id="S000002839",
        ticker="VOO",
    ),
    FundRef(
        key="VTI",
        name="Vanguard Total Stock Market ETF",
        source=Source.NPORT,
        cik="0000036405",
        series_id="S000002848",
        ticker="VTI",
    ),
    FundRef(
        key="IWM",
        name="iShares Russell 2000 ETF",
        source=Source.NPORT,
        cik="0001100663",
        series_id="S000004344",
        ticker="IWM",
    ),
    FundRef(
        key="SCHD",
        name="Schwab US Dividend Equity ETF",
        source=Source.NPORT,
        cik="0001454889",
        series_id="S000034163",
        ticker="SCHD",
    ),
    FundRef(
        key="ARKK",
        name="ARK Innovation ETF",
        source=Source.NPORT,
        cik="0001579982",
        series_id="S000042977",
        ticker="ARKK",
    ),
    FundRef(
        key="XLE",
        name="Energy Select Sector SPDR",
        source=Source.NPORT,
        cik="0001064641",
        series_id="S000006410",
        ticker="XLE",
    ),
)

#: 13F managers. No `series_id` -- a 13F filer has no series, it files one report covering its whole
#: reportable book. Every CIK below was confirmed live on 2026-08-18 against
#: `https://www.sec.gov/cgi-bin/browse-edgar` (company search, `type=13F`) or
#: `https://data.sec.gov/submissions/CIK##########.json`; see :func:`default_catalog`'s docstring
#: for the exact query used for each. A manager considered but not confirmable from either source is
#: left out entirely rather than guessed -- a wrong CIK here silently displays a different
#: institution's real portfolio under a famous name, which is worse than a short list.
#: 13F filers, each with the person the firm is publicly identified with where naming one is
#: honest. Every CIK below was resolved on 2026-08-18 from EDGAR's own company search and then
#: driven end to end through `service.load_delta` before being listed, because a wrong CIK does not
#: fail -- it silently shows a stranger's book under a famous name.
#:
#: `principal` is editorial and deliberately conservative. It is left unset where the famous name
#: no longer runs the firm: Renaissance's founder Jim Simons died in 2024, and Lone Pine's Stephen
#: Mandel stopped managing money in 2019, so attributing these books to them would be a claim about
#: the past dressed as one about the present.
_MANAGERS: tuple[FundRef, ...] = (
    FundRef(
        key="BRK",
        name="Berkshire Hathaway Inc",
        source=Source.THIRTEEN_F,
        cik="0001067983",
        principal="Warren Buffett",
    ),
    FundRef(
        key="ARKINVEST",
        name="ARK Investment Management LLC",
        source=Source.THIRTEEN_F,
        cik="0001697748",
        principal="Cathie Wood",
    ),
    FundRef(
        key="PERSHING",
        name="Pershing Square Capital Management, L.P.",
        source=Source.THIRTEEN_F,
        cik="0001336528",
        principal="Bill Ackman",
    ),
    FundRef(
        key="SCION",
        name="Scion Asset Management, LLC",
        source=Source.THIRTEEN_F,
        cik="0001649339",
        principal="Michael Burry",
    ),
    FundRef(
        key="APPALOOSA",
        name="Appaloosa LP",
        source=Source.THIRTEEN_F,
        cik="0001656456",
        principal="David Tepper",
    ),
    FundRef(
        key="DUQUESNE",
        name="Duquesne Family Office LLC",
        source=Source.THIRTEEN_F,
        cik="0001536411",
        principal="Stanley Druckenmiller",
    ),
    FundRef(
        key="SOROS",
        name="Soros Fund Management LLC",
        source=Source.THIRTEEN_F,
        cik="0001029160",
        principal="George Soros",
    ),
    FundRef(
        key="THIRDPOINT",
        name="Third Point LLC",
        source=Source.THIRTEEN_F,
        cik="0001040273",
        principal="Dan Loeb",
    ),
    FundRef(
        key="ELLIOTT",
        name="Elliott Investment Management L.P.",
        source=Source.THIRTEEN_F,
        cik="0001791786",
        principal="Paul Singer",
    ),
    FundRef(
        key="TIGERGLOBAL",
        name="Tiger Global Management LLC",
        source=Source.THIRTEEN_F,
        cik="0001167483",
        principal="Chase Coleman",
    ),
    FundRef(
        key="COATUE",
        name="Coatue Management LLC",
        source=Source.THIRTEEN_F,
        cik="0001135730",
        principal="Philippe Laffont",
    ),
    FundRef(
        key="LONEPINE",
        name="Lone Pine Capital LLC",
        source=Source.THIRTEEN_F,
        cik="0001061165",
    ),
    FundRef(
        key="BRIDGEWATER",
        name="Bridgewater Associates, LP",
        source=Source.THIRTEEN_F,
        cik="0001350694",
        principal="Ray Dalio",
    ),
    FundRef(
        key="RENTECH",
        name="Renaissance Technologies LLC",
        source=Source.THIRTEEN_F,
        cik="0001037389",
    ),
    # Added 2026-08-30. Same standard as the eleven above: resolved from EDGAR company search, then
    # driven end to end through `service.load_delta` with `as_of=2026-08-30` before being listed.
    # Two of these reverse documented exclusions -- see `default_catalog`'s docstring.
    FundRef(
        key="SITAWARE",
        name="Situational Awareness LP",
        source=Source.THIRTEEN_F,
        cik="0002045724",
        principal="Leopold Aschenbrenner",
    ),
    FundRef(
        key="BAUPOST",
        name="Baupost Group LLC",
        source=Source.THIRTEEN_F,
        cik="0001061768",
        principal="Seth Klarman",
    ),
    FundRef(
        key="ICAHN",
        name="Icahn Carl C",
        source=Source.THIRTEEN_F,
        cik="0000921669",
        principal="Carl Icahn",
    ),
    FundRef(
        key="POINT72",
        name="Point72 Asset Management, L.P.",
        source=Source.THIRTEEN_F,
        cik="0001603466",
        principal="Steven A. Cohen",
    ),
    FundRef(
        key="HIMALAYA",
        name="Himalaya Capital Management LLC",
        source=Source.THIRTEEN_F,
        cik="0001709323",
        principal="Li Lu",
    ),
    FundRef(
        key="ALTIMETER",
        name="Altimeter Capital Management, LP",
        source=Source.THIRTEEN_F,
        cik="0001541617",
        principal="Brad Gerstner",
    ),
    FundRef(
        key="D1",
        name="D1 Capital Partners L.P.",
        source=Source.THIRTEEN_F,
        cik="0001747057",
        principal="Daniel Sundheim",
    ),
    FundRef(
        key="CITADEL",
        name="Citadel Advisors LLC",
        source=Source.THIRTEEN_F,
        cik="0001423053",
        principal="Ken Griffin",
    ),
    FundRef(
        key="MILLENNIUM",
        name="Millennium Management LLC",
        source=Source.THIRTEEN_F,
        cik="0001273087",
        principal="Israel Englander",
    ),
    FundRef(
        key="AQR",
        name="AQR Capital Management LLC",
        source=Source.THIRTEEN_F,
        cik="0001167557",
        principal="Cliff Asness",
    ),
    # `principal` deliberately unset below, on the same rule Lone Pine and Renaissance are unset:
    # the famous name either no longer runs the firm (Akre Capital's founder stepped back in 2020;
    # Miller Value's founder handed the book on), or there is no single person the filer is
    # honestly identified with (Baillie Gifford and Two Sigma are firms, the Gates Foundation Trust
    # is an endowment, Whale Rock and Dragoneer are not household names in the way this field is
    # for). Set one only with a source; an unset field is not a gap to be filled in by guess.
    FundRef(
        key="MILLERVALUE",
        name="Miller Value Partners, LLC",
        source=Source.THIRTEEN_F,
        cik="0001135778",
    ),
    FundRef(
        key="WHALEROCK",
        name="Whale Rock Capital Management LLC",
        source=Source.THIRTEEN_F,
        cik="0001387322",
    ),
    FundRef(
        key="DRAGONEER",
        name="Dragoneer Investment Group, LLC",
        source=Source.THIRTEEN_F,
        cik="0001602189",
    ),
    FundRef(
        key="GATES",
        name="Gates Foundation Trust",
        source=Source.THIRTEEN_F,
        cik="0001166559",
    ),
    FundRef(
        key="AKRE",
        name="Akre Capital Management LLC",
        source=Source.THIRTEEN_F,
        cik="0001112520",
    ),
    FundRef(
        key="BAILLIE",
        name="Baillie Gifford & Co",
        source=Source.THIRTEEN_F,
        cik="0001088875",
    ),
    FundRef(
        key="TWOSIGMA",
        name="Two Sigma Investments, LP",
        source=Source.THIRTEEN_F,
        cik="0001179392",
    ),
)

_DEFAULT_CATALOG: tuple[FundRef, ...] = _ETFS + _MANAGERS


def default_catalog() -> tuple[FundRef, ...]:
    """The tracked filers this app knows how to fetch, ETFs first then 13F managers.

    Confirmed sources, one CIK / series id at a time:

    * ``QQQ``, ``IVV``, ``VOO``, ``SCHD``, ``ARKK`` -- given by the spec and cross-checked against
      `tests/fixtures/institutions/sec_company_tickers_mf.json`, which independently lists the same
      cik/seriesId pairs.
    * ``VTI``, ``IWM``, ``XLE`` -- read directly from that fixture, which is a real slice of
      `https://www.sec.gov/files/company_tickers_mf.json`.
    * ``BRK`` (Berkshire Hathaway Inc, cik 0001067983) -- given by the spec; independently confirmed
      2026-08-18 against `https://data.sec.gov/submissions/CIK0001067983.json`, which returns
      ``"name":"BERKSHIRE HATHAWAY INC"``.
    * ``BRIDGEWATER`` (Bridgewater Associates, LP, cik 0001350694) and ``RENTECH`` (Renaissance
      Technologies LLC, cik 0001037389) -- confirmed 2026-08-18 by querying
      `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=<name>&type=13F&output=atom`
      and reading the ``<cik>``/``<conformed-name>`` pair back from a live, currently-filing 13F-HR
      history (Bridgewater's latest filed 2026-08-14, Renaissance's 2026-08-13).

    * The eleven managers added later (``ARKINVEST``, ``PERSHING``, ``SCION``, ``APPALOOSA``,
      ``DUQUESNE``, ``SOROS``, ``THIRDPOINT``, ``ELLIOTT``, ``TIGERGLOBAL``, ``COATUE``,
      ``LONEPINE``) -- each resolved from EDGAR company search on 2026-08-18 and then driven end to
      end through :func:`app.institutions.service.load_delta`, which is the check that matters: a
      CIK that resolves is not the same as a filer whose documents parse into two comparable
      periods.

    ``SCION`` (Michael Burry) is included **and is stale by design of its filer, not of this list**:
    its most recent 13F-HR was filed 2025-11-03 and it reports the quarter ending 2025-09-30. It
    earns its place because the page states each filing's as-of and filed dates directly above the
    numbers, so a fund that has gone quiet reads as exactly that rather than as current holdings. An
    earlier revision left it out; that call was defensible, but hiding a filer is a worse answer
    than showing when it last spoke.

    * The seventeen managers added 2026-08-30 (``SITAWARE``, ``BAUPOST``, ``ICAHN``, ``POINT72``,
      ``HIMALAYA``, ``ALTIMETER``, ``D1``, ``CITADEL``, ``MILLENNIUM``, ``AQR``, ``MILLERVALUE``,
      ``WHALEROCK``, ``DRAGONEER``, ``GATES``, ``AKRE``, ``BAILLIE``, ``TWOSIGMA``) -- each resolved
      from EDGAR company search, disambiguated against
      `https://data.sec.gov/submissions/CIK##########.json` where the name search returned more than
      one filer, and then driven end to end through :func:`app.institutions.service.load_delta` with
      ``as_of=2026-08-30``. Every one returned two comparable periods ending 2026-06-30, filed
      2026-08-06 to 2026-08-14.

    **Two of those seventeen reverse exclusions this docstring previously recorded**, and the
    reversal is evidence, not a change of mind. ``BAUPOST`` was excluded because "name search
    returned no single unambiguous match" -- it returns two, and the submissions endpoint separates
    them cleanly: ``0001054420`` (BAUPOST GROUP LLC /ADV) last filed a 13F-HR in **2002**, while
    ``0001061768`` (BAUPOST GROUP LLC/MA) has 105 in its recent history, latest 2026-08-13. ``ICAHN``
    was excluded on Icahn Capital LP (0001412093, last 13F-HR 2011), which is genuinely dormant --
    but the live filer is ``0000921669`` (ICAHN CARL C), 47 recent 13F-HRs, latest 2026-08-14. The
    original exclusions were right about the CIKs they tested and wrong that no live CIK existed.

    **Five of the seventeen are not stock-picking books, and the list says so rather than letting a
    reader assume otherwise.** Position counts in the quarter ending 2026-06-30: ``CITADEL`` 13,575,
    ``MILLENNIUM`` 5,796, ``TWOSIGMA`` 5,017, ``POINT72`` 3,923, ``AQR`` 3,900. A NEW row in a book
    that size is a fraction of a percent of an index-like or systematic portfolio, not a decision
    comparable to a concentrated manager opening a position -- the same reason
    `app/paper/library/retired/D-13f-newbuys.json` excluded ``ARKINVEST`` from its universe while
    keeping it on this list. ``CITADEL`` also disclosed 7,901 option legs against 15,525 changed
    rows. They are included because this is a viewer and hiding a filer is worse than showing what
    it is; they are labelled because "Ken Griffin bought X" is a claim this data cannot support.

    Candidates looked up and **excluded** because their CIK could not be confirmed against a
    currently-filing 13F-HR history: Melvin Capital (0001628110, last 2023-10-05, fund closed) and
    Greenlight Capital Inc (0001079114, last 13F-HR **2024-02-14** -- re-checked 2026-08-30 and still
    dormant, so David Einhorn's current book is not on this list under any CIK). Excluded for a
    different reason: **Viking Global Investors LP** (0001103804) resolves to a live filer with 101
    recent 13F-HRs, but ``load_delta`` failed against it on 2026-08-30 with a
    :class:`~app.market.providers.base.ProviderResponseError` on its filing index, so it never
    cleared the end-to-end check the other seventeen did. It is a candidate to retry, not a
    rejection. A famous name over the wrong CIK is worse than an absent one, and a famous name whose
    documents this code cannot parse is worse than a short list.
    """
    return _DEFAULT_CATALOG


def find(key: str) -> FundRef | None:
    """Look up a tracked filer by its key, case-insensitively (``"qqq"`` matches ``"QQQ"``)."""
    target = key.lower()
    for fund in _DEFAULT_CATALOG:
        if fund.key.lower() == target:
            return fund
    return None


def ledger_cusip_tickers(settings: Settings) -> dict[str, str]:
    """``{cusip: ticker}`` for every instrument in the user's ledger that carries a CUSIP.

    Reads `instrument.cusip` and `instrument.primary_symbol` from the ledger at
    `settings.ledger_path`, opened read-only (this function never writes to the ledger). Rows with a
    null or empty CUSIP are skipped -- an `instrument` row with no CUSIP (an OTC name, a private
    placement, a broker that never supplied one) has nothing to bridge and must not appear in the
    result, not even as a `None` value.

    **Deliberately does not fall back to matching on issuer name.** The whole reason this bridge
    exists is that CUSIP is the only identifier both the SEC filing and the user's broker agree on;
    falling back to fuzzy name matching when a CUSIP is not in the user's ledger would reintroduce
    exactly the failure this package's CUSIP-first design exists to prevent (see
    :mod:`app.institutions.models`'s module docstring on "Bank America Corp" vs "Bank of Amer
    Corp") -- a name-based guess can attach a real ticker to the wrong company, which is worse than
    leaving the ticker unresolved. A CUSIP outside the set the user owns legitimately maps to
    nothing.

    Returns `{}`, not an error, when `settings.ledger_path` does not exist -- a fresh checkout or a
    settings fixture pointed at an empty temp directory has no ledger yet, and "no tickers resolved"
    is the correct, unremarkable answer for that case, not a crash.

    **Duplicate CUSIPs resolve deterministically.** The live schema's `ux_instrument_cusip` unique
    index means two `instrument` rows cannot in practice share one non-null CUSIP -- but this
    function does not assume that invariant holds, because `primary_symbol` itself is *not* unique
    (the same symbol legitimately appears under separate `instrument_id` rows imported from
    different brokers before `app.core.canonical.canonicalize_ledger` merges them at derive time),
    and a defensive read should not depend on a constraint enforced elsewhere. Rows are read ordered
    by `(cusip, primary_symbol)`, and the first `primary_symbol` seen for a given CUSIP wins --
    alphabetically smallest -- so the result is the same on every call against the same data,
    independent of SQLite's unspecified row order.
    """
    ledger_file = ledger_db_path(settings)
    if not ledger_file.exists():
        return {}

    tickers: dict[str, str] = {}
    with ledger.connect(ledger_file, read_only=True) as conn:
        rows = conn.execute(
            "SELECT cusip, primary_symbol FROM instrument "
            "WHERE cusip IS NOT NULL AND cusip != '' "
            "ORDER BY cusip, primary_symbol"
        ).fetchall()

    for row in rows:
        cusip = str(row["cusip"]).upper()
        tickers.setdefault(cusip, row["primary_symbol"])

    return tickers


def apply_tickers(snapshot: Snapshot, tickers: Mapping[str, str]) -> Snapshot:
    """A copy of `snapshot` with `Holding.ticker` filled in wherever its CUSIP is a known key.

    Models are frozen (`app.institutions.models._Frozen`), so this builds new `Holding` instances
    via `model_copy(update=...)` rather than mutating in place, and returns a new `Snapshot` wrapping
    them -- the input snapshot is never modified. A holding whose CUSIP is not in `tickers` is copied
    through unchanged, ticker and all, including a `None` it already had.
    """
    new_holdings = tuple(_apply_ticker(holding, tickers) for holding in snapshot.holdings)
    return snapshot.model_copy(update={"holdings": new_holdings})


def _apply_ticker(holding: Holding, tickers: Mapping[str, str]) -> Holding:
    ticker = tickers.get(holding.cusip.upper())
    if ticker is None:
        return holding
    return holding.model_copy(update={"ticker": ticker})
