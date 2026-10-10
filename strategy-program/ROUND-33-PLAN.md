# Round 33 — the selector bake-off: Phase A pre-registration, $0 LLM spend

Pre-registered 2026-08-31, before any measurement in this round exists. **Not investment advice.**

This is the frozen Phase A half of `docs/WORKFLOW-DYNAMIC-UNIVERSE-ROUND-PLAN.md` (status: DRAFT,
owner-approved for Phase A to proceed). Eight deterministic ticker-selection rules compete, backtest-only,
against the `app.discovery` machinery already built for exactly this question
(`strategy-program/DISCOVERY.md`). The winner earns the shortlist seat in the Agent Workflow desk's new
`universe_select` stage — Phase B, a separate, later pre-registration, gated on this document's own
mechanical rule in §7, not on judgment applied after seeing Phase A's numbers.

---

## 0. Recon corrections — where this brief and the repo disagree, or where the brief left a gap the repo doesn't resolve on its own

Read in full before trusting any claim below that cites code. None of these are large; all of them change
what "frozen" has to mean in §3–§6.

1. **`app.discovery.selector.select()` and `app.discovery.exam.run_exam()` do not support gating,
   hysteresis, cooldowns, or regime-conditioned parameters.** `select()` (`backend/app/discovery/selector.py:177`)
   takes one `rank_key` from a fixed `RANK_KEYS` dict of exactly three functions (`mom12_1`, `mom6`,
   `trend` — verified, no fourth key exists) and returns the unconditional top-`top_n` by that key, with an
   optional correlation collapse. `run_exam()` replays `select()` unmodified across a fixed
   `decision_dates` tuple with a single `top_n`/`rank_key`/`collapse` for the whole replay. **Six of this
   round's eight entrants (all but the un-gated momentum base case) need net-new selector logic** — a
   filter-then-rank gate (breakout, mean-reversion, signal-density), a stateful hysteresis/cooldown wrapper
   carried across decision dates, and a per-date regime input threaded into `top_n` and pool choice. This
   is exactly what the parent document's §4 build inventory already lists as unbuilt ("2–3 new `RANK_KEYS`
   + hysteresis wrapper"), so it is not a new finding — but this document depends on that build existing
   before a single trial runs, and §3 below specifies each entrant precisely enough that the build has one
   reading to work from rather than eight ambiguous ones.
2. **`RANK_KEYS` has three entries, not two-or-three as the parent doc's table header implied.** Restated
   here because entrant 4 (`trend_sticky`) reuses `_trend` verbatim and entrant 1 reuses `_momentum_12_1`
   verbatim — two of the three existing keys are load-bearing for this round, not just precedent.
3. **`app.workflow.regime.classify()` does not read a historical time series for its Fear & Greed
   signal.** `RegimeMarketData.fear_greed_components` (`backend/app/workflow/regime.py:286`) takes *one
   current reading per component* (S&P momentum level, VIX level, put/call ratio, junk-bond spread,
   etc.), scored against **fixed calibration constants** baked into `app.market.fear_greed._CALIBRATION`
   from a ~40-day CNN fixture (`backend/app/market/fear_greed.py:90`) — there is no rolling recomputation
   and, more to the point, **no historical feed for these raw components exists anywhere in this repo**
   (put/call ratio and junk-bond spread in particular are not stored series). Reconstructing regime labels
   for a 20-year backtest cannot supply this signal from real historical data. §5 below freezes the
   resolution: `fear_greed_components` is left empty for every historical decision date, which is
   `classify()`'s own documented "no data" default — the signal abstains as *unavailable* every time,
   not as a fabricated neutral reading, and is excluded from the confidence denominator exactly as the
   module already specifies. This degrades every historical `RegimeCall` in this round from a
   four-signal vote to a three-signal one (`spy_trend`, `realized_vol`, `macro_2s10s`), uniformly across
   the whole walk-forward window, which is a materially different instrument from the one the live desk
   runs today. That difference is frozen and disclosed, not fixed, because fixing it needs a paid
   historical dataset this round does not have and the parent document did not budget for.
4. **`exam.run_exam`'s `horizon_days` is already calendar days, not sessions.** `end = as_of +
   dt.timedelta(days=horizon_days)` (`backend/app/discovery/exam.py:288`). The parent document frames
   preserving `resolve_pending`'s calendar-day horizon as a deliberate choice to keep an existing
   inconsistency for comparability; verified fact is stronger than that — the offline exam harness this
   round extends was *already* built on calendar days, so `horizon_days=21` is not an inconsistency being
   imported into `exam.py`, it is the unit `exam.py` already uses. The inconsistency is real but lives
   only between `resolve_pending`'s calendar-day language and the rest of `app.workflow`'s "sessions"
   vocabulary — see `backend/app/workflow/candidates.py:22,68,244`.
5. **The parent document's Phase A table gives each entrant a single fixed `top_n`; this round's brief
   gives per-regime `top_n` tables instead**, which is a real design change, not a contradiction — noted
   because a reader comparing the two documents side by side will see different numbers in the same cell
   and should not read that as drift. This document's §3 numbers are the frozen ones for Round 33.
6. **Neither source document pins which `CandidateSet` instance backs `control_card_universe` and
   `control_week_rotation`, or which regime→pool mapping the five regime-conditioned entrants use when a
   regime label is not literally `risk_on_trend` or one of the three defensive labels.** There are only
   four regime labels in the whole codebase (`app.workflow.regime.RegimeLabel`, verified:
   `risk_on_trend`, `risk_off`, `choppy_neutral`, `high_vol_stress` — no fifth), so this is a closed set,
   not an open one, but the mapping from label to pool still has to be written down before a run and
   wasn't. §4 pins it.
7. **`data/rounds/PROGRAMME-REPORT.md` and `docs/research/programme/00-EVERYTHING-TESTED.md` were checked
   against the owner's brief's specific figures.** `~865 lab cells` is exact: 150 primary + ~625
   exploratory + 75 seasonality + 15 VIX cells from the Strategy Lab row of `00-EVERYTHING-TESTED.md`
   line 37 sum to 865. `9,480-cell sweep` and momentum selector `IC −0.0073, p=0.892` both match verbatim
   (`00-EVERYTHING-TESTED.md:38-39`; `DISCOVERY.md` §4.1). The `±21.2-point` noise floor matches
   `PROTOCOL.md` §7 (`53.9-point spread, σ = 21.2 points`). Nothing in the brief's evidentiary claims
   needed correcting.

## 1. Why this round, and what it is not

`docs/WORKFLOW-DYNAMIC-UNIVERSE-ROUND-PLAN.md` §1 states the actual motivation precisely: the Agent
Workflow desk's candidate scan iterates a hand-authored ≤12-ticker `card.universe`
(`backend/app/workflow/pipeline.py::_scan_signals`), so the desk's paid research machinery (~$4/child run,
observed $12–20/day at defaults) is pointed by a static list rather than by where research could change a
decision. The question is whether a deterministic, $0 selector can point that spend better than a static
list does — an **attention-allocation** question, not an alpha-discovery one.

**This document is not investment advice, and it does not pretend to be discovering an edge.** The
programme's own record — `00-EVERYTHING-TESTED.md`, 18+ rounds, ~865 lab-cells, a 9,480-cell timeframe
sweep, and `DISCOVERY.md`'s own IC of −0.0073 (p=0.892) for the closest ancestor of this exact machinery —
predicts that none of the eight entrants below clears a real bar. §6 states that null formally, before it
is measured, so a null result reads as the predicted outcome, not as a surprise requiring explanation.

## 2. Owner's locked decisions (not reopened here)

- **Candidate pool is ETF rosters only.** `StoredETFCandidates` — `SECTOR_ETF_ROSTER` (21 symbols,
  `backend/app/discovery/candidates.py:88`) for defensive regimes, `THEME_ETF_ROSTER` (`SECTOR_ETF_ROSTER`
  plus 17 more, `:132`) for risk-on. **Single-stock pools are out of scope this round.** Verified: the bar
  store holds no delisted names — `LEH`, `BSC`, `WAMU`, `YHOO`, `SIVB`, `FRC` are all absent and `GM`'s
  first stored bar is 2010-11-17, the post-bankruptcy relisting (`DISCOVERY.md` §1, restated and not
  re-verified independently here since it is a store-content fact this document has no reason to doubt and
  no cheaper way to re-check than DISCOVERY.md already did). Any single-stock candidate pool built on this
  store is survivor-biased by construction; a point-in-time constituent feed is a separate, unbudgeted
  infrastructure question.
- **The Phase A→B gate is pragmatic and frozen in §7, before any run.** Phase B proceeds regardless of
  whether anything clears the IC bar. The promoted selector is decided by the mechanical rule in §7 — no
  judgment call after seeing results.

## 3. The eight entrants, frozen

Every parameter below is frozen at this commit. An entrant edited after seeing its own IC is a memory of
a selector, not a selector — `PROTOCOL.md` §2's integrity boundary applies here exactly as it applies to a
`StrategyCard`, even though §6's promotion machinery does not (see §9).

All eight share one decision cadence (§5) and read prices only through `AsOfMarket`, per `selector.py`'s
own as-of guarantee (`test_selection_ignores_everything_after_as_of`). Ties in every rank step below break
alphabetically by symbol, matching `select()`'s own convention (`selector.py:196`) and the reason given
there: an undocumented tiebreak is the same universe-ordering hazard `PROTOCOL.md` §7 measured at 53.9
points, one layer up.

### 1 — `mom12_1_hysteresis`

Base ranking: `select(rank_key="mom12_1", top_n=<regime>, collapse=True)`, i.e. `_momentum_12_1`
(`selector.py:86`, twelve-month return skipping the most recent month) verbatim, post-collapse.

Regime → `top_n`: `risk_on_trend` 3, `choppy_neutral` 2, `risk_off` 1 *and only if the market also has
`close > SMA(200)` on the same date* (else 0), `high_vol_stress` 0.

**Hysteresis, frozen as a state machine, not a sentence:**
1. Compute today's collapsed rank order (best first, 1-indexed).
2. Any held symbol whose rank today is `None` (unscoreable) or `> 5` is dropped.
3. Any held symbol still ranked `<= 5` is kept, **regardless of `top_n` for the day** — a regime
   downshift in `top_n` sheds slots only as incumbents individually fail the rank-5 test, never by force
   -truncating a still-qualifying incumbent. This is deliberate: forced truncation on a regime flip would
   make the hysteresis band meaningless on every regime change, which is the day it matters most.
4. Fill any slot left empty (by a drop, or because `top_n` for the day exceeds the held count) with the
   best-ranked not-held candidate whose rank is `<= 2` — a fresh challenger. If no such challenger exists,
   the slot stays empty for the day rather than being filled by a rank-3-to-5 candidate (only an
   already-held incumbent may occupy those ranks; a new entrant must clear rank 2).
5. On the very first decision date (no incumbents), fill up to `top_n` from rank 1 downward with no
   rank-2 gate — there is nothing to have hysteresis *against* yet.

Pre-registered failure regime: a sharp reversal inside the rank-5 band — a name falling from rank 1 to
rank 6 in one week — where hysteresis holds a stale pick exactly as long as the band is wide.

### 2 — `breakout_atr`

Gate (`bars` sourced the same way `selector._series` does — adjusted close, plus high/low for ATR via
`app.indicators.volatility.atr`, period 14):

```
last_close / rolling_max(close, 252) - 1 >= -0.02      # within 2% of a 252-session high
AND
atr(14) / atr(14).rolling(60).mean() - 1 >= 0.25        # ATR expanded >= 25% over its own 60-day mean
```

Rank the gated set by the ATR-expansion ratio, descending. Regime → `top_n`: `high_vol_stress` 3,
`choppy_neutral` 3, `risk_on_trend` 1, `risk_off` 0.

**10-trading-day per-symbol re-research cooldown**, frozen: once a symbol enters the shortlist (passes
gate + is picked), it is **not re-evaluated against the gate or rank** for the next 10 trading sessions —
it simply continues to be held through the cooldown regardless of what the gate says on those intervening
days, then re-enters the normal gate/rank evaluation on session 11. Once a symbol exits the shortlist
(gate failure or rank displacement after its cooldown lapses), it may not re-enter for 10 trading sessions
even if it would otherwise re-pass the gate — the cooldown is symmetric, covering both "just added" and
"just dropped," so the selector cannot flap a name in and out on noise inside the window.

Pre-registered failure regime: a volatility spike that reverses inside the 10-day cooldown — the entrant
holds a name for the cooldown's full duration after the breakout has already failed.

### 3 — `meanrev_rsi`

Gate: `rsi(14) < 35` (Wilder RSI, `app.indicators.momentum.RSI_SPEC`). Rank ascending by RSI (lowest
first); tie-break by ascending proximity to the lower Bollinger(20,2) band, i.e. ascending
`(close - bb_lower(20,2)) / bb_lower(20,2)` — closer to (or below) the band ranks first.

**Active only in `risk_off` and `high_vol_stress`** (`top_n` 2 in both); `top_n` 1 in `choppy_neutral`;
**empty shortlist in `risk_on_trend`** regardless of what the gate finds — this entrant is switched off
entirely in a trend-up regime, not merely deprioritized.

**Hysteresis: hold until RSI > 50.** A held symbol stays in the shortlist for as long as its RSI stays
`<= 50`, independent of the day's rank order or even the day's gate — RSI crossing back above 35 does not
by itself evict a held name; only crossing above 50 does. New entries still require the initial gate
(RSI < 35) at the moment of entry. Capacity is `top_n` for the day; if held names already fill it, no new
entrant is admitted regardless of rank until a held name's RSI clears 50.

Pre-registered failure regime: a genuine trend break dressed as an oversold bounce — RSI dips under 35,
recovers to the 35–50 band, and grinds there for months while the underlying trend keeps falling; the
entrant holds the whole time.

### 4 — `trend_sticky`

Base ranking: `select(rank_key="trend", top_n=2, collapse=False)` — `_trend` (`selector.py:104`, last
close over its own 200-day SMA) verbatim.

**Enter at rank 1 only.** A symbol may only be newly added to the shortlist on a day it is ranked first.
**Exit only below rank 6, or on close crossing below its own SMA(200)** — whichever comes first. Widen the
exit-rank threshold to **below rank 8** specifically in `high_vol_stress` (the SMA-200 cross exit is
unchanged in every regime). No regime-conditioned `top_n`: this entrant always targets 2 slots when both
are filled, but a slot vacated by an exit stays empty until a new rank-1 challenger appears — it is not
backfilled from rank 2–8, by the same "enter at rank 1 only" rule.

Pre-registered failure regime: a rangebound market where nothing holds rank 1 long enough to matter, and
the entrant sits with one or both slots empty through a stretch it could have profitably held something
looser.

### 5 — `signal_density`

Count, per candidate per day, how many of `app.rules.catalog`'s rules fire, **excluding `vwap_reclaim`**
(catalog verified: 12 rules total, `vwap_reclaim` is `intervals=(FIVE_MIN, HOUR)`-restricted per
`catalog.py:118` and has no meaning on a daily bar — 11 rules are eligible). Gate: density `>= 3`. Rank by
density descending; tie-break by **absolute net directional lean**, defined here (not specified upstream,
frozen now):

| sign | rules |
|---|---|
| +1 (bullish) | `rsi_oversold`, `bb_lower_touch`, `ema_golden_cross`, `macd_bullish_flip`, `price_above_sma200` |
| −1 (bearish) | `rsi_overbought`, `bb_upper_touch`, `ema_death_cross`, `macd_bearish_flip` |
| 0 (direction-agnostic) | `bb_squeeze`, `atr_range_expansion` |

`net_lean = sum(sign(r) for r in fired_rules)`; tie-break ranks by `abs(net_lean)` descending (more
conviction, either direction, ranks higher than a density tie split evenly between bullish and bearish
rules firing at once).

**Defensive subset, active in `risk_off` and `high_vol_stress` only** (density and the gate are both
computed over this 6-rule subset instead of all 11 on those days): `rsi_oversold`, `rsi_overbought`,
`bb_lower_touch`, `bb_upper_touch`, `bb_squeeze`, `atr_range_expansion` — the oscillator/volatility rules,
excluding the four trend-continuation rules (`ema_golden_cross`, `ema_death_cross`, `macd_bullish_flip`,
`macd_bearish_flip`) and `price_above_sma200`. Rationale for the exact split, frozen as reasoning rather
than left implicit: a trend-continuation rule presupposes an established trend, which is precisely what a
defensive regime is defined by *not* having; an oscillator/volatility rule instead asks about the
candidate's own local stretch, which is legible in a choppy or stressed tape regardless of the broader
trend's state.

`top_n`: 2 in every regime the gate is active in (all four — this entrant has no `top_n=0` regime,
unlike 2 and 3).

**Incumbent bumped only by a challenger at density `>= 5`.** A held symbol whose density has fallen below
the day's gate threshold is dropped; otherwise it is retained even if a higher-density non-held candidate
exists, unless that candidate's density is `>= 5`, in which case it bumps the weakest held incumbent (by
density, then by `abs(net_lean)`, then alphabetically).

Pre-registered failure regime: a period of genuinely low signal activity across the whole roster (every
name near its indicators' neutral zones at once) leaves this entrant's shortlist thin or empty for
stretches, ceding the whole period to whichever other entrant or control is compared against it.

### 6 — `divers_mom6`

`select(rank_key="mom6", top_n=3, collapse=True)` — `_momentum_6` (`selector.py:97`, six-month total
return, no skip) verbatim — **on the THEME roster specifically, in every regime**, not the regime-switched
pool §4 defines for entrants 1–5. Collapse is applied **before** truncation (this is `select()`'s own
order of operations already — `selector.py:218-221` partitions and collapses, then slices `[:top_n]` —
restated here because it is the property that makes "3 picks from 3 distinct correlation groups" true by
construction rather than by luck).

**Diagnostic only, not a selection input:** log `len(selection.groups)` — the number of correlation groups
the full collapsed candidate set partitioned into that day — alongside every trial. A day where the theme
roster partitions into only 2 or 3 groups total (most of the roster judged one bet) is flagged in the
Phase A report as a day this entrant's "3 distinct bets" framing was thinner than it looks.

Pre-registered failure regime: a single dominant theme (e.g. 2020's solar/semi rally) correlates enough of
the roster together that even a "diversified" 3-name pick is effectively one concentrated bet — the
collapse mechanism catches this and the group-count diagnostic is built to surface exactly it, but it does
not prevent the entrant from having taken the concentrated bet in the first place if only 2–3 groups exist
that day.

### 7 — `control_card_universe` (CONTROL)

Returns the **first** `agent_id` listed for the day's regime label in `backend/app/workflow/regime_map.json`
(verified: every label maps to an ordered list, "candidate-first" per that file's own `_comment` — the
orchestrator tries index 0 first) resolved to its `StrategyCard`, and returns that card's static `universe`
tuple, unmodified, every day. No price history read, no fallback if index 0 is unavailable that day
(retired, `desk_only` mismatch) — that fallback logic is production routing behavior this control
deliberately does not replicate; a day the production router would have fallen through to index 1 is
scored here against index 0's universe regardless. Recorded as a known simplification, not silently
resolved: index 0 by label is `C-trend` (`risk_on_trend`), `c14-riskmanaged-wide` (`risk_off`), `c07-chop`
(`choppy_neutral`), `c19-volatility` (`high_vol_stress`).

This is the status-quo baseline: "what would the desk's own hand-authored list have offered, if regime
routing worked exactly as `regime_map.json` says and nothing paid for research beyond what that card
already names."

### 8 — `control_week_rotation` (CONTROL)

`pool = sorted(candidates.symbols_as_of(as_of))`; `offset = as_of.isocalendar()[1] % len(pool)`;
`picks = pool[offset : offset + 3]`, wrapping around the end of `pool` if `offset + 3 > len(pool)`. No
RNG, no seed, no price data, no regime input — `candidates` is frozen to the **sector roster**
(`SECTOR_ETF_ROSTER`), fixed for the whole run regardless of regime. Frozen here, not specified upstream:
the sector roster rather than the theme roster, because a genuinely regime-blind control should not
inherit the theme roster's own, larger, survivorship bias (`candidates.py`'s own docstring: "materially
worse" for theme) — giving the *deterministic-noise* control the *cleaner* pool is the conservative
direction, the same one `costs.py` takes charging the benchmark nothing: it makes this control a harder
bar to beat, not an easier one.

## 4. Candidate-pool wiring, frozen entrant-by-entrant

Only four regime labels exist (`app.workflow.regime.RegimeLabel`, verified closed set:
`risk_on_trend`, `risk_off`, `choppy_neutral`, `high_vol_stress`), so this table is exhaustive.

| entrant | risk_on_trend | risk_off | choppy_neutral | high_vol_stress |
|---|---|---|---|---|
| 1 `mom12_1_hysteresis` | theme | sector | sector | sector |
| 2 `breakout_atr` | theme | sector | sector | sector |
| 3 `meanrev_rsi` | (inactive) | sector | sector | sector |
| 4 `trend_sticky` | theme | sector | sector | sector |
| 5 `signal_density` | theme | sector | sector | sector |
| 6 `divers_mom6` | theme (always) | theme (always) | theme (always) | theme (always) |
| 7 `control_card_universe` | n/a — card's own static list | n/a | n/a | n/a |
| 8 `control_week_rotation` | sector (always) | sector (always) | sector (always) | sector (always) |

Rule for entrants 1–5, restated as the "owner's locked decision" in §2 applied concretely: **theme roster
only in `risk_on_trend`, sector roster in every defensive label** (`risk_off`, `choppy_neutral`,
`high_vol_stress`). This is the one place this document exercises judgment the source documents left open
(recon correction 6) — the alternative (theme roster in every regime, for every entrant) was rejected
because it would make every entrant inherit the theme roster's worse survivorship bias even while
defending against a stressed tape, which is precisely the regime where a thinly-traded thematic fund is
most likely to have been the one that later closed.

## 5. Decision cadence, and reconstructing a regime label for a date in 2004

**Decision dates are every session on the trading calendar** within the walk-forward window (§6), not
annual or monthly as `DISCOVERY.md`'s original exam used. This is necessary, not a stylistic upgrade:
hysteresis states, cooldowns, and `control_week_rotation`'s ISO-week arithmetic are only meaningful
evaluated day to day — a monthly grid would silently change what "10-trading-day cooldown" or "hold until
RSI > 50" means. It also means overlapping 21-day horizons are the norm, not the exception, which is why
§6's IC aggregation uses the stationary bootstrap (`block ≈ 21`) rather than a t-table throughout, per
`stats.py`'s own repeated warning against exactly this trap.

**Every regime-conditioned entrant (1–5) needs a `RegimeCall` for every one of those sessions.** This
round reconstructs one via `app.workflow.regime.classify()`, frozen as follows:

- `spy_bars`: SPY's stored daily history through each `as_of`, read the same way `classify()`'s own live
  default does (`app.market.store.read_frame`) — pure disk I/O, no network call, already the module's own
  offline-safe path.
- `fear_greed_components`: **left empty for every decision date** — see recon correction 3. This signal
  abstains as unavailable on every single day of the replay, uniformly; it never votes and is never in the
  confidence denominator, for the whole walk-forward window.
- `macro_2s10s_pct`: the FRED `T10Y2Y` series, **release-lagged by one trading session** (a daily FRED
  series publishes on a next-business-day lag; this is a smaller, cleaner lag than the 45-day lag rounds
  30–32 used for monthly CPI, and is stated explicitly here rather than silently reused from the CPI figure
  which does not apply to a daily series). No revision risk for `T10Y2Y` unlike the monthly indices rounds
  30–32 handled, so no revision-leak caveat is needed for this input.

**A `RegimeCall` reconstructed this way is a three-signal vote (`spy_trend`, `realized_vol`,
`macro_2s10s`) for the entire historical replay**, not the four-signal vote the live desk runs today. This
is disclosed in §0 and repeated here because it is the input every regime-conditioned entrant's `top_n`
and pool choice depends on — a different classifier instrument than production, frozen and named as such,
not silently assumed equivalent.

## 6. Grading protocol

**Primary metric.** Bootstrapped information coefficient per entrant against the **candidate pool's own
equal weight** (`stats.ic_summary(bootstrap=True, block=21, seed=33)`), never SPY — `exam.py`'s own module
docstring gives the reason at length: a selector graded against SPY in a bull market looks brilliant for
picking anything at all, which is exactly how a hindsight basket comes to look like a strategy. Horizon:
**21 calendar days**, matching `HOLDING_DAYS` (`backend/app/workflow/candidates.py:73`) and the
already-calendar-day convention `exam.run_exam`'s own `horizon_days` uses (recon correction 4) — kept
deliberately, for comparability with the existing candidate log, not fixed to "sessions" here.

**Secondary metrics**, none of them ranking-relevant on their own:
- Hit rate + `binomial_p_value` (`app.backtest.scan.binomial_p_value`), reported with the same caveat
  `exam.py`'s own docstring gives: overlapping daily-cadence, 21-day-horizon trials are not independent, so
  this binomial overstates significance and is descriptive only.
- **Benjamini-Hochberg across all 8 entrants, controls included** — `PROTOCOL.md` §3 rule 8's denominator
  rule applied without exception. `q <= 0.10` is the survivor threshold, matching rounds 28–32's own
  convention.
- **Shortlist churn**: mean turnover per session, `discovery.costs.turnover` applied to each entrant's
  consecutive daily pick sets (reused verbatim, not reimplemented — `costs.py`'s own docstring on why a
  per-trial round-trip charge would invent turnover a stable rule never had applies exactly here, since
  this round's trials overlap far more than `DISCOVERY.md`'s annual ones did).
- **Implied $/day at $4/researched ticker**: for each session, count symbols present in that day's
  shortlist but absent from the prior session's — a "new to the shortlist" ticker is the one that would
  trigger a fresh paid research run under the necessity-gate chain the parent document sketches for Phase
  B (a re-held incumbent does not re-trigger research). `implied_$/day = mean(daily new-ticker count) * 4`.

**Walk-forward split**, dated against what the store and the classifier's own warmup actually support, not
against a round number:
- **Burn-in**: the first 500 sessions from `2003-01-02` (matching `DISCOVERY.md`'s own annual-date start,
  a date already vetted in this repo — by then all nine original SPDR sectors plus `SMH` clear the
  252-bar / `MIN_CROSS_SECTION=8` floors comfortably). State (hysteresis incumbents, cooldown timers,
  regime-classifier warmup) accumulates through burn-in but **no trial in this window is scored**.
- **In-sample (selection) slice**: session 501 through **2017-12-29**. This is the slice every number in
  §7's gate decision is computed from.
- **Held-out (confirmation) slice**: **2018-01-02 → 2026-08-18** (the last date `WINDOWS.md`'s own
  `recent` window reaches). Computed once, after the in-sample numbers and the §7 decision are already
  fixed, and **never consulted while making that decision** — the walk-forward discipline this document
  exists to enforce. Chosen to split roughly at 2018 specifically because it is a plain calendar boundary
  fixed before any measurement, not a boundary picked by scanning for where the split makes a result look
  better; it also happens to hand the holdout genuine regime diversity it would not have gotten from a
  "last three years" cut — `q4-2018`, `covid`, `bear-2022`, `bull-2024` and `recent` (`WINDOWS.md`) all
  fall inside it, alongside the calmer stretches.
- **Floor check**: in-sample alone is roughly 3,770 sessions (2005-01 through 2017-12), nearly 8x the
  ~500-session floor the parent document names; the floor is not binding here and needed no adjustment.
- **A caveat this split does not remove**: the theme roster's own breadth is still time-varying inside
  both slices — `URA`/`REMX`/`CPER` arrive 2010–2011, `ARKQ/ARKW/ARKG/ARKK` in 2014, `JETS` in 2015
  (`candidates.py:146-150`) — so entrant 6 and every entrant's `risk_on_trend` sessions have a materially
  thinner theme cross-section before 2015 than after. This is not correctable by moving the split date; it
  is inherent to when these funds launched, and is reported per-era in the Phase A output the same way
  `DISCOVERY.md` §4.5 reported an era split for exactly this reason.

## 7. Phase A → B gate — the mechanical rule, frozen before any run

**Phase B proceeds regardless of what Phase A measures.** The selector promoted to the live
`universe_select` seat is decided by this rule, applied to the **in-sample slice only**, mechanically:

**(1)** If any entrant clears `bootstrap_p <= 0.10` on its in-sample IC **and** its in-sample mean IC is
numerically greater than **both** controls' in-sample mean ICs, the promoted selector is the one among
such entrants with the **highest** in-sample mean IC (ties broken as in (2) below). This is the "an actual
IC edge exists and is realistic to prefer" branch — expected empty, per §8.

**(2)** Otherwise — the branch the programme's own record predicts will fire — the promoted selector is
the entrant that is **not statistically worse than either control**, with the **lowest mean shortlist
churn** among the entrants clearing that bar. "Not statistically worse than control X" means: a paired
stationary-bootstrap test (same machinery as `ic_summary`, `block=21`, one-sided alternative "entrant mean
IC < control X's mean IC") on the per-session paired IC difference does **not** reject at `p <= 0.10`. An
entrant must clear this test against **both** controls to be eligible for (2). If **no** entrant clears it
against both controls, both controls themselves are eligible candidates for (2) and are compared against
each other on churn the same way.

**Ties within either branch** break, in order: (a) lower implied $/day, (b) alphabetically by the frozen
selector id from §3/§8 (`breakout_atr` < `control_card_universe` < `control_week_rotation` <
`divers_mom6` < `meanrev_rsi` < `mom12_1_hysteresis` < `signal_density` < `trend_sticky`).

This rule is written to require no judgment call at the moment it is applied — every input (`bootstrap_p`,
mean IC, the paired-bootstrap significance test, churn, implied $/day) is a number this document already
specifies how to compute, and the ordering of branches and tiebreaks is total, not partial: some entrant
or control is always selected.

## 8. Pre-registered null, and the predictions this round is falsifiable against

**The pre-registered null**: no entrant clears `bootstrap_p <= 0.10` on its in-sample IC while also
beating both controls (branch (1) above does not fire). The programme's record predicts this plainly —
18+ rounds, ~865 lab cells, a 9,480-cell timeframe sweep and, most directly, `DISCOVERY.md`'s own
`mom12_1` IC of **−0.0073** (bootstrap p=0.892) on the closest ancestor of entrant 1. **This is said before
running anything, not after.** A null result in branch (1) is the predicted outcome, and it does not
imply this document was wrong to write — it is the expected way branch (2) is reached.

Falsifiable predictions, fixed before the first trial:

1. **Branch (1) does not fire for any entrant.** *Refuted if* any entrant both clears `q <= 0.10` (BH
   across all 8, §6) and beats both controls on mean IC.
2. **`mom12_1_hysteresis` (entrant 1) posts an in-sample mean IC statistically indistinguishable from
   `DISCOVERY.md`'s own −0.0073**, since it reuses the identical rank key on a materially overlapping
   candidate pool and era. *Refuted if* its in-sample mean IC sits outside roughly [−0.03, +0.03] — an
   order of magnitude away from the prior measurement would say the daily cadence or hysteresis wrapper
   changed the finding, not just the sampling rate.
3. **`control_week_rotation` (entrant 8) posts a mean IC statistically indistinguishable from zero.** It
   reads no price data and no regime input by construction; any measured IC materially away from zero
   would be an artifact of the `isocalendar()` offset interacting with a real seasonal pattern in sector
   ETF returns, which would itself be a separate, interesting finding this round is not designed to chase.
   *Refuted if* its `bootstrap_p <= 0.10`.
4. **`trend_sticky` (entrant 4) has the lowest mean churn of the six non-control entrants**, by
   construction of its "enter at rank 1 only, wide exit band" rule — the parent document already named it
   the expected branch-(2) winner. *Refuted if* another entrant's mean churn is lower.
5. **`meanrev_rsi` (entrant 3) has the fewest scored sessions of the six**, being switched off entirely in
   `risk_on_trend`. *Refuted if* another entrant's active-session count is lower.
6. **Held-out (2018+) mean ICs are not systematically better than in-sample** for any entrant — a
   selector's IC improving out of sample would itself be surprising given every entrant here is
   deterministic and none was tuned against the held-out slice by construction (there is nothing to tune;
   the parameters are frozen), so an improvement would most plausibly indicate the held-out slice's own
   regime mix simply favored that entrant's mechanics, not that generalization improved. *Refuted, in the
   sense of "flagged as needing explanation rather than being read as an edge," if any entrant's held-out
   mean IC exceeds its in-sample mean IC by more than the in-sample IC's own bootstrap standard error.*

## 9. One measurement, not a re-run

Every entrant here is **deterministic given the stored bars and the frozen regime-classifier inputs.**
Re-running the identical decision-date replay against the same store produces byte-identical trial output.
`PROTOCOL.md` §6(a) already made this point for `StrategyCard`s on overlapping windows (`A-rotation`
returned +95.2786% in `recent` in both rounds 1 and 2, to four decimal places, on the same 47 trades) —
the same fact holds here for exactly the same reason. **This round's in-sample and held-out numbers are
each one measurement, taken once.** A future round that re-runs Round 33's exact entrants against the same
2003–2026 history and reports a "confirmation" is counting one draw twice, not gathering new evidence — a
genuine second measurement needs either new decision dates (calendar time passing, `PROTOCOL.md` §5's own
walk-forward rule) or a different, equally frozen entrant.

## 10. Why PROTOCOL §6 does not mechanically apply

`PROTOCOL.md` §6's promotion ladder (challenger → `candidates/` → `base/`, two consecutive rounds, new
windows each time) is built for a `StrategyCard`: something with `designed_through`, a `universe`, entry
and exit rules the tournament runner can simulate inside the eight-window matrix. **A selector is not a
`StrategyCard`.** It has no `universe` of its own (it produces one, per decision date), no
`designed_through`, and nothing in `app.tournament` can run it — `run_exam` is a separate offline harness,
not the tournament runner. §7's rule is therefore not a substitute promotion ladder built to the same
mechanical standard as §6's; it is a narrower, one-shot decision about which single selector earns a Phase
B live-forward slot, made once, on this round's own frozen criterion. Whether that selector's Phase B
result later earns anything resembling `base/` status is an owner decision under the r21 posture
(`PROTOCOL.md` §9's r21 amendment — Gate L, Gate C, and judgment, the same posture that already governs
`C-trend`'s standing) — a mechanical two-consecutive-rounds rule applied to an 8-entrant search that was
never run twice would launder this round's own selection noise into a live default, which is the exact
failure §6 exists to prevent for cards and would be no less a failure here.

## 11. What is not built, and is not this document's job to build

Per the "design/documentation only" scope this document was written under: nothing above has been
implemented. Before Phase A can run, the gap in recon correction 1 has to close — new rank-gate functions,
a stateful hysteresis/cooldown wrapper threaded through `run_exam`'s trial loop (or an equivalent daily
driver, since the existing driver assumes a stateless `select()` call per date), the regime reconstruction
in §5, and the two controls, none of which exist in `app.discovery` today. The parent document's own §4
build-inventory row ("Phase A: 2–3 new `RANK_KEYS` + hysteresis wrapper + 2 controls + exam driver loop |
S–M") already scoped this; this document's job was to make that build unambiguous, not to do it.

## 12. Determinism and honesty about scope

- Seed `33` for every bootstrap in this round (IC bootstrap, paired-control test), fixed, never the clock.
- **What this round cannot settle**: whether a selector helps *because* it changes which symbols get paid
  research (the actual Phase B question) — Phase A measures selection quality against an equal-weight
  benchmark, which is a necessary but not sufficient condition for that; both ETF rosters carry the
  survivorship caveats `candidates.py` and `DISCOVERY.md` §7 already state in detail, restated in §2
  above rather than re-derived; the regime labels driving five of eight entrants are a three-signal,
  Fear-and-Greed-degraded reconstruction of a four-signal live classifier (§0, §5), not the instrument
  Phase B will actually run against day to day; and the daily-cadence, 21-day-horizon overlap this round
  requires (§5) is priced into the IC statistic via the block bootstrap but is not priced into the
  descriptive binomial hit rate at all, which is reported and explicitly not trusted for exactly that
  reason.
- Return/IC statistics only. **No trade, no live spend, no card, nothing promotable by §6's mechanism** —
  see §10. The only thing this round can promote is which frozen selector's name goes into Phase B's own,
  separate, later pre-registration.
