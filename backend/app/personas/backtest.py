"""A descriptive backtest LENS over a persona's dated calls: did following them beat holding SPY?

**The question this module answers, and only this question:** for every directional call an
influencer made (a `TickerMention` with stance bullish or bearish, dated and priced by
`app.personas.scoring.score_calls`), at each fixed trading-day horizon (5/20/60), how did the
persona's mean SIGNED call return compare to SPY's mean return over the SAME entry->exit windows?
This is explicitly NOT a strategy recommendation and NOT an alpha claim -- small samples over a
single historical window prove nothing about skill, which is why every `PersonaBacktest` carries a
fixed `caveat` the UI must render. See `docs/INFLUENCER-CONTRACT.md`, "Phase 4b -- persona backtest
lens (pinned)", for the exact wire contract this module implements; the semantics below restate it,
they do not vary it.

**This module reuses `score_calls` rather than re-deriving entries.** Call scoring (Phase 3a/3b) has
already solved "what was the entry price, was the horizon complete, what was the signed return" --
re-implementing any of that here would be a second place those answers could drift from the
scorecard the rest of the persona feature already shows. This module's only new work is fetching
SPY once and pricing the SAME entry->exit windows against it.

**No-look-ahead benchmark anchoring.** For a call whose entry fell on `entry_date`, the benchmark
entry is SPY's first daily bar with `ts.date() >= entry_date.date()` -- never an earlier one. This is
the identical rule `scoring._entry_bar` uses for the call's own symbol, applied a second time against
SPY, so the persona's window and the benchmark's window start on the same trading session by
construction. The benchmark exit is the SPY bar exactly `days` trading sessions after that entry bar;
when that bar does not exist yet in the fetched series, the benchmark window is unavailable for that
call at that horizon -- the call is excluded from the aggregate and a warning is recorded, never
counted as a zero return.

**`None`, not `0.0`, when a horizon's aggregate has no qualifying calls.** `n == 0` means "no
directional call had both a complete horizon return AND a priced benchmark window at this horizon" --
undefined, not measured-and-flat. Collapsing that into `0.0` would make "we have no answer" and "we
measured no edge" indistinguishable to anything downstream that reads the field, exactly the
discipline `scoring.py`'s own module docstring lays out for `CallScore`/`PersonaScorecard`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from statistics import fmean
from typing import Final

from app.config import Settings
from app.db.duck import Interval
from app.market.models import Bar
from app.market.providers.base import ProviderError
from app.market.store import ensure_series  # patched as `backtest.ensure_series` in tests
from app.personas.models import (
    BenchmarkedHorizon,
    CallScore,
    DigestWarning,
    EpisodicNote,
    PersonaBacktest,
)
from app.personas.scoring import DEFAULT_HORIZONS, score_calls  # patched as `backtest.score_calls`

__all__ = ["BENCHMARK", "run_backtest"]

_log = logging.getLogger(__name__)

#: Fixed for now -- the market proxy this repo already uses everywhere. Pinned by the contract, not
#: a per-persona or per-request choice.
BENCHMARK: Final[str] = "SPY"

#: A fixed sentence every `PersonaBacktest` carries, and every UI rendering one must show. Small
#: samples over a single historical window are not evidence of skill; this exists so that claim is
#: never separated from the numbers it qualifies.
_CAVEAT: Final[str] = (  # a module constant; put a real, honest sentence here
    "Descriptive and backward-looking over a single window with small samples -- this is not a "
    "measure of skill, a prediction, or advice. It compares following the persona's dated calls "
    "against holding SPY over the same holding periods."
)

#: Slack subtracted from the earliest directional call's `entry_date` before fetching SPY's series.
#: Same reasoning as `scoring._FETCH_START_BUFFER`: the no-look-ahead anchoring rule itself needs no
#: slack (the first bar on or after the exact date is correct with a zero-day margin), this is only
#: a safety margin against a fetch that starts exactly on a market holiday or weekend.
_FETCH_START_BUFFER: Final[timedelta] = timedelta(days=5)

_DIRECTIONAL_STANCES = ("bullish", "bearish")


def _warn(warnings: list[DigestWarning], seen: set[tuple[str, str]], *, source: str, reason: str) -> None:
    """Append a `DigestWarning`, deduplicated on `(source, reason)` -- identical to `scoring._warn`.
    Without dedup, several calls failing the same horizon for the same underlying cause would each
    print their own warning instead of one entry per distinct cause."""
    key = (source, reason)
    if key in seen:
        return
    seen.add(key)
    warnings.append(DigestWarning(source=source, reason=reason))


def _directional_calls(scored: Sequence[CallScore]) -> list[CallScore]:
    """Directional calls (bullish/bearish) that reached a priced entry.

    A call without `entry_date` (`pending`, `no_data`, or a note `score_calls` could not date at
    all) has nothing to anchor a benchmark window against -- `scoring.score_calls` already recorded
    why in its own `warnings`, which this module folds into its own output rather than re-deriving.
    """
    return [c for c in scored if c.stance in _DIRECTIONAL_STANCES and c.entry_date is not None]


def _fetch_benchmark(
    earliest_entry: date,
    settings: Settings,
    warnings: list[DigestWarning],
    seen: set[tuple[str, str]],
) -> list[Bar]:
    """SPY's daily series, fetched exactly once, sorted ascending by `ts`.

    Returns an empty list -- never raises -- when SPY cannot be served at all: `ProviderError` (a
    real provider failure with nothing stored to fall back on -- `ensure_series` only raises when the
    store is otherwise empty) or a healthy fetch that comes back with zero bars. Both leave every
    horizon at `n == 0` one level up, with a single warning explaining why, per the contract's "never
    a 5xx" rule.
    """
    start = earliest_entry - _FETCH_START_BUFFER
    try:
        series = ensure_series(BENCHMARK, Interval.DAY, start=start, settings=settings)
    except ProviderError as exc:
        _log.info("run_backtest: SPY has no usable bars (provider error: %s)", exc)
        _warn(warnings, seen, source=BENCHMARK, reason="no market data")
        return []

    if not series.bars:
        _warn(warnings, seen, source=BENCHMARK, reason="no market data")
        return []

    return sorted(series.bars, key=lambda b: b.ts)


def _index_at_or_after(bars: Sequence[Bar], target: date) -> int | None:
    """The first SPY bar with `bar.ts.date() >= target` -- the identical no-look-ahead rule
    `scoring._entry_bar` applies to a call's own symbol, applied here to the benchmark. `None` when
    every stored SPY bar predates `target` (the fetched window did not reach far enough forward yet)."""
    for idx, bar in enumerate(bars):
        if bar.ts.date() >= target:
            return idx
    return None


def _signed_return(call: CallScore, days: int) -> float | None:
    """The call's signed return at `days` -- `+return_pct` bullish, `-return_pct` bearish -- or
    `None` when that horizon has not elapsed yet (`complete is False`) or was never priced."""
    horizon = next((h for h in call.horizons if h.days == days), None)
    if horizon is None or not horizon.complete or horizon.return_pct is None:
        return None
    return horizon.return_pct if call.stance == "bullish" else -horizon.return_pct


def _horizon(
    days: int,
    directional: Sequence[CallScore],
    bars: Sequence[Bar],
    warnings: list[DigestWarning],
    seen: set[tuple[str, str]],
) -> BenchmarkedHorizon:
    """One `BenchmarkedHorizon`: every directional call whose call-side horizon is complete AND
    whose SPY entry->exit window exists at `days`, compared pairwise so `mean_return_pct` and
    `mean_benchmark_pct` are always means over the exact same set of windows -- never one aggregate
    over more calls than the other, which would make `excess_pct` compare apples to a different
    basket of oranges."""
    signed_returns: list[float] = []
    benchmark_returns: list[float] = []
    wins = 0

    for call in directional:
        signed = _signed_return(call, days)
        if signed is None:
            continue

        assert call.entry_date is not None  # guaranteed by `_directional_calls`
        entry_date = call.entry_date.astimezone(UTC).date()
        j = _index_at_or_after(bars, entry_date)
        if j is None or j + days >= len(bars):
            _warn(
                warnings,
                seen,
                source=BENCHMARK,
                reason=f"no benchmark window at the {days}-day horizon for one or more calls",
            )
            continue

        benchmark_return = (bars[j + days].close / bars[j].close - 1.0) * 100.0
        signed_returns.append(signed)
        benchmark_returns.append(benchmark_return)
        if signed > benchmark_return:
            wins += 1

    n = len(signed_returns)
    if n == 0:
        return BenchmarkedHorizon(days=days)

    mean_return_pct = fmean(signed_returns)
    mean_benchmark_pct = fmean(benchmark_returns)
    return BenchmarkedHorizon(
        days=days,
        n=n,
        mean_return_pct=mean_return_pct,
        mean_benchmark_pct=mean_benchmark_pct,
        excess_pct=mean_return_pct - mean_benchmark_pct,
        win_rate_vs_benchmark=wins / n,
    )


def run_backtest(
    *,
    persona_slug: str,
    notes: Sequence[EpisodicNote],
    settings: Settings,
    now: datetime | None = None,
) -> PersonaBacktest:
    """Score `notes` via `score_calls`, then compare its directional calls to SPY over the same
    entry->exit windows at each of `scoring.DEFAULT_HORIZONS`.

    `call_count` counts every directional (bullish/bearish) call that reached a priced entry, whether
    or not any of its horizons ends up qualifying for the aggregate below -- it answers "how many
    calls did this persona actually make that could in principle be benchmarked", not "how many
    landed in a horizon's `n`". SPY is fetched exactly once, from the earliest such call's
    `entry_date` (minus a small safety buffer) through today, and is skipped entirely when there are
    no directional calls to benchmark against -- an empty scorecard needs no network call.

    Always 200-shaped: a `ProviderError` fetching SPY, or an empty SPY series, degrades to
    `n == 0` on every horizon plus one `DigestWarning`, never an exception.
    """
    effective_now = now or datetime.now(UTC)
    warnings: list[DigestWarning] = []
    seen_warnings: set[tuple[str, str]] = set()

    card = score_calls(persona_slug=persona_slug, notes=notes, settings=settings, now=now)
    for w in card.warnings:
        _warn(warnings, seen_warnings, source=w.source, reason=w.reason)

    directional = _directional_calls(card.scored_calls)
    call_count = len(directional)

    if not directional:
        horizons = tuple(BenchmarkedHorizon(days=days) for days in DEFAULT_HORIZONS)
        return PersonaBacktest(
            persona=persona_slug,
            as_of=effective_now,
            benchmark=BENCHMARK,
            call_count=0,
            horizons=horizons,
            caveat=_CAVEAT,
            warnings=tuple(warnings),
        )

    earliest_entry = min(c.entry_date for c in directional if c.entry_date is not None).astimezone(UTC).date()
    bars = _fetch_benchmark(earliest_entry, settings, warnings, seen_warnings)

    if not bars:
        horizons = tuple(BenchmarkedHorizon(days=days) for days in DEFAULT_HORIZONS)
    else:
        horizons = tuple(
            _horizon(days, directional, bars, warnings, seen_warnings) for days in DEFAULT_HORIZONS
        )

    return PersonaBacktest(
        persona=persona_slug,
        as_of=effective_now,
        benchmark=BENCHMARK,
        call_count=call_count,
        horizons=horizons,
        caveat=_CAVEAT,
        warnings=tuple(warnings),
    )
