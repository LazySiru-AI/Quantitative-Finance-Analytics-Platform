# 07 — Multi-timeframe rule-accuracy sweep: findings

Runs `app.timeframes.service.compute_cells` / `aggregate` over the full 20-symbol research
universe (`app.timeframes.models.RESEARCH_UNIVERSE`) across all seven stored intervals
(`5m 15m 30m 1h 4h 1d 1w`), the entire 12-rule catalog (`app.rules.catalog`), and all four
horizons (`1 5 20 60` bars). Answers the user's question — *how does each decision rule behave at
each candle size, and does the daily candle the strategy currently runs on actually win?*

Raw data: `data/research/timeframes/cells_symbol_all.csv` (6,320 rows, one per
symbol×interval×rule×horizon), `cells_sector.csv` (2,844 rows, pooled to sector),
`cells_universe.csv` (316 rows, pooled to the whole 20-symbol universe), plus one
`cells_symbol_{interval}.csv` checkpoint per interval. Every row is one `RuleAccuracyCell`,
flattened; `sufficient=False` rows carry blank statistic columns by construction (the model's own
validator rejects a number on a cell that failed the gate). `regime` was left at `"all"` throughout
— a regime-conditioned sweep (rising/falling) was not run; see "what this does not show."

Method note on scope: individual-symbol cells are the most numerous but the noisiest (small n per
cell); universe cells pool all 20 symbols' raw counts and returns before gating and are the most
statistically defensible single number per (rule, interval, horizon). The rule×interval verdicts
below use universe-scope cells unless stated otherwise.

## 1. Coverage: the honest headline

9,480 cells were computed in total across all three scopes. Sufficiency (`n_independent >= 20`)
pass rates:

| interval | symbol-scope total | symbol sufficient | % | sector-scope sufficient | % | universe-scope sufficient | % |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5m  | 960 | 703 | 73.2% | 350/432 | 81.0% | 48/48 | 100.0% |
| 15m | 880 | 332 | 37.7% | 245/396 | 61.9% | 44/44 | 100.0% |
| 30m | 880 |  60 |  6.8% | 138/396 | 34.8% | 42/44 |  95.5% |
| 1h  | 960 | 787 | 82.0% | 375/432 | 86.8% | 48/48 | 100.0% |
| 4h  | 880 | 298 | 33.9% | 244/396 | 61.6% | 44/44 | 100.0% |
| 1d  | 880 | 790 | 89.8% | 384/396 | 97.0% | 44/44 | 100.0% |
| 1w  | 880 | 446 | 50.7% | 253/396 | 63.9% | 40/44 |  90.9% |

**30-minute bars are barely measurable at the individual-symbol level** — only 6.8% of cells clear
the independence gate; the greedy non-overlap scan on a 60-day intraday history at 30m intervals
leaves too few non-overlapping episodes for most rule/horizon pairs. 15m and 4h aren't much better
(under 38%). Pooling to universe scope rescues almost all of these (95–100% sufficient once 20
symbols' counts are summed) — but that is a statement about aggregate measurability, not about any
one symbol's individual behavior.

**Even where a cell clears the sufficiency gate, almost none of it is statistically real once
corrected for the size of this search.** Of the 9,480 cells computed, **3,416 symbol-scope, 1,989
sector-scope, and 310 universe-scope cells were sufficient** — but after Benjamini-Hochberg FDR
correction at α=0.10:

| scope | sufficient cells | p<0.05 (uncorrected) | q<0.10 (FDR-corrected) |
|---|---:|---:|---:|
| symbol | 3,416 | 109 (3.2%) | **0** |
| sector | 1,989 | 74 (3.7%) | **0** |
| universe | 310 | 16 (5.2%) | **3** |

At symbol and sector scope, the uncorrected p<0.05 rate (3.2–3.7%) is right around what a pile of
null tests produces by chance alone — and **zero of those symbol- or sector-level "significant"
cells survive FDR correction.** Only at universe scope, where pooling raises statistical power the
most, do 3 of 316 cells (0.97%) survive — see §3.

## 2. Rule × interval lift matrix (universe scope, best horizon, percentage points)

Each cell is the highest lift among the four horizons that clears the sufficiency gate at
universe scope; `insuff` = evaluated but no horizon reached 20 independent episodes; `n/a` = the
rule is not defined on that interval (`vwap_reclaim` is intraday-only, per its indicator
registration). `*` marks the one cell in the entire matrix that survives BH-FDR at α=0.10.

| rule | 5m | 15m | 30m | 1h | 4h | 1d | 1w |
|---|---:|---:|---:|---:|---:|---:|---:|
| rsi_oversold | +3.8 | +2.9 | +2.1 | +1.6 | +2.3 | +3.3 | +5.5 |
| rsi_overbought | +2.6 | +2.0 | +2.8 | +0.6 | +1.7 | +0.6 | +3.4 |
| bb_lower_touch | +3.1 | +5.4 | +3.5 | +1.6 | +0.2 | +2.0 | **+6.7\*** |
| bb_upper_touch | +0.2 | -1.1 | +2.6 | +0.7 | +1.8 | +1.4 | +1.9 |
| bb_squeeze | +5.2 | +3.8 | +0.1 | +1.8 | +3.8 | +2.0 | insuff |
| ema_golden_cross | +7.2 | +10.5 | +14.8 | -3.6 | +1.1 | +0.9 | +3.6 |
| ema_death_cross | +5.8 | +2.6 | +4.7 | +1.5 | +0.1 | +0.1 | +2.5 |
| macd_bullish_flip | -0.3 | +2.4 | +2.7 | +1.4 | +1.2 | +1.0 | +0.3 |
| macd_bearish_flip | +1.1 | +1.9 | +2.6 | -0.1 | +1.6 | +0.4 | +1.0 |
| price_above_sma200 | +2.4 | +6.1 | +8.9 | +1.7 | +2.7 | +0.1 | -2.3 |
| atr_range_expansion | +1.9 | +2.5 | +1.7 | +0.4 | +1.9 | +1.1 | +0.2 |
| vwap_reclaim | -0.1 | n/a | n/a | +0.5 | n/a | n/a | n/a |

**Read this matrix as "what the lift looked like," not "what is real."** Every cell in it except
`bb_lower_touch`/1w has q_value = 1.0 — none of the striking-looking numbers (`ema_golden_cross`
at +14.8pp on 30m, +10.5pp on 15m; `price_above_sma200` at +8.9pp on 30m) survive multiple-testing
correction. Their n_independent at the winning cell is small (20, 44, 66 respectively) — exactly
the range where a `~15pp` binomial standard error (the reasoning behind the `MIN_INDEPENDENT=20`
gate itself) swallows the entire effect.

## 3. What actually survives correction — all three cells, everywhere in the sweep

Across every scope and every cell computed (9,480 total), exactly **three** are FDR-significant,
all at universe scope:

| rule | interval | horizon | lift | q_value | base_rate | hit_rate | n_independent |
|---|---|---:|---:|---:|---:|---:|---:|
| bb_lower_touch | 1w | 1 bar (~1 week) | **+6.7pp** | 0.014 | 52.6% | 59.4% | 903 |
| vwap_reclaim | 5m | 1 bar (~5 min) | **-3.7pp** | 0.014 | 49.7% | 46.0% | 2,872 |
| bb_upper_touch | 5m | 1 bar (~5 min) | **-4.2pp** | 0.034 | 49.7% | 45.5% | 1,913 |

Only one of the three is a positive edge: **a close below the lower 20-bar Bollinger band, held
one week, wins 59.4% of the time vs. a 52.6% baseline** — a genuine, FDR-survived +6.7pp lift on
903 independent weekly episodes pooled across the universe. The other two are **statistically
reliable anti-signals at 5-minute bars**: when `vwap_reclaim` or `bb_upper_touch` fires on a 5m
bar, the one-bar-ahead result is *worse* than the baseline, not better — a real, significant
negative lift, not noise. This does not mean "short the reclaim"; it means the mean-reversion/
breakout read those two rules imply does not hold at 5m over the next bar, at cost-free measurement
(see §6 for what costs do to it).

## 4. Does the daily candle — what the strategy currently uses — actually win?

**No, but neither does anything else clearly beat it.** Daily's best-looking universe cell
(`rsi_oversold`, horizon=5 bars, lift=+3.3pp, p=0.006) does **not** survive FDR (q=0.41). Across
all 44 sufficient daily universe cells, **zero** survive correction — the same "nothing survives"
result every interval except 1w gets. Daily's lift distribution across those 44 cells (mean
+0.18pp, median +0.17pp, min -3.8pp, max +3.3pp) is unremarkable — tightly centered near zero, no
tail either direction — versus, e.g., 30m's distribution (mean +0.22pp but std 4.4pp, driven by the
small-n `ema_golden_cross` cell above) or 1h's (mean **-0.65pp**, the only interval with a
negative average lift, though still not FDR-significant anywhere). Concretely: of the sweep's 3
FDR-significant cells (§3), none are on the daily interval — the interval currently in production
shows no better and no worse a reliable signal than most of the rest of the grid; the one place a
real edge does turn up is weekly, not daily, and it is a single rule (`bb_lower_touch`), not a
wholesale case for switching timeframes.

## 5. Per-sector analysis

`aggregate(cells, to="sector")` pools each sector's member symbols' raw counts before gating.
Sufficiency by sector × interval (of 44–48 possible rule×horizon cells per sector×interval,
excluding `vwap_reclaim`'s non-intraday n/a intervals):

| sector | 5m | 15m | 30m | 1h | 4h | 1d | 1w |
|---|---:|---:|---:|---:|---:|---:|---:|
| Broad Market | 36 | 25 | 14 | 40 | 25 | 44 | 25 |
| Communication Services | 40 | 29 | 18 | 40 | 28 | 36 | 22 |
| Consumer Discretionary | 40 | 28 | 15 | 40 | 27 | 40 | 25 |
| Consumer Staples | 40 | 28 | 13 | 40 | 26 | 44 | 31 |
| Energy | 36 | 26 | 14 | 48 | 27 | 44 | 29 |
| Financials | 36 | 27 | 14 | 40 | 29 | 44 | 31 |
| Health Care | 36 | 26 | 14 | 40 | 30 | 44 | 30 |
| Industrials | 38 | 20 | 3 | 39 | 16 | 44 | 28 |
| Technology | 48 | 36 | 33 | 48 | 36 | 44 | 32 |

Industrials is thinnest (only 1 symbol, CAT, and the smallest sample of any sector — 30m coverage
collapses to 3/44 cells); Technology is richest (5 symbols: AAPL, MSFT, NVDA, AMD, SOXX).

**Finding: zero sector-scope cells survive FDR correction.** 74 of 1,989 sufficient sector cells
show uncorrected p<0.05 (3.7%, consistent with chance), and every single one of them has q_value
≥ 0.85 after correction — none holds up. The largest-looking sector effects before correction
(`price_above_sma200` on Financials/15m at +23.8pp, p=0.0098, n=30; `bb_squeeze` on Communication
Services/30m at +23.5pp, p=0.029, n=22) are exactly the small-n, striking-looking cells the FDR
correction exists to catch — do not read these as sector-specific edges. **This sweep found no
rule that reliably behaves differently by sector** once corrected for the number of sector cells
tested; the per-symbol variance section below is a more honest way to see that the underlying
inconsistency is real, it just isn't sector-structured.

As a supporting (not FDR-passing) observation: at symbol scope, the (rule, interval, horizon)
combinations with the widest spread of lift *across individual symbols* (std ≥ 0.10, n≥5 sufficient
symbols) are concentrated in `rsi_overbought`/`bb_upper_touch`/`bb_lower_touch` at 15m/4h and
`rsi_oversold` at 1d/5m — e.g. `bb_lower_touch` at 4h/1-bar horizon ranges from -23.9pp to +17.6pp
across 19 symbols that individually clear the gate. That range is a symptom of small per-symbol
samples at those cells, not evidence of a coherent per-symbol pattern — no q_value supports treating
any individual symbol's cell there as real.

## 6. The `ema_golden_cross` rare-rule prediction

**The prediction holds at every interval except daily.** `ema_golden_cross` (a 50/200 EMA cross —
inherently rare) was predicted to fail the `n_independent >= 20` gate for every individual symbol
at every interval, becoming measurable only once pooled to universe scope. Checked against real
data:

| interval | symbols clearing the per-symbol gate (of 20) |
|---|---:|
| 5m | 0 |
| 15m | 0 |
| 30m | 0 |
| 1h | 0 |
| 4h | 0 |
| **1d** | **12** |
| 1w | 0 |

At 5m/15m/30m/1h/4h/1w the prediction is exactly right: 0 of 20 symbols individually reach 20
independent golden crosses (max symbol-level `n_independent` at, e.g., 1h is 13; at 1w it's 8).
**At daily it does not hold**: 12 of the 20 universe symbols (AAPL, MSFT, AMD, KO, WMT, JPM, BAC,
JNJ, UNH, XOM, CVX, CAT) individually clear the gate, because the stored daily history is long
enough (CAT alone reaches 52 independent crosses) for a slow, rare crossover to accumulate 20+
non-overlapping instances on its own. The remaining 8 (SPY, QQQ, GOOGL, META, AMZN, TSLA, NVDA,
SOXX) still fail individually at daily (as few as 5 independent crosses for META). So: **partially
verified** — true for 6 of 7 intervals, false for the one interval (daily) with by far the deepest
stored history. Pooling to universe scope is still what makes the rule measurable across the board
(560 symbol-scope cells for this rule, only 48 sufficient, all 48 on daily; universe-scope cells
are sufficient at every interval).

## 7. Cost sensitivity on the best-looking short-interval rules

Of the 92 sufficient universe-scope cells at 5m/15m, **17 (18%) still show a positive
`cost_adjusted_edge`** after haircutting each triggered episode by the assumed 5bps round-trip
cost — but **zero of those 17 have q_value < 0.10.** Both FDR-significant 5m cells from §3 get
markedly worse once costed: `vwap_reclaim`/5m/1-bar goes from -3.7pp lift to **-17.7pp**
cost-adjusted edge; `bb_upper_touch`/5m/1-bar goes from -4.2pp lift to **-18.1pp** cost-adjusted
edge (both anti-signals get roughly 4-5x worse under the cost haircut, since the flat 5bps cost is
applied per-episode to an already-small-magnitude return). The largest apparently-positive
cost-survivor in the whole 5m/15m set is `ema_golden_cross`/15m/20-bar (lift +10.5pp,
cost-adjusted +10.5pp — the horizon is long enough, 300 minutes, that a flat 5bps cost barely
dents it) but its q_value is 1.0.

**No 5m or 15m edge in this catalog survives both FDR correction and transaction costs
simultaneously.** The two significant 5m cells found are cost-negative (they are anti-signals to
begin with); the cells that do look cost-robust are exactly the ones the FDR correction already
rejected as statistically indistinguishable from chance.

## 8. What this does NOT show

- **Regime dependence was not swept.** Every cell above is `regime="all"`; `compute_cells(...,
  regimes=True)` (rising/falling trailing-window buckets) was not run over the full grid in this
  pass — a rule could easily show a real, FDR-survivable lift *conditional on* a rising or falling
  regime that washes out when pooled across all regimes, or vice versa. **NOT MEASURED.**
- **5m/15m/30m cover only ~60 days of history** (Yahoo's retention ceiling for those intervals) —
  one market regime, not a multi-year claim. Every intraday lift number in this document, FDR-
  significant or not, describes roughly two months of 2026 price action, not a stable long-run
  property of the rule.
- **4h has the thinnest independent-observation count of any interval** (~41–53 independent
  episodes per symbol for a common rule like `ema_death_cross`, vs. daily's ~500+) — its cells
  clear the gate about a third of the time and even the ones that do carry the widest per-episode
  noise of any interval in this sweep.
- **Intraday rolling windows silently span the overnight gap.** A lookback-window indicator (RSI,
  Bollinger, ATR, EMA/SMA, MACD) computed on the first few bars of an intraday session blends in
  closes from the prior session's close — this is not corrected for anywhere in this sweep, at any
  intraday interval.
- **4h bars alternate 4h/2.5h session durations.** A "20-bar" 4h horizon is not a fixed number of
  calendar hours across episodes; `horizon_minutes` uses the nominal 240-minute bucket for cross-
  interval comparison, which is the best available correction, not an exact one.
- **Multiple-comparisons exposure is severe and is the central finding of this sweep, not a
  footnote.** 9,480 cells were computed; even under a true null hypothesis everywhere, ~3–5% would
  show p<0.05 by chance alone — which is exactly the rate observed at symbol (3.2%) and sector
  (3.7%) scope. Only the FDR-corrected `q_value` in §3 should be trusted as "probably real"; every
  raw lift number and every uncorrected p-value elsewhere in this document (including the whole
  rule×interval matrix in §2) is reported for pattern-visibility only and is explicitly flagged as
  not surviving correction.
- **This sweep used `Entry.NEXT_OPEN` only** (`app.rules.evidence`'s "research-only upper bound"
  entry convention) — no other entry/exit convention, and no position sizing, stop-loss, or
  portfolio-level backtest was run. This is a rule-accuracy study, not a strategy backtest.
- **Per-symbol lift dispersion (§5) is descriptive, not diagnostic** — no test was run for whether
  any individual symbol's cell is a real outlier vs. sampling noise from a small per-symbol n;
  treat those ranges as "there is inconsistency" rather than "here is which symbol is different."

## Bug found in the service (reported, not fixed)

None found. `compute_cells`/`aggregate` ran cleanly across all 140 (symbol, interval) pairs and
every rule/horizon combination without exception, and every returned cell satisfied its own
Pydantic invariants (sufficient/None-gating, `lift = hit_rate - base_rate`, sample-count ordering).
One documented, non-bug gap worth flagging back: `aggregate()`'s own docstring already names its
own design cost — sector/universe pooling recomputes each member's raw stats from stored bars
rather than reusing `compute_cells`' output, which is correct today but means a caller supplying
cells computed under different settings (e.g. a different `cost_bps`) than `get_settings()`'s
default would silently get bars re-read under `get_settings()` regardless — not hit in this sweep
since one `Settings` instance was used throughout, but worth the same interface-contract owners
being aware of if `aggregate()` is ever called with a non-default settings' cells.
