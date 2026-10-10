# Strategy family design documents — evidence inventory

Read-only research pass over `strategy-program/ALLOCATION-FAMILY.md`, `SAVINGS-FAMILY.md`,
`ROTH-MOMENTUM.md`, `ROTH-VOLTARGET.md`, `ROTH-DISJOINT-LADDER.md`, `DRAWDOWN-LADDER.md`,
`VARIANT-DISCRIMINATION.md` and `THREE-PURPOSES-PLAN.md`, cross-checked against
`backend/app/paper/library/{base,variants,candidates,retired,allocation,ladder}/` and against
`data/rounds/r13-2026-08/`, `data/rounds/r15-2026-08/`, `data/rounds/r16-2026-08/`.

All figures below are quoted from the named document. **"Claim" = asserted in a design document.
"Measured" = a number produced by an actual backtest run reported in that document. "Seated" = a
JSON card physically present in `backend/app/paper/library/`.** These are kept separate throughout;
where a document itself blurs lump-sum backtest numbers against contribution-funded IRR/CAGR
numbers, that document's own warning against conflating them is quoted rather than paraphrased.

---

## 1. `ALLOCATION-FAMILY.md` — whole-market-core allocation, four variants

**Hypothesis.** Pick a whole-market ETF as a core, distribute across asset classes around it, and
size positions by volatility awareness — with **no leverage anywhere** (the family exists explicitly
to avoid "the leverage trap" already documented in `ROTH-VOLTARGET.md`).

**Backtester:** `strategy-program/tools/allocation_family.py`. Cost model: 5bp slippage one-way,
5% drift band, band-rebalance only.

### Concepts (A–D)

- **A. Static Core-Satellite** (`make_static_blend`) — fixed SPY 40% / SCHD 20% / AGG 20% / GLD 10%
  / BIL 10% (PRIMARY), SPY 60%/AGG 20%/GLD 10%/BIL 10% with SCHD folded into SPY (CRISIS, marked
  `*`). **Measured.** PRIMARY (2011-10-20..2026-08-11, 14.77y): CAGR 8.23%, maxDD −21.5%, MAR 0.38.
  CRISIS (2007-05-30..2011-10-19, 4.40y): CAGR 0.55%, maxDD −36.3%, MAR 0.02. **Seated** —
  `backend/app/paper/library/allocation/spy-schd-agg-gld-bil-atr-tilt.json`'s own base weights
  *are* this variant (its `rules` array is variant B's tilt layered on top; strip it and the card is
  variant A exactly, per the document's own "the candidate" section) — but there is **no standalone
  card on the shelf with the rules stripped**, i.e. the recommended candidate itself has no dedicated
  JSON file. **This is a gap**: the document's own headline recommendation ("Put forward: Variant 1,
  Static Core-Satellite") is not independently seated.
- **B. ATR-Tilt Core-Satellite** (`make_atr_tilt`) — identical base weights to A; while SPY's own
  rolling-mean ATR(14) is above 1.8% (≈80th percentile), shift 5pp SPY→BIL and 5pp SCHD→GLD,
  stateless (rebuilt from base every session). **Measured.** PRIMARY: CAGR 7.89%, maxDD −19.9%, MAR
  0.40, 44 rebalances, 25.0bp cumulative slippage cost. CRISIS: CAGR 0.35%, maxDD −32.6%, MAR
  **0.01, worse than variant A's 0.02 despite a shallower drawdown** — the document's own verdict:
  "not a strategy that clearly earns its complexity." **Seated** —
  `backend/app/paper/library/allocation/spy-schd-agg-gld-bil-atr-tilt.json`.
- **C. Continuous Vol-Target Core** (`make_vol_target_core`) — SPY weight =
  `min(1.0, target_vol / realized_vol(SPY, lookback))`, residual 50/50 IEF/GLD. Tested at
  `target_vol` ∈ {12%, 16%, 20%}, `lookback` ∈ {20, 60}. **Measured, FULL window (2004-11-18..
  2026-08-18, 21.71y).** Best risk-adjusted cell: 12% target, 60-session lookback, MAR **0.34** —
  "the best risk-adjusted number in this entire family" per the document, better than SPY (MAR 0.16)
  and QQQ (MAR 0.27) buy-and-hold in that window. Also the sharpest negative finding in the family:
  raising the target from 12%→20% (lb20) *improves* FULL-window CAGR (9.14%→9.71%) but in the 2008
  slice makes drawdown *worse* (−29.2%→−39.3%), **worse than the plain static 60/20/20 blend's
  −33.7%** — "the sharpest negative result in this whole family." **Not `AllocationCard`-expressible
  — see §5.** **Not seated** (cannot be).
- **D. Continuous Inverse-Volatility Risk Parity** (`make_inverse_vol`) — `weight_i = (1/vol_i) /
  Σ(1/vol_j)` across SPY/IEF/GLD, recomputed every session. **Measured, FULL window.** CAGR
  4.84–5.04% vs SPY buy-and-hold's 8.98% — "roughly half the market's own return" — for maxDD
  −17.6% to −18.2% vs static's −33.7%; 2008 slice essentially flat (−1.2% to −2.2% return). MAR
  0.27–0.29, "a modest, not dramatic, improvement over static's 0.25." Turnover 125x (lb20)/26.8x
  (lb60) of starting capital; 215.2bp/48.0bp of final balance in slippage. **Not
  `AllocationCard`-expressible — see §5.** **Not seated** (cannot be).
- **Candidate put forward:** Variant A (Static Core-Satellite), chosen specifically *because* it is
  expressible today, not because it scores best — the document states plainly that "if risk-adjusted
  return is genuinely the criterion, not 'is it expressible as a card today,' vol-target 12% at a
  60-session lookback is the stronger candidate on the numbers."

### Designed but never measured (this document)

- **A fifth, hybrid variant** combining B's discrete tilt with C's continuous core sizing — a
  card-expressible discrete approximation of vol-targeting, stepping through several fixed
  `TiltRule` thresholds instead of one continuous formula. Stated reason: "not built... flagged here
  as unfinished work rather than attempted under this task's own time and scope."
- **VTI** (or any genuinely whole-market fund) — SPY stood in throughout because no VTI bars are
  stored. Reason: data availability, not a design choice.
- **Recalibrating variant B's ATR threshold against the engine's real Wilder-smoothed `atr(14)`**
  rather than the module's own simplified equal-weight rolling-mean proxy. Reason: "a card author
  reproducing this rule... would get the real indicator, and this backtest's 1.8% threshold was
  calibrated against the proxy, not it" — stated as an open gap, not swept.
- **Slippage sensitivity** — every number uses a flat 5bp assumption; not swept upward to find where
  rankings (e.g. lookback choice) might flip.

---

## 2. `SAVINGS-FAMILY.md` — contribution-funded savings, four variants

**Hypothesis.** A $20,000-seed, $1,000/month (also modelled at $500/month) taxable account held
10–20 years needs its own scoring basis (money-weighted IRR *and* time-weighted CAGR), not
lump-sum `adjusted_excess`, because "contribution funding inverts sequence risk."

**Backtester:** `strategy-program/tools/savings_family.py`. Raw run recorded at
`data/rounds/r13-2026-08/savings-family-run.txt`.

### Concepts (E–H)

- **E. Broad-Market Core** (`make_static_blend`) — fixed SPY 80% / AGG 20%. **Measured**, CORE
  window (2003-09-29..2026-08-19, 22.85y, $1,000/mo): TWR 7.68%, maxDD −47.4%, MAR 0.16. **Explicit
  "known trap, demonstrated directly"**: "beats the 60/40 benchmark on every headline number...
  and the entire reason is that it holds more equity... not a smarter rule finding an edge."
- **F. Diversified Multi-Asset Core** (`make_static_blend`) — SPY 35%/SCHD 20%/AGG 30%/GLD 15%
  (native SCHD) or SPY 55%/AGG 30%/GLD 15%* (pre-SCHD fold-in). **Measured**, DIVERSIFIED-FULL
  (2004-11-18..2026-08-19, $1,000/mo): TWR 7.10%, MAR **0.21**, 2008 slice maxDD −25.1% to −26.7%
  vs SPY buy-and-hold's −42.9% to −48.4%. Document's strongest positive finding: "a genuinely
  different risk profile from either benchmark." **Candidate put forward.**
- **G. Horizon Glidepath** (`make_glidepath`) — SPY/AGG, 90%→60% equity, linear over 20 years, no
  price signal at all. **Measured**, CORE ($1,000/mo): MAR **0.1338–0.1340, the family's worst in
  every window at both rates** — "it pays variant 1's risk without variant 1's return" because the
  20-year glide is too slow relative to the 22.85-year window tested.
- **H. Volatility-Trimmed Core** (`make_vol_trim`) — base SPY 70%/AGG 30%, monthly check, 60-session
  SPY realised vol ≥18% cuts 20pp SPY→AGG, reverts at ≤13% (hysteresis). **Measured**, CORE
  ($1,000/mo): MAR **0.1765** — "the best risk-adjusted number in the CORE window at both rates" —
  at 8.14x–8.54x turnover vs variant E's 1.68x–1.71x (7x the cost for a 0.01–0.02 MAR gain).
- **Rate-dependence finding (the report's own highest-value number):** variant F's MAR in
  DIVERSIFIED-PRIMARY (native SCHD, 2011-10-20..2026-08-19, 14.79y) is **0.3837 at $1,000/mo (loses
  to SPY buy-and-hold's 0.3862) but 0.3922 at $500/mo (beats SPY's 0.3865)** — "this is the exact
  effect `THREE-PURPOSES-PLAN.md` warned about: a strategy ranked at one contribution rate is not
  guaranteed to rank the same way at another."

### Designed but never measured (this document)

- **The glidepath's 20-year horizon was not swept** — a 10-year or non-linear front-loaded glide
  "was not built or tested here, and is the most likely candidate to change variant 3's verdict."
- **The vol-trim thresholds (18%/13%, 60-session lookback, 20-point cut) were set once and not
  swept.** Explicit cross-reference: `ALLOCATION-FAMILY.md`'s own lookback-sensitivity section
  "found the surface is not flat for a structurally similar rule; this module does not repeat that
  sensitivity check."
- **A fifth variant combining the glidepath's time-based de-risking with variant F's asset-class
  diversification** (a multi-asset glidepath) — "not built, and is the most direct way to test
  whether variant 3's weak showing is really about the glide horizon rather than the two-asset
  universe."
- **VTI** as a whole-market substitute for SPY — same data-availability reason as
  `ALLOCATION-FAMILY.md`.
- **Slippage sensitivity** — not swept.

### Library cross-check

**No savings-purpose card exists anywhere in `backend/app/paper/library/`.** All four variants are
plain `WeightFn` closures in `savings_family.py`, explicitly **not** validated `StrategyCard`,
`AllocationCard` or `LadderCard` instances (the document states this itself in "what these results
cannot be compared to"). Round 15 later froze five contribution-scored cards including
`spy-schd-agg-gld-bil-static` (variant E/F's shape) under `data/rounds/r15-2026-08/cards/` — a
**round-scoped artifact, not a shelf-seated card** — and Round 15's own §6 records: "Nothing is
promoted... The savings and Roth leaderboards were empty before today for absence of measurement,
not for poor results. They are no longer empty. They are also not yet a basis for moving anything."

---

## 3. `ROTH-MOMENTUM.md` — four momentum/regime strategies, contribution-funded

**Hypothesis:** trend/momentum rules on a QLD-based Roth book, evaluated against static baselines
and each other, with the money-weighted-vs-time-weighted distinction stated up front (an 8.4pp IRR
vs CAGR gap on one QLD buy-and-hold row in the `gfc-2006-2011` window, from *when* money arrived,
not what the strategy did).

### Concepts (I–L)

- **I. Absolute (time-series) momentum** (`make_abs_momentum`) — QLD 100% if own trailing 12-month
  return positive, else defensive sleeve 100%, monthly. **Measured.** `schd-era-2011-2026`: TWR
  23.79%, MAR 0.42. `gfc-2006-2011`: maxDD −41.0%, "average QLD exposure over the window is still
  47.9%... it gets the direction right eventually, but 'eventually' is most of the way down."
  Verdict: **keep, with the crisis-window caveat spelled out.**
- **J. Dual momentum** (`make_dual_momentum`) — rank candidates on trailing 12-month return, hold
  top-N positive-only, else 100% cash-equivalent (SHY). **Measured.** "the weakest performer in
  every window" — SCHD-era MAR **0.23, worse than the plain static 40/30/30 blend's 0.41**. Verdict:
  **do not keep as specified**, though its GFC-window maxDD (−32.0%, shallowest of the momentum
  family) is noted as a capital-preservation merit.
- **K. Moving-average regime switch** (`make_ma_regime`) — QLD 100% while SPY > its own 200-session
  average, else defensive 100%, daily, no confirmation delay. **Measured.** `gfc-2006-2011`: TWR
  14.68% (vs IEF-substitute static's 7.55%), **MAR 0.48 — "the best MAR anywhere in this report."**
  Verdict: **keep — this is where the family's real edge lives**; **single best candidate** overall,
  chosen specifically for its GFC-window performance over the confirmed-regime variant's marginally
  better SCHD-era MAR (0.44 vs 0.43).
- **L. Confirmed regime** (`make_confirmed_regime`) — combine I and K; 50/50 split when the two legs
  disagree. **Measured**, and its own hypothesis was falsified: built on the premise that requiring
  agreement would *reduce* round-trip trades; instead it generated **more** (160 vs K's 125
  rebalances in `full-2006`; 104 vs 80 in SCHD-era; 42 vs 34 in GFC). "This was checked against the
  raw `rebalances` column, not asserted from theory, and it holds in all three windows." Verdict:
  reasonable but not the crisis-window improvement it was designed to be.

### Designed but never measured

- **No pre-2011 SCHD analog** — IEF substitutes throughout `full-2006`/`gfc-2006-2011`, "a
  materially different risk profile, not a stand-in."
- **Lookback and moving-average window lengths were not swept** — a single 252-session momentum
  lookback and 200-session trend average are used exactly as specified; "whether a shorter or
  longer window changes any of these verdicts is an open question this run does not answer."
- **TQQQ (3x) was deliberately not substituted for QLD (2x)** — stated reason: "would almost
  certainly have produced a better-looking table for exactly the leverage-trap reason this report
  warns against... building that variant would have invited presenting a bigger bet as a better
  rule." This is a policy exclusion, not a data gap.
- **No out-of-sample split / walk-forward** anywhere.

### Library cross-check

No momentum/regime Roth card (I–L) is present in `backend/app/paper/library/` under any
subdirectory. These remain `WeightFn` closures in `roth_momentum.py`, never seated.

---

## 4. `ROTH-VOLTARGET.md` — volatility-scaled and risk-budgeted Roth strategies

**Hypothesis:** the drawdown ladder's failure mode (see §6) is that drawdown-from-high is a
*lagging* signal; sizing exposure from realised volatility instead lets a strategy "act while a
crash is developing rather than one rung behind it."

### Concepts (M–P)

- **M. Vol targeting** (`make_vol_target`) — QLD weight = `min(1.0, target_vol/realized_vol(QLD))`,
  residual in IEF, capped at 1.0 (no margin in a Roth). Tested `target_vol` ∈ {12%,15%,20%},
  `lookback` ∈ {20,60}. **Measured.** Ranked by **worst MAR across three windows** (CRISIS/PRIMARY/
  FULL): 12%(lb20) worst-case MAR **0.34 — "the best worst-case in the entire table, baselines
  included, by a wide margin,"** nearly matching QLD buy-and-hold's own IRR in CRISIS (10.71% vs
  10.70%) while cutting maxDD from −84.3% to −29.1%. **Best candidate, kept.**
- **N. Inverse-volatility weighting** (`make_inverse_vol`) across QLD/income-sleeve/IEF. **Measured.**
  "essentially flat and mediocre across all three windows (0.22–0.26)," in PRIMARY
  "indistinguishable from the plain static 60/40 baseline (0.25 vs 0.25, identical to two decimal
  places)" because QLD's vol is persistently 5–10x IEF's, parking most of the book in IEF. **Verdict:
  the one to not keep, as designed.**
- **O. Volatility circuit-breaker** (`make_circuit_breaker`) on static 40/30/30 QLD/income/IEF — QLD
  cut to zero above 45% annualised vol, restored at ≤30% (hysteresis, calibrated from QLD's own
  33%/45–46%/61% median/75th/90th percentile vol distribution). **Measured.** PRIMARY MAR **0.53,
  "the single best result anywhere in the table,"** but CRISIS MAR **0.18, "the worst result in the
  vol-scaled family, barely better than the static 40/30/30 baseline (0.09)."** Verdict: **flag
  rather than keep or discard** — binary all-or-nothing exposure misses the sharp post-crash
  recovery rallies a continuous vol-target strategy captures partially.
- **P. Risk-budgeted core** (`make_risk_budgeted_core`) — this programme's own synthesis: QLD sized
  by vol targeting at a fixed 12% target; residual split between income-sleeve and IEF by *their
  own* inverse volatility (not a fixed ratio), built specifically for 2022, where "SCHD (equity
  beta) and IEF (rate duration) both drew down that year, but not together and not by the same
  amount." **Measured.** Worst-case MAR **0.27, "the second-best in the table."** **Verdict: keep,
  as the second choice** for anyone who wants more upside than 12% vol-target without vol-target
  20%'s leverage-trap exposure.
- **Leverage-trap finding, paired and explicit:** in PRIMARY, raising the vol-target from 12%→20%
  (lb20) monotonically *improves* every metric (TWR 12.58%→20.51%, MAR 0.35→0.44); in CRISIS the
  *same move monotonically worsens* every metric (MAR 0.35→0.25, maxDD −29.1%→−44.7%) — "the
  'better' setting in the bull window is worse in the bear window... because a higher vol target
  simply means holding more QLD on average."

### Designed but never measured

- **A SGOV-based defensive sleeve.** SGOV's history starts 2020-06-01; using it "would restrict the
  test to roughly six years, covering only the tail of PRIMARY, and was not built for that reason."
- **Independence of the windows** — CRISIS+PRIMARY=FULL is "one sequence of market history, not
  three independent trials"; a stagflationary bear, a sideways grind, or a bond-led crisis where
  IEF itself is the risky asset "could produce a different ranking entirely, and nothing here tests
  against one because none occurred in the available data."
- **Slippage sensitivity** — not swept.
- **Circuit-breaker threshold sensitivity (45%/30%)** — set once from QLD's own percentiles, "not
  swept the way lookback and target-vol were."
- **Anything beyond QLD/SCHD/IEF/SPY** — GLD, TQQQ, AGG, BIL, SHY "were available in the store but
  not incorporated into any variant here... out of scope for this pass."

### Library cross-check

No M–P card is present anywhere in `backend/app/paper/library/`. `ROUND-15-CANDIDATES.md` §7 and
`data/rounds/r15-2026-08/SELECTION.md` §7 both flag this directly: **"Vol-targeting and inverse-vol
risk parity remain inexpressible. `TiltRule.shift_pct` is a fixed `Decimal`, not a function of an
indicator's magnitude. `ALLOCATION-FAMILY.md` found the vol-target variant the strongest on
risk-adjusted terms, and it is still not a card."**

---

## 5. `ROTH-DISJOINT-LADDER.md` — the drawdown ladder re-expressed on Roth-safe tickers

**Hypothesis:** the drawdown ladder (§6 below) trades QLD/SCHD/IEF, which collide with a taxable
account's likely universe; under Rev. Rul. 2008-5 a wash-sale replacement bought inside an IRA
**destroys** the disallowed loss (no basis adjustment), strictly worse than an ordinary deferred
wash sale. The document asks whether the ladder can be re-expressed on disjoint tickers.

### Concept (Q)

- **Q. Ladder on SSO/VIG/BND** — same rungs, confirmation window, recovery rule and draw-down order
  as the original QLD/SCHD/IEF ladder, tickers substituted (SSO for QLD — different index, same
  leverage factor; VIG for SCHD — different index and selection philosophy; BND for IEF — different
  index *and* adds credit risk IEF does not have, "the weakest of the three [substitutions]").
  **Measured**, shared window 2011-10-20..2026-08-11 (14.77y, $7,500/yr): original (QLD/SCHD/IEF)
  IRR **11.59%**, MAR **0.45**; disjoint (SSO/VIG/BND) IRR **9.56%**, MAR **0.36**. Cost of the
  substitution: **−2.02pp IRR, −1.72pp CAGR, −1.10pp deeper maxDD, −0.09 MAR (≈20% relative)** —
  "not catastrophic... but it is not free." **Seated** —
  `backend/app/paper/library/ladder/sso-vig-bnd.json`.

### Designed but never measured

- **A computed correlation coefficient between each original/substitute pair** — "the case in §4 is
  made from index methodology and holdings composition, not from a computed correlation
  coefficient... that would be a reasonable next check and is not done here."
- **A dividend-ETF or Treasury-duration alternative closer to SCHD/IEF** — VYM, HDV, SPYD, SDY,
  NOBL, DGRO, IEI, GOVT, VGIT, VGLT, EDV, SPXL were all "wanted and not found in the store" — a
  **data-availability gap, not a design decision**.
- **The §1091 "substantially identical" question itself** — explicitly stated as "this author's
  judgement, not a ruling. A tax professional reviewing the specific fund pairs before any real
  capital moves is the actual safeguard here, not this document."

### The closure-contamination defect, resolved on this exact card

`Q` (`sso-vig-bnd`, filed as `ladder-sso-vig-bnd` in Round 15's harness) is the card the known
defect touched. **Round 15's runner (`round15.py`) created one `card_weight_fn` per card and reused
it across five long backtest windows.** For an `AllocationCard` this is harmless (stateless
closure — confirmed: "every one of the 26 allocation cells reproduced exactly"). **`LadderCard`'s
closure is a state machine, carrying armed rung depth and the cycle-starting high, so each window
after the first inherited the previous window's state.** Found by Round 16 while building a paired
comparison; the affected figures and the correction, quoted from `data/rounds/r15-2026-08/
SELECTION.md`'s own "CORRECTION, 2026-08-24 (same day, by round 16)":

| window | as published (contaminated) | corrected | delta |
|---|---|---|---|
| h10y-1 | 8.14% | 8.14% | **+0.00** (ran first, fresh closure) |
| h10y-2 | 18.53% | 10.64% | **−7.90pp** |
| h5y-1 | 22.16% | **6.09%** | **−16.07pp** |
| h5y-2 | 27.36% | 11.63% | **−15.73pp** |
| h5y-3 | 16.96% | 9.77% | **−7.19pp** |

This is the "up to 16 percentage points of CAGR" figure named in the task brief, precisely: **−16.07
points on `h5y-1`.** Confirming test cited in `data/rounds/r16-2026-08/SELECTION.md`: `SHARED
closure: run1 cagr=11.6330% run2 cagr=26.5207% same=False` vs `FRESH closures: run1 cagr=11.6330%
run2 cagr=11.6330% same=True`. **The conclusion these numbers fed did not survive the correction**:
"`ladder-sso-vig-bnd` did not beat QQQ on return in `h5y-1` or `h5y-3`. It never beat QQQ on either
return or drawdown, in any window" — reversing the (now-retracted) claim that its "case rests on
return." **The original, invalid records are kept as evidence at
`data/rounds/r15-2026-08/contributions/roth-CONTAMINATED-INVALID/`**, and were re-measured with
fresh per-window closures, per Round 16's own record. This defect belongs to Round 15's
`round15.py` harness, not to `ROTH-DISJOINT-LADDER.md`'s own backtester
(`strategy-program/tools/roth_disjoint.py`), whose §7 results table (IRR 11.59%/9.56%, MAR
0.45/0.36, quoted above) is a **single continuous 14.77-year run, not five independently-windowed
runs re-using one closure**, and is not implicated by this defect on its own terms — this is stated
because the two documents' numbers for the same card must not be silently merged.

**Note on the source of the general warning.** The abstract lesson — "a ladder closure reused
across windows once cost 16pp of CAGR" — also appears, without figures, in
`strategy-program/AGENTS-INTEGRATION-PLAN.md` (not one of the seven documents in scope here), cited
as a caution for a future agent-runtime build. That document does not itself name which card or
document the defect touched; **that attribution is established here**, from
`data/rounds/r15-2026-08/SELECTION.md` and `data/rounds/r16-2026-08/SELECTION.md` directly. Not
found: any mention of this defect inside `strategy-program/DEFECTS.md`'s own D1–D6 catalogue — the
defect is recorded only in the two round-selection documents named above, not in the programme's
central defect log. That gap is noted, not inferred away.

---

## 6. `DRAWDOWN-LADDER.md` — the original QLD/SCHD/(SGOV→IEF) ladder

**Hypothesis, as handed to the author:** hold SCHD; rotate into QLD at −10%/−20%/−30% S&P drawdowns
from all-time high; halve QLD on a new high. Claimed (external) result: $83,507 on $10,000,
23.7% CAGR, −41.1% maxDD, 2016-08..2026-08.

### Concepts (R–U)

- **R. Ladder as specified.** **Measured**, and this is the document's headline finding: **"the
  strategy as specified reaches a −72.7% drawdown through 2008 — worse than a static blend, and far
  worse than the index it triggers on."** `2006-06→2011-10`: CAGR +4.49%, maxDD **−72.7%**, MAR
  0.06, vs static 60/40's −69.5% and QLD buy-and-hold's own −84.0%. Root cause named directly: "no
  rule that reduces it, because its only de-risking condition is a new all-time high, which in 2008
  was more than four years away."
- **S. + Bounce confirmation** (50-session, SPY must close back above its own 50-session average
  before a rung fires). **Measured.** GFC MAR **0.06→0.17** (nearly triples), full-window MAR
  0.23→0.25.
- **T. + Time stop** (60 or 120 sessions without a new high cuts leverage). **Measured, and refuted
  — the author's own proposed fix, and the data said otherwise:** GFC CAGR turns **negative** (MAR
  **−0.05 to −0.07**) — "it sells at the bottom and misses the recovery, the classic whipsaw."
  **Explicitly recorded as a fix that does not work**, kept in the document because the author
  "expected it to help and the data said otherwise."
- **U. + Reserve sleeve (IEF, 30–50%)**, drawn down before SCHD. **Measured.** 40% IEF: GFC MAR
  **0.25** (from 0.17 with no reserve); "the surface is smooth across 30–50%, not a knife edge... 40%
  is chosen as the midpoint; anywhere in that band is defensible and this data cannot distinguish
  them." Root cause of the original defect stated plainly: "the defensive sleeve is not defensive...
  both sleeves fall together. SCHD fell 33% in 2022 and SPY fell 56% in 2008. There is no reserve —
  the strategy funds leverage by selling something that is also down." Named as a dropped part of
  the *original* three-ticker sketch (QLD/SCHD/SGOV): "It turns out to be the part that matters
  most."
- **Final version (S + U combined, 40% IEF, 50-session confirmation, full exit at +10% or 60
  sessions post-high):** **Measured** across four windows. GFC: CAGR +13.70%, maxDD **−55.0%** (from
  −72.7%), MAR **0.25**. "Essentially the same risk-adjusted return in every window, with the
  drawdown cut by 15 to 18 points." Explicitly **does not beat QLD** on return (13.95% vs QLD's
  24.50% over 20 years) or MAR (0.25 vs QLD's 0.29) — "What the ladder buys is a −55.0% worst
  drawdown instead of −84.0%. Whether 29 points of drawdown is worth 10 points of CAGR is a question
  about the holder, not about the data." **Seated** —
  `backend/app/paper/library/ladder/qld-schd-ief.json`.
- **Sensitivity checks, all measured and refuted/confirmed directly, not assumed:** trigger depths
  (−7/−15/−22 and −13/−25/−35 and −15/−25/−35 all tested; the specification's own −10/−20/−30 "are
  the right ones" — flat surface, 0.20–0.25 full-window MAR); signal choice (NDX/QQQ triggering
  "refuted" — SPX/SPY is the better trigger in the crisis window that matters); tranche sizes
  (larger tranches "score better on MAR in every window — and are not adopted," because "that
  improvement is only 'more QLD did better in a period where QLD did well,' the same trap.").

### Designed but never measured

- **Rolling five-year windows** rather than four fixed ones, "to see dispersion rather than a point
  estimate. The critique asked for this and it is not done here."
- **A synthetic 2x NDX back to 2000**, to include the dot-com collapse — "the single most likely
  source of a result that would change the conclusion."
- **SGOV or BIL in place of IEF**, "once enough history exists... IEF carries duration risk that a
  T-bill sleeve does not — and in 2022 that duration was itself a large drawdown."

---

## 7. `VARIANT-DISCRIMINATION.md` — the largest document, not a new-strategy family

**What it is, per its own §6:** a deterministic recomputation over **already-stored** `AgentResult`
data for four existing trading cards (`B-momentum` base, `B2-hold-90`, `B3-concentrated`,
`B4-tight-stop` — all four already seated in `backend/app/paper/library/base/` and
`backend/app/paper/library/variants/`), asking which of 44 stored backtest windows make their
differing exit rules (90-day hold cap, 8%-vs-12% stop, position sizing) actually bind. **It
introduces no new strategy concept** and reports no newly-run backtest — "every `AgentResult` read
here was already on disk before this script ran... this document is therefore a deterministic
recomputation over stored evidence, not a new measurement."

**Finding:** the largest spread on record is `h5y-1` (+69.11 percentage points four-way spread,
+28.49pp exit-only spread), and every top-5 discriminating window shares one shape — "a single name
... runs for well over 90 sessions without triggering the shared rule exit or either stop, so the
only thing that can separate the cards is whether a time-based backstop cuts the position off
first." The median exit-spread across all 44 windows is small; "most of the windows this program
has actually measured" cluster near zero. The document's own closing self-assessment: "This...
does not by itself justify adding a window to any future round's matrix — it says *what kind* of
window would separate these cards, which is a design input for choosing one, not a substitute for
running it." No inexpressible or unmeasured concept originates in this document; it is excluded
from the A–Z concept count below for that reason.

---

## 8. `THREE-PURPOSES-PLAN.md` — the trading/savings/roth split

Not itself a strategy family; it is the organisational document the other six were written to serve
(explicitly named as their common cause: contribution funding "inverts sequence risk," so savings
and roth cards need `contributions.py`'s IRR/CAGR basis rather than lump-sum `adjusted_excess`).

**What was built vs deferred, per its own §8 staging:**
- **Stage 1 (executed):** the `Purpose` enum, `PurposeSpec`, the `purpose` field on all three card
  models (defaulting to `TRADING`, so no existing card breaks), and the symbol-disjointness
  invariant/check — confirmed present in `backend/app/tournament/purposes.py`.
- **Stage 2 (deferred):** the desk restructure into three separately-funded, separately-benchmarked
  books (`PaperDeskState.books`). Per the 2026-08-23 update embedded in the document itself: "Half
  of that paragraph has since been done" — inception moved to 2026-08-15 and the desk's starting
  capital reads `PURPOSE_SPECS[Purpose.TRADING].seed`, but "the `books` wrapper, per-book benchmarks
  and the per-card `purpose` lookup are still ahead."
- **Stage 3 (deferred):** per-purpose competition, scoring and roster selection — three
  leaderboards, three gate sets. Depends on stage 2, not yet built.
- **`library/allocation/` is orphaned**, stated directly in §7: "No loader reads it — not
  `results.py`, not `jobs.py`, not `desk.py`. The allocation cards already committed there are
  unreachable." (Confirmed still true at inspection time — `qld-schd-sgov.json` and
  `spy-schd-agg-gld-bil-atr-tilt.json` sit in `backend/app/paper/library/allocation/` with no
  loader wired to read that path into the competition or desk.)
- **A blended (multi-symbol) benchmark** for the savings purpose is named as new code that does not
  exist yet: "Nothing in the codebase composes more than one symbol into one return."
- **Owner corrections tracked in the document itself, not silently overwritten** (per its own stated
  discipline against rewriting a plan after the fact): trading funding moved $100,000→$50,000
  (2026-08-23)→back to $100,000 (2026-08-24); trading horizon "under three years"→unbounded; roth
  seed set to $30,000 (an existing IRA balance) on top of the $7,500/year, not named at all in the
  original §1 table.

---

## A-to-Z concept inventory (summary table)

| # | Concept | Family doc | Status | Headline figure |
|---|---|---|---|---|
| A | Static core-satellite (SPY/SCHD/AGG/GLD/BIL) | ALLOCATION-FAMILY | Measured; base weights seated, standalone card not seated | PRIMARY CAGR 8.23%, MAR 0.38 |
| B | ATR-tilt core-satellite | ALLOCATION-FAMILY | Measured, seated | PRIMARY CAGR 7.89%, MAR 0.40 |
| C | Continuous vol-target core | ALLOCATION-FAMILY | Measured, **inexpressible** | FULL MAR 0.34 (12%,lb60) |
| D | Continuous inverse-vol risk parity (3-asset) | ALLOCATION-FAMILY | Measured, **inexpressible** | FULL CAGR 4.84–5.04% |
| E | Broad-market core 80/20 | SAVINGS-FAMILY | Measured, not seated | CORE TWR 7.68% |
| F | Diversified multi-asset core | SAVINGS-FAMILY | Measured, not seated (round-scoped card only) | DIVERSIFIED-FULL MAR 0.21 |
| G | Horizon glidepath 90→60/20y | SAVINGS-FAMILY | Measured, not seated | CORE MAR 0.1338 |
| H | Volatility-trimmed core 70/30 | SAVINGS-FAMILY | Measured, not seated | CORE MAR 0.1765 |
| I | Absolute momentum (QLD/defensive) | ROTH-MOMENTUM | Measured, not seated | SCHD-era MAR 0.42 |
| J | Dual momentum (top-N, cash fallback) | ROTH-MOMENTUM | Measured, not seated | SCHD-era MAR 0.23 |
| K | MA regime switch (SPY 200d) | ROTH-MOMENTUM | Measured, not seated | GFC MAR 0.48 |
| L | Confirmed regime (dual-signal) | ROTH-MOMENTUM | Measured, not seated | GFC MAR 0.38 |
| M | Vol targeting (QLD/IEF) | ROTH-VOLTARGET | Measured, not seated | worst-case MAR 0.34 |
| N | Inverse-vol weighting (3-asset) | ROTH-VOLTARGET | Measured, not seated | worst-case MAR 0.22–0.25 |
| O | Vol circuit-breaker (45%/30%) | ROTH-VOLTARGET | Measured, not seated | worst-case MAR 0.09–0.18 |
| P | Risk-budgeted core (vol-target + inverse-vol residual) | ROTH-VOLTARGET | Measured, not seated | worst-case MAR 0.27 |
| Q | Ladder on disjoint tickers (SSO/VIG/BND) | ROTH-DISJOINT-LADDER | Measured, seated; **contamination found and corrected** | IRR 9.56% (corrected) |
| R | Ladder as originally specified (QLD/SCHD, SPY-proxy) | DRAWDOWN-LADDER | Measured, refuted | GFC maxDD −72.7% |
| S | + Bounce confirmation | DRAWDOWN-LADDER | Measured | GFC MAR 0.17 |
| T | + Time stop | DRAWDOWN-LADDER | Measured, **refuted (hurts)** | GFC MAR −0.05 to −0.07 |
| U | + Reserve sleeve (IEF 40%) | DRAWDOWN-LADDER | Measured, seated (final version) | GFC MAR 0.25, maxDD −55.0% |

**21 distinct strategy concepts** (A–U) across five backtested families, excluding
`VARIANT-DISCRIMINATION.md` (re-analysis of already-seated trading cards, no new concept) and
`THREE-PURPOSES-PLAN.md` (organisational, not a strategy).

---

## Designed-but-never-measured set (highest-value output)

| Idea | Family doc | Stated reason |
|---|---|---|
| Hybrid discrete-approximation-of-vol-targeting (stepped `TiltRule` thresholds) | ALLOCATION-FAMILY | Scope/time — "flagged here as unfinished work" |
| VTI as true whole-market core (both allocation and savings families) | ALLOCATION-FAMILY, SAVINGS-FAMILY | No VTI bars stored |
| ATR(14) recalibration against the engine's real Wilder-smoothed indicator | ALLOCATION-FAMILY | Threshold calibrated against a simplified proxy, not the real indicator |
| Slippage-assumption sweep (all four allocation/roth/savings families) | ALLOCATION-FAMILY, SAVINGS-FAMILY, ROTH-VOLTARGET | Flat 5bp used throughout, never swept upward |
| 10-year / non-linear front-loaded glidepath | SAVINGS-FAMILY | 20-year glide untested against a shorter horizon; "most likely candidate to change variant 3's verdict" |
| Vol-trim threshold sweep (18%/13%, 60-session lb, 20pp cut) | SAVINGS-FAMILY | Set once, calibrated from percentiles, not swept |
| Multi-asset glidepath (glide + diversification combined) | SAVINGS-FAMILY | "the most direct way to test whether variant 3's weak showing is really about the glide horizon" |
| SGOV/BIL-based defensive sleeve (Roth vol families) | ROTH-VOLTARGET, DRAWDOWN-LADDER | SGOV history starts 2020-06-01 only — data availability |
| Lookback/MA window sweep for momentum legs (252d, 200d) | ROTH-MOMENTUM | "an open question this run does not answer" — avoided to prevent overfitting to specific historical paths |
| TQQQ (3x) substituted for QLD (2x) | ROTH-MOMENTUM | Deliberately excluded — "would... invite presenting a bigger bet as a better rule," a policy exclusion |
| Circuit-breaker threshold sweep (45%/30%) | ROTH-VOLTARGET | Set once from QLD's own percentiles, not swept |
| GLD/TQQQ/AGG/BIL/SHY as additional Roth sleeves | ROTH-VOLTARGET | "out of scope for this pass" |
| Direct correlation coefficient between each original/substitute ticker pair | ROTH-DISJOINT-LADDER | "a reasonable next check and is not done here" |
| Dividend/Treasury-duration alternatives (VYM, HDV, SPYD, SDY, NOBL, DGRO, IEI, GOVT, VGIT, VGLT, EDV, SPXL) | ROTH-DISJOINT-LADDER | All queried and returned empty from the bar store — data availability, not choice |
| Rolling five-year windows (dispersion, not point estimate) | DRAWDOWN-LADDER | "The critique asked for this and it is not done here" |
| Synthetic 2x NDX back to 2000 (dot-com collapse) | DRAWDOWN-LADDER | "the single most likely source of a result that would change the conclusion" |
| Cash-aware (broker-constrained) contribution harness for savings/Roth | THREE-PURPOSES-PLAN / Round 15 SELECTION | Round 15 found `run_allocation`'s real `PaperBroker` rejects 58 buy orders `contributions.simulate` always funds; "the single highest-value follow-up" |
| Three-book desk restructure, per-purpose blended benchmarks, per-purpose competition/scoring | THREE-PURPOSES-PLAN | Explicitly deferred (Stages 2–3); larger than Stage 1, "should not ride along" |

**18 designed-but-never-measured items** identified with a stated reason (some families report
several; the count above is per distinct idea, not per mention).

---

## Inexpressible-by-engine set (quoted precisely)

Two concepts are blocked by an engine limitation, not a decision, and both trace to the same root
cause: `TiltRule.shift_pct` is a fixed `Decimal`, not a function of a live indicator value.

1. **Continuous vol-target core sizing (variant C, ALLOCATION-FAMILY.md), and structurally
   identical concepts M in ROTH-VOLTARGET.md and Q's-would-be vol-target cousin.** Quoted verbatim
   from `ALLOCATION-FAMILY.md`:

   > "`TiltRule.shift_pct` is a `Decimal` declared once on the card — a fixed number of percentage
   > points, the same amount whether the triggering condition is barely true or wildly true.
   > Variant 3's core weight is `min(1.0, target_vol / realized_vol)` — a continuous function of a
   > real number that can be anywhere from 0 to 1.0 depending on how far realised volatility sits
   > from the target, and it changes by a different amount on two different sessions where the
   > underlying vol differs."

2. **Continuous inverse-volatility risk parity (variant D, ALLOCATION-FAMILY.md), and structurally
   identical concept N in ROTH-VOLTARGET.md.** Same document, immediately following:

   > "Variant 4's weights are `(1/vol_i) / sum(1/vol_j)` across every sleeve simultaneously — not a
   > shift *between* two named sleeves at all, but a full re-derivation of every sleeve's weight
   > from every other sleeve's current risk, every session. Neither has any representation in a card
   > whose only conditional mechanism is 'if this boolean is true, move this many percentage points
   > from sleeve A to sleeve B.'"

3. **What would close the gap**, per the same document — two options, neither built:

   > "A new field type on `TiltRule` — a formula or a reference to a computed quantity (e.g.
   > `weight = f(indicator_value)`) instead of a fixed `shift_pct` — which is a materially larger
   > change to a model this task was told to treat as read-only, not a small addition. [...] A
   > fourth card type... a `VolTargetCard` or `RiskParityCard` with its own `run_*` engine..."

4. **Confirmation the limitation still stood at Round 15**, after the family document was written,
   quoted from `data/rounds/r15-2026-08/SELECTION.md` §7:

   > "Vol-targeting and inverse-vol risk parity remain inexpressible. `TiltRule.shift_pct` is a
   > fixed `Decimal`, not a function of an indicator's magnitude. `ALLOCATION-FAMILY.md` found the
   > vol-target variant the strongest on risk-adjusted terms, and it is still not a card. Closing
   > that needs a formula-valued tilt field or a fourth card type; a boolean staircase imitating a
   > continuous function was explicitly refused."

**Deliberately explored and rejected, not blocked** — the "boolean staircase imitating a continuous
function" mentioned in quote 4 is `ALLOCATION-FAMILY.md`'s own proposed fifth-variant workaround (a
card-expressible discrete approximation of vol-targeting, stepping through several fixed `TiltRule`
thresholds). It is a *possible* expressible approximation the family document itself proposed but
never built (see the designed-but-never-measured table above) — it does not remove the
inexpressibility of the true continuous form, and Round 15 explicitly declined to build it as a
substitute.

**Two distinct inexpressible ideas**, both rooted in the one engine limitation quoted above.
`ROTH-VOLTARGET.md`'s M/N and `ALLOCATION-FAMILY.md`'s C/D are the same two concepts in two
different asset universes, not four independent inexpressible ideas.

---

## Disagreements between documents, named

- **`ROTH-DISJOINT-LADDER.md` vs `data/rounds/r15-2026-08/SELECTION.md`/`r16-2026-08/SELECTION.md`
  on the SSO/VIG/BND ladder's numbers.** `ROTH-DISJOINT-LADDER.md`'s own single 14.77-year
  continuous run reports IRR 9.56% / MAR 0.36 for the disjoint ladder — this run is **not**
  implicated by the closure-contamination defect (it is one continuous window, not five independent
  windows sharing a reused closure) and stands as reported. Round 15's *own* five-window matrix run
  for the same card was contaminated and initially reported figures up to 16.07 points of CAGR too
  high on `h5y-1`, corrected the same day by Round 16. The two documents are measuring the identical
  card on different window sets with different harnesses (single continuous window vs five separate
  long windows), so their numbers should not be read as duplicates of each other or reconciled to a
  single figure — both are named here specifically so a reader does not average them.
- **`ALLOCATION-FAMILY.md`'s lookback-sensitivity finding vs `ROTH-VOLTARGET.md`'s.**
  `ALLOCATION-FAMILY.md` states directly: "The lookback sensitivity does not point one direction
  here, unlike `ROTH-VOLTARGET.md`'s own finding. That document found the faster (20-session)
  lookback beating the slower (60-session) one on every metric, every strategy, every window, for
  QLD. Here the ranking flips by period." Both documents' own words are quoted because this is a
  named, explicit disagreement between two of the seven documents in scope, not an inconsistency
  found by this inventory.

---

## What is "not established"

- **Whether the closure-contamination defect touched any figure outside the ladder family (Q).**
  `ALLOCATION-FAMILY.md`'s and `SAVINGS-FAMILY.md`'s `WeightFn`s are all stateless closures by the
  documents' own design statements, and Round 15's own confirmation ("every one of the 26
  allocation cells reproduced exactly") supports this — but no equivalent per-cell reproducibility
  check for the savings-family or roth-momentum/voltarget closures (I–P) was located in any of the
  seven documents or the round-selection records reviewed. Not established either way for those.
- **Whether `spy-schd-agg-gld-bil-static` (Round 15's card) is definitionally identical to
  `ALLOCATION-FAMILY.md`'s Variant A.** The round-15 candidates document states the shared sleeves
  and weights; whether the JSON is byte-for-byte the "rules stripped" version described in
  `ALLOCATION-FAMILY.md`'s own candidate section was not independently diffed here.
- **Whether the cash-constraint asymmetry Round 15 found (`run_allocation`'s 58 rejected buy
  orders vs `contributions.simulate`'s unconstrained rebalancing) changes any of the ranking
  verdicts in `ALLOCATION-FAMILY.md`, `SAVINGS-FAMILY.md`, `ROTH-MOMENTUM.md` or
  `ROTH-VOLTARGET.md` themselves** — those four documents all use `contributions.simulate` or
  `allocation_family.py`'s own unconstrained rebalancing, so their own headline numbers may carry
  the identical optimism Round 15 flagged. Round 15's own SELECTION.md calls this "the single
  highest-value follow-up" and states plainly it is unmeasured. Not established.

---

## Summary

**Families covered:** 8 documents read (`ALLOCATION-FAMILY.md`, `SAVINGS-FAMILY.md`,
`ROTH-MOMENTUM.md`, `ROTH-VOLTARGET.md`, `ROTH-DISJOINT-LADDER.md`, `DRAWDOWN-LADDER.md`,
`VARIANT-DISCRIMINATION.md`, `THREE-PURPOSES-PLAN.md`); 5 of them (all but `VARIANT-DISCRIMINATION.md`
and `THREE-PURPOSES-PLAN.md`) design and backtest genuinely new strategy concepts.

**Distinct strategy concepts:** **21** (A–U above).

**Designed-but-never-measured items, each with a stated reason:** **18**.

**Inexpressible-by-engine concepts:** **2** (continuous vol-targeting, continuous inverse-vol risk
parity), both rooted in one precisely-quoted limitation — `TiltRule.shift_pct` being a fixed
`Decimal` rather than a function of an indicator's magnitude — appearing independently in the
allocation family (variants C/D), the Roth family (concepts M/N), and confirmed still unresolved in
Round 15's own selection record.

**Contamination found and reconciled:** the `LadderCard.card_weight_fn` closure-reuse defect
(Round 15→16), touching `ROTH-DISJOINT-LADDER.md`'s seated `sso-vig-bnd` card's five-window
matrix figures by as much as **−16.07 percentage points of CAGR** (`h5y-1`), corrected the same
day and recorded in both `data/rounds/r15-2026-08/SELECTION.md` and
`data/rounds/r16-2026-08/SELECTION.md` — but absent from the programme's central
`strategy-program/DEFECTS.md` catalogue.

**The single most valuable untested idea:** the **cash-constrained contribution harness**. Every
IRR/CAGR/MAR figure across `SAVINGS-FAMILY.md`, `ROTH-MOMENTUM.md` and `ROTH-VOLTARGET.md` — three
of the five backtested families, roughly a dozen of the 21 concepts above — was produced by
`contributions.simulate`, which (per Round 15's own Gate 2 finding) rebalances to target
unconditionally, while the real broker path rejected 58 of the identical buy orders in a single
control run because the leveraged sleeve had run out of financeable room exactly during the deepest
drawdown. Round 15's own words: "every savings and Roth number in this round is systematically
optimistic, and most optimistic exactly where it matters least defensibly: a deep drawdown in a
leveraged sleeve is when rebalancing to target is both most valuable and least affordable, and the
harness always manages it." No document in scope measures the size of that optimism for any of the
21 concepts; it is the largest unquantified risk sitting under this entire inventory.
