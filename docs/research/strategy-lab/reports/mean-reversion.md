# Mean reversion — Bollinger Bands, z-score, and volatility regime

Stream `mean-reversion`, run 2026-08-11. All numbers below are copy-pasteable from
`docs/research/strategy-lab/data/mean_reversion_primary.json` (primary family) and
`docs/research/strategy-lab/data/mean_reversion_horizon_sweep.json` (exploratory sweep). The script
that produced them is `docs/research/strategy-lab/scripts/mean_reversion.py`. No replication file was
written -- see §6. This stream used the shared harness (`lib/quantlab.py`) exactly as documented; no
application source was modified; `data/store/thesis.sqlite` and `data/store/runs` were never touched.

**Headline finding.** The note's headline entry rule reproduces almost exactly on SPY (edge +0.133,
n_indep=87, p=0.0075 here vs the smoke test's +0.134/87/0.0075) and on QQQ (+0.099/63/0.153 here vs
the smoke test's +0.099/63/0.153). Once corrected across this stream's actual 40-test family instead
of the smoke test's 2-test family, SPY's q rises from ~0.015 (what a 2-test BH correction gives) to
**0.276** -- well above the 0.10 screening bar. **Zero of 40 primary tests survived.** This is
consistent with the rest of this study: the prior QQQ/SOXX/IGV report found zero survivors across 75
tests, and the trend-ma stream (run in parallel on this same date) also reports zero primary
survivors.

---

## 1. What was tested

8 ideas x 5 primary symbols (SPY, QQQ, IWM, XLK, XLV) = 40 primary tests, one Benjamini-Hochberg
ledger, `screen_alpha=0.10`, costs at harness default (5 bps slippage each way, $0 commission,
$10,000 notional). Every idea uses horizon 20, matching the smoke test's own declared horizon and
keeping every idea directly comparable to every other.

| key | entry | exit | horizon | direction | holding cap | stop | note line |
|---|---|---|---|---|---|---|---|
| `bb_lower_only` | `close < bb_lower(20,2)` | `close > bb_mid(20,2)` | 20 | up | 40 | — | p.2 headline rule, decomposed: band-touch component alone |
| `sma200_only` | `close > sma(200)` | `close < sma(200)` | 20 | up | — | — | p.2 headline rule, decomposed: 200MA gate alone |
| `headline_conjunction` | `close > sma(200) and close < bb_lower(20,2)` | `close > bb_upper(20,2)` | 20 | up | 40 | — | p.2, headline entry logic, verbatim |
| `zscore_oversold_band` | `(close - bb_mid(20,2)) / ((bb_upper(20,2) - bb_mid(20,2)) / 2) < -0.5 and (close - bb_mid(20,2)) / ((bb_upper(20,2) - bb_mid(20,2)) / 2) > -2` | `close > bb_mid(20,2)` | 20 | up | 20 | — | p.5, z-score banded entry `\|0.5\| < z < \|2\|`, oversold/long half |
| `zscore_extreme_stopout` | `(close - bb_mid(20,2)) / ((bb_upper(20,2) - bb_mid(20,2)) / 2) < -3` | `close > bb_mid(20,2)` | 20 | up | 20 | — | p.5, hard stop at `\|z\| > 3` |
| `bb_bandwidth_compression` | `(bb_upper(20,2) - bb_lower(20,2)) / bb_mid(20,2) < 0.05` | — | 20 | up | 20 | — | p.5, bandwidth < 5% => compression/consolidating |
| `bb_bandwidth_expansion` | `(bb_upper(20,2) - bb_lower(20,2)) / bb_mid(20,2) > 0.15` | — | 20 | up | 20 | — | p.5, bandwidth > 15% => high-vol trending regime |
| `boll50_band_touch` | `close < bb_lower(50,2)` | `close > bb_mid(50,2)` | 20 | up | 40 | — | p.5, BOLL(50,2) named alongside BOLL(20,2) |

**Lookahead guard: `passed` for every entry and every exit in every one of the 40 primary cells and
all 8 exploratory-sweep expressions.** No `UNVERIFIED` status was returned anywhere in this stream.

**Design notes carried over from the family declaration (see the script's module docstring):**

- The DSL has no `abs()` and comparisons cannot chain, so the note's symmetric `\|0.5\| < z < \|2\|`
  and `\|z\| > 3` conditions -- which describe mirror-image behavior on the overbought (short) side --
  are each tested only on the oversold/long construction, matching this whole study's long-only
  convention. The overbought/short mirror was not run; see §7.
- `zscore_extreme_stopout` is not a literal position-management stop-loss (the DSL's `stop_loss_pct`
  field is a price-percentage, not a z-score-conditioned exit). It tests the note's underlying
  empirical claim directly instead: under identical direction/exit/horizon/holding-cap to
  `zscore_oversold_band`, does buying an extreme deviation (z < -3) show a *weaker* edge than buying a
  moderate one? That is the falsifiable content of "a large deviation means a trend, not a rubber
  band."
- `bb_bandwidth_compression`/`_expansion` use the note's own 5%/15% thresholds on
  `(bb_upper - bb_lower) / bb_mid` -- **not** the prior study's `volatility_contraction` template,
  which used `bb_upper - bb_lower < close * 0.04`, a 4% threshold on a *different* denominator
  (`close`, not the mid band). Both are legitimate readings of "bandwidth"; they are not the same
  number and are not silently reconciled here.

---

## 2. What the note claims vs. what the data says

| # | Note claim | Verdict |
|---|---|---|
| 1 | p.2 headline: `price > 200MA AND price < lower BB` predicts a bounce | **Not supported after correction.** Reproduces the smoke test's raw p-values almost exactly (SPY p=0.0075, QQQ p=0.153), but q rises to 0.276 (SPY, the best case) once corrected across the real 40-test family. Positive edge on all 5 primary symbols (+0.076 to +0.133), but every one is `inconclusive`, and the strategy built on it loses to buy-and-hold on total return on all 5 (§4). |
| 2 | The 200MA gate is what makes the headline rule work (implicit in testing it as a conjunction) | **Rejected as stated.** The gate alone (`sma200_only`) shows *smaller* edges than the conjunction on 3/5 symbols and runs the wrong way (negative edge, `rejected` verdict) on IWM and XLV. The band-touch alone (`bb_lower_only`) shows edges of similar or larger magnitude to the conjunction on SPY and XLV. See §3 decomposition discussion -- the band touch, not the 200MA gate, is doing more of the work, and neither component individually clears significance. |
| 3 | z-score entry band `\|0.5\| < z < \|2\|` marks a good moderate-reversion entry | **Not supported -- edge runs negative on 4 of 5 symbols.** `zscore_oversold_band` is `rejected` (edge < 0, wrong direction) on SPY, QQQ, XLK, XLV, and merely flat (+0.002, `inconclusive`) on IWM. This is the cleanest negative result in the family: the band as literally specified does not show the up-bias the note's framing implies, on any primary symbol. |
| 4 | `\|z\| > 3` marks a trend, not a stretched rubber band, and should be avoided/stopped out of | **Cannot be confirmed or refuted -- underpowered everywhere.** `zscore_extreme_stopout`'s independent sample size is 12-29 across the five symbols, all under the harness's 30-observation floor. Where the raw numbers are visible at all, they run the *opposite* way from the note's caution (nominally large positive edges, e.g. XLV +0.239 p=0.0138, IWM +0.235), but with n this small that is not evidence of anything, in either direction. |
| 5 | BB bandwidth < 5% marks compression / consolidation | **No directional edge found (as expected -- see caveat).** All 5 symbols show edges near zero or `rejected`; none survive. The claim is inherently direction-agnostic (a breakout can go either way) and the harness's hit-rate statistic cannot test that directly. Descriptively, median 20-bar forward returns during compression are *smaller* than baseline on all 5 symbols (e.g. SPY 1.09% vs 1.25% baseline), consistent with "quiet regime" but not with an imminent, larger-than-usual breakout move in either direction -- if anything this argues against the "coiled spring" reading. |
| 6 | BB bandwidth > 15% marks a high-volatility trending regime | **Mixed, and regime-carried.** `rejected` (negative edge) on QQQ and XLK; `inconclusive` (small positive edge) on SPY and IWM; `underpowered` on XLV. Descriptively, median 20-bar forward returns during high bandwidth are *larger* in magnitude than baseline on SPY, IWM and XLV (e.g. SPY 3.86% vs 1.25% baseline) -- consistent with "bigger moves happen," which is a volatility claim, not a directional one. On QQQ and XLK the negative directional edge is substantially explained by two specific episodes: the 2000-2002 dot-com crash and the 2022 bear market both registered as high-bandwidth "trending" periods and both trended *down* (§5). |
| 7 | A BB(20,2) band touch works as an *exit*, not just an entry (p.9) | **Descriptively plausible, not independently tested as a hypothesis.** Every idea with an exit in this family uses a band touch as that exit (`bb_lower_only` and `boll50_band_touch` use the mid band; `headline_conjunction` uses the opposite/upper band). None of these strategies beat buy-and-hold on total return (§4), so a band-touch exit did not turn any of these entries into a market-beating strategy, but the harness has no machinery to isolate "this exit vs. a different exit on the identical entry" as its own corrected hypothesis, so this is a description of what happened under the exits chosen, not a formal test of the exit rule against an alternative. |
| 8 | BOLL(50,2) behaves like BOLL(20,2) (both named on p.5) | **No, weaker and noisier.** `boll50_band_touch`'s edges are smaller and flip sign more often than `bb_lower_only`'s (e.g. SPY: 20-period +0.075 vs 50-period -0.003; QQQ: +0.043 vs -0.037). Neither survives, but the 20-period band touch is the more internally consistent of the two (positive edge on all 5 symbols vs. 3 of 5 for the 50-period version). |

---

## 3. Primary family results

40 tests, `screen_alpha = 0.10`, `small_sample_threshold = 30`. **0 survivors.** Smallest q in the
whole family is 0.276 (SPY/`headline_conjunction` and XLV/`zscore_extreme_stopout`, tied).

### `bb_lower_only` — `close < bb_lower(20,2)`, exit `close > bb_mid(20,2)`, h=20

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.710 | 0.635 | +0.075 | 448 | 145 | 0.0697 | 0.5559 | inconclusive |
| QQQ | 0.663 | 0.619 | +0.043 | 338 | 112 | 0.3830 | 0.7429 | inconclusive |
| IWM | 0.655 | 0.588 | +0.066 | 391 | 115 | 0.1848 | 0.6149 | inconclusive |
| XLK | 0.646 | 0.607 | +0.038 | 333 | 116 | 0.4471 | 0.7429 | inconclusive |
| XLV | 0.670 | 0.594 | +0.076 | 382 | 115 | 0.1069 | 0.5559 | inconclusive |

### `sma200_only` — `close > sma(200)`, exit `close < sma(200)`, h=20

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.658 | 0.637 | +0.021 | 6150 | 335 | 0.4954 | 0.7429 | inconclusive |
| QQQ | 0.639 | 0.617 | +0.022 | 4877 | 268 | 0.4903 | 0.7429 | inconclusive |
| IWM | 0.574 | 0.595 | -0.021 | 4276 | 240 | 0.5542 | 0.7429 | **rejected** |
| XLK | 0.637 | 0.610 | +0.027 | 4824 | 264 | 0.4122 | 0.7429 | inconclusive |
| XLV | 0.571 | 0.596 | -0.025 | 4600 | 268 | 0.4184 | 0.7429 | **rejected** |

### `headline_conjunction` — `close > sma(200) and close < bb_lower(20,2)`, exit `close > bb_upper(20,2)`, h=20

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.768 | 0.634 | +0.133 | 211 | 87 | **0.0075** | 0.2764 | inconclusive |
| QQQ | 0.719 | 0.619 | +0.099 | 167 | 63 | 0.1529 | 0.5559 | inconclusive |
| IWM | 0.709 | 0.589 | +0.120 | 165 | 63 | 0.0539 | 0.5559 | inconclusive |
| XLK | 0.713 | 0.607 | +0.105 | 160 | 62 | 0.1182 | 0.5559 | inconclusive |
| XLV | 0.671 | 0.595 | +0.076 | 149 | 55 | 0.2730 | 0.7429 | inconclusive |

### `zscore_oversold_band` — `-2 < z < -0.5`, exit `close > bb_mid(20,2)`, h=20

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.617 | 0.635 | -0.018 | 1886 | 253 | 0.5572 | 0.7429 | **rejected** |
| QQQ | 0.586 | 0.619 | -0.033 | 1723 | 205 | 0.3150 | 0.7429 | **rejected** |
| IWM | 0.591 | 0.588 | +0.002 | 1640 | 206 | 0.9436 | 1.0000 | inconclusive |
| XLK | 0.584 | 0.607 | -0.023 | 1768 | 211 | 0.4814 | 0.7429 | **rejected** |
| XLV | 0.587 | 0.594 | -0.007 | 1753 | 215 | 0.8350 | 0.9543 | **rejected** |

### `zscore_extreme_stopout` — `z < -3`, exit `close > bb_mid(20,2)`, h=20

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.800 | 0.635 | +0.165 | 35 | 29 | 0.0843 | 0.5559 | **underpowered** |
| QQQ | 0.688 | 0.619 | +0.068 | 16 | 12 | 1.0000 | 1.0000 | **underpowered** |
| IWM | 0.824 | 0.588 | +0.235 | 17 | 15 | 0.1183 | 0.5559 | **underpowered** |
| XLK | 0.682 | 0.607 | +0.075 | 22 | 19 | 0.6402 | 0.7739 | **underpowered** |
| XLV | 0.833 | 0.594 | +0.239 | 24 | 21 | 0.0138 | 0.2764 | **underpowered** |

Every cell is `n_indep < 30`. No comparison against `zscore_oversold_band` can be made with any
confidence; see §2 row 4.

### `bb_bandwidth_compression` — `(upper-lower)/mid < 0.05`, h=20

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.639 | 0.635 | +0.004 | 3697 | 265 | 0.9492 | 1.0000 | inconclusive |
| QQQ | 0.651 | 0.619 | +0.032 | 1484 | 139 | 0.5412 | 0.7429 | inconclusive |
| IWM | 0.552 | 0.588 | -0.036 | 1280 | 130 | 0.4240 | 0.7429 | **rejected** |
| XLK | 0.606 | 0.607 | -0.001 | 1483 | 130 | 1.0000 | 1.0000 | **rejected** |
| XLV | 0.572 | 0.594 | -0.022 | 2988 | 226 | 0.4982 | 0.7429 | **rejected** |

### `bb_bandwidth_expansion` — `(upper-lower)/mid > 0.15`, h=20

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.678 | 0.635 | +0.044 | 317 | 32 | 0.5869 | 0.7573 | inconclusive |
| QQQ | 0.533 | 0.619 | -0.086 | 957 | 77 | 0.1273 | 0.5559 | **rejected** |
| IWM | 0.681 | 0.588 | +0.093 | 508 | 51 | 0.1999 | 0.6149 | inconclusive |
| XLK | 0.518 | 0.607 | -0.090 | 935 | 73 | 0.1501 | 0.5559 | **rejected** |
| XLV | 0.677 | 0.594 | +0.083 | 223 | 21 | 0.6578 | 0.7739 | **underpowered** |

### `boll50_band_touch` — `close < bb_lower(50,2)`, exit `close > bb_mid(50,2)`, h=20

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.633 | 0.636 | -0.003 | 442 | 75 | 1.0000 | 1.0000 | **rejected** |
| QQQ | 0.584 | 0.621 | -0.037 | 332 | 64 | 0.5200 | 0.7429 | **rejected** |
| IWM | 0.656 | 0.589 | +0.066 | 395 | 63 | 0.3707 | 0.7429 | inconclusive |
| XLK | 0.581 | 0.608 | -0.027 | 358 | 69 | 0.6244 | 0.7739 | **rejected** |
| XLV | 0.633 | 0.593 | +0.039 | 411 | 69 | 0.5404 | 0.7429 | inconclusive |

**Exploratory horizon sweep** (`mean_reversion_horizon_sweep.json`, 200 trials -- 8 expressions x 5
symbols x 5 horizons, separately BH-corrected, descriptive only): **0 discoveries at q <= 0.10.** For
`headline_conjunction` specifically, SPY's best horizon in the sweep is in fact 20 (p=0.0075, the
pre-declared one), but QQQ's best is 60 (p=0.0521, edge +0.132) and IWM/XLK/XLV's best sits between
5 and 20 with no horizon clearing significance for any symbol once corrected in its own 200-trial
ledger. The pre-declared horizon was not cherry-picked after the fact (it was fixed before this script
ran), and it happens to be close to optimal for SPY, but that is a coincidence the sweep exposes
rather than a confirmation -- QQQ's own best horizon is different, and neither survives its own
ledger regardless.

---

## 4. Strategy mechanics vs. buy-and-hold

Full history, `Costs(slippage_bps=5.0, commission_per_trade=0.0, notional=10000.0)`, closed trades
only for win-rate. **Not one of the 32 backtested ideaxsymbol combinations beats buy-and-hold on total
return.** (`bb_bandwidth_compression` and `bb_bandwidth_expansion` have no `exit`, only a 20-bar
holding cap, so they are included below; the two decomposition-only entries without any exit
(`sma200_only` does have an exit) are covered too.)

| idea | symbol | strat total ret | strat CAGR | strat Sharpe | strat max DD | exposure | trades | win rate | cost drag | bh total ret | bh Sharpe | beats bh (ret / Sharpe) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| bb_lower_only | SPY | 3.752 | 4.76% | 0.432 | -37.2% | 0.221 | 161 | 76.4% | -0.830 | 16.525 | 0.553 | No / No |
| bb_lower_only | QQQ | 1.208 | 2.94% | 0.253 | -56.9% | 0.222 | 118 | 74.6% | -0.277 | 13.014 | 0.493 | No / No |
| bb_lower_only | IWM | 0.563 | 1.72% | 0.189 | -43.6% | 0.245 | 122 | 70.5% | -0.203 | 5.503 | 0.420 | No / No |
| bb_lower_only | XLK | 2.360 | 4.49% | 0.344 | -44.0% | 0.225 | 120 | 74.2% | -0.428 | 10.479 | 0.470 | No / No |
| bb_lower_only | XLV | 1.030 | 2.60% | 0.283 | -32.0% | 0.224 | 118 | 74.6% | -0.254 | 5.578 | 0.472 | No / No |
| sma200_only | SPY | 7.189 | 6.48% | **0.591** | -30.5% | 0.744 | 112 | 29.7% | -0.966 | 16.525 | 0.553 | No / **Yes** |
| sma200_only | QQQ | 6.951 | 7.87% | **0.536** | -54.3% | 0.722 | 87 | 26.7% | -0.718 | 13.014 | 0.493 | No / **Yes** |
| sma200_only | IWM | 1.345 | 3.31% | 0.297 | -39.4% | 0.669 | 112 | 23.4% | -0.277 | 5.503 | 0.420 | No / No |
| sma200_only | XLK | 8.414 | 8.47% | **0.588** | -52.8% | 0.710 | 90 | 27.0% | -0.881 | 10.479 | 0.470 | No / **Yes** |
| sma200_only | XLV | 0.099 | 0.34% | 0.088 | -55.1% | 0.687 | 157 | 19.9% | -0.186 | 5.578 | 0.472 | No / No |
| headline_conjunction | SPY | 3.636 | 4.69% | 0.500 | -29.1% | 0.284 | 76 | 76.3% | -0.366 | 16.525 | 0.553 | No / No |
| headline_conjunction | QQQ | 2.983 | 5.18% | 0.450 | -23.0% | 0.257 | 57 | 71.4% | -0.232 | 13.014 | 0.493 | No / No |
| headline_conjunction | IWM | 1.631 | 3.77% | 0.368 | -44.2% | 0.269 | 59 | 76.3% | -0.160 | 5.503 | 0.420 | No / No |
| headline_conjunction | XLK | 3.754 | 5.82% | **0.519** | -24.9% | 0.250 | 58 | 75.4% | -0.281 | 10.479 | 0.470 | No / **Yes** |
| headline_conjunction | XLV | 0.646 | 1.82% | 0.242 | -28.5% | 0.211 | 52 | 65.4% | -0.088 | 5.578 | 0.472 | No / No |
| zscore_oversold_band | SPY | 1.955 | 3.29% | 0.300 | -46.4% | 0.351 | 357 | 74.5% | -1.268 | 16.525 | 0.553 | No / No |
| zscore_oversold_band | QQQ | 0.318 | 1.01% | 0.152 | -73.1% | 0.381 | 299 | 73.2% | -0.459 | 13.014 | 0.493 | No / No |
| zscore_oversold_band | IWM | 0.971 | 2.63% | 0.235 | -43.7% | 0.401 | 305 | 73.8% | -0.703 | 5.503 | 0.420 | No / No |
| zscore_oversold_band | XLK | 1.306 | 3.08% | 0.251 | -66.1% | 0.390 | 313 | 72.8% | -0.847 | 10.479 | 0.470 | No / No |
| zscore_oversold_band | XLV | 1.326 | 3.11% | 0.298 | -41.7% | 0.389 | 306 | 72.2% | -0.833 | 5.578 | 0.472 | No / No |
| zscore_extreme_stopout | SPY | 0.953 | 2.02% | 0.394 | -17.3% | 0.045 | 29 | 82.8% | -0.057 | 16.525 | 0.553 | No / No |
| zscore_extreme_stopout | QQQ | 0.276 | 0.89% | 0.188 | -12.9% | 0.027 | 12 | 83.3% | -0.015 | 13.014 | 0.493 | No / No |
| zscore_extreme_stopout | IWM | 0.310 | 1.04% | 0.224 | -10.2% | 0.034 | 15 | 86.7% | -0.020 | 5.503 | 0.420 | No / No |
| zscore_extreme_stopout | XLK | 0.166 | 0.56% | 0.114 | -25.7% | 0.043 | 19 | 68.4% | -0.022 | 10.479 | 0.470 | No / No |
| zscore_extreme_stopout | XLV | 0.412 | 1.26% | 0.326 | -17.1% | 0.038 | 21 | 90.5% | -0.030 | 5.578 | 0.472 | No / No |
| bb_bandwidth_compression | SPY | 1.397 | 2.64% | 0.284 | -40.7% | 0.648 | 261 | 65.0% | -0.713 | 16.525 | 0.553 | No / No |
| bb_bandwidth_compression | QQQ | 1.137 | 2.81% | 0.310 | -27.6% | 0.405 | 133 | 63.9% | -0.304 | 13.014 | 0.493 | No / No |
| bb_bandwidth_compression | IWM | -0.092 | -0.37% | 0.027 | -41.3% | 0.405 | 127 | 54.0% | -0.122 | 5.503 | 0.420 | No / No |
| bb_bandwidth_compression | XLK | 1.981 | 4.04% | 0.448 | -22.4% | 0.378 | 125 | 64.8% | -0.397 | 10.479 | 0.470 | No / No |
| bb_bandwidth_compression | XLV | 1.172 | 2.85% | 0.301 | -42.8% | 0.664 | 220 | 59.4% | -0.533 | 5.578 | 0.472 | No / No |
| bb_bandwidth_expansion | SPY | 0.924 | 1.97% | 0.234 | -33.5% | 0.080 | 32 | 65.6% | -0.063 | 16.525 | 0.553 | No / No |
| bb_bandwidth_expansion | QQQ | -0.657 | -3.83% | -0.082 | -86.6% | 0.231 | 76 | 46.1% | -0.027 | 13.014 | 0.493 | No / No |
| bb_bandwidth_expansion | IWM | 1.341 | 3.31% | 0.288 | -39.9% | 0.163 | 51 | 70.6% | -0.123 | 5.503 | 0.420 | No / No |
| bb_bandwidth_expansion | XLK | -0.537 | -2.75% | -0.047 | -77.8% | 0.215 | 71 | 49.3% | -0.034 | 10.479 | 0.470 | No / No |
| bb_bandwidth_expansion | XLV | 0.740 | 2.03% | 0.266 | -25.4% | 0.063 | 21 | 61.9% | -0.037 | 5.578 | 0.472 | No / No |
| boll50_band_touch | SPY | 0.878 | 1.90% | 0.213 | -39.1% | 0.180 | 69 | 72.5% | -0.134 | 16.525 | 0.553 | No / No |
| boll50_band_touch | QQQ | 0.022 | 0.08% | 0.094 | -62.5% | 0.192 | 55 | 74.5% | -0.058 | 13.014 | 0.493 | No / No |
| boll50_band_touch | IWM | -0.148 | -0.61% | 0.036 | -58.7% | 0.212 | 55 | 72.7% | -0.048 | 5.503 | 0.420 | No / No |
| boll50_band_touch | XLK | 0.628 | 1.78% | 0.188 | -45.9% | 0.205 | 58 | 74.1% | -0.097 | 10.479 | 0.470 | No / No |
| boll50_band_touch | XLV | 0.465 | 1.40% | 0.179 | -36.6% | 0.194 | 56 | 69.6% | -0.084 | 5.578 | 0.472 | No / No |

**On the "real forward-return edge, real underperformance" tension the assignment names directly.**
`headline_conjunction` on SPY: total return 3.636x vs buy-and-hold 16.525x over the full 1993-2026
history, at 28.4% exposure -- meaning the strategy was **out of the market roughly 72% of the time**,
and even during its 28% in-market window it did not compound to match a fully-invested position. (This
stream's own exit choice -- `close > bb_upper(20,2)`, 40-bar cap -- is not necessarily the exact
mechanics behind the informal smoke-test figures cited in the assignment, SPY total return 2.07 vs
16.59; that exact spec was not handed to this stream. The qualitative shape -- a modest multiple
against a large buy-and-hold multiple, driven by low exposure -- reproduces regardless of the precise
exit chosen.) **This is not evidence the rule is worthless and it is not evidence it is useful.** A
low-exposure rule that shows a genuine, if statistically inconclusive, forward-return edge *while in a
position* can still lose to buy-and-hold on total return purely from time out of the market, in a
34-year window where the market's unconditional expected return was strongly positive. Total return is
the wrong lens for judging a rule that is deliberately selective about when to hold; exposure-adjusted
metrics (Sharpe, per-trade hit rate) are more informative, and even by that lens the rule does not
clearly win: Sharpe beats buy-and-hold on only 1 of the 5 symbols for `headline_conjunction` (XLK,
0.519 vs 0.470) and the p/q results in §3 say the entry's edge itself is not distinguishable from
sampling noise across the primary family. `sma200_only` (a 70-75%-exposure trend filter, not the
band-touch idea) beats buy-and-hold's Sharpe on 3 of 5 symbols precisely because it avoids the deepest
drawdowns, not because it captures more return -- max DD -30% to -55% vs buy-and-hold's much deeper
episodes (§5's drawdown context). **Neither of these Sharpe wins should be read as "the strategy is
better than buy-and-hold"; a strategy that is flat 25-70% of the time has a mechanically different risk
profile from one that is always invested, and Sharpe alone, on a partly-flat equity curve, is not a
substitute for that comparison.**

Cost drag (`total return at cost` minus `total return at zero cost`, re-simulated on the identical
signal sequence, per the harness docstring) is material for the highest-turnover ideas:
`zscore_oversold_band` traded 250-360 times per symbol and paid -46 to -127 percentage points of total
return to slippage alone. On SPY specifically: net total return 195.5%, cost drag -126.8pp, implying a
zero-cost total return of roughly 322.3% -- costs alone consumed close to 40% of the gross gain across
357 round trips at 5bps each way. `zscore_extreme_stopout`, by contrast, trades so rarely (12-29 times)
that cost drag is negligible (-1.5pp to -5.7pp), but the sample is too small to trust the resulting
numbers either way.

---

## 5. Regime breakdown

Windows: dotcom_2000_2002, bull_2003_2007, qe_bull_2009_2019, covid_2020_2021, bear_2022,
recent_2023_now (same six windows used across this study).

**`headline_conjunction` is structurally almost silent in bear markets, by construction.** The rule
requires `close > sma(200)` *and* an oversold band touch simultaneously -- a combination that a
sustained downtrend (price under its 200-day average) makes rare. Trade counts by window, all 5
symbols:

| window | SPY | QQQ | IWM | XLK | XLV |
|---|---|---|---|---|---|
| dotcom_2000_2002 | 0 | 0 | 3 | 0 | 2 |
| bull_2003_2007 | 13 | 10 | 9 | 7 | 10 |
| qe_bull_2009_2019 | 28 | 27 | 29 | 28 | 23 |
| covid_2020_2021 | 5 | 6 | 4 | 4 | 5 |
| **bear_2022** | **0** | **0** | **0** | **0** | **0** |
| recent_2023_now | 9 | 7 | 7 | 9 | 4 |

**Zero trades on all five symbols during 2022.** The rule cannot fire in a bear regime where price
sits below its 200-day average for most of the year -- which is exactly the regime the 200MA gate is
designed to filter out, so this is expected behavior, not a bug, but it also means the aggregate 40-
test edge is **overwhelmingly carried by the 2009-2019 QE bull window** (23-29 trades per symbol,
roughly half of every symbol's total trade count) and to a lesser extent 2003-2007. A rule this
concentrated in one 11-year bull regime is not well described by its full-history aggregate p-value as
if it were evenly sampled across market conditions.

**`bb_bandwidth_expansion`'s negative aggregate edge on QQQ and XLK is regime-carried.** Both symbols'
strategy total return is negative overall (QQQ -65.7%, XLK -53.7%), and both losses concentrate in two
windows specifically:

- dotcom_2000_2002: QQQ -69.2% (86.6% exposure, 31 trades), XLK -64.0% (80.1% exposure, 29 trades)
- bear_2022: QQQ -36.3% (66.9% exposure, 8 trades), XLK -31.2% (66.9% exposure, 8 trades)

High BB bandwidth correctly flags "high volatility, trending" on QQQ and XLK in both episodes -- the
regime detector is not wrong about volatility -- but both episodes trended *down*, and the idea's
`direction="up"` framing pays for that. On SPY, IWM and XLV, where 2000-2002 and 2022 losses were
milder, the same idea shows small positive edges instead. This is the clearest within-family
illustration of the note's own ambiguity: "high volatility trending regime" says nothing about which
way the trend runs, and a directional test built on top of it will only look good in whichever windows
happen to trend the tested direction.

**`sma200_only` and `bb_lower_only` behave more evenly across regimes** (both have nonzero trade
counts in every window, including 2022, since neither requires the conjunction), though `sma200_only`'s
exposure swings from ~3% in dotcom_2000_2002 (correctly mostly out of the market) to 70-80% in the
2009-2019 bull, which is the mechanism, not a coincidence -- it is a trend filter doing exactly what a
trend filter does.

**Buy-and-hold drawdown context** (descriptive, `app.backtest.drawdown.profile`, no baseline/no
correction): SPY's single worst episode is the 2007-2009 financial crisis, -56.5% peak-to-trough
(2007-10-09 to 2009-03-09); its 2000-2002 dot-com decline is second-worst at -49.1%. QQQ's worst by a
wide margin is the 2000-2002 dot-com decline itself, -83.0%. None of this stream's rules were exposed
to the worst of that QQQ episode (`headline_conjunction`: 0 trades on QQQ in dotcom_2000_2002, per the
window table above), which is again the 200MA/oversold-conjunction structurally avoiding the deepest
bear-market entries -- consistent with, but not independent confirmation of, the exposure story above.
Note this also means none of this stream's rules were tested against SPY's 2007-2009 crash as its own
labeled window (the shared `WINDOWS` list treats 2003-2007 and 2009-2019 as separate bull windows and
has no standalone 2007-2009 slice), so the single deepest SPY drawdown in the whole history is present
in the aggregate full-history statistics in §3 but not broken out on its own in §5.

---

## 6. Replication

**Not run.** Zero of the 40 primary tests reached `verdict == "survived"` (all were `inconclusive`,
`rejected`, or `underpowered`), and the brief is explicit that replication runs only for primary
survivors, run separately with its own BH correction, never folded into the primary family. No
`mean_reversion_replication.json` was written.

---

## 7. What this cannot tell you

- **The shared regime windows have a gap that includes SPY's single worst drawdown.** The harness's
  `WINDOWS` list (used identically by every stream in this study) runs `bull_2003_2007` through
  2007-10-31 and picks back up with `qe_bull_2009_2019` on 2009-04-01 -- the roughly 17 months between
  them, which contains the entire 2007-2009 financial crisis (SPY's deepest drawdown of the whole
  1993-2026 history, -56.5%), falls in none of the six labeled windows. Every full-history number in
  §3 and §4 includes that period; the regime breakdown in §5 cannot show it on its own, because there
  is no window that isolates it. This is a property of the shared window list, not specific to this
  stream's ideas, but it means "carried by one regime" claims in §5 should be read as "carried by one
  *labeled* regime" -- the unlabeled 2007-2009 gap is folded into whichever of its neighbors' trades
  spilled into it, or into neither.
- **Overlapping windows, one historical path.** Every `n_independent` above already discards
  overlapping 20-bar forward windows, but the independent subset is still drawn from one realized
  sequence of US large-cap and small-cap history. `headline_conjunction`'s 87 "independent" SPY
  triggers are 87 non-overlapping slices of the *same* 1993-2026 path, concentrated (§5) in one bull
  regime -- not 87 draws from different market universes.
- **Instrument correlation.** SPY, QQQ and XLK are three views of the same large-cap-growth-tilted
  complex; a rule that shows a positive edge on all three (as `headline_conjunction` does, +0.133 /
  +0.099 / +0.105) is not three independent confirmations. IWM and XLV were included specifically to
  probe this (assignment question 2): the edge does show up on both (IWM +0.120, XLV +0.076), so this
  is not purely a large-cap-growth artifact on the raw-edge evidence, but none of the five, including
  IWM and XLV, clears correction, so "shows up everywhere but survives nowhere" is the honest summary.
- **The z-score and stop-out claims were tested one-sided only.** The note's bands are symmetric
  (oversold *and* overbought, long *and* implicitly short); this stream tested only the oversold/long
  half on every primary symbol, for the reasons in §1. A reader should not read "the oversold band
  showed a negative edge on 4 of 5 symbols" as "the z-score concept is refuted" -- the overbought/short
  construction was never run.
- **The bandwidth-regime claims are inherently directional tests of a direction-agnostic concept.**
  "Compression precedes a breakout" and "wide bands mean a trending regime" do not, on their own, say
  which way price moves next; this stream's hit-rate machinery can only measure "up," so the negative
  results in §2 rows 5-6 mean "no up-bias was found," not "the regime claim is false." The median-
  forward-return numbers reported alongside are an attempt to keep that distinction visible rather than
  overclaiming a directional finding the statistic cannot support.
- **Survivorship in ETF constituents.** SPY/QQQ/IWM/XLK/XLV are today's index/sector membership, not a
  point-in-time reconstruction; sector and style composition, especially XLK's and XLV's, has drifted
  over 25+ years.
- **A backtest is not a forecast.** Everything above describes what these specific rules did on this
  specific stored history under this project's pre-registration and correction discipline. It is not a
  claim about what any rule will do going forward, and nothing here is investment advice or a
  recommendation to buy, hold, or sell any of the five primary or thirteen replication-universe
  instruments named in this study.

---

## 8. Anything not expressible, and what was done instead

- **`\|z\|` and `\|z\| > 3` as written (both-sided).** The DSL has no `abs()`, and comparisons cannot
  chain (`1 < rsi(14) < 2` is a syntax error by design). A true `\|0.5\| < z < \|2\|` reads as "z is in
  (0.5, 2) OR z is in (-2, -0.5)" -- an `or` of two ranges whose two halves have *opposite* directional
  implications under mean-reversion logic (positive z expects a pullback down, negative z expects a
  bounce up). The harness's hit-rate statistic has one direction per idea, so folding both halves into
  one test would average a real signal against its own mirror image. Instead of that, or of spending
  two more family slots on the short/overbought halves, this stream tested only the oversold/long
  construction of each -- consistent with this whole study's long-only convention, but a real, stated
  scope limit, not a silent substitution.
- **A z-score-conditioned stop-loss.** The `Idea.stop_loss_pct` field the harness exposes is a fixed
  price percentage, not an expression; there is no way to say "exit if z crosses 3" through that field.
  An exit *expression* referencing z was available in principle (`exit="... or z < -3"`), but adding it
  to an idea already in the family would have required a second, near-duplicate idea sharing the same
  entry (and therefore the same event-study p-value) purely to compare two exit variants -- spending a
  correction-family slot on a strategy-mechanics-only question. `zscore_extreme_stopout` instead tests
  the note's underlying empirical claim directly (§1), which is the falsifiable content of the
  heuristic even though it is not a literal backtest of a stop-loss mechanism.
- **Volume-based confirmation, ADX, Stochastic, Ichimoku, Fibonacci, order flow, divergence.** Not in
  the indicator registry (or, for divergence, not expressible without a lookback-extremum operator);
  none of these were needed for this stream's assigned claims, but they are noted here per the brief's
  instruction to report DSL gaps encountered rather than silently working around them.
- **A true magnitude-of-move statistic for the bandwidth-regime claims.** The harness reports a hit
  rate (P(20-bar forward return > 0)) and a median forward return, but no volatility-of-forward-return
  statistic. The median-return comparison in §2/§5 is the closest available proxy and is reported as
  such, not as a formal test.

---

## Application notes

- **No new bug found.** All 40 primary lookahead guards and all 8 exploratory-sweep expressions
  returned `passed`; no `UNVERIFIED` status anywhere in this stream's run.
- **The prior study's documented `OverflowError` in `app.backtest.scan.binomial_p_value` did not
  reproduce, and the fix is visible in the current source.** The prior QQQ/SOXX/IGV report (this same
  date) found that `close > sma(200)` at horizon 1 with `n_independent` in the thousands crashed the
  whole scan with an unhandled `OverflowError` from `math.comb` overflowing a Python-to-float
  conversion. This stream's exploratory sweep runs the *identical* reproduction case --
  `close > sma(200)`, horizon 1, QQQ, `n_independent = 4896`, the exact count cited in the prior
  report -- and it completed normally (p=0.4655, no exception). Reading
  `backend/app/backtest/scan.py::binomial_p_value` confirms why: the function's docstring and
  implementation now compute every pmf term in log space via `math.lgamma` specifically to avoid this
  overflow, and the docstring explicitly names `close > sma(200)` at horizon 1 as the motivating case.
  This looks like the prior study's reported bug has since been fixed in this codebase; noted here as a
  finding, not claimed as this stream's own fix (no application source was modified by this study).
