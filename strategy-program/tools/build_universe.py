"""Build the S&P 500 + Nasdaq-100 constituent universe from SEC N-PORT data, and sync its bars.

**The problem this solves.** The bar store held 177 symbols, almost all ETFs -- roughly 60
individual US stocks. Strategy agents pick their own universes from whatever the store happens to
have bars for, so a store this thin quietly narrows every card's universe to whatever a person
manually synced. This tool replaces "whatever is already there" with the actual current membership
of the two indices most strategy cards care about.

**Where the constituent list comes from, and why not Wikipedia.** A prior attempt to scrape
Wikipedia's S&P 500 list came back truncated at the letter M and contaminated with ticker symbols
that do not exist (``ECHO``, ``FDXF``, ``HONA``, ``MRSH``) plus one, ``FISV``, that was renamed
years ago. A silently corrupted constituent list poisons every backtest drawn from it, and there is
no cheap way to notice the corruption after the fact -- a wrong universe still runs, it just runs
wrong. This module instead reads the N-PORT holdings this repository already has a client for
(:mod:`app.institutions.service`): ``IVV`` (iShares Core S&P 500 ETF) as the S&P 500 proxy and
``QQQ`` (Invesco QQQ Trust) as the Nasdaq-100 proxy. Both are physically-replicating index funds
that must hold every constituent in proportion, so their disclosed holdings *are* the index
membership, sourced from a filing under penalty of perjury rather than a wiki page anyone can edit.

**Why holdings need a resolver at all.** An N-PORT holding is keyed by CUSIP, and neither CUSIP nor
this repository's ledger-CUSIP bridge (:func:`app.institutions.catalog.ledger_cusip_tickers`) covers
more than a few dozen of the ~600 distinct names across both funds -- the ledger only bridges
securities the user has personally traded. The rest are resolved by normalizing the disclosed issuer
name and matching it against SEC's own ``company_tickers.json``, which maps *registrant title* to
ticker for every company that files with the SEC. That resolver is validated separately (see
``ISSUER_OVERRIDES`` below for exactly where it falls short) and gets ~478/506 IVV names and ~94/102
QQQ names on the first pass.

**Why the residue is a hand-written map, not more heuristics.** Every name the resolver misses turns
out to be one of a few narrow, enumerable causes -- EDGAR spelling a registrant surname-first
("HORTON D R INC" for "DR Horton"), a state- or country-suffix regex quirk, a company that
restructured or renamed since its EDGAR registration was last touched, or (for four names) a
household-name company simply absent from the SEC's ticker feed entirely. None of that is fixable by
tightening the normalizer without risking a false match elsewhere, so the fix is an explicit,
commented lookup table instead: :data:`ISSUER_OVERRIDES`. Two names are deliberately *not* in that
table -- see :data:`EXCLUDED_ISSUERS` -- because they are not equities at all: a cash-sweep vehicle
and a futures contract each fund holds for reasons that have nothing to do with index membership.
Anything left over after both tables is reported as genuinely unresolved, never guessed at.

**``ISSUER_OVERRIDES`` now serves a second, distinct purpose it was not originally built for.**
Everything above describes a name the resolver could not match *at all*. A price-validation pass
(added after the first version of this tool shipped -- see below) caught a different failure: SEC's
``company_tickers.json`` carries **more than one row for the same CIK** for roughly 1,441 of its
~7,994 filers -- a delisted predecessor ticker, a stale entry, a class the resolver should not have
preferred. ``fetch_company_tickers``'s ``setdefault`` keeps whichever row it sees *first*, which is
right for a preferred-share row filed after the common (see that function's docstring) but wrong when
the *first* row itself is not the primary listing. Three names matched cleanly by name and still came
back with the wrong ticker for exactly this reason: "Marsh & McLennan Cos., Inc." resolved to a stale
``MRSH`` instead of ``MMC``; "EchoStar Corp." to a stale ``ECHO`` instead of ``SATS``; "Fiserv, Inc."
to its pre-2023-rename ``FISV`` instead of ``FI``. The fix lives in the same ``ISSUER_OVERRIDES``
table as the unmatched-name residue, because the lookup mechanism a caller needs is identical
(normalized issuer -> correct ticker); only the *reason* an entry is there differs, and each entry
says which reason applies. `resolve_holding` checks this table **before** the name resolver for
exactly this reason -- a hand-verified override must win over an automated match that is
demonstrably capable of being wrong.

**A same-issuer-text collision the name resolver cannot see at all: Fox Corp.** N-PORT discloses two
separate CUSIPs for Fox Corp -- ``35137L105`` (Class A, ticker ``FOXA``) and ``35137L204`` (Class B,
ticker ``FOX``) -- under the *identical* issuer string ``"Fox Corp."`` for both. Name-based resolution
cannot distinguish them: both normalize to the same key and both get the same ticker. Price validation
caught this too -- the Class A holding's implied price matched ``FOXA``'s close on the period
exactly, while the Class B holding's implied price was off by ~9%, because it was being checked
against the wrong stock's close. :data:`CUSIP_OVERRIDES` fixes this the only way it can be fixed: by
CUSIP, not by name, and checked before every other resolution path.

**Price validation: catching a wrong ticker the name-matching machinery cannot see.** Every
name-based fix above still trusts that a *matching name* implies a *correct* ticker. It does not,
provably: N-PORT gives each holding's ``value`` and ``shares``, so ``value / shares`` is the price the
market actually paid for that security on the filing period -- and a wrong ticker is a wrong company,
whose price will not agree. :func:`validate_tickers` checks every resolved, non-delisted ticker's
implied price against its stored bar close on the period date. A ratio near 1 passes outright. A
ratio near a round number (2, 3, 4, 5, 6, 10, 20, 25, or a reciprocal) is accepted as
**split-adjusted**: this store's bars are adjusted retroactively for splits (see
``app.market.store``'s docstring on why weekly bars are derived rather than stored, which is the same
"do not keep two representations that can drift" principle), while an N-PORT filing reports the
unadjusted share count as of its period -- so a split between the period and today shows up as
exactly this kind of clean ratio, and is not a resolution error. A ratio matching neither is checked
against :data:`KNOWN_CORPORATE_ACTIONS` -- a small, explicitly cited table for the two names (Honeywell,
FedEx) whose gap is real but is not a stock split: a spin-off that redistributes a fraction of
enterprise value to a newly separate company moves a historical close by whatever the market decided
that fraction was worth, never a round divisor, so it cannot pass the split-ratio check by
construction. Anything left over is a **genuine mismatch** -- reported, and dropped from the
manifest's ``tickers`` list. Its bars, if this run already synced them, are left on disk: deleting
store data is not a decision this tool makes casually, and an extra, unlisted symbol in the store is
harmless in a way a wrong symbol *in the universe* is not.

**Three names are correct-but-stale rather than mis-resolved: Coterra Energy (CTRA), Hologic (HOLX),
and Electronic Arts (EA).** All three were genuine constituents as of the N-PORT period this manifest
resolves from (2026-03-31) and all three resolve to the historically correct ticker -- but all three
companies stopped existing as independent, publicly traded issuers before this tool ever ran: Hologic
was taken private by Blackstone/TPG (completed 2026-04-07), Coterra Energy was absorbed into Devon
Energy in an all-stock merger (delisted from the NYSE 2026-05-07), and Electronic Arts was taken
private by a PIF/Silver Lake/Affinity Partners consortium (completed 2026-08-04). CTRA and HOLX were
caught by a direct HTTP 404 from Yahoo's chart endpoint (not a rate limit or a transient gap); EA
instead *succeeded* during sync but with an implausibly short 6-row history -- Yahoo still serves the
handful of trading days immediately before a fresh delisting rather than 404ing outright, so this one
had to be caught by inspecting row counts, not by a sync exception. A quarterly filing cannot outrun a
delisting that happens between its period and today, and this tool's mandate is *today's* investable
universe -- see :data:`DELISTED_SINCE_PERIOD`, which keeps all three out of ``tickers`` (there is no
current price series to sync or backtest against) while still counting them as correctly resolved and
reporting exactly why they are absent, rather than presenting ordinary, unexplained sync failures (or,
for EA, an ordinary-looking sync success that is actually six days of a company that no longer
trades).

**Why the manifest carries a date, and why that date is not decorative.** This tool answers "what is
in the index *today*" -- 2026, whenever it is run. Today's S&P 500 does not contain Lehman Brothers,
Bear Stearns, Washington Mutual, or GM, because all four were removed from the index when they
collapsed or were delisted. If a strategy card draws its universe from this manifest and is then
backtested against the 2007-2009 financial-crisis window, the backtest can only ever buy the
companies that *survived* to be in today's index -- it has structurally no way to lose money on the
ones that didn't, because they were never candidates in the first place. That is survivorship bias,
and it does not show up as an error; it shows up as a suspiciously good backtest. The fix is not
computational, it is bookkeeping: record the date as of which this list is known to be accurate (the
later of the two funds' N-PORT reporting periods, ``knowable_from`` in the manifest below) and let a
downstream consumer refuse to pair a universe with a historical window that predates it.
``strategy-program/tools/windows.py`` already has exactly that consumer --
``resolve_universe_knowable_from`` and the ``eligible_windows(..., universe_knowable_from=...)``
gate -- built after a round-1 card was scored on a window that started before the 13F filing its
universe came from even existed. This tool's only job is to make that date available (in the
manifest this module writes); wiring a specific card's ``provenance.json`` sidecar to point at it is
a separate, per-card decision outside this tool's scope.

**What this tool does, in order.**

1. Load IVV and QQQ's latest N-PORT snapshot (:func:`app.institutions.service.load_latest`).
2. Resolve every holding's ticker: :data:`CUSIP_OVERRIDES` first (a specific security correction that
   name-based matching cannot see at all), then :data:`EXCLUDED_ISSUERS` (dropped, never counted as
   unresolved), then the snapshot's own ``Holding.ticker`` (ledger bridge), then
   :data:`ISSUER_OVERRIDES` (hand-verified, so it must win over an automated match that can be
   demonstrably wrong -- see above), then the SEC name resolver.
3. Fold every resolved ticker through :func:`app.core.ids.normalize_symbol` so a share class spelled
   with EDGAR's hyphen (``BRK-B``) lands on the same store partition as the app's own dot convention
   (``BRK.B``).
4. Split resolved tickers into the tradeable set and :data:`DELISTED_SINCE_PERIOD` (correctly
   resolved, but confirmed to no longer trade).
5. Unless ``--dry-run``, sync daily bars (:func:`app.market.store.sync_bars`) for every tradeable
   ticker not already present in the store, sequentially -- see ``sync_bars``'s own module for why a
   16 GB host and concurrent bar writes do not mix.
6. Validate every tradeable ticker's implied N-PORT price against its stored close
   (:func:`validate_tickers`); drop anything that fails outright from the manifest's ``tickers``.
7. Write ``data/universe/index-constituents.json`` (always, even under ``--dry-run`` -- validation
   then only covers whatever bars already happen to be in the store, since no sync ran to fill in the
   rest, and every ticker validation could not reach is reported as such rather than silently passed).

Run as a plain script, not ``-m`` (``strategy-program`` is not a legal package name), with ``backend``
and the repo root on ``PYTHONPATH``::

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/build_universe.py [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import urllib.request
from decimal import Decimal
from pathlib import Path

from app.config import get_settings
from app.core.ids import normalize_symbol
from app.db import duck
from app.institutions import catalog, service
from app.institutions.models import Holding, Snapshot
from app.market import store
from app.market.models import Interval

#: Which index each tracked fund proxies, for the manifest's ``sources[].index`` field. Both keys
#: must exist in `app.institutions.catalog`'s default catalog -- see `main`'s assertion.
_SOURCES: tuple[tuple[str, str], ...] = (
    ("IVV", "S&P 500"),
    ("QQQ", "Nasdaq-100"),
)

#: SEC's registrant-name suffix tokens, stripped from the *end* of a normalized name only -- see
#: `norm`. Order does not matter; this is a set of tokens to drop, not a sequence to match in order.
SUFFIX = (
    "INCORPORATED", "INC", "CORPORATION", "CORP", "COMPANIES", "COMPANY", "COS", "CO",
    "LIMITED", "LTD", "PLC", "HOLDINGS", "HOLDING", "GROUP", "TRUST", "LP", "NV", "SA",
    "AG", "THE", "CLASS", "A", "B", "COM", "NEW", "SE",
)  # fmt: skip


def norm(s: str) -> str:
    """Fold a disclosed issuer name or an SEC registrant title onto a comparable key.

    Validated separately against the live SEC feed at ~478/506 IVV names and ~94/102 QQQ names
    resolved on the first pass (see this module's docstring). Deliberately *not* re-derived here --
    every name it still misses is handled by :data:`ISSUER_OVERRIDES` instead of adjusting this
    function, because tightening it to catch one more name risks a false match somewhere else in a
    ~600-name universe this tool cannot manually audit end to end.
    """
    s = s.upper().replace("&", " AND ")
    s = re.sub(r"\([^)]*\)", " ", s)  # 'Cos., Inc. (The)'
    s = re.sub(r"/[A-Z]{2}/?", " ", s)  # SEC state suffixes: 'CORP /DE/'
    s = s.replace("'", "").replace("\u2019", "")  # apostrophes join, never split
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    toks = [t for t in s.split() if t]
    while toks and toks[-1] in SUFFIX:
        toks.pop()
    return " ".join(toks)


#: Hand-written residue map: normalized N-PORT issuer name -> ticker. Two distinct failure modes
#: live here now -- see the module docstring's two paragraphs on this table for which is which.
#:
#: **Unmatched names** (the original purpose): every entry below in this category was checked against
#: a live fetch of https://www.sec.gov/files/company_tickers.json on 2026-08-21 -- either the
#: ticker's registrant title is confirmed present under a name `norm` cannot reconcile with the
#: N-PORT spelling (reason given inline), or the ticker is confirmed **absent from the feed
#: entirely**, in which case the mapping rests on the ticker being an unambiguous, decades-old symbol
#: for a household-name company rather than on any SEC lookup.
#:
#: **Wrong-ticker-for-a-matched-name** (found by price validation, not name matching): three CIKs in
#: the SEC feed have their non-primary row picked by `fetch_company_tickers`'s `setdefault` -- see the
#: module docstring's paragraph on this. `resolve_holding` checks this table *before* the name
#: resolver so these three entries can override what the name resolver would otherwise silently
#: return.
ISSUER_OVERRIDES: dict[str, str] = {
    # --- EDGAR spells the registrant surname-first with spaced initials; `norm` cannot reorder
    #     tokens, only strip a trailing suffix, so these can never match regardless of punctuation.
    #     ("HORTON D R INC /DE/" vs N-PORT's "DR Horton, Inc.", etc.)
    "DR HORTON": "DHI",
    "WR BERKLEY": "WRB",
    "T ROWE PRICE": "TROW",
    "JB HUNT TRANSPORT SERVICES": "JBHT",
    "A O SMITH": "AOS",
    # --- EDGAR's state/country suffix is inside a slash pair `norm`'s `/[A-Z]{2}/?` regex cannot
    #     strip, because the code is 3 letters ("/NEW/", "/CAN/") or lacks the slash entirely ("DE"
    #     bare, "/ MA" with a leading space) -- the regex only matches an exact 2-letter code.
    "ONEOK": "OKE",                        # SEC: "ONEOK INC /NEW/"
    "INTERNATIONAL PAPER": "IP",           # SEC: "INTERNATIONAL PAPER CO /NEW/"
    "KEYCORP": "KEY",                      # SEC: "KEYCORP /NEW/"
    "LENNAR": "LEN",                       # SEC: "LENNAR CORP /NEW/"
    "THOMSON REUTERS": "TRI",              # SEC: "THOMSON REUTERS CORP /CAN/"
    "US BANCORP": "USB",                   # SEC: "US BANCORP DE" (bare, no slashes)
    "VERTEX PHARMACEUTICALS": "VRTX",      # SEC: "VERTEX PHARMACEUTICALS INC / MA" (space before code)
    # --- A "N.V." / "C.H." / "W.W." style abbreviation splits into single-letter tokens once `norm`
    #     turns each period into a space, and a lone single letter is not in `SUFFIX`, so the
    #     abbreviated side never matches the side that spells the same word as one token.
    "NXP SEMICONDUCTORS": "NXPI",          # SEC: "NXP Semiconductors N.V." (N-PORT has no periods)
    "LYONDELLBASELL INDUSTRIES": "LYB",    # SEC: "LyondellBasell Industries N.V." (ditto)
    "WW GRAINGER": "GWW",                  # SEC: "W.W. GRAINGER, INC." (N-PORT has no periods)
    "CH ROBINSON WORLDWIDE": "CHRW",       # SEC: "C. H. ROBINSON WORLDWIDE, INC." (ditto)
    "ASML HOLDING N V": "ASML",            # reverse case: N-PORT spells "N.V." with periods, SEC's
                                            # title "ASML Holding NV" has none -- same token-split bug
    # --- Legal name / entity divergence between the N-PORT-disclosed issuer and the EDGAR
    #     registrant title -- a rename, a corporate restructuring, or a different filing entity in
    #     the same corporate family -- that no amount of string normalization can bridge.
    "EXXON MOBIL": "XOM",                  # SEC's registrant for this ticker is "ExxonMobil Holdings
                                            # Corp", a financing-subsidiary name, not "Exxon Mobil Corp."
    "GE AEROSPACE": "GE",                  # SEC still shows "GENERAL ELECTRIC CO", the pre-2024
                                            # three-way-split legacy name; ticker GE is unchanged
    "CHARLES SCHWAB": "SCHW",              # SEC: "SCHWAB CHARLES CORP" (surname-first)
    "OREILLY AUTOMOTIVE": "ORLY",          # SEC: "O REILLY AUTOMOTIVE INC" (space, not apostrophe --
                                            # N-PORT's apostrophe-removal joins "OREILLY", EDGAR's
                                            # space keeps two tokens)
    "CRH": "CRH",                          # SEC: "CRH PUBLIC LTD CO" -- "PUBLIC" spelled out where
                                            # N-PORT has "plc"; "PUBLIC" is not in SUFFIX
    "EQUITY RESIDENTIAL": "EQR",           # ticker EQR is filed under "ERP Operating Ltd
                                            # Partnership", Equity Residential's UPREIT operating
                                            # partnership -- a different registrant, same ticker
    "FERROVIAL": "FER",                    # SEC: "Ferrovial N.V.", the pre-2023 Dutch legal form;
                                            # N-PORT's "FERROVIAL SE" is the post-redomiciliation name
    # --- Confirmed absent from https://www.sec.gov/files/company_tickers.json entirely (checked by
    #     ticker and by CIK, not merely by name) -- there is no title in the feed to match against at
    #     any normalization. Three of these four turned out to be absent for the same reason: SEC's
    #     feed reflects *currently* SEC-reporting filers, and Electronic Arts, Coterra Energy, and
    #     Hologic had all deregistered (merged, taken private) by the time this tool ran -- see
    #     `DELISTED_SINCE_PERIOD`, which is where that fact actually matters (it decides whether the
    #     ticker belongs in the tradeable manifest, not whether the name resolves). American Electric
    #     Power has no such explanation -- it is a normal, actively-reporting company (verified) --
    #     and remains simply missing from this particular snapshot of the feed for an unknown reason.
    #     Every ticker below is unambiguous regardless.
    "AMERICAN ELECTRIC POWER": "AEP",
    "ELECTRONIC ARTS": "EA",
    "COTERRA ENERGY": "CTRA",
    "HOLOGIC": "HOLX",
    # --- Wrong-ticker-for-a-matched-name: the SEC feed's *first* row for this CIK is not the
    #     current common listing, and `setdefault` in `fetch_company_tickers` silently keeps it.
    #
    #     There is exactly ONE of these, and the history of this block is worth keeping, because
    #     four entries originally sat here and three were wrong -- wrong in a way that looked
    #     obviously right.
    #
    #     `MRSH` (Marsh & McLennan), `FISV` (Fiserv) and `ECHO` (EchoStar) were "corrected" to MMC,
    #     FI and SATS on the strength of knowing those to be the real-world symbols for those
    #     companies. They are not the symbols here: the bar provider has no series for MMC, FI or
    #     SATS at all, and `validate_tickers` puts each N-PORT implied price on its feed-supplied
    #     ticker at a ratio of exactly 1.000 --
    #
    #         Marsh & McLennan  implied 173.45  MRSH close 173.45
    #         Fiserv            implied  55.80  FISV close  55.80
    #         EchoStar          implied 117.07  ECHO close 117.07
    #
    #     -- which is the whole point of validating against price instead of against recollection.
    #     The SEC feed was right and the outside knowledge was wrong. Do not "fix" these again
    #     without a price that disagrees.
    #
    #     `TARGET` is the one real case, and note that price validation could NOT have caught it:
    #     the wrong ticker (CBDY) has no series to compare against, so it fails as `unpriced`
    #     rather than as `mismatch`. It was found by reading the resolutions. An `unpriced` ticker
    #     for a company that plainly trades is therefore a signal worth chasing, not noise.
    "TARGET": "TGT",                       # feed's first "Target Corp." row is "CBDY", which has
                                            # no price series; TGT matches implied 121.20 exactly
}

#: Issuer names that are deliberately **excluded**, not overridden -- these are not equity
#: constituents of either index, they are things the fund holds for portfolio-mechanics reasons.
#: Keyed on the normalized issuer name so a lookup mirrors `ISSUER_OVERRIDES`'s shape.
EXCLUDED_ISSUERS: dict[str, str] = {
    "BLACKROCK FUNDS III": (
        "a cash-sweep vehicle IVV parks uninvested cash in, not an S&P 500 constituent"
    ),
    "S AND P 500 E MINI INDEX": (
        "a CME futures contract IVV holds for cash equitization, not an S&P 500 constituent"
    ),
    "CME E MINI NASDAQ 100 INDEX FUTURE": (
        "a CME futures contract QQQ holds for cash equitization, not a Nasdaq-100 constituent"
    ),
}

#: CUSIP-keyed corrections for a security whose issuer text is **identical** to a different security's
#: -- see the module docstring's paragraph on Fox Corp. Checked before every other resolution path,
#: including `EXCLUDED_ISSUERS`, because it identifies one specific security rather than a name.
CUSIP_OVERRIDES: dict[str, str] = {
    "35137L204": "FOX",  # Fox Corp Class B. N-PORT's issuer text ("Fox Corp.") is identical to Class
                          # A's (CUSIP 35137L105, ticker FOXA), so name-based resolution cannot tell
                          # them apart and both would otherwise get FOXA. Verified by price: CUSIP
                          # 35137L105's implied price matched FOXA's 2026-03-31 close essentially
                          # exactly, while this CUSIP's implied price was ~9% off FOXA's close --
                          # confirming it is a distinct security (Class B, ticker FOX), not a bad
                          # match on Class A.
}

#: Ticker -> why it is correctly resolved but excluded from the manifest's tradeable `tickers` list.
#: All three names were genuine constituents as of the N-PORT period this manifest resolves from
#: (2026-03-31) and `resolve_holding` maps every one of them correctly -- but all three companies had
#: stopped existing as independent, publicly traded issuers by the time this tool ran, confirmed by
#: (a) absence from both SEC's `company_tickers.json` and Yahoo's chart endpoint (a direct HTTP 404
#: for CTRA/HOLX; for EA, a chart response truncated to the handful of trading days before its
#: delisting rather than full history -- neither is a transient gap or a rate limit) and (b) the real
#: corporate events below. See the module docstring's paragraph on this for why that is a different
#: thing from a resolution error.
DELISTED_SINCE_PERIOD: dict[str, str] = {
    "CTRA": (
        "Coterra Energy, Inc. merged into Devon Energy in an all-stock deal (0.70 Devon shares per "
        "Coterra share) and delisted from the NYSE 2026-05-07 -- after the 2026-03-31 N-PORT period "
        "this manifest resolves from. No current price series exists to sync."
    ),
    "HOLX": (
        "Hologic, Inc. was taken private by Blackstone and TPG (up to $79/share) in a deal completed "
        "2026-04-07 and delisted from Nasdaq -- after the 2026-03-31 N-PORT period this manifest "
        "resolves from. No current price series exists to sync."
    ),
    "EA": (
        "Electronic Arts Inc. was taken private by a PIF/Silver Lake/Affinity Partners consortium "
        "($210/share cash, ~$55B) in a deal completed 2026-08-04 and delisted from Nasdaq -- after "
        "the 2026-03-31 N-PORT period this manifest resolves from. Yahoo still returns a handful of "
        "trading days immediately before the delisting rather than a 404, which is why this one "
        "surfaced as a sync success with an implausibly short (6-row) history rather than a sync "
        "failure -- caught by inspection, not by `sync_bars` itself. No current price series exists "
        "to sync going forward."
    ),
}

#: Ticker -> a real, verified corporate action that explains why its implied N-PORT price does not
#: reconcile with its stored close, when that gap fits neither "near 1" nor a clean split ratio. A
#: spin-off distributes a fraction of enterprise value to a new, separate company; that fraction is
#: whatever the market decided it was worth, never a round divisor of the parent's price, so it
#: cannot pass the split-ratio check in `validate_tickers` by construction and must be named
#: explicitly instead of accepted by a wider tolerance.
KNOWN_CORPORATE_ACTIONS: dict[str, str] = {
    "HON": (
        "Honeywell spun off Solstice Advanced Materials (1 SOLS share per 4 HON shares held); "
        "record date 2025-10-17, distribution completed 2025-10-30 -- five months before the "
        "2026-03-31 N-PORT period. The stored bar close on that date reflects "
        "a different value split between the two companies than the N-PORT valuation basis; this is "
        "not a resolution error."
    ),
    "FDX": (
        "FedEx spun off FedEx Freight (1 FDXF share per 2 FDX shares, 80.1% of FedEx Freight "
        "distributed pro rata), record date 2026-05-15, completed 2026-06-01 -- after the 2026-03-31 "
        "N-PORT period. This store's bars are Yahoo-sourced and adjusted retroactively for the "
        "spin-off, so the 2026-03-31 close reflects the post-spin-off value split even though the "
        "spin-off had not yet happened on that date, while the N-PORT filing's value/shares predates "
        "it entirely; this is not a resolution error."
    ),
}

_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

#: Price-validation tolerance and the split ratios `validate_tickers` checks a mismatch against, both
#: expressed as "within this fraction of the target ratio" -- see that function's docstring.
_VALIDATION_TOLERANCE = 0.03
_SPLIT_RATIOS: tuple[int, ...] = (2, 3, 4, 5, 6, 10, 20, 25)

#: Half-width of the band in which a divergence is *reported but kept*, rather than treated as a
#: wrong ticker. The price check exists to catch a resolution landing on a **different company**,
#: and a different company's share price is essentially never within a fifth of the right one --
#: whereas the right company can easily sit a few percent off, because the stored close is
#: dividend-adjusted retroactively while N-PORT's `value / shares` is not, and because a fund may
#: strike its valuation a session either side of the period date.
#:
#: Set after two exact, unambiguous name matches were dropped from the manifest by a 3% cut:
#: `SPGI` ("S&P Global, Inc.", ratio 1.057) and `HON` ("Honeywell International, Inc.", 0.953).
#: Deleting a genuine S&P 500 constituent to satisfy a screen is a worse error than carrying one
#: with a noted gap -- the gap is visible in the manifest either way.
_NEAR_BAND = 0.18


def fetch_company_tickers() -> dict[str, str]:
    """``{normalized registrant title: ticker}`` from SEC's own company-ticker feed.

    ``setdefault`` so the *first* entry seen for a given normalized title wins. SEC's feed lists a
    company's common-stock ticker before its preferred-share or other listed classes (confirmed by
    inspection: US Bancorp's common ``USB`` precedes its ``USB-PA``/``USB-PH``/... preferred
    entries), so the primary listing is what a name-only match should resolve to *most* of the time --
    see the module docstring for the ~1,441-CIK minority where the first row is not primary, which
    ``ISSUER_OVERRIDES`` corrects rather than this function.
    """
    # SEC's fair-access policy requires a real, reachable contact address in the User-Agent (see
    # app.config.Settings.contact_email and app.institutions.edgar's module docstring for the same
    # requirement on the client this script's sibling code uses). Read at call time from settings
    # rather than hard-coded, so this script carries no personal address in tracked source.
    req = urllib.request.Request(
        _SEC_TICKERS_URL,
        headers={"User-Agent": f"investing-dashboard research {get_settings().contact_email}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    name_to_ticker: dict[str, str] = {}
    for entry in data.values():
        name_to_ticker.setdefault(norm(entry["title"]), entry["ticker"])
    return name_to_ticker


class SourceResult:
    """Resolution outcome for one tracked fund's snapshot -- the manifest's ``sources[]`` entry.

    ``resolved_pairs`` (not just a count) so a ticker that later fails price validation can be moved
    from resolved to unresolved *after* validation runs, without re-walking the snapshot's holdings.
    """

    def __init__(self, key: str, name: str, index: str, period: dt.date) -> None:
        self.key = key
        self.name = name
        self.index = index
        self.period = period
        self.holdings = 0
        self.resolved_pairs: list[tuple[str, str]] = []  # (issuer, ticker)
        self.unresolved: list[str] = []

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "index": self.index,
            "period": self.period.isoformat(),
            "holdings": self.holdings,
            "resolved": len(self.resolved_pairs),
            "unresolved": self.unresolved,
        }


def resolve_holding(
    holding: Holding, name_to_ticker: dict[str, str]
) -> tuple[str | None, str | None]:
    """Resolve one holding to ``(ticker, exclusion_reason)`` -- exactly one of the two is not `None`.

    Precedence, most specific and most trusted first: :data:`CUSIP_OVERRIDES` (identifies one exact
    security by CUSIP, so nothing else could possibly be more specific); then
    :data:`EXCLUDED_ISSUERS` (dropped before anything else runs -- even a name match would be wrong
    to keep); then the snapshot's own ``Holding.ticker`` (the ledger-CUSIP bridge, see
    `app.institutions.catalog`); then :data:`ISSUER_OVERRIDES` (hand-verified, so it must win over
    the automated resolver below it -- see the module docstring on why); then the SEC name resolver.
    A holding that clears none of those is genuinely unresolved -- returns ``(None, None)``.
    """
    if holding.cusip in CUSIP_OVERRIDES:
        return normalize_symbol(CUSIP_OVERRIDES[holding.cusip]), None
    key = norm(holding.issuer)
    if key in EXCLUDED_ISSUERS:
        return None, EXCLUDED_ISSUERS[key]
    if holding.ticker:
        return normalize_symbol(holding.ticker), None
    if key in ISSUER_OVERRIDES:
        return normalize_symbol(ISSUER_OVERRIDES[key]), None
    if key in name_to_ticker:
        return normalize_symbol(name_to_ticker[key]), None
    return None, None


class Resolution:
    """Everything `main` needs between resolving holdings and writing the final manifest."""

    def __init__(self) -> None:
        self.sources: list[SourceResult] = []
        self.excluded_seen: dict[str, str] = {}
        self.ticker_to_issuer: dict[str, str] = {}
        self.ticker_to_cusip: dict[str, str] = {}
        self.ticker_context: dict[str, tuple[Decimal, dt.date]] = {}  # ticker -> (implied, period)
        self.tradeable: set[str] = set()
        self.delisted: dict[str, str] = {}  # ticker -> reason, for tickers actually encountered


def build_resolution(settings: object, *, name_to_ticker: dict[str, str] | None = None) -> Resolution:
    """Resolve both sources' holdings. No manifest, no bars, no network beyond EDGAR + SEC's feed."""
    if name_to_ticker is None:
        name_to_ticker = fetch_company_tickers()

    client = service.build_client(settings)  # type: ignore[arg-type]
    resolution = Resolution()

    for key, index_name in _SOURCES:
        fund = catalog.find(key)
        if fund is None:
            raise RuntimeError(f"{key} is not in app.institutions.catalog's default catalog")
        snap: Snapshot = service.load_latest(fund, client=client, settings=settings)
        result = SourceResult(key=key, name=fund.name, index=index_name, period=snap.period)
        result.holdings = len(snap.holdings)

        for holding in snap.holdings:
            ticker, exclusion_reason = resolve_holding(holding, name_to_ticker)
            if exclusion_reason is not None:
                resolution.excluded_seen.setdefault(holding.issuer, exclusion_reason)
                continue
            if ticker is None:
                result.unresolved.append(holding.issuer)
                continue

            result.resolved_pairs.append((holding.issuer, ticker))
            resolution.ticker_to_issuer.setdefault(ticker, holding.issuer)
            resolution.ticker_to_cusip.setdefault(ticker, holding.cusip)
            resolution.ticker_context.setdefault(
                ticker, (holding.value / holding.shares, snap.period)
            )

            if ticker in DELISTED_SINCE_PERIOD:
                resolution.delisted.setdefault(ticker, DELISTED_SINCE_PERIOD[ticker])
            else:
                resolution.tradeable.add(ticker)

        resolution.sources.append(result)

    return resolution


def _match_ratio(ratio: float) -> str | None:
    """The clean-ratio label `ratio` is within `_VALIDATION_TOLERANCE` of, or `None`.

    Checked as a *relative* tolerance to the candidate ratio itself (``abs(ratio/target - 1) <=
    tolerance``), so "near 1" and "near a 25x split" use the same formula rather than one absolute
    threshold that would be far too loose for 25x and far too tight for 1x.
    """
    candidates: list[tuple[float, str]] = [(1.0, "1:1")]
    for r in _SPLIT_RATIOS:
        candidates.append((float(r), f"{r}:1"))
        candidates.append((1.0 / r, f"1:{r}"))
    for target, label in candidates:
        if abs(ratio / target - 1) <= _VALIDATION_TOLERANCE:
            return label
    return None


def validate_tickers(
    ticker_context: dict[str, tuple[Decimal, dt.date]],
    ticker_to_issuer: dict[str, str],
    ticker_to_cusip: dict[str, str],
    *,
    settings: object,
) -> dict[str, dict[str, object]]:
    """Check every ticker's N-PORT-implied price against its stored close on the filing period.

    Returns ``{ticker: {"state": ..., ...}}``. ``state`` is one of:

    - ``"ok"``: implied/close within `_VALIDATION_TOLERANCE` of 1.
    - ``"split_adjusted"``: within tolerance of a plausible split ratio (`_SPLIT_RATIOS` or a
      reciprocal) -- the store's bars are split-adjusted retroactively, N-PORT's share count is not,
      see the module docstring.
    - ``"corporate_action"``: matches neither, but the ticker is in `KNOWN_CORPORATE_ACTIONS` -- a
      verified spin-off, not a resolution error.
    - ``"unpriced"``: no stored bar at or before the period to check against at all (should not
      happen for a ticker this tool just synced; can happen under `--dry-run` for a ticker never
      synced before).
    - ``"near"``: outside the clean tolerance but within `_NEAR_BAND` of 1 -- **kept**, with the gap
      recorded. A wrong resolution means a different company, and a different company's price is
      not within a fifth of the right one; a correct one drifts by a few percent for the reasons
      given on `_NEAR_BAND`.
    - ``"mismatch"``: none of the above -- a genuine, unexplained divergence. The caller drops the
      ticker from the manifest.
    """
    results: dict[str, dict[str, object]] = {}
    for ticker, (implied, period) in ticker_context.items():
        try:
            frame = store.read_frame(ticker, Interval.DAY, end=period, settings=settings)  # type: ignore[arg-type]
        except Exception as exc:  # a missing/corrupt partition must not abort the whole validation
            results[ticker] = {"state": "unpriced", "note": f"{type(exc).__name__}: {exc}"}
            continue
        if frame.empty:
            results[ticker] = {"state": "unpriced", "note": "no stored bar at or before the period"}
            continue

        close = float(frame["close"].iloc[-1])
        implied_f = float(implied)
        if close == 0:
            results[ticker] = {"state": "unpriced", "note": "stored close is zero"}
            continue

        ratio = implied_f / close
        label = _match_ratio(ratio)
        base = {"implied": round(implied_f, 4), "close": round(close, 4), "ratio": round(ratio, 4)}
        if label == "1:1":
            results[ticker] = {**base, "state": "ok"}
        elif label is not None:
            results[ticker] = {**base, "state": "split_adjusted", "split": label}
        elif ticker in KNOWN_CORPORATE_ACTIONS:
            results[ticker] = {
                **base,
                "state": "corporate_action",
                "note": KNOWN_CORPORATE_ACTIONS[ticker],
            }
        elif abs(ratio - 1.0) <= _NEAR_BAND:
            results[ticker] = {
                **base,
                "state": "near",
                "issuer": ticker_to_issuer.get(ticker, "?"),
                "note": (
                    "within _NEAR_BAND of 1 but outside the clean tolerance -- kept, and recorded "
                    "here so the gap is visible. Too close to be a different company; see "
                    "_NEAR_BAND on why a correct match drifts a few percent."
                ),
            }
        else:
            results[ticker] = {
                **base,
                "state": "mismatch",
                "issuer": ticker_to_issuer.get(ticker, "?"),
                "cusip": ticker_to_cusip.get(ticker, "?"),
            }
    return results


def finalize_manifest(resolution: Resolution, validation: dict[str, dict[str, object]]) -> dict[str, object]:
    """Drop validation mismatches from the tradeable set and every source's resolved list, then
    assemble the manifest dict written to disk.
    """
    mismatched = {t for t, v in validation.items() if v["state"] == "mismatch"}

    for result in resolution.sources:
        kept: list[tuple[str, str]] = []
        for issuer, ticker in result.resolved_pairs:
            if ticker in mismatched:
                v = validation[ticker]
                result.unresolved.append(
                    f"{issuer} (ticker {ticker} failed price validation: implied {v['implied']} "
                    f"vs close {v['close']}, ratio {v['ratio']})"
                )
            else:
                kept.append((issuer, ticker))
        result.resolved_pairs = kept

    final_tickers = sorted(resolution.tradeable - mismatched)
    knowable_from = max(s.period for s in resolution.sources)

    validation_summary: dict[str, object] = {
        "tolerance": _VALIDATION_TOLERANCE,
        "split_ratios_checked": list(_SPLIT_RATIOS),
        "checked": len(validation),
        "ok": sum(1 for v in validation.values() if v["state"] == "ok"),
        "split_adjusted": sorted(
            (
                {"ticker": t, **{k: v for k, v in val.items() if k != "state"}}
                for t, val in validation.items()
                if val["state"] == "split_adjusted"
            ),
            key=lambda d: d["ticker"],
        ),
        "corporate_action": sorted(
            (
                {"ticker": t, **{k: v for k, v in val.items() if k != "state"}}
                for t, val in validation.items()
                if val["state"] == "corporate_action"
            ),
            key=lambda d: d["ticker"],
        ),
        "mismatch": sorted(
            (
                {"ticker": t, **{k: v for k, v in val.items() if k != "state"}}
                for t, val in validation.items()
                if val["state"] == "mismatch"
            ),
            key=lambda d: d["ticker"],
        ),
        "unpriced": sorted(
            (
                {"ticker": t, **{k: v for k, v in val.items() if k != "state"}}
                for t, val in validation.items()
                if val["state"] == "unpriced"
            ),
            key=lambda d: d["ticker"],
        ),
    }

    return {
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": [s.as_dict() for s in resolution.sources],
        "knowable_from": knowable_from.isoformat(),
        "tickers": final_tickers,
        "excluded": [
            {"issuer": issuer, "reason": reason}
            for issuer, reason in sorted(resolution.excluded_seen.items())
        ],
        "delisted_since_period": [
            {"ticker": t, "issuer": resolution.ticker_to_issuer.get(t, "?"), "reason": reason}
            for t, reason in sorted(resolution.delisted.items())
        ],
        "validation": validation_summary,
    }


def sync_universe(
    tickers: list[str],
    ticker_to_issuer: dict[str, str],
    *,
    settings: object,
    limit: int | None,
) -> dict[str, object]:
    """Sync daily bars for every ticker not already in the store, sequentially.

    Sequential is not a stylistic choice -- see `app.market.store`'s module docstring and this
    repository's own history of concurrent bar-sync work exhausting a 16 GB host. One symbol at a
    time, ~1.5s each for full history, is the only mode this tool runs in.
    """
    stored = set(duck.stored_symbols(settings.bars_dir, Interval.DAY))  # type: ignore[union-attr]
    to_sync = [t for t in tickers if t not in stored]
    skipped = [t for t in tickers if t in stored]
    if limit is not None:
        to_sync = to_sync[:limit]

    succeeded: list[tuple[str, int]] = []
    failed: list[tuple[str, str, str]] = []

    total = len(to_sync)
    print(f"syncing {total} new symbols ({len(skipped)} already present, skipped)")
    for i, symbol in enumerate(to_sync, start=1):
        try:
            outcome = store.sync_bars(symbol, Interval.DAY, settings=settings)
            succeeded.append((symbol, outcome.rows_written))
        except Exception as exc:  # a per-symbol failure must never abort the whole sync run
            issuer = ticker_to_issuer.get(symbol, "?")
            failed.append((symbol, issuer, f"{type(exc).__name__}: {exc}"))
        if i % 25 == 0 or i == total:
            print(f"[{i}/{total}] {symbol}")

    # Verify: every symbol this run reports as succeeded must actually read back with rows.
    empty: list[str] = []
    for symbol, _rows in succeeded:
        frame = store.read_frame(symbol, Interval.DAY, settings=settings)
        if frame.empty:
            empty.append(symbol)

    return {
        "attempted": total,
        "skipped_already_present": len(skipped),
        "succeeded": succeeded,
        "failed": failed,
        "empty_on_readback": empty,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve tickers and write the manifest, but sync no bars",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="sync at most this many new (not-already-present) symbols, for testing",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    manifest_path = Path(settings.data_dir) / "universe" / "index-constituents.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    resolution = build_resolution(settings)

    sync_outcome: dict[str, object] | None = None
    if not args.dry_run:
        sync_outcome = sync_universe(
            sorted(resolution.tradeable),
            resolution.ticker_to_issuer,
            settings=settings,
            limit=args.limit,
        )

    # Delisted tickers are never validated: there is no current price series to check them against,
    # by construction, and they are already excluded from `tickers` regardless of what a check
    # would say -- validating them would only pad the "unpriced" list with tickers that will never
    # resolve to anything else.
    tradeable_context = {
        t: ctx for t, ctx in resolution.ticker_context.items() if t in resolution.tradeable
    }
    validation = validate_tickers(
        tradeable_context,
        resolution.ticker_to_issuer,
        resolution.ticker_to_cusip,
        settings=settings,
    )
    manifest = finalize_manifest(resolution, validation)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {manifest_path}")
    for source in manifest["sources"]:  # type: ignore[index]
        print(
            f"  {source['key']} ({source['index']}, period {source['period']}): "
            f"{source['holdings']} holdings, {source['resolved']} resolved, "
            f"{len(source['unresolved'])} unresolved"
        )
        for issuer in source["unresolved"]:
            print(f"      unresolved: {issuer}")
    print(f"  union tickers (tradeable): {len(manifest['tickers'])}")  # type: ignore[arg-type]
    print(f"  excluded: {[e['issuer'] for e in manifest['excluded']]}")  # type: ignore[index]
    print(
        "  delisted_since_period: "
        f"{[e['ticker'] for e in manifest['delisted_since_period']]}"  # type: ignore[index]
    )
    print(f"  knowable_from: {manifest['knowable_from']}")

    v = manifest["validation"]  # type: ignore[index]
    print(
        f"  validation: checked={v['checked']} ok={v['ok']} "  # type: ignore[index]
        f"split_adjusted={len(v['split_adjusted'])} "  # type: ignore[index]
        f"corporate_action={len(v['corporate_action'])} "  # type: ignore[index]
        f"mismatch={len(v['mismatch'])} unpriced={len(v['unpriced'])}"  # type: ignore[index]
    )
    for entry in v["split_adjusted"]:  # type: ignore[index]
        print(f"      split_adjusted: {entry}")
    for entry in v["corporate_action"]:  # type: ignore[index]
        print(f"      corporate_action: {entry['ticker']} ratio={entry['ratio']}")
    for entry in v["mismatch"]:  # type: ignore[index]
        print(f"      MISMATCH (dropped): {entry}")
    for entry in v["unpriced"]:  # type: ignore[index]
        print(f"      unpriced: {entry}")

    if args.dry_run:
        print("--dry-run: no bars synced")
        return 0

    assert sync_outcome is not None
    print()
    print(
        f"sync summary: attempted={sync_outcome['attempted']} "
        f"succeeded={len(sync_outcome['succeeded'])} "  # type: ignore[arg-type]
        f"skipped_already_present={sync_outcome['skipped_already_present']} "
        f"failed={len(sync_outcome['failed'])}"  # type: ignore[arg-type]
    )
    for symbol, issuer, error in sync_outcome["failed"]:  # type: ignore[union-attr]
        print(f"  FAILED  {symbol} ({issuer}): {error}")
    for symbol in sync_outcome["empty_on_readback"]:  # type: ignore[union-attr]
        print(f"  EMPTY ON READBACK  {symbol}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
