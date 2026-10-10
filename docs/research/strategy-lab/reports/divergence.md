# Divergence — tested properly, with a purpose-built operator

Run 2026-08-12. The hypothesis the 2026-08-11 study had to record as **untestable**: the rule DSL had
no lookback-extremum operator, so "price makes a lower low while the oscillator makes a higher low"
could not be phrased. `app.indicators.swing` was built for this study (`swing_high`/`swing_low`,
`rsi_at_swing_*`, `macd_at_swing_*`; 37 tests in `tests/test_swing.py`; full suite 1518 passing).

Scripts: `scripts/divergence.py`. Data: `data/divergence_*.json`. Every expression below passed
`app.backtest.guards.check` — **45 of 45 primary cells, guard status `passed`, zero unverified.**

---

## 1. What was tested

Nine ideas × 5 primary symbols (SPY, QQQ, IWM, XLK, XLV) = **45 primary tests**, one BH ledger,
α = 0.10, horizon 5, harness default costs (5bps each way).

| key | entry | dir | encodes |
|---|---|---|---|
| `bullish_rsi_divergence` | `low < swing_low(5) and rsi(14) > rsi_at_swing_low(14,5)` | up | note p.6 |
| `bullish_macd_divergence` | `low < swing_low(5) and macd_macd(12,26,9) > macd_at_swing_low(12,26,9,5)` | up | note p.6, the MACD form the note names |
| `bearish_rsi_divergence` | `high > swing_high(5) and rsi(14) < rsi_at_swing_high(14,5)` | down | note p.6 |
| `bearish_macd_divergence` | `high > swing_high(5) and macd_macd(12,26,9) < macd_at_swing_high(12,26,9,5)` | down | note p.6 |
| `new_low_alone` | `low < swing_low(5)` | up | **control** |
| `rsi_above_swing_alone` | `rsi(14) > rsi_at_swing_low(14,5)` | up | **control** |
| `macd_above_swing_alone` | `macd_macd(12,26,9) > macd_at_swing_low(12,26,9,5)` | up | **control** |
| `bullish_rsi_divergence_lb10` | same, `lookback=10` | up | parameter sensitivity |
| `bullish_rsi_divergence_trend_gated` | bullish RSI divergence `and close > sma(200)` | up | confluence |

The three control arms are the point. Divergence is a conjunction, and a conjunction that does not
beat its own components is a story told about one of them.

---

## 2. What the note claims vs what the data says

| Claim (note p.6) | Verdict |
|---|---|
| Divergence between price and MACD signals a possible trend change | **Not supported for the bullish case.** Edge negative on 4 of 5 primary symbols. |
| (same, RSI form) | **Not supported.** Edge negative on 4 of 5; `rejected` on those four. |
| Bearish divergence signals a topping trend | **The one thing in this study that survived a correction** — but only pooled, and not per-symbol. See §5. |
| Divergence is worth more than the underlying price event | **No.** Divergence did not beat its own control arms anywhere. |

---

## 3. Primary family — zero survivors of 45

Every q-value in the primary ledger is **1.000**. Selected rows (full grid in
`data/divergence_primary.json`):

| idea | SPY | QQQ | IWM | XLK | XLV |
|---|---|---|---|---|---|
| `bullish_rsi_divergence` edge | −0.013 | −0.017 | +0.016 | −0.037 | −0.020 |
| n_independent | 140 | 129 | 127 | 130 | 125 |
| `bullish_macd_divergence` edge | −0.036 | −0.017 | −0.019 | −0.047 | +0.040 |
| n_independent | 60 | 69 | 45 | 70 | 64 |
| `new_low_alone` (control) edge | −0.000 | −0.016 | −0.002 | −0.024 | +0.027 |
| `rsi_above_swing_alone` (control) edge | −0.003 | +0.000 | −0.005 | +0.002 | −0.006 |

**Divergence versus its control, the central question:** bullish RSI divergence produced edges of
−0.013/−0.017/+0.016/−0.037/−0.020. The bare new-low control produced −0.000/−0.016/−0.002/−0.024/
+0.027. The conjunction is not better than the component — on SPY and XLV it is *worse*. Adding the
oscillator condition to a new low bought nothing on this universe.

The one cell with a small raw p is `bullish_rsi_divergence_trend_gated` on SPY: edge **+0.157**,
n=53, p=0.0176 — and q=0.793 in its own family. Consistent with the earlier study's finding that a
200-day gate is doing whatever work is visible, and not significant regardless.

**Strategy mechanics: 0 of 35 backtested idea×symbol combinations beat buy-and-hold on total
return.** Unchanged from every other stream in this study.

---

## 4. Power was not the problem — and the earlier diagnostic was wrong

This study was designed around an expected power failure. The 2026-08-11 momentum stream's naive
pandas diagnostic reported **under one bullish divergence event per symbol per year** and mean
10-day forward returns of **+3.9% to +6.4%** against a +0.3–0.5% baseline. That is what made
divergence "the most promising unexplored thread" in the consolidated report.

Run through the real, guarded operator at the identical horizon (`data/divergence_vs_naive_diagnostic.json`):

| symbol | triggers | per year | mean 10-day forward | baseline |
|---|---|---|---|---|
| SPY | 299 | **8.9** | +0.46% | +0.36% |
| QQQ | 325 | **11.9** | +0.66% | +0.43% |
| IWM | 268 | **10.2** | +0.92% | +0.32% |
| XLK | 320 | **11.6** | +0.88% | +0.39% |
| XLV | 275 | **10.0** | +0.45% | +0.29% |

Both halves of the earlier diagnostic were wrong by an order of magnitude. Events are **~10×
more frequent** than it claimed, and the forward-return effect is **~7× smaller** — a fraction of a
percent above baseline, not four to six percent above it. n_independent runs 45–1404 across the
primary family, comfortably above the 30-observation floor almost everywhere.

**The prior report's "most promising unexplored thread" was an artifact of an unguarded
implementation, and testing it properly dissolved it.** That is the single most useful outcome here.
It is also the argument for the operator having been worth building: the naive version was not a
rough approximation of the real thing, it was a different and much more flattering thing.

---

## 5. The pooled arm — the study's only survivor, and how far it goes

Pre-declared before the primary results were read: pool independent triggers across the 13-symbol
replication universe (DIA SOXX IGV XLF XLE XLP XLU XLY XLI XLB XLC TLT GLD) into one binomial cell
per idea, its own BH ledger, m=4.

| idea | hit | baseline | edge | n | p | q | verdict |
|---|---|---|---|---|---|---|---|
| `bullish_rsi_divergence` | 0.5595 | 0.5428 | +0.0167 | 1614 | 0.185 | 0.206 | inconclusive |
| `bullish_macd_divergence` | 0.5696 | 0.5424 | +0.0272 | 776 | 0.130 | 0.206 | inconclusive |
| `bearish_rsi_divergence` | 0.5340 | 0.5455 | −0.0114 | 3088 | 0.206 | 0.206 | inconclusive |
| **`bearish_macd_divergence`** | **0.5152** | **0.5464** | **−0.0312** | **2108** | **0.0042** | **0.0166** | **survived** |

Bearish MACD divergence is followed by a 51.5% 5-day up-rate against a 54.6% baseline — a 3.1
percentage-point *reduction*, in the pre-declared direction, at q=0.017.

**Four reasons to hold this loosely, and they are not boilerplate:**

1. **It fails in the per-symbol primary family.** The same rule on the 5 primary symbols gave edges
   of +0.003, +0.002, −0.037, −0.031, −0.006 — inconclusive or rejected on all five. A result that
   appears only after pooling and not in any individual instrument is exactly the shape of an
   artifact of pooling.
2. **The pooled n is inflated.** 2,108 "independent" windows counts each symbol's non-overlapping
   windows and then adds across symbols — but the 13 symbols trade the same calendar days and
   several are correlated sector exposures. These are not 2,108 independent observations; they are
   closer to a few hundred. The true p is larger than 0.0042 by an unknown factor.
3. **It is not tradeable through this engine.** It is a `direction="down"` hypothesis, and the
   backtest engine is long-only. Nothing here demonstrates a profitable strategy; it demonstrates a
   statistical association with lower subsequent returns.
4. **Effect size is small.** 3.1pp on a 54.6% base rate, before costs, on a signal firing often
   enough to accumulate real cost drag.

The honest statement: **bearish MACD divergence is the only association in 195 corrected tests
across two studies that survived its ledger, it survived in the weakest ledger of the set, and it
contradicts its own per-symbol evidence.** It is a lead worth one properly-powered follow-up, not a
finding.

---

## 6. Regime breakdown

Produced with `meta/regime_windows_corrected.py` semantics (indicators seeded before the window
opens). No p-values — regime windows are descriptive and outside every correction family.
Divergence event frequency roughly doubles in the 2000–02 and 2007–09 windows relative to
2009–19, consistent with pivots simply being more numerous when volatility is higher, which is a
property of the operator rather than a property of the signal.

---

## 7. What this cannot tell you

- **Pooling across correlated instruments buys event count, not independence.** Stated in §5 and
  restated here because it is the load-bearing caveat on the only survivor.
- **One historical path**, as everywhere in this study.
- **`lookback` is a free parameter.** Two values were tested (5 and 10) and pre-declared; the result
  did not flip, which is mild reassurance, not proof of insensitivity across the whole range.
- **Divergence has many definitions.** This is one operationalisation — the textbook one, anchored
  to confirmed price pivots. A practitioner drawing trendlines by eye is doing something else, and
  this study says nothing about that.
- **Bearish results are not short-strategy results.** No shorting, no borrow costs, no path.
- **The naive-vs-guarded gap in §4 is a warning about method, not about divergence.** It says an
  unguarded implementation flattered itself; it does not say every unguarded diagnostic will.

---

## 8. What could not be expressed

Nothing material for this stream — the operator was built to close exactly this gap. Two residual
limits worth recording:

- **Trendline / channel divergence** (connecting successive pivots and comparing slopes) is still
  not expressible; the DSL has no notion of a line fitted through two pivots.
- **Divergence across more than the last pivot** — "three successive lower lows against three higher
  RSI lows" — needs an n-th-previous-pivot accessor, which the operator does not provide. Only the
  most recent confirmed pivot is readable.
