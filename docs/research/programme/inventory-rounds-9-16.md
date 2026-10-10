# Inventory — competition rounds 9 through 16

**Read-only research.** This document exists because `data/rounds/PROGRAMME-REPORT.md` is titled
"rounds 1–11" and stops at round 11 (§10–10.2). Rounds 12–16 have never been consolidated anywhere
else. This inventory covers rounds 9–16 so the two documents together span the whole programme to
date.

**Not investment advice.** Everything below describes a simulation programme on stored price history.

Sources read in full: `data/rounds/PROGRAMME-REPORT.md` §10–10.2 (rounds 9–11); every file in
`data/rounds/r9-2026-08/` … `data/rounds/r16-2026-08/`; `strategy-program/ROUND-10-PLAN.md`,
`ROUND-11-PLAN.md`, `ROUND-12-PLAN.md`, `ROUND-14-PLAN.md`, `ROUND-15-PLAN.md`,
`ROUND-15-CANDIDATES.md`, `ROUND-16-PLAN.md`; `strategy-program/SAVINGS-FAMILY.md`;
`strategy-program/DEFECTS.md` (D6, and the "Round 13's job" thread); `data/rounds/SCOREBOARD.txt`;
`backend/app/api/competition.py`.

---

## 0. Two anomalies, established first

### Round 13 — no plan, no selection, not a competition round

**There is no `strategy-program/ROUND-13-PLAN.md` anywhere in the repository**, and
`data/rounds/r13-2026-08/` contains exactly one file: `savings-family-run.txt`. No `SELECTION.md`, no
`BRIEF.md`, no `REPORT.md`.

What actually happened, established from `data/rounds/r13-2026-08/NARRATIVE.json` (which states this
plainly rather than manufacturing a selection that never occurred) and `strategy-program/SAVINGS-FAMILY.md`:

- **Round 13's number was consumed by an unrelated backtest**, not a `StrategyCard` tournament round.
  `strategy-program/tools/savings_family.py` ran a monthly-contribution savings-account backtest —
  four allocation variants against SPY buy-and-hold and a static 60/40 benchmark, at two contribution
  rates, over multi-decade windows including a 2008 GFC slice — and its raw stdout was written to
  `data/rounds/r13-2026-08/savings-family-run.txt`. That is the entire contents of the round-13
  directory.
- **No `StrategyCard` was gated, ranked, promoted, retired, seated or dropped in round 13.** No owner
  override occurred. `r13-2026-08/NARRATIVE.json`: *"The round number was simply consumed by this
  separate piece of work rather than by a competition round, and this narrative records that honestly
  rather than manufacturing a selection that never happened."*
- **What round 13 was originally supposed to be**, per `strategy-program/DEFECTS.md` D6: a fix that
  makes rounds pin their own store state (row count, last bar date) into their `scorecard.json`, so a
  later round can check drift against a *recorded* value instead of a number transcribed from another
  document's prose — the practice that had already let round 11's "unchanged since round 9" claim go
  stale within one working day. D6 explicitly deferred that fix: *"Not implemented here: it changes
  what every round writes, and doing it mid-integration is the kind of instrument change
  `PROTOCOL.md` refuses. **Round 13's job.**"*
- **That job was never done as round 13.** D6's own "What landed — 2026-08-26" section: it was
  *"Implemented at a clean boundary rather than at round 13"* — after an unrelated autonomous
  evolution loop had stopped of its own accord at generation 1848, so the store-pinning tool
  (`strategy-program/tools/storestate.py`, with `score.py --pin-store` / `--compare-store` flags) was
  built and landed outside the round numbering entirely, on 2026-08-26.
- Corroborating cross-references confirm round 13 was expected to be a competition round and simply
  wasn't one: `data/rounds/r12-2026-08/SELECTION.md` §"For whoever runs round 13" gives round 13
  instructions about not reading its roster as re-confirmation, the store-drift process gap, the
  unresolved no-live-record card problem, and the `B4-tight-stop` duplicate-row question — none of
  which round 13 addressed, because round 13 never ran a selection.

**Established:** round 13 did not run as a competition round at all. It was a savings-family backtest
(see §3 below for what it tested) that happened to occupy the round-13 slot on disk, and the actual
job the number was pre-registered for (store-state pinning, D6's fix) was built later, outside the
round sequence.

### Round 16 — ran, but produced no `results/` tree, and here is why

`data/rounds/r16-2026-08/` holds `NARRATIVE.json`, `SELECTION.md` and `paired.json` — no `results/`
directory, unlike round 14's directory which does have one.

**Established, from `backend/app/api/competition.py`:** the `/api/competition` rounds listing sets
`has_results=False` for any round whose directory has no `results/` subdirectory (or one with no
windows in it) — `app.tournament.results.load_round_results` raises `RoundNotFoundError` in that case,
and the docstring states plainly: *"`has_results=False` means `/rounds/{round_id}/leaderboard` will
404 for this round by design."* Round 16 has no `results/` directory, so the API correctly reports it
as having no results. This is not a bug or an incomplete run — it is what the round actually produced.

**Established, from `strategy-program/ROUND-16-PLAN.md` and `data/rounds/r16-2026-08/SELECTION.md`:**
round 16 ran in full. It was never a `StrategyCard` tournament round — it re-ran round 15's
contribution-funded savings/Roth cells (the ones in `data/rounds/r15-2026-08/contributions/`) a second
time under a new cash-constrained mode of `contributions.simulate`, paired cell-for-cell against the
unconstrained originals, and wrote the paired comparison to `paired.json` (31 cells × 2 conditions,
528 lines) rather than to a `results/<window>/runs/*.json` tree, because it was never producing
`AgentResult`/`StrategyCard` records that a leaderboard could read — it was producing
`ContributionResult` pairs. `SELECTION.md` §1: *"Round 15 shipped every savings and Roth figure
stamped `cash_constraint_modelled: false`... Round 16 built the constraint and measured it across all
31 contribution cells."* The round's own headline: *"The answer: nothing. It never fires"* — zero
underfunded buys across all 31 cells (see §3 below for the full result and its same-day follow-up).

**Established:** round 16 ran and produced a real, complete, pre-registered/falsified result — it is
absent from the competition leaderboard API only because it was never a card-tournament round; the
same is true, structurally, of rounds 9 (partially — the tournament ran but under-filled), 10, 12, 13
and, for the trading arm at least, 14 and 15.

---

## 1. Round-by-round inventory

### Round 9 — a pre-registered rule that under-filled

*Source: `data/rounds/PROGRAMME-REPORT.md` §10.*

- **Question pre-registered:** turn round 8's owner override (choosing `B-momentum` over
  `B3-concentrated` on rank stability across matrices) into a repeatable rule, rather than a one-off
  judgement call.
- **Field:** the 15-card field carried forward from round 8. Gate A (positive median annualized
  adjusted excess at round 5's 5y/10y rungs vs SPY and QQQ), tightened Gate L (traded out-of-sample
  and alive within 60 sessions), new Gate S (worst rank ≤5 across round-2/round-4/round-5-ladder
  matrices), ranking by median annualized adjusted excess vs QQQ over the 5y/10y rungs, distinctness,
  top four.
- **Windows:** round 2's 9-window matrix, round 4's 6-window matrix, round 5's 27-window horizon
  ladder — all frozen, pre-existing.
- **Result:** `B-momentum` won the ranking outright, **+7.68%** median annualized adjusted excess vs
  QQQ (PROGRAMME-REPORT.md §10), against `B4-tight-stop`'s +4.96% and `B3-concentrated`'s +2.72%. Only
  three cards cleared Gates A/L/S (`B-momentum`, `B4-tight-stop`, `B3-concentrated`, one family), so
  distinctness allowed exactly one — a **two-card desk** (`B-momentum` + the unranked
  `ladder-qld-schd`), against a four-seat target.
- **Verdict:** the owner explicitly refused to ship the under-filled two-card roster or loosen the
  Gate-S threshold, and instead kept round 8's five-card desk unchanged and asked round 10 to repair
  Gate S.
- **What it corrected:** nothing from an earlier round yet — it produced the rule, and diagnosed two
  defects in its own design (Gate S and distinctness select against each other; Gate S re-measures
  competitiveness that Gate A and the ranking already measure, when what was wanted was *dispersion*).
- **Left open:** whether `discipline` is the right distinctness axis (`C-trend` vs.
  `H-trend-diversified`, flagged since round 8).

### Round 10 — Gate S′, and the desk drops its best live performer

*Source: `data/rounds/PROGRAMME-REPORT.md` §10.1.*

- **Question:** repair Gate S's two named defects with a coverage clause (result on ≥2 of 3 matrices,
  never imputed) plus a pure dispersion bar (`max rank − min rank ≤ 3`), and make the seat count an
  **output, not a target**.
- **Field/windows:** identical frozen evidence to round 9 — same 127-session out-of-sample window,
  same three matrices, Gate L carried forward rather than re-run.
- **Result:** four cards cleared Gate S′ (`B-momentum` 3/2/2 range 1, `B4-tight-stop` 4/3/4 range 1,
  `C-trend` 5/5/6 range 1, `H-trend-diversified` 6/8/7 range 2); distinctness seated one per discipline
  — **`B-momentum`** (+7.68% vs QQQ) and **`C-trend`** (+2.01% vs `H-trend-diversified`'s +1.79%).
  Two seats of four target, again.
- **Verdict:** the rule dropped `A-rotation` — its **best live performer, +65.18% since inception,
  +37.36% out-of-sample** (PROGRAMME-REPORT.md §10.1) — for `C-trend` at −2.03% live. **The owner
  overrode the rule and kept `A-rotation` on the desk** (round 10 §7). Desk: `B-momentum`, `C-trend`,
  `A-rotation`, `ladder-qld-schd`.
- **What it corrected:** round 9's treatment of `A-rotation`'s absent round-4 matrix as a bad rank —
  under S′ the absence is simply not counted, "same verdict, honest reason."
- **Left open:** fix 4 (score the live desk's own record, weight it above backtests) — open since
  round 6, and this is the first time it would have changed a seat rather than a footnote. Also: the
  trend seat is decided by 0.22 points, "far inside the programme's measured noise floor."

### Round 11 — fix 4 implemented, and D5 (an invalid live matrix caught by a failed prediction)

*Source: `data/rounds/PROGRAMME-REPORT.md` §10.2.*

- **Question:** implement fix 4 — score the live desk's own record and weight it above the backtests.
  Gates A/L stay floors, Gate S′ demoted to tie-break, new Gate C (positive result in ≥3 of 6 live
  sub-periods), ranking by median `adjusted_excess` across those six.
- **Field/windows:** the six live sub-periods spanning 2026-02-17 to 2026-08-18 (127 sessions).
- **Result — first attempt invalid (D5):** six *independent* sub-window runs each forced a flat-book
  liquidate/re-enter, directionally biasing high-turnover cards up and hold-and-ride cards down —
  `B-momentum` showed zero trades and 0.0% exposure in two sub-windows while fully invested. Caught not
  by inspection but because `ROUND-11-PLAN.md` §6's pre-committed prediction (`B3-concentrated` would
  lead) failed against the broken matrix's answer (`A-rotation` alone). **Corrected** to cumulative runs
  from one fixed start, differenced — exact, self-checked against `score.adjusted_excess` for the first
  sub-period.
- **Result — corrected:** three seats — `B3-concentrated` (+7.41% median, 4/6), `A-rotation` (+3.47%,
  4/6), `C-trend` (+1.81%, 3/6), plus the unranked ladder. Gate C removed `H-trend-diversified` (1/6).
  All four of the plan's pre-committed expectations held.
- **Verdict:** **split the two prior overrides rather than ratifying either.** Round 8's override
  (`B-momentum` over `B3-concentrated`) is **reversed** by the live record (+7.41% vs +4.82%); round
  10's override (keeping `A-rotation`) is **vindicated** (seated on the rule itself). `B-momentum`
  leaves the desk.
- **What it corrected:** the invalid first live matrix (D5) — kept as evidence, not deleted.
- **Left open:** six contiguous sub-periods of one period are not six regime draws — "this rule weights
  six months of 2026 above" the three backtest matrices' GFC/COVID/chop/bull/27-horizon regime
  coverage. `A-rotation`'s 10th-to-1st backtest swing "has not gone away; under this rule it costs a
  tie-break instead of a seat." Closing paragraph names the binding constraint for what follows:
  `ROTH-MOMENTUM.md` and `ROTH-VOLTARGET.md` are the only genuinely new ideas since round 5, and
  neither has a distinctness path into the competition because the rule can't score a card with no
  live record.

### Round 12 — distinctness restated over holdings

*Source: `data/rounds/r12-2026-08/SELECTION.md`, `NARRATIVE.json`, `ROTH-CANDIDATES.md`.*

- **Question:** replace the base-family distinctness clause with a rule measured directly on live
  holdings overlap ("novel names" per invested session vs. the union of already-seated cards), to give
  round 11's owner override (keeping both `B3-concentrated` and `B-momentum`) a principled,
  pre-registered test instead of a standing exception.
- **Field/windows:** no new tournament run at all — Gate A, Gate L, the live matrix, Gate C and the
  ranking are round 11's exact stored computations, reused by import (`round12.py` imports
  `round10.gate_a`, `round10.rung_excess_vs_qqq`, `round11.live_cells`) rather than restated.
- **Result:** threshold = 1.00 novel name/session, walked down the round-11 ranking. `B3-concentrated`
  seats unconditionally; `B-momentum` seats at **1.32** novel names (23.3% of its book);
  `A-rotation` seats at **1.32** (49.9%); `C-trend` seats at **1.21** (37.0%). `B4-tight-stop` (0.00
  novel names — **identical book to `B-momentum` on all 127 live sessions**, mean daily Jaccard 100%)
  and `B2-hold-90` (0.08) are excluded despite clearing every gate.
- **Verdict:** the four seats reproduce exactly the desk's existing (owner-overridden) roster. The
  document states directly that this is **not independent confirmation**: *"the same evidence, scored
  by a rule partly shaped by watching this exact pairing get overridden, reproducing that pairing is
  expected, not remarkable."* No card promoted or demoted beyond what round 11 already seated.
- **What it corrected:** nothing new; it re-derives round 11's seats under a different, more
  defensible distinctness rule and documents that the rule still cannot see the weights-vs-names
  difference between `B3-concentrated` (4 slots/22%) and `B-momentum` (6 slots/15%).
- **Also in round 12: `ROTH-CANDIDATES.md`** ran `ROTH-MOMENTUM.md`'s and `ROTH-VOLTARGET.md`'s seven
  `WeightFn` variants through the contribution harness over round 5's 27-window horizon ladder for the
  first time (see §2 below for the concepts and findings — this is not a `StrategyCard` result and
  isn't gated in round 12's own selection).
- **D6 (store-drift) disclosure:** round 12's own store check found `SPY: 8448 rows, last 2026-08-21`
  against the round 11 document's claimed `8445 rows, last 2026-08-18` — three extra sessions
  appended by concurrent unrelated work. Every computation in round 12 is bounded at or before
  2026-08-18, so the drift is inert to every number reported, but the claim "the store is unchanged"
  is what breaks (see §0 above).
- **Left open:** cards with no live record still have no distinctness path in; `B4-tight-stop` is a
  duplicate row and should be reconsidered; weights vs. names is still unmeasurable by any existing
  rule.

### Round 13 — not a competition round

See §0 above. Covered under §3 (concepts tested) as the savings-family backtest.

### Round 14 — naming the chooser

*Source: `strategy-program/ROUND-14-PLAN.md`, `data/rounds/r14-2026-08/SELECTION.md`,
`NARRATIVE.json`.*

- **Question pre-registered:** does naming `StrategyCard.rank_by` (the tie-break deciding which
  qualifying name takes a scarce slot when more names qualify than fit) meaningfully reduce the
  arbitrariness `PROTOCOL.md` §7 already measured at **53.9 points of spread over twelve orderings of
  one identical card**? Explicitly *not* "does a ranking key add alpha."
- **Field:** 5 base cards chosen on measured headroom (universe size − slots): `B3-concentrated`
  (headroom 8), `c19-volatility` (8), `B-momentum` (6), `A-rotation` (6), `C-trend` (4); plus one
  zero-headroom control, `c21-uncorrelated`. Three ranking keys tested: relative strength
  (`close/sma(200)`), low-volatility (`−atr(14)/close`), "stretch"
  (`(close−sma(20))/atr(14)`) — 16 variant cards run against 6 frozen bases, in round 14's own
  directory, touching no existing results tree.
- **Windows:** round 2's eight main regime windows (`score.MAIN_WINDOW_TAGS`), rerun with round 14's
  own cards. 176 runs expected; 164 ran — the 12-run shortfall traced to honest lookahead-guard refusals
  (`META` in `chop-2011`, `AVGO` in `gfc`, missing pre-window history), not store contention, and it
  fell on whole card families, not biasing any single comparison.
- **Result:** control passed exactly (0.00 divergence over 8 windows, after correcting a false-positive
  contention-counting bug that mistook trade-log *row order* for economic difference). On **4 of 5**
  base cards, the entire choice of ranking key — including making no choice at all — is worth **under
  1.3 points** of median adjusted excess (`B3-concentrated` 0.62, `c19-volatility` 0.58, `B-momentum`
  1.29, `C-trend` 0.67). **`A-rotation` is the exception: 8.88 points of spread**, and the only card
  where a key flips the sign (−7.16% unranked → **+0.72%** under relative strength). Headroom did not
  predict contention: `c19-volatility` (headroom 8) was contested in 7 of 8 windows, `B3-concentrated`
  (also headroom 8) in only 2 of 6.
- **Verdict:** **round 14 selects nothing** — no card seated, no gate changed, desk roster unchanged. It
  is a measurement round about the engine, not the field.
- **What it corrected:** nothing about an earlier round's seat, but flags a caution about `A-rotation`
  specifically — it "would read about nine points differently under a different, equally defensible
  slot-selection key," though the card actually seated (round 10's owner override) is the unranked,
  as-typed order, so the seated figures are not shown to be mis-scored.
- **Left open:** the 53.9-point figure is one measurement on one card; round 14 is a second, mostly
  confirming (spread is small) but with one sharp exception; `rank_by` "reads here as a per-card
  parameter, not a setting with a right value"; a field selected on measured contention (not headroom)
  would be the better follow-up experiment.

### Round 15 — three accounts, three scoring bases

*Source: `strategy-program/ROUND-15-PLAN.md`, `ROUND-15-CANDIDATES.md`,
`data/rounds/r15-2026-08/SELECTION.md`, `NARRATIVE.json`.*

- **Question pre-registered:** does the funding shape of an account (lump sum vs. monthly drip vs.
  annual Roth contribution) change which strategy belongs in it? All 54 scored agents across every
  prior round were `purpose="trading"` (lump-sum) cards — never asked before.
- **Blocker addressed first (this round's real engineering content):** `AllocationResult`/`LadderResult`
  are separate pydantic models from `AgentResult` (not `isinstance`-compatible), so the scorer could
  not load a round-15 candidate at all; `capital_exposure` means a different quantity for a
  continuously-invested allocation book (≈1.0 always) than for a `StrategyCard`, so
  `adjusted_excess = corrected_return − capital_exposure × benchmark_return` "silently becomes a
  different metric" if fed an allocation book; and `contributions.simulate` (the only IRR/deposit-stream
  harness in the repo) takes a hand-written `WeightFn` closure, not a card, so no prior savings/Roth
  study was a frozen, competition-eligible entry. Round 15 built two adapters: a `ScoredRun` reader
  that **refuses** to compute `adjusted_excess` for an invested-value-basis run rather than silently
  producing one, and `card_weight_fn(card)` letting one frozen `AllocationCard`/`LadderCard` run both
  lump-sum through the real engine and contribution-funded through `simulate`.
- **Field:** three sub-rounds by `purpose` — 15-T trading ($100,000 lump sum), 15-S savings ($20,000 +
  $1,000/mo, with a $500/mo sensitivity arm), 15-R roth ($30,000 + $7,500/yr, Roth-disjoint tickers).
  Five new `AllocationCard`s authored as three tilt-vs-static matched pairs (see §2 below for the
  concepts) plus four already-frozen cards entering as-is (`qld-schd-sgov`,
  `spy-schd-agg-gld-bil-atr-tilt`, `ladder-qld-schd`, `ladder-sso-vig-bnd`).
- **Windows:** trading arm on round 2's eight main windows; contribution-funded arms restricted to
  windows ≥3 years (round 5's `h10y-1`, `h10y-2`, `h5y-1`, `h5y-2`, `h5y-3`); a QQQ single-leg
  benchmark blend was added to `benchmarks.REGISTRY` as a prerequisite (previously only `spy` and
  `60-40-spy-agg` existed).
- **Gates, both had to pass first:** Gate 1 (bridge weight-fidelity) — 753 comparisons, **zero
  mismatches, worst gap zero**. Gate 2 (ending-equity agreement between `run_allocation` and
  `simulate`) — passed its pre-registered 1.00% tolerance at **0.6567%** divergence, but the *cause*
  is a finding in itself: the real engine (`run_allocation`) rejected **58 buy orders for insufficient
  cash** as a leveraged sleeve fell, while `simulate` has no cash constraint and always rebalances to
  target. **Every savings and Roth number in round 15 is stamped `cash_constraint_modelled: false` and
  is systematically optimistic**, most so in exactly the deep-drawdown case where rebalancing matters
  most.
- **Result — four pre-registered predictions:**
  - **P1, FALSIFIED (the round's most useful result):** predicted the monthly drip would rank *better*
    than an equivalent lump sum on the most volatile card (`qld-schd-sgov`) because "a drip buys more
    of a fallen sleeve." Measured against a same-harness lump sum: the drip **lost** by −2.78 points
    (h10y-1) and −0.80 (h10y-2), winning only in h5y-3 (**+2.52**, the one window with a bear market).
    *"Across both decade windows the cost of being out of a rising market swamps the benefit of buying
    its dips, and the drip loses."*
  - **P2, HELD:** IRR and time-weighted CAGR diverged >2pp on exactly one card, the most-leveraged one
    (`qld-schd-sgov`, **3.11pp**; next highest `spy-schd-agg-gld-bil-static` at 1.86pp).
  - **P3, HELD:** $500/mo and $1,000/mo drip sizes never inverted the ranking across three windows.
  - **P4, HELD but only on its second clause, and later corrected (see round 16):** no candidate beat
    QQQ on *both* return and drawdown. As originally published, `ladder-sso-vig-bnd` appeared to beat
    QQQ on return in 2 of 5 windows (h5y-1: 22.16% vs 19.76%; h5y-3: 16.96% vs 12.42%) while losing on
    drawdown — later found to be a measurement artifact (see round 16).
- **Tilt-vs-static matched pairs (isolating one decision each):** Roth arm — the mean-reversion tilt
  beat its static twin in **5 of 5 windows**, +0.27 to +0.65pp CAGR, for ~1.5pp more drawdown. Trading
  arm — regime-dependent: the ATR tilt was worth **+3.65pp in the GFC window**, cost **−2.15pp in
  COVID**, and was **byte-identical to its static twin in the "recent" window** (the ATR gate never
  fired once in a full year) — "a tilt that never fires is not free: it is an unexercised claim on the
  reader's attention and a parameter in the budget." On the trading leaderboard's own ranking (median
  excess, 8 windows), the tilted card ranked **last** of the three trading-arm entrants (+5.81% vs.
  `qqq-ief-gld-static`'s +6.35% and `ladder-qld-schd`'s +6.76%) — its edge sits entirely in two tail
  events, which the median statistic ignores.
- **Verdict:** nothing promoted — `PROTOCOL.md` §6 needs two consecutive rounds on differing window
  sets, and round 15 is the first round any savings or Roth card ever ran in. The leaderboards were
  empty before "for absence of measurement, not poor results," and are populated now but still not a
  promotion basis.
- **What it corrected:** nothing from a prior *competition* round (there was no prior savings/Roth
  evidence to correct) — but it is itself later corrected by round 16 (see below).
- **What it left open, verbatim from its own §7:** *"The cash-constraint asymmetry is unclosed... it
  may move the P1 result, since the drip's advantage in h5y-3 is exactly the case where a real account
  would most often fail to fund the rebalance."* *"Vol-targeting and inverse-vol risk parity remain
  inexpressible. `TiltRule.shift_pct` is a fixed `Decimal`, not a function of an indicator's magnitude.
  `ALLOCATION-FAMILY.md` found the vol-target variant the strongest on risk-adjusted terms, and it is
  still not a card. Closing that needs a formula-valued tilt field or a fourth card type; a boolean
  staircase imitating a continuous function was explicitly refused."* *"ATR-gated cards cannot be
  scored under any contribution schedule until the bridge carries high/low, which means the savings arm
  structurally cannot evaluate one of its own frozen cards"* (`spy-schd-agg-gld-bil-atr-tilt` did not
  run in the savings arm at all — the bridge raises rather than silently letting its ATR-gated tilt
  never fire).

**CORRECTION appended to round 15's own `SELECTION.md`, dated 2026-08-24, by round 16:** round 15's
`round15.py` created one `card_weight_fn` **per card** and reused that same closure object across all
five long windows. This is harmless for `AllocationCard` (stateless closure — all 26 allocation cells
reproduced exactly) but **`LadderCard`'s closure is a state machine** (armed rung depth,
cycle-starting high), so each window after the first silently inherited the previous window's state.
Corrected `ladder-sso-vig-bnd` figures: h10y-1 unchanged (8.14% — it ran first, fresh closure, "the
signature that confirms the cause rather than merely fitting it"); h10y-2 falls **7.90 points**
(18.53%→10.64%); h5y-1 falls **16.07 points** (22.16%→6.09%); h5y-2 falls **15.73 points**
(27.36%→11.63%); h5y-3 falls **7.19 points** (16.96%→9.77%). Corrected, `ladder-sso-vig-bnd` never
beat QQQ on either return or drawdown, in any window — P4's verdict holds *more* strongly, but the
supporting sentence "its case rests on return, and drawdown is the bill" is **false and retracted**.
Original contaminated records preserved at `data/rounds/r15-2026-08/contributions/roth-CONTAMINATED-INVALID/`.

### Round 16 — what the cash constraint is worth

*Source: `strategy-program/ROUND-16-PLAN.md`, `data/rounds/r16-2026-08/SELECTION.md`,
`NARRATIVE.json`, `paired.json`.*

- **Question pre-registered:** how much of round 15's savings/Roth result is an artifact of a
  contribution harness that can always afford to rebalance, when the real engine's account cannot?
  Direct follow-up to round 15's own disclosed limitation.
- **Field:** every round-15 contribution cell (5 windows × drip sizes × 5 savings/Roth cards) re-run
  paired — same card, same window, same schedule — under a new `cash_constrained: bool` mode of
  `contributions.simulate` (default `False`, so all round-15 numbers stay reproducible). Under
  `cash_constrained=True`: sells execute before buys (not dict order), buys are capped at available
  cash (a shortfall is counted, not silently absorbed), and a rejection counter attaches to
  `ContributionResult`. Settlement lag deliberately **not** modelled, to keep one variable isolated.
  31 paired cells total, recorded in `paired.json`.
- **Result:** **zero underfunded buys across all 31 cells.** Mean drag +0.000pp, worst drag −0.000pp.
  All 31 unconstrained cells reproduced round 15 exactly (regression check passed). Two mechanisms
  already made the unconstrained harness cash-safe by construction (the contribution pre-buy step
  spends only `min(cash, need)`; a band-breach rebalance nets to zero across the book because targets
  sum to at most 1.0 of equity), so the only overdraw the old code could ever produce was a transient,
  mid-loop one from dict-order symbol walking — never a net one. Re-checking round 15's own control
  window (`r15_control.py`) after the change: divergence **unchanged at 0.6567%**.
- **Verdict on the four pre-registered predictions:** #1 (bias real and one-directional) —
  **FALSIFIED**, zero not small. #2 (bias largest for `qld-schd-sgov`) — **FALSIFIED**, no card took
  any hit. #3 (round 15's P1 survives in direction, shrinks in magnitude) — **HALF**: survives exactly,
  does not shrink at all. #4 (divergence falls below 0.30%) — **FALSIFIED**, unchanged at 0.6567%.
- **Same-day follow-up (still 2026-08-24), the divergence explained:** prediction 4 had named its own
  consequence — staying above 0.50% would implicate settlement lag over the cash cap. Three suspects
  were checked directly: (1) whole-share fills — **eliminated**, `r15_control.py` already sets
  `allow_fractional_shares=True`; (2) settlement lag — **confirmed**, via
  `backend/app/paper/paperbroker.py`'s own docstring and code (`self._unsettled`, `available =
  self.settled_cash(fill_date)`): the real engine holds sale proceeds unspendable for
  `settlement_days` and logged **59 `insufficient_cash` rejections** in the identical window with
  fractional shares on and all friction zeroed, which the pure cash-cap (settlement-free by
  construction) could never reproduce; (3) decide-at-close/fill-at-open lag — **tested and eliminated**
  (`r16_fill_lag.py`): adopting the engine's own fill timing made the gap **1.9% worse**, not smaller.
- **Headline:** *"The bias is zero, not small... That result is not evidence that a real account's
  funding constraint is immaterial — it is evidence that a cash cap without settlement is not the
  constraint a real account has. The optimistic bias round 15 warned about is real; round 16 built the
  wrong instrument to measure it, and now knows which one to build."*
- **What it invalidated/corrected:** round 15's *stated cause* for the 0.6567% divergence (the cash
  constraint) — wrong; the 58/59 rejections are real but the aggregate cash was never binding. It also
  found and corrected the `ladder-sso-vig-bnd` stateful-closure defect in round 15 (documented above,
  under round 15).
- **Left open:** the 0.66% divergence is now attributed to settlement, not yet closed by a fix — "next,
  concretely: give `contributions.simulate` a settlement lag, not just a cash cap, and re-run this
  comparison." `cash_constrained=True` stays in the harness as inert insurance for a future card with a
  larger relative rebalance. Nothing promoted — a paired re-use of round 15's windows is explicitly not
  the second independent measurement `PROTOCOL.md` §6(b) requires for promotion.

---

## 2. Every distinct strategy concept tested, rounds 9–16

Named concretely, not by card id alone.

1. **Rank-stability-across-matrices as a promotion gate** (round 9's Gate S) — worst rank ≤5 across
   three frozen matrices, later found to conflate competitiveness (already measured by Gate A) with
   dispersion (what the override was actually reaching for).
2. **Coverage + pure rank-dispersion gate** (round 10's Gate S′) — `max rank − min rank ≤ 3` across
   ≥2-of-3 matrices, no level term.
3. **Live-record-weighted ranking with a liveness/positivity floor** (round 11's fix 4) — Gate C
   (positive in ≥3 of 6 live sub-periods), ranking on median live `adjusted_excess`, backtest rank
   range demoted to a tie-break only.
4. **Holdings-overlap distinctness** (round 12) — "novel names held per invested session" against the
   union of already-seated cards, ≥1.00 threshold, replacing a base-family/discipline distinctness
   clause that couldn't discriminate `B3-concentrated` from `B-momentum`.
5. **Savings-purpose static blends** (`SAVINGS-FAMILY.md`/round 13): **Broad-Market Core**
   (fixed SPY 80% / AGG 20%, no signal — "the known trap," outperforms 60/40 purely by holding more
   equity) and **Diversified Multi-Asset Core** (fixed SPY 35% / SCHD 20% / AGG 30% / GLD 15%, or SPY
   55%/AGG 30%/GLD 15% pre-SCHD — best MAR in every window tested, a genuine structural drawdown
   reduction, not a disguised equity-weight trade).
6. **Horizon glidepath, contribution-funded** (`SAVINGS-FAMILY.md` variant 3) — SPY/AGG, 90%→60%
   equity linear over 20 years as a pure function of elapsed time, no price signal at all. Worst MAR in
   its family over a 22.85-year window, because the 20-year glide is too slow relative to the window
   tested.
7. **Volatility-trimmed core, monthly-checked** (`SAVINGS-FAMILY.md` variant 4) — SPY 70%/AGG 30%
   base, cuts 20 points to AGG when SPY's 60-session realized vol ≥18% (near its 75th percentile),
   reverts only below 13% (its median), checked monthly not daily. Best risk-adjusted (MAR) number in
   its window, at ~7x the turnover cost of the static blend.
8. **Contribution-funded IRR vs. time-weighted CAGR, reported as a mandatory pair** — every
   contribution-funded family (savings, `ROTH-CANDIDATES.md`, round 15) reports both figures because
   they diverge specifically when sequence risk bites; round 15's own measurement found the divergence
   >2pp on exactly the most-leveraged card (3.11pp).
9. **Roth/momentum family on the tournament's own 27-window ladder** (`ROTH-CANDIDATES.md`, round 12)
   — absolute momentum, moving-average regime switch, confirmed-regime blend, and a static
   40/30/30 QLD/SCHD/IEF baseline. On common-support windows only (where every variant's signal is
   live), the MA regime switch beats the static blend by 5.4 points on the ladder arm (+10.3% vs
   +4.9%), but the static blend is the *worst* variant of the field in the six bear-supplement windows
   (a genuine "timing costs in calm history, pays in a crash" finding).
10. **Roth/vol-target family on the same ladder** (`ROTH-CANDIDATES.md`) — vol-target 12% at 20-session
    lookback, risk-budgeted core, and a volatility circuit-breaker. None clears +5% median at any single
    ladder horizon; the circuit-breaker's bear-arm result (+12.2% median) sits awkwardly against its own
    source document's "flag rather than keep or discard" verdict.
11. **Slot-selection ranking keys** (round 14) — relative strength (`close/sma(200)`), low-volatility
    (`−atr(14)/close`), and momentum-stretch (`(close−sma(20))/atr(14)`) as `StrategyCard.rank_by`
    tie-breaks for scarce-slot contention, tested against the as-typed (unranked) order and against
    `PROTOCOL.md` §7's 53.9-point ordering-arbitrariness baseline.
12. **Purpose-fit allocation pairs — tilt vs. static, matched sleeves, three account types** (round 15):
    - Savings: `spy-schd-agg-gld-bil-atr-tilt` (ATR-gated 20-point shift) vs.
      `spy-schd-agg-gld-bil-static`.
    - Trading: `qqq-ief-gld-atr-tilt` (QQQ/IEF/GLD, ATR(14)>2.8% of close shifts 10pp QQQ→IEF) vs.
      `qqq-ief-gld-static`.
    - Roth: `sso-vig-bnd-mean-reversion` (SSO below 150-day SMA shifts VIG→SSO; SSO above its own
      20-day/2σ Bollinger band shifts SSO→BND) vs. `sso-vig-bnd-static`.
13. **Lump-sum vs. contribution-funded ranking, same card, same harness, only the money's timing
    differing** (round 15's P1 test on `qld-schd-sgov`) — the direct test of whether funding shape
    changes which strategy is preferred; found the drip loses to an equivalent lump sum across a
    rising decade and wins only in a bear-market window.
14. **Cash-constrained contribution simulation** (round 16) — sells-before-buys ordering plus a
    cash-availability cap on `contributions.simulate`, isolating whether the harness's unconstrained
    rebalancing was inflating every savings/Roth figure. Measured as exactly zero effect; the follow-up
    isolated the true cause as settlement lag, not aggregate cash.
15. **Settlement-lag attribution, isolated by direct comparison** (round 16 follow-up,
    `r16_fill_lag.py`) — ran `simulate` at `close[i]` vs. `open[i+1]` fill prices to rule out
    decide/fill timing as the cause of the engine/harness divergence, leaving settlement as the
    confirmed remaining term.

---

## 3. Ideas raised and explicitly NOT tested — verbatim, with attribution

These are the most valuable output of this inventory, per the task brief. Quoted directly from the
named source document.

- **Vol-targeting and inverse-volatility risk parity remain inexpressible**, because
  `AllocationCard.TiltRule.shift_pct` is a fixed `Decimal`, not a function of a real-valued indicator.
  From `strategy-program/ROUND-15-CANDIDATES.md`: *"Continuous vol-targeting —
  `SPY_weight = min(1.0, target_vol / realized_vol(SPY, lookback))`... At a 12% target and 60-session
  lookback this was the single best risk-adjusted number in that whole study (FULL-window MAR 0.34,
  beating both SPY and QQQ buy-and-hold)... Continuous inverse-volatility risk parity —
  `weight_i = (1/vol_i) / sum(1/vol_j)` across SPY, IEF, GLD, recomputed every session with no
  privileged 'core' sleeve. Neither is attempted here, nor approximated by a staircase of boolean
  `TiltRule`s stepping through several fixed thresholds — that staircase is explicitly named as the
  smuggling this round's design discipline exists to prevent... `shift_pct` is a `Decimal` declared once
  on the card — a fixed number of percentage points, identical whether the triggering condition is
  barely true or wildly true."* Closing it needs either a formula-valued tilt field on `TiltRule`, or a
  fourth card type (a `VolTargetCard`/`RiskParityCard` with its own engine, the way `LadderCard` was
  built when `AllocationCard` didn't fit a state machine). Restated as still-open in
  `data/rounds/r15-2026-08/SELECTION.md` §7 after round 15 ran.

- **No lump-sum re-expression of any contribution-funded Roth/savings variant through the real
  tournament engine.** From `data/rounds/r12-2026-08/ROTH-CANDIDATES.md`: *"No lump-sum re-expression
  of any variant through `app.tournament`'s engine — explicitly out of scope for this pass"*; and from
  `strategy-program/SAVINGS-FAMILY.md`: *"For any of these variants to be seated on the tournament's
  own roster, the same three-part gap `ALLOCATION-FAMILY.md` already documented for its own family
  would have to be closed first: widening `AgentResult.card`'s type, running the card through the
  round's actual window grid instead of one long backtest, and re-deriving what 'exposure-adjusted'
  would even mean for a continuously-invested, monthly-funded book. None of that is attempted here."*

- **No priming of momentum-family lookback state from bars before a window's start** — leaves 10 of 21
  ladder windows (and 6 of 21 for the MA/confirmed-regime variants) measuring the fallback sleeve, not
  the strategy. `ROTH-CANDIDATES.md`: *"a future integration into the tournament proper needs to prime
  a momentum-family strategy's lookback state from bars before the window starts... That is real work,
  not a two-line patch, and this script does not attempt it."*

- **Turnover/slippage cost not broken out as a bp-of-final-balance figure** for the Roth momentum/vol
  families in round 12's run, unlike `ROTH-VOLTARGET.md`'s own tables — *"a bp-of-final-balance cost
  figure was not recomputed here"* (`ROTH-CANDIDATES.md`).

- **The glidepath's 20-year horizon was not swept**, nor was a non-linear (front-loaded) glide built or
  tested — `SAVINGS-FAMILY.md`: *"a glide calibrated to a 10-year horizon... was not built or tested
  here, and is the most likely candidate to change variant 3's verdict."*

- **The vol-trim thresholds (18%/13%, 60-session lookback, 20-point cut) were set once and not swept.**
  `SAVINGS-FAMILY.md`: *"`ALLOCATION-FAMILY.md`'s own lookback-sensitivity section found the surface is
  not flat for a structurally similar rule; this module does not repeat that sensitivity check for its
  own thresholds."*

- **A fifth savings variant combining the glidepath's time-based de-risking with the diversified core's
  four-asset-class mix was not built.** `SAVINGS-FAMILY.md`: *"the most direct way to test whether
  variant 3's weak showing is really about the glide horizon rather than the two-asset universe it was
  tested on"* — not built.

- **Slippage sensitivity not swept** for the savings family — every number uses a flat 5bp assumption;
  *"a materially higher real-world cost was not swept to find where any of this family's rankings might
  change"* (`SAVINGS-FAMILY.md`).

- **VTI (a genuinely whole-market fund) was never used anywhere in the savings family** — SPY stands in
  throughout, *"the same substitution `ALLOCATION-FAMILY.md` already made and flagged: SPY is a
  large-cap index, not a total-market one"* (`SAVINGS-FAMILY.md`).

- **The cash-constraint asymmetry between `contributions.simulate` and the real engine's `PaperBroker`
  is still open at the end of round 16** — round 16 built and ruled out the wrong instrument (a pure
  cash cap); settlement lag is now the confirmed but still-unimplemented remaining term. From
  `data/rounds/r16-2026-08/SELECTION.md`: *"Next, concretely: give `contributions.simulate` a
  settlement lag, not just a cash cap, and re-run this comparison. The prediction to write down first is
  that the gap closes materially — and if it does not, the remaining term is something none of the
  three suspects named."*

- **A rule to resolve live evidence against backtest evidence has never been written**, despite two
  owner overrides in three rounds turning on exactly that tension. From
  `data/rounds/PROGRAMME-REPORT.md` §10.1: *"The programme has no rule for resolving live evidence
  against backtests, which is fix 4... and this is the first time it would have changed a seat rather
  than a footnote."* (Fix 4 was subsequently implemented in round 11, but the deeper tension — 127 or
  six months of live sessions vs. decades of regime-diverse backtest — is stated as unresolved even
  after fix 4 landed: round 11's own §4, quoted in the report, calls six contiguous sub-periods "not
  six regime draws.")

- **`rank_by` was tested on only five bases, chosen by a proxy (headroom) round 14 itself showed was
  "a measurably poor" predictor of contention** — no follow-up field selected on measured contention
  was run. `data/rounds/r14-2026-08/SELECTION.md` §6: *"A field selected on measured contention would be
  the better experiment, and that ordering was not available before running."*

- **The 53.9-point ordering-arbitrariness figure (`PROTOCOL.md` §7) is a single measurement on a single
  card** — round 14 supplies a second estimate on five more cards, but the underlying claim that
  arbitrary-ordering sensitivity generalizes across the whole 39-strategy field has still only been
  checked on six cards total across the programme's life.

- **A holdings-based distinctness rule cannot assess any card that has never traded live** — this
  blocks every candidate authored since round 5 from having any seat-eligibility path at all under
  round 12's rule, still open at the end of round 12: *"Cards with no live record still have no
  distinctness path into the competition... deciding how to seat the ROTH-MOMENTUM and ROTH-VOLTARGET
  specifications is the actual widening move available next"* (`r12-2026-08/NARRATIVE.json`).

- **ATR-gated allocation cards cannot be scored under any contribution schedule** — `contributions.py`
  passes closes only, and ATR needs high/low. `data/rounds/r15-2026-08/SELECTION.md` §4: the bridge
  *"raises rather than evaluating it: condition 'atr(14) > close * 0.018' uses indicator 'atr', which
  this bridge does not support — only ['bb', 'ema', 'macd', 'rsi', 'sma'] are computable from closes
  alone."* This structurally excludes `spy-schd-agg-gld-bil-atr-tilt` from the savings arm entirely,
  left open at round 15's close.

---

## 4. Figures quoted inconsistently across documents (attributed, per the rigour rules)

- **The bar store's row count/last-bar date "unchanged since round 9" claim** was quoted three
  different ways across three documents: round 11's §0 claimed *"SPY holds 8,445 rows ending
  2026-08-18"*; round 12's own store check found *"SPY: 8448 rows, last 2026-08-21"*
  (`data/rounds/r12-2026-08/SELECTION.md` §0); the `storestate.py` pin taken 2026-08-26 records
  *"SPY at 8,450 rows ending 2026-08-25"* (`strategy-program/DEFECTS.md`, D6 "What landed"). All three
  are internally consistent with an actively-growing gitignored store, not contradictory measurements
  of the same moment — but the same reassuring sentence ("the store is unchanged") was reused across
  documents whose underlying number had already moved, which is D6's whole point.
- **`ladder-sso-vig-bnd`'s h5y-1 and h5y-3 CAGR** is quoted two ways depending on which document is
  read: `data/rounds/r15-2026-08/SELECTION.md` as originally published states h5y-1 = 22.16%, h5y-3 =
  16.96% ("beat QQQ on return in two of five windows"); the same document's own 2026-08-24 correction
  section, and `data/rounds/r16-2026-08/SELECTION.md`, restate the corrected figures as h5y-1 = 6.09%,
  h5y-3 = 9.77% (never beating QQQ on return in any window). Both numbers appear in round 15's own
  file; the corrected one is authoritative, and the original is explicitly retained as evidence rather
  than deleted.
- **`r15_control.py`'s ending-equity divergence** is quoted as **0.6567%** in `data/rounds/r15-2026-08/SELECTION.md`
  §1 and reproduced unchanged in `data/rounds/r16-2026-08/SELECTION.md` §2 and its follow-up — this one
  is consistent across both documents (deliberately, since round 16 re-ran the identical control to show
  the cash cap did *not* move it).

---

## Summary

**Rounds covered:** 9 through 16 (round 13 established as not a competition round; round 16 established
as a completed measurement round with no `results/` tree).

**Round 13:** not a competition round. No `ROUND-13-PLAN.md` exists anywhere in the repository, and
`data/rounds/r13-2026-08/` holds a single file — `savings-family-run.txt`, the raw output of an
unrelated monthly-contribution savings-account backtest (`strategy-program/SAVINGS-FAMILY.md`). No
`StrategyCard` was gated, ranked, promoted, retired or seated; no owner override occurred. The job
round 13 was originally pre-registered for by `strategy-program/DEFECTS.md` D6 — pinning store state
into each round's `scorecard.json` — was built later, outside the round sequence, landing 2026-08-26 at
a clean boundary after an unrelated autonomous loop stopped.

**Round 16:** ran completely and produced a full pre-registered/falsified result (`SELECTION.md`,
`NARRATIVE.json`, `paired.json`), but never wrote a `results/` directory because it was never a
`StrategyCard` tournament round — it re-ran round 15's 31 contribution cells paired under a new
cash-constrained mode of `contributions.simulate`. `backend/app/api/competition.py` sets
`has_results=False` for exactly this condition (no `results/` subdirectory), so the API's report of "no
results" is a correct description of what round 16 produced, not evidence of an incomplete or aborted
run.

**Distinct strategy concepts tested across rounds 9–16:** 15 (enumerated in §2 above), spanning
promotion-gate redesigns (rank-stability, coverage+dispersion, live-weighted, holdings-overlap
distinctness), four savings-purpose allocation mechanisms (static 80/20, diversified multi-asset,
horizon glidepath, monthly vol-trim), two Roth candidate families re-run on the tournament's own
27-window ladder, three engine-level measurement studies (slot-selection ranking keys, purpose-fit
tilt-vs-static pairs across three account types, cash-constrained contribution simulation with a
settlement-lag follow-up).

**Three most significant "never measured" gaps:**

1. **Vol-targeting and inverse-volatility risk parity are structurally inexpressible** by the current
   `AllocationCard` model (`TiltRule.shift_pct` is a fixed `Decimal`, not a function of an indicator's
   magnitude) — despite `ALLOCATION-FAMILY.md` finding continuous vol-targeting the single best
   risk-adjusted number in its entire study (FULL-window MAR 0.34, beating both SPY and QQQ
   buy-and-hold). A boolean staircase approximation was explicitly refused as smuggling a grid search
   in as a design choice.
2. **The programme still has no rule for resolving live evidence against backtest evidence** in
   general — fix 4 (round 11) implemented one specific resolution (weight six months of live
   sub-periods above three decades-spanning backtest matrices), but the deeper tension is stated as
   unresolved in round 11's own text, and separately, no lump-sum re-expression of any contribution-funded
   strategy through the real tournament engine has ever been attempted, so savings/Roth findings and
   trading-purpose findings remain formally incomparable.
3. **The true cause of the 0.6567% divergence between the contribution harness and the real paper
   engine is confirmed (settlement lag) but not yet fixed** — round 16 built and ruled out a cash cap,
   isolated settlement as the remaining term via `PaperBroker`'s own unsettled-proceeds mechanism, and
   left "give `contributions.simulate` a settlement lag and re-run" as the next concrete, unimplemented
   step.
