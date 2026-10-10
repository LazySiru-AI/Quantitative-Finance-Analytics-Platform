# Round 10 — Gate S, respecified

**Not investment advice.** Simulated books on a paper account, selected to be informative to watch.
I am not a licensed financial adviser and none of this is a recommendation about real capital.

**Pre-registered 2026-08-22, before any of round 10's numbers exist.** No round-10 run has been
executed at the time of writing. The one computation this document does report is a feasibility check
against *round 9's already-published field*, disclosed in full in section 4 below, and section 5 sets
out exactly what that check is and is not allowed to influence.

---

## 1. Why this round exists

Round 9 pre-registered a stability rule, applied it exactly as written, and filled **one** of four
intended ranked seats (`data/rounds/r9-2026-08/SELECTION.md`). The desk owner elected to keep round
8's five-agent roster running rather than ship the two-card output, and asked for Gate S to be
repaired rather than re-thresholded (that document, section 6).

Round 9's *finding* is not in dispute and is not revisited here. Its Gate A and Gate L tables, its
rank tables and its result all stand. What this document replaces is Gate S, the ranking step's
relationship to it, and the fixed seat count.

## 2. The two defects being fixed

**(a) Gate S and distinctness select against each other.** Gate S ranked each card against the whole
fifteen-card field and required a worst rank ≤ 5. Distinctness allows at most one card per
`StrategyCard.discipline`. A global top-five bar is clearable only by the field's strongest family —
in round 9 all three survivors were momentum variants — and distinctness then collapses them to a
single seat. Tightening Gate S reduces the number of *disciplines* that can reach the ranking, which
is the opposite of what a roster of independent reference signals needs.

The obvious repair — rank within discipline instead of globally — is **rejected**, because it has the
mirror defect. Round 9's field holds four momentum cards, two each in pairs-rotation, trend,
mean-reversion, volatility and risk-managed, and one in breakout. A within-discipline bar punishes a
card for having siblings and rewards one for having none: at "within-discipline rank ≤ 2" the entire
momentum family fails (its best card, `B-momentum`, is 3rd of 4 on round 2's matrix) while
`c11-breakout` — 8th, 11th and 12th of fifteen — passes automatically as the only card of its kind.
Swapping one scope for the other trades a bias toward large families for a bias toward small ones.

**(b) Gate S measures competitiveness, which is already measured twice.** "Never worse than fifth of
fifteen" is a statement about how good a card is. Gate A already tests that (positive median
annualized adjusted excess at the 5y and 10y rungs against both benchmarks) and the ranking step tests
it again directly. What round 8's override was actually reaching for is a different property:
`B-momentum` ranked 3/2/2 across the three matrices, `B3-concentrated` ranked 2/1/5. `B3` has the
better *level* on two of three; `B-momentum` has the tighter *spread*. A level bar cannot express
that, and separated the two here only because `B3`'s worst rank landed exactly on the ≤5 line.

## 3. Gate S′, as it will be applied

Ranks are computed exactly as round 9 computed them — 1-indexed, descending median adjusted excess
against the fifteen-card candidate field, on the round-2 matrix (`MAIN_WINDOW_TAGS`, non-annualized),
the round-4 matrix (`R4_MAIN_WINDOW_TAGS`, non-annualized) and the round-5 ladder arm
(`R5_LADDER_TAGS`, annualized, because that arm mixes 6-month through 10-year windows). Nothing about
how a rank is produced changes; only what is asked of it.

**S′-1 — coverage.** The card must have a result on **at least two** of the three matrices. A card
with one matrix has no dispersion to measure. **An absent matrix is never imputed**, in either
direction: not counted as a failure, not filled in from a neighbouring round.

**S′-2 — dispersion.** Across the matrices the card actually ran, `max(rank) − min(rank) ≤ 3`.

That is the whole gate. It contains no level term, because level is Gate A's job and the ranking
step's job.

**Why 3.** Under a null where a card's rank is unrelated to the matrix, three draws from fifteen have
an expected range of `(n+1)(k−1)/(k+1)` = 8. A bar of ≤ 3 is under half the range chance alone
produces, and it is the largest threshold that still excludes `B3-concentrated`'s 2/1/5 — the exact
pair of cards round 8's override was about, and therefore the one discrimination this gate has to be
able to make to be worth having. Both facts are stated so a later reader can see the threshold was
anchored twice and pinned by the second.

**The disclosed weakness.** The same null gives a two-matrix card an expected range of 5.33 against a
three-matrix card's 8, so `≤ 3` is a mechanically easier bar on two matrices than on three. The
coverage clause limits the exposure, and any card that passes on two matrices **must be marked
reduced-coverage in round 10's own tables**, with its rank pair printed rather than only its range. It
is not adjusted for numerically, because a size-corrected threshold on this small a sample would be a
precision the evidence does not carry.

### The ranking, distinctness, and the seat count

**Gate A** — unchanged from round 9. **Gate L** — unchanged from round 9's tightened form (traded in
the out-of-sample window, and either holding a position now or having traded within 60 sessions).
**Ranking** — unchanged: median annualized adjusted excess over round 5's 5y and 10y rungs
(`h5y-1/2/3`, `h10y-1/2`) against QQQ, tie-break out-of-sample adjusted excess vs QQQ.
**Distinctness** — unchanged: at most one per `discipline`, at most one per base family.

**Changed: the seat count is an output, not a target.** Round 9's rule ended "take the top four", and
that instruction is what turned an under-fill into a problem needing a decision. Round 10 seats *every*
card that clears Gates A, L and S′ after distinctness, **capped at four** and with no floor. A roster
of two is a reportable result about the field, not a failure of the round; a roster of five is capped
back to four on the ranking. `ladder-qld-schd` remains seated outside the competition and unranked,
per `strategy-program/DRAWDOWN-LADDER.md`.

## 4. Feasibility check — disclosed in full

A gate that structurally cannot fill a seat is broken regardless of how principled it reads, so S′ was
run against round 9's published field before being committed. **This is a check on the rule, not a
round-10 result**, and round 10's own numbers do not exist yet.

Global ranks are reproduced independently from `data/rounds/r{2,4,5}-2026-08/results` and match round
9's section 3 table exactly for all seven cards it published — the same arithmetic over the same
frozen results, as expected.

| card | discipline | r2 | r4 | r5-ladder | range | matrices | S′ |
|---|---|---|---|---|---|---|---|
| `B-momentum` | momentum | 3 | 2 | 2 | **1** | 3 | pass |
| `B4-tight-stop` | momentum | 4 | 3 | 4 | **1** | 3 | pass |
| `C-trend` | trend | 5 | 5 | 6 | **1** | 3 | pass |
| `H-trend-diversified` | trend | 6 | 8 | 7 | **2** | 3 | pass |
| `B3-concentrated` | momentum | 2 | 1 | 5 | **4** | 3 | fail |
| `c07-chop` | mean-reversion | 7 | 4 | 8 | **4** | 3 | fail |
| `B2-hold-90` | momentum | 1 | 7 | 3 | **6** | 3 | fail |
| `A-rotation` | pairs-rotation | 10 | *absent* | 1 | **9** | 2 | fail |

(Gate A's eight survivors only; the seven cards Gate A eliminates cannot reach Gate S′.)

Applying the rest of the rule to those four: `c07-chop` is already out at Gate L, and distinctness
takes one momentum card and one trend card. On the ranking metric that would be `B-momentum` over
`B4-tight-stop` and `C-trend` over `H-trend-diversified` — indicative only, since the check above was
ordered on the engine's SPY anchor (`B-momentum` +9.68% vs `B4` +7.75%; `C-trend` +6.98% vs
`H-trend-diversified` +4.40%, median annualized adjusted excess over the five rungs) and the rule
ranks on QQQ. **The trend pair is close on the 10-year rung specifically** — round 9's Gate A table has
`C-trend` +1.28% and `H-trend-diversified` +1.32% vs QQQ there — so that seat is genuinely undecided
until round 10 runs it, and nothing here should be read as having decided it.

**Projected: two ranked seats plus the ladder.** Better than round 9's one, still short of four, and
for reasons that are now findings rather than artefacts.

### What the check changed, and what it did not

It changed **one** thing: the seat count became an output rather than a target (section 3), because
the check showed a well-specified gate still does not fill four seats on this field, which means the
fixed four was never a property of the evidence. That change is disclosed here rather than folded in
silently.

It did **not** move the ≤ 3 threshold. Loosening to ≤ 4 would admit `B3-concentrated` and `c07-chop`;
`B3` is collapsed by distinctness anyway and `c07-chop` fails Gate L, so it would buy no seats — and
it would undo the one discrimination section 3 pinned the threshold on.

## 5. What this round will and will not be evidence of

- **`A-rotation` failing S′ is now a substantive finding, not a data-availability artefact.** It ranks
  10th of fifteen on round 2's bear-weighted matrix and 1st on round 5's ladder arm. That is the
  largest rank swing in the field, it is measured on matrices the card actually ran, and it is exactly
  what round 4 concluded in general: **rankings are conditional on the window mix.** Round 9 reached
  the same exclusion through a missing round-4 matrix — the right answer for the wrong reason. It is
  still not evidence that `A-rotation` is a bad card; it clears Gate A and holds live positions.
- **Two ranked seats, if that is what round 10 produces, is a statement about the field's width, not
  about the gate.** Eight cards clear Gate A, and four of the eight are variants of one base card. The
  way to widen a roster of independent references is more genuinely distinct candidates — the
  contribution-funded families in `strategy-program/ROTH-MOMENTUM.md` and
  `strategy-program/ROTH-VOLTARGET.md` are the obvious source, and neither has been through a gate yet
  — not a looser bar on the same eight.
- **Still one out-of-sample window.** 2026-02-17 onward remains the only period nobody could have
  designed a card against, and Gate L and the tie-break both still rest on it.
- **Benchmark anchor must be stated wherever a SPY figure crosses a round boundary.** The engine's
  `benchmark_return` and a bar-store calendar slice differ by up to ~0.12 annualized points on these
  windows for reasons unrelated to any card. Round 9 stated it per figure; round 10 does the same.

## 6. Carried forward, still not done

1. **Score the live desk's own matrix and weight it above the backtests.** Recommended by rounds 6, 7,
   8 and 9. Every round that passes adds sessions to the only genuinely out-of-sample record the
   programme has, and Gate L's recency clause is a proxy for it rather than the thing itself.
2. **The Roth candidates need a card shape before they can be gated.** `vol-target-12/20d` and the
   regime-switch variants are simulated through `strategy-program/tools/contributions.py`, which is a
   different harness from `app.tournament`; they cannot run round 5's ladder windows as `StrategyCard`s
   and would need either an `AllocationCard`-style path (`backend/app/tournament/allocation.py`) or an
   explicit decision to seat them unranked the way `ladder-qld-schd` is.
