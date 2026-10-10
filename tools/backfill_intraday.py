"""Backfill the bar store with intraday history for the research universe, across every interval.

    ./.venv/Scripts/python.exe tools/backfill_intraday.py
    ./.venv/Scripts/python.exe tools/backfill_intraday.py --symbols SPY,QQQ --intervals 5m,15m
    ./.venv/Scripts/python.exe tools/backfill_intraday.py --dry-run --verbose

Why this exists, and why it is urgent: intraday history is perishable. Yahoo serves a rolling 60-day
window for 5m/15m/30m bars and ~730 days for 1h/4h (see `Interval`'s docstring in `app.db.duck`), so
every calendar day this tool does not run against the live provider is a day of intraday history that
can never be recovered later. `1d` is unbounded and `1w` is not fetched at all -- see below.

This is a thin CLI wrapper around `app.market.store.sync_bars`, the project's own store entry point.
It does no parquet I/O and no HTTP of its own: `sync_bars` handles the provider fallback walk, the
incremental-vs-full fetch window, the merge-dedup write and the meta sidecar. This tool's whole job is
to walk `(symbol, interval)` pairs for the 20-symbol research universe (`app.timeframes.
RESEARCH_UNIVERSE`), call `sync_bars` for each, not let one bad pair take down the other ~119, and
report what actually landed.

**`1w` is never fetched.** `app.market.store` derives weekly bars from stored daily bars on every
read (see that module's docstring) -- storing a separate weekly series would create two
representations of the same week that drift apart the moment a daily bar is corrected. So `1w` is
excluded from the default `--intervals` list, and if a caller passes it explicitly anyway, this tool
skips that pair with an explicit log line rather than silently dropping it or (worse) calling
`sync_bars` on it, which would quietly redirect to a daily sync a caller did not ask for and did not
see happen.

**Idempotency.** Running this twice must not duplicate bars. Verified by reading
`app.db.duck._merge_and_write`: every write is a read-merge-write keyed on `ts` --
``ROW_NUMBER() OVER (PARTITION BY ts ORDER BY src)`` with the incoming batch winning ties -- so a
bar already on disk for a given timestamp is replaced in place, never appended alongside itself. That
merge behaviour is also exercised directly by `tests/test_market_store.py` (e.g. re-syncing the same
provider frame and asserting the row count does not grow). This tool adds nothing on top of that
merge; it is idempotent because `sync_bars` already is.

**Robustness**, because this walks roughly 120 pairs against a live, rate-limitable provider:

* One pair failing never aborts the run -- every pair is wrapped in its own `try`/`except`, the
  failure is recorded, and the walk continues. The process exits non-zero if *any* pair failed, but
  only after every pair has been attempted.
* `SymbolNotFound` (`app.market.providers.base`) is treated as terminal for that symbol, not retried:
  the upstream is healthy and says the ticker does not exist, so every other interval for that same
  symbol is skipped too rather than re-asking a question already answered.
* `RateLimited` (a subclass of `ProviderUnavailable`) gets a bounded backoff-and-retry: this tool
  sleeps (using the provider's own `retry_after` when it supplies one, otherwise an exponential
  backoff seeded by `--retry-backoff`) and tries again, up to `--max-retries` times, before giving up
  on that one pair.
* Any other `ProviderUnavailable` (network failure, timeout, 5xx, a parsing failure) is recorded as a
  failure for that pair after a single attempt and the walk moves on.
* A small delay (`--delay`, default 0.5s) is inserted between provider calls as a politeness
  measure, even though no rate limit has been observed in a burst probe -- that absence of evidence
  is not evidence of no ceiling.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from app.config import Settings, get_settings
from app.db.duck import Interval
from app.market import store
from app.market.providers.base import (
    ProviderError,
    RateLimited,
    SymbolNotFound,
)
from app.market.registry import ProviderRegistry, default_registry
from app.timeframes import RESEARCH_UNIVERSE

__all__ = [
    "DEFAULT_INTERVALS",
    "DEFAULT_SYMBOLS",
    "PairResult",
    "main",
    "parse_args",
    "print_summary",
    "run_backfill",
]

#: Every interval `sync_bars` will actually ask a provider for. `Interval.WEEK` is excluded on
#: purpose -- see the module docstring -- and is handled as an explicit skip inside `run_backfill`
#: rather than removed from the `Interval` enum's own ordering.
DEFAULT_INTERVALS: tuple[Interval, ...] = tuple(i for i in Interval if i is not Interval.WEEK)

#: The frozen 20-symbol research universe, symbols only (sector is `app.timeframes`'s concern, not
#: this tool's). Imported, never redefined -- see `app.timeframes.models.RESEARCH_UNIVERSE`.
DEFAULT_SYMBOLS: tuple[str, ...] = tuple(symbol for symbol, _sector in RESEARCH_UNIVERSE)

Status = Literal["ok", "failed", "skipped"]

LogFn = Callable[[str], None]


@dataclass
class PairResult:
    """The outcome of backfilling one `(symbol, interval)` pair."""

    symbol: str
    interval: Interval
    status: Status
    bars_before: int | None = None
    bars_after: int | None = None
    bars_added: int | None = None
    first_ts: dt.datetime | None = None
    last_ts: dt.datetime | None = None
    elapsed_s: float = 0.0
    attempts: int = 1
    detail: str = ""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help=(
            "comma-separated symbols (default: the full 20-symbol RESEARCH_UNIVERSE: "
            f"{','.join(DEFAULT_SYMBOLS)})"
        ),
    )
    parser.add_argument(
        "--intervals",
        type=str,
        default=None,
        help=(
            "comma-separated intervals (default: all fetchable -- "
            f"{','.join(i.value for i in DEFAULT_INTERVALS)} -- i.e. all seven EXCLUDING 1w, which "
            "is derived from daily and never fetched; passing 1w explicitly does not fetch it "
            "either, it is skipped with a log line)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="walk every pair and report current coverage, but perform no writes",
    )
    parser.add_argument("--verbose", action="store_true", help="log provider warnings per pair")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="seconds to sleep between provider calls (default: %(default)s)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="max retry attempts for a rate-limited pair before giving up on it (default: %(default)s)",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=5.0,
        help=(
            "seconds to wait before the first retry after a rate limit with no provider-supplied "
            "retry_after; doubles on each subsequent attempt (default: %(default)s)"
        ),
    )
    return parser.parse_args(argv)


def _parse_symbols(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return DEFAULT_SYMBOLS
    return tuple(s.strip().upper() for s in raw.split(",") if s.strip())


def _parse_intervals(raw: str | None) -> tuple[Interval, ...]:
    if raw is None:
        return DEFAULT_INTERVALS
    return tuple(Interval(token.strip().lower()) for token in raw.split(",") if token.strip())


def _sync_with_retries(
    symbol: str,
    interval: Interval,
    *,
    registry: ProviderRegistry,
    settings: Settings,
    max_retries: int,
    retry_backoff: float,
    log: LogFn,
    sleep: Callable[[float], None],
) -> tuple[store.SyncOutcome, int]:
    """Call `store.sync_bars`, retrying only on `RateLimited`, up to `max_retries` times.

    Returns the outcome together with the number of attempts made, so a caller (and a test) can tell
    a retry actually happened rather than the pair merely having succeeded on the first try.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            outcome = store.sync_bars(symbol, interval, registry=registry, settings=settings)
        except RateLimited as exc:
            if attempt > max_retries:
                raise
            wait = exc.retry_after if exc.retry_after is not None else retry_backoff * (2 ** (attempt - 1))
            log(
                f"    rate limited by {exc.provider} (attempt {attempt}/{max_retries + 1}); "
                f"waiting {wait:.1f}s before retrying"
            )
            sleep(wait)
            continue
        return outcome, attempt


def run_backfill(
    symbols: Iterable[str],
    intervals: Iterable[Interval],
    *,
    dry_run: bool = False,
    verbose: bool = False,
    delay: float = 0.5,
    max_retries: int = 3,
    retry_backoff: float = 5.0,
    registry: ProviderRegistry | None = None,
    settings: Settings | None = None,
    log: LogFn = print,
    sleep: Callable[[float], None] = time.sleep,
) -> list[PairResult]:
    """Walk every `(symbol, interval)` pair and backfill it through the store's own sync entry point.

    One failing pair never aborts the walk -- see the module docstring for the exact handling of
    `SymbolNotFound`, `RateLimited` and other `ProviderUnavailable` failures. `sleep` and `registry`/
    `settings` are injectable so tests can run this with no real clock delay and no real provider.
    """
    cfg = settings or get_settings()
    reg = registry or default_registry(cfg)

    symbols = tuple(symbols)
    intervals = tuple(intervals)
    pairs = list(itertools.product(symbols, intervals))
    total = len(pairs)

    results: list[PairResult] = []
    # A symbol confirmed not to exist by a healthy upstream stays not-found at every interval --
    # asking again per interval would just be 5 more slow, identical 404s per dead ticker.
    dead_symbols: set[str] = set()

    for index, (symbol, interval) in enumerate(pairs, start=1):
        prefix = f"[{index}/{total}] {symbol} {interval.value}"

        if interval is Interval.WEEK:
            log(
                f"{prefix}: SKIPPED -- 1w bars are derived from daily bars on read "
                "(app.market.store) and are never fetched or stored; not backfilling"
            )
            results.append(
                PairResult(
                    symbol=symbol,
                    interval=interval,
                    status="skipped",
                    detail="derived from daily on read, not fetched",
                )
            )
            continue

        if symbol in dead_symbols:
            log(f"{prefix}: SKIPPED -- {symbol} already confirmed not found by the provider")
            results.append(
                PairResult(
                    symbol=symbol,
                    interval=interval,
                    status="skipped",
                    detail="symbol already confirmed not found at an earlier interval",
                )
            )
            continue

        before = store.coverage(symbol, interval, settings=cfg)

        if dry_run:
            log(
                f"{prefix}: DRY-RUN -- currently {before.rows} bars "
                f"({before.first_ts} .. {before.last_ts}); no write performed"
            )
            results.append(
                PairResult(
                    symbol=symbol,
                    interval=interval,
                    status="ok",
                    bars_before=before.rows,
                    bars_after=before.rows,
                    bars_added=0,
                    first_ts=before.first_ts,
                    last_ts=before.last_ts,
                    elapsed_s=0.0,
                    detail="dry-run: no write performed",
                )
            )
            if delay:
                sleep(delay)
            continue

        started = time.time()
        try:
            outcome, attempts = _sync_with_retries(
                symbol,
                interval,
                registry=reg,
                settings=cfg,
                max_retries=max_retries,
                retry_backoff=retry_backoff,
                log=log,
                sleep=sleep,
            )
        except SymbolNotFound as exc:
            dead_symbols.add(symbol)
            elapsed = time.time() - started
            log(f"{prefix}: FAILED -- SymbolNotFound (terminal for this symbol): {exc}")
            results.append(
                PairResult(
                    symbol=symbol,
                    interval=interval,
                    status="failed",
                    bars_before=before.rows,
                    bars_after=before.rows,
                    bars_added=0,
                    first_ts=before.first_ts,
                    last_ts=before.last_ts,
                    elapsed_s=elapsed,
                    detail=f"SymbolNotFound: {exc}",
                )
            )
        except ProviderError as exc:
            # Covers RateLimited exhausted past max_retries, any other ProviderUnavailable
            # (network failure, timeout, 5xx, a parsing failure), and any other ProviderError.
            elapsed = time.time() - started
            log(f"{prefix}: FAILED -- {type(exc).__name__}: {exc}")
            results.append(
                PairResult(
                    symbol=symbol,
                    interval=interval,
                    status="failed",
                    bars_before=before.rows,
                    bars_after=before.rows,
                    bars_added=0,
                    first_ts=before.first_ts,
                    last_ts=before.last_ts,
                    elapsed_s=elapsed,
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
        except Exception as exc:
            elapsed = time.time() - started
            log(f"{prefix}: FAILED -- unexpected {type(exc).__name__}: {exc}")
            results.append(
                PairResult(
                    symbol=symbol,
                    interval=interval,
                    status="failed",
                    bars_before=before.rows,
                    bars_after=before.rows,
                    bars_added=0,
                    first_ts=before.first_ts,
                    last_ts=before.last_ts,
                    elapsed_s=elapsed,
                    detail=f"unexpected {type(exc).__name__}: {exc}",
                )
            )
        else:
            elapsed = time.time() - started
            after = outcome.coverage
            added = after.rows - before.rows
            retry_note = f" ({attempts} attempts)" if attempts > 1 else ""
            log(
                f"{prefix}: OK{retry_note} -- bars {before.rows} -> {after.rows} (+{added}) "
                f"range={after.first_ts} .. {after.last_ts} elapsed={elapsed:.1f}s"
            )
            if verbose:
                for warning in outcome.warnings:
                    log(f"    warning [{warning.kind}]: {warning.message}")
            results.append(
                PairResult(
                    symbol=symbol,
                    interval=interval,
                    status="ok",
                    bars_before=before.rows,
                    bars_after=after.rows,
                    bars_added=added,
                    first_ts=after.first_ts,
                    last_ts=after.last_ts,
                    elapsed_s=elapsed,
                    attempts=attempts,
                    detail="; ".join(w.message for w in outcome.warnings),
                )
            )

        if delay:
            sleep(delay)

    return results


def print_summary(results: Sequence[PairResult], *, log: LogFn = print) -> int:
    """Print the final per-pair table and totals; return the process exit code (0 or 1)."""
    log("")
    log("=" * 130)
    log(
        f"{'SYMBOL':<8}{'INTERVAL':<10}{'STATUS':<10}{'BEFORE':>9}{'AFTER':>9}{'ADDED':>9}  "
        f"{'FIRST':<28}{'LAST':<28}{'ELAPSED':>9}"
    )
    log("-" * 130)
    for r in results:
        first = r.first_ts.isoformat() if r.first_ts else "-"
        last = r.last_ts.isoformat() if r.last_ts else "-"
        log(
            f"{r.symbol:<8}{r.interval.value:<10}{r.status:<10}"
            f"{r.bars_before if r.bars_before is not None else '-':>9}"
            f"{r.bars_after if r.bars_after is not None else '-':>9}"
            f"{r.bars_added if r.bars_added is not None else '-':>9}  "
            f"{first:<28}{last:<28}{r.elapsed_s:>8.1f}s"
        )
    log("-" * 130)

    ok = [r for r in results if r.status == "ok"]
    failed = [r for r in results if r.status == "failed"]
    skipped = [r for r in results if r.status == "skipped"]
    total_added = sum(r.bars_added or 0 for r in ok)
    total_elapsed = sum(r.elapsed_s for r in results)

    log(
        f"TOTAL: {len(results)} pairs -- {len(ok)} ok, {len(failed)} failed, {len(skipped)} skipped "
        f"-- bars added: {total_added} -- elapsed: {total_elapsed:.1f}s"
    )

    if failed:
        log("")
        log("FAILURES:")
        for r in failed:
            log(f"  {r.symbol} {r.interval.value}: {r.detail}")

    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = _parse_symbols(args.symbols)
    intervals = _parse_intervals(args.intervals)

    print(
        f"backfill_intraday: {len(symbols)} symbols x {len(intervals)} intervals "
        f"= {len(symbols) * len(intervals)} pairs"
        + (" (DRY RUN)" if args.dry_run else ""),
        flush=True,
    )

    def log(msg: str) -> None:
        print(msg, flush=True)

    results = run_backfill(
        symbols,
        intervals,
        dry_run=args.dry_run,
        verbose=args.verbose,
        delay=args.delay,
        max_retries=args.max_retries,
        retry_backoff=args.retry_backoff,
        log=log,
    )
    return print_summary(results, log=log)


if __name__ == "__main__":
    sys.exit(main())
