# Strategy Lab — consolidated report

**Run date 2026-08-11.** Six analysts, one shared harness, one shared universe, then an adversarial
QA pass over all of it including the harness and the coordinator's own work.

Source of the hypotheses: the user's chart-analysis note, *[MAIN] Chart Analysis
(Indicator/Strategy)*. The note was treated as a set of claims to be tested, not a specification to
be implemented.

**Nothing in this report is investment advice, and no instrument here is framed as one to buy or
sell.** It describes what conditions did historically, with sample sizes and corrections attached —
the convention this repository's own `README.md` already commits to.

| | |
|---|---|
| Primary tests | **150** (4 DSL streams × declared ideas × 5 symbols) |
| Survivors at q ≤ 0.10, within-stream correction | **0** |
| Survivors at q ≤ 0.10, study-wide pooled correction | **0** |
| Exploratory horizon-sweep trials | ~625, **0** discoveries |
| Seasonality family | 75 cells, **0** survivors (all q ≥ 0.98) |
| VIX-threshold family | 15 cells, **0** survivors |
| Lookahead guards | 150 of 150 **passed**, zero unverified |
| Strategies beating buy-and-hold on total return, full history | ~1 of 150, and that one underpowered |

Per-stream detail: [trend-ma](reports/trend-ma.md) · [mean-reversion](reports/mean-reversion.md) ·
[momentum](reports/momentum.md) · [regime-risk](reports/regime-risk.md) ·
[macro](reports/macro.md) · [universe](reports/universe.md) · [QA](reports/qa.md).

---

## 1. The note, claim by claim

The centre of this study. Every row is a claim from the note, tested as written.

| # | Note claim | Source | Verdict |
|---|---|---|---|
| 1 | `IF price > 200MA AND price < lower BB THEN Buy` | p.2 | **Best result in the study, still not significant.** SPY edge +13.3pp, n=87, p=0.0075 — but q=0.276 in its own 40-test family, 0.529 pooled. Reproduced exactly; killed by correction, not by the data. |
| 2 | 200MA as market-regime gate ("trade in a rising market") | p.2 | **Real, but as risk control, not as signal.** Cuts max drawdown up to half and exposure 15–19pp; makes the hit-rate edge *worse* on IWM and XLV. Open 67–75% of the time — a default state, not a rare permission. |
| 3 | "Ideal Entry setup": `20EMA > 50SMA > 10EMA > 200MA` | p.4 | **The note's literal ordering beat the conventional reading.** Positive edge on all 5 symbols vs mixed sign and 2 directional rejections for the "corrected" stack. Neither significant. The obvious fix was the worse hypothesis. |
| 4 | "Price crossing MA" ≠ "MA crossing MA" | p.3 | **Qualitatively supported.** MA-crossing-MA fires ~half as often, better win rate, far less cost drag. Neither significant. |
| 5 | Golden cross 50/200 SMA | p.4 | **Underpowered on 4 of 5 symbols, rejected on the 5th.** The event is too rare to test per-symbol; more history would not fix it, more instruments might. |
| 6 | "MACD crossover is faster but more falsy than MA crossover" | p.6 | **Split — and the note conflates two signals.** Signal-line cross: faster (~10–11/yr vs ~5.2/yr, 12–13 bars held vs 28–32). Zero-line cross: *slower* than MA crossover (~4/yr, ~39 bars). "More falsy" **not supported** — MACD-signal win rate 41.96% vs MA crossover 39.80%. |
| 7 | Bullish/bearish divergence | p.6, contents 1b | **Now tested — see [divergence](reports/divergence.md).** A `swing_high`/`swing_low` operator was built (2026-08-12) to close this gap. Bullish divergence: **0 of 45**, and it does **not beat its own control arms**. The earlier "+3.9–6.4% on <1 event/year" diagnostic was an unguarded artifact — real figures are ~10 events/year and +0.5–0.9% vs a +0.3–0.4% baseline. Bearish MACD divergence **survived the pooled ledger** (edge −0.031, q=0.017) while failing per-symbol; see the four caveats there. |
| 8 | Z-score entry band `|0.5| < z < |2|`, hard stop at `|z| > 3` | p.5 | **Underpowered everywhere** (n=12–29, all under the 30 floor). No `abs()` in the DSL, so tested one-sided only; `stop_loss_pct` is price-percentage, so the z-stop could not be tested as a mechanism at all. |
| 9 | BB bandwidth <5% compression / >15% high-vol regime | p.5 | **No survivor.** Direction-agnostic claim tested with a directional statistic; median forward return reported alongside to avoid overclaiming. |
| 10 | Band touch as *exit* | p.9 | Tested in that role. No survivor. |
| 11 | Confluence / "Golden Alignment" stacking | p.6, p.8, p.9 | **Costs are certain, benefits are not.** Stacking loses 26–32% of independent sample vs the trigger alone, every time. Hit-rate effect: best of three on 3/10 cells, worst on 3/10, no pattern. Scatter next to a guaranteed loss is the finding. |
| 12 | RSI as oversold trigger *and* as trend-strength regime | p.2, p.7 | **Neither framing survives.** Reversion: positive edge on all 5, best q=0.391, net loser on XLK/XLV after costs. Regime gate: mixed sign across symbols. |
| 13 | "March-April Bull and May-October Bear" | p.10 | **Does not hold.** All 75 cells q ≥ 0.98, directionally inconsistent on both halves, composites underpowered. "Sell in May" absent too. Largest raw effects — XLV September weakness (p=0.029), IWM November strength (p=0.043), both folklore — evaporate to q≈0.98. Textbook demonstration of the correction earning its keep. |
| 14 | Fear & Greed / VIX-based strategy | p.11 | **VIX partially, F&G not at all.** VIX>30: positive edge on all 5 symbols (+5.9 to +9.9pp), consistent sign, best q=0.685. VIX>20: near-zero or wrong-way on 4/5. Fear & Greed is **architecturally untestable** — no entry in `macro._SERIES_CATALOG`, no persisted history to join. |
| 15 | ATR position sizing; max-drawdown cap | p.2, p.7 | **Not testable through the engine** — it is long-only, all-in, with no sizing concept (`Costs.notional` is a unit converter). Descriptive simulation outside the engine: ATR-proportional sizing cut volatility and max drawdown on all 5 symbols, improved Sharpe on 4/5. **The most promising risk result in the study, and the app cannot express it.** |
| 16 | Volume Profile, ADX, Stochastic, Ichimoku, Fibonacci, order flow | pp.2, 7, 10 | **Not in the indicator registry.** Not tested. Volume indicators remain deliberately deferred. |
| 17 | Multi-timeframe confluence ("decision on base TF, confirmation on lower TF") | p.9 | **Not expressible** — one expression sees one interval. Also blocked by the settled daily-bars-only decision. |

### What this table adds up to

Seventeen claims. **Zero survive statistical correction.** Four (#2, #4, #6-partial, #11) are
qualitatively supported as *descriptions of mechanics* while failing as edges. Five (#7, #15, #16,
#17, and the mechanism half of #8) could not be tested because the application cannot express them.

That is not a disappointing result. A note assembled from trading literature and influencer content
was tested honestly against 25+ years of five instruments, and behaved exactly as the base rate
predicts. The prior study on this repo found zero survivors in 75 tests; this one found zero in 150
with a wider hypothesis set. **Two independent studies, 225 tests, no survivors** is now this
project's most robust finding about technical rules on daily bars.

---

## 2. The one claim that changes with regime

Full history says nothing beats buy-and-hold. Crisis windows say something different — and the
difference has to be stated precisely or it misleads. From
[`data/regime_windows_corrected.json`](data/regime_windows_corrected.json), indicators properly
seeded:

| Window | Never traded | Traded | Profitable | Beat buy-and-hold |
|---|---|---|---|---|
| dot-com 2000–02 | 8 | 142 | 25 | 120 of 150 |
| GFC 2007–09 | 18 | 132 | **14** | 150 of 150 |
| 2022 bear | 28 | 122 | 28 | 106 of 150 |

In the GFC window every cell that traded beat buy-and-hold — because buy-and-hold lost 32–48% and
these rules mostly **lost less**. Only 14 of 132 actually made money. "Beat buy-and-hold" in a crash
means *lost less*, and in 2022 it did not even mean that for 44 cells, which lost **more**.

One genuine standout survives the correction: **`rsi_oversold_reversion` on IWM returned +51.4%
across 6 trades through the 2007–09 crash.** One cell, one instrument, one window, no correction
applied. Recorded as interesting, claimed as nothing.

---

## 3. Instruments — characterisation, not selection

From [reports/universe.md](reports/universe.md). 56 candidates, 56 resolved.

**Swing character** (trailing-3y ATR% descending + variance-ratio ascending): SLV, NVDA, XBI, IWM,
ARKK. Factor funds rank 40th/52nd/55th — VLUE's VR-20 of 1.078 is the least mean-reverting reading
of any unleveraged instrument tested.

**Long-term holding character** (drawdown depth + recovery + CAGR): MTUM, VOO, QUAL, QQQM, SCHD,
VLUE — **and this ranking is an artifact you must not read past.** All six have 2010-or-2013
inceptions and have never been tested against 2000–02 or 2008–09 in this data. QQQ, same index
family with longer history, ranks 43rd of 52 for exactly that reason. The table ranks survivorship,
not resilience.

**Correlation, the practically useful finding:** 80 near-duplicate pairs at |corr| > 0.90 over
trailing 3 years. SPY/VOO/VTI/RSP/QUAL/MTUM is close to **one bet counted six times**. VLUE and VWO
were the only additions producing zero new duplicates — value is the one factor tested here that is
not a relabelled large-cap-growth position.

**Leveraged products** (the note names QLD on p.11): the gap runs both ways. Shortfall in choppy
windows (SOXL trailing-5y +205% realised vs +753% naive), large outperformance since inception
(TQQQ +33,681% vs +4,636% naive). The naive `k × underlying` model goes **below −100%** in
worst-episode comparisons — mathematically impossible, which is the clean proof the linear intuition
is wrong rather than merely optimistic. Separately: `app.thesis.instruments.REGISTRY` maps
TQQQ/SOXL/UPRO but **has no entry for QLD**, so the note's own leveraged pick is invisible to the
app's decay-avoidance guard.

---

## 4. Macro context as of 2026-08-11

From [reports/macro.md](reports/macro.md), sourced and dated there.

Broad equities near highs (SPY/IWM within 0.35% of 52-week highs; 12 of 14 instruments above their
200-day SMA, only XLU and XLC below). VIX 15.28 — 13th percentile trailing-1y, 34th since 1990. 10Y
≈4.65–4.70%, 2s10s **+47bp, positive**. Fed on hold at 3.50–3.75% since a 9–3 July 29 vote with
three hawkish dissents. Sector dispersion 21.45pp (XLV +17.98%, XLC −3.48%, 3-month).

**The condition with no analogue in the sample:** a Strait of Hormuz / Iran crisis running since
2026-02-28, disrupting ~20–25% of seaborne oil trade, with core PCE at 3.3% y/y. Every historical
result in this study comes from a window containing no comparable oil-supply shock. Near-term
calendar: CPI Aug 12, PPI Aug 13, retail sales Aug 14, NVDA Aug 26, Jackson Hole Aug 27–29, jobs
Sep 4, CPI Sep 11, FOMC Sep 16.

---

## 5. Defects found

**In the application** (none fixed by this study, per its own rules):

1. **`app.market.store.read_frame` opens DuckDB read-write despite only reading.** Concurrent
   readers collide with an uncaught `IOException` that surfaces as a per-symbol data refusal
   **indistinguishable from a nonexistent ticker**. It cost the universe stream four symbols
   (QUAL, MTUM, VLUE, VWO — all recovered on serial retry with 3,286–5,389 bars each) and hit the
   momentum stream twice. In a research context this silently drops symbols from a study.
2. **`ensure_series`' default staleness gate left most symbols 4 days stale.** Benign for 25-year
   backtests; not benign for the macro panel, whose entire purpose is current values.
3. **`app.thesis.instruments.REGISTRY` has no entry for QLD or SSO** — leveraged instruments the
   decay-avoidance guard therefore never sees.
4. **Fear & Greed has no persisted history** (`macro._SERIES_CATALOG`), making an entire strategy
   family in the note untestable.
5. **`HANDOFF.md` is seven phases stale** — it states Phases 0–2 of 8 and "backtesting not built
   yet", while Phase 9 has landed. Anyone onboarding from it would rebuild what exists.
6. The prior study's `OverflowError` in `scan.binomial_p_value` is **already fixed** (log-space
   `lgamma`), independently confirmed by three streams at trial counts up to 6,167.

**In this study, by its coordinator:**

7. **The regime-window list omitted the 2007–09 crisis.** Found by the mean-reversion analyst.
   Every stream inherited it. Backfilled, brief corrected with a visible note.
8. **`quantlab.slice_window` recomputed indicators from bar 0 of each window slice** — so an
   `sma(200)` rule inside a 253-bar window was blind for 200 of them. Found by QA. SPY was truly
   below its 200-day SMA for 84.9% of 2022; the harness saw 19.5%. It inflated the study's
   never-traded count from 18 to 41 and distorted every regime narrative. Superseded by
   `meta/regime_windows_corrected.json`; the defect is documented in place rather than silently
   patched, because the shipped stream JSONs were produced by that exact code.

No p-value, q-value or verdict is affected by #7 or #8 — regime windows are descriptive and sit
outside every correction family, and primary statistics were always computed on full unsliced
history. QA's verdict on the central negative finding: **sound.**

---

## 6. What this cannot tell you

- **One historical path.** Every "independent" n counts non-overlapping windows of *one* sequence of
  macro events, not draws from different universes.
- **Correlated instruments.** SPY/QQQ/XLK are three views of large-cap growth. XLV and IWM were put
  in the primary set precisely so this would be visible rather than hidden — and it was: several
  rules behaved differently there.
- **Survivorship, twice over.** ETF constituents are today's constituents; the long-term ranking
  table is dominated by funds too young to have been tested by the worst drawdowns in the sample.
- **No fees, spreads, or taxes.** 5bps slippage each way is modelled; expense ratios and real
  bid-ask are not. For a swing rule, a wide spread can exceed the entire modelled edge.
- **A backtest is not a forecast**, and this study is emphatically not one. Zero survivors describes
  what these rules did on stored history under pre-registration, correction and guard discipline.
- **Position sizing, the note's own risk leg, was never testable.** The most encouraging risk result
  here (ATR-proportional sizing improving Sharpe on 4/5 symbols) sits outside the guarded engine and
  carries no statistical claim at all.

---

## 7. Where the evidence points next

Ranked by expected value, not by ease.

1. **Add a lookback-extremum primitive to `app/rules/`** (`swing_high`/`swing_low`, with a
   confirmation-lag-aware guard). It unlocks divergence — the note's own claim #7, the one
   descriptive signal in this study that looked interesting and could not be tested. Highest value
   per unit of work in the entire backlog.
2. **Give the backtest engine a position-sizing concept.** Claim #15 is the note's central risk
   idea, the descriptive evidence for it is the best in the study, and the engine structurally
   cannot express it.
3. **Fix the DuckDB read path** so an infrastructure failure can never again be reported as a
   missing ticker. This one is a correctness issue in a research tool, not a feature.
4. **Persist Fear & Greed history** so claim #14's other half becomes answerable at all.
5. **Test rules across instruments rather than per-instrument.** The golden cross (#5) failed on
   power, not on effect — pooling the event across many symbols is the standard remedy and this
   universe now has 56 validated symbols to do it with.
