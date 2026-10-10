# Timeframe data feasibility — live-probed, 2026-08-25

Everything in this document was produced by hitting Yahoo's live chart API directly
(`https://query1.finance.yahoo.com/v8/finance/chart/{symbol}`) with the same `User-Agent`
`app/market/providers/yahoo.py` uses, and by reading the actual parquet files in
`data/store/bars/`. Nothing here is restated from docs or code comments without a live check
next to it. Probe scripts and raw output live in the scratchpad
(`scratchpad/probe_yahoo.py`, `scratchpad/full_output.log`) — not committed, per the scope fence
for this task.

Environment check: `.venv/Scripts/python.exe` is Python 3.12.10, imports
`app.market.providers.yahoo` cleanly, and has `httpx` 0.28.1 and `duckdb` 1.5.5 available.
**`pandas.read_parquet` fails in this venv** — no `pyarrow`/`fastparquet` installed — so the store
inspection below (task 6) was done via `duckdb.read_parquet()` instead, which works fine.

## Interval support table

| Token | Accepted by Yahoo? | Max history observed (single request) | SPY bars (best single request) | Native or resampled? |
|---|---|---|---|---|
| `5m` | Yes | Exactly 60 days | 1,717 (1mo window shown; ~60d fills more) | Native |
| `15m` | **Yes** | Exactly 60 days | 573 (1mo) | **Native** — not resampled, contra the brief |
| `30m` | **Yes** | Exactly 60 days | 287 (1mo) | **Native** — not resampled |
| `1h` / `60m` | Yes (identical results either token) | ~730 days (2y accepted, 5y rejected) | 3,498 (2y) | Native |
| `4h` | **Yes** | ~730 days (2y accepted, 5y rejected) | 1,003 (2y) | **Native** — Yahoo itself computes 4h bars, not resampled locally |
| `1d` | Yes | Full history (8,450 bars to 1993-01-29 for SPY, 11,705 to 1980-03-17 for AMD) — but only via `period1=0`, never `range=max` | 8,450 | Native |
| `1wk` | Yes | Full history (same span as daily) — same `range=max` trap applies | 404 (via `range=max`, wrongly downgraded — see below) | Native at Yahoo, but **this app never calls it** — resamples from stored daily instead |

**`app/market/providers/yahoo.py`'s `supported_intervals = {FIVE_MIN, HOUR, DAY}` and
`_YAHOO_INTERVAL` mapping under-represent what Yahoo will actually serve.** Yahoo accepts `15m`,
`30m`, and `4h` as valid `interval` values today, returns HTTP 200, correctly session-aligned bars,
and echoes the requested granularity back in `meta.dataGranularity` (i.e. no silent coarsening) —
exactly the same shape of response as the three intervals the app already trusts. There is no
`app.db.duck.Interval` member for 15m/30m/4h and no store partition for them, so this is not
something the app can use today, but it is a live Yahoo capability, not a documentation gap.

## Yahoo's own error text (verbatim)

Requesting a too-long span does not return a "valid intervals" list — every one of the 8 tokens
tested (`5m 15m 30m 1h 60m 4h 1d 1wk`) was accepted as a *recognized* interval in every probe;
Yahoo never once rejected a token as unknown. The only rejection shape observed is HTTP 422 on an
over-wide **window**, with the interval named back to you:

```
5m data not available for startTime=1779689242 and endTime=1787724442. The requested range must be within the last 60 days.
```
```
15m data not available for startTime=1779689246 and endTime=1787724446. The requested range must be within the last 60 days.
```
```
30m data not available for startTime=1779689251 and endTime=1787724451. The requested range must be within the last 60 days.
```
```
1h data not available for startTime=1630044457 and endTime=1787724457. The requested range must be within the last 730 days.
```
```
4h data not available for startTime=1630044466 and endTime=1787724466. The requested range must be within the last 730 days.
```

This directly confirms `INTERVAL_MAX_LOOKBACK` in `backend/app/market/models.py` for the two
intervals it covers (5m → 60d, 1h → 730d), and extends the same two numbers to the three
intervals the table doesn't mention: 15m and 30m share the 60-day cap with 5m; 4h shares the
730-day cap with 1h.

## The `range=max` trap — confirmed, and confirmed to apply to every interval

`yahoo.py`'s docstring warns that `range=max` silently downgrades to monthly bars for `1d`. Live
probing shows **this happens for every single token tested, not just `1d`** — `5m`, `15m`, `30m`,
`1h`, `4h`, `1wk` with `range=max` all came back with `meta.dataGranularity: "1mo"` and the same
404 monthly bars from 1993-02-01, regardless of what was requested. The only way to get true daily
granularity all the way back is what `yahoo.py` already does: explicit `period1=0`/`period2=now`,
never `range=max`. Verified directly: `period1=0` with `interval=1d` returned `dataGranularity:
"1d"` and 8,450 real daily bars for SPY (1993-01-29 → today), 11,705 for AMD (1980-03-17 → today).

## Max history sweep detail (SPY, single request)

| Interval | 1mo | 3mo | 6mo | 1y | 2y | 5y | 10y | `max` |
|---|---|---|---|---|---|---|---|---|
| 5m | 1,717 bars | 422 | 422 | 422 | 422 | 422 | — | downgraded to 1mo, 404 bars from 1993 |
| 15m | 573 | 422 | 422 | 422 | 422 | 422 | — | downgraded |
| 30m | 287 | 422 | 422 | 422 | 422 | 422 | — | downgraded |
| 1h | 155 | 449 | 876 | 1,754 | 3,498 | 422 | 422 | downgraded |
| 4h | 45 | 129 | 251 | 503 | 1,003 | 422 | 422 | downgraded |
| 1d | 22 | 64 | 125 | 251 | 501 | 1,254 | 2,512 | downgraded |
| 1wk | 6 | 15 | 28 | 54 | 106 | 263 | 524 | downgraded |

"422" means Yahoo rejected the window outright (`Unprocessable Entity`, the 60d/730d messages
above). Daily and weekly never reject — they just keep growing — until you hit `range=max`, which
silently corrupts the granularity instead of erroring.

## The 4h session-boundary problem

A US regular session is 6.5 hours (9:30–16:00 ET / 13:30–20:00 UTC). A fixed 4-hour bar does not
divide this evenly: 6.5 ÷ 4 = 1.625. Two ways to resolve this exist, and **Yahoo's live `4h` token
has already picked one** — verified by pulling individual bar timestamps for SPY over 5 days:

```
2026-08-19T13:30:00+00:00   <- session open
2026-08-19T17:30:00+00:00   <- 4h later: a short ~2.5h bar to session close (20:00) implied
2026-08-20T13:30:00+00:00
2026-08-20T17:30:00+00:00
2026-08-21T13:30:00+00:00
2026-08-21T17:30:00+00:00
2026-08-24T13:30:00+00:00
2026-08-24T17:30:00+00:00
2026-08-25T13:30:00+00:00
2026-08-25T17:30:00+00:00
2026-08-25T20:00:00+00:00   <- trailing bar stamped exactly at close, on the in-progress day
```

Every completed session shows exactly 2 bars/day: one full 4-hour bar (13:30–17:30) and one short
~2.5-hour remainder bar (17:30–20:00) that absorbs the leftover session time. Yahoo does **not**
emit an even 3.25h+3.25h split, and does not carry a partial bar over midnight into the next
session. The trailing `20:00:00` entry on the still-open day is the same "still-forming candle"
shape `yahoo.py`'s `_last_bar_unsettled` already exists to drop for 1h/5m — it just isn't wired up
for 4h because 4h isn't in `_YAHOO_INTERVAL`/`_BAR_DURATION` today.

**Options for this project, in order of effort:**

1. **Add `Interval.FOUR_HOUR` and fetch the native `4h` token directly**, extending
   `_YAHOO_INTERVAL`, `_BAR_DURATION` (with a variable-length duration or a session-close-aware
   rule, since the second bar of each day is short), `supported_intervals`, `INTERVAL_MAX_LOOKBACK`
   (730 days, same as 1h), and adding a `interval=4h` store partition. This is the option the live
   data supports best — Yahoo has already solved the boundary problem the same way for every
   symbol, no local resampling logic needed.
2. **Resample 4h locally from stored `1h` bars**, grouping by session date into buckets
   `[13:30,17:30)` and `[17:30,20:00)` — i.e. reimplementing exactly what Yahoo already does
   server-side. Only worth doing if the project wants 4h bars older than 730 days by stitching
   onto already-archived 1h history the app has accumulated past that window (see store note
   below) — Yahoo's own API cannot serve 4h data older than 730 days at all, natively or not.
3. **Do not build 4h at all** and treat it as out of reach — the weakest option, since option 1 is
   cheap and the data plainly exists.

Whichever is chosen, the "4 hours" label is inherently a lie for the second bar of every day; any
UI or backtest that assumes uniform bar duration at this timeframe needs to know that.

## `_resample_weekly` — is it generalizable to intraday?

Read directly: `backend/app/market/store.py:461-531`. **It is weekly-specific, not a generic
resampler.** It:

- Groups by `(iso_year, iso_week)` via `pandas.Timestamp.dt.isocalendar()` — a calendar construct
  that has no intraday equivalent (there is no "ISO 4-hour-of-day").
- Decides "still forming" by comparing the last daily bar's ISO week to *today's* ISO week — a
  once-a-week-granularity check that would need to become a session-and-clock-time check for any
  intraday bucket (exactly the logic `_last_bar_unsettled` in `yahoo.py` already carries for
  1h/5m, which `_resample_weekly` does not reuse or share).
- Operates on **daily** input specifically (`read_frame(symbol, Interval.DAY, ...)` is hardcoded at
  every call site) — it was never handed intraday bars and does not know about session opens/closes
  within a day.

The *shape* of the technique (derive a bucket key, `groupby().agg(first/max/min/last/sum)`, drop
the still-forming trailing group) is reusable as a pattern, but the concrete function would need a
new bucketing key (session-relative time bucket, not ISO week) and a new "still forming" rule
(session-and-clock-aware, not calendar-week-aware) to serve 4h. It is not a drop-in.

## What's already in the store (live read via duckdb, since pandas' parquet engine is missing)

`interval=1h/`: **AMZN, DRAM, NVDA, QQQ, SOXL** — no SPY.

| Symbol | Rows | First | Last | fetched_at |
|---|---|---|---|---|
| AMZN | 3,548 | 2024-08-13 06:30 (America/Los_Angeles display, i.e. session-local) | 2026-08-24 12:30 | 2026-08-25T05:30:50Z |
| DRAM | 693 | 2026-04-02 06:30 | 2026-08-24 12:30 | 2026-08-25T05:30:51Z |
| NVDA | 3,555 | 2024-08-12 06:30 | 2026-08-24 12:30 | 2026-08-25T05:30:52Z |
| QQQ | 3,548 | 2024-08-13 06:30 | 2026-08-24 12:30 | 2026-08-25T05:30:52Z |
| SOXL | 3,555 | 2024-08-12 06:30 | 2026-08-24 12:30 | 2026-08-25T05:30:53Z |

`interval=5m/`: **AMZN, DRAM, NVDA, QQQ, SOXL, SOXX** — no SPY.

| Symbol | Rows | First | Last | fetched_at |
|---|---|---|---|---|
| AMZN | 3,822 | 2026-06-15 06:30 | 2026-08-24 12:55 | 2026-08-25T05:30:54Z |
| DRAM | 3,822 | 2026-06-15 06:30 | 2026-08-24 12:55 | 2026-08-25T05:30:54Z |
| NVDA | 3,822 | 2026-06-15 06:30 | 2026-08-24 12:55 | 2026-08-25T05:30:55Z |
| QQQ | 3,822 | 2026-06-15 06:30 | 2026-08-24 12:55 | 2026-08-25T05:30:56Z |
| SOXL | 3,822 | 2026-06-15 06:30 | 2026-08-24 12:55 | 2026-08-25T05:30:57Z |
| SOXX | 3,822 | 2026-06-15 06:30 | 2026-08-24 12:55 | 2026-08-25T05:30:57Z |

Two things worth flagging: (1) **all six 5m-store symbols span 2026-06-15 → 2026-08-24, which is
~70 days — longer than the 60-day single-request cap.** This is only possible because the store
accumulates incrementally across repeated daily syncs (each sync appends the newest day and keeps
what's already on disk); a single backfill call could never produce this in one shot. (2) the 1h
store for AMZN/NVDA/QQQ/SOXL already spans ~742 days (2024-08-12/13 → 2026-08-24), *past* the
730-day live-fetch ceiling, for the same reason — accumulated history outlives what a fresh request
window can re-fetch. **SPY has no intraday history in the store at all** — every SPY number in this
document came from the live probe, not from what's already synced.

## Stooq — confirmed broken, live, today

One quick live check, no dwelling: `GET https://stooq.com/q/d/l/?s=spy.us&i=d` → HTTP 404, body
`"The page you requested does not exist or has been moved"`. `GET https://stooq.com/` (the site's
own homepage) → also HTTP 404. Same address-level block the `stooq.py` docstring documented on
2026-08-24; unchanged one day later. Confirms `stooq.py` as dead weight for this plan; do not
budget it as a data source.

## Rate limiting

None observed. 34 sequential probe requests (Part 1 + 2, ~0.3–0.9s apart with a deliberate 0.4s
sleep between calls) all returned HTTP 200 or a clean 422, never 429. A follow-up burst of 20
requests with **no delay at all** — total wall time 0.6 seconds for all 20 — also came back 100%
HTTP 200, response times settling to ~0.02s each after the first. At this volume (54 requests total
across ~2 minutes, including a 20-request burst with zero backoff) Yahoo's chart endpoint showed no
throttling. This does not prove it never throttles — `yahoo.py` already has `RateLimited` handling
for HTTP 429 with `Retry-After`, so the possibility is clearly anticipated — it only proves the
threshold is well above what a normal single-session backfill would generate.

## Verdicts for a rule-accuracy study (20-bar horizon)

- **5m: 60 days of history, ~78 bars/session (6.5h × 60/5).** A single fetch gives roughly
  60 × 78 ≈ 4,700 bars, but non-overlapping 20-bar windows cannot cross a session boundary without
  contaminating the horizon with an overnight gap, so the usable count is closer to 3 clean windows
  per session × 60 days ≈ **~180 independent observations**. Thin for a rule that wants to
  distinguish a real edge from noise, and entirely dependent on which 60 days happen to be in
  scope — there is no way to get an out-of-sample 5m holdout period without waiting for it to
  accrue in the store day by day.
- **15m: same 60-day cap, ~26 bars/session.** ~60 × 26 ≈ 1,560 bars, ~1 clean 20-bar window per
  session ≈ **~60 independent observations**. Too thin on its own for a standalone rule-accuracy
  claim; would need to accumulate store history over months to become useful.
- **1h: 730-day live cap (already exceeded in-store to ~742 days for 4 of 5 synced symbols),
  ~6.5 bars/session.** ~504 sessions × 6.5 ≈ 3,300 bars, giving **~160 independent 20-bar windows**
  over two years. Workable for a first-pass study, marginal for anything wanting multiple market
  regimes.
- **4h: same 730-day cap, 2 bars/session (1 full + 1 short).** ~504 × 2 ≈ 1,000 bars (matches the
  1,003 observed), so a 20-bar horizon is ~10 trading days (2 calendar weeks) and yields only
  **~50 independent windows** in the entire available history. This is the weakest interval of the
  four for a rule-accuracy study — not enough independent observations to separate a real 4h edge
  from sampling noise, regardless of which side of the resample-vs-native decision is taken.
- **1d: unbounded, 8,450 bars for SPY back to 1993.** 20 bars ≈ 1 trading month, giving
  **~420 independent observations** spanning multiple decades and several distinct market regimes.
  By far the strongest interval for statistical power; the only one with enough history to support
  genuine out-of-sample splits.

**Bottom line for planning: daily is the only interval with enough independent observations to
trust a 20-bar rule-accuracy result on its own. 1h is workable but thin. 4h is the weak link of the
four target intervals — its 730-day ceiling caps it at roughly 50 non-overlapping windows no
matter what data-sourcing choice is made, because that ceiling is Yahoo's, not a resampling
artifact.**

## What I could not verify

- **Whether Yahoo enforces the 60-day / 730-day windows identically for every symbol**, or whether
  thinly-traded / recently-listed tickers get a shorter effective window. Only SPY and AMD were
  probed, both large, long-listed names.
- **The precise boundary edge** (yahoo.py's comment claims exactly 730 days fails and 729 passes).
  The probe only tested `range=2y` (succeeded) vs `range=5y` (failed) — coarse range tokens, not
  day-exact `period1`/`period2` values — so the exact day the cutoff flips was not pinned down here.
  The 60-day/730-day *figures themselves* are confirmed verbatim from Yahoo's own error text; the
  *exact off-by-one* (729 vs 730) is not independently re-verified in this pass.
- **Whether Yahoo's rate limiting exists at all, and if so at what volume.** 54 requests over ~2
  minutes never tripped it. That is not proof it doesn't exist — `yahoo.py` has `RateLimited`
  handling ready — just that this session's probe volume was too low to find the ceiling.
- **Whether 15m/30m/4h bars would pass `_assert_granularity` and the rest of the fetch pipeline
  cleanly if wired up** — the live HTTP responses look structurally identical to 5m/1h/1d (same
  `meta`, `timestamp`, `indicators.quote` shape), but this was not run through
  `YahooProvider.fetch_bars` itself (that would require code changes, out of scope for this
  probe-only task) — only through a standalone script hitting the same URL.
- **Whether the 4h "short second bar" pattern holds for non-US-exchange symbols or half-days**
  (early close days, e.g. day after Thanksgiving) — only 5 ordinary trading days for one US symbol
  were inspected at bar-level granularity.
- **Whether `1wk`'s native token differs in any way from the app's own `_resample_weekly`** output
  (e.g. week start day, DST edge handling) — both were read (Yahoo's native `1wk` bars via probe,
  the app's resampled output via source reading) but never diffed against each other row-by-row.
