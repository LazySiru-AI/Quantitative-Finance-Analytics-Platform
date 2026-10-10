"""The tradeable universe: which tickers ten analysts may put in a `StrategyCard.universe`.

The naive version of this list is "everything the user has ever bought," pulled straight off the
ledger's `symbol` column. That naive version breaks a tournament result in three separate, silent
ways, and this module exists to close all three rather than trust an analyst to notice.

**A one-off ticker is not evidence the user trades it.** A symbol bought once, on a whim, and never
touched again tells a backtest nothing about how the user actually behaves, and letting it into ten
analysts' universes manufactures nine near-duplicate opportunities to overfit to a single trade.
:func:`tradeable_universe`'s ``min_txns`` floor exists so "tradeable" means what it says.

**A gap in the middle of the trading window is not a missing chart -- it is a strategy that could
not have been run.** A symbol whose bars stop for two weeks and then resume lets a backtest hold a
position through a stretch where no fill, no stop, and no exit could actually have executed. Include
it silently and the resulting equity curve is not a strategy result, it is a strategy result with an
undisclosed skip built in -- indistinguishable, on the page, from six clean months of trading.
:func:`tradeable_universe` scans for exactly this and records where the gap fell.

**A leveraged or inverse fund is not a stock with a bigger number attached.** Daily-reset products
rebalance every session, so their multi-day return is path-dependent and decays against a
buy-and-hold benchmark in a choppy market for reasons that have nothing to do with any strategy's
skill -- see `app.thesis.instruments` for the mechanism. An analyst holding SOXL and another holding
SOXX are not testing two strategies on the same instrument class; the first is testing leverage
decay avoidance and calling it edge. They are excluded here rather than left for an analyst to
discover after the fact.

**A symbol with three weeks of price history before the design cutoff is not something to design
against.** `app.tournament.models.DESIGN_THROUGH` is the last day an analyst may look at while
writing a `StrategyCard`; a symbol that IPO'd two weeks before that date gives them nothing to form a
thesis on, so a strategy submitted for it is either untested or secretly informed by the trading
window itself -- the leak `StrategyCard._cannot_claim_to_have_seen_the_trading_window` exists to
rule out. ``min_design_bars`` keeps that leak from opening through a data-availability side door.

Every symbol that fails any of these checks is still returned, carrying the reason it failed --
never silently dropped. A tournament report that says "38 symbols were eligible" without saying what
happened to the other 113 the user actually traded is not something the next reader can audit.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from app.config import Settings
from app.datasource import ledger_db_path
from app.db import sqlite as ledger
from app.db.duck import Interval, read_bars
from app.db.duck import connect as duck_connect
from app.thesis import instruments
from app.tournament.models import DESIGN_THROUGH, TRADE_END, TRADE_START

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

__all__ = [
    "DEFAULT_MAX_GAP_DAYS",
    "DEFAULT_MIN_DESIGN_BARS",
    "DEFAULT_MIN_TXNS",
    "RosterEntry",
    "format_roster",
    "print_roster",
    "qualified_symbols",
    "tradeable_universe",
]

DEFAULT_MIN_TXNS: int = 5
"""Transactions required for a symbol to count as one the user actually trades, not a one-off.

Chosen over ``1``: a single buy (or a buy plus its eventual sell) is a purchase, not a trading
pattern -- there is no repeated behaviour in the ledger for a strategy's rules to be checked against
the user's own history for. Five round-trips-or-legs is enough to distinguish "something this account
does" from "something that happened once."
"""

DEFAULT_MIN_DESIGN_BARS: int = 250
"""Daily bars required on or before `DESIGN_THROUGH` -- roughly one trading year.

A shorter floor lets a symbol with, say, six weeks of pre-cutoff history into the design window. Six
weeks is not enough sessions to see a full cycle of the kind of behaviour (a drawdown, a range, a
trend) a discretionary strategy is usually built to react to, so a thesis written against it is
disproportionately a thesis about whatever those six weeks happened to contain. A year is the
smallest span that reliably contains more than one regime.
"""

DEFAULT_MAX_GAP_DAYS: int = 10
"""Largest calendar-day gap tolerated between two sessions of stored bars inside the trading window.

The US equity calendar's own gaps top out well under this: a weekend is 2 days, and the longest
holiday cluster in the trading window's calendar (a holiday adjacent to a weekend) reaches 3-4 days
-- never more, because the exchange does not close for more than one holiday in a row. So any gap
that reaches double digits is not the exchange's calendar, it is missing data or an instrument that
was not tradeable across that stretch -- exactly the "missing a fortnight mid-window" failure this
module exists to catch, per its module docstring. 10 sits comfortably above every legitimate holiday
gap and comfortably below the 14-day fortnight used as the illustrative failure case, so it never
fires on an ordinary calendar and reliably fires on the thing it is meant to catch.
"""

#: Leveraged/inverse products this module can identify *from data already in the repository*:
#: `app.thesis.instruments.REGISTRY`, built for an unrelated purpose (pairing a leveraged holding
#: with its unlevered twin for reporting) but equally good evidence of which symbols are daily-reset
#: products. Consulted first because it is the one source here that is actually data rather than a
#: claim -- it is exercised by that module's own tests and updated by whoever maintains it.
_REGISTRY_LEVERAGED = instruments.REGISTRY

#: Leveraged/inverse products this module can *not* identify from any data in the repository -- no
#: instrument-kind flag, no factor field, nothing in `app.thesis.instruments.REGISTRY` -- and are
#: excluded anyway because the tournament brief that commissioned this module named them explicitly
#: as leveraged/inverse funds to keep out of the universe. That is a real basis (a human who knows
#: these products said so), but it is not a *repository* basis: nothing here can be run to verify it,
#: and nothing here would catch the next leveraged fund the user starts trading that is not on this
#: list. Anyone maintaining this module should prefer adding a symbol to
#: `app.thesis.instruments.REGISTRY` instead, where it is checked and reusable, over growing this set.
#:
#: QLD's presence here is corroborated by a second repository artifact beyond the brief itself --
#: ``docs/research/strategy-lab/data/universe.json`` (and its report,
#: ``docs/research/strategy-lab/reports/universe.md``) independently classifies it as "2x QQQ
#: daily-reset" from an earlier research pass. That JSON is a one-off dated report rather than a
#: maintained module, so it is cited here rather than imported, but it means QLD's classification
#: rests on two repository sources agreeing, not one person's say-so. LABU (Direxion Daily S&P
#: Biotech Bull, 3x) has no corroborating artifact anywhere in this repository; its inclusion rests
#: on the brief alone. AMDL and SNXX have no stored bars at all and are excluded on that basis
#: regardless of leverage status, but are listed here too so the leveraged reason is recorded
#: accurately if bars for them ever appear.
_BRIEF_ASSERTED_LEVERAGED: frozenset[str] = frozenset({"QLD", "AMDL", "SNXX", "LABU"})


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One symbol's eligibility for the tournament universe, with the evidence behind it.

    Returned for *every* symbol the ledger has ever seen at least once -- qualifying or not -- so
    that "why isn't X in my universe" is answerable by reading this record rather than by re-running
    the query that produced it.
    """

    symbol: str
    qualifies: bool
    txn_count: int
    first_bar: dt.date | None
    """Earliest stored daily bar, across all history -- ``None`` if no bars are stored at all."""
    last_bar: dt.date | None
    """Latest stored daily bar. Compared against `TRADE_END`: anything short of it stopped trading
    (or stopped being fetched) before the tournament's last session."""
    design_bars: int
    """Daily bars on or before `DESIGN_THROUGH` -- what an analyst has to design against."""
    trading_bars: int
    """Daily bars within `[TRADE_START, TRADE_END]` -- how much of the trading window is covered."""
    max_gap_days: int | None
    """Largest calendar-day gap found while scanning the trading window (see `DEFAULT_MAX_GAP_DAYS`),
    including the gap from `TRADE_START` to the first bar and from the last bar to `TRADE_END` if
    either is late/early. ``None`` when there are no stored bars to scan."""
    reasons: tuple[str, ...] = ()
    """Why this symbol was excluded. Empty exactly when :attr:`qualifies` is ``True``."""
    warnings: tuple[str, ...] = ()
    """Non-disqualifying notes about a symbol that *did* qualify -- a gap or a design-history margin
    close enough to the cutoff that an analyst should know about it even though it did not exclude
    the symbol."""


def tradeable_universe(
    settings: Settings,
    *,
    min_txns: int = DEFAULT_MIN_TXNS,
    min_design_bars: int = DEFAULT_MIN_DESIGN_BARS,
    max_gap_days: int = DEFAULT_MAX_GAP_DAYS,
) -> tuple[RosterEntry, ...]:
    """Every symbol the ledger has ever recorded, evaluated against the tournament's four gates.

    A symbol qualifies only when it clears all of:

    1. At least ``min_txns`` transactions in the ledger (see `DEFAULT_MIN_TXNS`).
    2. Not a leveraged or inverse fund (see `_REGISTRY_LEVERAGED` / `_BRIEF_ASSERTED_LEVERAGED`).
    3. Daily bars through `TRADE_END` with no trading-window gap larger than ``max_gap_days``
       calendar days (see `DEFAULT_MAX_GAP_DAYS`).
    4. At least ``min_design_bars`` daily bars on or before `DESIGN_THROUGH` (see
       `DEFAULT_MIN_DESIGN_BARS`).

    The ledger is opened strictly read-only (`app.db.sqlite.connect(..., read_only=True)`) -- this
    function only ever counts transactions, it never has a reason to write one. Bars are read through
    an in-memory DuckDB connection; the on-disk `Settings.analytics_path` catalog is not touched,
    because nothing here needs it and a read path has no business creating it.

    Returns one `RosterEntry` per symbol the ledger has ever seen, in symbol order, both qualifying
    and excluded -- see the module docstring for why silently dropping the excluded ones is exactly
    the failure this function exists to prevent.
    """
    txn_counts = _txn_counts(ledger_db_path(settings))

    entries: list[RosterEntry] = []
    with duck_connect() as conn:
        for symbol in sorted(txn_counts):
            entries.append(
                _evaluate_symbol(
                    conn,
                    settings.bars_dir,
                    symbol,
                    txn_counts[symbol],
                    min_txns=min_txns,
                    min_design_bars=min_design_bars,
                    max_gap_days=max_gap_days,
                )
            )
    return tuple(entries)


def _txn_counts(ledger_path: Path) -> dict[str, int]:
    """Transaction count per distinct non-empty symbol in the ledger's `txn` table."""
    with ledger.connect(ledger_path, read_only=True) as conn:
        rows = conn.execute(
            "SELECT symbol, COUNT(*) AS n FROM txn WHERE symbol IS NOT NULL AND symbol <> '' "
            "GROUP BY symbol"
        ).fetchall()
    return {str(row["symbol"]): int(row["n"]) for row in rows}


def _leveraged_reason(symbol: str) -> str | None:
    """Why ``symbol`` is a leveraged/inverse fund, or ``None`` if neither known source flags it."""
    upper = symbol.upper()
    entry = _REGISTRY_LEVERAGED.get(upper)
    if entry is not None:
        underlying = entry.underlying or "no mapped underlying"
        return (
            f"leveraged/inverse per app.thesis.instruments.REGISTRY: daily-reset {entry.factor:+g}x "
            f"on {underlying} -- its multi-day return is path-dependent and decays against a "
            "buy-and-hold benchmark in a choppy market regardless of any strategy's skill."
        )
    if upper in _BRIEF_ASSERTED_LEVERAGED:
        return (
            f"leveraged/inverse fund by identity, not by data in this repository -- {upper} is not "
            "in app.thesis.instruments.REGISTRY. Excluded because the tournament brief that "
            "commissioned this roster named it explicitly as a leveraged/inverse product; see "
            "_BRIEF_ASSERTED_LEVERAGED's docstring for why that is a weaker basis than the registry "
            "and should be migrated there."
        )
    return None


def _max_gap(
    dates: Sequence[dt.date], window_start: dt.date, window_end: dt.date
) -> tuple[int, dt.date, dt.date]:
    """Largest calendar-day span between consecutive points of coverage, in ``[window_start, window_end]``.

    ``dates`` must already be sorted ascending and confined to the window. `window_start` and
    `window_end` are treated as virtual coverage points on either end, so a symbol whose bars start
    late or stop early registers as a gap the same way an interior missing stretch does -- a strategy
    cannot trade a symbol before its first bar or after its last one, whichever side of the window
    that falls on.

    Returns ``(gap_days, gap_start, gap_end)`` for the single largest gap found. With no dates at all
    the "gap" is the entire window, which is correct: zero bars in the trading window is the most
    untradeable a symbol can be.
    """
    prev = window_start
    widest = 0
    span = (window_start, window_start)
    for d in dates:
        gap = (d - prev).days
        if gap > widest:
            widest = gap
            span = (prev, d)
        prev = d
    closing_gap = (window_end - prev).days
    if closing_gap > widest:
        widest = closing_gap
        span = (prev, window_end)
    return widest, span[0], span[1]


def _evaluate_symbol(
    conn: duckdb.DuckDBPyConnection,
    bars_dir: Path,
    symbol: str,
    txn_count: int,
    *,
    min_txns: int,
    min_design_bars: int,
    max_gap_days: int,
) -> RosterEntry:
    reasons: list[str] = []
    warnings: list[str] = []

    if txn_count < min_txns:
        reasons.append(
            f"{txn_count} transaction{'s' if txn_count != 1 else ''} in the ledger, below the "
            f"min_txns={min_txns} floor -- not enough repeated activity to call this a symbol the "
            "user trades rather than a one-off."
        )

    leveraged_reason = _leveraged_reason(symbol)
    if leveraged_reason is not None:
        reasons.append(leveraged_reason)

    frame: pd.DataFrame = read_bars(conn, bars_dir, symbol, Interval.DAY)
    if frame.empty:
        reasons.append(
            "no daily bars stored for this symbol -- nothing to design against and nothing to "
            "trade against."
        )
        return RosterEntry(
            symbol=symbol,
            qualifies=False,
            txn_count=txn_count,
            first_bar=None,
            last_bar=None,
            design_bars=0,
            trading_bars=0,
            max_gap_days=None,
            reasons=tuple(reasons),
            warnings=(),
        )

    dates = sorted(ts.date() for ts in frame["ts"])
    first_bar, last_bar = dates[0], dates[-1]

    design_bars = sum(1 for d in dates if d <= DESIGN_THROUGH)
    if design_bars < min_design_bars:
        reasons.append(
            f"only {design_bars} daily bars on or before DESIGN_THROUGH ({DESIGN_THROUGH.isoformat()}), "
            f"below the min_design_bars={min_design_bars} floor -- too little pre-cutoff history for "
            "an analyst to form a thesis against."
        )
    elif design_bars < 2 * min_design_bars:
        warnings.append(
            f"design history is {design_bars} bars, under 2x the min_design_bars={min_design_bars} "
            "floor -- thin margin, likely close to one regime rather than several."
        )

    trading_dates = [d for d in dates if TRADE_START <= d <= TRADE_END]
    trading_bars = len(trading_dates)

    gap_days: int | None
    if last_bar < TRADE_END:
        reasons.append(
            f"bars end {last_bar.isoformat()}, before TRADE_END ({TRADE_END.isoformat()}) -- "
            "delisted, halted, or not fetched through the end of the trading window; a strategy "
            "cannot be scored past the day its data stops."
        )
        gap_days, _gap_from, _gap_to = _max_gap(trading_dates, TRADE_START, TRADE_END)
    else:
        gap_days, gap_from, gap_to = _max_gap(trading_dates, TRADE_START, TRADE_END)
        if gap_days > max_gap_days:
            reasons.append(
                f"a {gap_days}-calendar-day gap in trading-window bars between {gap_from.isoformat()} "
                f"and {gap_to.isoformat()} exceeds the max_gap_days={max_gap_days} limit -- the US "
                "market calendar never closes that long on its own (see DEFAULT_MAX_GAP_DAYS), so a "
                "strategy holding through this stretch could not actually have traded it."
            )
        elif gap_days > max(1, max_gap_days // 2):
            warnings.append(
                f"a {gap_days}-calendar-day gap in trading-window bars between {gap_from.isoformat()} "
                f"and {gap_to.isoformat()} is under the max_gap_days={max_gap_days} exclusion limit "
                "but well past an ordinary weekend or holiday -- worth a look before relying on this "
                "symbol through that stretch."
            )

    return RosterEntry(
        symbol=symbol,
        qualifies=not reasons,
        txn_count=txn_count,
        first_bar=first_bar,
        last_bar=last_bar,
        design_bars=design_bars,
        trading_bars=trading_bars,
        max_gap_days=gap_days,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


def qualified_symbols(entries: Sequence[RosterEntry]) -> tuple[str, ...]:
    """Just the tickers that qualified, in the order `tradeable_universe` produced them.

    What `StrategyCard.universe` should be drawn from -- the runner and the analysts both want the
    plain list far more often than the full evidence trail.
    """
    return tuple(e.symbol for e in entries if e.qualifies)


def format_roster(entries: Sequence[RosterEntry]) -> str:
    """Render a `tradeable_universe` result as a page a person can read in a terminal.

    Qualified symbols first (busiest first, by transaction count), then every exclusion with the
    reason it failed -- the one artifact an analyst is expected to check before writing a
    `StrategyCard`, rather than re-deriving these rules by reading this module.
    """
    qualified = sorted((e for e in entries if e.qualifies), key=lambda e: -e.txn_count)
    excluded = sorted((e for e in entries if not e.qualifies), key=lambda e: -e.txn_count)

    lines = [
        f"Tradeable universe: {len(qualified)} qualified, {len(excluded)} excluded "
        f"(of {len(entries)} symbols ever traded)",
        "",
        "QUALIFIED",
    ]
    for e in qualified:
        lines.append(
            f"  {e.symbol:<8} txns={e.txn_count:<5} bars {e.first_bar}..{e.last_bar}  "
            f"design_bars={e.design_bars:<5} trading_bars={e.trading_bars}"
        )
        for warning in e.warnings:
            lines.append(f"      ! {warning}")

    lines.append("")
    lines.append("EXCLUDED")
    for e in excluded:
        lines.append(f"  {e.symbol:<8} txns={e.txn_count}")
        for reason in e.reasons:
            lines.append(f"      - {reason}")

    return "\n".join(lines)


def print_roster(entries: Sequence[RosterEntry]) -> None:
    """Print `format_roster` to stdout -- the one-call version for a REPL or a notebook."""
    print(format_roster(entries))
