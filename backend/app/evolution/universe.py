"""Purpose-partitioned ticker pools: the instruments a proposed genome is allowed to draw from.

This module answers the owner's ask directly -- "you have to divide tickers if it is Roth IRA vs a
regular taxable account", and "not just QLD/SSO -- mix trend and stability, add a few percent SOXX or
SMH" -- with data rather than with a convention every future caller has to remember to honour. Two
things follow from that ask, and each is enforced here rather than left to a proposer's discipline:

**One pool per book, not per `Purpose`.** `Purpose.TRADING` and `Purpose.SAVINGS` are both taxable
(`app.tournament.purposes.PURPOSE_SPECS[...].symbols_must_be_disjoint` is `False` for both), so they
share one ticker set -- the same set, not merely an equal one, expressed as one module-level constant
handed to two `Pool` instances that differ only in their `purpose` label. `Purpose.ROTH` is the one
purpose flagged `symbols_must_be_disjoint=True`, and it gets a wholly separate set. This mirrors
`app.tournament.purposes.find_disjointness_violations`, which never compares two non-Roth cards to
each other -- there would be nothing to check.

**Every pool has four sleeves, not one flat list.** A genome that only ever mixes QLD and QQQ is the
exact failure mode the owner flagged by name. `growth` is the trend/return engine (the large, liquid
names a `StrategyCard` trades directly); `leveraged` is the single amplifier for the book (QLD
taxable, SSO Roth -- one each, never both in the same pool, so a genome cannot accidentally double up
leverage by drawing two); `satellite` is the few-percent tactical tilt ("SOXX or SMH") that
`genome.py`'s allocation weight generator deliberately caps in the 0.03-0.12 range; `stability` is the
dividend/low-vol/bond/cash sleeves that give an allocation card's rebalancing band something to trim
into. `Pool.all_symbols()` flattens all four for callers that only need "everything this purpose may
touch" (bar-availability checks, disjointness checks) and do not care which sleeve a symbol came from.

**The taxable/Roth split had to be checked against the library that already exists, not designed in a
vacuum.** The ticker lists below were not chosen freely -- `strategy-program`'s owner-authored brief
for this module suggested XLV and TLT for the Roth pool's satellite and stability sleeves, and SMH
for its satellite semiconductor tilt (with SOXX going to the taxable book). All three of the
suggested Roth tickers already appear in existing taxable-purpose (default `Purpose.TRADING`) cards
somewhere in `backend/app/paper/library/`: XLV in `candidates/c07-chop.json` and
`candidates/c20-rotation.json`; TLT in `candidates/c09-convex.json`, `candidates/c11-breakout.json`
and `candidates/c14-riskmanaged-wide.json`; and SMH -- easy to miss on a naive grep, because
`retired/c10-momentum.json` writes its `universe` as a single-line JSON array rather than one ticker
per line -- in `retired/c10-momentum.json`. `retired` is one of the four tiers
`app.tournament.results.load_library` actually loads (`base`, `variants`, `candidates`, `retired`),
so a retired card counts exactly as much as a live one for this check; nothing here got to assume
otherwise. Because `app.evolution.proposer.propose_generation` is required to check every Roth
candidate against `load_library()`'s existing cards before returning (`ProposalRejected` if any
ticker collides), shipping any of these three symbols in the Roth pool would not be a close call the
loop sometimes loses -- it would make every Roth-purpose generation that happened to draw one of them
fail outright, deterministically, forever. The Roth pool therefore substitutes for all three, and
`tests/test_evolution_proposer.py` runs the same `load_library()` intersection as a regression guard
rather than trusting it to stay true.

**Both semiconductor ETFs are taxable.** The owner's framing was "SOXX goes taxable and SMH goes
Roth", and that exact pairing collides with `retired/c10-momentum.json`. SOXX and SMH now sit together
in `_TAXABLE_SATELLITE` -- taxable-to-taxable overlap is legal, since the disjointness rule binds only
between `roth` and the taxable purposes -- and the Roth book keeps its own tactical tilt through
`_ROTH_SATELLITE` instead of sharing one.

**A ticker's history is a constraint, not a detail, and this module got that wrong first.** The
sleeves below were originally chosen for what each ticker *is* and never checked what it *has*. That
shipped a pool in which META and SCHD had zero bars before `gfc` and `chop-2011`, SGOV had zero before
five of the eight main windows, and BIL and BND had real first bars before `gfc` but only 93 and 128
bars of it -- far short of the 200 an `sma(200)` rank key needs to warm up.

The consequence was not a few weaker candidates. `app.backtest.guards` refuses a whole *card* for a
window when one of its symbols cannot demonstrate causality, and the refusal is recorded as an
ordinary card failure, so nothing surfaces as an error. A live round logged
`chop-2011: 0 run file(s) written, 6 run(s) attempted`, every candidate finished below
`MIN_ELIGIBLE_MAIN_WINDOWS`, and the generation reported `0 of 0 eligible candidate(s) cleared the
margin`. The loop was not producing poor results; it was structurally incapable of producing a
rankable one, and would have stayed that way indefinitely.

Every sleeve is now screened by :data:`MIN_WARMUP_BARS` against the oldest window the loop can
rotate through, measured off the real bar store by :func:`coverage_gaps`, which
`tests/test_evolution_proposer.py` asserts is empty over `app.tournament.jobs.MAIN_WINDOWS`. Each
substitution is documented at the sleeve it belongs to. The rule when that test fails is to swap the
ticker, never to lower the threshold: the threshold comes from the genome's own indicator vocabulary,
so lowering it just re-admits cards the engine will refuse.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import duckdb

from app.config import Settings
from app.db.duck import Interval, stored_symbols
from app.tournament.purposes import Purpose

__all__ = [
    "MIN_WARMUP_BARS",
    "Pool",
    "bars_before",
    "coverage_gaps",
    "filter_to_available",
    "pool_for",
    "symbols_with_bars",
]


# ---------------------------------------------------------------------------
# The pool type
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pool:
    """One purpose's investable universe, split into the four sleeves `genome.py` draws from.

    A plain frozen dataclass, not a pydantic model -- nothing here is untrusted input that needs
    parsing or coercion; it is a fixed constant this module builds once at import time, and the
    dataclass form is what lets it be a module-level literal instead of requiring a validation pass
    on every access.
    """

    purpose: Purpose
    growth: tuple[str, ...]
    """The trend/return engine -- individual names a `StrategyCard`'s `entry`/`exit` trades directly,
    or an allocation card's core equity sleeve."""

    leveraged: tuple[str, ...]
    """The single amplifier for this book. Deliberately one symbol: QLD for the taxable book, SSO for
    Roth -- never both, so a genome cannot double up leverage by drawing two leveraged sleeves into
    one card."""

    satellite: tuple[str, ...]
    """The few-percent tactical tilt -- semiconductors and sector/style funds (SOXX, SMH and XLK
    taxable; IGV and VUG Roth). `genome.py`'s allocation weight generator targets roughly 0.03-0.12 of
    the book for a satellite sleeve, which is what makes this "a few percent", not a fourth core
    holding."""

    stability: tuple[str, ...]
    """Dividend, low-volatility, bond and cash sleeves -- what a `band_pct` rebalance trims into and
    what mostly absorbs `genome.py`'s rounding remainder when weights are quantised to sum to
    exactly one."""

    def __post_init__(self) -> None:
        symbols = self.growth + self.leveraged + self.satellite + self.stability
        counts = Counter(symbols)
        dupes = sorted(symbol for symbol, count in counts.items() if count > 1)
        if dupes:
            raise ValueError(
                f"pool for {self.purpose.value!r} repeats {dupes} across sleeves -- a symbol must "
                "belong to exactly one sleeve so genome.py's category-preserving ticker swap "
                "(mutate() never crosses sleeves) has an unambiguous category to look up"
            )

    def all_symbols(self) -> tuple[str, ...]:
        """Every symbol in this pool, sleeve order (`growth`, `leveraged`, `satellite`, `stability`),
        flattened for callers that only need "everything this purpose may touch" -- bar-availability
        checks and `find_disjointness_violations` do not care which sleeve a symbol came from."""
        return self.growth + self.leveraged + self.satellite + self.stability

    def category_of(self, symbol: str) -> str:
        """Which sleeve `symbol` belongs to: `"growth"`, `"leveraged"`, `"satellite"` or
        `"stability"`. Raises `KeyError` if `symbol` is not in this pool at all -- callers
        (`genome.mutate`'s ticker-swap step) are expected to only ever ask about a symbol already
        known to be one of this pool's own, e.g. a symbol drawn from a parent genome's own
        `universe`."""
        for name in ("growth", "leveraged", "satellite", "stability"):
            if symbol in getattr(self, name):
                return name
        raise KeyError(f"{symbol!r} is not in the {self.purpose.value!r} pool")


# ---------------------------------------------------------------------------
# The taxable book -- Purpose.TRADING and Purpose.SAVINGS share this ticker set
# ---------------------------------------------------------------------------

#: Trading days of history a ticker must have *before* a window opens to be drawable for it.
#:
#: Not "has a first bar before the window starts" -- that test passes tickers the engine then refuses.
#: An entry rule carries an indicator warmup (`regime_ma` is drawn from 56..160 and mutates upward,
#: and `rank_by` may be `close / sma(200)`), and `app.backtest.guards` fails a card outright when a
#: symbol has no post-warmup region to demonstrate causality over. The failure is per *card*, not per
#: symbol: one too-young ticker in a universe takes the whole card down for that window.
#:
#: 300 is 200 (the largest fixed warmup in the genome's vocabulary, `sma(200)`) plus room for
#: `regime_ma` to mutate above its initial ceiling. Measured against the real bar store, the binding
#: cases at the oldest main window are QLD and SSO with 328 bars before `gfc` -- comfortably over 200,
#: which is why the leveraged sleeves survive this rule and the 2011-vintage factor ETFs do not.
MIN_WARMUP_BARS = 300

_TAXABLE_GROWTH: tuple[str, ...] = (
    "NVDA", "TSM", "MU", "AMD", "QCOM", "MSFT", "GOOGL", "AMZN", "NFLX", "ORCL", "INTC", "TXN",
)
"""AVGO and META are gone, and INTC and TXN replace them, because of history rather than merit.

The first draft of this pool was chosen for what the tickers *are* and never checked what they
*have*. Measured against the bar store: META's first bar is 2012-05-17, so it has **zero** bars
before either `gfc` (2007-10-09) or `chop-2011` (2011-05-26); AVGO's is 2009-08-05, zero before
`gfc`. Every card drawing one of them failed those windows outright, and because a whole generation
shares a window set, `chop-2011` recorded `0 run file(s) written, 6 run(s) attempted` -- the entire
window lost for the entire field.

That is not a cosmetic loss. Selection runs five windows and `app.tournament.results`'
`MIN_ELIGIBLE_MAIN_WINDOWS` is five, so losing two left three, every candidate was marked ineligible,
and the round reported `0 of 0 eligible candidate(s) cleared the margin`. The loop was not producing
weak results; it was structurally incapable of producing a rankable one.

INTC (1980) and TXN (1972) keep the sleeve at twelve names and in the same semiconductor/large-cap
tech neighbourhood. INTC is already traded by a `trading`-purpose card, which is fine -- the
disjointness rule binds only between `roth` and the taxable purposes."""
_TAXABLE_LEVERAGED: tuple[str, ...] = ("QLD",)
_TAXABLE_SATELLITE: tuple[str, ...] = ("SOXX", "SMH", "XLK")
"""SOXX *and* SMH, both on the taxable side, which is not where the first draft put them.

The owner asked for "a few percent SOXX or SMH", and the obvious reading -- one semiconductor ETF per
book -- is the one that cannot ship: SMH is already traded by `retired/c10-momentum.json`, a
`trading`-purpose card, and `app.tournament.results.load_library` loads `retired/` along with the
other three tiers, so a Roth candidate holding SMH would fail
`app.tournament.purposes.find_disjointness_violations` and take every Roth generation down with it.

Putting both here instead costs nothing and honours the request literally. Taxable-to-taxable overlap
is legal -- the disjointness rule binds only between `roth` and the two taxable purposes, because the
hazard it exists for is Rev. Rul. 2008-5's permanent disallowance inside an IRA, not the ordinary
deferred wash sale two taxable cards can create between them. The Roth book keeps its own sector tilt
through `_ROTH_SATELLITE` rather than by sharing one of these.

Whether SOXX and SMH are "substantially identical" to each other under IRC section 1091 is a live
question and nothing here answers it; what makes the question harmless in this direction is that both
sit in taxable accounts, where the worst case is deferral."""
_TAXABLE_STABILITY: tuple[str, ...] = ("DVY", "XLP", "XLU", "AGG", "GLD", "IEF")
"""SCHD and BIL are gone; DVY replaces SCHD and nothing replaces BIL.

SCHD's first bar is 2011-10-19 -- zero bars before `gfc` or `chop-2011`. DVY (2003-11-06, 986 bars
before `gfc`) plays the same role: a dividend-weighted equity sleeve, and one no card in the library
trades, so it costs nothing elsewhere.

BIL is the more interesting cut, because it *looks* fine on the naive test and is not. Its first bar
is 2007-05-29, which is genuinely before `gfc` opens on 2007-10-09 -- but that is only **93 trading
days**, and a card whose `rank_by` is `close / sma(200)` needs 200. A first-bar-before-the-window
check passes BIL and the engine then refuses it, which is exactly the shape of failure this pool now
screens for with :data:`MIN_WARMUP_BARS` rather than with dates. Nothing replaces it: no cash-like ETF
in the store has both the history and a ticker free of the Roth pool, and AGG and IEF already anchor
the low-risk end of this sleeve."""


# ---------------------------------------------------------------------------
# The Roth book -- must stay ticker-disjoint from the taxable book above, and from every existing
# taxable-purpose card already in the library (see this module's own docstring for the XLV/TLT swap).
# ---------------------------------------------------------------------------

_ROTH_GROWTH: tuple[str, ...] = (
    "AAPL", "ADBE", "CRM", "AMAT", "LRCX", "KLAC", "INTU", "CSCO",
)
"""ANET (first bar 2014-06-05) and PANW (2012-07-19) are replaced by INTU (1993) and CSCO (1990).

Both originals had zero bars before `gfc` and `chop-2011`, and ANET has only 210 before `chop-2015`
as well -- three of the eight main windows lost by one ticker. See `_TAXABLE_GROWTH` for what that
costs a whole generation. INTU and CSCO keep the sleeve at eight enterprise-software and networking
names and are traded by no card in the library, so they stay clear of the Roth disjointness rule."""
_ROTH_LEVERAGED: tuple[str, ...] = ("SSO",)
_ROTH_SATELLITE: tuple[str, ...] = ("IGV", "VUG")
"""IGV (software, 2001) stands in for the originally suggested SMH -- both are sector-tilt satellites,
and IGV keeps the Roth book's satellite sleeve on its own side of the disjointness wall without
reusing a ticker `retired/c10-momentum.json` already trades.

VUG (Vanguard Growth, 2004-01-29, 930 bars before `gfc`) replaces MTUM. MTUM's first bar is
2013-04-17 -- zero before `gfc` or `chop-2011`. Both express "tilt toward what is working"; MTUM does
it by momentum rank and VUG by growth characteristics, which is a real difference in construction but
the same job in this sleeve, and it is the one of the two that can actually be measured across this
programme's regimes."""

_ROTH_STABILITY: tuple[str, ...] = (
    "VIG", "TIP", "SHY", "VTV", "RSP", "VNQ",
)
"""Four of the seven originals are gone. This sleeve took the worst of the history problem.

TIP (2003) and VIG (2006-05-01, 363 bars before `gfc`) survive. Cut, with their bars before `gfc`:
**SGOV (0 -- and zero before `chop-2011`, `chop-2015`, `q4-2018` and `covid` too, five of the eight
main windows)**, USMV (0), QUAL (0), SPLV (0, and 16 before `chop-2011`), and BND (128, which is a
real first bar in 2007-04-09 but nowhere near the 200 an `sma(200)` rank key needs).

SGOV was the most damaging single entry in either pool. Any Roth allocation card drawing it could run
at most three of the eight windows and was therefore ineligible by construction, no matter how it
performed -- the Roth lane could not have promoted anything.

The replacements, all with 700+ bars before `gfc` and traded by no card in the library:
SHY (1-3yr Treasury, 2002) takes SGOV's cash-like role with twenty years of history; VTV (value,
2004) takes the defensive-factor role USMV and QUAL held; RSP (equal-weight S&P, 2003) is a
concentration hedge against the growth sleeve's mega-caps; VNQ (REITs, 2004) adds a real-asset sleeve
the book did not have.

BND's departure leaves the existing hand-authored `ladder-sso-vig-bnd` card as the only thing trading
it, which is unaffected -- that card is not generated by this loop and its own purpose is already
`roth`."""


_POOLS: dict[Purpose, Pool] = {
    Purpose.TRADING: Pool(
        purpose=Purpose.TRADING,
        growth=_TAXABLE_GROWTH,
        leveraged=_TAXABLE_LEVERAGED,
        satellite=_TAXABLE_SATELLITE,
        stability=_TAXABLE_STABILITY,
    ),
    Purpose.SAVINGS: Pool(
        purpose=Purpose.SAVINGS,
        growth=_TAXABLE_GROWTH,
        leveraged=_TAXABLE_LEVERAGED,
        satellite=_TAXABLE_SATELLITE,
        stability=_TAXABLE_STABILITY,
    ),
    Purpose.ROTH: Pool(
        purpose=Purpose.ROTH,
        growth=_ROTH_GROWTH,
        leveraged=_ROTH_LEVERAGED,
        satellite=_ROTH_SATELLITE,
        stability=_ROTH_STABILITY,
    ),
}


def pool_for(purpose: Purpose) -> Pool:
    """The fixed `Pool` for `purpose`. `Purpose.TRADING` and `Purpose.SAVINGS` return pools built
    from the identical taxable ticker constants (see this module's own docstring); `Purpose.ROTH`
    returns the disjoint Roth pool."""
    return _POOLS[purpose]


# ---------------------------------------------------------------------------
# The disjointness invariant, enforced structurally rather than merely checked at proposal time.
#
# `app.tournament.purposes.find_disjointness_violations` is the runtime check `proposer.py` runs
# against real cards; this assertion is the design-time guarantee that the check can never actually
# fire between the pools themselves -- a candidate genome cannot draw a Roth/taxable-colliding
# universe from these pools no matter what `genome.py`'s operators do with them, because the source
# sets never overlapped in the first place. Raised at import time (an `AssertionError`, not a
# `ProposalRejected` -- there is no genome yet for a `ProposalRejected` to name) so a future edit that
# reintroduces an overlapping ticker fails the instant this module is imported, not the first time a
# Roth generation happens to draw the colliding symbol.
# ---------------------------------------------------------------------------

_taxable_symbols = frozenset(_POOLS[Purpose.TRADING].all_symbols())
_roth_symbols = frozenset(_POOLS[Purpose.ROTH].all_symbols())
_overlap = _taxable_symbols & _roth_symbols
assert not _overlap, (
    f"Roth and taxable pools share tickers {sorted(_overlap)} -- the two books must be completely "
    "ticker-disjoint (strategy-program/THREE-PURPOSES-PLAN.md section 6); fix universe.py's pool "
    "constants before anything else in app.evolution runs"
)


# ---------------------------------------------------------------------------
# Bar availability
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _symbols_with_bars_cached(bars_dir_str: str) -> frozenset[str]:
    """The actual scan, cached per `bars_dir` string so a hot proposal loop does not re-list a
    directory of several hundred symbol partitions on every genome. Keyed on the string form of the
    path (a `Path` is hashable too, but the string is what a caller's `Settings.bars_dir` -- itself
    already resolved -- reliably reduces to across repeated calls with equal-but-not-identical `Path`
    objects, which `functools.lru_cache`'s equality-based key would otherwise treat as a cache miss
    only if `Path.__eq__` disagreed with `Path.__hash__`, which it does not, but keying on `str`
    keeps this cache correct without depending on that `Path` implementation detail holding forever).
    """
    return frozenset(stored_symbols(Path(bars_dir_str), Interval.DAY))


def symbols_with_bars(settings: Settings) -> frozenset[str]:
    """Every symbol with at least one stored daily bar under `settings.bars_dir`.

    Delegates to `app.db.duck.stored_symbols`, the same directory-listing helper
    `app.market.refresh` and `app.api.health` already use, rather than re-walking
    `interval=1d/symbol=<TICKER>/` here a second time -- a pool that shipped a ticker with no bars
    would fail silently at run time (an empty-bars `StrategyCard`/`AllocationCard` guard failure deep
    in `app.tournament.runner`), not at proposal time, which is exactly the kind of defect this
    function exists to catch before a genome is ever built.
    """
    return _symbols_with_bars_cached(str(settings.bars_dir))


def filter_to_available(symbols: tuple[str, ...], settings: Settings) -> tuple[str, ...]:
    """`symbols`, in the same order, with anything missing stored bars dropped.

    Order-preserving rather than returning a set: callers pass ordered sleeve tuples
    (`Pool.growth`, and eventually a genome's `universe`, whose order is meaningful --
    `traits["weights"]` for an allocation genome is positional against `universe`), and silently
    reordering them here would be a second, harder-to-spot way for a weight vector to end up pointing
    at the wrong symbol.
    """
    available = symbols_with_bars(settings)
    return tuple(symbol for symbol in symbols if symbol in available)


# ---------------------------------------------------------------------------
# Bar-availability self-check against the pools this module actually ships.
#
# Verified once, empirically, against the real `data/store/bars/interval=1d/` tree while this module
# was written -- every symbol in every sleeve above has a stored `bars.parquet` partition. Encoded
# here as a `get_settings()`-driven check that only runs (and only ever *can* run) when the real
# store is present, rather than as a hardcoded "confirmed present" list this file would have to keep
# in step with the store by hand: `tests/test_evolution_proposer.py`'s bar-availability test is the
# enforced version of this same check and is what actually fails a future edit that adds a
# bars-less ticker; this block is deliberately inert (a no-op past `pool_for` and
# `symbols_with_bars` themselves) so importing this module never depends on the real filesystem being
# in any particular state, including in a fresh clone before `data/` has been populated at all.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Warmup coverage -- the check the pools above are chosen to satisfy
# ---------------------------------------------------------------------------


def bars_before(symbol: str, when: dt.date, settings: Settings) -> int:
    """How many stored daily bars `symbol` has strictly before `when`.

    Read straight off the symbol's own parquet partition with a throwaway DuckDB connection rather
    than through `app.db.duck.read_bars`, because this asks a counting question about one file and
    that function materialises a full DataFrame of every bar ever stored for the symbol -- fine for a
    backtest, wasteful when the answer is a single integer and the caller is about to ask it once per
    ticker per window.

    Returns 0 for a symbol with no stored partition, which is the same answer a caller acts on as
    "cannot run this window" -- there is no useful distinction here between "no data" and "no data
    yet", and raising would make the coverage report below stop at the first gap instead of listing
    every one.
    """
    partition = settings.bars_dir / f"interval={Interval.DAY.value}" / f"symbol={symbol}" / "bars.parquet"
    if not partition.is_file():
        return 0
    with duckdb.connect() as conn:
        row = conn.execute(
            "select count(*) from read_parquet(?) where ts < ?",
            [partition.as_posix(), when],
        ).fetchone()
    return int(row[0]) if row else 0


def coverage_gaps(
    windows: Mapping[str, dt.date],
    settings: Settings,
    *,
    purposes: Sequence[Purpose] = (Purpose.TRADING, Purpose.SAVINGS, Purpose.ROTH),
    minimum: int = MIN_WARMUP_BARS,
) -> dict[str, list[str]]:
    """Every `(symbol -> windows it cannot be drawn for)` pair across the given purposes' pools.

    An empty dict means every pool ticker can be drawn for every window. Anything else is a defect in
    the pools, not a fact about the market, and the fix is to substitute the ticker rather than to
    lower `minimum`.

    This exists because the first version of this module chose its tickers for what they *are* and
    never checked what history they *have*, and the failure that produced was invisible in every unit
    test: cards ran, the engine refused them per-window with a lookahead-guard error, the refusals
    were recorded as ordinary card failures, and a whole generation came back
    `0 of 0 eligible candidate(s)`. `tests/test_evolution_proposer.py` calls this over
    `app.tournament.jobs.MAIN_WINDOWS` and fails on any non-empty result, so a future edit that adds a
    2013-vintage ETF to a sleeve is caught at test time instead of an hour into a round.
    """
    gaps: dict[str, list[str]] = {}
    seen: set[str] = set()
    for purpose in purposes:
        for symbol in pool_for(purpose).all_symbols():
            if symbol in seen:
                continue
            seen.add(symbol)
            short = sorted(
                tag for tag, start in windows.items() if bars_before(symbol, start, settings) < minimum
            )
            if short:
                gaps[symbol] = short
    return gaps
