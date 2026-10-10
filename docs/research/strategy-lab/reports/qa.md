# QA review — adversarial pass on the strategy-lab study

Reviewer stream `qa`. Every number below was reproduced by reading the JSON in `data/` directly (via
short read-only Python snippets against the actual files) or by reading the cited source in
`backend/app/backtest/`, `backend/app/thesis/`. Nothing here was taken on the reports' word alone.
Nothing in `data/`, `scripts/`, `reports/`, `lib/quantlab.py`, or application source was modified.

**Bottom line up front.** The study's central negative finding — 0 of 150 pooled primary tests
survived — is sound and independently reproduced from `data/meta_correction.json`. The four
specifically flagged "over-read risk" claims all check out arithmetically and are honestly framed.
The one real defect worth taking seriously is a harness-level artifact in how regime *windows*
(not the primary hit-rate tests) recompute indicator warmup, which silently truncates exposure in
every short regime window for every long-lookback idea across all four streams — including the
coordinator's own GFC backfill. It does not touch the 0/150 headline, but it does undermine several
specific "regime breakdown" narrative claims that were stated with more confidence than the mechanism
supports.

---

## 1. Confirmed defects, ranked by impact

### 1a. [HIGH] `slice_window` + `run_family`'s window backtests silently truncate exposure for any
long-lookback indicator, most severely in the shortest windows — undisclosed in every report

**The mechanism.** `quantlab.slice_window` resets the bar index at the window boundary and recomputes
every indicator from bar 0 of the slice (`lib/quantlab.py:133-144`, docstring: "Indicator warmup is
recomputed inside the slice, which is the point"). `strategy_backtest` then evaluates the entry/exit
expressions against that truncated frame (`app/backtest/strategy.py:220`,
`evaluator.evaluate(node, bars, ...)` on whatever frame it's given). For any expression referencing
`sma(200)`, this means the condition is `NaN` (unknown, not false) for the first 200 bars *of the
window*, regardless of what the true `sma(200)` value — computed from real, pre-window price history —
would have been. This is not lookahead protection (the excluded data is strictly in the past); it is a
lookback-deprivation bug: the window is blind to real trailing history a live trader would have had.

**Reproduction 1 — `below_200ma_regime`, SPY, `bear_2022` window** (the shortest window in the study,
252 trading days):

```
full-history sma(200): SPY first crosses below on 2022-01-21; below 200MA for 84.9% of the year
window-recomputed sma(200): first computable value only at bar 199 -> 2022-10-18
window-recomputed: below 200MA for only 19.5% of the year
```

`data/regime_risk_dsl_primary.json`'s own reported cell for this window
(`per_symbol.SPY.ideas.below_200ma_regime.windows.bear_2022`) shows `exposure: 0.1952...`, `trades: 2`
— matching the truncated 19.5% exactly, not the true 84.9%. The regime-risk report reads this as
"loses less than buy-and-hold during drawdowns (... bear_2022 +5.9% vs BH −20.2%)" (§5a) — true as a
number, but the mechanism is largely "the strategy was mechanically unable to detect the crash for the
first ~10 months of the window," not "the filter correctly read the regime and got long only for the
Q4 partial recovery." No report states this.

**Reproduction 2 — `below_200ma_regime`, all five primary symbols, the GFC backfill window**
(2007-11-01 to 2009-03-31, 355 bars — the coordinator's own `meta/backfill_gfc_window.py`):

```
SPY: exposure=0.437, XLK: exposure=0.437   (== exactly 155/355, the post-warmup fraction of the window)
QQQ: 0.434, IWM: 0.392, XLV: 0.428          (same ceiling, modulo real transitions after warmup)
```

200/355 = 56.3% of this window is warmup-blind. SPY was persistently below its 200-day SMA for
essentially the entire real GFC crash (a well-documented fact — it crossed below in December
2007/January 2008 and did not cross back until mid-2009), so the *true* exposure for
`close < sma(200)` over this window should be close to 100%, not capped at 43.7%. Of the 41 GFC-window
cells that recorded zero trades (the count the coordinator's own script reported: 41 never-traded, 109
traded with only 10 profitable, all 150 nominally "beat" a catastrophically negative buy-and-hold),
**38 of the 41 reference `sma(200)` in their entry expression** — a population squarely at risk of
this artifact, though whether any specific zero-trade cell would actually have fired earlier with full
pre-window history cannot be determined without re-running the strategy on unsliced bars with a
window-restricted *reporting* range instead of a window-restricted *computation* range.

**Severity is inversely proportional to window length**: `bear_2022` (252 bars, ~79% blind),
`gfc_2007_2009` (355 bars, ~56% blind), `covid_2020_2021` (~500 bars, ~40% blind — consistent with the
suspiciously identical `exposure: 0.604` seen on SPY/QQQ/XLK for `regime_filter_standalone` in that
window in `trend_ma_primary.json`), `dotcom_2000_2002` (756 bars, ~26% blind, concentrated at the very
start of the actual crash), down to `qe_bull_2009_2019` (~2,700 bars, ~7% blind, immaterial).

**What this does and does not undermine.** The primary family's hit-rate/p-value/q-value statistics
(the actual 0/150 headline) are **not affected** — `run_family` computes `event_study` on the full,
unsliced `bars_frame(symbol)` result, not on a window slice (`lib/quantlab.py:358,377-383`); windowing
only touches the `strategy_backtest` calls made per-window for the descriptive mechanics tables. What
it does undermine: every report's §5 "Regime breakdown" narrative for any idea referencing `sma(200)`
or `sma(50)` in a window shorter than roughly 1,000 bars, and — most consequentially — the precision of
the coordinator's own 41/109/10 GFC decomposition, some fraction of which is a data-availability
artifact rather than a genuine absence of signal. The qualitative shape of that finding (most
regime-gated rules avoided the worst of the crash, few of the ones that traded made money) likely
survives, but the exact cell-by-cell "never traded" attribution should not be read as "the condition
never held" — it should be read as "the condition was never observable to this window's own
recomputation," which is a different and weaker claim. `trend-ma`'s explanation for
`golden_cross_sma`'s zero-trade windows ("the 50/200 relationship was already established before each
window opened and never flipped inside it," §5) states knowledge the window-sliced computation cannot
actually have — the harness cannot see anything about the pre-window state at all, by design.

**Not a new statistical bug** — it is a design choice (`slice_window`'s docstring calls the
truncation "the point") whose real-world consequence was not measured or disclosed by any of the four
streams that use it. No report mentions "warmup" anywhere (checked by grep across all six `reports/*.md`
files — zero hits).

### 1b. [MEDIUM] `beats_buy_hold_total_return` is trivially `True` for a strategy that never traded, and
this is the mechanical explanation for a large share of the coordinator's "150 of 150 beat buy-and-hold"
GFC finding — confirmed, and the harness field does not qualify it

Independently reproduced from `data/gfc_backfill.json`:

```
total cells: 150, beat_buy_hold: 150 (exactly matches the file's own beat_buy_hold.count/of)
never-traded cells (strategy.trades == 0): 41
traded cells: 109, of which profitable (total_return > 0): 10
```

Example (`data/gfc_backfill.json`, `mean-reversion/sma200_only/SPY`): `strategy.total_return = 0.0`,
`buy_hold.total_return = -0.475`, `beats_buy_hold_total_return = True`. This is arithmetically correct
— 0.0 is greater than −0.475 — but it means "beat buy-and-hold" for 41 of the 150 cells means nothing
more than "sat entirely in cash while the market fell," not "the rule protected capital by correctly
reading the regime." `lib/quantlab.py`'s `strategy_backtest` (`beats_buy_hold_total_return`,
lines 271-275) does not distinguish a strategy with zero trades from one that traded and simply lost
less; both produce `True` under the same boolean. This is confirmed as the coordinator's own finding
(the task brief that spawned this review states the same decomposition), and this review corroborates
it exactly rather than merely repeating it. **No report currently cites the GFC-backfill "150 of 150"
figure as a finding** — a grep for "150 of 150," "gfc_backfill," and "0 of 150 pooled primary tests"
across every report file returns nothing — so this is not, today, a claim any stream is making that
needs correcting. It is flagged here because it is exactly the kind of number that would be quoted
uncritically in a future consolidated summary, and the field that would produce it (`beats_buy_hold_
total_return`) does not carry the qualification needed to use it safely.

### 1c. [LOW] `meta/meta_correction.py`'s own module docstring cites a stale illustrative number

The docstring's worked example claims `trend-ma`'s XLV `intermediate_cross_ema20_sma50` cell (p=0.0176)
"had q = 0.793 inside its own 45-test family and q = 0.458 in the pooled 130-test one." Reproduced
directly from `data/meta_correction.json`: `q_value = 0.7930`, `q_value_studywide = 0.5288`, not 0.458.
The qualitative point the docstring is illustrating (pooling is not monotonically stricter — this cell
improves under pooling) is still true and still correctly demonstrated by the real number; only the
specific illustrative figure in a comment is stale, most likely written against an earlier partial run
before all four primary families existed. This affects no report and no reader-facing number — it is a
one-line documentation staleness issue in a script's docstring, noted for completeness per the brief's
instruction to report what was checked, not because it changes any conclusion.

---

## 2. Family integrity — clean

Verified programmatically against all four `data/*_primary.json` files:

| file | family_size | ideas×symbols | len(cells) | idea keys match declared | guard status |
|---|---|---|---|---|---|
| mean_reversion_primary.json | 40 | 8×5=40 | 40 | yes | 40/40 entry passed, 30/30 exit passed (2 ideas have no exit) |
| momentum_primary.json | 45 | 9×5=45 | 45 | yes | 45/45 entry passed, 45/45 exit passed |
| regime_risk_dsl_primary.json | 20 | 4×5=20 | 20 | yes | 20/20 entry passed, 20/20 exit passed |
| trend_ma_primary.json | 45 | 9×5=45 | 45 | yes | 45/45 entry passed, 45/45 exit passed |

150 total, matching `data/meta_correction.json`'s `pooled_family_size: 150` exactly (40+45+20+45).
`meta_correction.json`'s `survived_within_stream`, `survived_study_wide`, and `demoted_by_pooling` are
all empty lists — independently confirms **0 of 150 survived either the within-stream or the
study-wide correction**. No `"error"` key appears anywhere in any file under `data/` (grepped the whole
directory) — no silently dropped symbol or masked exception corrupted any family anywhere in the
study. No stream ran an idea it did not report: every `*_primary.json`'s `cells[*].idea` set is
identical to its own `ideas_declared[*].key` set.

The seasonality (75 cells) and VIX (15 cells) sub-families in `regime-risk` are correctly excluded from
the pooled study-wide ledger — they don't match the `*_primary.json` glob `meta_correction.py` uses,
and the `regime-risk` report itself treats them as separate, non-primary ledgers (§1 of that report).
This is consistent with the study's own stated design, not an omission.

---

## 3. The four flagged over-read risks

### 3a. XLV +17.8% / +424.7% compounding split — **survives scrutiny**

Reproduced exactly from `data/regime_risk_regime_value.json` →
`per_symbol.XLV.drawdown_avoided`: `favorable_days_contribution = 0.177648...`,
`unfavorable_days_contribution = 4.247474...`, `buy_hold_total_return = 5.179678...`. Recombining
multiplicatively — `(1 + 0.177648) × (1 + 4.247474) − 1 = 5.179678` — matches the reported buy-and-hold
return to 13 decimal places (floating-point exact). The method (`scripts/regime_risk_regime_value.py`)
gates on `state.shift(1)` (yesterday's regime decides today's exposure), which is correctly lookahead-
safe. Checked for robustness across the other four primary symbols, which the report itself does: SPY,
QQQ, and XLK show the conventional pattern (favorable days dominate: +7.26x, +6.57x, +9.11x
respectively vs. unfavorable's +1.01x, +0.06x, −0.14x); only IWM (+1.74x fav / +1.39x unfav) is close
to even. XLV is a genuine outlier, not a universal artifact of the method, and the report says so
explicitly rather than implying the pattern is general. XLV also has the most regime transitions of any
symbol (314 episodes vs. 172–224 for the others), a real, disclosed, and plausible contributor (shorter,
choppier regime episodes mean big single-session moves are more likely to land on the "wrong" side of a
lagged 200-day filter). The report's framing ("nearly all of XLV's real gain happened on days this
filter calls unfavorable") is supported by the numbers as computed and is appropriately hedged
elsewhere in the same report (§7: "a fact about 1998–2026 XLV, not a forecast... not a claim that being
below a moving average is generally favorable"). **No defect found.**

### 3b. Momentum divergence diagnostic (+3.9–6.4% bullish vs +0.3–0.5% baseline) — **survives scrutiny**

`data/momentum_divergence_diagnostic.json` has `"p_value": null` at the top level and
`"descriptive_only": true`, `"guarded_rule_engine": false`. Per-symbol event counts and returns match
the report table exactly (spot-checked SPY: `bullish_events.count=23`, `mean_forward_return=0.05826`
≈ +5.83%; `bearish.count=97`, `mean=-0.01177` ≈ −1.18%; `unconditional_baseline.mean=0.00388` ≈
+0.39% — all match the report's table to the decimal). Event counts really are small (17–27 bullish
events per symbol over 26–34 years, well under one per year, exactly as claimed). The report explicitly
labels this "not a finding of this study and must not be cited as evidence that divergence 'works'"
(§8) and it is correctly excluded from the corrected 45-cell family and from every verdict in §§2–6.
**No defect found.**

### 3c. trend-ma's "verbatim ordering beats conventional" — **survives scrutiny**

`data/trend_ma_primary.json`'s `ideas_declared` confirms the two expressions exactly as the report
describes them:

```
ideal_entry_verbatim:            ema(20) > sma(50) and sma(50) > ema(10) and ema(10) > sma(200)
stacked_alignment_conventional:  ema(10) > ema(20) and ema(20) > sma(50) and sma(50) > sma(200)
```

The first is a literal, internally-unusual encoding of the note's stated order (50SMA sits ahead of
10EMA, which is not how a normal "fastest MA on top" stack reads); the second is the conventional
fastest-on-top fix. Both use the same exit, horizon (20), and direction. Cross-checked every symbol's
edge in `data/trend_ma_primary.json`'s `cells`: `ideal_entry_verbatim`'s edge exceeds
`stacked_alignment_conventional`'s on all 5 symbols (0.095 > 0.010, 0.063 > 0.003, 0.080 > −0.046,
0.121 > 0.008, 0.058 > −0.027) and never goes negative, while the conventional reading is `rejected`
(negative edge) on IWM and XLV. The report's caveat that "of two ideas that both failed to reach
significance, one failed slightly less badly" (§7) correctly prevents this from being over-read as a
positive finding. **No defect found.**

### 3d. Coordinator's own GFC decomposition (41 never-traded / 109 traded / 10 profitable) — **confirmed
correct as computed, but see §1a for why the "never traded" bucket needs a caveat**

Independently recomputed from `data/gfc_backfill.json` (method in §1b above): 150 total cells, 150
beat buy-and-hold, 41 never traded, 109 traded, 10 of the 109 profitable. All four numbers match
exactly. `beats_buy_hold_total_return`'s handling of the zero-trade case is confirmed to produce the
misleading "150 of 150" headline mechanically (§1b). The size of the never-traded bucket (41) is itself
partly a consequence of the warmup-truncation bug in §1a (38 of the 41 reference `sma(200)`, and the
GFC window is short enough — 355 bars — that 56% of it is warmup-blind for any such expression), which
this review surfaced independently while checking the decomposition's robustness.

---

## 4. Buy-and-hold and exposure honesty — clean

Every report states underperformance in plain words, not just a number: mean-reversion ("Not one of the
32 backtested idea×symbol combinations beats buy-and-hold on total return"), momentum ("Every one of the
45 idea/symbol combinations trails buy-and-hold on total return. No exceptions."), trend-ma ("44 of 45
cells underperform buy-and-hold on total return"), regime-risk ("Every single cell trails buy-and-hold
on total return, and none beats it on Sharpe either"). Where a rule does beat buy-and-hold on Sharpe
(trend-ma's `golden_cross_sma`/QQQ; several low-exposure regime-risk/mean-reversion cells), every
instance found in this review is qualified with the exposure context, not presented bare — e.g.
mean-reversion §4's explicit paragraph: "a strategy that is flat 25-70% of the time has a mechanically
different risk profile from one that is always invested, and Sharpe alone, on a partly-flat equity
curve, is not a substitute for that comparison." This matches the brief's requirement in both spirit
and the literal words used. **No defect found.**

---

## 5. Guard status — clean

Programmatically counted every `guard_entry.status` and `guard_exit.status` value across all four
`*_primary.json` files (§2's table above): every value present is `passed`. Zero occurrences of
`unverified` or `failed` anywhere in any primary family. This matches every report's prose claim, and
was verified from the JSON rather than taken from the prose, per the brief's instruction.

---

## 6. The DuckDB `IOException` infrastructure bug — no other occurrence found

Grepped every file under `data/` for `IOException`, `error`, `refused`, `refusal`, `SymbolNotFound`,
`HoldoutUnavailable` (case-insensitive). The only hits are in `data/universe.json`'s own narrative
fields describing the incident it already documents (four symbols recovered on retry: QUAL, MTUM,
VLUE, VWO) — its final `"refused": {}` block is empty, confirming all 56 candidates resolved cleanly in
the file actually used for the report's tables. No `"error"` key exists anywhere else in any JSON file
in the study (a literal string search for `"error"` across the entire `data/` directory returns zero
matches outside that one file's prose). The `momentum` stream's own account of hitting the same bug
twice (documented in its "Application-level observation" section with a reproduction and root-cause
analysis pointing at `app/market/store.py::read_frame` defaulting to `read_only=False`) is consistent
with — and does not conflict with — `universe`'s account. No silently-dropped symbol or masked data
refusal was found anywhere else in the study.

---

## 7. Advice framing — clean

Grepped every report for buy/sell/recommendation-adjacent phrasing (`buy signal`, `is a buy`, `is a
sell`, `attractive entry`, `good opportunity`, `worth buying`, `time to buy`, `time to sell`, `you
should`, `we recommend`, `consider buying/selling`, `good entry point`, `now is a good time`). The one
hit (`momentum.md`, "RSI<30 is an oversold buy signal (p.7)") is the report quoting the *note's* claim
verbatim inside a "what the note claims" table cell, immediately followed by the report's own neutral,
corrected verdict in the adjacent column — not the report's own framing. No report anywhere frames any
instrument as one to buy, sell, or hold, and every report carries the required "not investment advice"
disclaimer. **No defect found.**

---

## 8. The harness (`lib/quantlab.py`)

- **`_p_value`'s `round(hit × n_indep)` reconstruction — not a harness-introduced bug.** Traced to
  `backend/app/thesis/loop.py:197-198`: `successes = round(rate * independent)` followed by
  `binomial_p_value(successes, independent, baseline)` — the identical formula, and the surrounding
  comment in that file states plainly: "Successes among the independent subset are not directly
  observed... this is the same documented approximation `app.backtest.scan` makes, and it is an
  approximation rather than a derivation." `quantlab.py`'s docstring accurately attributes this to the
  app's own convention. It is a known, disclosed, pre-existing simplification in production code that
  the harness faithfully reproduces rather than a defect this study introduced. Worth naming for a
  reader who assumes "exact binomial p" means the reconstructed count is directly observed — it is not,
  in the harness or in the app it mirrors.
- **`_verdict`'s direction-before-power ordering** produces `rejected` (not `underpowered`) for a
  wrong-direction edge even at very small `n_independent` — confirmed in `trend_ma_primary.json`
  (`golden_cross_sma`/XLV: `n_independent=23`, edge=−0.018, verdict=`rejected`, while every other
  `golden_cross_sma` cell with a positive edge and similarly small `n` is `underpowered`). This matches
  BRIEF.md §5.4's explicit instruction ("direction is checked before significance... rejected, not
  inconclusive") and every report that hits this case states the small `n` alongside the verdict rather
  than hiding it (trend-ma §Q2: "outright rejected on XLV (edge -0.018, n_independent=23)"). Working as
  specified; not a defect.
- **`run_family`'s BH pool is exactly `len(ideas) × len(symbols)`**, one cell per idea per symbol at
  that idea's own declared horizon — confirmed by the family-size table in §2 above; no double-counting
  found.
- **`horizon_sweep` and `run_family` do not double-count.** They write to separate JSON files with
  separate BH ledgers (`*_horizon_sweep.json` vs `*_primary.json`), and `meta_correction.py`'s glob
  (`*_primary.json`) only pools the latter. Confirmed `mean_reversion_horizon_sweep.json` (200 cells =
  8 expressions × 5 symbols × 5 horizons) and `trend_ma_horizon_sweep.json` (225 = 9×5×5) are structured
  as separate files with their own `q_value`, never merged into `data/meta_correction.json`.
- **`slice_window` / windowed `strategy_backtest` calls** — see §1a. This is the one place a harness
  behavior materially affects reported numbers across all four streams at once, and it is not disclosed
  anywhere it's used.
- **The prior study's `OverflowError` in `binomial_p_value`** is confirmed fixed: `backend/app/backtest/
  scan.py` computes every pmf term via `math.lgamma` in log space (lines ~74-115), exactly as three
  independent reports (regime-risk, trend-ma, mean-reversion) each verify by name. Confirmed directly by
  reading the source.

---

## 9. What this review could not verify

- **Whether any specific GFC-window "never traded" cell would have actually fired given full pre-window
  indicator history.** Confirming this would require re-running `strategy_backtest` against the full,
  unsliced `bars_frame` and then restricting the *reported* trade/equity range to the window — a
  different computation than `slice_window` performs, and one this review did not construct (doing so
  would mean writing new code against the harness, which the brief's scope reserves for repair, not
  review). §1a's reproductions establish the mechanism and its direction (severe undercounting of
  exposure) but not the exact corrected trade count for every affected cell.
  - **Flagged for follow-up:** `meta/backfill_gfc_window.py`'s `beats_buy_hold` decomposition (41
    never-traded / 109 traded / 10 profitable) should be re-run against full-history-computed
    indicators restricted to the window's reporting range, rather than window-recomputed indicators, to
    get a trustworthy per-cell trade count for the GFC window specifically.
- **The precise degree to which regime-window "loses less than buy-and-hold in a crash" claims across
  all four primary reports are attributable to genuine regime-avoidance vs. warmup truncation**, on a
  cell-by-cell basis. §1a establishes the mechanism is real and material for short windows; apportioning
  the effect for every affected cell in every report was out of scope for this pass.
- **CNN Fear & Greed provider claims (regime-risk §8, macro report)** — this review did not make a live
  network call to re-verify the catalogue/history claims; both reports already flag this limitation
  themselves and this review did not attempt to independently confirm live-endpoint behavior.
- **Live macro/news claims in `reports/macro.md`** (Fed policy, jobs data, earnings season commentary) —
  out of scope for a reproducibility review; these are sourced/dated citations, not computed statistics,
  and this review did not re-fetch any of the cited URLs.

---

## Summary for the record

- **Ranked confirmed defects**: (1) undisclosed indicator-warmup truncation in every regime-window
  backtest, most severe in the shortest windows — HIGH; (2) `beats_buy_hold_total_return`'s unqualified
  `True` for zero-trade cells, confirmed as the mechanical source of the coordinator's 150/150 GFC
  figure — MEDIUM, not currently cited in any report; (3) one stale illustrative number in
  `meta_correction.py`'s docstring — LOW, cosmetic only.
- **The four flagged over-read risks**: all four survive scrutiny. The XLV compounding split, the
  momentum divergence diagnostic, and the trend-ma verbatim-ordering claim are each arithmetically exact
  and honestly framed in their reports. The coordinator's own GFC decomposition is numerically correct
  as computed but its "never-traded" bucket is now understood to be partly an artifact of defect (1),
  which this review surfaced while checking it.
- **Harness bug**: no bug in the statistical core (`event_study`, BH correction, `_p_value`,
  `_verdict`) that would bias the primary family's 0/150 result. The one real harness-level issue is
  `slice_window`'s warmup truncation in windowed strategy backtests (§1a/§8) — it affects descriptive
  regime-mechanics tables only, not the corrected hit-rate/p-value/q-value statistics that produce the
  study's headline.
- **Overall verdict on the central negative finding**: **sound.** 0 of 150 pooled primary tests
  survived Benjamini-Hochberg correction, independently reproduced from `data/meta_correction.json`,
  with every family's size, cell count, and idea/symbol declaration verified to match its report. The
  defects found in this review live entirely in the descriptive, non-corrected mechanics layer (regime
  windows, the GFC backfill's exposure figures) and in one unqualified boolean field — none of them
  touch the statistical machinery that produced the null result, and none of them would flip any
  individual verdict from `inconclusive`/`rejected` to `survived` or vice versa.
