# Momentum oscillators — MACD, RSI, and confluence

Stream `momentum`. Run 2026-08-11. All numbers below are copy-pasteable from
`docs/research/strategy-lab/data/momentum_primary.json`,
`docs/research/strategy-lab/data/momentum_horizon_sweep.json`, and
`docs/research/strategy-lab/data/momentum_divergence_diagnostic.json`. The scripts that produced
them are `docs/research/strategy-lab/scripts/momentum.py` and
`docs/research/strategy-lab/scripts/momentum_divergence_diagnostic.py`. No production state was
touched: `bars_frame` reads `app.market.store.ensure_series` against the existing cache, nothing
calls `app.thesis.loop`, and `data/store/thesis.sqlite` / `data/store/ledger.sqlite` were never
opened.

**Nothing here is investment advice.** Every result below describes what these conditions did
historically on stored price history, with sample sizes and multiple-testing corrections attached.
None of it says an instrument should be bought or sold.

---

## 1. What was tested

Nine ideas, declared as one family before anything ran, tested on all five primary symbols
(`SPY QQQ IWM XLK XLV`) — 45 primary tests, one Benjamini-Hochberg ledger, screening threshold
`q <= 0.10`.

| key | entry | exit | horizon | dir | cap | stop | note line |
|---|---|---|---|---|---|---|---|
| `macd_signal_cross` | `macd_macd(12,26,9) crosses_above macd_signal(12,26,9)` | `macd_macd(12,26,9) crosses_below macd_signal(12,26,9)` | 10 | up | — | — | p.6, MACD signal-line crossover |
| `macd_zero_cross` | `macd_macd(12,26,9) crosses_above 0` | `macd_macd(12,26,9) crosses_below 0` | 10 | up | — | — | p.6, "zero line = momentum midpoint" |
| `ma_crossover_matched` | `ema(10) crosses_above ema(20)` | `ema(10) crosses_below ema(20)` | 10 | up | — | — | p.6, matched comparator for "MACD crossover is faster but more falsy than MA crossover" |
| `rsi_oversold_reversion` | `rsi(14) < 30` | `rsi(14) > 50` | 5 | up | 10 | 15% | p.7, RSI oversold/overbought reading (mechanics identical to prior study's `oversold_bounce`) |
| `rsi_regime_gate` | `rsi(14) crosses_above 60` | `rsi(14) crosses_below 40` | 10 | up | — | — | p.2, RSI as "trend strength regime" |
| `trend_gate_sma200` | `close > sma(200)` | `close < sma(200)` | 10 | up | — | — | p.2, trend gate alone — component of `confluence_macd_trend` |
| `confluence_macd_trend` | `macd_macd(12,26,9) crosses_above macd_signal(12,26,9) and close > sma(200)` | `macd_macd(12,26,9) crosses_below macd_signal(12,26,9)` | 10 | up | — | — | p.6/p.8/p.9, "Confluence metric" / "Golden Alignment" (MACD × 200-day trend) |
| `trend_gate_ema20_sma50` | `ema(20) > sma(50)` | `ema(20) crosses_below sma(50)` | 10 | up | — | — | p.4, intermediate trend gate alone — component of `confluence_rsi_trend` |
| `confluence_rsi_trend` | `rsi(14) crosses_above 60 and ema(20) > sma(50)` | `rsi(14) crosses_below 40` | 10 | up | — | — | p.6/p.8/p.9, "Confluence metric" / "Golden Alignment" (RSI regime × intermediate trend) |

`n = 9 ideas x 5 symbols = 45`. All 45 cells' entry **and** exit expressions passed the lookahead
guard (`app.backtest.guards.check`, status `passed`) — no `UNVERIFIED` anywhere in this family.

Windows used for the regime breakdown (Section 5), identical to the brief's example and to the
other streams for comparability:

```
dotcom_2000_2002  2000-01-01 .. 2002-12-31
bull_2003_2007    2003-01-01 .. 2007-10-31
qe_bull_2009_2019 2009-04-01 .. 2019-12-31
covid_2020_2021   2020-01-01 .. 2021-12-31
bear_2022         2022-01-01 .. 2022-12-31
recent_2023_now   2023-01-01 .. present
```

---

## 2. What the note claims vs. what the data says

| # | Note claim | Encoded as | Verdict |
|---|---|---|---|
| 1 | "MACD crossover" is a single, well-defined signal-line trigger (p.6) | `macd_signal_cross` vs `macd_zero_cross` | **Not one thing.** The two readings have opposite speed rankings against a matched MA crossover — see Q1 below. Conflating them, as the note does, produces an answer that depends entirely on which one you meant. |
| 2 | "MACD crossover is faster but more falsy than MA crossover" (p.6, verbatim) | `macd_signal_cross` vs `ma_crossover_matched`, same horizon (10) | **Faster: yes, decisively, for the signal-line reading.** ~10.0–11.0 triggers/yr vs ~5.2–5.4/yr, on every one of 5 symbols; ~12–13 bars held vs ~28–32. **More falsy: not supported.** Win rate is essentially tied (41.96% avg vs 39.8% avg — MACD-signal *slightly* higher), and neither rule's event-study edge survives correction on any symbol. See Q1. |
| 3 | RSI<30 is an oversold buy signal (p.7) | `rsi_oversold_reversion` | **Inconclusive on every symbol, none survive correction.** Directionally positive edge on all 5 (+0.033 to +0.145), including a raw p=0.017 on XLV, but q=0.39 after BH — underneath the 0.10 screen. As a strategy it is a net loser gross of return on 2 of 5 symbols (XLK, XLV) despite decent win rates (56–72%), because average losses (stop-outs, 10-bar-cap exits at a loss) outweigh average wins. |
| 4 | High RSI reads as a strong-trend regime worth joining, not exhaustion (p.2) | `rsi_regime_gate` | **Inconclusive, mixed sign.** Positive edge on SPY/QQQ/XLK (+0.001 to +0.032), negative on IWM/XLV (−0.021, −0.035). No survivor. See Q3. |
| 5 | Stacking conditions ("Confluence metric" / "Golden Alignment") improves entries (p.6, p.8, p.9) | `confluence_macd_trend`, `confluence_rsi_trend` vs their components tested alone | **No support, and no consistent direction either.** Both confluence ideas shrink the independent sample substantially and reliably (26–32% vs the trigger alone, 58–68% vs the trend gate alone). The hit-rate effect of stacking is inconsistent across symbols — better than both components on some, worse than both on others — which is itself evidence against a real effect: a genuine improvement should not scatter randomly in sign. See Q2. |
| 6 | Bullish/bearish divergence between price and MACD signals a possible trend change (p.6, contents item 1b) | **Not expressible in the DSL** | Not tested in the corrected family. A separate, explicitly descriptive, non-DSL diagnostic is reported in Section 8 — it is suggestive in the expected direction but carries no p-value and must not be read as a finding. |

---

## 3. Primary family results — full grid

`q` is the Benjamini-Hochberg-corrected value across all 45 cells. `n_indep` is the
independent-window count `app.backtest.forward.independent_count` reports, not the raw trigger
count. Every cell's guard status is `passed` (omitted from the table for space; see Section 1).

### macd_signal_cross (h=10, up)

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.601 | 0.602 | −0.0006 | 367 | 315 | 0.9542 | 0.9985 | inconclusive |
| QQQ | 0.581 | 0.588 | −0.0068 | 278 | 245 | 0.7954 | 0.9985 | rejected |
| IWM | 0.567 | 0.560 | +0.0066 | 264 | 229 | 0.8419 | 0.9985 | inconclusive |
| XLK | 0.584 | 0.579 | +0.0055 | 292 | 250 | 0.8982 | 0.9985 | inconclusive |
| XLV | 0.558 | 0.559 | −0.0006 | 275 | 240 | 1.0000 | 1.0000 | rejected |

### macd_zero_cross (h=10, up)

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.674 | 0.601 | +0.0731 | 133 | 124 | 0.0984 | 0.9985 | inconclusive |
| QQQ | 0.645 | 0.588 | +0.0569 | 108 | 102 | 0.2684 | 0.9985 | inconclusive |
| IWM | 0.685 | 0.560 | +0.1252 | 112 | 98 | 0.0143 | 0.3912 | inconclusive |
| XLK | 0.568 | 0.578 | −0.0106 | 119 | 111 | 0.8478 | 0.9985 | rejected |
| XLV | 0.622 | 0.559 | +0.0628 | 119 | 112 | 0.1827 | 0.9985 | inconclusive |

### ma_crossover_matched (h=10, up)

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.609 | 0.601 | +0.0080 | 175 | 159 | 0.8715 | 0.9985 | inconclusive |
| QQQ | 0.566 | 0.588 | −0.0216 | 144 | 133 | 0.5975 | 0.9985 | rejected |
| IWM | 0.650 | 0.560 | +0.0897 | 138 | 127 | 0.0394 | 0.5909 | inconclusive |
| XLK | 0.567 | 0.578 | −0.0108 | 142 | 135 | 0.8620 | 0.9985 | rejected |
| XLV | 0.547 | 0.559 | −0.0122 | 150 | 140 | 0.8650 | 0.9985 | rejected |

### rsi_oversold_reversion (h=5, up, cap=10, stop=15%)

| symbol | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|
| SPY | 0.648 | 0.571 | +0.0766 | 125 | 57 | 0.2844 | 0.9985 | inconclusive |
| QQQ | 0.639 | 0.564 | +0.0745 | 108 | 52 | 0.3305 | 0.9985 | inconclusive |
| IWM | 0.573 | 0.540 | +0.0331 | 164 | 65 | 0.7094 | 0.9985 | inconclusive |
| XLK | 0.636 | 0.555 | +0.0804 | 118 | 58 | 0.2350 | 0.9985 | inconclusive |
| XLV | 0.685 | 0.540 | +0.1448 | 165 | 65 | 0.0174 | 0.3912 | inconclusive |

### rsi_regime_gate (h=10, up)

| symbol | edge | n_indep | p | q | verdict |
|---|---|---|---|---|---|
| SPY | +0.0316 | 289 | 0.2800 | 0.9985 | inconclusive |
| QQQ | +0.0014 | 223 | 1.0000 | 1.0000 | inconclusive |
| IWM | −0.0206 | 209 | 0.5780 | 0.9985 | rejected |
| XLK | +0.0174 | 222 | 0.6835 | 0.9985 | inconclusive |
| XLV | −0.0345 | 227 | 0.3161 | 0.9985 | rejected |

### trend_gate_sma200 (h=10, up — component alone)

| symbol | edge | n_indep | p | q | verdict |
|---|---|---|---|---|---|
| SPY | +0.0095 | 652 | 0.6031 | 0.9985 | inconclusive |
| QQQ | +0.0134 | 516 | 0.5321 | 0.9985 | inconclusive |
| IWM | −0.0193 | 462 | 0.4254 | 0.9985 | rejected |
| XLK | +0.0155 | 509 | 0.4728 | 0.9985 | inconclusive |
| XLV | −0.0174 | 512 | 0.4492 | 0.9985 | rejected |

### confluence_macd_trend (h=10, up — macd_signal_cross ∧ trend_gate_sma200)

| symbol | edge | n_indep | p | q | verdict |
|---|---|---|---|---|---|
| SPY | +0.0186 | 233 | 0.5474 | 0.9985 | inconclusive |
| QQQ | −0.0077 | 175 | 0.9388 | 0.9985 | rejected |
| IWM | −0.0180 | 155 | 0.6861 | 0.9985 | rejected |
| XLK | +0.0165 | 182 | 0.7080 | 0.9985 | inconclusive |
| XLV | −0.0348 | 166 | 0.3900 | 0.9985 | rejected |

### trend_gate_ema20_sma50 (h=10, up — component alone)

| symbol | edge | n_indep | p | q | verdict |
|---|---|---|---|---|---|
| SPY | −0.0073 | 606 | 0.7400 | 0.9985 | rejected |
| QQQ | +0.0020 | 477 | 0.9259 | 0.9985 | inconclusive |
| IWM | −0.0228 | 443 | 0.3387 | 0.9985 | rejected |
| XLK | +0.0046 | 466 | 0.8513 | 0.9985 | inconclusive |
| XLV | −0.0210 | 469 | 0.3772 | 0.9985 | rejected |

### confluence_rsi_trend (h=10, up — rsi_regime_gate ∧ trend_gate_ema20_sma50)

| symbol | edge | n_indep | p | q | verdict |
|---|---|---|---|---|---|
| SPY | +0.0101 | 252 | 0.7970 | 0.9985 | inconclusive |
| QQQ | +0.0082 | 190 | 0.8830 | 0.9985 | inconclusive |
| IWM | −0.0402 | 173 | 0.3195 | 0.9985 | rejected |
| XLK | +0.0089 | 184 | 0.8814 | 0.9985 | inconclusive |
| XLV | −0.0520 | 191 | 0.1663 | 0.9985 | rejected |

**Family result: 45/45 tests, 0 survivors at q ≤ 0.10.** No cell fell under the
`SMALL_SAMPLE_THRESHOLD = 30` independent-observation floor, so no verdict here is `underpowered` —
every inconclusive/rejected verdict reflects a real screen, not a power problem.

---

## 4. Strategy mechanics vs. buy-and-hold

Full history per symbol, `Costs(slippage_bps=5.0, commission_per_trade=0.0, notional=10000.0)`.
**Every one of the 45 idea/symbol combinations trails buy-and-hold on total return.** No exceptions.

| idea | symbol | total return | CAGR | Sharpe | max DD | trades | win rate | cost drag | buy-hold TR |
|---|---|---|---|---|---|---|---|---|---|
| macd_signal_cross | SPY | 1.563 | 2.85% | 0.310 | −33.1% | 367 | 43.2% | −1.134 | 16.525 |
| macd_signal_cross | QQQ | 0.095 | 0.33% | 0.104 | −77.2% | 278 | 42.6% | −0.350 | 13.014 |
| macd_signal_cross | IWM | 1.754 | 3.95% | 0.330 | −49.3% | 264 | 39.9% | −0.830 | 5.503 |
| macd_signal_cross | XLK | 0.380 | 1.18% | 0.153 | −73.9% | 292 | 42.3% | −0.467 | 10.479 |
| macd_signal_cross | XLV | 0.531 | 1.56% | 0.195 | −35.5% | 275 | 41.8% | −0.485 | 5.578 |
| macd_zero_cross | SPY | 3.028 | 4.25% | 0.429 | −33.4% | 133 | 42.4% | −0.571 | 16.525 |
| macd_zero_cross | QQQ | 7.202 | 7.99% | 0.554 | −35.0% | 108 | 45.8% | −0.931 | 13.014 |
| macd_zero_cross | IWM | 1.959 | 4.24% | 0.353 | −34.7% | 112 | 42.3% | −0.349 | 5.503 |
| macd_zero_cross | XLK | 1.692 | 3.66% | 0.307 | −50.0% | 119 | 38.1% | −0.339 | 10.479 |
| macd_zero_cross | XLV | 0.853 | 2.26% | 0.256 | −33.0% | 119 | 40.7% | −0.233 | 5.578 |
| ma_crossover_matched | SPY | 2.346 | 3.67% | 0.383 | −38.5% | 175 | 39.1% | −0.638 | 16.525 |
| ma_crossover_matched | QQQ | 4.940 | 6.73% | 0.481 | −46.2% | 144 | 38.5% | −0.917 | 13.014 |
| ma_crossover_matched | IWM | 1.099 | 2.88% | 0.265 | −42.5% | 138 | 38.0% | −0.309 | 5.503 |
| ma_crossover_matched | XLK | 3.353 | 5.48% | 0.422 | −42.5% | 142 | 40.4% | −0.662 | 10.479 |
| ma_crossover_matched | XLV | 0.731 | 2.01% | 0.235 | −40.1% | 150 | 43.0% | −0.279 | 5.578 |
| rsi_oversold_reversion | SPY | 0.278 | 0.74% | 0.128 | −29.8% | 49 | 63.3% | −0.064 | 16.525 |
| rsi_oversold_reversion | QQQ | 0.876 | 2.33% | 0.257 | −29.0% | 43 | 72.1% | −0.080 | 13.014 |
| rsi_oversold_reversion | IWM | 0.085 | 0.31% | 0.084 | −45.2% | 53 | 54.7% | −0.107 | 5.503 |
| rsi_oversold_reversion | XLK | −0.123 | −0.47% | 0.026 | −42.2% | 49 | 61.2% | −0.042 | 10.479 |
| rsi_oversold_reversion | XLV | −0.143 | −0.56% | −0.022 | −44.7% | 53 | 56.6% | −0.045 | 5.578 |
| rsi_regime_gate | SPY | 1.994 | 3.33% | 0.364 | −46.2% | 97 | 40.6% | −0.303 | 16.525 |
| rsi_regime_gate | QQQ | 2.634 | 4.83% | 0.373 | −53.0% | 80 | 50.0% | −0.303 | 13.014 |
| rsi_regime_gate | IWM | 1.581 | 3.69% | 0.325 | −25.9% | 72 | 45.1% | −0.191 | 5.503 |
| rsi_regime_gate | XLK | 1.622 | 3.56% | 0.306 | −55.7% | 80 | 47.5% | −0.218 | 10.479 |
| rsi_regime_gate | XLV | 0.287 | 0.92% | 0.138 | −51.2% | 82 | 43.2% | −0.109 | 5.578 |
| trend_gate_sma200 | SPY | 7.189 | 6.48% | 0.591 | −30.5% | 112 | 29.7% | −0.966 | 16.525 |
| trend_gate_sma200 | QQQ | 6.951 | 7.87% | 0.536 | −54.3% | 87 | 26.7% | −0.718 | 13.014 |
| trend_gate_sma200 | IWM | 1.345 | 3.31% | 0.297 | −39.4% | 112 | 23.4% | −0.277 | 5.503 |
| trend_gate_sma200 | XLK | 8.414 | 8.47% | 0.588 | −52.8% | 90 | 27.0% | −0.881 | 10.479 |
| trend_gate_sma200 | XLV | 0.099 | 0.34% | 0.088 | −55.1% | 157 | 19.9% | −0.186 | 5.578 |
| confluence_macd_trend | SPY | 0.516 | 1.25% | 0.222 | −24.8% | 275 | 42.7% | −0.479 | 16.525 |
| confluence_macd_trend | QQQ | 0.101 | 0.35% | 0.085 | −40.6% | 194 | 42.5% | −0.235 | 13.014 |
| confluence_macd_trend | IWM | 0.222 | 0.77% | 0.133 | −25.4% | 180 | 38.5% | −0.240 | 5.503 |
| confluence_macd_trend | XLK | 0.443 | 1.34% | 0.186 | −34.0% | 211 | 42.4% | −0.338 | 10.479 |
| confluence_macd_trend | XLV | −0.066 | −0.25% | −0.002 | −36.9% | 186 | 39.2% | −0.191 | 5.578 |
| trend_gate_ema20_sma50 | SPY | 2.388 | 3.71% | 0.376 | −39.1% | 94 | 48.4% | −0.332 | 16.525 |
| trend_gate_ema20_sma50 | QQQ | 5.959 | 7.35% | 0.509 | −43.3% | 68 | 54.4% | −0.490 | 13.014 |
| trend_gate_ema20_sma50 | IWM | 1.485 | 3.54% | 0.303 | −36.7% | 70 | 40.6% | −0.179 | 5.503 |
| trend_gate_ema20_sma50 | XLK | 4.231 | 6.19% | 0.458 | −48.2% | 74 | 54.1% | −0.402 | 10.479 |
| trend_gate_ema20_sma50 | XLV | 0.911 | 2.38% | 0.261 | −43.3% | 79 | 46.2% | −0.156 | 5.578 |
| confluence_rsi_trend | SPY | 1.360 | 2.60% | 0.314 | −37.3% | 84 | 45.8% | −0.206 | 16.525 |
| confluence_rsi_trend | QQQ | 3.023 | 5.22% | 0.422 | −39.0% | 66 | 48.5% | −0.274 | 13.014 |
| confluence_rsi_trend | IWM | 1.114 | 2.91% | 0.287 | −29.5% | 62 | 45.9% | −0.134 | 5.503 |
| confluence_rsi_trend | XLK | 0.625 | 1.78% | 0.198 | −43.2% | 67 | 46.3% | −0.113 | 10.479 |
| confluence_rsi_trend | XLV | 0.180 | 0.60% | 0.110 | −46.2% | 73 | 41.7% | −0.089 | 5.578 |

Buy-and-hold, same windows: SPY 16.525x (33.5 yr), QQQ 13.014x (27.4 yr), IWM 5.503x (26.1 yr),
XLK 10.479x (27.6 yr), XLV 5.578x (27.6 yr). Buy-and-hold's own worst drawdown on each symbol —
descriptive, `app.backtest.drawdown.profile`, no baseline needed — is deeper than every rule's max
drawdown above: SPY −56.5% (2007-10 to 2009-03, recovered 2013-03), QQQ −83.0% (2000-03 to 2002-10,
recovered 2016-09), IWM −59.5% (2007-07 to 2009-03, recovered 2011-04), XLK −82.0% (2000-03 to
2002-10, recovered 2017-11), XLV −40.6% (2007-12 to 2009-03, recovered 2012-03). Every rule here
trades a large chunk of buy-and-hold's total return for a shallower drawdown — the same shape the
prior study found for `trend_following`, and true of every idea in this family, not just the trend
gates.

`macd_signal_cross` pays the largest cost drag of any idea in this family on 3 of 5 symbols — SPY
(−1.134, i.e. slippage alone erased more than the strategy's entire 1.563 total return would
otherwise have been), IWM (−0.830), and XLV (−0.485) — a direct consequence of it firing roughly
twice as often per year as any other idea in this family on every symbol (Q1 below has the full
trigger-frequency table). On QQQ and XLK it is not the worst: `macd_zero_cross` pays more on QQQ
(−0.931 vs macd_signal_cross's −0.350) and `trend_gate_sma200` pays more on XLK (−0.881 vs −0.467) —
those two ideas hold longer per trade but still trade often enough, on those two symbols specifically,
to out-drag the higher-frequency MACD signal cross.

---

## 5. Regime breakdown

Full window tables are in `data/momentum_primary.json` under
`per_symbol.<SYMBOL>.ideas.<idea>.windows`. Representative rows, SPY and QQQ, for the three ideas
central to Q1:

| idea | window | SPY strat TR | SPY b&h TR | QQQ strat TR | QQQ b&h TR |
|---|---|---|---|---|---|
| macd_signal_cross | dotcom_2000_2002 | −0.056 | −0.385 | −0.679 | −0.735 |
| macd_signal_cross | bull_2003_2007 | 0.231 | 0.701 | 0.172 | 1.161 |
| macd_signal_cross | qe_bull_2009_2019 | 0.613 | 2.874 | 1.184 | 5.788 |
| macd_signal_cross | covid_2020_2021 | 0.289 | 0.479 | 0.384 | 0.865 |
| macd_signal_cross | bear_2022 | 0.011 | −0.202 | −0.124 | −0.338 |
| macd_signal_cross | recent_2023_now | 0.159 | 1.011 | 0.239 | 1.704 |
| macd_zero_cross | dotcom_2000_2002 | −0.214 | −0.385 | −0.192 | −0.735 |
| macd_zero_cross | qe_bull_2009_2019 | 0.491 | 2.874 | 1.266 | 5.788 |
| macd_zero_cross | recent_2023_now | 0.648 | 1.011 | 0.743 | 1.704 |
| ma_crossover_matched | dotcom_2000_2002 | −0.203 | −0.385 | −0.267 | −0.735 |
| ma_crossover_matched | qe_bull_2009_2019 | 0.472 | 2.874 | 1.155 | 5.788 |
| ma_crossover_matched | recent_2023_now | 0.648 | 1.011 | 0.780 | 1.704 |

**No idea's aggregate is carried by a single regime.** All three families of ideas here (MACD,
matched MA, RSI, trend gates, confluence) show the same shape in every window checked: they lose
less than buy-and-hold in the crash windows (`dotcom_2000_2002`, `bear_2022`) and capture only a
fraction of buy-and-hold's gain in the long bull window (`qe_bull_2009_2019`) — the crash-window
outperformance is a drawdown-avoidance effect from being out of the market part of the time, not a
regime-specific edge. This is the same shape the prior study documented for
`trend_following`/`momentum_persistence` on QQQ/SOXX/IGV; nothing in this stream's five symbols
breaks that pattern.

---

## 6. Replication

**Not run.** Zero ideas survived the primary family (Section 3), and the brief is explicit:
replication runs only for primary survivors, never folded into the primary family. There is nothing
to replicate.

---

## Answering the three assigned questions

### Q1 — "Faster and more falsy" — yes or no, with numbers

Matched on the same horizon (10 bars), same symbols, same window, `macd_signal_cross` vs
`ma_crossover_matched`:

| metric | macd_signal_cross | macd_zero_cross | ma_crossover_matched |
|---|---|---|---|
| triggers/yr (SPY / QQQ / IWM / XLK / XLV) | 10.96 / 10.16 / 10.10 / 10.59 / 9.97 | 3.97 / 3.95 / 4.28 / 4.32 / 4.32 | 5.23 / 5.26 / 5.28 / 5.15 / 5.44 |
| avg bars held (SPY / QQQ / IWM / XLK / XLV) | 11.6 / 12.7 / 12.5 / 12.2 / 12.7 | 42.8 / 41.9 / 36.7 / 37.5 / 35.7 | 32.0 / 30.9 / 29.3 / 30.8 / 27.7 |
| win rate, avg across 5 symbols | 41.96% | 41.86% | 39.80% |
| event-study edge, avg across 5 symbols | +0.0008 | +0.0615 | +0.0106 |
| BH-corrected q, best (min) across 5 symbols | 0.998 | 0.391 | 0.591 |
| cost drag, avg across 5 symbols | −0.653 | −0.485 | −0.561 |

**Faster: yes, unambiguously, but only under the signal-line reading.** `macd_signal_cross` fires
roughly twice as often per year as `ma_crossover_matched` on every one of the five symbols (a
consistent ~2x ratio, not an average masking split results) and holds positions for roughly a third
as long. That is "faster" in every operational sense — signal frequency and holding period both
agree, and cost drag confirms it mechanically (more round trips, more slippage paid: −0.653 avg vs
−0.561 avg). Under the **zero-line reading**, the opposite holds: `macd_zero_cross` fires *less*
often than `ma_crossover_matched` (≈4/yr vs ≈5.2/yr) and holds positions *longer* (≈39 bars vs ≈30).
The note's single sentence describes two different mechanisms with opposite speed rankings against
the same comparator — "MACD crossover" is not one thing, and which one you mean changes the answer
to "faster" from yes to no.

**More falsy: not supported, on either reading, by win rate.** Win rate for `macd_signal_cross`
(41.96% average) is *slightly higher*, not lower, than `ma_crossover_matched`'s (39.80% average) —
the opposite of "more falsy" if win rate is the falsy metric. By the event-study hit-rate/edge
metric, `macd_signal_cross`'s average edge (+0.0008) is closer to zero than `ma_crossover_matched`'s
(+0.0106), which could be read as "MACD's edge is less reliably positive" — but neither rule's edge
survives BH correction on **any** of the 15 primary cells across these three ideas (best q is 0.391,
for `macd_zero_cross` on IWM), so "more falsy" cannot be asserted as a measured, corrected finding
either way. **Verdict: "faster" holds cleanly for the signal-line MACD reading and reverses for the
zero-line reading; "more falsy" does not show up in win rate and cannot be asserted with statistical
confidence in either direction on this data.**

### Q2 — Does confluence help or just shrink n?

| pair | trigger alone n_indep (SPY/QQQ/IWM/XLK/XLV) | gate alone n_indep | confluence n_indep | trigger edge (avg) | gate edge (avg) | confluence edge (avg) |
|---|---|---|---|---|---|---|
| MACD × 200-day trend | 315/245/229/250/240 | 652/516/462/509/512 | 233/175/155/182/166 | +0.0008 | +0.0003 | −0.0051 |
| RSI regime × EMA20/SMA50 | 289/223/209/222/227 | 606/477/443/466/469 | 252/190/173/184/191 | −0.0009 | −0.0089 | −0.0130 |

(edge averages above are the mean of the five per-symbol edges for that idea, all from Section 3)

**Sample size collapses sharply and consistently in both cases.** `confluence_macd_trend`'s
independent count is 26–32% smaller than `macd_signal_cross` alone and 64–68% smaller than
`trend_gate_sma200` alone, on every one of the five symbols. `confluence_rsi_trend`'s is 13–17%
smaller than `rsi_regime_gate` alone and 58–61% smaller than `trend_gate_ema20_sma50` alone, again on
every symbol. This part of the pattern is uniform: stacking a second condition always throws away a
large, predictable fraction of the triggers, regardless of which pair or which symbol.

**The hit-rate effect of stacking is not uniform, and that inconsistency is itself the answer.** Per
symbol, comparing confluence's edge against both of its components (all figures from Section 3):

| symbol | MACD trigger | 200d trend gate | MACD×trend confluence | RSI trigger | EMA/SMA gate | RSI×trend confluence |
|---|---|---|---|---|---|---|
| SPY | −0.0006 | +0.0095 | **+0.0186** (best) | +0.0316 | −0.0073 | +0.0101 (between) |
| QQQ | −0.0068 | +0.0134 | −0.0077 (worst) | +0.0014 | +0.0020 | **+0.0082** (best) |
| IWM | +0.0066 | −0.0193 | −0.0180 (between) | −0.0206 | −0.0228 | **−0.0402** (worst) |
| XLK | +0.0055 | +0.0155 | **+0.0165** (best) | +0.0174 | +0.0046 | +0.0089 (between) |
| XLV | −0.0006 | −0.0174 | **−0.0348** (worst) | −0.0345 | −0.0210 | **−0.0520** (worst) |

Confluence is the *best* of the three on SPY and XLK for the MACD pairing and on QQQ for the RSI
pairing (3 of 10 symbol/pairing cells); it is the *worst* of the three on XLV for both pairings and
on IWM for the RSI pairing (3 of 10 cells); the remaining 4 fall between its own two components. There
is no direction here that holds up across even a majority of cases — an average edge that is slightly
negative for both confluence ideas (−0.0051, −0.0130 vs their components' averages, all near zero) is
being produced by a symbol-by-symbol pattern that swings from "stacking helped the most" to "stacking
hurt the most" with no visible logic tying the swings to anything about the symbols (XLK
overlaps heavily with QQQ's large-cap-growth complex and gets opposite signs on the two pairings;
IWM and XLV, deliberately the least-correlated symbols in the universe, land on opposite ends too).
**Answer: confluence shrinks the sample substantially and predictably in every case tested (26–68%,
depending on which component); whether it helps the edge is not predictable and does not point in one
direction — on 3 of 10 cells it was the best of the three, on 3 of 10 the worst, with no pattern
distinguishing which.** None of the individual cells (component or confluence) survive BH correction,
so nothing here is a screened rejection of confluence as a concept — but a symbol-by-symbol coin flip
on edge, next to a reliable and substantial loss of sample size, is exactly the shape the brief warned
about: it is the setup in which reading one favorable cell (say, QQQ's RSI confluence at +0.0082) as
"confluence works" would have been mistaking noise on a shrunken sample for a discovery.

### Q3 — RSI: regime gate or reversion trigger?

Neither reading survives correction on this universe, and the two readings do not even agree with
each other in sign across symbols. `rsi_oversold_reversion` (RSI<30 reversion) has a **positive**
edge on all five primary symbols (+0.033 to +0.145) — directionally consistent, unlike the prior
study's SOXX/IGV result — but the smallest q achieved is 0.391 (XLV), still well above the 0.10
screen; as a strategy it is a **net loser** gross of return on XLK (−12.3%) and XLV (−14.3%) despite
win rates above 55% on both, because losing trades (stop-outs and cap-outs) run larger than winning
ones. `rsi_regime_gate` (high RSI as trend confirmation) is **mixed in sign** — positive on
SPY/QQQ/XLK, negative on IWM/XLV — and its best q is 1.000 (QQQ), the flattest result of any idea in
this family. **Direct answer for this universe: neither RSI framing clears this study's screen.** If
forced to rank them on the descriptive numbers alone, the reversion reading is the more
internally consistent one (same sign, same rough magnitude, on all five symbols) even though it is
further from significance and, mechanically, loses money on two of the five symbols once costs and
stops are applied — the regime-gate reading is directionally incoherent across this universe and
offers no consistent story to prefer it.

---

## 7. What this cannot tell you

- **Overlapping windows, one historical path.** Every `n_indep` above discards overlapping forward
  windows, but the independent subset is still drawn from one 26–34 year sequence of macro events per
  symbol, not from independent draws of market history. A rule with 300 "independent" 10-bar windows
  on SPY observed 300 non-overlapping slices of the same three-decade run, not 300 different market
  regimes.
- **Instrument correlation.** SPY, QQQ, and XLK are three views of the same large-cap-growth-tilted
  complex (QQQ and XLK both carry heavy mega-cap tech weight that SPY partially shares); a result that
  "holds" on all three is closer to one confirmation than three. IWM (small cap) and XLV (healthcare,
  deliberately not a tech proxy) are the two symbols in this universe that would actually break that
  pattern if it existed — in this family, nothing survived on any symbol, so the correlation caveat
  does not change any verdict, but a reader should not count SPY+QQQ+XLK agreement as three
  independent looks at the market.
- **Regime dependence beyond the six windows checked.** The six windows (Section 5) are themselves
  overlapping-history slices of the same underlying series, not independent economic regimes, and a
  rule that shows the same shape (loses less in crashes, captures a fraction of the gain in the long
  bull) across all six is showing "spends less time exposed," not "reads the regime correctly."
- **Two RSI readings, five symbols, mixed signs — this study cannot adjudicate the note's contradiction
  in general, only for these five ETFs over this history.** A different universe (individual equities,
  a period dominated by a different volatility regime, a shorter or longer horizon) could reasonably
  produce a different sign pattern for `rsi_regime_gate`; nothing here generalizes past this specific
  test.
- **Divergence could not be tested at all** — see Section 8. The descriptive diagnostic there is
  suggestive but has no p-value, no correction, and a small raw event count (17–27 bullish, 59–97
  bearish events per symbol over 26–34 years); it answers "what did a naive definition do
  historically," not "is this a real effect."
- **A backtest is not a forecast.** Every number above describes stored historical bars under this
  project's pre-registration, correction, and cost discipline. It says nothing about what any of these
  conditions will do going forward.
- **Survivorship in the ETF constituents.** SPY/QQQ/IWM/XLK/XLV are the current index/sector
  compositions, not point-in-time membership; sector and style weights have drifted over each symbol's
  25+ year history in ways this study does not adjust for.

---

## 8. What could not be expressed, and what was done instead

**Bullish/bearish divergence (note p.6, "Divergences btw price & MACD ⇒ signal of possible trend
change"; contents item 1b) is not expressible in this study's rule DSL.** Divergence requires
comparing the *extremum* of price against the *extremum* of an indicator across two separate swing
points — "price made a lower low while MACD made a higher low." The DSL (`quantlab.py` §4 /
BRIEF.md §4) has exactly two operators for relating two series over time, `crosses_above` and
`crosses_below`, and both are single-bar relational tests: they can express "A is now above/below B
at this bar," never "A's most recent local minimum is lower than its previous local minimum." There
is no lookback-extremum, no `argmin`/`argmax` over a window, and no way to bind "the value at the
last swing low" as a first-class quantity a comparison can reference. Faking it with a crossover
(e.g., treating a MACD signal-line cross as a divergence event) would silently test a different,
already-covered signal under the note's name — the brief instructs against exactly this, and this
report does not do it.

**What the DSL would need.** A new operator family in `app/rules/` (the expression grammar and its
evaluator) with roughly this shape: a `swing_low(series, order)` / `swing_high(series, order)`
function that returns, at each bar, the value and index of the most recent confirmed local
extremum of `series` within a `±order`-bar window (confirmable only `order` bars after the fact,
which itself has a lookahead implication the guard would need to understand — a "confirmed" swing
low is not knowable until `order` bars later, so any rule using it enters later than the swing point
itself, and the guard must verify the rule's evaluation timing accounts for that lag rather than
silently peeking). A divergence expression could then be written as something like
`sign(close - swing_low(close, 5, lag=1)) != sign(macd_macd(12,26,9) - swing_low(macd_macd(12,26,9), 5, lag=1))`
or, more directly, a dedicated `diverges_bullish(price_series, indicator_series, order)` boolean
operator that encapsulates the two-swing-point comparison and its confirmation lag internally. Either
path is a materially larger change than adding an indicator: it needs new state (the last two
confirmed swing points, not just the current bar), a defined confirmation lag, and a guard extension
that can reason about swing-point confirmation timing rather than single-bar crossings. This is
implementation guidance for a future change to `app/rules/`, not a change made in this study — per
the brief, application source was not modified.

**What was done instead: a separate, explicitly descriptive, non-DSL diagnostic**
(`scripts/momentum_divergence_diagnostic.py`, output in
`data/momentum_divergence_diagnostic.json`). It calls `app.indicators.trend.macd` directly — the
same function the app itself uses, so the indicator values match production exactly — on bars pulled
via `quantlab.bars_frame`, then finds local price extrema with plain numpy (a bar is a swing
low/high if it is the strict min/max within a centered ±5-bar window). A "naive divergence" is
flagged between two consecutive swing lows (bullish) or highs (bearish) where price and MACD
disagree on direction, and the 10-bar forward return following the second swing point is compared to
the unconditional 10-bar forward-return distribution over the same window. This runs entirely outside
`app.backtest` — no guard check, no `event_study`, no BH correction — and **is not part of the
corrected `momentum` family**; none of its numbers appear in Sections 2–6 above or fed the
verdicts there.

**Results, labelled descriptive-only, carrying no p-value:**

| symbol | bullish events (n, /yr) | bullish mean fwd 10d | bearish events (n, /yr) | bearish mean fwd 10d | unconditional mean fwd 10d |
|---|---|---|---|---|---|
| SPY | 23 (0.69/yr) | +5.83% | 97 (2.90/yr) | −1.18% | +0.39% |
| QQQ | 26 (0.95/yr) | +4.92% | 76 (2.78/yr) | −1.69% | +0.49% |
| IWM | 20 (0.76/yr) | +6.44% | 59 (2.26/yr) | −2.65% | +0.36% |
| XLK | 27 (0.98/yr) | +6.42% | 75 (2.72/yr) | −1.60% | +0.44% |
| XLV | 17 (0.62/yr) | +3.85% | 62 (2.25/yr) | −1.45% | +0.31% |

Directionally, this naive definition is suggestive of the note's claim — flagged bullish events were
followed by larger-than-baseline forward returns on all five symbols, flagged bearish events by
negative forward returns on all five, against a positive unconditional baseline throughout. But the
raw event counts are small (under one bullish event per year per symbol; 17–27 events total per
symbol over 26–34 years of history), there is no independence discount, no baseline hit-rate test, no
multiple-testing correction, and the swing-detection method (`order=5`) is one arbitrary choice among
many that would each flag a different event set. **This table describes what a specific, simple,
uncorrected definition would have flagged historically — it is not a finding of this study and must
not be cited as evidence that divergence "works."**

---

## Application-level observation (not fixed, per instructions)

**`app.market.store.read_frame` opens the DuckDB analytics cache read-write even for read-only
queries, and concurrent readers collide with an uncaught `IOException`.**

Reproduction: this stream's own run hit it directly. The first `momentum.py` run
(`data/momentum_primary.json`'s XLK cell before the retry) and the first
`momentum_divergence_diagnostic.py` attempt both failed with:

```
_duckdb.IOException: IO Error: Cannot open file "...\data\store\analytics.duckdb": The process
cannot access the file because it is being used by another process.
```

raised from `app/db/duck.py::connect` → `app/market/store.py::read_frame` →
`app/market/store.py::ensure_series`. `duck.connect()` (`app/db/duck.py:94`) defaults to
`read_only=False`, and `read_frame` (`app/market/store.py:226`) calls it without passing
`read_only=True`, even though `read_frame` only executes a `SELECT` — it never writes. DuckDB permits
multiple concurrent **read-only** connections to the same file but takes an exclusive lock for any
non-read-only connection, so two processes calling `ensure_series`/`bars_frame` on the same symbol at
the same moment (exactly the situation in this multi-analyst study, with five streams reading the
same production `analytics.duckdb` cache in parallel) will intermittently have one of them fail with
this `IOException` while the other succeeds, even though both are reading, neither is writing, and
the data both are asking for is identical and already cached. In `run_family`, this exception is
caught by the per-symbol `try/except` and surfaces as `"error": "IOException: ..."` for that symbol —
indistinguishable in the JSON output from a genuine data-existence refusal (like the prior study's
`FONO`) unless a human reads the exception text and recognizes it as transient. A retry moments later
(confirmed twice in this run) succeeds with identical data, confirming this is a concurrency artifact,
not a real data problem with XLK. Worth fixing at the `read_frame` level — pass `read_only=True` for
the analytics-cache connection used by pure-read paths like `ensure_series`'s cache check, reserving
exclusive (write) connections for the actual ingestion path — rather than only widening the caller's
exception handling, since the underlying issue is that a read path is silently taking a write lock it
does not need.
