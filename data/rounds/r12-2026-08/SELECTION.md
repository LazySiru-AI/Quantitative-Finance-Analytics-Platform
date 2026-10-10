# Round 12 — distinctness, restated over holdings

**Not investment advice.** Simulated books on a paper account, selected to be informative to watch.
I am not a licensed financial adviser and none of this is a recommendation about real capital.

**Run 2026-08-22** against the rule pre-registered in `strategy-program/ROUND-12-PLAN.md`, committed
before any round-12 selection had run. Reproducible:

```
cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round12.py --json data/rounds/r12-2026-08/scorecard.json
```

`run.txt` is that command's output verbatim; `scorecard.json` its machine-readable form.

---

## 0. Read this first: round 12 adds no new evidence, and one thing about the store needs disclosing

**This round changes one rule — distinctness — and reruns nothing.** Gate A, Gate L, the live matrix,
Gate C and the ranking are the exact computations round 11 already published, recomputed from the same
stored `AgentResult` files rather than copied. `round12.py` imports `round10.gate_a`,
`round10.rung_excess_vs_qqq` and `round11.live_cells` rather than restating them, so a number here
means what the same number meant in round 11. **No tournament was run for this round.** Every read is
either a stored-JSON read or a read-only bar-store read, in line with `strategy-program/DEFECTS.md` D3.

**The store is not byte-for-byte what `ROUND-12-PLAN.md` assumed, and that is disclosed rather than
smoothed over.** The plan's feasibility check (its own §5) was run against a store the round expected
to still show when this document was written. `round12.py`'s own store check instead found:

```
SPY: 8448 rows, last 2026-08-21   (expected 8445 rows, last 2026-08-18)
```

Three extra sessions' worth of bars were appended to `data/store/bars` after round 11 closed — the
timestamps line up with the same day's `ROTH-CANDIDATES.md` / `roth-matrix.py` work in this same round
directory, which synced fresh bars for its own unrelated purpose. **This does not add evidence to
round 12.** Every computation below is bounded at or before the live window's own end date,
2026-08-18: Gate A's 5y/10y rungs end 2026-02-13 (`data/rounds/r5-2026-08/windows.json`), the live
matrix is six sub-windows differenced from cumulative runs that stop at 2026-08-18
(`round11.live_cells`), and the holdings walk reads `holdings_overlap.WINDOW`, which is also bounded
at 2026-08-18. Bars appended after that date are invisible to all three. The mismatch is reported here
because "the store is unchanged" is a claim this document makes explicitly below, and a reader should
be able to check it rather than take it on trust — it is checked, and it is not exactly true, though it
is inert for every number that follows.

**With that caveat stated: no new evidence was added within the window this round measures.** The
fifteen-card field is frozen, every window this round scores is fixed, and this is a different *rule*
applied to the same body of evidence round 11 already published — not a fresh measurement.

---

## The result

**Four ranked seats — and they are the same four cards currently on the desk.**

| seat | card | live median | hits | novel names |
|---|---|---|---|---|
| momentum (wide) | **`B3-concentrated`** | **+7.41%** | 4/6 | seated first |
| momentum (broad) | **`B-momentum`** | **+4.82%** | 3/6 | **1.32** vs `B3-concentrated` alone |
| pairs-rotation | **`A-rotation`** | **+3.47%** | 4/6 | **1.32** vs the union of the above |
| trend | **`C-trend`** | **+1.81%** | 3/6 | **1.21** vs the union of the above |
| unranked, by design | `ladder-qld-schd` | — | — | not assessed by this rule |

**`B4-tight-stop` and `B2-hold-90` clear every gate and reach the ranking, and both are excluded here** —
`B4-tight-stop` at **0.00** novel names against `B3-concentrated` alone (it held an identical book to
`B-momentum` on all 127 live sessions, mean daily Jaccard 100%), `B2-hold-90` at **0.08**. Neither adds
a name to the page that a seated card does not already show.

**This matches the plan's own feasibility check exactly** (`ROUND-12-PLAN.md` §5,
`data/rounds/r12-2026-08/holdings-overlap.txt`), which projected this same roster and named
`B4-tight-stop` and `B2-hold-90` as the two exclusions at these same counts. Section 4 below addresses
what that match does and does not mean.

---

## 1. Gates A and L — floors, unchanged, recomputed

**Gate A** (positive median annualized adjusted excess at round 5's 5y and 10y rungs vs both SPY and
QQQ) passes eight cards — the same eight rounds 6, 8, 9, 10 and 11 found:

`A-rotation`, `B-momentum`, `B2-hold-90`, `B3-concentrated`, `B4-tight-stop`, `C-trend`,
`H-trend-diversified`, `c07-chop`.

**Gate L** (traded out-of-sample, and holding now or traded within 60 sessions) removes `c07-chop`
(all cash for 92 sessions) and, from outside Gate A's survivors, would also remove
`c14-riskmanaged-wide` (zero trades). **Seven cards reach the live matrix**, unchanged from round 11.

Both gates are recomputed here rather than copied, and neither changed — their job under this round,
as under round 11, is "the long-horizon backtest does not call this card broken," a floor rather than
a rank.

## 2. The live matrix and Gate C — unchanged from round 11

Six contiguous sub-periods of 2026-02-17 to 2026-08-18, `adjusted_excess` per sub-period, recovered by
differencing consecutive cumulative runs (`round11.live_cells` — the fix for D5; no independent
sub-window tournament was run):

| card | live-1 | live-2 | live-3 | live-4 | live-5 | live-6 | median | hits |
|---|---|---|---|---|---|---|---|---|
| `B3-concentrated` | −1.23% | +14.69% | +15.88% | +26.47% | −14.88% | +0.14% | **+7.41%** | 4/6 |
| `B-momentum` | −0.85% | +10.50% | +12.89% | +17.12% | −12.62% | −2.58% | +4.82% | 3/6 |
| `B4-tight-stop` | −0.85% | +10.50% | +12.89% | +17.12% | −12.62% | −2.58% | +4.82% | 3/6 |
| `B2-hold-90` | −0.85% | +10.50% | +12.89% | +17.12% | −12.62% | −3.84% | +4.82% | 3/6 |
| `A-rotation` | +0.05% | +20.34% | +15.80% | +6.89% | −6.95% | −6.24% | +3.47% | 4/6 |
| `C-trend` | +0.00% | +3.74% | +4.71% | +3.62% | −6.60% | −8.20% | +1.81% | 3/6 |
| `H-trend-diversified` | +0.00% | +0.22% | −0.06% | −1.45% | −1.11% | −2.73% | −0.58% | 1/6 |

These are byte-identical to round 11's published cells, as they must be: same stored runs, same
differencing arithmetic, same code path (`round11.live_cells`, imported, not copied).

**Gate C** (positive `adjusted_excess` in ≥ 3 of 6) removes **`H-trend-diversified`** at 1/6. Six of
seven pass, unchanged from round 11.

## 3. Ranking — unchanged tie-break chain

Live median, then live hit rate, then Gate S′'s backtest rank range (lower better, retired as a gate
in round 11 and kept only as a tie-break), then Gate A's 10-year QQQ median:

| card | live median | hits | S′ range | 10y QQQ |
|---|---|---|---|---|
| `B3-concentrated` | +7.41% | 4/6 | 4 | +1.90% |
| `B-momentum` | +4.82% | 3/6 | **1** | +3.92% |
| `B4-tight-stop` | +4.82% | 3/6 | **1** | +3.51% |
| `B2-hold-90` | +4.82% | 3/6 | 6 | +4.60% |
| `A-rotation` | +3.47% | 4/6 | **9** | +0.63% |
| `C-trend` | +1.81% | 3/6 | **1** | +1.28% |

The tie-break chain does exactly the work it did in round 11: the three `B` variants tie on median and
hit rate; S′'s range separates `B2-hold-90` (6) from the other two (1 each); the 10-year QQQ median
separates `B-momentum` (+3.92%) from `B4-tight-stop` (+3.51%). **This ranking is unchanged from round
11's; what changes below is only which cards distinctness lets through.**

## 4. Distinctness — round 12's rule, over holdings

Walk the ranking above. Seat the first card unconditionally. Seat each later card if its **novel
names** — the mean over its own invested sessions of the count of names it holds that nothing already
seated holds, measured against the union of seated cards, per session across all 127 live sessions —
is **≥ 1.00**. Names come from each card's own trade log in the `live-6` cumulative run
(`holdings_overlap.held_by_session`), not weights or a snapshot.

| step | card | novel names | % of its book | invested sessions | verdict |
|---|---|---|---|---|---|
| 1 | `B3-concentrated` | — | — | — | **SEAT** (nothing to be redundant with) |
| 2 | `B-momentum` | 1.32 | 23.3% | 111/127 | **SEAT** (≥ 1.00) |
| 3 | `B4-tight-stop` | 0.00 | 0.0% | 111/127 | skip |
| 4 | `B2-hold-90` | 0.08 | 1.5% | 111/127 | skip |
| 5 | `A-rotation` | 1.32 | 49.9% | 118/127 | **SEAT** (≥ 1.00, against the union of steps 1–2) |
| 6 | `C-trend` | 1.21 | 37.0% | 89/127 | **SEAT** (≥ 1.00, against the union of steps 1, 2, 5) |

Four seats reached, at the round's cap. **`B4-tight-stop` held an identical book to `B-momentum` on
all 127 live sessions** — mean daily Jaccard 100% (`data/rounds/r12-2026-08/holdings-overlap.txt`) —
so its novelty against a set that already contains `B-momentum` is exactly zero by construction, not
by a near miss. `B2-hold-90` differs from the `B3`/`B-momentum` pair by less than a tenth of one name
on average and clears no threshold that was on the table (`ROUND-12-PLAN.md` §5 shows the roster is
identical at 0.50 and 1.00, so this is not a borderline call decided by exactly where the line sits).

## 5. What this evidence cannot do

Carried forward from `ROUND-12-PLAN.md` §4, because the limits of the rule do not expire when the rule
produces an answer:

- **It cannot assess a card that has not traded live.** Novelty is computed from the live window, so a
  new candidate — the contribution-funded families in `ROTH-CANDIDATES.md`, for instance — has no
  holdings to measure and cannot be seated or excluded by this rule at all. It would need to be seated
  outside the competition the way `ladder-qld-schd` is, or have its distinctness measured on backtest
  holdings over a window common to it and every seated card. **This round does not decide which; that
  gap is unchanged from the plan and is still open.**
- **It measures names, not weights.** `B3-concentrated` and `B-momentum` share every entry rule, exit
  rule, stop-loss and holding cap, and differ only in slot count and position size — four slots at 22%
  against six at 15% (`strategy-program/VARIANT-DISCRIMINATION.md` §1). This rule cannot see that
  difference in conviction; it can only see that `B-momentum`'s wider book currently holds two names
  `B3-concentrated` does not. `B3-concentrated` scores zero novelty against `B-momentum` seated first,
  for the same reason — the ranking, not this rule, decided which one gets to be "first" and therefore
  immune.
- **Order-dependence is real, not hypothetical, on this exact field.** §5's own sensitivity check
  shows it: at a threshold of 1.50, `A-rotation` (1.42 novel names) is rejected while `C-trend` (1.84)
  is seated, purely because `A-rotation` comes first in the walk and inherits a smaller residual. The
  rule run here, at 1.00, does not hit that failure mode — but the mechanism that would produce it if
  the threshold moved is present in this same roster, not a distant hypothetical.
- **One market environment, and half the programme's own bar.** The live window is 127 sessions of one
  regime — round 7 set ~250 sessions as the bar for weighting live evidence this heavily and round 8
  repeated it; round 11 ran fix 4 at half that anyway, and round 12 inherits the same shortfall without
  adding a single session to it. Every seat above should be read as provisional in the same sense round
  11 §4 stated: any margin here smaller than the difference between two sub-periods is not a settled
  finding.

## 6. This reproduces the desk's current roster — addressed directly, not glossed

**The four cards this rule seats — `B3-concentrated`, `B-momentum`, `A-rotation`, `C-trend` — are
exactly the four `StrategyCard`s the desk currently trades**, a state it reached through an owner
override (`data/rounds/r11-2026-08/SELECTION.md` §8) of the base-family clause this rule replaces. A
reader is entitled to the same suspicion `ROUND-12-PLAN.md` §5 named before this round ran: that a rule
written after watching that override, and designed specifically to let the overridden pairing back in,
was fitted to ratify a decision rather than test it.

The plan's own answer to that suspicion is what this round's result actually offers, carried forward
rather than re-argued:

1. **The threshold is a unit, not a fitted number.** "One whole position" was chosen before this
   round's numbers existed, and §5's sensitivity check — reproduced unchanged in
   `holdings-overlap.txt` and §4 above — shows the roster is identical at half that value. A rule
   balanced on the chosen threshold would not survive halving it; this one does.
2. **The rule excludes things that clear every other gate.** `B4-tight-stop` and `B2-hold-90` both pass
   Gate A, Gate L and Gate C, both reach the ranking, and both are cut here at 0.00 and 0.08 novel
   names. A rule engineered only to admit the owner's preferred four would not need teeth against
   cards adjacent to them.
3. **It reproduces a decision by making the owner's own stated reason measurable, not by agreeing with
   the preference.** The owner's argument in round 11 §8 for keeping `B-momentum` alongside
   `B3-concentrated` was that their holdings differ — a strict four-of-six subset, not a near-total
   overlap. This rule is that argument, turned into an auditable number: 1.32 novel names, 23.3% of
   the wider book. Agreeing with a specific, checkable claim about what two cards hold is a different
   thing from agreeing with a preference for which cards should be on the desk.

**What none of that adds up to is independent confirmation.** This is one field, one 127-session
window, and the first live outing of this exact rule. The rule was partly informed by watching the
override it now reproduces — `ROUND-12-PLAN.md` itself was written to give the base-family clause's
failure case (§1) a principled replacement, and that failure case *was* the `B3`/`B-momentum` pairing.
**If round 13 seats the same roster again on the same evidence, that is not a second measurement — it
is this measurement read twice.** A genuinely independent check needs either new live sessions the
rule has not yet seen, or a different pairing on the field to test the rule against, neither of which
this round supplies.

---

## For whoever runs round 13

1. **Do not read this roster as re-confirmation.** §6 above is explicit: the same evidence, scored by
   a rule partly shaped by watching this exact pairing get overridden, reproducing that pairing is
   expected, not remarkable. Treat the next genuinely new live sub-window as the first real test of
   this rule, not this round's output.
2. **The store-drift disclosed in §0 is a process gap, not a data problem.** Bars were appended to the
   shared store by concurrent work in this same round's directory while this round's numbers were
   being computed. Nothing here was affected because every read is bounded before the appended dates,
   but a future round's window boundaries may not be so lucky — worth a convention (a store snapshot
   pinned per round, or a check that fails loud rather than warns) before two rounds' concurrent work
   silently overlaps a window that matters.
3. **Card with no live record remains unresolved** (§5, first bullet). This is the same binding
   constraint round 11 named and round 12 does not touch: `ROTH-MOMENTUM.md` and `ROTH-VOLTARGET.md`
   are the only genuinely new ideas since round 5, `ROTH-CANDIDATES.md` now runs them on the
   tournament's own windows, and none of it has a distinctness path into this competition because this
   rule cannot score a card that has not traded live. Deciding that is the actual widening move
   available to round 13.
4. **`B4-tight-stop` is a duplicate row, not a distinct entry.** Identical holdings to `B-momentum` on
   all 127 sessions, 0.00 novel names in both directions. Round 11 §6 already recommended reconsidering
   its place in the field; this round adds a second, independent measurement of the same fact from a
   different angle (holdings rather than the stop-loss's binding frequency) and it says the same thing.
5. **Weights, not just names, is still the open gap** (§5, second bullet). The exact case this
   programme keeps returning to — `B3-concentrated` at four slots/22% against `B-momentum` at six
   slots/15% — is the one pairing this rule structurally cannot see the difference in, and it is the
   pairing currently occupying two of the desk's four seats.
