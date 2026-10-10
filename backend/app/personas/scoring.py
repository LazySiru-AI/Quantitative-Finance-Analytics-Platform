"""Score a persona's dated ticker calls against what the market actually did since.

**The question this module answers, and only this question:** for every symbol an influencer named
in an episodic note, with a stance THEY took, on the day the note was published -- if you had acted
on that call at the next available close, what would the market have done since? This is descriptive,
never predictive, and never advice; it measures only the calls a persona actually made on camera, so
it is not an audited track record and it carries the usual selection/survivorship caveats. See
`docs/INFLUENCER-CONTRACT.md`, "Phase 3a -- call scoring (pinned)", for the exact wire contract this
module implements -- the semantics below restate it, they do not vary it.

**Why the entry rule looks backwards at first glance.** A call is dated by `EpisodicNote.published`,
the day the influencer actually said it. The obvious entry price is "the close on that day", but nine
times out of ten that bar simply does not exist yet by the time this function is asked to score the
call: a Sunday upload has no Sunday close, and even a weekday note's own session may not have settled
in the store the moment scoring runs. Pricing forward to the *next* trading session's close is not a
convenience -- it is the only entry that could actually have been dealt, and reaching backward to a
close that predates the statement (a prior Friday's, say) would silently look ahead of what the
influencer actually reacted to. So: entry = the close of the first daily bar with
`bar.ts.date() >= said_on.date()`, never earlier. When no such bar exists yet -- the statement is from
today or later than the last settled session -- the outcome is `pending`, not a guess dressed up as a
number.

**Why `None` and not `0.0`.** `pending` and `no_data` calls carry no price, no return, no basis --
every one of those fields is `None`. A `0.0` return would read as "flat", which is a real, measured
outcome this module also produces (the flat band below); collapsing "we have no answer" into the same
number as "we measured no move" would make the two indistinguishable to anything downstream that
reads the field. `PersonaScorecard.hit_rate` and `median_return_pct` follow the same discipline: `None`
when the denominator is zero, never `0.0` -- a rate over no calls is undefined, not zero.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Literal

from app.config import Settings
from app.db.duck import Interval
from app.market.models import Bar
from app.market.providers.base import ProviderUnavailable
from app.market.store import ensure_series  # patched as `scoring.ensure_series` in tests
from app.personas import stats
from app.personas.models import (
    CallOutcome,
    CallScore,
    DigestWarning,
    EpisodicNote,
    HorizonReturn,
    HorizonStat,
    PersonaScorecard,
    Stance,
)

__all__ = ["DEFAULT_HORIZONS", "score_calls"]

_log = logging.getLogger(__name__)

#: `|return_pct| < 2.0` is "nothing really happened" -- a directional call inside this band is `flat`,
#: neither a hit nor a miss. Pinned by the contract, not tunable here.
_FLAT_BAND_PCT = 2.0

#: Fixed trading-day horizons scored alongside return-to-today, per `docs/INFLUENCER-CONTRACT.md`,
#: "Phase 3b -- fixed horizons". A July call and an August call are both judged over the same
#: 5/20/60-bar window this way, rather than one over months and the other over days -- return-to-today
#: alone is not comparable across calls made at different times.
DEFAULT_HORIZONS: tuple[int, ...] = (5, 20, 60)

#: Slack subtracted from the earliest `said_on` date before fetching a symbol's series. The no-look-
#: ahead entry rule (`bar.ts.date() >= said_on.date()`) does not itself need any slack -- the first
#: bar on or after the exact date is correct with a zero-day margin. This buffer exists only so a
#: fetch that starts exactly on a market holiday or weekend still lands comfortably inside whatever
#: window the underlying provider/store considers "this request's start", rather than riding the exact
#: boundary of a clamp or a calendar edge case. The contract's own wording -- "a few days earlier is
#: fine to be safe" -- says this is a safety margin, not a load-bearing number, so a small fixed value
#: is enough.
_FETCH_START_BUFFER = timedelta(days=5)


@dataclass(frozen=True)
class _Call:
    """One note's `TickerMention`, dated and ready to price. The intermediate shape this module
    builds calls into before it knows whether a symbol's bars are even reachable -- kept separate
    from `CallScore` because `CallScore` also carries the *result* of pricing, which is not known
    until the symbol's series has been fetched."""

    symbol: str
    stance: Stance
    note_id: str
    said_on: datetime


def _warn(warnings: list[DigestWarning], seen: set[tuple[str, str]], *, source: str, reason: str) -> None:
    """Append a `DigestWarning`, deduplicated on `(source, reason)`.

    Dedup matters here specifically: a symbol with several undated notes, or a symbol whose series is
    unreachable, would otherwise produce one identical warning per mention/call instead of one warning
    per distinct cause -- noise that tells the reader nothing a single entry would not.
    """
    key = (source, reason)
    if key in seen:
        return
    seen.add(key)
    warnings.append(DigestWarning(source=source, reason=reason))


def _collect_calls(
    notes: Sequence[EpisodicNote], warnings: list[DigestWarning], seen: set[tuple[str, str]]
) -> list[_Call]:
    """Every scorable call across `notes`, in the order encountered. A note whose `published` is
    `None` has no anchor date and cannot be scored at all -- never guessed, per the contract -- so
    every one of its mentions is warned about instead of turned into a call."""
    calls: list[_Call] = []
    for note in notes:
        if note.published is None:
            for mention in note.mentions:
                _warn(warnings, seen, source=mention.symbol, reason="no published date")
            continue
        for mention in note.mentions:
            calls.append(
                _Call(
                    symbol=mention.symbol,
                    stance=mention.stance,
                    note_id=note.note_id,
                    said_on=note.published,
                )
            )
    return calls


def _group_by_symbol(calls: Sequence[_Call]) -> dict[str, list[_Call]]:
    """Group calls by symbol, preserving first-seen order of symbols -- the order `ensure_series` is
    then called in, which matters only for test determinism, not for correctness."""
    grouped: dict[str, list[_Call]] = {}
    for call in calls:
        grouped.setdefault(call.symbol, []).append(call)
    return grouped


def _fetch_bars(
    symbol: str,
    calls: Sequence[_Call],
    settings: Settings,
    warnings: list[DigestWarning],
    seen: set[tuple[str, str]],
) -> list[Bar]:
    """The symbol's full daily series, fetched exactly once, sorted ascending by `ts`.

    Returns an empty list -- never raises -- on anything that makes the symbol unscorable: the store
    truly has nothing for it (`ProviderUnavailable` with nothing to fall back on, per
    `ensure_series`'s own contract), or a healthy fetch simply came back with zero bars. Both collapse
    every one of this symbol's calls to `no_data` one level up; the caller does not need to
    distinguish "could not ask" from "asked and there was nothing".
    """
    earliest = min(call.said_on.astimezone(UTC).date() for call in calls)
    start = earliest - _FETCH_START_BUFFER

    try:
        series = ensure_series(symbol, Interval.DAY, start=start, settings=settings)
    except ProviderUnavailable as exc:
        _log.info("score_calls: %s has no usable bars (provider unavailable: %s)", symbol, exc)
        _warn(warnings, seen, source=symbol, reason="no market data")
        return []

    if not series.bars:
        _warn(warnings, seen, source=symbol, reason="no market data")
        return []

    return sorted(series.bars, key=lambda b: b.ts)


def _entry_bar(bars: Sequence[Bar], said_on: date) -> tuple[int, Bar] | None:
    """The first bar with `bar.ts.date() >= said_on` -- never an earlier one. See the module
    docstring for why this direction, and not the reverse, is the only one that avoids look-ahead.
    `None` when every stored bar predates the statement (a call from today, or later than the last
    settled session): that is `pending`, not a bar to guess at.

    Returns the bar's index in `bars` alongside the bar itself -- not just for convenience. Fixed-
    horizon scoring (Phase 3b) needs to walk forward a fixed *number of bars* from entry
    (`bars[entry_idx + days]`), and re-deriving that index by scanning `bars` a second time would be
    both wasteful and a second place the "which bar is entry" answer could drift from this one.
    """
    for idx, bar in enumerate(bars):
        if bar.ts.date() >= said_on:
            return idx, bar
    return None


def _basis_and_prices(entry: Bar, latest: Bar) -> tuple[Literal["adjusted", "close"], float, float]:
    """Pick one basis for both endpoints -- adjusted close only when *both* bars have one, raw close
    otherwise. Never mixes a raw close at one end with an adjusted close at the other: that would
    silently fold a split or dividend adjustment into only half of the measured move."""
    if entry.adj_close is not None and latest.adj_close is not None:
        return "adjusted", entry.adj_close, latest.adj_close
    return "close", entry.close, latest.close


def _pct_return(entry_price: float, other_price: float) -> float:
    """`(other/entry - 1) * 100`, guarding a zero entry print.

    A zero entry print is not a real market condition for anything this feature tracks, but guarding
    it means a corrupted or delisted-and-halted bar degrades one number to `0.0` rather than raising
    `ZeroDivisionError` out of an otherwise-healthy scorecard. Shared by return-to-today and every
    fixed-horizon return so the two can never compute a percentage differently.
    """
    return 0.0 if entry_price == 0 else (other_price / entry_price - 1) * 100.0


def _horizon_returns(
    bars: Sequence[Bar], entry_idx: int, entry: Bar, horizons: Sequence[int]
) -> tuple[HorizonReturn, ...]:
    """One `HorizonReturn` per configured horizon, counting bars (not calendar days) forward from
    entry -- see `docs/INFLUENCER-CONTRACT.md`, "Fixed-horizon scoring", for why trading-day horizons
    are the comparable unit across calls made at different times.

    `bars[entry_idx + days]` is the horizon bar. When `entry_idx + days >= len(bars)` that many
    trading sessions have not happened yet in the stored series -- the horizon is **incomplete**, and
    `return_pct` stays `None` rather than being extrapolated from a bar that does not exist. Basis
    selection reuses `_basis_and_prices` so a horizon return can never pick a different adjusted/raw
    basis than return-to-today would for the same two endpoints.
    """
    out: list[HorizonReturn] = []
    for days in horizons:
        idx = entry_idx + days
        if idx >= len(bars):
            out.append(HorizonReturn(days=days, return_pct=None, complete=False))
            continue
        horizon_bar = bars[idx]
        _basis, entry_price, horizon_price = _basis_and_prices(entry, horizon_bar)
        out.append(
            HorizonReturn(days=days, return_pct=_pct_return(entry_price, horizon_price), complete=True)
        )
    return tuple(out)


def _outcome(stance: Stance, return_pct: float) -> CallOutcome:
    """`stance` plus the (already-computed) `return_pct` for a call that has a priced entry and
    latest bar -- `pending`/`no_data` are decided by the caller before this is ever reached, since
    both mean there is no `return_pct` to classify."""
    if stance in ("neutral", "unclear"):
        return "not_directional"
    if abs(return_pct) < _FLAT_BAND_PCT:
        return "flat"
    if stance == "bullish":
        return "played_out" if return_pct > 0 else "went_against"
    # stance == "bearish"
    return "played_out" if return_pct < 0 else "went_against"


def _score_call(call: _Call, bars: Sequence[Bar], horizons: Sequence[int]) -> CallScore:
    """One `_Call` plus its symbol's already-fetched bars -> one `CallScore`.

    `bars` empty is `no_data`; no entry bar found is `pending`. Both leave every priced field `None`
    and `horizons=()` -- see the module docstring's discipline on `None` vs. a fabricated `0.0`, and
    the contract's rule that a call with no entry has nothing to measure a fixed window from either.
    """
    if not bars:
        return CallScore(
            symbol=call.symbol,
            stance=call.stance,
            note_id=call.note_id,
            said_on=call.said_on,
            entry_date=None,
            entry_price=None,
            latest_date=None,
            latest_price=None,
            return_pct=None,
            basis=None,
            outcome="no_data",
        )

    said_on_date = call.said_on.astimezone(UTC).date()
    located = _entry_bar(bars, said_on_date)
    if located is None:
        return CallScore(
            symbol=call.symbol,
            stance=call.stance,
            note_id=call.note_id,
            said_on=call.said_on,
            entry_date=None,
            entry_price=None,
            latest_date=None,
            latest_price=None,
            return_pct=None,
            basis=None,
            outcome="pending",
        )
    entry_idx, entry = located

    latest = bars[-1]
    basis, entry_price, latest_price = _basis_and_prices(entry, latest)
    return_pct = _pct_return(entry_price, latest_price)

    return CallScore(
        symbol=call.symbol,
        stance=call.stance,
        note_id=call.note_id,
        said_on=call.said_on,
        entry_date=entry.ts,
        entry_price=entry_price,
        latest_date=latest.ts,
        latest_price=latest_price,
        return_pct=return_pct,
        basis=basis,
        outcome=_outcome(call.stance, return_pct),
        horizons=_horizon_returns(bars, entry_idx, entry, horizons),
    )


#: Outcomes that count toward the hit-rate denominator: directional calls that actually got priced.
#: `pending`, `no_data` (never priced) and `not_directional` (not a directional call at all) are
#: excluded -- see `PersonaScorecard.hit_rate`'s own docstring on why a rate over zero calls is `None`,
#: not `0.0`.
_DIRECTIONAL_PRICED: frozenset[CallOutcome] = frozenset({"played_out", "went_against", "flat"})


def _signed_return(call: CallScore) -> float | None:
    """The signed return `median_return_pct` averages over: `return_pct` for a bullish call, its
    negation for a bearish one, so a persona who is consistently right trends positive regardless of
    which direction they called. `None` only when `return_pct` itself is `None`, which cannot happen
    for a call in `_DIRECTIONAL_PRICED` -- kept as a guard rather than an assumption so a future bug
    fails loudly instead of feeding `None` into `statistics.median`."""
    if call.return_pct is None:
        return None
    return call.return_pct if call.stance == "bullish" else -call.return_pct


def _horizon_stats(scored: Sequence[CallScore], horizons: Sequence[int]) -> tuple[HorizonStat, ...]:
    """One `HorizonStat` per configured horizon, over directional calls (stance bullish/bearish) whose
    return at that horizon is `complete` -- see the contract's "Fixed-horizon scoring".

    Mirrors the top-level return-to-today aggregate's discipline exactly, just re-run per horizon
    instead of over `CallScore.return_pct`: a `flat` horizon return counts toward `directional_count`
    but not `played_out` (a call that went nowhere by that horizon is not a hit), and `hit_rate`/
    `median_return_pct` are both `None` -- never `0.0` -- when `directional_count == 0`. Reuses
    `_outcome` rather than re-deriving the flat-band/direction rule a second time, so a horizon call
    can never be classified differently than an equivalent return-to-today call would be.
    """
    horizon_stats: list[HorizonStat] = []
    for days in horizons:
        signed_returns: list[float] = []
        played_out = 0
        directional_count = 0
        for call in scored:
            if call.stance not in ("bullish", "bearish"):
                continue
            horizon = next((h for h in call.horizons if h.days == days), None)
            if horizon is None or not horizon.complete or horizon.return_pct is None:
                continue
            directional_count += 1
            if _outcome(call.stance, horizon.return_pct) == "played_out":
                played_out += 1
            signed_returns.append(
                horizon.return_pct if call.stance == "bullish" else -horizon.return_pct
            )
        horizon_stats.append(
            HorizonStat(
                days=days,
                directional_count=directional_count,
                played_out=played_out,
                hit_rate=(played_out / directional_count) if directional_count else None,
                median_return_pct=median(signed_returns) if signed_returns else None,
                mean_return_pct=(sum(signed_returns) / len(signed_returns)) if signed_returns else None,
                hit_rate_ci=stats.proportion(played_out, directional_count),
                return_ci=stats.bootstrap_mean(signed_returns),
            )
        )
    return tuple(horizon_stats)


def score_calls(
    *,
    persona_slug: str,
    notes: Sequence[EpisodicNote],
    settings: Settings,
    now: datetime | None = None,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
) -> PersonaScorecard:
    """Score every dated `TickerMention` across `notes` into a `PersonaScorecard`.

    Fetches each distinct symbol's daily bar series exactly once (earliest `said_on` across that
    symbol's mentions, minus a small safety buffer, through today), then prices every one of that
    symbol's calls against the same series -- never one `ensure_series` call per note. A symbol whose
    series cannot be produced at all (`ProviderUnavailable` with nothing stored to fall back on, or a
    healthy fetch that comes back empty) scores every call on that symbol `no_data` and is named in
    `warnings`, rather than failing the whole scorecard -- this endpoint is always-200 per the
    contract.

    `now` is accepted purely so tests can pin `as_of` and the "is this call pending" boundary; it
    plays no role in the entry-price rule itself (no-look-ahead is a property of the *stored bars*,
    not of the wall clock).

    `horizons` defaults to `DEFAULT_HORIZONS` (5/20/60 trading days) and drives both
    `CallScore.horizons` (per-call, empty for `pending`/`no_data`) and the returned
    `PersonaScorecard.horizon_stats` (per-horizon aggregates over directional calls whose horizon has
    fully elapsed) -- the window-independent complement to the return-to-today fields above.
    """
    effective_now = now or datetime.now(UTC)
    warnings: list[DigestWarning] = []
    seen_warnings: set[tuple[str, str]] = set()

    calls = _collect_calls(notes, warnings, seen_warnings)
    grouped = _group_by_symbol(calls)

    scored: list[CallScore] = []
    for symbol, symbol_calls in grouped.items():
        bars = _fetch_bars(symbol, symbol_calls, settings, warnings, seen_warnings)
        for call in symbol_calls:
            scored.append(_score_call(call, bars, horizons))

    scored.sort(key=lambda c: c.said_on, reverse=True)

    directional = [c for c in scored if c.outcome in _DIRECTIONAL_PRICED]
    played_out = sum(1 for c in directional if c.outcome == "played_out")
    hit_rate = (played_out / len(directional)) if directional else None
    signed_returns = [r for c in directional if (r := _signed_return(c)) is not None]
    median_return_pct = median(signed_returns) if signed_returns else None

    return PersonaScorecard(
        persona=persona_slug,
        as_of=effective_now,
        scored_calls=tuple(scored),
        directional_count=len(directional),
        played_out=played_out,
        hit_rate=hit_rate,
        median_return_pct=median_return_pct,
        hit_rate_ci=stats.proportion(played_out, len(directional)),
        horizon_stats=_horizon_stats(scored, horizons),
        warnings=tuple(warnings),
    )
