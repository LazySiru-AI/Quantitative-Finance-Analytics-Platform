# Round 10 — Gate S′, applied

**Not investment advice.** Simulated books on a paper account, selected to be informative to watch.
I am not a licensed financial adviser and none of this is a recommendation about real capital.

**Run 2026-08-22** against the rule pre-registered in `strategy-program/ROUND-10-PLAN.md`, committed
in `940f643` before any figure in this document was produced. Every number here is reproducible:

```
cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round10.py --check
```

`run.txt` in this directory is that command's output verbatim; `scorecard.json` is its machine-readable
form.

---

## Read this before the tables: round 10 adds no new evidence

Rounds 9 and 10 are **two rules applied to one body of evidence**, not two measurements. The bar store
is unchanged since round 9 ran — verified, not assumed: SPY holds 8,445 rows ending 2026-08-18 and QQQ
6,903 rows ending 2026-08-18, the same figures round 9 recorded. Every card is frozen, every window is
fixed, and the out-of-sample period is still the same 127 sessions.

So this round **recomputes** the arithmetic over the stored results (cheap, and worth doing rather than
copying a prior round's prose) and **carries forward** Gate L rather than re-running it. Re-running a
frozen tournament over an unchanged store reproduces it exactly; reporting that as a second round's
confirmation would be one measurement counted twice, which `strategy-program/PROTOCOL.md` §6(a)
forbids and which this programme has already caught itself doing once.

**Nothing in this document is out-of-sample evidence that round 9 did not also have.** What changed is
the question asked of that evidence.

---

## The result

**Two ranked seats, and the desk shrinks from five references to three.**

| seat | card | live since 2026-01-01 | why |
|---|---|---|---|
| momentum | **`B-momentum`** | **+28.65%** | clears Gates A, L and S′ (rank range **1**: 3/2/2) and wins the ranking at **+7.68%** median annualized adjusted excess vs QQQ |
| trend | **`C-trend`** | **−2.03%** | clears all three gates (rank range **1**: 5/5/6) and wins the trend seat at **+2.01%** vs `H-trend-diversified`'s +1.79% |
| unranked, by design | **`ladder-qld-schd`** | +10.91% | seated outside the competition per `strategy-program/DRAWDOWN-LADDER.md`; not gated or ranked here |

Leaving on the rule: **`c07-chop`** (+0.26%, all cash) and **`H-trend-diversified`** (−2.36%).
Joining: `C-trend`.

**Two seats of a possible four, for the second round running.** The pre-registered rule made the seat
count an output with no floor precisely so this would be reportable rather than a decision to escalate
— see §6.

> **The desk actually trades four cards, not three.** `A-rotation` failed Gate S′ and was kept on the
> desk by owner override — **§7, added after §§1–6 were written**. The rule's output above is
> unchanged and `A-rotation` is still recorded as failing; the override is recorded beside it rather
> than folded into it. This table is what the rule produced, not what is running.

---

## 1. Gate A — unchanged, recomputed

Median annualized adjusted excess at the 5-year rungs (`h5y-1/2/3`) and 10-year rungs (`h10y-1/2`),
required positive against **both** benchmarks at **both** horizons.

**Benchmark anchors, stated per column:** SPY is the engine's own `benchmark_return` stored on each
`AgentResult`, measured over the sessions that run actually traded. QQQ is recomputed from the bar
store, close-to-close over each window's calendar dates in `data/rounds/r5-2026-08/windows.json`. The
two are separate defensible anchors for the same period and differ by up to ~0.12 annualized points on
these windows for reasons unrelated to any card.

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
| `c19-volatility` | +2.86% | +1.87% | −1.75% | −2.56% | **fail** |
| `c09-convex` | −0.49% | −1.38% | −0.46% | −0.98% | fail |
| `c18-meanrev` | −1.06% | −2.65% | −0.88% | −1.77% | fail |
| `c21-uncorrelated` | −2.38% | −4.15% | −1.40% | −3.09% | fail |
| `c14-riskmanaged-wide` | −2.83% | −5.35% | −1.79% | −3.25% | fail |
| `c11-breakout` | −3.96% | −7.28% | −2.39% | −4.90% | fail |
| `c20-rotation` | −4.28% | −7.14% | −3.77% | −6.12% | fail |

**Eight survivors — the same eight rounds 6, 8 and 9 found**, every figure identical to round 9's
published table. Expected: deterministic arithmetic over frozen results. It is recomputed rather than
copied so a transcription error would surface, and it did not.

## 2. Gate L — carried forward, inputs verified unchanged

Unchanged from round 9's tightened form: a card must have traded in the out-of-sample window
2026-02-17 to 2026-08-18 **and** either hold a position now or have traded within the last 60 sessions
(SPY's calendar puts that cutoff at 2026-05-22).

**Not re-run.** The clause is unchanged, the fifteen cards are frozen, the window is bounded by a bar
store verified identical above, and the desk's own `as_of` is still 2026-08-18. Round 9's §2 table is
the result, and re-deriving it here would produce the same file and invite it to be read as
independent confirmation.

- **`c07-chop` fails** — 100% cash, last trade closed 2026-04-07, 92 sessions before the as-of date.
- **`c14-riskmanaged-wide` fails** on zero out-of-sample trades, and was already out at Gate A.

**Seven cards proceed:** `B-momentum`, `B4-tight-stop`, `B2-hold-90`, `B3-concentrated`, `A-rotation`,
`C-trend`, `H-trend-diversified`.

## 3. Gate S′ — the respecified stability gate

Two clauses, and **no level term at all** (`strategy-program/ROUND-10-PLAN.md` §3):

- **S′-1 coverage** — a result on **at least 2** of the round-2, round-4 and round-5-ladder matrices.
  An absent matrix is never imputed in either direction.
- **S′-2 dispersion** — across the matrices the card actually ran, `max(rank) − min(rank) ≤ 3`.

Ranks are computed exactly as round 9 computed them, against the same fifteen-card field, and reproduce
round 9's §3 table for all seven cards it published.

| card | discipline | r2 | r4 | r5-ladder | range | matrices | S′ |
|---|---|---|---|---|---|---|---|
| `B-momentum` | momentum | 3 | 2 | 2 | **1** | 3 | pass |
| `B4-tight-stop` | momentum | 4 | 3 | 4 | **1** | 3 | pass |
| `C-trend` | trend | 5 | 5 | 6 | **1** | 3 | pass |
| `H-trend-diversified` | trend | 6 | 8 | 7 | **2** | 3 | pass |
| `B3-concentrated` | momentum | 2 | 1 | 5 | **4** | 3 | **fail** |
| `B2-hold-90` | momentum | 1 | 7 | 3 | **6** | 3 | **fail** |
| `A-rotation` | pairs-rotation | 10 | *absent* | 1 | **9** | 2 | **fail** |

(Gate L's seven survivors only. The full fifteen-card table, including the eight cards eliminated
earlier, is in `run.txt`; **no card that passes S′ was eliminated earlier**, so nothing is hidden by
showing the short table here.)

**No card passed on reduced coverage.** All four survivors ran all three matrices. The plan's disclosed
weakness — that a two-matrix card faces a mechanically easier dispersion bar (expected range 5.33 under
a null against a three-matrix card's 8) — therefore does not bear on this round's result at all. Four
cards in the wider field do pass S′-1 on two matrices (`c18-meanrev`, `c14-riskmanaged-wide`,
`c21-uncorrelated`, `c19-volatility`) and every one of them was already out at Gate A.

**`A-rotation` now fails for a substantive reason, and that is the repair working.** Round 9 excluded
it because its round-4 matrix is absent — an availability gap that read identically to a bad rank.
Under S′ the absent matrix is simply not counted, `A-rotation` clears the coverage floor on two
matrices, and it then fails on what those two actually say: **10th of fifteen on round 2's
bear-weighted matrix and 1st on round 5's ladder arm.** That is the largest rank swing in the field by
a factor of 1.5, and it is a direct instance of round 4's central finding that rankings are conditional
on the window mix. §5 states what this costs.

**`B3-concentrated` fails at range 4 (2/1/5), which is the discrimination the threshold was pinned
on.** Round 8's rule ranked it first and the owner overrode that in favour of `B-momentum` on exactly
this property. Under S′ the override is unnecessary: `B3` does not reach the ranking step.

## 4. Ranking and distinctness

Among the four S′ survivors, ranked by **median annualized adjusted excess vs QQQ** over the 5y and 10y
rungs (bar-store anchor, per §1):

| card | h5y-1 | h5y-2 | h5y-3 | h10y-1 | h10y-2 | **median** |
|---|---|---|---|---|---|---|
| `B-momentum` | +9.41% | +7.68% | +9.29% | +3.74% | +4.10% | **+7.68%** |
| `B4-tight-stop` | +9.67% | +7.79% | +4.96% | +3.87% | +3.16% | +4.96% |
| `C-trend` | +2.53% | +1.33% | +9.16% | +0.55% | +2.01% | **+2.01%** |
| `H-trend-diversified` | +1.89% | +0.91% | +6.55% | +0.86% | +1.79% | +1.79% |

**Distinctness** (one per `discipline`, and the four `B` variants counting as one base family) then
seats `B-momentum` over `B4-tight-stop`, and `C-trend` over `H-trend-diversified`.

**The trend seat was genuinely undecided going in, and it is close.** The plan (§4) flagged that round
9's Gate A table has `C-trend` at +1.28% and `H-trend-diversified` at +1.32% vs QQQ on the 10-year
rung — the wrong way round for `C-trend` — and declined to call it. Over the pooled five rungs
`C-trend` wins by **0.22 points**. Two things should temper that: the programme's own measured noise
floor from universe ordering alone is far larger than 0.22 points, and both cards' medians are pulled
around by a single outsized `h5y-3` rung (+9.16% and +6.55%, three to five times either card's other
cells). **This seat should be read as "a trend card, probably this one", not as a settled ranking.**
Round 8's open question about whether `discipline` is the right distinctness axis lands squarely here
and is still unanswered.

**Seat count:** two of a possible four. No third discipline reaches the ranking — every other card was
eliminated at Gate A (seven), Gate L (one) or Gate S′ (three).

---

## 5. What this costs, stated plainly

**Round 10 drops the best-performing reference on the live desk.** `A-rotation` returns **+65.18%**
since 2026-01-01 and **+37.36%** over the out-of-sample window, second only to `B3-concentrated` there.
The card replacing it on the desk, `C-trend`, is at **−2.03%** live and **+1.87%** out-of-sample.

**This is the third time a selection rule has dropped `A-rotation`, each time for a different stated
reason:** round 7 on the holdings-overlap cap (which round 7's own correction later found cost roughly
nine points of out-of-sample return), round 9 on an absent round-4 matrix, and round 10 on rank
dispersion. Round 8 reinstated it once already, by retiring the premise round 7's cap rested on.

Two readings, and this round does not claim to settle which is right:

- **The gate is working.** `A-rotation` is a high-exposure semis rotation that ranks 1st when the
  window mix favours risk and 10th of fifteen when it does not. A reference signal that is only good in
  one regime is exactly what a dispersion bar should catch, and its live +65.18% comes from a period
  that has been overwhelmingly one of those regimes.
- **The gate is throwing away the desk's most useful signal.** The out-of-sample record is 127
  sessions long and it says `A-rotation` works. Round 7 already made this mistake once on a different
  rule and had to correct it.

The honest position is that **one out-of-sample window cannot distinguish these**, and the programme's
own standing recommendation — score the live desk's own matrix and weight it above backtests, open
since round 6 — is the thing that would. It is still not done.

**The desk owner has since settled this in favour of the second reading and kept `A-rotation` on the
desk — §7, added after this section.** The rule's output is unchanged; the override is recorded rather
than folded into it.

---

## 6. What this is and is not evidence of

- **Not evidence that Gate S′ is too strict.** It is evidence that the *field* is narrow. Eight cards
  clear Gate A, four of the eight are variants of one base card, and two more are variants of a second.
  After distinctness there were never more than about four genuinely separate ideas available. The way
  to widen a reference desk is more distinct candidates, not a looser bar on these fifteen.
- **Not evidence that a fourth reference was unavailable.** `A-rotation` is on the desk by owner
  override, recorded in §7 below, added after this section was written. It failed Gate S′ and is
  seated anyway; the rule's own output remains two ranked seats.
- **Not evidence that round 9 was wrong to produce one seat.** Round 9's rule was applied faithfully
  and its arithmetic reproduces here exactly. It reached a defensible exclusion for `A-rotation`
  through an indefensible mechanism, which is the specific thing round 10 repaired — and the repair
  did not change that card's verdict, only the reason for it.
- **Not new out-of-sample evidence.** See the note at the top. Two rules, one body of evidence.
- **The seat count being an output was load-bearing.** Under round 9's "take the top four", this round
  would have been another under-fill needing a decision. Under round 10's rule, two seats is simply the
  answer, and the pressure to loosen a threshold to reach four never arises. That change is worth more
  than the change to Gate S itself.
- **`c07-chop` remains eliminated and remains uninformative.** It has held 100% cash for 92 sessions
  and returns +0.26% live. It was on the desk under round 8's roster; nothing is lost by its going.

---

## 7. Owner override, 2026-08-22 — `A-rotation` stays on the desk

**Added after sections 1–6 were written and their numbers produced. Nothing above is edited.** The
gates, tables and result stand exactly as recorded. Round 10's ranked output is still `B-momentum` and
`C-trend`, and `A-rotation` still fails Gate S′ at a rank range of 9.

**The desk trades `B-momentum`, `C-trend`, `A-rotation` and `ladder-qld-schd`.** Section 5 laid out
two readings of the `A-rotation` exclusion and explicitly declined to settle them. The desk owner has
settled it, on the side of the live record: 127 sessions at +37.36% out-of-sample and +65.18% since
inception, against a dispersion bar computed entirely from backtests.

`backend/app/paperdesk/desk.py`'s `AGENT_IDS` records this at the point of use, with the four ids
ordered by provenance — the two rule-selected seats, then the override seat, then the card seated
outside the competition.

### What is being overridden, precisely

Not Gate A: `A-rotation` passes it (+10.46% / +3.39% at 5y, +5.28% / +0.63% at 10y). Not Gate L: it
holds NVDA, AVGO and TSM today. **Only Gate S′**, and only its dispersion clause — 10th of fifteen on
round 2's bear-weighted matrix against 1st on round 5's ladder arm.

The override does not claim that swing is noise. It is real, it is the largest in the field, and §5's
first reading — that a reference signal which only works in one regime is exactly what a dispersion bar
should catch — is not refuted by anything here. The override claims something narrower: **that a
127-session live record is evidence the rule cannot see, and that on this card it points the other
way.** Whether it is *enough* evidence is precisely what the programme has no rule for.

### This is the second override in three rounds, and that is the finding

Round 8's rule ranked the momentum seat on one out-of-sample window and selected `B3-concentrated`;
the owner overrode it and seated `B-momentum`, then asked for the reasoning to become a rule. That
request produced **two entire rounds of rule-writing** — round 9 pre-registered a stability gate,
round 10 repaired it after round 9's version under-filled — and the repaired rule has now been
overridden too.

Both overrides went the same direction, and it is not a coincidence:

| | the rule ranked on | the owner weighted |
|---|---|---|
| round 8 | one 127-session out-of-sample window | rank stability across three backtest matrices |
| round 10 | rank stability across three backtest matrices | the 127-session live record |

Round 9 and round 10 correctly diagnosed round 8's problem and fixed it properly. **The fix was not
the thing that was actually missing.** Every gate in the rule — A, L, S′ — and the ranking step are
computed from backtests over frozen historical windows. Gate L is the only one that touches the live
desk at all, and it only asks whether a card is *alive*, never whether it is *right*. So the rule is
structurally unable to weigh the one input the owner has now twice weighted most heavily.

**A third gate will not close that gap.** Scoring the live desk's own matrix will, and that
recommendation has been open since round 6 (fix 4), repeated by rounds 7, 8, 9 and this one. Round 10
is the first round where its absence changed a seat rather than a footnote — and this override is the
second consequence of the same absence within it.

### Not being claimed

- **Not that Gate S′ is wrong or should be loosened.** It is unchanged, it stays pre-registered as
  written, and `A-rotation` is recorded as failing it. A rule that is overridden and says so is more
  useful than a rule quietly bent to agree with the outcome — round 8's document made the same choice
  and it is why round 9 and round 10 were possible at all.
- **Not that `A-rotation` will keep working.** Its live record comes from a period that has been
  strongly favourable to high-exposure semis exposure, which is the same fact §5's first reading rests
  on. If the regime turns, the 10th-of-fifteen half of that rank swing is what the desk will be
  watching.
- **Not that the desk is a portfolio.** Four independent reference signals on four separate simulated
  balances; nobody holds all four, and averaging them is a summary statistic rather than a result
  anyone could earn.

---

## For whoever runs round 11

1. **Score the live desk's own matrix and weight it above the backtests. This is now the only item
   that matters.** Recommended by rounds 6, 7, 8, 9 and 10. Round 10 is the first round where its
   absence changed a seat rather than a footnote — twice: once at Gate S′ (§5) and again at the
   override (§7). Two of the last three rounds ended with the owner overriding the rule, both times
   in the direction of live evidence the rule is structurally unable to see. **Do not write a fourth
   gate.** Round 8 asked for a rule and got two rounds of careful rule-writing that fixed a real
   defect and did not touch the actual gap.
2. **The trend seat is 0.22 points wide and should not be treated as settled** (§4). Either the
   distinctness axis needs revisiting — round 8's still-open question — or the trend pair needs a
   tie-break that is not a coin-flip-sized median difference.
3. **New candidates, not new thresholds.** `strategy-program/ROTH-MOMENTUM.md` and
   `strategy-program/ROTH-VOLTARGET.md` hold the only genuinely new ideas the programme has produced
   since round 5, and neither has been through a gate. They cannot run round 5's ladder windows as
   `StrategyCard`s and need either an `AllocationCard`-style execution path
   (`backend/app/tournament/allocation.py`) or an explicit decision to seat them unranked the way
   `ladder-qld-schd` is. That decision is round 11's most valuable single move.
4. **State the benchmark anchor wherever a SPY figure crosses a round boundary.** Held this round.
