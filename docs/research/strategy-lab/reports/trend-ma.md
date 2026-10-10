# trend-ma — the note's MA/EMA systematic framework, tested

Run 2026-08-11. Stream `trend-ma`. Script: `scripts/trend_ma.py`. Data:
`data/trend_ma_primary.json` (primary family, 45 tests), `data/trend_ma_horizon_sweep.json`
(exploratory sweep, 225 trials, separate ledger). No replication run — the primary family produced
zero survivors, and per the brief the replication universe is only run for survivors.

Universe: `SPY QQQ IWM XLK XLV` (primary, unchanged from the brief). Costs: harness default
(`Costs(slippage_bps=5.0, commission_per_trade=0.0, notional=10000.0)`), never modified. Screening
bar: `q <= 0.10` (`SCREEN_ALPHA`). Small-sample floor: `n_independent < 30` is `underpowered`
(`SMALL_SAMPLE_THRESHOLD`). Windows: the same six regime slices used across the study
(`dotcom_2000_2002`, `bull_2003_2007`, `qe_bull_2009_2019`, `covid_2020_2021`, `bear_2022`,
`recent_2023_now`).

**Headline: zero survivors, 0 of 45 primary tests, 0 of 225 exploratory-sweep trials.** Every
lookahead guard passed. 44 of the 45 strategy backtests underperform buy-and-hold on total return;
the sole exception (`golden_cross_sma` on QQQ) wins by 5.8 percentage points on a test that itself
came back statistically inconclusive. That is the finding this report exists to document in detail,
not to soften.

---

## 1. What was tested

9 ideas × 5 symbols = 45 primary tests, one Benjamini-Hochberg ledger.

| key | entry | exit | horizon | direction | holding cap / stop | note reference |
|---|---|---|---|---|---|---|
| `ideal_entry_verbatim` | `ema(20) > sma(50) and sma(50) > ema(10) and ema(10) > sma(200)` | `ema(5) crosses_below ema(20)` | 20 | up | none / none | p.4 "Ideal Entry setup", literal ordering |
| `stacked_alignment_conventional` | `ema(10) > ema(20) and ema(20) > sma(50) and sma(50) > sma(200)` | `ema(5) crosses_below ema(20)` | 20 | up | none / none | p.4, conventional "fastest-on-top" reading |
| `stacked_alignment_no_gate` | `ema(10) > ema(20) and ema(20) > sma(50)` | `ema(5) crosses_below ema(20)` | 20 | up | none / none | same as above, 200-SMA regime gate removed — pairs with the row above |
| `golden_cross_sma` | `sma(50) crosses_above sma(200)` | `sma(50) crosses_below sma(200)` | 60 | up | none / none | p.4 crossover table, "50SMA×200SMA golden/dead cross" |
| `intermediate_cross_ema20_sma50` | `ema(20) crosses_above sma(50)` | `ema(20) crosses_below sma(50)` | 20 | up | none / none | p.4 crossover table, "20EMA×50SMA intermediate trend" |
| `price_cross_sma50` | `close crosses_above sma(50)` | `close crosses_below sma(50)` | 20 | up | none / none | p.3, "price crossing MA" (timing) — pairs with the row above |
| `short_term_cross_10ema_20sma` | `ema(10) crosses_above sma(20)` | `ema(10) crosses_below sma(20)` | 10 | up | none / none | p.4 crossover table, "10EMA×20MA short-term trend strengthening" |
| `ma_strategy_page` | `close > sma(200) and close > sma(120) and sma(5) crosses_above sma(20)` | `close >= bb_upper(20,2) or sma(5) crosses_below sma(20)` | 20 | up | none / none | p.9 "MA Strategy" page |
| `regime_filter_standalone` | `close > sma(200)` | `close < sma(200)` | 20 | up | none / none | p.2 "Trade in a rising market" |

All nine declared before anything ran; the family size never changed after seeing results.

---

## 2. What the note claims vs. what the data says

| Claim (note) | Idea(s) | What the data says |
|---|---|---|
| "Robust MA/EMA systematic framework" — 200SMA=regime, 50SMA=intermediate, 20EMA=active, 10EMA=timing (p.4) | all 9 | No combination built from these four MAs cleared `q <= 0.10` on any of 5 symbols, in either alignment reading. The framework does not produce a statistically distinguishable edge as tested. |
| "Ideal Entry setup," verbatim ordering `20EMA > 50SMA > 10EMA > 200MA` (p.4) | `ideal_entry_verbatim` | Positive edge on **all 5 symbols** (+0.058 to +0.121), the most consistent sign pattern of any idea in the family. None individually significant (best `p=0.103` on XLK, `q=0.793`), but no rejections either. |
| Conventional stacked-alignment reading `ema(10) > ema(20) > sma(50) > sma(200)` (p.4, alternative reading) | `stacked_alignment_conventional` | Mixed sign: positive on SPY/QQQ/XLK (tiny, +0.003 to +0.010), **rejected** (wrong-direction edge) on IWM (-0.046) and XLV (-0.027). |
| **Which reading does the data prefer?** | both above | The verbatim, "internally odd" ordering from the note *outperforms* the conventional fix on every symbol and never runs backwards. This is the opposite of what a naive reader would guess — a plausible "typo" reads as the better-behaved rule in this data, though neither survives correction. See §7 for the caveat this deserves. |
| Crossover table: 5MA×20MA / 10EMA×20MA / 20EMA×50SMA / 50SMA×200SMA (p.4) | `short_term_cross_10ema_20sma`, `intermediate_cross_ema20_sma50`, `golden_cross_sma` (5MA×20MA not tested, see §8) | `intermediate_cross_ema20_sma50` (20EMA×50SMA) is positive on all 5 symbols (+0.051 to +0.138) — the second-most consistent idea in the family. `short_term_cross_10ema_20sma` (10EMA×20MA) flips sign on 3 of 5 symbols and is **rejected** on SPY, QQQ, XLK. `golden_cross_sma` (50SMA×200SMA) is positive on 4 of 5 but structurally underpowered everywhere (n_independent 15–24, floor is 30) and **rejected** on XLV. |
| "Price crossing an MA" (timing) vs "MA crossing MA" (trend-confirmation) behave differently (p.3) | `price_cross_sma50` vs `intermediate_cross_ema20_sma50` | **Confirmed as a behavioral distinction, on all 5 symbols, even though neither survives.** MA-crossing-MA fires roughly half as often, has a materially higher win rate (41–55% vs. 26–33%), and pays roughly a third to a half the cost drag of price-crossing-MA. See §4 for the full table. |
| MA Strategy page: MA120/200 regime + MA5×MA20/60 entry, BB(20,2) touch or MA5×MA8/20 exit (p.9) | `ma_strategy_page` | The worst-performing idea in the family on strategy mechanics: exposure 15–19% (versus 27–74% for every other idea), total return 0.03x–0.69x against buy-and-hold's 5.5x–16.6x on the same windows. **Rejected** (wrong-direction edge) on SPY and XLV, inconclusive elsewhere. |
| "Trade in a rising market" — `close > sma(200)` as a standalone gate (p.2) | `regime_filter_standalone` | Positive edge on SPY/QQQ/XLK, **rejected** on IWM and XLV. Never beats buy-and-hold total return on any symbol. Consistently reduces max drawdown (see §4/§Q3 below) — the defensive claim holds up better than the offensive one. |

---

## 3. Primary family results

Full 45-cell grid. `n_raw` = raw triggers, `n_indep` = independent (non-overlapping) forward windows,
`hit`/`base` = event hit-rate vs. same-bars baseline, `edge = hit − base`. BH correction is across
the full 45-cell family (`m=45`).

| idea | sym | h | n_raw | n_indep | hit | base | edge | p | q | verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| ideal_entry_verbatim | SPY | 20 | 167 | 69 | 0.731 | 0.636 | +0.095 | 0.1346 | 0.7930 | inconclusive |
| stacked_alignment_conventional | SPY | 20 | 4020 | 245 | 0.649 | 0.638 | +0.010 | 0.7903 | 0.9738 | inconclusive |
| stacked_alignment_no_gate | SPY | 20 | 4906 | 300 | 0.632 | 0.636 | -0.004 | 0.9522 | 0.9738 | **rejected** |
| golden_cross_sma | SPY | 60 | 15 | 15 | 0.933 | 0.694 | +0.239 | 0.0493 | 0.7930 | underpowered |
| intermediate_cross_ema20_sma50 | SPY | 20 | 92 | 87 | 0.696 | 0.636 | +0.060 | 0.2219 | 0.8918 | inconclusive |
| price_cross_sma50 | SPY | 20 | 304 | 159 | 0.655 | 0.636 | +0.018 | 0.6807 | 0.9738 | inconclusive |
| short_term_cross_10ema_20sma | SPY | 10 | 221 | 208 | 0.593 | 0.601 | -0.008 | 0.7774 | 0.9738 | **rejected** |
| ma_strategy_page | SPY | 20 | 173 | 128 | 0.624 | 0.635 | -0.010 | 0.8545 | 0.9738 | **rejected** |
| regime_filter_standalone | SPY | 20 | 6148 | 335 | 0.658 | 0.637 | +0.021 | 0.4954 | 0.8918 | inconclusive |
| ideal_entry_verbatim | QQQ | 20 | 120 | 53 | 0.683 | 0.621 | +0.063 | 0.4002 | 0.8918 | inconclusive |
| stacked_alignment_conventional | QQQ | 20 | 3124 | 189 | 0.622 | 0.619 | +0.003 | 0.9403 | 0.9738 | inconclusive |
| stacked_alignment_no_gate | QQQ | 20 | 3909 | 238 | 0.627 | 0.621 | +0.006 | 0.8939 | 0.9738 | inconclusive |
| golden_cross_sma | QQQ | 60 | 17 | 15 | 0.765 | 0.668 | +0.097 | 0.7857 | 0.9738 | underpowered |
| intermediate_cross_ema20_sma50 | QQQ | 20 | 67 | 65 | 0.672 | 0.621 | +0.051 | 0.3741 | 0.8918 | inconclusive |
| price_cross_sma50 | QQQ | 20 | 217 | 122 | 0.687 | 0.621 | +0.066 | 0.1356 | 0.7930 | inconclusive |
| short_term_cross_10ema_20sma | QQQ | 10 | 181 | 171 | 0.564 | 0.588 | -0.024 | 0.4853 | 0.8918 | **rejected** |
| ma_strategy_page | QQQ | 20 | 141 | 106 | 0.638 | 0.619 | +0.019 | 0.6896 | 0.9738 | inconclusive |
| regime_filter_standalone | QQQ | 20 | 4877 | 268 | 0.639 | 0.617 | +0.022 | 0.4903 | 0.8918 | inconclusive |
| ideal_entry_verbatim | IWM | 20 | 103 | 52 | 0.670 | 0.590 | +0.080 | 0.2601 | 0.8918 | inconclusive |
| stacked_alignment_conventional | IWM | 20 | 2525 | 159 | 0.547 | 0.593 | -0.046 | 0.2586 | 0.8918 | **rejected** |
| stacked_alignment_no_gate | IWM | 20 | 3511 | 218 | 0.566 | 0.590 | -0.024 | 0.4494 | 0.8918 | **rejected** |
| golden_cross_sma | IWM | 60 | 19 | 19 | 0.684 | 0.633 | +0.051 | 0.8130 | 0.9738 | underpowered |
| intermediate_cross_ema20_sma50 | IWM | 20 | 70 | 68 | 0.643 | 0.589 | +0.054 | 0.3886 | 0.8918 | inconclusive |
| price_cross_sma50 | IWM | 20 | 239 | 131 | 0.623 | 0.589 | +0.034 | 0.4248 | 0.8918 | inconclusive |
| short_term_cross_10ema_20sma | IWM | 10 | 182 | 168 | 0.615 | 0.560 | +0.055 | 0.1863 | 0.8918 | inconclusive |
| ma_strategy_page | IWM | 20 | 126 | 97 | 0.611 | 0.589 | +0.022 | 0.7573 | 0.9738 | inconclusive |
| regime_filter_standalone | IWM | 20 | 4276 | 240 | 0.574 | 0.595 | -0.021 | 0.5542 | 0.9236 | **rejected** |
| ideal_entry_verbatim | XLK | 20 | 103 | 48 | 0.728 | 0.607 | +0.121 | 0.1033 | 0.7930 | inconclusive |
| stacked_alignment_conventional | XLK | 20 | 2986 | 186 | 0.621 | 0.613 | +0.008 | 0.9400 | 0.9738 | inconclusive |
| stacked_alignment_no_gate | XLK | 20 | 3792 | 235 | 0.616 | 0.608 | +0.008 | 0.8412 | 0.9738 | inconclusive |
| golden_cross_sma | XLK | 60 | 16 | 16 | 0.688 | 0.658 | +0.029 | 1.0000 | 1.0000 | underpowered |
| intermediate_cross_ema20_sma50 | XLK | 20 | 74 | 69 | 0.689 | 0.608 | +0.081 | 0.1410 | 0.7930 | inconclusive |
| price_cross_sma50 | XLK | 20 | 242 | 127 | 0.649 | 0.608 | +0.041 | 0.4141 | 0.8918 | inconclusive |
| short_term_cross_10ema_20sma | XLK | 10 | 180 | 172 | 0.517 | 0.578 | -0.062 | 0.1223 | 0.7930 | **rejected** |
| ma_strategy_page | XLK | 20 | 131 | 100 | 0.695 | 0.607 | +0.087 | 0.1012 | 0.7930 | inconclusive |
| regime_filter_standalone | XLK | 20 | 4824 | 264 | 0.637 | 0.610 | +0.027 | 0.4122 | 0.8918 | inconclusive |
| ideal_entry_verbatim | XLV | 20 | 129 | 55 | 0.651 | 0.593 | +0.058 | 0.4110 | 0.8918 | inconclusive |
| stacked_alignment_conventional | XLV | 20 | 2523 | 161 | 0.568 | 0.595 | -0.027 | 0.4703 | 0.8918 | **rejected** |
| stacked_alignment_no_gate | XLV | 20 | 3679 | 229 | 0.572 | 0.593 | -0.021 | 0.5451 | 0.9236 | **rejected** |
| golden_cross_sma | XLV | 60 | 24 | 23 | 0.625 | 0.643 | -0.018 | 0.8283 | 0.9738 | **rejected** |
| intermediate_cross_ema20_sma50 | XLV | 20 | 78 | 74 | 0.731 | 0.593 | +0.138 | 0.0176 | 0.7930 | inconclusive |
| price_cross_sma50 | XLV | 20 | 259 | 140 | 0.602 | 0.593 | +0.009 | 0.9315 | 0.9738 | inconclusive |
| short_term_cross_10ema_20sma | XLV | 10 | 197 | 184 | 0.574 | 0.559 | +0.015 | 0.6566 | 0.9738 | inconclusive |
| ma_strategy_page | XLV | 20 | 126 | 105 | 0.571 | 0.594 | -0.023 | 0.6912 | 0.9738 | **rejected** |
| regime_filter_standalone | XLV | 20 | 4600 | 268 | 0.571 | 0.596 | -0.025 | 0.4184 | 0.8918 | **rejected** |

**0 of 45 cells `survived` (q ≤ 0.10).** 4 `underpowered` (all `golden_cross_sma`, every symbol —
n_independent 15–24, all below the 30-observation floor). 10 `rejected` (wrong-direction edge,
correctly distinguished from "not enough data" by the direction check). The remaining 31 are
`inconclusive`. Every `p_value` in the family clears well above the naive 0.05/0.10 line the moment
BH is applied across all 45 cells — the smallest raw p in the family, `golden_cross_sma`/SPY at
`p=0.0493`, becomes `q=0.7930`.

**Lookahead guard: `passed` on every one of the 45 entry expressions and every one of the 9 exit
expressions.** No `UNVERIFIED` findings anywhere in the family.

---

## 4. Strategy mechanics vs. buy-and-hold

Full history per symbol, `Costs(slippage_bps=5.0, commission_per_trade=0.0, notional=10000.0)`,
closed trades only for win/loss counts.

| idea | sym | strat total ret | bh total ret | strat CAGR | bh CAGR | strat Sharpe | bh Sharpe | strat maxDD | bh maxDD | exposure | trades | win rate | cost drag | beats BH (total ret) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ideal_entry_verbatim | SPY | 4.522 | 16.587 | 5.2% | 8.9% | 0.542 | 0.554 | -0.290 | -0.565 | 0.33 | 70 | 0.68 | -0.397 | False |
| stacked_alignment_conventional | SPY | 2.083 | 16.587 | 3.4% | 8.9% | 0.404 | 0.554 | -0.323 | -0.565 | 0.55 | 162 | 0.46 | -0.540 | False |
| stacked_alignment_no_gate | SPY | 2.145 | 16.587 | 3.5% | 8.9% | 0.348 | 0.554 | -0.397 | -0.565 | 0.70 | 199 | 0.44 | -0.691 | False |
| golden_cross_sma | SPY | 14.002 | 16.587 | 8.4% | 8.9% | 0.669 | 0.554 | -0.341 | -0.565 | 0.72 | 15 | 0.79 | -0.219 | False |
| intermediate_cross_ema20_sma50 | SPY | 2.483 | 16.587 | 3.8% | 8.9% | 0.383 | 0.554 | -0.391 | -0.565 | 0.68 | 93 | 0.49 | -0.338 | False |
| price_cross_sma50 | SPY | 1.911 | 16.587 | 3.2% | 8.9% | 0.349 | 0.554 | -0.419 | -0.565 | 0.70 | 306 | 0.30 | -1.040 | False |
| short_term_cross_10ema_20sma | SPY | 2.703 | 16.587 | 4.0% | 8.9% | 0.407 | 0.554 | -0.367 | -0.565 | 0.66 | 222 | 0.46 | -0.918 | False |
| ma_strategy_page | SPY | 0.176 | 16.587 | 0.5% | 8.9% | 0.120 | 0.554 | -0.261 | -0.565 | 0.19 | 174 | 0.55 | -0.224 | False |
| regime_filter_standalone | SPY | 7.217 | 16.587 | 6.5% | 8.9% | 0.592 | 0.554 | -0.305 | -0.565 | 0.74 | 112 | 0.30 | -0.969 | False |
| ideal_entry_verbatim | QQQ | 2.426 | 13.014 | 4.6% | 10.1% | 0.373 | 0.493 | -0.385 | -0.830 | 0.33 | 55 | 0.64 | -0.194 | False |
| stacked_alignment_conventional | QQQ | 5.186 | 13.014 | 6.9% | 10.1% | 0.572 | 0.493 | -0.244 | -0.830 | 0.52 | 132 | 0.49 | -0.873 | False |
| stacked_alignment_no_gate | QQQ | 9.511 | 13.014 | 9.0% | 10.1% | 0.588 | 0.493 | -0.561 | -0.830 | 0.66 | 161 | 0.48 | -1.836 | False |
| golden_cross_sma | QQQ | 13.768 | 13.014 | 10.3% | 10.1% | 0.698 | 0.493 | -0.286 | -0.830 | 0.68 | 17 | 0.62 | -0.246 | **True** |
| intermediate_cross_ema20_sma50 | QQQ | 6.585 | 13.014 | 7.7% | 10.1% | 0.528 | 0.493 | -0.433 | -0.830 | 0.66 | 67 | 0.55 | -0.526 | False |
| price_cross_sma50 | QQQ | 6.888 | 13.014 | 7.8% | 10.1% | 0.548 | 0.493 | -0.470 | -0.830 | 0.68 | 220 | 0.29 | -1.936 | False |
| short_term_cross_10ema_20sma | QQQ | 4.520 | 13.014 | 6.4% | 10.1% | 0.466 | 0.493 | -0.515 | -0.830 | 0.63 | 182 | 0.44 | -1.099 | False |
| ma_strategy_page | QQQ | 0.326 | 13.014 | 1.0% | 10.1% | 0.185 | 0.493 | -0.202 | -0.830 | 0.19 | 142 | 0.54 | -0.202 | False |
| regime_filter_standalone | QQQ | 6.951 | 13.014 | 7.9% | 10.1% | 0.536 | 0.493 | -0.543 | -0.830 | 0.72 | 87 | 0.27 | -0.718 | False |
| ideal_entry_verbatim | IWM | 1.886 | 5.503 | 4.1% | 7.4% | 0.453 | 0.420 | -0.276 | -0.595 | 0.27 | 54 | 0.70 | -0.159 | False |
| stacked_alignment_conventional | IWM | 0.153 | 5.503 | 0.5% | 7.4% | 0.105 | 0.420 | -0.425 | -0.595 | 0.47 | 138 | 0.41 | -0.170 | False |
| stacked_alignment_no_gate | IWM | 1.000 | 5.503 | 2.7% | 7.4% | 0.250 | 0.420 | -0.416 | -0.595 | 0.65 | 172 | 0.42 | -0.374 | False |
| golden_cross_sma | IWM | 0.349 | 5.503 | 1.2% | 7.4% | 0.152 | 0.420 | -0.512 | -0.595 | 0.66 | 19 | 0.56 | -0.025 | False |
| intermediate_cross_ema20_sma50 | IWM | 1.485 | 5.503 | 3.5% | 7.4% | 0.303 | 0.420 | -0.367 | -0.595 | 0.64 | 70 | 0.41 | -0.179 | False |
| price_cross_sma50 | IWM | 0.672 | 5.503 | 2.0% | 7.4% | 0.207 | 0.420 | -0.397 | -0.595 | 0.65 | 242 | 0.30 | -0.457 | False |
| short_term_cross_10ema_20sma | IWM | 0.751 | 5.503 | 2.2% | 7.4% | 0.217 | 0.420 | -0.488 | -0.595 | 0.61 | 183 | 0.41 | -0.351 | False |
| ma_strategy_page | IWM | 0.025 | 5.503 | 0.1% | 7.4% | 0.047 | 0.420 | -0.273 | -0.595 | 0.16 | 127 | 0.56 | -0.138 | False |
| regime_filter_standalone | IWM | 1.345 | 5.503 | 3.3% | 7.4% | 0.297 | 0.420 | -0.394 | -0.595 | 0.67 | 112 | 0.23 | -0.277 | False |
| ideal_entry_verbatim | XLK | 4.011 | 10.479 | 6.0% | 9.3% | 0.548 | 0.470 | -0.249 | -0.820 | 0.27 | 49 | 0.69 | -0.249 | False |
| stacked_alignment_conventional | XLK | 3.951 | 10.479 | 6.0% | 9.3% | 0.511 | 0.470 | -0.313 | -0.820 | 0.51 | 128 | 0.49 | -0.673 | False |
| stacked_alignment_no_gate | XLK | 4.735 | 10.479 | 6.5% | 9.3% | 0.464 | 0.470 | -0.547 | -0.820 | 0.65 | 158 | 0.47 | -0.978 | False |
| golden_cross_sma | XLK | 8.259 | 10.479 | 8.4% | 9.3% | 0.584 | 0.470 | -0.315 | -0.820 | 0.66 | 16 | 0.67 | -0.145 | False |
| intermediate_cross_ema20_sma50 | XLK | 4.231 | 10.479 | 6.2% | 9.3% | 0.458 | 0.470 | -0.482 | -0.820 | 0.64 | 74 | 0.54 | -0.402 | False |
| price_cross_sma50 | XLK | 5.306 | 10.479 | 6.9% | 9.3% | 0.511 | 0.470 | -0.347 | -0.820 | 0.67 | 244 | 0.33 | -1.739 | False |
| short_term_cross_10ema_20sma | XLK | 3.338 | 10.479 | 5.5% | 9.3% | 0.420 | 0.470 | -0.510 | -0.820 | 0.62 | 181 | 0.45 | -0.858 | False |
| ma_strategy_page | XLK | 0.691 | 10.479 | 1.9% | 9.3% | 0.322 | 0.470 | -0.163 | -0.820 | 0.18 | 132 | 0.56 | -0.238 | False |
| regime_filter_standalone | XLK | 8.414 | 10.479 | 8.5% | 9.3% | 0.588 | 0.470 | -0.528 | -0.820 | 0.71 | 90 | 0.27 | -0.881 | False |
| ideal_entry_verbatim | XLV | 1.041 | 5.578 | 2.6% | 7.1% | 0.358 | 0.472 | -0.340 | -0.406 | 0.28 | 56 | 0.68 | -0.118 | False |
| stacked_alignment_conventional | XLV | 0.058 | 5.578 | 0.2% | 7.1% | 0.070 | 0.472 | -0.478 | -0.406 | 0.47 | 124 | 0.41 | -0.139 | False |
| stacked_alignment_no_gate | XLV | 0.072 | 5.578 | 0.3% | 7.1% | 0.085 | 0.472 | -0.593 | -0.406 | 0.66 | 169 | 0.41 | -0.197 | False |
| golden_cross_sma | XLV | 0.527 | 5.578 | 1.5% | 7.1% | 0.183 | 0.472 | -0.447 | -0.406 | 0.65 | 25 | 0.46 | -0.038 | False |
| intermediate_cross_ema20_sma50 | XLV | 0.919 | 5.578 | 2.4% | 7.1% | 0.265 | 0.472 | -0.430 | -0.406 | 0.63 | 78 | 0.47 | -0.155 | False |
| price_cross_sma50 | XLV | 0.089 | 5.578 | 0.3% | 7.1% | 0.083 | 0.472 | -0.507 | -0.406 | 0.65 | 259 | 0.26 | -0.321 | False |
| short_term_cross_10ema_20sma | XLV | 0.095 | 5.578 | 0.3% | 7.1% | 0.085 | 0.472 | -0.431 | -0.406 | 0.61 | 198 | 0.42 | -0.239 | False |
| ma_strategy_page | XLV | 0.213 | 5.578 | 0.7% | 7.1% | 0.174 | 0.472 | -0.276 | -0.406 | 0.15 | 127 | 0.59 | -0.164 | False |
| regime_filter_standalone | XLV | 0.099 | 5.578 | 0.3% | 7.1% | 0.088 | 0.472 | -0.551 | -0.406 | 0.69 | 157 | 0.20 | -0.186 | False |

**Aggregate, said plainly: 44 of 45 cells underperform buy-and-hold on total return.** The only
exception is `golden_cross_sma` on QQQ (13.77x vs. 13.01x, +5.8 percentage points) — a strategy whose
own event-study test came back `underpowered` (n_independent=15). 14 of 45 cells post a *higher*
Sharpe than buy-and-hold (mostly `golden_cross_sma` and `regime_filter_standalone`, the two lowest-
turnover ideas), and 38 of 45 cells have a shallower max drawdown than buy-and-hold on the identical
window. That is the trend-following trade the note describes, showing up exactly where it should:
**less time in the market, usually a shallower drawdown, almost always a worse total return.**
`XLV` is the one symbol where several ideas' max drawdown is *deeper* than buy-and-hold's own
(−0.41 to −0.59 vs. buy-and-hold's −0.41) — healthcare's own drawdown history is comparatively mild,
so there is less downside for a filter to avoid, and several of these rules manage to be both
whipsawed and no safer.

`ma_strategy_page` is the standout failure on mechanics specifically: exposure of 0.15–0.19 across
all five symbols (versus 0.27–0.74 for every other idea) — the BB(20,2)-touch leg of its exit fires
so readily that positions almost never stay open, and total return collapses to 0.03x–0.69x against
buy-and-hold's 5.5x–16.6x on the same window.

---

## 5. Regime breakdown

Full window table lives in the JSON (`per_symbol.<SYM>.ideas.<idea>.windows`); highlights:

- **`golden_cross_sma` is carried almost entirely by two windows.** On SPY, QQQ, XLK it registers
  **zero trades** in `dotcom_2000_2002`, `covid_2020_2021`, and `bear_2022` (the 50/200 relationship
  was already established before each window opened and never flipped inside it), and the bulk of
  its full-history return comes from `qe_bull_2009_2019` alone (e.g. QQQ: `qe_bull` window
  strat=+192.6% vs. buy-and-hold +578.8%; `bull_2003_2007` and `recent_2023_now` contribute the rest
  in single-digit-trade amounts). This is the textbook shape of "aggregate result carried by one
  regime" the brief asks to flag, and it is the same structural reason the idea is `underpowered`
  everywhere: a 50/200 SMA cross is a rare event, and a handful of decade-spaced crosses cannot
  populate six independent regime windows.
- **`regime_filter_standalone` trades in every window on every symbol** — it is the most regime-
  robust idea in the family by construction, since `close > sma(200)` flips often enough to have
  activity even in short windows (1–40 trades per window). It still underperforms buy-and-hold on
  total return in every window with meaningful exposure, because being out of the market for the
  fastest recovery legs (e.g. `qe_bull_2009_2019`, where it captures QQQ +109.0% against buy-and-hold's
  +578.8%) costs far more than the whipsaw losses it avoids in `dotcom_2000_2002` and `bear_2022`
  save.
- **`stacked_alignment_no_gate` is the only idea that ever posts a full window with *worse* drawdown
  than buy-and-hold while also losing money outright** — SPY's `dotcom_2000_2002` window: strategy
  −31.7% vs. buy-and-hold −38.5% (still shallower, but barely, on 17 trades of whipsaw), and XLK's
  same window: strategy −39.8% vs. buy-and-hold −72.6% (here the filter genuinely helps). The size
  of the regime-gate benefit is regime-dependent, not a constant.
- No window shows any idea with a materially *higher* return than the aggregate full-history figure
  implies — none of the nine ideas are "secretly good in one regime and bad everywhere else and it
  washes out to inconclusive." The inconclusive verdicts are inconclusive throughout, not a mix of
  a real regime effect and a canceling one.

---

## Question 1: does the regime filter earn its keep?

Paired test, identical entry structure, identical exit/horizon/direction, only the `sma(50) >
sma(200)` gate differs: `stacked_alignment_conventional` (gate on) vs. `stacked_alignment_no_gate`
(gate off).

| symbol | maxDD w/ gate | maxDD no gate | total ret w/ gate | total ret no gate | exposure w/ gate | exposure no gate | edge w/ gate | edge no gate |
|---|---|---|---|---|---|---|---|---|
| SPY | -0.323 | -0.397 | 2.083 | 2.145 | 0.55 | 0.70 | +0.010 | -0.004 |
| QQQ | -0.244 | -0.561 | 5.186 | 9.511 | 0.52 | 0.66 | +0.003 | +0.006 |
| IWM | -0.425 | -0.416 | 0.153 | 1.000 | 0.47 | 0.65 | -0.046 | -0.024 |
| XLK | -0.313 | -0.547 | 3.951 | 4.735 | 0.51 | 0.65 | +0.008 | +0.008 |
| XLV | -0.478 | -0.593 | 0.058 | 0.072 | 0.47 | 0.66 | -0.027 | -0.021 |

**The gate's effect is defensive, not offensive.** It shrinks max drawdown on 4 of 5 symbols
(sometimes by more than half: QQQ -24.4% vs. -56.1%, XLK -31.3% vs. -54.7%) and cuts exposure by
roughly 15–19 percentage points every time, exactly as the "trades less, drawdowns less" claim
predicts. It does **not** reliably improve the forward-hit-rate edge: it helps on SPY (edge flips
from -0.004 to +0.010), is a wash on XLK and QQQ (both within 0.005 of each other, and QQQ's edge is
actually very slightly *worse* with the gate on), and makes the edge *worse* on IWM (-0.046 vs.
-0.024) and XLV (-0.027 vs. -0.021) — both already-rejected cells. On IWM specifically the gate also
costs total return without buying a shallower drawdown (-0.425 vs. -0.416, essentially identical).
**Verdict: the 200-day regime gate earns its keep on the drawdown/exposure axis in this data, but
not on the timing axis** — it makes the ride smoother without making the entries more accurate, and
on 2 of 5 symbols it makes the entries measurably less accurate.

## Question 2: does the golden cross (50/200) actually do anything?

`golden_cross_sma` (SMA, per the note) is `underpowered` on SPY/QQQ/IWM/XLK (n_independent 15, 15,
19, 16 — all under the 30 floor) and outright `rejected` on XLV (edge -0.018, n_independent=23). A
bigger family (5 symbols instead of the prior study's 1) does **not** fix this, because each symbol
is its own independent test cell, not a pooled one — the harness corrects `len(ideas) x
len(symbols)` cells, it does not pool triggers across symbols into one larger `n`. A 50/200-day
moving-average cross is inherently a rare event (roughly one every several years per symbol), so
`n_independent` stays in the teens-to-twenties no matter how many symbols are added to the family,
short of pooling across instruments (which the harness deliberately does not do, since QQQ/SPY/XLK
crosses are not independent draws — see §7).

Comparing to the prior study's EMA(50)×EMA(200) version on QQQ directly:

| | prior study (`trend_following`, EMA, QQQ, h=60) | this study (`golden_cross_sma`, SMA, QQQ, h=60) |
|---|---|---|
| n_independent | 10 | 15 |
| edge | +0.184 | +0.097 |
| p / q | 0.510 / 0.511 | 0.786 / 0.974 |
| verdict | inconclusive (n<30) | underpowered |
| strategy total return | 13.371x | 13.768x |
| buy-and-hold total return | 13.014x | 13.014x |
| strategy max DD | -0.303 | -0.286 |
| buy-and-hold max DD | -0.830 | -0.830 |

**The SMA and EMA readings of the golden cross behave almost identically on QQQ**: both structurally
underpowered, both produce a small total-return edge over buy-and-hold driven almost entirely by
staying out of the 2000–2002 and 2008-adjacent drawdowns rather than by superior entries, and neither
clears significance. The note specifies SMA; the prior study (working from the app's own
pre-registered catalogue) used EMA. That the choice barely matters here is itself informative — the
golden cross's apparent virtue in this data is a drawdown-avoidance effect, not a moving-average-type
effect, and it is not statistically distinguishable from noise on any symbol tested, in either
formulation.

## Question 3: exposure and drawdown, not just return

Across the full 45-cell primary family: **1 of 45 strategies beats buy-and-hold on total return**
(`golden_cross_sma`/QQQ, and only by 5.8 points on an underpowered test), **14 of 45 beat
buy-and-hold on Sharpe**, and **38 of 45 have a shallower max drawdown than buy-and-hold on the
identical window**. Stated plainly, per idea, per symbol (full table in §4):

- Every one of the 9 ideas underperforms buy-and-hold's total return on at least 4 of 5 symbols;
  `ma_strategy_page` and `stacked_alignment_conventional`/`_no_gate` underperform on all 5.
- Exposure ranges from 0.15 (`ma_strategy_page`, everywhere) to 0.81 (`regime_filter_standalone` on
  QQQ within the `qe_bull_2009_2019` window). Lower exposure does correlate with the ideas that show
  the smallest cost drag (`golden_cross_sma`: -0.02 to -0.25 total-return points lost to slippage,
  versus `price_cross_sma50`: -0.32 to -1.94) — fewer, more decisive signals cost less to trade, as
  the note's own crossover-vs-price-cross distinction would predict (see §2, §4).
- Max drawdown is shallower than buy-and-hold in 38 of 45 cells but the 7 exceptions cluster on XLV
  (5 of the 7), where buy-and-hold's own history is comparatively mild (max DD -0.406) and several
  filters manage to be both less profitable and no safer.

---

## 6. Replication

**Not run.** Zero of 45 primary cells `survived`, and per the brief the replication universe
(`DIA SOXX IGV XLF XLE XLP XLU XLY XLI XLB XLC TLT GLD`) is run only for ideas that cleared the
primary screen. `scripts/trend_ma.py` checks for survivors and skips the replication call entirely
when there are none — confirmed in the run log ("No primary survivors -- replication universe not
run").

---

## 7. What this cannot tell you

- **Overlapping windows, one historical path.** Every `n_independent` above already discards
  overlapping forward windows, but the independent subset is still drawn from one realized sequence
  of macro history. `golden_cross_sma`'s 15–24 "independent" golden crosses per symbol are 15–24
  non-overlapping windows of the same market history, not 15–24 draws from different economic
  universes — this is the direct cause of its structural underpower, and no amount of BH correction
  fixes a small `n`.
- **Instrument correlation.** SPY, QQQ, and XLK are three views of the same large-cap growth complex;
  a rule that shows a consistent-sign edge on all three (as `intermediate_cross_ema20_sma50` and
  `ideal_entry_verbatim` both do) is showing you one macro-tech regime expressing itself three times,
  not three independent confirmations. IWM and XLV are the two symbols where several ideas flip to
  `rejected`, and that divergence is the more informative signal than the SPY/QQQ/XLK agreement.
- **Correction family size vs. power.** Running 5 symbols instead of 1 makes the BH correction more
  conservative (`m=45` instead of `m=5`), which is the honest cost of a bigger family — it does not,
  by itself, give any individual cell more independent observations. `golden_cross_sma` proves this
  directly: 5x the symbols, and it is still underpowered on 4 of 5.
- **Regime dependence and survivorship.** As in the prior study: sector/index ETF constituents
  (XLK, XLV specifically) are current holdings, not a point-in-time membership snapshot, and this
  study does not adjust for turnover. The six regime windows are non-overlapping by construction but
  still hand-drawn around known historical episodes, not statistically derived breakpoints.
- **A backtest is not a forecast.** Everything above describes what these nine MA/EMA constructions
  did on five ETFs' stored daily history under this project's declared costs, correction, and
  screening discipline. It says nothing about what any of them will do going forward, and the
  strategy-mechanics tables are a description of historical mechanics and costs, not a projection.
- **The "verbatim ordering wins" finding needs a caveat of its own.** `ideal_entry_verbatim` showing
  a more consistent sign than `stacked_alignment_conventional` is a real, reportable pattern in this
  data — but neither idea clears `q <= 0.10` on any symbol, so "the data prefers the verbatim
  reading" means exactly "of two ideas that both failed to reach significance, one failed slightly
  less badly and more consistently," not "the verbatim reading works."

---

## 8. What could not be expressed, and what was done instead

- **MA slope / "direction" (note p.9, "MA120/200 direction").** The DSL has no derivative or
  slope operator. `ma_strategy_page`'s "long-term MA120/200 direction aligned with price location"
  was encoded as `close > sma(200) and close > sma(120)` (price above both long-term MAs) rather than
  the MAs themselves rising — a location proxy for a direction claim. This likely overstates how
  often the note's actual condition would fire, since price can sit above a still-declining MA.
- **"2 pull-back entry ⇒ price @ 10 EMA & 20 EMA" (note p.4).** The DSL has no proximity/tolerance
  operator ("price near level X" is not expressible; only `<`, `<=`, `>`, `>=`, `==`, `!=`,
  `crosses_above`, `crosses_below`). `ideal_entry_verbatim` tests the alignment condition the pullback
  is supposed to occur *within*, and reuses the note's own "5EMA crossing 20EMA" as the exit/timing
  trigger, but the pullback-to-the-MA entry itself — the more specific, arguably more important half
  of the "Ideal Entry setup" — is not tested by this study.
- **"5MA×20MA — short-term momentum" (note p.4 crossover table).** Budget, not the DSL, is the
  constraint here: the expression itself (`sma(5) crosses_above sma(20)`) is trivially expressible,
  but the family was already at the 9-idea cap. It was dropped in favor of
  `intermediate_cross_ema20_sma50` (already testing a 20-period crossover against a 50-period MA) and
  `short_term_cross_10ema_20sma` (already testing a 10-vs-20 crossover); adding a fourth crossover
  variant would have pushed the family past the 9-idea cap for a fourth, weaker copy of a concept
  already covered twice.
- **"MA5–MA8/20 crossover" as an exit (note p.9).** The note names two possible fast-MA pairings for
  the exit leg (MA5×MA8 or MA5×MA20) without disambiguating. `ma_strategy_page`'s exit uses MA5×MA20
  to match the entry leg's own MA20 reference, rather than introducing an MA8 that appears nowhere
  else in the family; the MA5×MA8 reading was not separately tested.
- **ADX, Stochastic, Ichimoku, Fibonacci, order flow, divergence, VWAP, multi-timeframe confluence**
  — none of these appear anywhere in this stream's assignment, but for completeness: none are in the
  DSL registry (brief §4), and none were needed for any of the nine ideas above.

---

## Application bug encountered

**None found — and the prior study's bug appears already fixed.** All 45 lookahead guards passed;
`run_family` and `horizon_sweep` completed without exception. Notably, the exploratory sweep
(`data/trend_ma_horizon_sweep.json`) includes `close > sma(200)` at horizon 1 on all five primary
symbols — the exact expression/horizon combination the prior study reported as an uncaught
`OverflowError` in `app.backtest.scan.binomial_p_value` (there, `momentum_persistence`/QQQ, h=1,
n_independent=4,896). This study's own equivalent cells ran to completion with valid p-values on
every symbol, including larger trial counts than the prior study's crash case:

| symbol | n_independent | p_value |
|---|---|---|
| SPY | 6,167 | 0.888 |
| QQQ | 4,896 | 0.466 |
| IWM | 4,295 | 0.726 |
| XLK | 4,843 | 0.481 |
| XLV | 4,619 | 0.026 |

Reading `backend/app/backtest/scan.py`'s current `binomial_p_value` (lines ~62–110) confirms why:
its docstring now states explicitly that "every pmf term is computed in log space via `math.lgamma`,
never via `math.comb`" and names this exact scenario — `close > sma(200)` at horizon 1 against
ordinary tickers with thousands of sessions — as the "routine crash" the log-space rewrite exists to
prevent. The fix matches the prior study's own recommendation ("this is worth fixing at the `pmf()`
level, e.g. working in log-space... rather than only widening the `except`"). Per the brief, this
study made no source changes; the fix was already present when this stream began. Nothing else
anomalous was observed in this stream's runs.
