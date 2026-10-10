# Phase 4 — Market data: store, providers, indicators, ticker page

**Date:** 2026-08-10 · **Status:** complete · **Next:** Phase 5 (macro dashboard)

Provider registry with typed fallback, incremental Parquet bar store, an indicator library that
feeds charts and (later) rules and backtests from one definition, and a ticker page with four
working timeframes.

**599 tests passing, ruff clean, mypy strict clean across 48 source files.** Frontend typechecks and
builds. Verified running: real candles, overlays and a synced oscillator pane in the browser.

The chart view also does two things the build order did not ask for, added on request: **all four
timeframes rendered at once**, and **multiple instances of one indicator, each in its own colour** —
`sma:20 / 50 / 100 / 200` as a ribbon rather than a single toggled line.

> Market data is **float**; ledger money stays **Decimal**. These are observations feeding
> statistics, and the upstream hands them over as IEEE doubles already. A quoted price must never
> reach a lot, a basis or a gain.

---

## What landed

Built contract-first again: the orchestrator wrote the shared models, the provider protocols, the
indicator contract and the TypeScript wire format, then four agents implemented against them in
parallel on disjoint file sets.

| Module | Lines | Tests | Owns |
|---|---|---|---|
| `market/providers/yahoo.py` | 471 | — | Bars, quote, profile off one endpoint; session-date normalisation; settled-bar rule |
| `market/providers/stooq.py` | 166 | — | Daily fallback, currently blocked, correctly typed |
| `market/providers/sec_edgar.py` | 119 | — | Ticker→CIK, company facts |
| `market/fundamentals.py` | 231 | 12 | Concept extraction, amended-filing dedup |
| `market/registry.py` | 205 | 13 | Fallback chain driven by exception class |
| `market/store.py` | 448 | 12 | Incremental sync, weekly resampling, coverage, stale fallback |
| `market/cache.py` | 163 | — | Response cache as an httpx transport |
| `indicators/` | 575 | 63 | SMA, EMA, MACD, RSI, Bollinger, ATR, anchored VWAP |
| `api/market.py` | 394 | 23 | Bars, quote, profile, indicators, catalog, ticker, sync |
| `pages/Ticker.tsx` + components | 958 | — | Four timeframes, catalog-driven overlays, terminal theme |

Providers and the store share `tests/test_providers.py` (40 tests). No test touches the network:
real wire captures live in `tests/fixtures/market/`.

---

## Four defects, all invisible to 571 green tests

Every module passed its own suite. Each of these lives where two modules meet, or between the code
and the live upstream — the places a hand-built fixture cannot reach.

### 1. "Daily" bars were monthly — silently, for 27 years of history

The production path fetched with `range=max`; the fixtures had been captured with `range=1y`. Yahoo
answers an over-wide request by **coarsening the data rather than refusing it**, reporting the
substitution only in `meta.dataGranularity`.

So `interval=1d` returned **330 monthly bars** where the true daily series has **6,897**. The
response is otherwise structurally identical — same fields, ascending timestamps, plausible prices —
and it landed in the `interval=1d` partition where nothing downstream could tell. Every indicator
computed from it was a monthly indicator wearing a daily label: an SMA(50) that was really a
50-*month* average, reading 478.83 against a real value of 714.27.

Fixed twice over: explicit `period1`/`period2` always, and a granularity assertion that refuses any
response whose bars are not the size requested. The second half is the durable one — it turns this
entire class of silent substitution into a loud failure.

### 2. Both intraday timeframes were completely dead

The retention window is **exclusive**: a 1h request spanning exactly 730 days is refused with HTTP
422; 729 days is served. The clamp computed exactly the limit, and `period2` is the day *after* the
end date, so every intraday request landed precisely on the one value guaranteed to fail.

**Half the phase's headline deliverable — four timeframes — did not work at all.** Daily has no
retention limit, so it never approached the boundary, and every test that exercised the fetch path
used daily bars. The suite was green.

Now enforced in the provider, which is the only layer that knows where it is putting the far edge of
its own window, with a parametrised test that runs over *every* interval rather than the one whose
fixture was at hand.

### 3. The response cache poisoned the second request to any gzip upstream

`response.content` is httpx's already-decoded body. The cache stored that plain body alongside the
original `Content-Encoding: gzip`, so replaying it made the client inflate uncompressed JSON and die
with a zlib header error.

It fails only on a cache *hit* — the first request of any run succeeds and the second one crashes.
SEC EDGAR serves gzip, so fetching one ticker's fundamentals worked and the next ticker's brought
down the request. Unit tests could not see it: `MockTransport` sets no encoding header, and a single
request never reads its own cache entry.

### 4. Parquet round-trips moved every daily bar back one day

DuckDB stores a `TIMESTAMP WITH TIME ZONE` as an instant and re-labels it with the *connection's*
timezone on read. A bar written as `2026-01-09T00:00Z` came back as `2026-01-08T18:00-06:00` on a
US-Central machine — the same instant, correctly, but a different calendar day the moment anything
called `.date()`.

That is precisely the failure the session-date convention exists to prevent, arriving through the
storage layer instead of the provider. It would shift every daily bar's session date for any user
west of UTC, put weekly bars in the wrong ISO week, and misalign bars against ledger trade dates —
silently, and invisibly on a UTC developer machine. The connection now pins UTC, so the round trip is
identity for every caller rather than something each one must remember to undo.

*(Found by the store agent, which worked around it locally and escalated rather than editing a
contract file. That was the right call and it is why the fix landed at the source.)*

---

## A fifth, caught by design rather than by accident

Stooq mapped its 404 to `SymbolNotFound`. That exception is **terminal** in the registry: it
re-raises at once and the user is told their ticker is wrong.

But Stooq is behind an anti-bot challenge — QQQ, which plainly exists, 404s there today — and it is
only ever reached *after* the primary has already failed. So a degraded fallback could overrule a
healthy primary and report "Yahoo is down" as "no such ticker": the wrong diagnosis, pointing the
user at their own typing instead of at the outage. Now a `ProviderResponseError`, which falls
through and aggregates.

This one surfaced because the error taxonomy was written down first. It is the argument for the
contract-first split in one example.

---

## What the live run produces

Real fetches, three symbols, all four intervals:

| Symbol | 1d | 1h | 5m | 1w (derived) |
|---|---|---|---|---|
| QQQ | 6,897 (1999-03-10→) | 3,485 | 3,042 | 1,432 |
| SOXL | 4,129 (2010-03-11→) | 3,485 | 3,042 | — |
| NVDA | 6,929 (1999-01-22→) | 3,485 | 3,042 | 1,439 |

- **Idempotent re-sync**: 2 rows re-fetched over the overlap window, 0 rows added, count unchanged.
- **Weekly reconciles**: last weekly close 720.87 = last daily close 720.87, aggregated not fetched.
- **No partial bar stored**: today's open session is absent from the daily partition.
- **JSON is valid**: no bare `NaN` token on any endpoint, including a MACD series that is 33 nulls
  deep at the head.
- **Fundamentals**: NVDA returns assets, liabilities, equity and net income off the 10-K. QQQ, an
  ETF, returns an explained absence — the common case for this portfolio.

Verified in the browser: SOXL 1h candles with an SMA(20) overlay starting *after* its warmup, a
magenta anchored VWAP available only on intraday, and RSI in a separate pane with a synchronised time
axis. No console errors.

---

## Design decisions worth knowing

- **The store holds settled bars only.** A bar whose session has not closed will still change;
  rather than persist a mutating value, the fetcher drops it and the view layer may append a live one
  tagged `partial`. Backtests read the store, so they *structurally* cannot see a partial bar — not a
  rule anyone has to remember.
- **Daily `ts` is the exchange-local session date at midnight UTC**, not the provider's raw
  timestamp. Yahoo stamps a US daily bar 13:30 UTC; `.date()` on that is right by luck for a UTC
  reader and wrong for everyone else.
- **`adj_close` is stored from day one.** Split-adjusted OHLC and split-plus-dividend-adjusted close
  answer different questions, and a dataset holding one cannot produce the other later. Retrofitting
  means rewriting every Parquet file.
- **`1w` is never fetched or stored** — resampled from stored daily bars on read, grouped by ISO
  week so holiday-shortened weeks come out right. Two stored representations of one week would drift
  apart the first time a daily bar was corrected.
- **Bollinger uses population standard deviation (`ddof=0`)**, matching every charting platform.
  Pandas defaults to `ddof=1`, which produces bands close enough to look right and wrong enough to
  shift band-touch trigger dates — the exact study planned for Phase 7.
- **RSI and ATR use Wilder's smoothing**, not a rolling mean.
- **The indicator catalog is served to the UI**, so overlay controls are generated from the same
  object the maths hangs off and cannot offer a parameter the backend rejects.

Two corrections came back from the agents and were adopted:

- **MACD warmup is `slow + signal − 2`, not `− 1`** — my brief had it wrong. Chained `ewm` calls
  compose on the NaN count, since `min_periods` counts non-null observations rather than re-counting
  the upstream's NaNs. Verified empirically: 33 leading nulls for 12/26/9, not 34.
- **Revenue must be chosen by recency across both XBRL tags, not by a fixed preference order.**
  Apple's `Revenues` tag holds only a stale 2018 figure while the current one sits under the ASC 606
  tag, so try-A-then-B reports seven-year-old revenue as current.

A fifth `ParamKind`, `CHOICE_OR_DATE`, was added to the indicator contract. Anchored VWAP takes
either `session` or a date, and encoding that as a plain choice over `("session",)` would have left
the frontend able to render only a one-option dropdown — making the date-anchored form, which is the
entire point of an *anchored* VWAP for post-drawdown analysis, unreachable from the UI.

---

## Three more defects, found by using the UI rather than testing it

The multi-instance overlays and the four-timeframe grid turned out to be a load test nobody had run.
Both features fire several requests for the same symbol at once — four panels mounting together, one
request per keystroke in a period box — and that broke three things that 594 green tests did not.

### The store was stale the instant it was written

`ensure_series` compared the **newest stored bar** against a one-day threshold. But the store
deliberately holds settled bars only, so during Monday's session the newest daily bar is Friday's —
already past the threshold, and further past it every minute.

**Every single request re-fetched from the provider.** Not just wasteful: it is what produced the
concurrent writes that then collided below. Two individually correct decisions — hold only settled
bars, refresh when the data looks old — wrong in combination. Staleness is now measured from the last
fetch, which is what the `fetched_at` sidecar was already recording.

### A shared staging filename, in two modules

`write_bars` and the HTTP cache both staged through a fixed temp path per target. Concurrent writers
fought over one filename: on Windows a hard `IOException`; on POSIX the rename silently succeeds and
one writer's output replaces the other's, which is worse — the failure becomes missing rows instead
of an error.

Fixed with uuid-named staging files plus a per-partition lock in the bar store, where the write is a
read-merge-write and a lost update means lost bars. The cache needs no lock — racing writers there
are storing the same response — but it does need to tolerate a failed replace, since on Windows the
*destination* is contended even when the staging name is unique. A failed cache write is not a failed
request.

### The VWAP anchor control could not express a date

Adding `ParamKind.CHOICE_OR_DATE` to the backend left the frontend rendering it through the fallback
branch — a **number input**, which can never produce `session` or a date. The control was inert from
the moment the kind was introduced. It now renders a token select plus a date field.

---

## The UI is now dark-neon terminal

Global rewrite of `styles.css`, so all five pages inherit it rather than only the new one. Near-black
ground `#07090c`, phosphor cyan `#39f2d0` primary with magenta secondary, monospace for anything that
reads as instrument output and sans retained for prose, ~2% scanline wash. Semantic roles are
unchanged — the Tax page's red still means *permanently destroyed loss*.

---

## Open items

| Item | Owner | Blocks |
|---|---|---|
| **Stooq is blocked by an anti-bot challenge** — the only fallback provider, currently non-functional | — | Nothing today; Yahoo is sole source, so a Yahoo outage is a full outage |
| **Yahoo is unauthenticated and unversioned** — the `range=max` behaviour was found by running it, not from documentation | — | The granularity guard now catches this class of change loudly |
| Session-anchored VWAP assumes `America/New_York` | next pass | Wrong session boundaries for a non-US listing |
| Date-anchored VWAP warmup cannot be expressed | — | `IndicatorSpec.warmup` takes params, not bars; covered by its own test instead of the registry sweep |
| SEC 404 on a resolved CIK maps to `SymbolNotFound` | — | Semantic looseness only; no fixture for the case |
| Volume indicators still deferred | you | The band-touch + volume-confirmation study in Phase 7 |
| Intraday history is capped at 729/59 days by the provider | — | Inherent to the free feed; daily is unbounded and is the only backtestable interval anyway |
