# Inventory: the strategy-programme's method, constraints, and known defects

Read-only research artifact. Scope is the testing apparatus itself — what it can measure, what it
refuses to measure, and which of its own past findings it has already invalidated — not a survey of
round results. Primary sources: `strategy-program/PROTOCOL.md`, `CONSTRAINTS.md`, `WINDOWS.md`,
`DEFECTS.md`, `README.md`, `docs/DEFINITIONS.md`, `backend/app/tournament/jobs.py`,
`strategy-program/tools/windows.py`, `backend/app/paper/library/README.md`, cross-checked against
`data/rounds/PROGRAMME-REPORT.md` (rounds 1–11) where that document adds verified figures. Every claim
below is attributed to a named document; where prose and code disagreed, code won, and the
disagreement is stated.

---

## 1. The window matrix — and the finding that code has outgrown the prose that describes it

**`strategy-program/WINDOWS.md` describes only the round-2/3 eight-window matrix.** Reading code
(`backend/app/tournament/jobs.py`, mirrored by `strategy-program/tools/windows.py`) shows the matrix
the served application actually runs against is much larger. This is the single clearest instance in
this inventory of "prefer code over prose": **WINDOWS.md is stale prose for one generation of the
instrument, not a description of the current one.**

### 1a. The eight round-2/3 "main" windows (`MAIN_WINDOWS` / `R2_MAIN_WINDOWS`)

Source: `WINDOWS.md`, confirmed byte-for-byte against `jobs.py` lines 132–140 and
`tools/windows.py` lines 95–103.

| tag | window | sessions | SPY return | regime | direction |
|---|---|---|---|---|---|
| `q4-2018` | 2018-09-21 → 2018-12-24 | 65 | −20.05% | sharp quarter-long selloff | falling |
| `covid` | 2020-02-19 → 2020-06-30 | 93 | −8.71% | crash + snapback | falling |
| `bear-2022` | 2022-01-03 → 2022-10-12 | 196 | −25.14% | grinding rate-driven decline | falling |
| `chop-2015` | 2015-04-07 → 2016-04-15 | 260 | −0.04% | sideways | flat |
| `chop-2011` | 2011-05-26 → 2012-06-06 | 260 | −0.05% | sideways, higher vol | flat |
| `bull-2024` | 2024-08-21 → 2025-08-20 | 250 | +14.00% | ordinary good year | rising |
| `recent` | 2025-08-21 → 2026-08-18 | 249 | +20.62% | most recent 12 months | rising |
| `gfc` | 2007-10-09 → 2009-03-09 | 356 | −56.23% | deepest drawdown available | falling |

**Directional balance of this matrix: 4 falling / 2 flat / 2 rising**, mean benchmark return **−9.45%**
(figure and the "six of eight falling" characterisation both stated in
`data/rounds/r4-2026-08/REPORT.md` §1, computed from round 2's own matrix — the "6 of 8" count there
groups the two flat windows with the falling ones by sign of return, since chop-2015/2011 both close
fractionally negative; read narrowly by regime label the split is 4 falling / 2 flat / 2 rising).
Gate: `MIN_ELIGIBLE_MAIN_WINDOWS = 5` of 8 (`jobs.py` line 340; `WINDOWS.md`).

**Not represented in this matrix:** any regime after 2026-08-18; any window between `gfc` and
`q4-2018` (2009–2018, a near-decade); a genuine grinding *rally* under 2024–2026's volatility profile
distinct from `bull-2024`/`recent`, which are drawn from one continuous late bull run and are highly
likely to be correlated draws of the same regime rather than two independent rising markets.

### 1b. The six round-4 windows (`R4_MAIN_WINDOWS`) — deliberately disjoint from 1a

Source: `jobs.py` lines 141–151, `tools/windows.py` lines 104–116. Built specifically so no window
overlaps rounds 1–3's matrix — `PROTOCOL.md` §6(a) requires new windows for a second confirming round
to count as independent evidence, not the same measurement counted twice.

| tag | window | regime |
|---|---|---|
| `oil-2014` | 2014-06-20 → 2015-02-11 | oil collapse and dollar surge |
| `volmageddon-2018` | 2018-01-26 → 2018-04-02 | volatility shock |
| `taper-2013` | 2013-05-22 → 2013-09-05 | rate shock, taper tantrum |
| `recovery-2009` | 2009-03-10 → 2010-04-23 | post-crisis recovery rally |
| `inflation-2021` | 2021-01-04 → 2021-12-31 | inflation onset and rotation |
| `banks-2023` | 2023-03-01 → 2023-05-31 | regional banking crisis |

**Directional balance: 2 of 6 falling, mean benchmark +17.13%** (`data/rounds/r4-2026-08/REPORT.md` §1,
via `PROGRAMME-REPORT.md` §5). Gate: `MIN_ELIGIBLE_R4_WINDOWS = 4` of 6 (`jobs.py` line 361).

**This is the direct source of the "identical cards reversed" finding the task names.** Round 3's
8-window matrix (6-of-8/4-of-8-by-regime falling, mean −9.45%) and round 4's 6-window matrix (2-of-6
falling, mean +17.13%) scored the *same frozen cards* and reversed the ranking: round 3's
combined-book result (`B-momentum` + `C-trend` + `c14-riskmanaged-wide`, median +15.4%) did not
replicate on round 4's windows, was beaten by `B-momentum` alone on every axis, and the mechanism was
a correlation between two frozen cards flipping sign — `C-trend`/`c14-riskmanaged-wide` measured
ρ = +0.04 on round 3's matrix and ρ = −0.554 on round 4's (`data/rounds/r4-2026-08/REPORT.md` §4,
quoted in `PROGRAMME-REPORT.md` §4). Round 4's own heading: **"Round 3's conclusions were properties
of round 3's windows."**

### 1c. Round 5's 27-window horizon ladder (`R5_LADDER_WINDOWS` + `R5_BEAR_WINDOWS`)

Source: `jobs.py` lines 152–309, `tools/windows.py` lines 124–310, transcribed verbatim from
`data/rounds/r5-2026-08/windows.json`. This is not a set of named regimes at all — it is the same
handful of anchor dates (2013-09, 2014-02, 2016-02, 2018-02/08, 2020-02/08, 2021-02, 2022-02/08,
2023-02, 2025-02/08) sliced to five run lengths (6m ×6, 1y ×6, 3y ×4, 5y ×3, 10y ×2), so a card's edge
can be read as a function of hold length rather than of which crisis it landed in, plus a 6-window
"bear" supplement selected specifically for a falling benchmark and reported separately, never pooled
into the ladder's medians.

**Directional bias, stated in the code's own comment (`jobs.py`/`tools/windows.py`, the block above
`R5_BEAR_WINDOWS`): the benchmark rises in 19 of the 21 ladder windows, and only `h1y-5` (2022) is
negative among the eighteen 6m/1y ladder windows.** No decade in the available data has a falling
benchmark, so the two `h10y` windows are both rising by construction — the ladder cannot represent a
long-horizon bear market at all, and the bear-arm supplement exists precisely because the ladder's own
anchor dates could not surface one. Gate: `MIN_ELIGIBLE_R5_PER_HORIZON = 2`, applied *per horizon*
rather than once over the flat 27-window matrix (`jobs.py` line 309) — a card can clear every long-rung
slot and still be ungated at the short end, and the two figures are not comparable.

**What round 5 found with this matrix, and why it is the sharpest generalisation warning in the whole
programme:** the best annualised figure in the field fell from **+31.6% at one year to +7.6% at ten
years** — same cards, same engine, same metric, same calendar (`data/rounds/r5-2026-08/REPORT.md` §2.1,
verified in `PROGRAMME-REPORT.md` §6). Swapping the benchmark from SPY to QQQ roughly halves every
AI/semiconductor book's decade edge (`B-momentum` +7.59%→+3.9%, `A-rotation` +5.28%→+0.6%). And every
top card's universe was chosen by an analyst in 2026 and then run from 2013 — a decade over which
knowing which semiconductor names to hold was worth the most, and the survivorship gate (§1d below)
does not catch a thesis-picked basket the way it catches an index-derived one. Every long-rung figure
in round 5 is stated in its own report as an **upper bound**, not a result.

### 1d. Round 11's six live sub-periods (`R11_LIVE_WINDOWS`) — not regime windows at all

Source: `jobs.py` lines 187–201, 248–265; `tools/windows.py` lines 172–254. One continuous
out-of-sample period (2026-02-17 → 2026-08-18, the only stretch no card could have been designed
against) cut into six contiguous sub-periods on SPY's own session calendar. **Not comparable to any
other matrix in this inventory** — it samples one regime six times, not six regimes once.

**This matrix's measurement method was itself a defect** — see D5 below. The first implementation ran
each sub-period as an independent tournament, which reset every card to a flat book at each boundary;
the fix runs cumulative tournaments from the single fixed start and differences the results so
position continuity survives.

### 1e. The special-case window and the provenance gate

`13f-legal` (2025-11-17 → 2026-08-18, +14.60%) is not part of any ranked matrix and never counts
toward any gate — it exists only for a 13F-derived universe, which by construction cannot reach any
other window (`WINDOWS.md`). Round 1 ranked a 13F-derived card on four windows predating its own
filings before this was caught by a human reader; the fix is `StrategyCard.universe_knowable_from`
plus `PROVENANCE_CONSTRAINED_WINDOWS` in code (`jobs.py` line 367; `WINDOWS.md` "Provenance").

**Index-membership survivorship is the harder, still-live version of the same problem.** The store's
universe now includes the full current S&P 500/Nasdaq-100 constituent list, pulled from N-PORT
filings. Today's index contains no Lehman Brothers, Bear Stearns, Washington Mutual, Countrywide or
GM — every one removed *because it collapsed*. A card whose universe is selected from that list and
run over `gfc` is testing a strategy against the subset of the crisis's participants that survived it.
`WINDOWS.md` states the gate is scoped to *selection method*, not to the store: a card that declares
`universe_knowable_from` an index file is gated; a card that hand-picks names on its own thesis is
not, even if those names happen to also be in the index. **This means an analyst's thesis-picked
GFC-era universe is never checked for survivorship by any code path** — round 3's `c15-volatility-wide`
is the concrete instance: its author pre-registered `gfc` as the card's predicted *worst* window on
sound 2008-bank-balance-sheet reasoning, and it came back as the card's *best* window
(+69.6% raw / +18.4% adjusted), because a thesis-picked universe can silently omit the failures a
mechanical index draw would have kept. `PROGRAMME-REPORT.md` §4 records this as "the project's
clearest demonstration of survivorship, precisely because the prediction preceded the wrong result."

### 1f. What the matrix as a whole cannot see

- No window before 2007 (the store's practical depth) or after 2026-08-25 (evolving; see D6).
- No long-horizon bear market — the 27-window ladder's decade slots are both rising by construction.
- No regime combining a falling benchmark with the specific volatility/liquidity texture of 2026's
  AI/semiconductor-heavy universe, because that universe did not exist through any historical falling
  window on its own merits (only via survivorship-biased index/13F draws).
- Thesis-picked (as opposed to mechanically index-derived) universes are never survivorship-checked by
  code, only by an analyst's own disclosed reasoning — a control that depends on the analyst noticing.

---

## 2. The protocol's rules, and what each one forbids

Source: `strategy-program/PROTOCOL.md` §3 (the "anti-overfitting constitution"), §5 (windows), §6
(promotion), §7 (variants). Framed as prohibitions, per the task's instruction, because each one is
the reason a specific class of idea has never been tested here.

1. **One submission per analyst per round, no revision after seeing any result.** Forbids climbing a
   leaderboard mid-round. There is no such thing in this programme as "try again with the same idea
   after seeing how it did" within a round.
2. **Design cutoff enforced by type** (`StrategyCard` rejects a `designed_through` past the round's
   cutoff). Forbids designing with knowledge of data after the cutoff — including, implicitly, the
   analyst's own memory of how a similar idea performed in a prior round, since §6 (below) forbids
   reading prior results at all.
3. **Parameter budget: ten free numbers per card**, counted across entry, exit, both brackets, hold
   cap, slot count and position size. Forbids a card with more discretion than that from being
   submitted at all — an idea that genuinely needs an eleventh free number has no path into this
   programme as written.
4. **No grid search.** Forbids searching a parameter space for a setting that works; sensitivity
   testing is permitted only to *demonstrate* insensitivity, and a rule that works at one setting and
   breaks one notch away must be reported as fitted, not submitted as robust.
5. **Pre-registered failure regime.** Forbids submitting a card without naming, in advance, the regime
   it is expected to hate — closing off the move of explaining a bad result after the fact as if it
   had been anticipated.
6. **Information quarantine.** Forbids an analyst from reading any prior round's results. Whatever is
   methodologically useful from a prior round is hand-extracted into the next round's brief instead —
   which means an analyst can never directly learn "card X failed for reason Y," only whatever the
   orchestrator chose to abstract into the brief.
7. **The regime gate** (fewer than 3 of 5 main windows in round 1's history — see §1's per-round gates
   above for exact thresholds since). Forbids ranking a card whose universe cannot reach enough
   regimes; its numbers are published but excluded from the ranking, never sorted to the bottom.
8. **Correction across everything tried**, denominator of every card run in the comparison. Forbids
   correcting against a subgroup — explicitly recorded as a failure this project made once already.

**§6, promotion — two additional conditions, added after round 2:**
- **(a) The second qualifying round must bring new windows**, not a re-scored superset. Forbids
  counting a re-run of an already-measured window as a second, independent confirmation — the engine
  is deterministic, so a re-run on the same window reproduces the identical number rather than sampling
  anything. Verified on twenty of twenty checked pairs in round 2 (`A-rotation` returned +95.2786% in
  `recent` in both rounds, to four decimal places, on the same 47 trades).
- **(b) Every promotion/demotion margin must clear the noise floor** (§3 below). Forbids promoting on a
  margin the programme's own noise-floor measurement calls meaningless — round 2 found the rule as
  literally written would have replaced `B-momentum` with `B2-hold-90` on margins of 5.62 and 4.15
  points, both inside the floor.

**§7, variants.** Forbids a variant from changing more than one decision against its base — a variant
changing three things at once cannot attribute a result to a cause, so it is not run as a variant at
all under this protocol.

**One directed exception is recorded, not hidden:** on 2026-08-21 the programme's owner set
`B-momentum` and `C-trend` as the two primaries and closed the research phase. `C-trend` was **not**
promoted by the rule above — one round's evidence where two are required, on a decision overriding the
scorecard rather than satisfying it. `PROTOCOL.md` §6 records this explicitly so a later reader cannot
mistake `C-trend`'s presence in `base/` for evidence it does not have.

---

## 3. The noise floor — the 53.9-point ordering spread

**Source and figure, precisely attributed.** `backend/app/paper/library/README.md` (§"The two base
strategies"), reporting a sensitivity study over `docs/tournament/results/a07-order/`: one identical
card (`a07-rotation`, later `A-rotation`) re-run under **twelve `universe` orderings** — the runner's
tiebreak when more symbols qualify for a slot than there are slots, absent a `rank_by` field — over the
full three-year window:

| ordering | 3-year return |
|---|---|
| best of 10 random orderings | +161.83% |
| relative-strength order (later adopted as `A-rotation`) | +158.74% |
| median random ordering | +142.21% |
| alphabetical, as submitted | +145.08% |
| worst of 10 random orderings | +107.98% |

**Spread: 53.9 percentage points of three-year return. σ = 21.2 points**, from ordering alone, on a
card whose *rules* never changed. Relative-strength ordering itself ranked **9th of 10** against random
draws — better than the alphabet, but inside the noise, not beyond it (confirmed independently at
`PROTOCOL.md` §7 and `CONSTRAINTS.md` "Structural limits of the engine").

**What this disqualifies.** Every card frozen before `StrategyCard.rank_by` existed — which is every
result this programme published before the field was added — was tiebroken by raw universe-array
order and is fully exposed to this spread. `PROTOCOL.md` §7 states the consequence directly: "Any
variant comparison whose margin is inside that band has demonstrated nothing." Concretely:
- `A-rotation`'s incumbent-era three-year figures (the numbers that made it base-tier in the prior
  tournament) sit inside this band and cannot be distinguished from an artifact of symbol-list order
  (`README.md` "The two base strategies").
- Round 1's eight variant experiments found **none** separated from its own base by a margin clearing
  the floor; the pure ordering-artifact control (`A1-alpha-order` vs `A-rotation`, differing only in
  array order) itself produced a +6.47 point gap — larger than five of the seven substantive variant
  comparisons run that round (`PROGRAMME-REPORT.md` §2).
- Round 2's mechanical promotion-rule check (`B-momentum` vs `B2-hold-90`, margins of 5.62 and 4.15
  points) is squarely inside the floor — this is the concrete case that motivated `PROTOCOL.md` §6
  condition (b).
- Setting `rank_by` (CONSTRAINTS.md, "Structural limits of the engine") replaces the arbitrary
  tiebreak with a stated one; it does **not** make the spread disappear for cards still using it, and
  the one measurement of relative-strength ordering against random orderings put it 9th of 10 — inside
  the noise, not a demonstrated improvement.

**Rule of thumb this floor licenses, stated in `README.md`:** "Any comparison between two cards decided
by less than roughly 20 points of three-year return may be an artifact of the order symbols were
listed in." That is the practical filter for reading every backtest margin in this programme's
history against.

---

## 4. Defects D1–D6

Source: `strategy-program/DEFECTS.md`. Each entry: what it was, which numbers it touched, whether
those numbers were re-measured or only annotated, and current status.

### D1 — `total_return` rebased to first session's close, not starting equity
**Numbers touched:** `total_return` and `cagr` only (not `max_drawdown`, `volatility`, per-bar
returns — those cancel the constant harmlessly). 14 card-window pairs in round 1 diverged from the
true `ending_equity/starting_equity − 1` by more than 0.05pp, two of them **changing sign**
(A1-alpha-order in covid: reported −0.972%, true +1.099%; A-rotation in covid: reported −0.652%, true
+0.465%).
**Status: FIXED** in the engine between rounds 1 and 2. **Re-measured, not merely annotated** — the
2026-08-21 restatement (see D4 below) re-ran all 330 committed run files across r1–r3 through the
corrected engine and overwrote them, so round 1's *published, currently-committed* figures reflect the
fix. The workaround in `score.py` (deriving return from `ending_equity`/`starting_equity` directly) is
retained even after the fix so round 1 and round 2 scoring stay comparable under the same formula.
**Explicitly not remediated:** "This affects the previous tournament's published numbers too" — the
tournament that *preceded* this programme (26 strategies, ρ = 0.162 finding) used the same buggy
formula and its published figures were never restated. That is a contaminated figure set outside this
programme's own commits, named in `DEFECTS.md` itself and never revisited.

### D2 — `exposure` measures session presence, not capital at risk
**Numbers touched:** every `adjusted_excess` figure computed before the fix, anywhere raw `exposure`
was multiplied into a benchmark term. Reproduction: `c04-riskmanaged` in `gfc` reported
`exposure = 0.9719` against a capital-weighted true figure of 43.83%; using the raw figure in
`total_return − exposure × benchmark_return` against a −56.23% benchmark produced +55.45% adjusted
excess where the corrected figure is +25.45%. `c03-breakout` in `gfc` **changed sign**, +13.43% →
−1.71%.
**Status: FIXED** between rounds 1 and 2 by adding `AgentResult.capital_exposure` alongside the
existing (unrenamed) `exposure` field. `score.py`'s independent trade-log reconstruction is retained as
a cross-check. Re-measured for every round scored since (round 2's engine confirmation:
`max |total_return − ending/starting| = 0.000000pp` across all 170 round-2 runs, per
`PROGRAMME-REPORT.md` §3).

### D3 — a concurrent DuckDB reader is reported as an ordinary card failure
**Numbers touched:** none directly — this is an availability defect (silent shortfall in a round's run
files), not a numeric-correctness one. **Cost:** an entire first attempt at round 2 (135 card-runs,
zero results, from two `run_round.sh` processes fighting over the store's write lock after one was
"killed" by `taskkill /IM python.exe`, which killed only the python process, not the driving shell
loop).
**Status: FIXED at source**, not merely mitigated by procedure. All three pure-read call sites in
`app.market.store` (`read_frame`, `_read_many`, `sync_bars`'s pre-fetch) now use an in-memory DuckDB
connection that never touches the physical file, so concurrent reads cannot collide with the runner's
write lock at all. Verified: three concurrent processes reading through `read_frame` succeed; two cards
re-run through the tournament produced bit-identical results to the committed round-2 output. Full test
suite: 2197 passed, 1 skipped, with two regression tests confirmed to fail against the unfixed code.
Operational rules (never launch detached, never kill by `python.exe`, reconcile run-file counts against
`FAILED` lines) remain in force as belt-and-braces, but the underlying race is closed.

### D4 — indicator seeding depends on an unchosen 400-day lookback constant
**Numbers touched:** every recursive-indicator (`ema`, Wilder `rsi`) signal in every backtest ever run
in this programme, in principle — in practice, exactly one signal flipped across the whole comparison:
`C-trend`'s TSM entry on 2020-05-14 (an `ema(20)`/`ema(50)` crossing decided by a ~1.8e-5 relative
seeding error). **This moved 3 of 330 committed run files** across r1–r3 (all the same card/window,
`C-trend` in `covid`, present in all three rounds) by 0.065 percentage points of starting equity;
`C-trend` regains a trade (6 trades → 7), covid excess moves +24.5% → +24.6%. **No median, ranking,
Pareto frontier, promotion or conclusion in any round report changed.**
**Status: FIXED**, `lookback_days=None` (full stored history) now used everywhere a recursive indicator
is evaluated (`AsOfMarket.history`, `runner._rule_fires`, the paper desk's signal evaluation), and
**every round was restated** — all 330 run files re-run through the corrected engine and overwritten,
driven from each file's own embedded `StrategyCard`, so the restated field is provably the field
originally run. This is the clearest instance in the programme of "re-measured, not merely annotated":
the reproduction harness that found the defect is also what makes the restatement independently
verifiable rather than asserted.
**Caveat DEFECTS.md itself states:** the defect's *size* was always ~1e-5 and its *effect* was always
going to be all-or-nothing at whichever knife-edge crossings happened to fall inside the error band —
3 moved here; a different window or a card with more knife-edge crossings would move more, and nothing
in the old code bounded how much.

### D5 — cutting a live out-of-sample period into independent sub-window runs resets the book at every boundary
**Not an engine defect — a defect in a measurement this programme itself designed** (round 11's live
matrix, §1d above). **Numbers touched:** the entire first live-matrix attempt. `B-momentum` reported
zero trades and 0.0% exposure in two of six sub-windows while, in reality, fully invested throughout —
because its confirmed-acceleration entry rule cannot rebuild its lookback in 21 sessions from a flat
restart. The bias was directional, not random: high-turnover cards barely noticed the reset;
hold-and-ride cards were destroyed by it, and the two cards that cleared the round's live-consistency
gate on the invalid matrix were the two highest-turnover cards in the field.
**Status: instrument replaced, not fixed in place.** The invalid output is preserved as evidence at
`data/rounds/r11-2026-08/results-independent-INVALID/` rather than deleted or silently overwritten. The
replacement runs six **cumulative** tournaments from one fixed entry point and recovers each
sub-period's return/benchmark/exposure by exact differencing — preserving position continuity by
construction. No threshold, gate, window boundary or ranking criterion was changed after seeing the
broken result; only the run mechanics changed, and the correction happened to run *against* the result
(seating `A-rotation` alone) that would have been convenient.

### D6 — a round asserts the bar store is unchanged, against a stale prose figure
**Not an engine defect — a defect in how the programme handles its own inputs.** Round 11's §0 asserted
"SPY holds 8,445 rows ending 2026-08-18 — verified, not assumed." By the end of the same day the store
held 8,448 rows ending 2026-08-21, because `data/store/` is gitignored mutable state and any ordinary
use of the running application (a browser session checking dashboard pages) advances it via
`ensure_series`. Round 12 caught the discrepancy and disclosed it rather than absorbing it.
**Numbers touched: none.** Every affected round's computations were explicitly bounded to windows
closing on or before the store-state date in question, so appended bars could not reach any scored
figure. **What broke was a sentence, not a number** — "the store is unchanged" is a claim with an
unstated expiry date, and it kept being asserted after it stopped being true.
**Status: FIXED 2026-08-26.** `strategy-program/tools/storestate.py` now captures row count and last
bar date per symbol as data, and `score.py --pin-store` / `--compare-store` let a later round compare
against a *recorded* pin rather than a number transcribed from another document's prose. Pinning is
opt-in (does not add keys to already-published round JSON). Drift is reported, never judged — whether
drift can reach a round's own bounded windows is left to the round document. **A missing pin reports as
missing**, not as "unchanged": every round scored before 2026-08-26 has none, and the tool says so.
As of the fix landing, the drift was still live: the pin taken 2026-08-26 recorded SPY at 8,450 rows
ending 2026-08-25 — a third different reading, against round 11's 8,445/2026-08-18 and round 12's
8,448/2026-08-21, one unchanged sentence sitting above all three in committed documents. **Whether that
sentence in round 11's and round 12's own committed documents was ever corrected in place is not
established from DEFECTS.md** — the entry describes the tooling fix, not a retraction of the specific
prose.

### Summary table

| defect | numbers touched | re-measured or annotated | status |
|---|---|---|---|
| D1 | `total_return`, `cagr`; sign flip on 2 pairs | re-measured (330 files restated) | closed at source |
| D2 | `adjusted_excess` wherever raw `exposure` fed it; sign flip on 1 case shown | re-measured (capital_exposure added, cross-checked) | closed at source |
| D3 | none (availability, not correctness) | n/a — verified bit-identical after fix | closed at source |
| D4 | 3 of 330 run files, 0.065pp; no conclusion changed | re-measured (full restatement, reproducible) | closed at source |
| D5 | the entire first round-11 live matrix | instrument replaced; invalid output kept as evidence, not used | closed by replacement |
| D6 | none (a false prose claim, not a number) | not re-measured (nothing to remeasure); tooling now prevents recurrence | closed 2026-08-26 |

**Which published figures remain contaminated: the prior tournament's, not this programme's.** Every
defect that touched a number inside this programme's own `data/rounds/` tree was re-measured and the
committed files overwritten (D1, D2, D4) or the invalid output was quarantined and replaced (D5). The
one explicitly unremediated contamination named in `DEFECTS.md` itself is the **tournament that
preceded this programme** (the 26-strategy, 127-session, ρ = 0.162 study `PROTOCOL.md` §1 cites as the
programme's whole reason for existing) — its published `total_return` figures share D1's bug and were
never restated.

---

## 5. Metric definitions that constrain comparison

Source: `docs/DEFINITIONS.md`, `PROTOCOL.md` §4, `strategy-program/EVOLUTION-LOOP.md`,
`strategy-program/ROUND-15-PLAN.md`, confirmed as landed in code at `backend/app/tournament/results.py`
(`ExposureBasis`, `ExposureBasisError`, `ScoredRun.adjusted_excess`).

**`capital_exposure` means two structurally different things depending on card shape, and the
apparatus now refuses to conflate them.**
- For a `StrategyCard` (a rules card — `entry`/`exit` logic, discrete trades): `entry_notional /
  starting_equity`, **fixed at trade entry**. This is what `PROTOCOL.md` §4's `adjusted_excess` formula
  is defined against.
- For an `AllocationCard`/`LadderCard` (a continuously-rebalanced sleeve book): `invested_value /
  current_equity`, **averaged over sessions** — which for a continuously-invested sleeve is always near
  1.0. Feeding this into the rules-card `adjusted_excess` formula "does not produce a wrong-ish number,
  it produces a different metric wearing the same name" (`ROUND-15-PLAN.md` §2b).

**The refusal, as implemented:** `results.py`'s `ScoredRun` carries an explicit `exposure_basis:
"entry-notional" | "invested-value"` read off the run's own card shape, never assumed from context. A
run whose basis is `invested-value` is **not assigned an `adjusted_excess` at all** — calling
`.adjusted_excess()` on it raises `ExposureBasisError`; it is scored on plain `excess` and reported as
such. Silence here — quietly computing a number that looks like the others — is called out in
`ROUND-15-PLAN.md` as "the single most damaging thing this round could ship."

**The same refusal exists one layer up, in the evolution loop's generation scoring**
(`EVOLUTION-LOOP.md`): `build_leaderboard` refuses to rank a field that mixes the two exposure bases in
one generation — it ranks the larger group and lists the rest under `unscored_reason` rather than print
two orderings under one column header. Measured cost of this refusal in one generation: 4 candidates
proposed, 12 runs completed, 0 failures, **2 ranked** — the other half of the field is run at full cost
and then structurally excluded from the leaderboard, by design.

**What this means for reading any published comparison:** a card's `adjusted_excess` figure is only
ever comparable to another card's if both are rules cards (entry-notional basis). An allocation or
ladder book's `excess` figure is not on the same ranking axis as a rules card's `adjusted_excess`, and
the apparatus enforces this by refusing to compute the mixed number rather than by a reader's
discipline.

**Two further constraints on comparison, from `PROTOCOL.md` §4 directly, worth restating as
prohibitions:** "Never rank on a single window. Never compare a return from one window against another
window's benchmark." Both are stated as hard rules, not guidance — every window carries its own
benchmark, computed by the runner over that window's own sessions, and a comparison across windows or
against the wrong window's benchmark is treated as a category error rather than a weaker form of
evidence.

**One benchmark-measurement ambiguity, disclosed but not treated as a defect:** `benchmark_return` as
measured by the engine (over the sessions a card actually traded) and a calendar-date recomputation of
the same nominal window can differ by up to 0.85 points across 21 windows (round 5) and up to 0.124
annualised points for the identical out-of-sample window across round 7's and round 8's own documents
(SPY +12.84% vs +12.39%) — "one benchmark measured two defensible ways," per `PROGRAMME-REPORT.md` §9.
This is not logged in `DEFECTS.md` and is explained rather than corrected; any cross-round benchmark
comparison should state which measurement it used.

---

## Summary

**Window matrix and directional balance.** The instrument is not one matrix but at least four,
layered by round and only partially documented in prose (`WINDOWS.md` covers only the 8-window
round-2/3 set; the 6-window round-4 set, the 27-window round-5 horizon ladder, and the 6-window
round-11 live-period slices exist only in code/`tools/windows.py`, confirmed identical between the two).
Round-2/3 main matrix: 4 falling / 2 flat / 2 rising of 8, mean SPY −9.45%. Round-4 matrix: 2 of 6
falling, mean SPY +17.13% — built deliberately disjoint from round-2/3 so a second promotion round
counts as new evidence. Round-5 ladder: 19 of 21 windows rising, no decade-length window ever falling.
Round-11 live matrix: one regime cut into six pieces, not a regime sample at all. The reversal the task
names (6-of-8 falling vs 2-of-6 rising producing opposite verdicts on identical cards) is the
round-2/3-vs-round-4 pair, and the documented mechanism is a between-card correlation that flipped sign
(ρ = +0.04 → −0.554) between the two matrices.

**Noise floor.** 53.9 percentage points of three-year return, σ = 21.2 points, from twelve
universe-array orderings of one identical, rule-unchanged card (`backend/app/paper/library/README.md`,
via `docs/tournament/results/a07-order/`). This disqualifies as evidence: every variant comparison
published before `rank_by` existed, `A-rotation`'s own incumbent-era headline figures, and the
mechanical promotion-rule trigger round 2 found (5.62/4.15-point margins) — the specific case that
forced `PROTOCOL.md` §6's noise-floor condition into the promotion rule.

**Defects D1–D6.** D1 (return rebasing), D2 (exposure mismeasurement), D3 (false concurrent-read
failures) and D4 (arbitrary indicator-seeding constant) are all closed at the engine source, and every
number they touched inside this programme's committed round data was re-measured (D1/D2/D4 via a
full 330-file restatement) rather than merely annotated. D5 (independent live sub-windows resetting the
book) was closed by replacing the measurement instrument, with the invalid output kept on disk as
evidence rather than deleted. D6 (a stale "store unchanged" claim) touched no published number but was
a false claim left standing in committed round documents; it is now closed by tooling
(`storestate.py`) that makes the claim checkable, though whether the specific false sentences in round
11/12's own documents were retracted is not established from `DEFECTS.md` alone.

**Contaminated figures.** None remain contaminated inside this programme's own published record — every
numeric defect was either re-measured and overwritten or quarantined and replaced. The one
unremediated contamination on record is external to this programme: the prior tournament's published
`total_return` figures (the ρ = 0.162 study this whole programme was built to correct) share D1's
rebasing bug and were never restated, per `DEFECTS.md`'s own statement.

**Refused comparisons.** The apparatus refuses to compute `adjusted_excess` for any allocation/ladder
(invested-value-basis) card — it raises rather than silently produce a number "wearing the same name"
as a rules card's entry-notional figure — and the evolution loop's leaderboard refuses to rank a
generation that mixes the two bases at all, scoring only the larger group. Both refusals are
implemented in code (`backend/app/tournament/results.py`), not left to a reader's discipline. Separately,
`PROTOCOL.md` §4 hard-forbids ranking on a single window or comparing a return to another window's
benchmark.
