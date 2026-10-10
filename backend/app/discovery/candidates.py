"""What the selector is allowed to consider at a point in time -- and who supplies that list.

**Why this is a protocol and not a constant.** Every universe in this repository so far has been a
tuple of tickers written down by an analyst in 2026 (`app.evolution.universe`'s pools, and
`universe` on all 29 cards in `app.paper.library`). That is defensible for validation -- "does this
strategy work on these names" -- and fatal for discovery, which asks the opposite question: *would a
rule, given only what was knowable at the time, have found the thing that went up?* A selector graded
on a candidate list drawn after the fact answers that question with a number that cannot be wrong,
because every candidate it could possibly pick is a name that survived to be written down.

So the candidate set is an *input to be swapped*, not a constant to be edited. :class:`CandidateSet`
is the seam. Two implementations are intended and one exists:

* :class:`StoredETFCandidates` -- sector and theme ETFs read out of the local bar store, filtered by
  what had actually begun trading as of the asking date. Buildable today, and the bias it carries is
  small enough to state precisely (see :data:`SECTOR_ETF_ROSTER`). This is the sector track.
* A point-in-time constituent provider carrying names that later delisted -- the single-ticker track.
  Not implemented here, because the bar store contains no delisted names at all (measured: of
  ``LEH``, ``BSC``, ``WAMU``, ``YHOO``, ``SIVB`` and ``FRC``, none are present, and ``GM``'s first
  stored bar is 2010-11-17, the post-bankruptcy relisting rather than the company that failed). That
  is a data-sourcing problem, not a code problem, and this protocol is the shape the answer has to
  arrive in when it is sourced.

**The one rule every implementation owes its caller.** ``symbols_as_of(t)`` may consult nothing that
was unknowable at ``t``. Fund inception dates qualify -- a fund that had not launched could not have
been bought. Membership lists published later do not, however tempting, and neither does "this ticker
still exists in 2026", which is the assumption that makes the whole exercise circular.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.config import Settings
from app.evolution.universe import bars_before

__all__ = [
    "SECTOR_ETF_ROSTER",
    "THEME_ETF_ROSTER",
    "CandidateSet",
    "StoredETFCandidates",
    "sector_candidates",
    "theme_candidates",
]


@runtime_checkable
class CandidateSet(Protocol):
    """The instruments a selector may choose between, as of a date.

    Deliberately narrow: a provider answers "what could have been chosen on this day" and nothing
    else. It does not rank, score, or express a view -- that is the selector's job, and keeping the
    two apart is what lets one selector be graded against a survivor-only candidate set and a
    survivorship-free one with the difference between the two results meaning something.
    """

    @property
    def name(self) -> str:
        """Short identifier recorded alongside every exam result, so a stored result always says
        which candidate set produced it. An exam run against two providers is two different
        experiments and must never be pooled."""
        ...

    def symbols_as_of(self, as_of: dt.date) -> tuple[str, ...]:
        """Every symbol choosable on `as_of`, sorted. Must not depend on anything later than
        `as_of`."""
        ...


#: Sector, industry and theme ETFs with enough history to be worth asking about.
#:
#: **This roster was chosen in 2026 and is therefore not perfectly clean.** The honest statement of
#: the residual bias: ETFs do close, and a roster written today omits the ones that did. What makes
#: that a much smaller problem than the equivalent for single stocks is *why* they close. A company
#: delists because it failed, so a survivor-only stock list is selected directly on the outcome being
#: measured. A fund closes because it failed to gather assets, which correlates with its sector being
#: unfashionable but far more loosely -- and the funds below persisted through every regime in the
#: window matrix regardless of how their sector did: XLE through the 2014-2020 energy collapse, XLF
#: and KRE through 2008. The bias is real, second-order, and not zero. It is not a licence to call a
#: result from this roster survivorship-free.
#:
#: Every symbol here was confirmed present in the store, with the first-bar date noted. The nine
#: SPDR sectors all begin 1998-12-21; the rest carry their own inception because the as-of filter in
#: :meth:`StoredETFCandidates.symbols_as_of` turns those dates into real exclusions on the earlier
#: windows, which is the behaviour being bought.
SECTOR_ETF_ROSTER: tuple[str, ...] = (
    # The nine original SPDR sectors -- 1998-12-21, available for every window in the matrix.
    "XLB",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLU",
    "XLV",
    "XLY",
    # Industry and theme funds, with first stored bar.
    "SMH",  # semiconductors, 2000-06-04
    "SOXX",  # semiconductors, 2001-07-12
    "IGV",  # software, 2001-07-16
    "IBB",  # biotech, 2001-02-11
    "XBI",  # biotech, equal-weight, 2006-02-05
    "ITA",  # aerospace and defence, 2006-05-04
    "GDX",  # gold miners, 2006-05-21
    "KRE",  # regional banks, 2006-06-21
    "XOP",  # oil and gas E&P, 2006-06-21
    "VNQ",  # REITs, 2004-09-28
    "DBC",  # broad commodities, 2006-02-05
    # Late arrivals -- excluded from the early windows by the as-of filter, which is the point.
    "XLRE",  # real estate, 2015-10-07
    "XLC",  # communication services, 2018-06-18
)


#: :data:`SECTOR_ETF_ROSTER` widened with narrow thematic funds -- the shape "the next semiconductors"
#: would actually arrive in.
#:
#: **Why a second roster instead of widening the first.** The sector roster asks a clean question and
#: carries a small, statable bias. Adding theme funds asks a *better* question -- a broad sector fund
#: could never have expressed "semiconductors in 2016" the way SOXX did, and the concentrated bets
#: that run hardest are exactly the narrow ones -- but it pays for that with a materially worse
#: survivorship problem, because thematic ETFs close at a far higher rate than SPDR sectors and their
#: closures *are* correlated with the theme having failed. Every fund below launched, gathered assets
#: and survived to 2026; the cohort it was drawn from includes a long tail of theme funds that did not,
#: and this repository has no record of them.
#:
#: So the two rosters are kept separate and both are run. A result that holds on the sector roster and
#: strengthens on this one is interesting; a result that appears *only* here is the more likely to be
#: an artifact of which themes happened to survive, and should be read that way.
THEME_ETF_ROSTER: tuple[str, ...] = (
    *SECTOR_ETF_ROSTER,
    "XHB",  # homebuilders, 2006-02-05
    "XRT",  # retail, 2006-06-21
    "SLV",  # silver, 2006-04-27
    "USO",  # oil, 2006-04-09
    "NLR",  # nuclear, 2007-08-14
    "TAN",  # solar, 2008-04-14
    "ICLN",  # clean energy, 2008-06-24
    "GDXJ",  # junior gold miners, 2009-11-10
    "PPLT",  # platinum, 2010-01-07
    "REMX",  # rare earth and strategic metals, 2010-10-27
    "URA",  # uranium, 2010-11-04
    "CPER",  # copper, 2011-11-14
    "ARKQ",  # autonomous tech and robotics, 2014-09-29
    "ARKW",  # next-generation internet, 2014-09-29
    "ARKG",  # genomics, 2014-10-30
    "ARKK",  # disruptive innovation, 2014-10-30
    "JETS",  # airlines, 2015-04-29
)


@dataclass(frozen=True, slots=True)
class StoredETFCandidates:
    """A fixed roster, filtered at each asking date to what had begun trading and warmed up.

    `min_bars` is the warmup the *selector* needs, not a data-quality threshold. A rank key built on
    a trailing twelve-month return needs twelve months of bars; asking it about a fund three weeks
    old yields a number that is arithmetically fine and means nothing. The default of 252 is one
    trading year, the longest lookback :mod:`app.discovery.selector` uses.

    Delegating to `app.evolution.universe.bars_before` rather than counting here is deliberate: that
    function already answers exactly this question against the same parquet layout, and two
    independent implementations of "how much history did this symbol have on that date" is the kind
    of duplication that drifts into disagreement and is never noticed, because both answers look
    plausible.
    """

    settings: Settings
    roster: tuple[str, ...] = SECTOR_ETF_ROSTER
    min_bars: int = 252
    label: str = "sector-etf"

    @property
    def name(self) -> str:
        return self.label

    def symbols_as_of(self, as_of: dt.date) -> tuple[str, ...]:
        """The roster members with at least `min_bars` stored bars strictly before `as_of`.

        Strictly before, not up to and including: a selector deciding on `as_of` has the closes up to
        the previous session, not that day's own.
        """
        return tuple(
            symbol
            for symbol in sorted(self.roster)
            if bars_before(symbol, as_of, self.settings) >= self.min_bars
        )


def sector_candidates(settings: Settings, *, min_bars: int = 252) -> StoredETFCandidates:
    """The sector track's candidate set, with the roster and defaults this package was measured on."""
    return StoredETFCandidates(settings=settings, min_bars=min_bars)


def theme_candidates(settings: Settings, *, min_bars: int = 252) -> StoredETFCandidates:
    """The widened candidate set: sectors plus narrow themes. See :data:`THEME_ETF_ROSTER` for the
    survivorship cost that comes with the extra reach, and read any theme-only result sceptically."""
    return StoredETFCandidates(
        settings=settings, roster=THEME_ETF_ROSTER, min_bars=min_bars, label="theme-etf"
    )
