# Round 9 — the stability rule, pre-registered and applied

**Not investment advice.** Simulated books on a paper account, selected to be informative to watch.
I am not a licensed financial adviser and none of this is a recommendation about real capital.

---

## The rule, as executed

Round 8 ranked the momentum seat on a single 127-session out-of-sample window and selected
`B3-concentrated`. The desk owner overrode it and seated `B-momentum` instead, weighting rank
stability across the round-2, round-4 and round-5-ladder matrices and the ten-year rung
(`data/rounds/r8-2026-08/SELECTION.md` section 6). That section closed with an instruction: *"if
long-horizon stability is what the desk should be selected on, that belongs in the rule ... pre-
registered before the next round's numbers exist."*

**This round is that rule**, applied exactly as follows, before any of round 9's numbers were looked
at:

- **Gate A (unchanged).** Positive median annualized adjusted excess at both the 5y and 10y rungs of
  round 5's ladder, against both SPY and QQQ. Recomputed fresh below, not copied from round 8.
- **Gate L (tightened).** A card must have traded in the out-of-sample window 2026-02-17 to
  2026-08-18 **and** either hold a position now or have traded within the last 60 sessions. Being
  100% cash having last traded months ago now fails, closing the hole round 6 section 6.1 and round 8
  both flagged: `c07-chop` cleared round 8's liveness gate on three out-of-sample trades and sits at
  100% cash on the live desk today, its last trade closed 2026-04-07 — 92 sessions before this round's
  as-of date, well past the 60-session line.
- **Gate S (new — the stability gate).** Worst rank across the round-2, round-4 and round-5-ladder
  matrices must be ≤ 5. This is the rule form of the override: a card that has never finished worse
  than fifth on any matrix, rather than the card that won the most recent six months.
- **Ranking (changed).** Among cards clearing all three gates, rank by median annualized adjusted
  excess over round 5's 5y and 10y rungs, against **QQQ**. Tie-break: out-of-sample adjusted excess
  vs QQQ.
- **Distinctness (unchanged).** At most one card per `discipline`, and at most one per base family
  (`B-momentum`/`B2-hold-90`/`B3-concentrated`/`B4-tight-stop` count as one).
- **Take the top four. No book veto.**

`ladder-qld-schd` is **seated outside this competition and is not ranked.** It is a different card
type (`backend/app/tournament/ladder.py`, a drawdown-triggered rotation with no per-symbol entry/exit
rule), it cannot run round 5's ladder windows, and it was selected by direct analysis
(`strategy-program/DRAWDOWN-LADDER.md`), not by any of the gates above. It stays on the desk in
addition to whatever the competition produces.

---

## The result

**Only one card clears all three gates in a way that is distinct from another survivor.** Three cards
clear Gates A, L and S — `B-momentum`, `B4-tight-stop`, `B3-concentrated` — and all three are the same
base family. Distinctness allows one seat per family, so the competition seats exactly one ranked
card. No other discipline or family has a single survivor of all three gates. **This round's roster is
two cards, not five:**

| seat | card | why |
|---|---|---|
| momentum (ranked) | **`B-momentum`** | the only card to clear Gates A, L and S **and** win the ranking among the three that did (median ann. adj. excess vs QQQ, 5y+10y rungs: **+7.68%**, against `B4-tight-stop`'s +4.96% and `B3-concentrated`'s +2.72%) |
| unranked, by design | **`ladder-qld-schd`** | seated outside the competition per `strategy-program/DRAWDOWN-LADDER.md`; not gated or ranked here |

**Does the momentum seat now fall out of the rule, rather than a person's judgement? Yes.**
`B-momentum` wins on both the stability gate (worst rank 3, against `B3-concentrated`'s 5) and the
long-rung QQQ ranking the brief asked this round to use instead of the six-month window. No override
is recorded this round because none was needed — the rule and the round-8 owner's judgement now agree,
which is exactly what pre-registering the stability gate was for.

**What the rule does not do is deliver four seats.** `A-rotation`, `B2-hold-90`, `C-trend` and
`H-trend-diversified` each clear Gates A and L; every one of them fails Gate S. Section 3 below shows
why, card by card. This is reported as found — **no gate was loosened and no seat was filled with a
lower-ranked card to reach four** — see "What this is not evidence of."

---

## 1. Gate A — recomputed from round 5's ladder

Median annualized adjusted excess at the 5-year rungs (`h5y-1/2/3`) and 10-year rungs (`h10y-1/2`).
**Benchmark anchor: SPY is the engine's own `benchmark_return`** stored on each `AgentResult` (measured
over the sessions that window's run actually traded); **QQQ is recomputed from the bar store's own
history, close-to-close over each window's calendar start/end dates** (`data/rounds/r5-2026-08/windows.json`).
Loaded from `data/rounds/r5-2026-08/results` (run tag `r1`) via `strategy-program/tools/score.py`,
recomputed for this round, not copied from round 8's table.

| card | 5y SPY | 5y QQQ | 10y SPY | 10y QQQ | verdict |
|---|---|---|---|---|---|
| `B4-tight-stop` | +15.12% | +7.79% | +7.14% | +3.51% | pass |
| `B-momentum` | +14.87% | +9.29% | +7.59% | +3.92% | pass |
| `B2-hold-90` | +13.05% | +8.39% | +7.56% | +4.60% | pass |
| `A-rotation` | +10.46% | +3.39% | +5.28% | +0.63% | pass |
| `B3-concentrated` | +8.33% | +7.33% | +5.78% | +1.90% | pass |
| `C-trend` | +7.35% | +2.53% | +4.45% | +1.28% | pass |
| `H-trend-diversified` | +4.82% | +1.89% | +3.35% | +1.32% | pass |
| `c07-chop` | +3.28% | +2.65% | +0.85% | +0.27% | pass |
| `c19-volatility` | +2.86% | +1.87% | -1.75% | -2.56% | **fail** |
| `c09-convex` | -0.49% | -1.38% | -0.46% | -0.98% | fail |
| `c18-meanrev` | -1.06% | -2.65% | -0.88% | -1.77% | fail |
| `c21-uncorrelated` | -2.38% | -4.15% | -1.40% | -3.09% | fail |
| `c14-riskmanaged-wide` | -2.83% | -5.35% | -1.79% | -3.25% | fail |
| `c11-breakout` | -3.96% | -7.28% | -2.39% | -4.90% | fail |
| `c20-rotation` | -4.28% | -7.14% | -3.77% | -6.12% | fail |

**Eight survivors — the same eight rounds 6 and 8 found.** Every figure reproduces round 8's published
table exactly (recomputed independently for this round, not read from that document), which is
expected: round 5's results are frozen and this is deterministic arithmetic over them, not a fresh
sample.

**Eliminated by Gate A:** `c09-convex`, `c11-breakout`, `c14-riskmanaged-wide`, `c18-meanrev`,
`c19-volatility`, `c20-rotation`, `c21-uncorrelated`.

## 2. Gate L — the out-of-sample tournament, run fresh, plus the live desk's own state

**Trading-window clause**, unchanged from round 8: fifteen staged cards through
`app.tournament --start 2026-02-17 --end 2026-08-18` against the `pro-investor-01` persona.
**Benchmark anchor: both SPY and QQQ are priced close-to-close over the calendar window from the bar
store** (`app.paper.marketdata._full_frame`), giving **QQQ +19.33%** and **SPY +12.39%** over this
window — not the tournament engine's own `benchmark_return`, which reads SPY at +12.84% measured over
the sessions the run actually traded. Both are defensible; round 8 section 2 already established that
these are separate, real anchors for the same period, not a data disagreement.

This run reproduces round 8's table exactly, confirming it rather than copying it: the 15 result
files in the staging tournament output carry `trade_start=2026-02-17`, `trade_end=2026-08-18`,
`sessions=127`, matching round 8's own run. Frozen cards over an identical window are a deterministic
computation, not a new draw — re-running it changes nothing, and every figure below was checked
against the per-card result files directly rather than against round 8's prose.

**Recency clause (new this round):** current holdings and each card's last trade, from the live paper
desk itself (`app.paperdesk.desk.state`, run once for all fifteen candidates via
`INVDASH_PAPERDESK_AGENT_IDS`) — as of the desk's own `as_of`/`latest_bar` date, **2026-08-18**. A card
passes the recency clause if it holds a position today, or if its most recent closed trade's exit date
is within the last 60 trading sessions of that date (SPY's own calendar puts that cutoff at
**2026-05-22**).

| card | OOS return | adj. vs SPY | adj. vs QQQ | exposure | OOS trades | max DD | holds now | last trade closed | sessions since | Gate L |
|---|---|---|---|---|---|---|---|---|---|---|
| `B3-concentrated` | +51.63% | +44.07% | **+39.83%** | 61.0% | 6 | -28.50% | MRVL, TSM, AMD, MSFT | — (open) | — | pass |
| `A-rotation` | +37.36% | +28.97% | **+24.28%** | 67.7% | 29 | -16.87% | NVDA, AVGO, TSM | — (open) | — | pass |
| `B-momentum` | +31.97% | +24.93% | +20.98% | 56.9% | 11 | -25.23% | MRVL, TSM, AMD, MSFT, AMZN, NVDA | — (open) | — | pass |
| `B4-tight-stop` | +31.97% | +24.93% | +20.98% | 56.9% | 11 | -25.23% | MRVL, TSM, AMD, MSFT, AMZN, AVGO | — (open) | — | pass |
| `B2-hold-90` | +29.89% | +23.08% | +19.27% | 54.9% | 12 | -21.01% | MSFT, AMZN, NVDA, AVGO | — (open) | — | pass |
| `c20-rotation` | +5.30% | +0.48% | -2.22% | 38.9% | 32 | -11.94% | XLV, XLP, DBC | — (open) | — | pass |
| `c18-meanrev` | +2.02% | -0.61% | -2.08% | 21.2% | 56 | -3.84% | CL, MMM | — (open) | — | pass |
| `C-trend` | +1.87% | -3.19% | -6.02% | 40.8% | 10 | -17.39% | NVDA, AVGO, TSM, SOXX | — (open) | — | pass |
| `c11-breakout` | +0.90% | -1.21% | -2.39% | 17.0% | 2 | -1.35% | SPY | — (open) | — | pass |
| `c07-chop` | +0.22% | -0.42% | -0.77% | 5.2% | 3 | -2.04% | *all cash* | 2026-04-07 | **92** | **FAIL — new this round** |
| `c09-convex` | +0.10% | -0.12% | -0.24% | 1.8% | 2 | -0.36% | GLD | — (open) | — | pass |
| `c14-riskmanaged-wide` | 0.00% | 0.00% | 0.00% | 0.0% | **0** | 0.00% | *all cash* | 2026-03-12 | 109 | **FAIL — zero OOS trades** |
| `c19-volatility` | -0.14% | -0.43% | -0.59% | 2.3% | 1 | -1.37% | *all cash* | 2026-07-14 | 25 | pass |
| `H-trend-diversified` | -3.14% | -4.65% | -5.49% | 12.2% | 7 | -5.21% | DBC, NVDA, GDX | — (open) | — | pass |
| `c21-uncorrelated` | -5.28% | -6.71% | -7.51% | 11.5% | 7 | -7.63% | DBC | — (open) | — | pass |

**`c07-chop` is exactly the card the tightened gate was written for.** It traded three times in the
out-of-sample window and cleared round 8's one-trade liveness bar, but its last trade closed
2026-04-07 and it has held 100% cash for 92 sessions since — a fact the trading-window clause alone
could not see. `c14-riskmanaged-wide` fails on the unchanged clause (zero trades in the window) and
already failed Gate A, so nothing changes for it.

**Of the eight Gate-A survivors, Gate L removes exactly one that Gate A did not already remove:
`c07-chop`.** Seven proceed to Gate S: `B-momentum`, `B4-tight-stop`, `B2-hold-90`, `A-rotation`,
`B3-concentrated`, `C-trend`, `H-trend-diversified`.

## 3. Gate S — the stability gate, new this round

Worst 1-indexed rank (descending median adjusted excess, rank 1 best) across three matrices, each
scored via `strategy-program/tools/score.py` restricted to the fifteen-card candidate field (the same
convention rounds 6 and 8 used for this figure, reproduced here rather than re-derived from scratch —
confirmed by matching round 8 section 6's quoted `B-momentum` figure of 3 (3/2/2) exactly):

- **round-2**: median (non-annualized) `adjusted_excess` across `MAIN_WINDOW_TAGS` (8 windows).
- **round-4**: median (non-annualized) `adjusted_excess` across `R4_MAIN_WINDOW_TAGS` (6 windows).
- **round-5-ladder**: median **annualized** `adjusted_excess` across all 21 of `R5_LADDER_TAGS`
  (annualized because the ladder mixes 6-month through 10-year windows, which a raw median cannot
  compare; round-2 and round-4 windows are all comparably-sized regime windows, so no annualization is
  needed there).

| card | r2 rank | r4 rank | r5-ladder rank | worst | Gate S |
|---|---|---|---|---|---|
| `B-momentum` | 3 | 2 | 2 | **3** | pass |
| `B4-tight-stop` | 4 | 3 | 4 | **4** | pass |
| `B3-concentrated` | 2 | 1 | 5 | **5** | pass |
| `B2-hold-90` | 1 | 7 | 3 | **7** | **fail** |
| `C-trend` | 5 | 5 | 6 | **6** | **fail** |
| `H-trend-diversified` | 6 | 8 | 7 | **8** | **fail** |
| `A-rotation` | 10 | *absent* | 1 | **n/a** | **fail** |

**`A-rotation` fails on missing data, not on a bad rank.** It was retired after round 4 for a
structurally negative median adjusted excess and a 43% hit rate across the whole `A`-family
(`strategy-program/ROUND-4-PLAN.md`, "The A family — 5 cards, retired together"), and reinstated only
for round 5 (`strategy-program/ROUND-5-PLAN.md`: "`A-rotation` reinstated as the high-exposure
comparator its control arm earned"). It has no round-4-matrix result at all in
`data/rounds/r4-2026-08/results` — not a poor rank, an absent one — so "never finished worse than
fifth" cannot be said of it on that matrix. Gate S treats an absent matrix the same as this document
treats every other missing number: not invented, not assumed favourable.

**`B2-hold-90`, `C-trend` and `H-trend-diversified` fail on an ordinary rank miss**, each landing one
to three places past the ≤5 line on at least one matrix (`B2-hold-90` at rank 7 on round 4;
`C-trend` at rank 6 on round-5-ladder; `H-trend-diversified` at rank 8 on round 4).

**Gate S survivors: `B-momentum`, `B4-tight-stop`, `B3-concentrated` — all one base family.**

## 4. Ranking and distinctness

Among the three Gate-A/L/S survivors, ranked by median annualized adjusted excess over round 5's 5y
and 10y rungs (`h5y-1/2/3`, `h10y-1/2`) against **QQQ**, recomputed the same way as Gate A's QQQ
column (bar store, close-to-close, each window's own calendar dates):

| card | h5y-1 | h5y-2 | h5y-3 | h10y-1 | h10y-2 | **median** |
|---|---|---|---|---|---|---|
| `B-momentum` | +9.41% | +7.68% | +9.29% | +3.74% | +4.10% | **+7.68%** |
| `B4-tight-stop` | +9.67% | +7.79% | +4.96% | +3.87% | +3.16% | +4.96% |
| `B3-concentrated` | +2.54% | +7.77% | +7.33% | +1.07% | +2.72% | +2.72% |

`B-momentum` leads by more than 2.7 points over the next-best variant — no tie, so the tie-break
(out-of-sample adjusted excess vs QQQ) is not needed.

**Distinctness** (`B-momentum`/`B2-hold-90`/`B3-concentrated`/`B4-tight-stop` count as one base
family) allows exactly one of the three survivors to be seated. `B-momentum` wins the ranking outright,
so distinctness costs nothing here — the same card wins both the gate and the rank.

**No other family or discipline reaches this step at all.** `A-rotation` (pairs-rotation),
`B2-hold-90` (momentum, already excluded once by family), `C-trend` and `H-trend-diversified` (trend)
and `c07-chop` (mean-reversion) were all eliminated at Gates L or S in section 2/3 above. There is
nothing left to rank in any other group, so the walk down the ranking stops after one seat.

**Result: one ranked seat, `B-momentum`.** Seats two through four are not filled, because nothing else
clears all three gates.

---

## 5. What this is not evidence of

- **Not evidence that four independent references were unavailable in principle** — only that four do
  not clear *this* pre-registered combination of gates on *this* evidence. A looser Gate S (say, ≤7),
  or a stability gate computed only within one discipline at a time, would seat more cards; this round
  does not make that substitution, because doing so after seeing that the ≤5 line produces one seat
  would be exactly the "rule quietly restated to produce the wanted answer" round 8 section 6 warned
  against.
- **Not evidence that `A-rotation`, `B2-hold-90`, `C-trend` or `H-trend-diversified` are bad cards.**
  Each clears Gate A and the tightened Gate L; three of the four are presently profitable references on
  the live desk (`A-rotation`, `B2-hold-90`, `C-trend`, `H-trend-diversified` all hold positions as of
  2026-08-18, per section 2's table). They fail a rank-stability bar that specifically penalises a card
  for occasionally finishing outside the top five of fifteen on some matrix — a different, narrower
  question than "does this card make money."
- **Not evidence that the desk is better served by one reference card than by four.** This round
  reports what its pre-registered rule produces; whether a one-card ranked roster (plus
  `ladder-qld-schd`) is the right thing to run forward, or whether Gate S's threshold or scope should
  change for round 10, is a decision for whoever reads this document next — **answered in section 6
  below**, added after this section was written.
- **Still one out-of-sample window for the trading-window clause of Gate L and the tie-break.**
  2026-02-17 to 2026-08-18 remains the only period nobody could have designed a card against, and it is
  127 sessions.
- **The benchmark-anchor effect round 8 documented is unchanged and applies here too.** Every SPY
  figure in this document states which of the two anchors (engine `benchmark_return` vs. bar-store
  calendar slice) produced it; the two differ by up to ~0.12 annualized points on these windows for
  reasons that have nothing to do with any card's quality.

---

## 6. Owner decision, 2026-08-22 — the desk keeps round 8's roster

**Added after this document's sections 1–5 were written and their numbers produced. Nothing above is
edited.** The gates, tables and result stand exactly as recorded; this section records what was done
about them.

The rule filled one of four ranked seats. The desk owner was given two options and chose the second:

1. **Ship the two-card desk** (`B-momentum` + `ladder-qld-schd`) — faithful to the rule as
   pre-registered, and "only one card in the field is stable across three matrices without being a
   duplicate of another survivor" is itself a real finding about how thin the field is.
2. **Keep round 8's roster running and repair Gate S for round 10** — chosen.

**The desk therefore trades `B-momentum`, `A-rotation`, `c07-chop`, `H-trend-diversified` and
`ladder-qld-schd`, unchanged from round 8.** `backend/app/paperdesk/desk.py`'s `AGENT_IDS` records
this at the point of use.

### What this is, and what it is not

**It is not a retroactive loosening of Gate S.** Section 5's first bullet warned specifically against
substituting a looser threshold *after seeing that ≤5 produces one seat*, and that is not what
happened: no threshold in this round moved, `B3-concentrated` was not promoted into the seat the rule
denied it, and round 9's ranked output is still one card. The decision is about which roster the desk
*runs while the next rule is written*, which is a different question from what this round's rule
produced.

**It is not an endorsement of round 8's rule either.** Round 8's own section 6 records the override
that prompted round 9 to exist. Both rules are known-imperfect; the choice between them is between a
four-reference desk selected by a rule with a documented override, and a one-reference desk selected
by a rule with a documented mis-specification. Neither is clean, and the wider one loses less
information while the gate is rewritten.

**`B-momentum`'s seat is the one thing both rules agree on.** It is the card round 8's owner override
seated and the card round 9's rule seated unaided. Every other name on the desk is there by round 8's
rule alone and should be read that way.

### Why Gate S needs repairing rather than re-thresholding

Two defects, both visible in section 3's own table, and neither fixed by moving ≤5 to ≤7:

- **Gate S and distinctness select against each other.** Gate S ranks each card against the entire
  fifteen-card field. Distinctness then allows at most one card per discipline. A global top-five bar
  can only be cleared by the strongest *family* — here all three survivors were momentum variants —
  and distinctness immediately collapses those three to one. The tighter Gate S is, the fewer
  disciplines can reach the ranking at all, which is the opposite of what a roster of independent
  references needs. Raising the threshold to ≤7 would add `B2-hold-90` (also momentum, also collapsed)
  and `C-trend`; it treats the symptom.
- **Gate S measures competitiveness, then the ranking measures it again.** "Never ranked worse than
  fifth of fifteen" is a statement about how *good* a card is, which Gate A already tests (positive
  median annualized adjusted excess at 5y and 10y against both benchmarks) and the ranking step tests
  again directly. What round 8's override was actually reaching for was something different:
  `B-momentum` ranked 3/2/2 across the three matrices and `B3-concentrated` ranked 2/1/5. `B3` has the
  better *level* on two matrices; `B-momentum` has the tighter *spread*. Gate S as written cannot say
  that, because a level bar cannot express dispersion. It happened to separate the two cards here only
  because `B3`'s worst rank fell exactly on the ≤5 line.

`A-rotation` remains the clearest case that the current gate is answering the wrong question. It fails
Gate S on an *absent* round-4 matrix — it did not exist in round 4, having been retired after it and
reinstated for round 5. But on the two matrices it did run, it ranked **10th and 1st**. That is a
genuine instability finding, entirely consistent with round 4's central result that rankings are
conditional on the window mix, and the current gate reaches it by accident through missing data rather
than by measuring it.

`strategy-program/ROUND-10-PLAN.md` pre-registers the replacement, written and committed before any of
round 10's numbers exist.

---

## For whoever runs round 10

1. **Reconcile the seat count.** This round's rule, applied exactly as pre-registered, fills one of
   four intended ranked seats. If a four-reference desk is wanted going forward, either Gate S's
   threshold (currently ≤5) or its scope (currently all three of round-2/round-4/round-5-ladder, with
   no partial credit) needs a pre-registered change *before* round 10's numbers exist — not after,
   and not because round 10 happens to produce a more convenient number under a stricter or looser
   line.
2. **`A-rotation`'s Gate S failure is a data-availability artefact, not a performance one**, and is
   worth a considered decision either way: treat "retired-then-reinstated" cards as ineligible for a
   gate that needs all three matrices (this round's reading), or decide that a card's *later* matrices
   can stand in for a missing earlier one where the card did not exist yet. Both are defensible; round
   9 takes the first because inventing a number for a matrix that was never run is exactly what this
   programme's own conventions (see `strategy-program/tools/score.py`'s treatment of missing cells)
   refuse to do elsewhere.
3. **Fix 4 (score the live desk's own matrix, weighted above backtests) is closer still** — every round
   this recommendation is repeated, the live desk accumulates more sessions and the case for weighting
   it directly, rather than through proxies like this round's Gate L recency clause, gets stronger.
4. **State the benchmark anchor wherever a SPY figure crosses a round boundary** — still true, still
   costing a round's attention every time it is not done first.
