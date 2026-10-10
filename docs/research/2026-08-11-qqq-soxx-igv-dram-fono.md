# QQQ, SOXX, IGV — pre-registered thesis study, plus DRAM and FONO refusals

Run 2026-08-11. Backend commit at run time: see `git rev-parse HEAD` in the repo; not pinned here
because this study makes no source changes. All numbers below came from executing the scripts in
`docs/research/scripts/`, which are kept alongside this report. Raw JSON output is in
`docs/research/data/`.

**Isolation.** Every `app.thesis.loop.run` call in this study used `Settings(store_dir=<fresh temp
directory>)`, one per ticker, with bars supplied directly (`bars=frame`) so the loop never touched
`app.market.store` under that settings object either. The production thesis ledger
(`data/store/thesis.sqlite`) was checked after the run: it contains exactly one symbol, `SOXL`, dated
`2026-08-11 05:43:58` — hours before this session started and consistent with Phase 9's own prior
work, not this study. **No production holdout was read, claimed, or burned by this study.** The five
temporary stores this study created (`%TEMP%\thesis_isolated_<SYMBOL>_*`) are disposable and can be
deleted; they are not part of the deliverable.

**What "the app's market-data functions" means here.** Bars for QQQ, SOXX, IGV and DRAM were read
(and, where stale, synced) via `app.market.store.ensure_series` against the production
`data/store/bars` cache — the same call the UI's chart endpoint makes, and explicitly permitted as
"the app working normally." No brokerage CSV and no `data/store/ledger.sqlite` was opened at any
point in this study.

## Coverage confirmed

```
QQQ:  6897 bars, 1999-03-10 -> 2026-08-10
SOXX: 6305 bars, 2001-07-13 -> 2026-08-10
IGV:  6303 bars, 2001-07-17 -> 2026-08-10
DRAM: 89 bars,   2026-04-02 -> 2026-08-10
FONO: EXCEPTION SymbolNotFoundWithContext: yahoo has no chart data for 'FONO'
```
(`docs/research/scripts/01_fetch_bars.py`)

## Correlation warning, stated once rather than three times

QQQ and IGV are not independent trials: IGV is a software-sector slice of the same large-cap growth
complex QQQ tracks, and both carry heavy overlap in mega-cap tech constituents. SOXX and DRAM overlap
by theme (semiconductors and semiconductor memory) though not by holdings. A rule that "works" (or
fails) on QQQ and again on IGV is not two confirmations — it is one macro-tech regime expressing
itself twice. None of the verdicts below need this caveat to change (nothing survived on any of the
three full-history tickers), but a reader should not read "tested on four instruments" as four
independent looks at the market.

---

## What was tested (all three tickers, identically)

**Primary instrument: `app.thesis.loop.run`.** Pre-registered catalogue from `app.thesis.author`,
five templates apply to a non-leveraged instrument (the sixth, `decay_avoidance`, is
`leveraged_only=True` and none of QQQ/SOXX/IGV/DRAM are in `app.thesis.instruments.REGISTRY`):

| key | entry | exit | horizon | direction | max holding | stop |
|---|---|---|---|---|---|---|
| `band_reversion` | `close < bb_lower(20,2)` | `close > sma(20)` | 20 | up | 40 | — |
| `trend_following` | `ema(50) crosses_above ema(200)` | `ema(50) crosses_below ema(200)` | 60 | up | — | — |
| `momentum_persistence` | `close > sma(200)` | `close < sma(200)` | 20 | up | — | — |
| `oversold_bounce` | `rsi(14) < 30` | `rsi(14) > 50` | 5 | up | 10 | 15% |
| `volatility_contraction` | `bb_upper(20,2) - bb_lower(20,2) < close * 0.04` | — | 20 | up | 20 | — |

Declared budget: `DEFAULT_ITERATION_BUDGET = 12`. Every run used exactly 5 of 12 iterations and
stopped on `CATALOGUE_EXHAUSTED` — the author had 5 applicable ideas, not 12, and the loop reports
that distinction rather than implying it searched harder than it did.

**Supplementary, exploratory instrument: `app.backtest.scan.scan` + `app.backtest.events.event_study`
+ `app.backtest.guards.check`**, run directly (not through `build_scan`, so no run card was written
and no store was touched beyond the already-cached bars) across the same 5 entry expressions at all
five `STUDY_HORIZONS = (1, 5, 10, 20, 60)` — 25 trials per ticker, Benjamini–Hochberg corrected across
that whole 25-trial family, on the **full available history** (no holdout split — this scan never
touches the thesis ledger or spends any ticker's one out-of-sample look). This is what answers "what
did each horizon show," which the pre-registered loop cannot: each template pre-declares exactly one
horizon, and testing a rule at every horizon and reading off the best one is itself the kind of
search the whole package exists to guard against. Treat this table as descriptive, not confirmatory —
it is a second, separately-corrected trial family, run only to satisfy "report what each horizon
showed."

**Strategy mechanics: `app.backtest.strategy.backtest`**, run for all 5 templates per ticker over the
full history, at the default non-zero `Costs()` (5 bps slippage each way, $0 commission, $10,000
notional), always paired with `buy_hold` on the identical window.

---

## QQQ

### Pre-registered loop verdict

Outcome: **`catalogue_exhausted`**, 5/12 iterations. Holdout split date `2019-09-26` (the trailing 25%
of 6,897 sessions); **holdout status remained `unused`, 0 attempts** — nothing cleared the in-sample
screen well enough to spend it.

| template | horizon | hit | baseline | edge | n (raw) | n (indep) | p | q | verdict |
|---|---|---|---|---|---|---|---|---|---|
| band_reversion | 20 | 0.642 | 0.604 | +0.038 | 257 | 87 | 0.511 | 0.511 | inconclusive |
| trend_following | 60 | 0.833 | 0.650 | +0.184 | 12 | **10** | 0.510 | 0.511 | inconclusive (n<30) |
| momentum_persistence | 20 | 0.617 | 0.601 | +0.016 | 3484 | 194 | 0.660 | 0.660 | inconclusive |
| oversold_bounce | 5 | 0.605 | 0.555 | +0.049 | 86 | 42 | 0.644 | 0.660 | inconclusive |
| volatility_contraction | 20 | 0.670 | 0.604 | +0.066 | 627 | 67 | 0.318 | 0.660 | inconclusive |

Every q-value is far above the 0.10 screening threshold; `trend_following`'s independent count (10)
is also under the 30-observation power floor on its own. **Zero survivors, holdout never spent.**

### Exploratory horizon scan (full history, 25 trials, separate BH family)

Zero of 25 discoveries (`q <= 0.10`) at any horizon for any rule. Full table in
`docs/research/data/horizon_scan_results.json`; headline rows:

| rule | h=1 edge/q | h=5 edge/q | h=10 edge/q | h=20 edge/q | h=60 edge/q |
|---|---|---|---|---|---|
| band_reversion | −0.010 / 0.90 | +0.044 / 0.83 | −0.029 / 0.83 | +0.043 / 0.83 | +0.031 / 0.90 |
| trend_following | +0.118 / 0.83 | −0.134 / 0.83 | +0.129 / 0.83 | +0.026 / 1.00 | +0.189 / 0.83 |
| momentum_persistence | untestable — see bug note below | +0.016 / 0.83 | +0.013 / 0.83 | +0.022 / 0.83 | +0.031 / 0.90 |
| oversold_bounce | +0.068 / 0.83 | +0.074 / 0.83 | +0.005 / 1.00 | −0.035 / 0.90 | −0.047 / 0.90 |
| volatility_contraction | −0.024 / 0.83 | +0.015 / 0.90 | −0.030 / 0.83 | +0.040 / 0.83 | +0.129 / 0.83 |

`momentum_persistence` at horizon 1 (n_indep = 4,896) could not be computed — see "Application bug
found" below. Its trial slot was retained (m = 25 throughout, not shrunk).

### Entry/exit mechanics and strategy backtest, all 5 templates, vs buy-and-hold, with costs

Full history, `Costs(slippage_bps=5.0, commission_per_trade=0.0, notional=10000.0)`, closed trades
only for win/loss counts (open-at-end excluded, per the engine's own convention):

| template | total return | CAGR | Sharpe | max DD | trades (closed) | win rate | cost drag |
|---|---|---|---|---|---|---|---|
| band_reversion | 1.208 | 2.9% | 0.253 | −0.569 | 118 | 74.6% | −0.277 |
| trend_following | 13.371 | 10.2% | 0.679 | −0.303 | 13 | 61.5% | −0.195 |
| momentum_persistence | 6.951 | 7.9% | 0.536 | −0.543 | 86 | 26.7% | −0.718 |
| oversold_bounce | 0.876 | 2.3% | 0.257 | −0.290 | 43 | 72.1% | −0.080 |
| volatility_contraction | 0.475 | 1.4% | 0.223 | −0.252 | 82 | 62.2% | −0.126 |
| **buy & hold (same window)** | **13.014** | **10.1%** | **0.493** | **−0.830** | — | — | — |

Every one of the five rule-driven strategies **trails buy-and-hold on total return over this full
1999–2026 window.** `trend_following` is the closest: it slightly beats buy-and-hold's raw total
return (13.37 vs 13.01) and its Sharpe (0.68 vs 0.49) by spending only 72% of the time in the market
(`exposure=0.720`) and confining the max drawdown to −30% against buy-and-hold's −83%. That drawdown
reduction is what the template's own `falsifies_if` text is actually about, and descriptively it
holds here — but see "Application-level observation" below: the pre-registered loop never tested that
claim directly; it tested hit-rate-above-baseline at a 60-bar horizon instead, and that test came back
`inconclusive` on 10 independent observations. `momentum_persistence`'s 26.7% win rate looks alarming
in isolation — it is a trend-following exit (`close < sma(200)`), so most trades are cut by a small
loss on a whipsaw and profit comes from a few large trend trades (best trade +77.5%); its win rate
below 50% is the expected shape of that kind of rule, not itself evidence against it, but it does mean
the strategy paid −71.8 percentage points of total return in cost drag on 86 closed trades — by far
the largest of the five.

**Mechanics detail for `oversold_bounce`, the template with the most exit machinery**: entry fires
when `rsi(14) < 30` at bar *t*'s close; the fill is bar *t+1*'s open, 5bps worse (long entry pays the
slippage). Every bar the position is open, a 15% stop is checked first against that bar's `low` (and
`open`, for a gap through the stop); if neither triggers, a 10-bar holding cap is checked next; only
if neither of those fires is the `rsi(14) > 50` exit signal consulted, and that exit also fills one
bar later than its signal (next bar's open). Of QQQ's 43 closed trades: 13 exited on the RSI signal,
27 hit the 10-bar cap, 3 hit the 15% stop, none were still open at series end.

### Buy-and-hold drawdown profile (descriptive, no baseline needed — `app.backtest.drawdown.profile`)

Top episode: 2000-03-27 peak to 2002-10-09 trough, **−83.0%**, 636 bars to trough, recovered
2016-09-06 (14.4 years underwater). Currently −11.3% below the 2026-06-02 peak, 47 bars underwater.
Four other episodes exceed −20% (2021-22 growth selloff −35.6%, COVID −28.6%, Q4 2018 −23.2%,
early-2025 −22.9%).

---

## SOXX

### Pre-registered loop verdict

Outcome: **`catalogue_exhausted`**, 5/12 iterations. Holdout split `2020-04-29`; **status `unused`, 0
attempts.**

| template | horizon | hit | baseline | edge | n (raw) | n (indep) | p | q | verdict |
|---|---|---|---|---|---|---|---|---|---|
| band_reversion | 20 | 0.600 | 0.572 | +0.028 | 245 | 83 | 0.658 | 0.658 | inconclusive |
| trend_following | 60 | 0.545 | 0.641 | −0.095 | 11 | **11** | 0.539 | 0.658 | inconclusive (n<30) |
| momentum_persistence | 20 | 0.595 | 0.577 | +0.019 | 2917 | 165 | 0.694 | 0.694 | inconclusive |
| oversold_bounce | 5 | 0.655 | 0.539 | +0.117 | 119 | 50 | 0.090 | 0.360 | inconclusive |
| volatility_contraction | 20 | 0.705 | 0.572 | +0.133 | 149 | **28** | 0.180 | 0.451 | inconclusive (n<30) |

`oversold_bounce` had the smallest raw p (0.090, would clear a naive 0.10) but its BH-corrected q
against SOXX's own 5-trial ledger is 0.360 — nowhere close to the 0.10 screening bar. This is exactly
the multiple-testing correction the package exists to apply: **the raw p alone would have been
misleading.** Zero survivors, holdout never spent.

### Exploratory horizon scan (25 trials)

Zero discoveries. `oversold_bounce` at h=1 has the smallest raw p in the whole 25-trial family
(0.0073, n_indep=126) but its scan-family q is 0.182 — still above 0.10.

| rule | h=1 edge/q | h=5 edge/q | h=10 edge/q | h=20 edge/q | h=60 edge/q |
|---|---|---|---|---|---|
| band_reversion | +0.013 / 1.00 | +0.010 / 1.00 | −0.028 / 1.00 | +0.031 / 1.00 | +0.012 / 1.00 |
| trend_following | −0.220 / 0.95 | −0.121 / 1.00 | −0.134 / 1.00 | −0.018 / 1.00 | −0.085 / 1.00 |
| momentum_persistence | untestable — bug | +0.004 / 1.00 | +0.017 / 1.00 | +0.025 / 1.00 | +0.029 / 1.00 |
| oversold_bounce | +0.123 / **0.182** | +0.120 / 0.95 | +0.004 / 1.00 | −0.006 / 1.00 | −0.029 / 1.00 |
| volatility_contraction | +0.054 / 0.99 | +0.025 / 1.00 | −0.002 / 1.00 | +0.129 / 1.00 | +0.176 / 0.99 |

### Entry/exit mechanics and strategy backtest vs buy-and-hold

| template | total return | CAGR | Sharpe | max DD | trades (closed) | win rate | cost drag |
|---|---|---|---|---|---|---|---|
| band_reversion | 2.478 | 5.1% | 0.355 | −0.577 | 110 | 68.2% | −0.404 |
| trend_following | 16.293 | 12.1% | 0.607 | −0.343 | 13 | 69.2% | −0.235 |
| momentum_persistence | 15.909 | 12.0% | 0.627 | −0.406 | 90 | 22.2% | **−1.602** |
| oversold_bounce | −0.027 | −0.1% | 0.060 | −0.331 | 41 | 48.8% | −0.040 |
| volatility_contraction | 0.455 | 1.5% | 0.255 | −0.255 | 30 | 73.3% | −0.044 |
| **buy & hold (same window)** | **21.259** | **13.2%** | **0.537** | **−0.705** | — | — | — |

All five trail buy-and-hold. `oversold_bounce` on SOXX is a net loser gross of anything else (total
return −2.7%, essentially flat/negative CAGR) over 4,129 evaluable bars — the RSI-oversold-bounce
prior does not survive on this instrument's history at these mechanics. `momentum_persistence`'s cost
drag alone (−160 percentage points across 90 trades) exceeds its entire total return; this is a
high-turnover trend filter and its edge, such as it is, is materially eaten by 5bps-each-way slippage.

### Buy-and-hold drawdown profile

Top episode: 2001-08-02 to 2008-11-20, **−70.5%**, 1,836 bars to trough, recovered 2014-03-20 (12.6
years underwater). **Currently in an unrecovered episode**: peak 2026-06-22, trough so far 2026-07-29
at −29.0%, 34 bars underwater as of the last stored session (2026-08-10) — this is a live, open
drawdown, not a closed historical one.

---

## IGV

### Pre-registered loop verdict

Outcome: **`catalogue_exhausted`**, 5/12 iterations. Holdout split `2020-04-30`; **status `unused`, 0
attempts.**

| template | horizon | hit | baseline | edge | n (raw) | n (indep) | p | q | verdict |
|---|---|---|---|---|---|---|---|---|---|
| band_reversion | 20 | 0.584 | 0.608 | −0.023 | 231 | 77 | 0.727 | 0.727 | **rejected** |
| trend_following | 60 | 0.846 | 0.701 | +0.145 | 13 | **11** | 0.524 | 0.727 | inconclusive (n<30) |
| momentum_persistence | 20 | 0.604 | 0.613 | −0.009 | 3437 | 192 | 0.824 | 0.824 | **rejected** |
| oversold_bounce | 5 | 0.549 | 0.557 | −0.008 | 102 | 40 | 1.000 | 1.000 | **rejected** |
| volatility_contraction | 20 | 0.581 | 0.608 | −0.027 | 456 | 51 | 0.776 | 1.000 | **rejected** |

IGV is the one ticker of the three where the measured edge ran **opposite the pre-registered
direction** on four of five templates — the loop's direction check (not just magnitude) marks those
`rejected` rather than `inconclusive`, correctly distinguishing "the effect pointed the wrong way"
from "there wasn't enough data to tell." Zero survivors, holdout never spent.

### Exploratory horizon scan (25 trials)

Zero discoveries.

| rule | h=1 edge/q | h=5 edge/q | h=10 edge/q | h=20 edge/q | h=60 edge/q |
|---|---|---|---|---|---|
| band_reversion | +0.018 / 1.00 | +0.015 / 1.00 | −0.067 / 1.00 | +0.002 / 1.00 | −0.034 / 1.00 |
| trend_following | −0.085 / 1.00 | +0.005 / 1.00 | +0.113 / 1.00 | +0.016 / 1.00 | +0.187 / 1.00 |
| momentum_persistence | untestable — bug | −0.003 / 1.00 | −0.005 / 1.00 | +0.0003 / 1.00 | −0.009 / 1.00 |
| oversold_bounce | −0.027 / 1.00 | +0.025 / 1.00 | −0.106 / 1.00 | −0.105 / 1.00 | +0.022 / 1.00 |
| volatility_contraction | +0.011 / 1.00 | +0.030 / 1.00 | +0.024 / 1.00 | −0.032 / 1.00 | −0.020 / 1.00 |

Every single q-value in IGV's 25-trial family is exactly 1.0 or effectively so — the flattest, most
unambiguously null result of the three tickers at every horizon tested.

### Entry/exit mechanics and strategy backtest vs buy-and-hold

| template | total return | CAGR | Sharpe | max DD | trades (closed) | win rate | cost drag |
|---|---|---|---|---|---|---|---|
| band_reversion | 1.071 | 3.0% | 0.257 | −0.469 | 107 | 67.3% | −0.234 |
| trend_following | 4.366 | 6.9% | 0.457 | −0.417 | 16 | 50.0% | −0.087 |
| momentum_persistence | 3.518 | 6.2% | 0.441 | −0.320 | 97 | 27.8% | −0.463 |
| oversold_bounce | −0.212 | −0.9% | −0.016 | −0.537 | 43 | 58.1% | −0.033 |
| volatility_contraction | 0.260 | 0.9% | 0.162 | −0.232 | 55 | 60.0% | −0.071 |
| **buy & hold (same window)** | **9.775** | **10.0%** | **0.491** | **−0.615** | — | — | — |

All five trail buy-and-hold, and by a wider relative margin than on QQQ or SOXX — even
`trend_following`, the strongest performer on the other two tickers, reaches only 4.37x total return
against buy-and-hold's 9.77x here, despite a shallower max drawdown (−41.7% vs −61.5%).
`oversold_bounce` is a net loser in absolute terms (total return −21.2%) with a negative Sharpe.

### Buy-and-hold drawdown profile

Top episode: 2001-07-17 to 2002-10-07, **−62.2%**, 305 bars to trough, recovered 2007-10-04 (6.2
years underwater). **Currently in an unrecovered episode**: peak 2025-09-22, trough so far
2026-04-10 at **−36.6%**, 221 bars underwater as of 2026-08-10 and not yet recovered — the deepest of
the three tickers' currently-open drawdowns by a wide margin.

---

## DRAM — refusal, verbatim

```
DRAM: 89 bars, 2026-04-02 -> 2026-08-10
```

`app.thesis.loop.run("DRAM", ...)` against an isolated store (never touching production state):

```
DRAM: outcome=holdout_unavailable  iterations_used=0/12
DRAM: WARNING [holdout_unavailable] DRAM: 89 sessions leaves 23 in the holdout, under the 250
      needed to support a verdict; this ticker cannot be evaluated out-of-sample yet
```

**Why, in numbers.** `app.thesis.holdout.HOLDOUT_FRACTION = 0.25`. `cut = int(89 * 0.75) = 66`, so
`89 - 66 = 23` sessions would fall in the holdout — under `MIN_HOLDOUT_BARS = 250` by more than a
factor of ten. DRAM listed 2026-04-02, four calendar months before this run. At roughly 21 trading
days a month, DRAM needs **about 3.7 more years of trading history** (to accumulate ~1,000 sessions,
the rough total this project's holdout math needs before ~250 of them land past the 75% cut) before
its holdout could support a verdict at all — and that is before a single in-sample thesis is even
proposed. The loop refuses at the very first guard, before author.propose is called, before anything
is registered, exactly as designed: `HoldoutUnavailable` is raised by `holdout.establish()`, which
runs before the proposal loop in `loop.run`. Nothing about DRAM was tested; nothing was rejected;
there is simply not enough history yet to ask the question.

## FONO — refusal, verbatim

```
FONO: loop.run raised SymbolNotFoundWithContext: yahoo has no chart data for 'FONO'
```

This is not a holdout-power refusal — it is a data-existence refusal, one level earlier.
`app.thesis.loop.run` calls `app.market.store.ensure_series`, which walks the provider registry;
Yahoo (the only configured provider that responds for this symbol) reports no chart data at all, and
`SymbolNotFoundWithContext` is documented as **terminal** — the registry does not fall through to
another provider because a nonexistent ticker will not be found by asking elsewhere. There is no
partial answer to give here: not "insufficient history" (DRAM's problem) but "no history exists in
this system under this symbol." If `FONO` is a real, recently-listed or differently-ticker'd
instrument, the gap is in what this app's provider can see, not in the math above — this report can't
distinguish "delisted," "mistyped," or "not covered by this provider" from the outside, and neither
can the app.

---

## What this cannot tell you

- **Overlapping windows.** Every `n` reported above is the *independent* count after
  `app.backtest.forward.independent_count` discards overlapping forward windows — but even the
  independent subset is drawn from one historical path. A 20-bar-horizon rule with 87 "independent"
  triggers on QQQ observed 87 non-overlapping windows of the *same* 27-year sequence of macro events,
  not 87 draws from different economic universes.
- **Regime dependence.** None of the three tickers' full-history windows were broken out by regime in
  this study. QQQ's window spans the dot-com crash, 2008, the 2010s bull market, COVID, 2022, and the
  current run; SOXX and IGV span a shorter but still multi-regime slice. A rule's aggregate edge over
  25 years can hide a large regime-specific effect or, more commonly, be dragged around by one or two
  extreme episodes (see each ticker's drawdown profile above) that the aggregate hit rate does not
  surface.
- **Instrument correlation.** Stated above: QQQ/IGV and SOXX/DRAM are not independent trials of
  "does this rule work." Treat the three full-history results as roughly one and a half independent
  looks at large-cap tech, not three.
- **Survivorship.** These are the current constituents of live ETFs, not a point-in-time index
  membership; sector ETFs like SOXX and IGV have had holdings turnover this study did not adjust for.
- **A backtest is not a forecast.** Zero survivors here describes what five standard technical rules
  did on QQQ, SOXX and IGV's stored history under this project's pre-registration, correction and
  holdout discipline. It is not evidence about what any rule will do going forward, and the strategy
  backtest section above is a description of historical mechanics and costs, not a projection.
- **DRAM and FONO say nothing about whether either instrument is a reasonable holding** — only that
  this system cannot yet, or cannot at all, answer a statistical question about their price history.

---

## Application bug found (not fixed, per instructions)

**`app.backtest.scan.binomial_p_value` raises an uncaught `OverflowError` for large trial counts, and
the crash is not contained to the offending entry.**

Reproduction: `momentum_persistence` (`close > sma(200)`) at horizon 1 has `independent_sample_size` =
4,896 (QQQ), 4,129 (SOXX), 4,561 (IGV) — a condition true on ~70% of trading days, scanned at the
shortest horizon over 20+ years, has almost no window overlap to discard, so nearly every trigger
counts as independent. `math.comb(4896, 2595)` (the central binomial coefficient near this observed
count) is a Python integer with **1,469 decimal digits**. `scan.py`'s `pmf()` computes
`math.comb(trials, k) * (p_null**k) * ...`; multiplying that integer by a float forces an implicit
`int.__float__()` conversion, which raises `OverflowError: int too large to convert to float` because
the value exceeds `sys.float_info.max` (~1.8e308, ~309 digits) by over a thousand digits.

The line that raises (`app/backtest/scan.py`, `_entry_p_value` → `binomial_p_value` → `pmf`) sits
**outside** the `try/except Exception` in `scan.scan`'s main loop — that `try` wraps only the call to
the injected `evaluate()` collaborator, not the p-value computation performed on its result. So this
is not "one bad entry loses its own trial," which is the documented and correct degraded behavior for
every *other* untestable case in this module (guard failure, zero sample, no hit rate); it is **the
entire `ScanResult` for the whole call failing with an unhandled exception**, taking every other
entry's already-computed statistics down with it. Confirmed by running `app.backtest.scan.scan`
directly (script `03_horizon_scan.py`'s first attempt, preserved as the failing case) and by isolating
the exact inputs (script `03b_diagnose_overflow_bug.py`).

Because `app.thesis.loop.evaluate_thesis` also calls `binomial_p_value` (via the identical
`round(rate * independent)` pattern) but *does* wrap the whole per-thesis evaluation in
`try/except Exception` (marking the thesis `ABANDONED` rather than crashing the run), the
pre-registered loop is not vulnerable to this in the same way — this study's own loop runs never hit
it, only the supplementary scan did, because none of the five templates pre-declare horizon 1 for a
broadly-firing condition. But any future template, or any user-submitted scan/decision-table request
through `app.backtest.service.build_scan` (which calls the same `scan.scan`), that combines a
short horizon with a condition firing on a large fraction of a long history will 500 the whole
request. This is worth fixing at the `pmf()` level (e.g. working in log-space, or capping/estimating
via a normal approximation for very large `trials`) rather than only widening the `except` — the
underlying number really cannot be represented as a `float` and the exact-binomial approach this
module deliberately chose (over `scipy`) needs a large-`n` fallback it does not currently have.

**Secondary observation, not a crash but worth flagging separately:** `Thesis.falsifies_if` is a
free-text field carried through pre-registration and the ledger, but `app.thesis.loop.evaluate_thesis`
does not branch on it — every thesis, regardless of what its `falsifies_if` text says, is tested by
the identical generic machinery (forward-return hit rate vs. baseline at the declared horizon, plus
the direction check). `trend_following`'s catalogue entry declares its falsification criterion in
terms of **maximum drawdown** ("maximum drawdown while following the rule is not smaller than
buy-and-hold's"), but the loop only ever measured its 60-bar hit rate — QQQ's `trend_following` came
back `inconclusive` on a hit-rate test that was never the criterion actually written down, while the
drawdown claim it was pre-registered to test happened, descriptively, to hold in the strategy backtest
above (−30.3% vs buy-and-hold's −83.0%) without ever being formally screened, corrected, or
holdout-tested. `decay_avoidance` (leveraged-only, not exercised in this study since none of the four
tickers qualify) has the same shape. This does not change any verdict reported here — the loop's
generic test is a defensible proxy and it is what actually ran — but a reader taking `falsifies_if`
literally as "this is what was tested" would be misled for these two templates specifically.
