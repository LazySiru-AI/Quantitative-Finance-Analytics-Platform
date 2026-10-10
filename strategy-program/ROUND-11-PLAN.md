# Round 11 — fix 4: the live record becomes the ranking criterion

**Not investment advice.** Simulated books on a paper account, selected to be informative to watch.
I am not a licensed financial adviser and none of this is a recommendation about real capital.

**Pre-registered 2026-08-22, before any round-11 result exists.** No sub-window has been run at the
time of writing. The only computation reported below is the sub-window calendar itself, taken from
SPY's session list — a property of the trading calendar, not of any card's performance. Section 6
states, in advance, what this rule is expected to produce and what would count as it going wrong.

---

## 1. Why this round exists

Fix 4 — *score the live desk's own matrix and weight it above the backtests* — has been the standing
recommendation since round 6 and was repeated by rounds 7, 8, 9 and 10. Round 10 is where its absence
stopped being a footnote:

- **Gate S′ dropped `A-rotation`** on backtest rank dispersion while a 127-session live record said
  the opposite (`data/rounds/r10-2026-08/SELECTION.md` §5), and the document could not resolve it
  because the programme has no rule for weighing live evidence against backtests.
- **The owner then overrode the rule and kept the card** (§7) — the second override in three rounds.
  Round 8's override went the same way. Both times the rule ranked on backtests and the owner
  weighted the live record.

The diagnosis in round 10 §7 is the premise of this round: **nothing in Gates A, L, S′ or the ranking
scores the live desk's own performance.** Gate L is the only clause that touches it, and it asks only
whether a card is *alive*, never whether it is *right*. Two rounds of careful rule-writing (round 9's
pre-registration, round 10's repair) fixed a real defect and never touched that gap. A fourth gate
would not either.

## 2. The live matrix

**One 127-session window is not a matrix.** It is one draw, and round 4's central finding is that a
single period's verdict is conditional on its regime. Treating it as a matrix and weighting it above
three backtest matrices would be replacing breadth with cleanliness and calling it an upgrade.

So the live record is **cut into six contiguous, non-overlapping sub-windows** and scored the way
every other matrix in this programme is scored: one `AgentResult` per (card, window), ranked on median
`adjusted_excess`, with a hit rate across windows. Boundaries are SPY's own sessions, split as evenly
as 127 divides:

| tag | start | end | sessions |
|---|---|---|---|
| `live-1` | 2026-02-17 | 2026-03-18 | 22 |
| `live-2` | 2026-03-19 | 2026-04-17 | 21 |
| `live-3` | 2026-04-20 | 2026-05-18 | 21 |
| `live-4` | 2026-05-19 | 2026-06-17 | 21 |
| `live-5` | 2026-06-18 | 2026-07-20 | 21 |
| `live-6` | 2026-07-21 | 2026-08-18 | 21 |

The period starts at 2026-02-17 and not at the desk's 2026-01-01 inception, because every card is
frozen with `designed_through = 2026-02-13`: the ~30 sessions before that are in-sample and a card
could in principle have been fitted to them. Only what follows is evidence nobody could have designed
against.

**What six sub-windows do and do not buy.** They turn one number per card into six, which measures
*consistency* — a card cannot be carried by one enormous month. They are **not** six independent
regime draws. They are one market environment cut into pieces, and a card that clears all six is
consistent *within that environment* and says nothing about any other. This is the central limitation
of fix 4 and slicing does not remove it; it only stops one sub-period masquerading as a record.

## 3. The rule

**Gate A — unchanged, and now explicitly a floor.** Positive median annualized adjusted excess at
round 5's 5y and 10y rungs against both SPY and QQQ. It stays eliminating. Its job is "the long-horizon
backtest does not say this card is broken", not "this card is good" — the second question moves to the
ranking.

**Gate L — unchanged.** Traded in the out-of-sample window and either holding a position now or having
traded within 60 sessions.

**Gate C (new) — the live consistency clause.** Positive `adjusted_excess` in **at least 3 of the 6**
sub-windows. A card whose live median rests on one outsized sub-window does not clear it. This is the
guard that stops "weight the live record" from meaning "weight the best month".

**Gate S′ — retired as an eliminating gate, kept as a tie-break.** Its dispersion number
(`max rank − min rank` across the round-2, round-4 and round-5-ladder matrices) is still computed and
**reported for every card**, and it now breaks ties instead of filtering. Round 10 established that S′
eliminates cards whose live record contradicts it; under fix 4 the live record is the senior evidence,
so backtest stability becomes the thing that decides between cards the live record cannot separate.

**Ranking (new, primary) — the live matrix.** Median `adjusted_excess` across the six sub-windows,
against the engine's own `benchmark_return` per sub-window (SPY, measured over the sessions each run
actually traded). Tie-breaks, in order: (1) live hit rate across the six; (2) Gate S′'s rank range,
lower better; (3) Gate A's 10-year QQQ median.

**Distinctness — unchanged.** At most one card per `discipline`, at most one per base family.

**Seat count — an output, capped at four, with no floor.** Unchanged from round 10, where it was the
change that mattered most.

## 4. What this deliberately gives up

Stated before the numbers exist, because after them it reads as excuse-making.

- **Breadth.** The three backtest matrices cover a GFC, a COVID crash, 2018's Q4, two chop regimes,
  a decade of bull market and 27 horizon windows. The live matrix covers six months of one
  environment. Weighting the narrow evidence above the broad evidence is the whole content of fix 4,
  and it is a real trade, not a free improvement.
- **Regime coverage, specifically.** Whatever worked between February and August 2026 will rank well
  here. If that period was kind to high-exposure equity books, this rule will seat high-exposure
  equity books, and it will have no way to notice.
- **Gate S′'s protection.** A card that ranks 1st on one backtest matrix and 10th of fifteen on
  another is no longer eliminated for it. That swing is real and the largest in the field; under this
  rule it costs a tie-break rather than a seat.

## 5. The integrity problem with this pre-registration, stated plainly

**This pre-registration is weaker than round 9's, and pretending otherwise would be the dishonest
part.** Round 9's rule was written before its numbers existed in any form. Round 11's is not, in one
specific way: **the full-window out-of-sample results are already published** in round 9's §2 table
and were read while writing rounds 9 and 10. The ordering of cards over 2026-02-17 to 2026-08-18 as a
single window is therefore known to whoever wrote this rule.

What is genuinely unknown, and what this round actually adds:

- how each card's `adjusted_excess` distributes **across** the six sub-windows,
- each card's **hit rate**, and therefore who clears Gate C,
- whether the median across sub-windows orders the field the same way the single full-window number
  does.

**The second risk is that fix 4 looks fitted to the owner's preference.** Round 10's override kept
`A-rotation`, and a rule that promotes the live record will plausibly seat `A-rotation` — which a
reader is entitled to read as the rule being bent to agree with the owner. The defence is a matter of
record and not of argument: fix 4 was recommended by rounds 6, 7, 8 and 9 — **three of those before
the round-10 override existed** — on grounds that had nothing to do with this card. That does not make
the suspicion unreasonable, so §6 pre-commits to a prediction that can fail.

## 6. Pre-committed expectations

Written before running. If the outcome contradicts these, the contradiction is reported, not the
prediction quietly revised.

1. **`B3-concentrated` is expected to lead the live matrix**, not `A-rotation`. It returned +51.63%
   over the full window against `A-rotation`'s +37.36%, and +39.83% adjusted vs QQQ against +24.28%.
   If the live-first rule seats `A-rotation` over `B3-concentrated`, that must come from Gate C, the
   sub-window median, or distinctness — with the specific mechanism named — and not be waved through.
2. **`B3-concentrated` and `B-momentum` are the same base family**, so distinctness will seat at most
   one of them regardless, and the momentum seat is expected to be decided between them by this rule
   rather than by the owner. That is the direct test of whether fix 4 dissolves round 8's override.
3. **Gate C is expected to eliminate at least one card with a strong full-window number.** If it
   eliminates nobody, it is not doing any work and should be said to be decorative rather than
   defended.
4. **A seat count of 2 to 4** is expected. Fewer than 2 would mean the live matrix is more restrictive
   than the backtest gates it replaced, which would be a finding worth more than the roster.

## 7. Execution

1. Stage the fifteen-card field from `backend/app/paper/library/`.
2. Run `app.tournament` over each of the six sub-windows, **serially** — the store is a single DuckDB
   file and a concurrent reader is recorded as an ordinary card failure, producing a report that looks
   complete and is quietly missing cards (`strategy-program/DEFECTS.md` D3).
3. Score with `strategy-program/tools/score.py` against a new `R11_MATRIX`.
4. Apply the rule above; write `data/rounds/r11-2026-08/SELECTION.md`.
5. Reconcile: 6 windows × 15 cards = **90 run files expected**. A shortfall is a lost card, not a
   rounding detail, and must be re-run rather than scored around.
