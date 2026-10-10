# regime-risk stream — market regime, risk management, and seasonality

Run 2026-08-11. Stream id `regime-risk`. Universe, harness, windows and statistical discipline are the
shared ones in `docs/research/strategy-lab/BRIEF.md`; read that first. Prior study
(`docs/research/2026-08-11-qqq-soxx-igv-dram-fono.md`) is not repeated here. Scripts live in
`docs/research/strategy-lab/scripts/regime_risk_*.py`; JSON outputs in
`docs/research/strategy-lab/data/regime_risk_*.json`; every number below is copy-pasteable from one of
those files.

**This stream owns "not losing money", plus two calendar/volatility claims.** Most of the note's risk
language — ATR position sizing, max-drawdown caps, VIX/Fear&Greed conditioning, seasonality — is not
expressible in the rule DSL at all (BRIEF.md section 4). Handling that honestly, rather than forcing it
into the DSL or silently skipping it, is most of this report. Five separate ledgers are declared and
run below; none of them are pooled into each other.

**Coordination note.** The `close > sma(200)` regime filter itself was already run by the `trend-ma`
stream as `regime_filter_standalone`, in their own 45-test family (`data/trend_ma_primary.json`). This
report cites that result rather than re-running it, and instead tests the regime filter's *converse*
(below the 200MA) and its *marginal contribution* to a risk-managed entry, plus a purely descriptive
regime-value analysis (time in regime, transitions, drawdown avoided) that produces no p-value at all.

---

## 1. What was tested

### 1a. DSL primary family (`regime_risk_dsl.py`) — 4 ideas x 5 symbols = 20 tests, one BH ledger

| key | entry | exit | horizon | direction | holding cap | stop | note line |
|---|---|---|---|---|---|---|---|
| `below_200ma_regime` | `close < sma(200)` | `close > sma(200)` | 20 | down | — | — | p.2, converse of "price > 200MA = positive trend" |
| `regime_filtered_pullback` | `close > sma(200) and rsi(14) < 30` | `rsi(14) > 50` | 10 | up | 15 | 10% | p.2 "trade only when broader market context is favorable", applied to a risk-managed entry |
| `unfiltered_pullback` | `rsi(14) < 30` | `rsi(14) > 50` | 10 | up | 15 | 10% | counterfactual: same trade, gate removed |
| `unfavorable_regime_pullback` | `close < sma(200) and rsi(14) < 30` | `rsi(14) > 50` | 10 | up | 15 | 10% | the trade the note's framework discourages |

Every guard (`app.backtest.guards.check`) on every entry and exit expression above **passed** —
verified per symbol per idea, 40 checks total (2 expressions x 4 ideas x 5 symbols), all `PASSED`, zero
`UNVERIFIED`. Full per-cell status is in `data/regime_risk_dsl_primary.json`, `cells[*].guard_entry` /
`guard_exit`.

### 1b. Seasonality family (`regime_risk_seasonality.py`) — 15 buckets x 5 symbols = 75 tests, one BH ledger

Not a DSL family (no date operator exists); built directly against `bars_frame` in pandas, using the
app's own `binomial_p_value`/`benjamini_hochberg` for every statistic. 12 individual calendar months +
3 composite buckets:

| bucket | span | direction | source |
|---|---|---|---|
| `mar_apr_bull` | end-Feb close -> end-Apr close | up | note p.10 verbatim: "March-April Bull" |
| `may_oct_bear` | end-Apr close -> end-Oct close | down | note p.10 verbatim: "May-October Bear" (= classic "Sell in May" bear leg) |
| `nov_apr_best_six` | end-Oct close -> end-Apr close (next yr) | up | classic "Best Six Months" complement, tested per BRIEF.md's instruction to check whether Sell-in-May shows up at all |

### 1c. VIX family (`regime_risk_vix.py`) — 3 thresholds x 5 symbols = 15 tests, one BH ledger

Thresholds declared before running: `VIX > 20` (elevated), `VIX > 30` (high fear/crisis), `VIX` above
its own full-history 80th percentile (24.18, an **in-sample** threshold, flagged as such — see section
7). Horizon 20 (~1 month), direction `up` for all three (the contrarian "buy the fear" reading). `^VIX`
used only as a joined signal, never backtested as an instrument.

### 1d. ATR stop mechanics (`regime_risk_atr_stops.py` Part 1) — mechanics only, no p-value, no BH ledger

Same entry/exit as trend-ma's `regime_filter_standalone` (`close > sma(200)` / `close < sma(200)`), run
through the real engine at no stop, six fixed stops (5/10/15/20/25/30%), and each symbol's own
1x/2x/3x-ATR(14)-typical stop. Declared explicitly as mechanics-only (see section 4's reasoning) because
a stop does not change the entry expression's hit rate — only its trade management — so these cells
carry no p-value and are not part of any corrected family.

### 1e. ATR-proportional sizing simulation (`regime_risk_atr_stops.py` Part 2) — descriptive, no p-value

Pure pandas: daily position weight inversely proportional to yesterday's ATR(14)%, rescaled so mean
weight = 1.0 (same average exposure as buy-and-hold), capped at 3x. Entirely outside
`app.backtest.strategy` — see section 8.

### 1f. Regime-value descriptive analysis (`regime_risk_regime_value.py`) — descriptive, no p-value

Time spent in each `close > sma(200)` regime state, transition counts, cumulative-return contribution
by regime, and a loss-streak/worst-trade read off the actual trade ledger.

### 1g. Fear & Greed testability check (`regime_risk_feargreed_check.py`) — static analysis + citation

No backtest — establishes whether one exists to run at all.

---

## 2. What the note claims vs. what the data says

| # | Note claim | Verdict |
|---|---|---|
| 1 | "ATR based position sizing... prevents catastrophic loss / ensures no single trade or loss streak can significantly damage the whole portfolio" (p.2) | **Cannot be backtested through the engine at all** — position sizing is explicitly out of scope of `app.backtest.strategy` (see section 8). What can be shown: ATR-*proportional* sizing, run as a descriptive simulation outside the engine, cut annualised volatility on all 5 primary symbols (e.g. SPY 18.6%→13.5%, QQQ 26.9%→18.4%) and cut max drawdown on all 5 (SPY −56.5%→−39.0%, QQQ −83.0%→−48.6%) versus a flat always-in position, at the same average exposure. This is descriptive, not a hypothesis test — no p-value attaches to it (section 1e, section 4c). |
| 2 | ATR(14) "how much does this asset normally move each day... more volatile assets ⇒ smaller positions" (p.7), used for stop distance | **Calibrated in real numbers, not tested as a hit-rate claim** (there is no hit-rate claim to test — ATR calibrates a *distance*, not a *direction*). Typical (median) ATR(14) as % of price: SPY 1.18%, QQQ 1.59%, IWM 1.71%, XLK 1.61%, XLV 1.28%. A 1x/2x/3x-ATR stop is therefore a **much tighter** stop (1.2%–5.1% depending on symbol and multiple) than the round percentages (10–30%) commonly used as fixed stops — see section 4b: the ATR-typical stops bound 5–75% of trades on the stop, while a fixed 15%+ stop never binds at all on this same entry on any of the 5 primary symbols (a fixed 10% stop binds narrowly — 0.6%–4.5% of trades — on 4 of 5). |
| 3 | Seasonality, verbatim: "March-April Bull and May-October Bear" (p.10) | **Not supported after correction, on either half of the claim, on any of the 5 primary symbols.** Every one of the 15 seasonality-family cells came back `q ≥ 0.98` (screening bar is 0.10) except for the composite-bucket cells, which never cleared 30 independent observations to begin with (`n_independent` = 25–34, all below the 30-observation power floor) — every composite-bucket cell is `underpowered` or `inconclusive`/`rejected`, none `survived`. Directionally: `mar_apr_bull`'s edge is positive on 3/5 symbols and negative on 2/5 (SPY +0.5pp, QQQ −6.6pp, IWM +4.9pp, XLK +4.7pp, XLV −1.5pp) — no consistent bull tilt. `may_oct_bear`'s edge is negative (i.e. directionally consistent with "bear") on only 2/5 symbols (SPY −1.6pp, IWM −3.6pp, XLV −11.1pp) and positive on 2/5 (QQQ +2.2pp, XLK +2.2pp) — not a consistent pattern either, and every one of these edges is a few percentage points against a ~60–75% baseline hit rate that is already high because 6-month holding periods are usually positive for equities regardless of calendar timing. **The note's claim does not hold on this universe.** |
| 3b | (not the note, but the obvious adjacent question) does the classic "Sell in May" pattern show up at all? | **No, not in a form that survives correction.** `nov_apr_best_six` (the "Best Six Months" complement) shows a positive edge on 3/5 symbols (SPY +1.4pp, IWM +1.8pp, XLV +11.1pp) and negative on 2/5 (QQQ −1.5pp, XLK −1.5pp) — magnitudes are all small relative to baseline and none survive (all q=1.0). Individually, the two largest raw seasonal effects in the entire 75-cell sweep are September weakness (XLV, edge −22.3pp, raw p=0.029) and November strength (IWM, edge +20.8pp, raw p=0.043) — both familiar calendar-effect folklore — but **neither survives Benjamini-Hochberg correction across the 75-test family** (both land at q≈0.98). This is exactly the "testing 12 months and reporting the best one" failure mode BRIEF.md names, made concrete: the raw signal exists, the corrected signal does not. |
| 4 | "[Macro] Fear & Greed / VIX based investment strategies" (p.11) — VIX half | **No corrected survivor at the declared thresholds, but a directionally consistent pattern worth naming plainly.** `VIX > 30`: positive edge on all 5 primary symbols (SPY +5.9pp, QQQ +9.9pp, IWM +7.3pp, XLK +9.5pp, XLV +8.4pp), but every q-value is ≥0.68 (best raw p = 0.118 on XLK, `n_independent` = 59–69, below the 30-observation floor is *not* the issue here — these are adequately powered and still don't clear correction). `VIX > 20`: near-zero or negative edge on all 5 (three `rejected` on direction). The full-history-80th-percentile threshold falls in between. **Verdict: inconclusive, not survived** — a real, consistent, but not statistically distinguishable-from-baseline pattern at the pre-declared thresholds and horizon. |
| 4b | Fear & Greed half | **Untestable in this study, for an architectural reason, not a data-quality one.** See section 8. |
| 5 | Trend/regime filter (p.2): "trade only when broader market context is favorable", "price > 200MA = positive long term trend" | **The filter is real but its value is asymmetric across symbols, and total return always loses to buy-and-hold.** trend-ma's own hit-rate test: `inconclusive` on 3/5 symbols, `rejected` (wrong-way edge) on IWM and XLV. This stream's regime-side analysis (section 5) adds the sharper finding: on XLV specifically, compounding only its "favorable" (above-200MA) days on their own produces **+17.8%** over 27 years, while compounding only its "unfavorable" days on their own produces **+424.7%** — nearly all of XLV's real +518% buy-and-hold gain happened on days this exact filter would have called unfavorable. Max drawdown from the costed filter is reduced relative to buy-and-hold on 4/5 symbols (SPY, QQQ, IWM, XLK) and *increased* on 1/5 (XLV). See section 5 for the full breakdown. |

---

## 3. Primary family results

### 3a. DSL family (`data/regime_risk_dsl_primary.json`, family_size=20)

| symbol | idea | hit | baseline | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|---|---|
| SPY | below_200ma_regime | 0.575 | 0.637 | −0.062 | 2071 | 138 | 0.132 | 0.697 | inconclusive |
| SPY | regime_filtered_pullback | 0.611 | 0.601 | +0.010 | 18 | 13 | 1.000 | 1.000 | underpowered |
| SPY | unfiltered_pullback | 0.632 | 0.601 | +0.031 | 125 | 49 | 0.771 | 0.964 | inconclusive |
| SPY | unfavorable_regime_pullback | 0.636 | 0.601 | +0.034 | 107 | 39 | 0.744 | 0.964 | inconclusive |
| QQQ | below_200ma_regime | 0.557 | 0.617 | −0.060 | 1801 | 112 | 0.174 | 0.697 | inconclusive |
| QQQ | regime_filtered_pullback | 0.538 | 0.588 | −0.049 | 13 | 11 | 0.769 | 0.964 | rejected |
| QQQ | unfiltered_pullback | 0.593 | 0.588 | +0.005 | 108 | 44 | 1.000 | 1.000 | inconclusive |
| QQQ | unfavorable_regime_pullback | 0.600 | 0.588 | +0.012 | 95 | 34 | 1.000 | 1.000 | inconclusive |
| IWM | below_200ma_regime | 0.638 | 0.595 | +0.043 | 2093 | 137 | 0.384 | 0.961 | rejected |
| IWM | regime_filtered_pullback | 0.643 | 0.560 | +0.083 | 14 | 9 | 0.740 | 0.964 | underpowered |
| IWM | unfiltered_pullback | 0.591 | 0.560 | +0.031 | 164 | 52 | 0.676 | 0.964 | inconclusive |
| IWM | unfavorable_regime_pullback | 0.585 | 0.560 | +0.025 | 147 | 44 | 0.762 | 0.964 | inconclusive |
| XLK | below_200ma_regime | 0.542 | 0.610 | −0.068 | 1905 | 126 | 0.120 | 0.697 | inconclusive |
| XLK | regime_filtered_pullback | 0.385 | 0.579 | −0.194 | 13 | 10 | 0.339 | 0.961 | rejected |
| XLK | unfiltered_pullback | 0.551 | 0.579 | −0.028 | 118 | 47 | 0.769 | 0.964 | rejected |
| XLK | unfavorable_regime_pullback | 0.571 | 0.579 | −0.007 | 105 | 37 | 1.000 | 1.000 | rejected |
| XLV | below_200ma_regime | 0.651 | 0.596 | +0.054 | 2129 | 145 | 0.236 | 0.786 | rejected |
| XLV | regime_filtered_pullback | 0.619 | 0.559 | +0.060 | 21 | 11 | 0.765 | 0.964 | underpowered |
| XLV | unfiltered_pullback | 0.673 | 0.559 | +0.114 | 165 | 51 | 0.158 | 0.697 | inconclusive |
| XLV | unfavorable_regime_pullback | 0.664 | 0.559 | +0.106 | 137 | 43 | 0.166 | 0.786 | inconclusive |

**0 of 20 survived.** All guards passed. Direction rejections (6 of 20) fell on `below_200ma_regime`
for IWM and XLV (edge ran positive, i.e. *not* worse than baseline — the converse claim failed on
exactly the two symbols where the note's forward claim also failed for trend-ma), on
`regime_filtered_pullback` for QQQ, and on all three of `regime_filtered_pullback` /
`unfiltered_pullback` / `unfavorable_regime_pullback` for XLK (all three pullback variants ran negative
on XLK specifically — worth noting since XLK is one of the tech-proxy symbols the note's framework was
probably built around, and it's the one where a bounce-buying rule did worst).

### 3b. Seasonality family (`data/regime_risk_seasonality.json`, family_size=75)

**0 of 75 at q≤0.10.** Individual-month q-values range 0.981–1.0; composite-bucket q-values are all
1.0. See section 2's table for the note's two specific claims and the Sell-in-May check. Smallest raw
p-values in the whole 75-cell sweep (all far from surviving correction): XLV September (edge −22.3pp,
p=0.029, q=0.981), IWM November (edge +20.8pp, p=0.043, q=0.981), QQQ February (edge −18.8pp, p=0.051,
q=0.981).

### 3c. VIX family (`data/regime_risk_vix.json`, family_size=15)

| symbol | threshold | edge | n_raw | n_indep | p | q | verdict |
|---|---|---|---|---|---|---|---|
| SPY | VIX>20 | −0.019 | 3182 | 219 | 0.575 | 0.803 | rejected |
| SPY | VIX>30 | +0.059 | 703 | 69 | 0.320 | 0.685 | inconclusive |
| SPY | VIX>p80(24.18) | +0.019 | 1737 | 136 | 0.722 | 0.902 | inconclusive |
| QQQ | VIX>20 | −0.003 | 2744 | 188 | 0.940 | 0.940 | rejected |
| QQQ | VIX>30 | +0.099 | 622 | 60 | 0.143 | 0.685 | inconclusive |
| QQQ | VIX>p80 | +0.037 | 1529 | 121 | 0.512 | 0.803 | inconclusive |
| IWM | VIX>20 | +0.025 | 2451 | 173 | 0.589 | 0.803 | inconclusive |
| IWM | VIX>30 | +0.073 | 619 | 59 | 0.292 | 0.685 | inconclusive |
| IWM | VIX>p80 | +0.058 | 1395 | 108 | 0.241 | 0.685 | inconclusive |
| XLK | VIX>20 | −0.007 | 2796 | 190 | 0.824 | 0.940 | rejected |
| XLK | VIX>30 | +0.095 | 632 | 62 | 0.118 | 0.685 | inconclusive |
| XLK | VIX>p80 | +0.030 | 1572 | 123 | 0.580 | 0.803 | inconclusive |
| XLV | VIX>20 | −0.004 | 2796 | 190 | 0.883 | 0.940 | rejected |
| XLV | VIX>30 | +0.084 | 632 | 62 | 0.198 | 0.685 | inconclusive |
| XLV | VIX>p80 | +0.046 | 1572 | 123 | 0.313 | 0.685 | inconclusive |

**0 of 15 survived.** But note the consistency: `VIX > 30` is positive on all 5 symbols, ranging +5.9pp
to +9.9pp, and `VIX > 20` is at or below zero (rejected direction) on 4 of 5. That consistency across
five distinct instruments is itself evidence the effect is not purely noise — but it is evidence at
the level of "worth someone re-testing with more power" (longer history, more thresholds, or a
pooled-across-symbols test this study did not pre-register), not evidence that clears this study's own
bar.

---

## 4. Strategy mechanics vs buy-and-hold

### 4a. DSL family (`data/regime_risk_dsl_primary.json`), full history, `Costs()` default (5bps each way)

| symbol | idea | total return | strat CAGR | Sharpe | max DD | BH max DD | exposure | trades | win rate | cost drag | beats BH (tr / Sharpe) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY | below_200ma_regime | 0.62 | 1.5% | 0.17 | −64.5% | −56.5% | 25.9% | 111 | 85.6% | −0.190 | No / No |
| SPY | regime_filtered_pullback | 0.18 | 0.5% | 0.16 | −12.6% | −56.5% | 1.6% | 13 | 76.9% | −0.015 | No / No |
| SPY | unfiltered_pullback | 0.62 | 1.5% | 0.20 | −30.0% | −56.5% | 6.7% | 50 | 70.0% | −0.080 | No / No |
| SPY | unfavorable_regime_pullback | 0.42 | 1.1% | 0.17 | −30.0% | −56.5% | 5.5% | 40 | 67.5% | −0.056 | No / No |
| QQQ | below_200ma_regime | −0.15 | −0.6% | 0.07 | −77.2% | −83.0% | 27.4% | 86 | 81.4% | −0.077 | No / No |
| QQQ | regime_filtered_pullback | 0.25 | 0.8% | 0.17 | −18.1% | −83.0% | 1.6% | 11 | 81.8% | −0.013 | No / No |
| QQQ | unfiltered_pullback | 0.50 | 1.5% | 0.18 | −40.0% | −83.0% | 7.0% | 45 | 62.2% | −0.062 | No / No |
| QQQ | unfavorable_regime_pullback | 0.22 | 0.7% | 0.12 | −42.0% | −83.0% | 5.7% | 36 | 55.6% | −0.040 | No / No |
| IWM | below_200ma_regime | 1.29 | 3.2% | 0.26 | −51.5% | −59.5% | 33.5% | 112 | 82.1% | −0.272 | No / No |
| IWM | regime_filtered_pullback | 0.02 | 0.1% | 0.04 | −10.2% | −59.5% | 1.7% | 9 | 55.6% | −0.009 | No / No |
| IWM | unfiltered_pullback | 0.45 | 1.4% | 0.18 | −35.8% | −59.5% | 9.5% | 54 | 57.4% | −0.075 | No / No |
| IWM | unfavorable_regime_pullback | 0.32 | 1.1% | 0.15 | −39.3% | −59.5% | 8.1% | 46 | 56.5% | −0.058 | No / No |
| XLK | below_200ma_regime | −0.21 | −0.9% | 0.05 | −76.4% | −82.0% | 28.7% | 89 | 83.1% | −0.073 | No / No |
| XLK | regime_filtered_pullback | 0.21 | 0.7% | 0.17 | −19.2% | −82.0% | 1.6% | 10 | 90.0% | −0.012 | No / No |
| XLK | unfiltered_pullback | 0.74 | 2.0% | 0.22 | −32.3% | −82.0% | 8.1% | 47 | 70.2% | −0.076 | No / No |
| XLK | unfavorable_regime_pullback | 0.50 | 1.5% | 0.18 | −32.3% | −82.0% | 6.6% | 38 | 65.8% | −0.053 | No / No |
| XLV | below_200ma_regime | 3.07 | 5.2% | 0.45 | −36.6% | −40.6% | 32.9% | 157 | 81.5% | −0.692 | No / No |
| XLV | regime_filtered_pullback | −0.09 | −0.4% | −0.08 | −16.2% | −40.6% | 2.1% | 12 | 75.0% | −0.010 | No / No |
| XLV | unfiltered_pullback | 0.33 | 1.0% | 0.16 | −28.5% | −40.6% | 8.9% | 51 | 66.7% | −0.065 | No / No |
| XLV | unfavorable_regime_pullback | 0.44 | 1.3% | 0.20 | −22.2% | −40.6% | 7.1% | 40 | 62.5% | −0.056 | No / No |

**Every single cell trails buy-and-hold on total return, and none beats it on Sharpe either** (contrast
trend-ma's own `regime_filter_standalone`, which *did* beat buy-and-hold Sharpe on SPY/QQQ/XLK — see
section 5). Win rates on the two "long only in an adverse/mixed regime" ideas
(`below_200ma_regime`, 81–86%) look strong in isolation but the strategy still loses money or barely
breaks even (QQQ and XLK post *negative* total return) — this is the expected shape of a
short-horizon mean-reversion trade with tiny average wins and rare large losses, not evidence the rule
works. Comparing `regime_filtered_pullback` (gated to the favorable regime) against
`unfavorable_regime_pullback` (the same trade, gated to the *unfavorable* regime instead) is mixed, not
one-directional: win rate is lower for the unfavorable-regime version on 4 of 5 symbols (SPY 76.9%→
67.5%, QQQ 81.8%→55.6%, XLK 90.0%→65.8%, XLV 75.0%→62.5%; IWM is the exception, 55.6%→56.5%), but
Sharpe is *not* worse for the unfavorable-regime version on 4 of 5 symbols (SPY 0.157→0.165, IWM
0.041→0.152, XLK 0.172→0.181, XLV −0.076→0.198; only QQQ is worse, 0.173→0.120) — on this specific
short-horizon, stopped mean-reversion entry, the regime gate screens out some winning trades along with
losing ones, and its risk-adjusted-return benefit is not as clean as the win-rate numbers alone would
suggest (see section 2, row 5, and section 7).

### 4b. ATR stop mechanics — SPY example (full table in `data/regime_risk_atr_stops.json`)

Shared entry/exit `close > sma(200)` / `close < sma(200)`, no p-value (see section 1d):

| stop | value | total return | max DD | trades | stop-exit share | cost drag |
|---|---|---|---|---|---|---|
| no stop | — | 7.19 | −30.5% | 111 | 0% | −0.966 |
| fixed 5% | 5.0% | 6.99 | −30.8% | 111 | 5% | −0.920 |
| fixed 10–30% | 10–30% | 7.19 | −30.5% | 111 | 0% | −0.966 |
| ATR 1x-typical | 1.18% | 6.60 | −32.3% | 146 | **72%** | −1.171 |
| ATR 2x-typical | 2.36% | 6.38 | −31.9% | 115 | 37% | −1.062 |
| ATR 3x-typical | 3.54% | 6.45 | −30.6% | 112 | 14% | −0.837 |

**Fixed stops of 15% or wider never bind at all**, on any of the 5 primary symbols (every fixed stop
from 15% to 30% reproduces the no-stop numbers exactly) — on SPY specifically, even 10% never binds;
on QQQ/IWM/XLK/XLV a 10% stop binds narrowly (0.6%–4.5% of trades). **ATR-typical stops bind
constantly**
(5–75% of trades exit via stop across the primary universe) because they are an order of magnitude
tighter (1.2%–5.1% vs 10%+). Tighter stops here do not clearly help: max drawdown is *slightly worse*
with ATR-typical stops on SPY (−32.3% vs −30.5% no-stop) because a tight stop on a slow trend filter
gets whipsawed out and re-entered repeatedly, adding trade count (146 vs 111) and cost drag without
reducing the drawdown it was meant to cap. This pattern (tight ATR stop, more trades, similar or worse
drawdown) holds on SPY, QQQ and IWM; XLK and XLV show the ATR 3x-typical stop modestly improving max
drawdown relative to no-stop. Full per-symbol table in the JSON.

### 4c. ATR-proportional sizing simulation (descriptive, no p-value)

| symbol | BH ann. vol | ATR-sized vol | BH max DD | ATR-sized max DD | BH Sharpe | ATR-sized Sharpe |
|---|---|---|---|---|---|---|
| SPY | 18.6% | 13.5% | −56.5% | −39.0% | 0.556 | 0.650 |
| QQQ | 26.9% | 18.4% | −83.0% | −48.6% | 0.487 | 0.723 |
| IWM | 23.9% | 19.1% | −59.5% | −39.8% | 0.404 | 0.353 |
| XLK | 26.0% | 18.5% | −82.0% | −55.9% | 0.463 | 0.638 |
| XLV | 17.9% | 14.5% | −40.6% | −30.9% | 0.462 | 0.483 |

Volatility and max drawdown fall on **all 5 of 5** symbols; Sharpe improves on 4 of 5 (IWM is the
exception, worse Sharpe despite lower vol — its return fell by more than its risk did). This is
consistent with the note's underlying intuition ("more volatile ⇒ smaller position") producing a
smoother ride at the same average exposure — but it is a mechanical property of vol-targeting applied
to any of these five return series, not a statistically tested edge, and it carries no p-value by
design (section 1e, section 8).

---

## 5. Regime breakdown

### 5a. DSL family windows

`below_200ma_regime` (SPY, illustrative — full table in JSON): loses less than buy-and-hold during
drawdowns (dotcom −33.8% vs BH −38.5%; bear_2022 +5.9% vs BH −20.2%) but captures almost nothing during
bull windows (bull_2003_2007 +18.0% vs BH +70.1%; qe_bull_2009_2019 +57.6% vs BH +287.4%) and triggered
**zero trades** during covid_2020_2021 on SPY specifically (the crash and recovery happened too fast
for this 20-bar-horizon condition to complete a round trip in that window). This is the expected shape
for "long only when the trend filter says not to be" — a defensive-tilt curiosity, not a strategy, and
not framed as one.

`regime_filtered_pullback` is **carried almost entirely by the two extended bull-market windows**: on
SPY, QQQ and XLV (checked in detail), nearly all of its closed trades cluster in `bull_2003_2007` and
`qe_bull_2009_2019`, and it fired only 0–1 times in `dotcom_2000_2002` and 0 times in `bear_2022` on
all three symbols (full per-window trade counts in `data/regime_risk_dsl_primary.json`). Which of the
two bull windows contributes more of the positive return varies by symbol (SPY and QQQ: mostly
`qe_bull_2009_2019`; XLV: mostly `bull_2003_2007`) — but in every case checked, the positive aggregate
comes from bull-market windows, not from a rule that held up across the bear regimes too. A gate that
requires both "price above the 200-day trend" *and* "RSI oversold" is nearly self-contradictory in a
genuine bear market, which is exactly why it barely fires in `dotcom_2000_2002` or `bear_2022` at all.

### 5b. Regime-value descriptive analysis (`data/regime_risk_regime_value.json`)

| symbol | % time favorable | transitions | fav episode median (bars) | unfav episode median (bars) | BH total return | favorable-days contribution | unfavorable-days contribution | frictionless favorable-only max DD | BH max DD |
|---|---|---|---|---|---|---|---|---|---|
| SPY | 74.9% | 222 | 6.0 | 4.0 | +15.6x | +7.26x | +1.01x | −28.7% | −56.5% |
| QQQ | 73.1% | 172 | 5.0 | 4.0 | +7.0x | +6.57x | +0.06x | −58.3% | −83.0% |
| IWM | 67.3% | 223 | 4.5 | 3.0 | +5.5x | +1.74x | +1.39x | −34.4% | −59.5% |
| XLK | 71.8% | 178 | 6.0 | 3.0 | +7.7x | +9.11x | −0.14x | −49.9% | −82.0% |
| XLV | 68.5% | 313 | 3.0 | 3.0 | +5.2x | **+0.18x** | **+4.25x** | −55.1% | −40.6% |

Price sits above its own 200-day SMA roughly two-thirds to three-quarters of the time across all five
symbols — the filter is not a rare-event gate, it is the default state. Transitions (whipsaws) are
frequent: 172–313 over each symbol's full history, with median *unfavorable* episode lengths of only
3–4 trading days (favorable episodes run a bit longer, 3–6 trading days median), meaning most
"unfavorable" spells are brief and the filter would flip a position in and out repeatedly rather than
sitting out one long bear market cleanly.

**The single most important number in this report is XLV's row.** Splitting XLV's full daily-return
history by regime and compounding each subset *separately* (compounding is multiplicative, not
additive, so the two pieces recombine as `(1 + fav) x (1 + unfav) - 1`, not by simple addition):
days classified "favorable" (price above its 200-day SMA) compounded to **+17.8%** over 27 years on
their own; days classified "unfavorable" (below the 200-day SMA) compounded to **+424.7%** on their
own. Multiplied together, `1.178 x 5.247 - 1 ≈ 5.18`, which reconstructs XLV's actual +518%
buy-and-hold total return. In other words: almost the entirety of XLV's real historical gain happened
on days this exact filter would classify as unfavorable. A frictionless, hindsight-timed "only hold
when favorable" version of XLV would have captured roughly +18% instead of +518% — essentially none of
the instrument's real return — while still carrying a worse frictionless max drawdown (−55.1%) than
plain buy-and-hold (−40.6%). This is the
deliberate reason BRIEF.md keeps XLV in the primary universe rather than three views of the same
large-cap-tech complex: **the regime filter's value is not universal, and on the one clearly
non-tech-proxy symbol in this universe, it would have been actively harmful to apply mechanically.**
SPY, QQQ and XLK show the more conventional pattern (favorable-regime days contribute most of the
gain, frictionless favorable-only max drawdown is meaningfully shallower than buy-and-hold's), but even
there the *costed* version (section 4a, trend-ma's own numbers) never beats buy-and-hold on total
return, because whipsaw trading frictions eat the theoretical drawdown-avoidance benefit.

### 5c. Loss streak / worst trade (the note's "no single trade or loss streak" claim)

| symbol | closed trades | longest losing streak | worst single trade | strategy max DD | BH max DD |
|---|---|---|---|---|---|
| SPY | 111 | 10 | −5.3% (2009-06) | −30.5% | −56.5% |
| QQQ | 86 | 9 | −8.7% (2020-03, COVID) | −54.3% | −83.0% |
| IWM | 112 | 10 | −10.3% (2008-09) | −39.4% | −59.5% |
| XLK | 89 | 12 | −9.3% (2020-03, COVID) | −52.8% | −82.0% |
| XLV | 156 | **18** | −7.6% (2020-03, COVID) | −55.1% | −40.6% |

No single trade is catastrophic on its own (worst single loss tops out at −10.3%, on a strategy with
no explicit stop attached here) — but **loss streaks of 9–18 consecutive losing trades occur on every
symbol**, and the strategy's own max drawdown is *worse* than buy-and-hold's on XLV specifically (see
5b). "No single trade... can significantly damage the whole portfolio" holds in the narrow sense that
no one trade in this data is a blowup; "no loss streak can significantly damage the whole portfolio" is
not supported by XLV's numbers, where the regime-gated strategy's drawdown exceeds buy-and-hold's.

---

## 6. Replication

**Not run.** The DSL primary family (section 3a) produced **zero survivors** — BRIEF.md section 6 is
explicit that the replication universe runs only for ideas that survived the primary family. The
seasonality and VIX families are not DSL families and the replication-universe protocol as written
applies to the DSL primary family specifically; both also produced zero survivors at the primary-family
level, so there is no idea from any of this stream's ledgers to carry forward.

---

## 7. What this cannot tell you

- **The seasonality family's real power is much lower than 75 "tests" suggests.** Every bucket's
  independent sample size is bounded by the number of years of history (25–34 observations per cell) —
  this is the "~30 observations, not 630 days" point BRIEF.md makes, and it means even a genuinely real
  multi-decade seasonal effect of modest size would be hard to distinguish from noise in this data,
  full stop. A null result here is a real null result at this study's power level, not proof no
  seasonal effect could ever exist.
- **The VIX `p80` threshold is not a tradable rule as constructed.** It is computed from the symbol's
  *entire* cached history, including dates after any given trigger — a trader on any historical day
  could not have known the eventual 80th percentile of a series that hadn't finished yet. It is
  reported as a distribution-relative description, not evidence a real-time-computable version would
  behave the same way.
- **Overlapping windows, one historical path.** Every `n_independent` in this report discards
  overlapping forward windows, but the independent subset is still one draw from one 27-year sequence
  of macro history (dot-com, 2008, COVID, 2022) for SPY/QQQ, and shorter but still single-path
  histories for IWM/XLK/XLV. IWM (2000-) and XLK/XLV (1998-) do not share SPY/QQQ's full dot-com-crash
  history.
- **Instrument correlation.** SPY, QQQ and XLK are three views of the same large-cap growth complex
  (BRIEF.md section 2); a pattern appearing on all three and not on IWM/XLV is evidence about
  large-cap tech specifically, not three independent confirmations. Section 5b's XLV finding is the
  clearest illustration in this report of why that separation matters.
- **The regime-value analysis (section 5b/5c) is entirely descriptive.** No baseline, no p-value, no
  correction — it describes what happened on one historical path, the same epistemic status
  `quantlab.drawdown_profile` carries. "XLV's return came almost entirely from below-200MA days" is a
  fact about 1998–2026 XLV, not a forecast about any period going forward, and not a claim that being
  below a moving average is generally favorable.
- **The ATR-proportional sizing simulation (section 4c) tests nothing.** It reports what one specific,
  reasonable-but-arbitrary sizing rule (inverse to trailing ATR%, rescaled to unit average exposure,
  capped at 3x) would have done to volatility and drawdown on one historical path, with one choice of
  cap. A different cap, a different rescaling target, or a different lookback would produce different
  numbers; no significance claim attaches to any of them.
- **A backtest is not a forecast**, and nothing in this report is investment advice or a
  recommendation to hold, avoid, buy, or sell any instrument named in it — including `below_200ma_regime`
  and `unfavorable_regime_pullback`, which are statistical probes of forward-return behavior in a
  named state, not proposed trades.

---

## 8. What could not be expressed, and what was done instead

- **ATR-based position sizing (note p.2), literally.** `app.backtest.strategy`'s own module docstring:
  the engine is long-only, all-in on every entry, no pyramiding, and `Costs.notional` "is not a
  position-sizing decision... it lives here... rather than as a constant buried in the simulator." No
  `StrategySpec` field exists to size a position at all, let alone size it inversely to volatility. What
  was done instead: (a) `StrategySpec.stop_loss_pct` *is* backtestable, so stop *distance* — the one
  ATR-derived risk parameter the engine actually prices — was tested through the real engine (section
  4b), fixed-percent vs ATR-1x/2x/3x-typical, per symbol, explicitly labelled mechanics-only with no
  p-value attached (a stop does not change an entry's hit rate); (b) ATR-*proportional* sizing applied
  to a simple always-in position was simulated descriptively, entirely outside the engine, in pandas
  (section 4c), also explicitly labelled with no p-value. The boundary between (a) and (b) is: (a) went
  through `app.backtest.strategy.backtest` with a real `StrategySpec`, real fills, real slippage; (b)
  never touched `app.backtest.strategy` at all — it is `close.pct_change()` times a hand-built daily
  weight series.
- **Max drawdown cap as a portfolio-level circuit breaker (note p.2).** Not expressible — the engine has
  no "halt trading if portfolio drawdown exceeds X" construct; `StrategySpec.stop_loss_pct` caps one
  trade's loss, not the portfolio's. Not attempted; flagged rather than approximated.
- **Seasonality (note p.10) — no date/month operator in the rule DSL.** Tested directly in pandas on
  the bars frame (section 1b), reusing the app's own `binomial_p_value`/`benjamini_hochberg` for every
  statistic, with the full discipline BRIEF.md asks for (independent n, declared family size up front,
  BH correction across all 75 buckets together, direction checked only where a genuine directional
  claim exists).
- **VIX-conditioned entries (note p.11) — the DSL evaluates one symbol's frame at a time**, and a
  VIX-vs-SPY join is a second symbol's series. Tested directly in pandas (section 1c), reusing
  `app.backtest.forward`'s exact forward-return/independent-count/hit-rate implementation (the same
  functions `event_study` calls internally) rather than reimplementing them — the only new code is the
  trigger mask, which the DSL cannot express.
- **CNN Fear & Greed (note p.11) — untestable, architecturally, not just today.** `app.market.macro
  ._SERIES_CATALOG` (the dict `load_series`, the one function capable of returning *history* for
  anything, dispatches on) has **no Fear & Greed entry** — confirmed directly against the running
  application in `scripts/regime_risk_feargreed_check.py` (`data/regime_risk_feargreed_check.json`: 26
  ids in the catalog, none of them Fear & Greed). `load_fear_greed`/`build_snapshot` return exactly one
  `FearGreed` object — "right now" — rebuilt fresh (behind a 24-hour cache) on every call; nothing
  appends it to a growing, queryable series the way `app.market.store` does for `^VIX`. This report
  makes no live network call of its own to re-verify; it cites the macro stream's own already-fetched
  evidence instead (`data/macro_snapshot.json`, `app_macro_panel.fear_greed`, produced by
  `scripts/macro_snapshot.py`, not this stream): CNN's live endpoint, when reachable, does embed a
  trailing composite-score history (`n_history_points=251`, spanning 2025-08-11 to 2026-08-11 in that
  run) via `CnnFearGreedProvider._parse_history`, but it is (1) never persisted anywhere the harness can
  reach, (2) discarded the instant the call returns, and (3) at ~1 year, an order of magnitude short of
  the multi-decade history this study's independent-sample discipline needs even if it *were*
  persisted. **This absence — no store, no history, no join target — is itself the finding**, not a
  gap this report is declining to fill.
- **Multi-timeframe / portfolio-level circuit breakers, VIX real-time percentile thresholds.** See
  section 7's caveats on the `p80` threshold above; not re-listed here to avoid duplication.

---

## Application bug found

**None.** The `OverflowError` the prior study documented in `app.backtest.scan.binomial_p_value`
(`math.comb` on trial counts in the thousands overflowing on int-to-float conversion) is **no longer
present** — the current implementation (read in full before writing any script in this stream) computes
every pmf term in log space via `math.lgamma`, exactly the fix the prior study's report recommended,
and this stream's VIX family deliberately exercises trial counts in the same range that used to crash
(`n_raw` up to 3,182 in `regime_risk_vix.py`) with no error. No new bug was found in any module this
stream touched (`app.backtest.strategy`, `app.backtest.forward`, `app.backtest.scan`,
`app.backtest.events`, `app.backtest.guards`, `app.indicators.volatility`, `app.market.macro`,
`app.market.fear_greed`, `app.market.providers.cnn`).
