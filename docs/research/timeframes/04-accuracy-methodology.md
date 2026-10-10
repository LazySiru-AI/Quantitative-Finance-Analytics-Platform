# Rule Accuracy Measurement Methodology

Status: design document, no code. Target: a dashboard cell answering "how accurate is rule R on
symbol/sector S at interval I over horizon H" without that number being an accident of the window it
was measured over.

**A scope correction, verified against the code rather than assumed.** `backend/app/db/duck.py`'s
`Interval` enum currently defines exactly four intervals: `5m`, `1h`, `1d`, `1w`. There is no `15m` or
`4h` anywhere in `app.db.duck`, `app.rules`, or `app.backtest` today. The brief's "5m/15m/1h/4h/1d/1w"
is the target shape of the feature, not the current data model. Everything below is written against
the four intervals that exist; a `15m`/`4h` addition is a data-layer change (new bar retention, new
`Interval` members) orthogonal to this methodology, and the methodology applies unchanged once they
exist. The same file also states, as a design constraint already enforced elsewhere in this codebase,
that `Interval.backtestable` is `True` only for `DAY` and `WEEK` — "Backtests are restricted to daily
bars because a 60-day sample cannot support a statistical claim." This document's job is to let 5m/1h
be *shown* honestly on a dashboard without pretending they clear that bar.

---

## 1. What `evidence.py` measures today

`backend/app/rules/evidence.py` (and its dependency `backend/app/backtest/forward.py`) is not a
placeholder — it already implements three of the four "honesty rules" this whole feature needs to
extend, not replace. Read `_evidence_for_horizon` first:

```python
def _evidence_for_horizon(
    signal: pd.Series, bars: pd.DataFrame, *, horizon: int, entry: Entry
) -> Evidence:
    returns = _forward_returns(bars, horizon=horizon, entry=entry)

    known_mask = signal.notna().to_numpy(dtype=bool)
    true_mask = signal.fillna(False).to_numpy(dtype=bool)

    evaluable = known_mask & ~np.isnan(returns)
    triggered = evaluable & true_mask

    baseline_sample = returns[evaluable]
    trigger_sample = returns[triggered]

    hit_rate = _rate(trigger_sample)
    baseline_hit_rate = _rate(baseline_sample)
    edge = None if hit_rate is None or baseline_hit_rate is None else hit_rate - baseline_hit_rate

    trigger_positions = np.flatnonzero(triggered)
    independent_sample_size = _independent_count(trigger_positions, horizon)
    ...
```

**A "hit" is defined precisely.** `forward_returns` (in `app/backtest/forward.py`) prices every bar
`t` at `NEXT_OPEN` by default: entry at `open[t+1]`, exit at `close[t+horizon]`, return =
`exit/entry - 1`. A hit is `hit_rate(values) = mean(values > 0)` — **strictly** greater than zero, not
`>=`, so a flat/stale-close bar is not counted as a win. `SAME_CLOSE` (entry and exit both priced off
`close`) exists solely as a research upper bound; the module docstring is explicit that it "assumes a
fill at a price that was actually obtainable... any figure computed this way is an upper bound on a
real result, never an estimate of one." Windows that fall off the end of the series are dropped, never
truncated to a shorter horizon.

**Horizons are fixed and bar-native.** `HORIZONS = (1, 5, 20, 60)` bars, declared in
`app/rules/models.py`, with the comment this document should not re-litigate: "'20 bars' is 20
opportunities to trade," not 20 calendar days.

**Overlap is already handled for the significance grade, not for the point estimate.**
`hit_rate`/`baseline_hit_rate`/`median_return` are computed over **every** triggered bar
(`trigger_sample`), overlapping windows included — a rule that fires on 400 consecutive 5m bars
contributes all 400 to the point estimate. What is *not* naive is the confidence judgment:
`independent_count` (in `forward.py`) runs a greedy, non-overlapping interval-scheduling scan over
trigger positions —

```python
def independent_mask(trigger_positions: np.ndarray, horizon: int) -> np.ndarray:
    mask = np.zeros(trigger_positions.size, dtype=bool)
    next_allowed = -1
    for i, t in enumerate(trigger_positions):
        if t < next_allowed:
            continue
        mask[i] = True
        next_allowed = t + horizon
    return mask
```

— and `Evidence.significance` is graded only off that count (`independent_sample_size`), never off the
raw `sample_size`. The grading itself is deliberately coarse, three levels, not a p-value:

```python
_MIN_INDEPENDENT_WEAK: Final[int] = 8
_MIN_INDEPENDENT_SUGGESTIVE: Final[int] = 30
_MIN_EDGE_WEAK: Final[float] = 0.15
_MIN_EDGE_SUGGESTIVE: Final[float] = 0.08
```

Both the sample-size and edge-magnitude condition must hold together (`_significance`), and the
`Significance` enum's own docstring says why nothing sharper is offered today: "a decision table
showing twenty rules is twenty simultaneous tests with no correction between them. Phase 7 adds the
FDR accounting that would justify a sharper claim." **This document is that Phase 7 accounting**,
generalized from one symbol/interval to the full rule × interval × ticker/sector × horizon grid.

**Unknown is not false.** `pd.NA` in the signal (indicator warmup, a data gap) is excluded from both
the trigger and baseline sets via `known_mask`, never folded into "did not fire."

**What evidence.py does *not* do today**, all of which this document must add:
- No cost/friction modeling. `Costs` (transaction costs, slippage, commission) lives only in
  `app/backtest/models.py` and is consumed only by `StrategyResult`/`app/backtest/strategy.py`, a
  fully separate code path (a real entry/exit simulation) that `evidence.py` never touches.
- No cross-ticker or cross-sector aggregation — one call is one `(signal, bars)` pair, i.e. one
  symbol at one interval.
- No regime conditioning — one call, one blended number over the whole stored history.
- No multiple-comparison correction across rules/symbols/intervals — only the single-cell
  significance grade above. `ScanResult`/`ScanEntry` (`app/backtest/models.py`) *do* already carry a
  full Benjamini-Hochberg implementation (`q_value`, `alpha: float = 0.10`, `discovery: bool`) for the
  backtest workbench's multi-condition scan — that is the precedent this document reuses in §4, not a
  new invention.

---

## 2. Defining rule accuracy

**Primary definition:**

> `hit_rate(rule, symbol, interval, horizon) = P(forward return over H bars > 0 | rule fired on bar t)`

using the existing `NEXT_OPEN` convention exactly as `forward_returns` computes it today. This is not
a new definition — it is `Evidence.hit_rate`, unchanged.

**A hit rate alone is not "accuracy."** It is a fact about one conditional probability that is
meaningless without knowing the unconditional one. If an instrument rises on 62% of all bars in a
window (a bull market), any signal correlated with "the market is generally up" — including one that
fires at random — will show `hit_rate ≈ 62%` and look "accurate" while containing zero information
about the rule. The base rate is not a nuisance parameter to footnote; it is the null the rule is being
tested against, and it must be computed over the **identical sample** (same symbol, interval, horizon,
entry convention, and evaluability mask) so the two numbers can be subtracted honestly:

> `base_rate = P(forward return over H bars > 0 | any evaluable bar in the same window)`
> `lift = hit_rate − base_rate`

This is exactly `Evidence.baseline_hit_rate` and the `Evidence.edge` property, generalized across the
grid. **Lift, not hit rate, is the headline number.** The argument for insisting on this, stated
plainly for the dashboard spec:

1. **A rule with zero skill has an expected lift of zero regardless of regime.** A coin-flip rule
   fires on ~50% of bars at random; its `hit_rate` tracks `base_rate` up and down with the market, and
   `lift ≈ 0` in a bull market, a bear market, and a chop market alike. `hit_rate` alone does not have
   this property — it inherits the market's drift.
2. **It is the only number that isolates the rule's own contribution.** `base_rate` already prices in
   everything a rule gets "for free" just by existing during a particular window (drift, that
   instrument's typical up-day frequency, whatever the sample's regime happened to be). Subtracting it
   is not a refinement of the headline metric, it *is* the metric.
3. **Any UI that renders `hit_rate` without `base_rate` adjacent, or renders `hit_rate` larger/bolder
   than `lift`, is manufacturing an edge that is not there.** This is not a stylistic preference; it
   is the same rule the existing `evidence.py` docstring and `frontend/src/api/rules.ts`'s own comments
   already assert ("Rendering the hit rate alone is the single easiest way to make noise look like a
   strategy") — this document extends that rule from one symbol to the whole feature and insists it be
   enforced structurally in the output schema (§9), not left to a component author's judgment.

Magnitude matters alongside direction: `median_return` vs `baseline_median_return` (already in
`Evidence`) answers "how big," which `hit_rate` cannot — a rule with `hit_rate` barely above baseline
but a much fatter positive tail is a different, and possibly more useful, finding than a rule with a
larger `hit_rate` edge and a thin one. Both should travel together (§9).

**Lift needs an uncertainty band, not a point estimate.** A `+4pp` lift on 9 independent episodes and a
`+4pp` lift on 400 are different claims; §3 and §9 specify how the interval is computed.

---

## 3. The overlapping-sample problem — concrete recommendation

The problem, stated in the terms the brief uses: 400 consecutive 5m bars where a condition holds is
not 400 observations of anything, and forward windows of nearby triggers overlap heavily even after
the condition has toggled off and on again. Two techniques already exist in this codebase for related
problems (`app/backtest/forward.py`'s greedy non-overlap scan; `app/discovery/stats.py`'s stationary
bootstrap). The recommendation is to stack three specific techniques, in this order, not to pick one
from a menu:

**1. Redefine "fired" as a rising edge for episode counting.** Today, `Evidence.sample_size` counts
*every* bar where `signal` is `True` — this is a change from current behavior and must be flagged as
such. Define an **episode** as `signal[t] is True and (t == 0 or signal[t-1] is not True)` — the first
bar of a run, not every bar in it. This matches how a rule would actually be traded (nobody re-enters
on bar 217 of an RSI-under-30 stretch that started on bar 200; they entered once, at the edge) and
matches the existing `HORIZONS` docstring's own framing of "opportunities to trade": 400 consecutive
firing bars under one persistent condition is one opportunity observed 400 times, not 400 opportunities.
Report both counts (`n_raw`, the old behavior; `n_episodes`, rising-edge count) — never discard the
raw count, since it still answers "how often is this condition true," a legitimate and different
question from "how many independent decisions did this represent."

**2. Apply the existing greedy non-overlap scan on top of the episode positions.**
`independent_count`/`independent_mask` already do exactly the right thing — greedy-earliest is optimal
for equal-length interval scheduling, so it recovers the *largest* non-overlapping subset, and it is
already tested and used for `Evidence.significance`. Run it on the rising-edge episode positions (not
the raw trigger positions) with the horizon in question: `n_independent =
independent_count(episode_positions, horizon)`. This is the number every gate and every confidence
statement in this document is built on (§4, §9) — never the raw bar count, and not even the
raw episode count on its own, since two episodes three bars apart under a 20-bar horizon still share
seventeen bars of the same forward path.

> **What actually shipped (recorded 2026-08-26): Newcombe, not the bootstrap.**
> `app/timeframes/stats.py` implements `lift_ci` as **Newcombe's (1998) hybrid-score interval** and
> `two_proportion_p` as a **pooled-proportion z-test**, rather than the stationary bootstrap this
> section recommends below. The reasoning is argued in that module's own docstring: the discovery
> package's bootstrap is built for a differently-shaped overlap problem (monthly rebalance decisions
> against annual horizons), and re-pointing it at this grid's already-de-overlapped episodes would
> have meant re-deriving its machinery for a much weaker dependence-repair job. Newcombe is
> conservative — it errs wide, not narrow — which is the correct direction to err for a study whose
> entire purpose is refusing to overclaim.
>
> This is a deliberate substitution, not drift. The section below is kept as the original reasoning
> and as the argument for what a future revision would need to beat. If the residual clustering
> concern it raises turns out to matter, the bootstrap is the upgrade path.

**3. Use a block/stationary bootstrap for the confidence interval and p-value on the surviving
episodes, not a naive binomial or normal approximation.** Non-overlapping windows are not the same as
independent draws — adjacent non-overlapping episodes can still cluster in the same trend leg (a
mean-reversion rule firing every few days through one choppy month is not "independent" of itself in
the way a coin flip is). `app/discovery/stats.py` already implements exactly the right tool for this —
`stationary_bootstrap_p` (Politis & Romano, 1994) — built to solve the identical problem for
overlapping decision dates in the discovery package:

```python
def stationary_bootstrap_p(
    series: Sequence[float], *, block: float = 3.0, seed: int = 0, draws: int = 10_000
) -> float | None:
    ...
```

Recommendation: apply this (or its percentile-bootstrap sibling for a CI rather than a p-value against
zero) to the per-episode forward-return series restricted to the `n_independent` surviving episodes,
with `block` set to a small constant (3–5) since these episodes are, by construction from step 2,
already non-overlapping in their forward windows — a much weaker dependence-repair job than the
discovery package's monthly-decision/annual-horizon case, which is exactly why a small block is
appropriate here and a larger one (as `stats.py` uses for 12-month overlap) is not. This reuses tested,
reviewed code rather than adding a new estimator, and produces `lift_ci_low`/`lift_ci_high` and a
`p_value` fit for the BH correction in §4.

**Do not use**: a raw binomial CI on `n_raw` (massively overstates confidence — this is precisely the
failure mode `evidence.py`'s own docstring calls "the standard error of a proportion... already ~18
percentage points at n=8"); a naive t-test on overlapping windows (the exact error `app/discovery/
stats.py`'s module docstring calls out: "a textbook t-statistic on such a series has an effective
sample size far below its nominal one and will report significance that is not there").

---

## 4. Multiple comparisons

**Scale.** ~11 catalogued rules × 4 supported intervals × M tickers (dozens to low hundreds once
individual names are added to the sector-ETF roster) × 4 horizons is easily 10,000+ cells; even a
modest universe of 50 tickers is `11 × 4 × 50 × 4 = 8,800`. Some fraction of these will clear any fixed
lift threshold by chance alone.

**Correction: reuse the codebase's own Benjamini-Hochberg implementation, not a new one.**
`ScanResult`/`ScanEntry` in `app/backtest/models.py` already carry a complete, tested FDR
implementation for exactly this problem in the backtest workbench (`p_value`, `q_value`,
`discovery: bool = q_value <= alpha`, `alpha: float = 0.10` — "higher than a conventional 0.05 on
purpose: this is a screening step... the expensive error here is discarding a real effect rather than
looking at one more chart"). Recommendation: use the identical `alpha = 0.10` default and the identical
BH procedure for the accuracy dashboard's `q_value` field.

**The unit of correction must be what a user's eye actually compares in one glance, not the global
cross product.** Correcting across all ~10,000 cells at once would crush power to near zero — at that
family size, BH's threshold for a p-value to survive at `alpha=0.10` is roughly `0.10 × k/10000`,
vanishingly small for anything but `k` in the single digits, which would make the dashboard report
almost nothing regardless of what is actually there. The honest "family" is the set of hypotheses a
viewer is implicitly comparing when they look at one screen: recommend correcting **within each
rendered slice** — one `(interval, horizon)` pair's row of rules × tickers, or one rule's row across
tickers at one interval — and stating the family size on the view exactly as `ScanResult.trials` does
today, so a reader can see "this q-value corrects for 47 simultaneous tests," not an unstated global
number.

**Minimum-sample gate: `n_independent >= 20`, below which a cell renders "insufficient data," not a
number.** Reasoning:

- This sits deliberately between `evidence.py`'s own two existing thresholds
  (`_MIN_INDEPENDENT_WEAK = 8`, `_MIN_INDEPENDENT_SUGGESTIVE = 30`) rather than reinventing a third
  scale. A dashboard that displayed a bare percentage below the codebase's own `WEAK` bar (`n < 8`)
  would directly contradict the `Significance` grade the same data already carries; 20 is the point at
  which a numeric display stops being strictly worse than what `Significance` already permits itself
  to call `WEAK`, while still requiring meaningfully more than the floor.
- At `n = 20`, the standard error of a proportion is `sqrt(0.25/20) ≈ 11pp` — still wide, but below
  it (`n < 20`) the SE exceeds 15pp, wider than almost any lift this feature will ever measure, so no
  bare percentage is defensible.
- **State the residual honestly rather than routing around it**: this gate will bind hardest exactly
  on 5m and 1h, the intervals users most want an answer for, precisely because those are also the
  intervals with the shortest history (60 and 730 days respectively, per `Interval`'s own docstring).
  A rule can clear thousands of raw triggers on 5m and still fail to clear 20 *independent* episodes at
  `H=60` bars (60 bars × ~5 minutes ≈ 5 hours, so a 60-day window holds at most a few hundred
  non-overlapping 60-bar windows total, and most rules fire far less often than every window). This is
  not a bug to be optimized away; it is the honest consequence of a genuinely short intraday sample,
  and the dashboard must say "insufficient data (n=6)" rather than hide the gate or lower it to make
  5m look populated.

Distinguish two thresholds on the cell, not one: `sufficient = n_independent >= 20` gates whether a
number is shown *at all*; `discovery = sufficient and q_value <= alpha and cost_adjusted_edge > 0`
(§6) gates whether it is visually flagged as a finding worth a second look. A cell can be `sufficient`
and displayed in gray/informational form without being a `discovery`.

---

## 5. Cross-interval comparability — bars vs. calendar time

**This is the central design decision, and the recommendation is both, with bars as the compute
primitive and calendar time as the default presentational lens — never the reverse.**

**Argument for bars as the primitive.** Every horizon in this codebase is deliberately bar-native
(`HORIZONS`' own docstring: "'20 bars' is 20 opportunities to trade... '20 days' silently shortens
across every holiday and lengthens across none"). `forward_returns`, `independent_count`, and every
significance calculation in `evidence.py` are already proven correct against this convention. Deriving
a *new* calendar-time-native return series (e.g. "the return over the next 100 minutes" on a daily
bar series, or "the return over the next trading day" resampled from 5m bars) means re-implementing
forward-return, entry-price, and window-exclusion logic that has already been carefully hardened
against lookahead (see the `TestLookahead` reference in `evidence.py`'s docstring) — for a second time,
on a second axis, with new opportunities for the exact class of bug that axis already survived once.
That reimplementation cost, not a preference, is the reason bars stay the primitive.

**Argument for calendar time as the comparison lens.** A 20-bar horizon is not one holding period
across intervals — it spans roughly 100 minutes on 5m, a handful of sessions on 1h, one calendar month
on 1d, and about five months on 1w. `evidence.py`'s `Evidence.horizon` field is silent on this: nothing
stops a table from placing a 5m-`H=20` cell in the same row as a 1d-`H=20` cell, inviting a reader to
compare hit rates across holding periods that differ by roughly three orders of magnitude as if they
answered the same question. **This is the single easiest way this feature could mislead**, and it is
subtler than the hit-rate-vs-baseline trap of §2 because both numbers being compared are individually
honest — the dishonesty is purely in the juxtaposition.

**The resolution: a static, precomputed bars-to-calendar-time lookup used only for grouping and
labeling, never for computing a return.** Attach an `approx_calendar_minutes` field to each
`(interval, horizon)` pair from a fixed table (5m bar ≈ 5 min, 1h ≈ 60 min, 1d ≈ 1 trading session
worth of calendar time in the exchange's own terms, 1w ≈ 5 sessions), computed once, not derived live
from a holiday calendar — it is a label for grouping, not a claim precise to the minute. The default
dashboard view groups/filters cells into calendar-time buckets ("~2 hours," "~1 day," "~1 week," "~1
month," "~1 quarter") built from this lookup, so a user asking "what's the best rule/interval
combination for roughly a one-day hold" sees 5m-`H≈78bars`, 1h-`H≈7bars`, and 1d-`H=1` compared fairly
against each other, instead of naively lining up every interval's `H=20` in one row. Where a
calendar-time bucket does not land on an exact entry in that interval's `HORIZONS`, round down to the
nearest available bar-horizon and say so in the label rather than synthesizing a fractional-bar return
— the bucket boundary is approximate by construction; the underlying number it is labeling is not.

A secondary, explicitly-labeled "native" view keeps the raw bars-native `HORIZONS` table exactly as
`evidence.py` produces it today, tagged "same-interval comparisons only — do not compare across rows,"
for a user who specifically wants "how many opportunities-to-trade did this rule get, on its own
timescale."

---

## 6. Transaction costs and the intraday trap

`evidence.py` has zero cost modeling; `Costs` (`app/backtest/models.py`) exists only in the fully
separate strategy-backtest path (`StrategyResult`/`app/backtest/strategy.py`), never touching the
rule-evidence hit-rate machinery. This gap is exactly how a 52%-hit-rate 5m rule with a small positive
`lift` could be presented as if it were profitable when a realistic round-trip cost consumes the whole
edge and more — the brief's "intraday trap."

**Recommendation.** Every accuracy cell carries a return-scale cost-adjusted figure alongside (never
instead of) the probability-scale `lift`:

- `cost_bps_assumed`: round-trip friction in basis points, defaulted from `Costs`'s own default —
  `2 × Costs.slippage_bps` (both entry and exit; the existing default is `5.0` bps each way, so `10`
  bps round trip), with `Costs.commission_per_trade` left at its own realistic US-retail default of
  `0.0` unless a caller overrides it. This reuses the codebase's already-argued-for cost assumptions
  rather than inventing new ones, and the value travels with the cell so it can be checked, not
  trusted (mirroring `RunCard.params` being canonicalised and carried rather than assumed).
- `cost_adjusted_edge`: a return-scale figure — `(median_return − baseline_median_return) −
  cost_bps_assumed/10_000` — netting the *return-magnitude* lift (already computed as
  `median_return`/`baseline_median_return` in `Evidence`) against the assumed round-trip friction. This
  is deliberately a **different scale** from `lift` (a hit-rate-probability difference) and must never
  be conflated with it in the schema or the UI — one is "how much more often did it win," the other is
  "after paying to trade it, was the edge still there."

**Why this must be foregrounded specifically at 5m/1h, not left as a drill-down.** `HORIZONS` fixes
`H=1` as the shortest measured horizon regardless of interval; on 5m that is a five-minute round trip,
where a 10bps assumed cost is frequently the same order of magnitude as the entire raw edge a
short-horizon mean-reversion rule can plausibly show. Recommendation: `cost_adjusted_edge` renders in
the same row as `hit_rate`/`lift`, not behind a click, specifically because hiding it is how a
cost-negative intraday rule ends up looking identical to a cost-positive daily one at a glance. **A
firm display rule**: if `cost_adjusted_edge <= 0`, the cell must not carry the same visual "finding"
treatment (color, badge) as a statistically-flagged cell regardless of its `q_value` — statistical
significance answers "is this pattern real," `cost_adjusted_edge` answers "is it monetizable," and a
green statistical badge must never imply a green economic one. This is folded into the `discovery`
field's definition in §9: `discovery` requires `cost_adjusted_edge > 0` as one of its three conditions,
not just a passing `q_value`.

---

## 7. Per-ticker vs. per-sector aggregation

**Codebase reality, verified rather than assumed:** there is no per-stock GICS/industry taxonomy
anywhere in `backend/app`. "Sector" in this codebase means a curated roster of sector ETFs —
`SECTOR_ETF_ROSTER` in `app/discovery/candidates.py` (the nine original SPDR sector funds: XLB, XLE,
XLF, XLI, XLK, XLP, XLU, XLV, XLY) and a wider `THEME_ETF_ROSTER` — plus a correlation-based
near-duplicate detector, `app/discovery/clusters.py`'s `correlation_groups`: single-linkage clustering
on trailing 252-day daily-return Pearson correlation at a `0.95` threshold, built specifically to stop
two near-identical funds (its own worked example: SMH/SOXX, ρ≈0.97) from being counted as two
independent pieces of evidence when they are nearly one bet.

**Recommendation, in two cases:**

**(a) The ticker *is* a sector ETF.** The sector-level cell is simply the directly-computed
`RuleAccuracyCell` on that ETF's own bars — `sector` is unset, `symbol = "XLE"`, no aggregation
required. This is the primary path and should ship first: it needs nothing beyond what §1–§6 already
specify, applied once per roster member.

**(b) Sector accuracy aggregated across several member tickers** (e.g., averaging a rule's accuracy
across individual energy-sector single names, once/if a member universe beyond the ETF roster exists).
Simpson's-paradox-safe aggregation requires:

1. **Compute lift per ticker first, against that ticker's own baseline**, never a sector-wide baseline
   applied uniformly. A pooled "sector hit rate" computed by concatenating raw triggered bars across
   tickers before computing `hit_rate` is the textbook Simpson's-paradox setup: a rule that fires
   constantly on one low-volatility, generally-rising member inflates both its own trigger count and
   its own bull-leaning baseline, and would dominate a naively pooled statistic even though its
   *per-ticker lift* is near zero.
2. **Aggregate lifts across tickers weighted by each ticker's `n_independent`** (episodes), never by
   raw triggered-bar count, for the same reason §3 rejects raw counts generally.
3. **Collapse near-duplicate members before counting how many independent tickers back the number**,
   reusing `correlation_groups` exactly as `app/discovery/clusters.py` already does for candidate
   selection: two correlated-at-0.95 members contribute as one representative to the sector's
   effective-ticker count, not two, mirroring that module's own reasoning verbatim ("allowing a
   duplicate through inflates the measured evidence"). The sector cell's sample-sufficiency gate (§4)
   should read the sum of `n_independent` across **distinct correlation groups' representative
   members**, not the naive sum across the full roster.

**A named gap, not a silent assumption:** building a real per-stock sector taxonomy (a GICS mapping or
equivalent) for arbitrary single names is out of scope for this document and does not exist in the
current data model. If the shipped feature promises "per-sector" breakdowns beyond the ~9–15 roster
ETFs, sourcing that taxonomy is a prerequisite, stated here explicitly so it is not later discovered as
a missing dependency.

---

## 8. Regime dependence

Prior project history recorded in the team's own notes is direct evidence for why this section cannot
be optional: round verdicts flipped entirely — 6-of-8 falling-window cards versus 2-of-6 rising-window
cards — from identical setups, purely because the window mix changed. A single blended accuracy number
is exactly the artifact that produced that flip, and this feature must not reproduce it.

**Minimum regime breakdown: two buckets, computed cheaply, always shown as a triplet.**

- Classify each surviving episode (post rising-edge, post non-overlap, from §3) by the instrument's
  own trailing trend at trigger time: `RISING` if the trailing 60-bar return (matching the longest
  entry in `HORIZONS`, so the classification window is never shorter than the longest forward window
  being measured) is positive, `FALLING` otherwise. Two buckets, not three: a bull/bear/chop
  three-way split needs an additional volatility or drawdown threshold — one more arbitrary parameter
  — and at the sample sizes this feature will typically see (§4's `n_independent >= 20` gate is already
  hard to clear on intraday intervals), adding a third bucket usually pushes at least one bucket below
  the gate anyway, trading a real signal for a spuriously "complete-looking" three-way table.
- Every cell reports which bucket it covers: `regime: "all" | "rising" | "falling"`. The blended `all`
  cell must never render alone — always alongside its `rising`/`falling` split, each independently
  subject to the same `sufficient` gate from §4. This mirrors the existing rule that `hit_rate` must
  never render without `baseline_hit_rate`: one number without its necessary companion is the same
  category of lie either way. A rule with overall `n_independent = 40` that splits `35` rising / `5`
  falling must show a numeric `all` and `rising` cell and an explicit "insufficient data" `falling`
  cell — not a blank, and not a number computed from 5 episodes presented with the same confidence as
  one from 35.
- **State the intraday sample's regime coverage as a first-class warning, not a footnote.** Because 5m
  history is bounded to ~60 days and 1h to ~730 days, either sample may by construction span only one
  regime end-to-end — whatever the market has been doing for the last two months or two years. In that
  case the missing regime's cells read "insufficient data — no observations in this regime over the
  available history" (distinct wording from the generic small-sample message, since the failure mode
  is different: it is not that the rule rarely fires, it is that the regime never occurred in the
  window at all), and the `all` cell itself carries a `MarketWarning` stating the sample is
  single-regime. This is the direct, mechanical link between the "hard data constraint" in this
  document's brief and the "round verdicts follow the window mix" lesson: a single-regime intraday
  sample is not a smaller version of the daily sample, it is a categorically weaker claim, and the
  schema must be able to say so on the cell itself.

---

## 9. Output schema — `RuleAccuracyCell`

```python
class RuleAccuracyCell(BaseModel):
    model_config = ConfigDict(frozen=True)

    # --- identity: what is being measured ---
    rule_id: str
    interval: Interval
    symbol: str
    """The instrument the cell is computed on. For a sector-ETF cell (§7a) this *is* the sector's
    representative symbol, e.g. "XLE"."""
    sector: str | None = None
    """Set only for an aggregate cell built across several member tickers (§7b). `None` for a
    single-ticker or single-sector-ETF cell — the common, default case."""
    entry: Entry = Entry.NEXT_OPEN

    # --- horizon, in both native and comparable form (§5) ---
    horizon_bars: int
    """One of `HORIZONS`. The computed quantity; never re-derived per interval."""
    approx_calendar_minutes: int | None = None
    """Static lookup label for cross-interval bucketing. A grouping key, not a claim precise to the
    minute -- see §5."""

    # --- regime (§8) ---
    regime: Literal["all", "rising", "falling"] = "all"

    # --- sample accounting (§3) ---
    n_raw: int = 0
    """Every triggered bar with a complete forward window -- today's `Evidence.sample_size`,
    unchanged, kept because "how often is this condition true" is still a legitimate question."""
    n_episodes: int = 0
    """Rising-edge count: `signal[t] True and signal[t-1] not True`. A run of the same persistent
    condition counts once, not once per bar."""
    n_independent: int = 0
    """`n_episodes` after the existing greedy non-overlap scan (`independent_count`). This is the
    number every gate and every CI in this schema is computed from -- never `n_raw`, and not
    `n_episodes` alone."""

    # --- the core measurement (§2) ---
    hit_rate: float | None = None
    base_rate: float | None = None
    """Matches today's `baseline_hit_rate`, computed over every evaluable bar in the identical
    sample/regime slice."""
    lift: float | None = None
    """`hit_rate - base_rate`. The headline number -- see §2 for why it must outrank `hit_rate`
    visually in any rendering of this cell."""
    lift_ci_low: float | None = None
    lift_ci_high: float | None = None
    """Stationary-bootstrap interval (§3) over the `n_independent` episodes. `None` below the
    minimum bootstrap sample (mirrors `stationary_bootstrap_p`'s own `n < 3` refusal)."""
    median_return: float | None = None
    baseline_median_return: float | None = None

    # --- statistical significance across the grid (§4) ---
    p_value: float | None = None
    """Two-sided, from the same stationary bootstrap, computed on `n_independent` episodes."""
    q_value: float | None = None
    """Benjamini-Hochberg over the declared family for the view this cell is rendered in (§4) --
    never a single global correction across the whole grid."""

    # --- economic significance (§6) ---
    cost_bps_assumed: float = 10.0
    """Round-trip friction assumed, default `2 x Costs.slippage_bps`. Return-scale, travels with the
    cell so the assumption can be checked, not trusted."""
    cost_adjusted_edge: float | None = None
    """Return-scale: median-return lift minus assumed round-trip cost. A *different scale* from
    `lift` (probability) -- must never be conflated with it in a component."""

    # --- gates (§4, §6) ---
    sufficient: bool = False
    """`n_independent >= MIN_SAMPLE_GATE` (recommended 20, see §4). Gates whether any number is shown
    at all."""
    discovery: bool = False
    """`sufficient and q_value <= alpha and cost_adjusted_edge > 0`. All three, never fewer --
    statistically flagged but cost-negative must not read as a finding (§6)."""

    # --- provenance, mirrors DecisionTable/RunCard ---
    generated_at: dt.datetime
    first_bar: dt.date | None = None
    last_bar: dt.date | None = None
    """The slice's actual span -- required because every number above is conditional on it, same
    reasoning as `DecisionTable.first_bar`/`last_bar`."""
    warnings: list[MarketWarning] = Field(default_factory=list)
    """Single-regime sample, correlation-collapsed sector roster, rule not defined on this interval,
    etc. -- a degraded cell still appears, carrying its reason, per the existing `DecisionRow`
    convention."""
```

Every field above is either taken unchanged from the existing `Evidence`/`ScanEntry`/`Costs` contracts,
or added because a preceding section of this document argued specifically for it — nothing here is
decorative.

---

## 10. How this could still lie to you

Even after every correction above, the displayed number carries residual ways to mislead:

- **The catalog itself is a filtered set.** `app/rules/catalog.py`'s rules are classics a human
  already believed in before measuring them; "worth cataloguing" already correlates with "has
  historically looked good on data like this," which is a form of selection the BH correction in §4
  cannot see because it corrects across the rules *tested*, not across the much larger set of rules
  that could have been proposed and were not because they looked unpromising to a human first.
- **A single-render `q_value` does not protect against a user re-rendering the dashboard over
  time.** A viewer who reloads the page weekly and eventually notices one green cell has performed an
  uncorrected multiple-look across *time* that no single view's family correction can price in.
- **Every per-ticker (and therefore per-sector) cell is implicitly conditioned on "the instrument
  still exists today."** The bar store holds no delisted names (`app/discovery/candidates.py` notes
  this directly, listing LEH, BSC, WAMU, YHOO, SIVB, FRC as absent), so both single-ticker and
  sector-aggregate accuracy are survivorship-biased in a way this document's corrections do not touch.
- **The rising/falling regime split (§8) is a coarse, single-variable proxy.** A rule can be genuinely
  conditional on volatility, on a macro regime, or on cross-asset correlation in ways a trailing-return
  sign cannot see, and two bars each still average over meaningfully different micro-regimes.
- **`cost_bps_assumed` is one static number applied uniformly.** Real slippage varies by liquidity,
  time of day, and instrument; the same assumed cost can make a genuinely tradeable large-cap ETF cell
  look cost-negative and a thin small-cap cell look cost-positive, purely because one fixed number was
  applied to both.
- **`NEXT_OPEN` assumes a fill at the next bar's open with no size or liquidity impact.** Realistic for
  a liquid ETF at modest size; optimistic for a thin theme fund or a single name traded at size.
- **Cross-interval comparison is also, silently, cross-regime comparison** (the brief's "hard data
  constraint"): a 1d cell may be built from three market cycles while its 5m counterpart, at matched
  `n_independent`, is built from the trailing two months alone. §5's calendar-time bucketing makes the
  *holding period* comparable; it does nothing to make the *maturity of the underlying evidence*
  comparable, and §8's regime split only helps for whichever regimes actually occurred inside that
  short window.
- **Nothing here is a forecast.** A `sufficient`, BH-corrected, cost-positive, regime-split cell is
  still a historical description of what already happened. It answers "did this look real in the
  past," never "will this keep working" — and no amount of correction turns the first question into
  the second.
