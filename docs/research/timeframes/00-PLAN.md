# Multi-timeframe rule research — findings and plan

Research conducted 2026-08-25 across five parallel investigations. This document
integrates them and proposes the build. The numbered documents beside it hold the
detail and the raw evidence.

| doc | subject |
|---|---|
| [01](01-data-feasibility.md) | What candle intervals are actually obtainable (live-probed) |
| [02](02-daily-assumption-change-map.md) | Where the daily-bar assumption is baked in |
| [03](03-indicator-rule-behavior-intraday.md) | What real indicators/rules do on real intraday bars |
| [04](04-accuracy-methodology.md) | How "rule accuracy" must be measured to mean anything |
| [05](05-feature-surface-design.md) | Where the feature lives and its API contract |

---

## The headline

**The engine already runs on intraday bars, unmodified.** 46 of 46 rule x interval
combinations executed clean — `evaluate()`, `compute_evidence()` and `rule_state()`
all work on stored 5m and 1h bars today with zero code changes (doc 03).

So the premise "the strategy is executing on the day candle" is true only as a
matter of *configuration*, not capability. Roughly ten modules pass
`interval=Interval.DAY` as a hardcoded literal. Nothing forces them to.

**The barrier to this research is semantic and statistical, not engineering.**

---

## What the same rule means at different intervals

Measured firing rates, QQQ, fires per calendar day (doc 03):

| rule | 5m | 1h | 1d | 5m:1d |
|---|---:|---:|---:|---:|
| `bb_squeeze` | 77.2 | 5.45 | 0.110 | 700x |
| `price_above_sma200` | 34.8 | 4.44 | 0.710 | 49x |
| `atr_range_expansion` | 6.94 | 0.77 | 0.067 | 104x |
| `bb_lower_touch` | 5.45 | 0.42 | 0.050 | 109x |
| `rsi_oversold` | 4.67 | 0.34 | 0.016 | 292x |
| `macd_bullish_flip` | 3.14 | 0.25 | 0.040 | 79x |
| `ema_golden_cross` | 0.163 | 0.016 | 0.002 | 82x |

`sma(200)` on 5m bars spans about two and a half sessions, not 200 days. It is a
different indicator wearing the same name. **Making cross-interval comparison
honest is the central design problem of this feature** — making it *possible* is
already done.

---

## Data: all six intervals are available

Live-probed against Yahoo's chart endpoint, not inferred from code (doc 01, plus a
direct manager re-probe that settled a disagreement between two investigations):

| interval | native at Yahoo | max history | bars/session | in `Interval` enum |
|---|---|---|---:|---|
| 5m | yes | exactly 60 days | 78 | yes |
| 15m | **yes** | exactly 60 days | 26 | **no — must add** |
| 30m | yes | exactly 60 days | 13 | no |
| 1h | yes | ~730 days | 7 | yes |
| 4h | **yes** | ~730 days | 2 | **no — must add** |
| 1d | yes | full (SPY to 1993-01-29) | 1 | yes |
| 1w | yes | full | — | yes (resampled from daily locally) |

The app's `supported_intervals = {5m, 1h, 1d}` in `yahoo.py` is a **self-imposed
restriction, not an upstream limit**.

### Two corrections worth recording

Two of the five investigations independently concluded that `4h` has no native
Yahoo interval and must be resampled from `1h`. Both inferred it from the codebase.
A direct live probe disproved it: Yahoo returns `dataGranularity: '4h'` and serves
1,003 SPY bars over two years. **Reasoning from code about an external API's
capabilities produced a wrong answer twice in one day** — probe the endpoint.

Yahoo also returns no `validRanges` interval list; it never rejected any of the
eight tokens tested. The only rejection shape is a 422 on an over-wide window.

### 4h is the weakest interval on every axis

A 4h session splits into one true 4h bar (09:30 ET) and one 2.5h remainder
(13:30 ET), so **bar durations alternate** and indicators will treat them as
homogeneous. Combined with the 730-day ceiling and only 2 bars/session, 4h yields
~73 independent 20-bar windows per symbol against daily's ~250. Include it, but the
UI should mark it as lower-confidence.

### Intraday history is perishable

5m history is a rolling 60-day window. The store already holds ~70 days of 5m data
for some symbols — more than any single fetch can return — which is only possible
through incremental accumulation. **Every day without collection permanently loses
a day of 5m history.** This is the one item with a deadline. SPY currently has no
intraday data stored at all (only AMZN, DRAM, NVDA, QQQ, SOXL, SOXX).

---

## Measurement: lift, not hit rate

`hit_rate = P(forward return over H bars > 0 | rule fired)` is the natural metric
and is what `evidence.py` already computes. **It must never be the headline
number.** In a bull window a zero-skill rule's hit rate tracks market drift and
looks excellent.

    base_rate = the same measurement over every evaluable bar in the identical sample
    lift      = hit_rate - base_rate        <- the number to display

A zero-skill rule has lift ~0 in every regime. This is the direct antidote to the
failure mode where a verdict reversed when the window mix changed.

Supporting requirements (doc 04): rising-edge de-duplication so 400 consecutive
firing bars are not 400 observations; a non-overlap scan for effective sample size;
Benjamini-Hochberg FDR across the cell grid; explicit regime conditioning; and cost
adjustment so a 52%-hit-rate 5m rule is never shown as profitable.

**Horizons: compute bar-native, compare in calendar time.** The bar-native
arithmetic in `evidence.py`/`forward.py` is already lookahead-proven — reuse it,
don't reimplement. But default the *view* to calendar buckets ("~1 day", "~1 week"),
with the raw bars-native table as a secondary, explicitly-labelled
"same-interval-only" view.

### The sample gate makes rare rules unmeasurable per-symbol

Gate: `n_independent >= 20`, sitting between the codebase's existing `WEAK`=8 and
`SUGGESTIVE`=30 grades so a bare percentage never contradicts a grade the same data
already carries.

Cross-checking that gate against the measured firing rates above (estimated
episodes = rate x available days):

| rule | 5m | 1h | 1d |
|---|---:|---:|---:|
| `bb_squeeze` | 4632 | 3978 | 550 |
| `price_above_sma200` | 2088 | 3241 | 3550 |
| `atr_range_expansion` | 416 | 562 | 335 |
| `rsi_oversold` | 280 | 248 | 80 |
| `macd_bullish_flip` | 188 | 182 | 200 |
| **`ema_golden_cross`** | **10 X** | **12 X** | **10 X** |

`ema_golden_cross` fails the gate at *every* interval on a single symbol. Rare
rules are unmeasurable per-symbol regardless of history depth. **Cross-symbol
pooling is therefore a correctness requirement, not an enhancement.**

---

## Known distortions to disclose in the UI

1. **Rolling windows cross the overnight gap.** Verified: a 20-bar SMA on the
   Monday 2026-08-24 09:30 ET bar blends in 19 Friday-afternoon closes; library
   `sma(20)` matched the manual cross-gap mean exactly (712.9930 both ways). Gaps
   are missing rows, not NaN placeholders, so nothing flags the discontinuity.
   Acceptable for "recent price action" indicators, wrong for anything representing
   session structure. No session-aware rolling mechanism exists except VWAP's
   opt-in anchor.
2. **4h bars alternate in duration** (above).
3. **5m/15m cover one regime only** — 60 days.
4. **Annualized metrics are meaningless at intraday scale.** `metrics.py`'s
   one-year floor already returns `None` for 5m under 60-day retention. Do not
   display annualized figures intraday; this is a feature, not a gap to fill.

---

## A latent bug found on the way

`Interval.backtestable` **is not a gate** — no application code calls it; it is
asserted only by a self-referential unit test (`tests/test_stores.py:643-655`).
The actual enforcement is an accidental `KeyError` from
`BARS_PER_YEAR[interval]` (`backtest/strategy.py`), and that path is untested at
non-daily intervals and **reachable today through the public API**, since
`interval: Interval` request fields are not restricted to backtestable values.

Passing `interval=5m` to the existing backtest endpoint should 422. It currently
raises a `KeyError`. Worth fixing regardless of whether this feature is built.

---

## The plan

The smallest viable path **bypasses the annualization stack entirely**:
`evaluate()` then `compute_evidence()` directly on stored bars, never touching
`backtest.strategy`, `backtest.metrics`, or `BARS_PER_YEAR`. That keeps this
feature off the live paperdesk/tournament code paths, so working daily behaviour
cannot regress.

### Phase A — foundation (parallelizable; independent of every open decision)

- **A1** Add `FIFTEEN_MIN`/`FOUR_HOUR` to `Interval`; widen Yahoo
  `supported_intervals`; wire `INTERVAL_MAX_LOOKBACK` and cache TTLs.
- **A2** Intraday backfill for the research universe, and a recurring collector.
  *Time-sensitive — 5m history is lost daily.*
- **A3** Fix the `BARS_PER_YEAR` KeyError to a 422 at the API boundary.

### Phase B — research engine

- **B1** `timeframes` service: per `(symbol, interval)`, evaluate all rules, dedup
  to rising edges, compute hit/base/lift, CIs, FDR, cost adjustment, gate.
- **B2** `GET /api/timeframes/{intervals,matrix,signal}`.
- **B3** Sweep job + cache. Unit of work is one `(symbol, interval)` pair — all
  rules and horizons share caches — so a full sweep is ~120 calls, not ~11,520;
  roughly 36s-4min warm. Job pattern needed for full sweeps; single-cell
  drill-downs stay synchronous.

### Phase C — UI

- **C1** New top-level page in the "Strategy Lab" nav section. Costs exactly two
  files (`App.tsx` route, `nav.ts` item) and touches no existing page — so the
  deferred "should this join the Rules tab?" question stays genuinely open.
- **C2** Rule x interval matrix; insufficient-sample cells render distinctly from
  numbers, never as a bare percentage.
- **C3** Drill-down: candles + indicator overlays + firing markers.
  `Chart.tsx` already renders server-supplied `IndicatorSeries[]` on the price pane
  at any interval with **zero changes**. The only gap is markers — `setMarkers` is
  never called in the frontend today; needs one optional `markers` prop and one
  call reusing the existing `toTime()` helper.

### Phase D — the actual research

Run the sweep and write up how each rule behaves per interval and per sector. This
is the question that started all of this; Phases A-C exist to make its answer
trustworthy.

---

## Open decisions

1. **Universe and depth** for the first sweep — a handful of liquid names, or the
   full discovery universe? Drives A2's backfill size and D's statistical power.
2. **Does 30m earn a slot?** It is native and free, and sits between 15m and 1h.
3. **Placement** stays deferred by design until C1 is on screen and judgeable.
