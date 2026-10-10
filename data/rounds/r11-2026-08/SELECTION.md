# Round 11 — fix 4, applied (and a measurement defect caught first)

**Not investment advice.** Simulated books on a paper account, selected to be informative to watch.
I am not a licensed financial adviser and none of this is a recommendation about real capital.

**Run 2026-08-22** against the rule pre-registered in `strategy-program/ROUND-11-PLAN.md`, committed
in `dda5573` before any sub-window existed. Reproducible:

```
cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round11.py
```

`run.txt` is that command's output verbatim; `scorecard.json` its machine-readable form.

---

## 0. Read this first: the first attempt at this matrix was invalid

**The instrument was rebuilt mid-round, and the reason matters more than the result.**

`ROUND-11-PLAN.md` §2 pre-registered cutting the live period into six sub-windows. The first
implementation ran **each sub-window as its own tournament**. Every one of those runs starts with a
flat book — so a card that entered positions in March and held them into August was made to liquidate
and re-enter at each boundary, inside a window too short for many entry rules to re-fire at all.

`B-momentum` over the full window takes 11 trades at 56.9% capital exposure and returns +31.97%. Cut
into six independent runs it showed **zero trades and 0.0% exposure in two entire sub-windows** — not
because it was in cash, but because its confirmed-acceleration rule cannot accumulate its lookback in
21 sessions from flat. That matrix measured *"this card, liquidated every 21 sessions"*, which is a
different strategy from the one on the desk.

**It was directionally biased**, not merely noisy: high-turnover cards barely notice a reset, cards
that enter once and hold are destroyed by it. On the invalid matrix all four momentum variants and
both trend cards scored 1/6, while the two highest-turnover cards in the field scored 4/6 and 5/6.

**And it produced the convenient answer.** It seated `A-rotation` alone — the same card the owner had
overridden round 10's rule to keep one day earlier. That is exactly what `ROUND-11-PLAN.md` §5 told a
reader to be suspicious of. What caught it was §6's pre-committed prediction that `B3-concentrated`,
not `A-rotation`, should lead the live matrix: the prediction was **contradicted**, which prompted
looking at the `+0.00%` cells instead of shipping the roster.

Recorded as `strategy-program/DEFECTS.md` **D5**. The invalid output is kept at
`results-independent-INVALID/` as the evidence for it rather than deleted.

**What changed and what did not.** The six runs are now **cumulative** from one fixed start
(2026-02-17 → each boundary), and each sub-period is recovered by differencing consecutive runs, which
is exact for return, benchmark and capital exposure alike (`round11.py`'s `live_cells`). **No
threshold, gate, window boundary or ranking criterion moved.** `ROUND-11-PLAN.md` is unamended. The
correction has a mechanical justification independent of which card it favours — and it moved the
result *away* from the convenient one.

A runtime self-check pins it: for the first sub-period there is nothing to difference against, so the
differenced cell must reduce exactly to `score.adjusted_excess`. It does, **for all 15 cards**.

---

## The result

**Three ranked seats.**

| seat | card | live median | hits | live since 2026-01-01 |
|---|---|---|---|---|
| momentum | **`B3-concentrated`** | **+7.41%** | 4/6 | +47.07% |
| pairs-rotation | **`A-rotation`** | **+3.47%** | 4/6 | +65.18% |
| trend | **`C-trend`** | **+1.81%** | 3/6 | −2.03% |
| unranked, by design | `ladder-qld-schd` | — | — | +10.91% |

**`B-momentum` leaves the desk.** It clears every gate and ranks second on the live matrix (+4.82%,
3/6), but `B3-concentrated` is the same base family and outranks it, so distinctness seats one.

**All four pre-committed expectations held** (§6 of the plan; reproduced by `round11.py` itself):
`B3-concentrated` led the live matrix; the momentum seat was decided by the rule; Gate C eliminated a
card (`H-trend-diversified`); the seat count landed in the predicted 2–4.

---

## 1. Gates A and L — floors, unchanged

**Gate A** (positive median annualized adjusted excess at round 5's 5y and 10y rungs vs both SPY and
QQQ) passes eight cards, the same eight rounds 6 and 8–10 found. **Gate L** (traded out-of-sample, and
holding now or traded within 60 sessions) removes `c07-chop`. `c14-riskmanaged-wide` fails both.

Both are recomputed but neither changed, and neither ranks anything any more. Their job under fix 4 is
to say "the long-horizon backtest does not call this card broken" — not to say which card is best.
**Seven cards reach the live matrix.**

Benchmark anchors are unchanged and stated per figure: SPY from the engine's own `benchmark_return`
over the sessions each run traded; QQQ recomputed from the bar store over each window's calendar dates.

## 2. The live matrix

Six contiguous sub-periods of 2026-02-17 to 2026-08-18, `adjusted_excess` per sub-period, whole field:

| card | live-1 | live-2 | live-3 | live-4 | live-5 | live-6 | median | hits |
|---|---|---|---|---|---|---|---|---|
| `B3-concentrated` | −1.23% | +14.69% | +15.88% | +26.47% | −14.88% | +0.14% | **+7.41%** | 4/6 |
| `B-momentum` | −0.85% | +10.50% | +12.89% | +17.12% | −12.62% | −2.58% | **+4.82%** | 3/6 |
| `B4-tight-stop` | −0.85% | +10.50% | +12.89% | +17.12% | −12.62% | −2.58% | +4.82% | 3/6 |
| `B2-hold-90` | −0.85% | +10.50% | +12.89% | +17.12% | −12.62% | −3.84% | +4.82% | 3/6 |
| `A-rotation` | +0.05% | +20.34% | +15.80% | +6.89% | −6.95% | −6.24% | **+3.47%** | 4/6 |
| `C-trend` | +0.00% | +3.74% | +4.71% | +3.62% | −6.60% | −8.20% | **+1.81%** | 3/6 |
| `H-trend-diversified` | +0.00% | +0.22% | −0.06% | −1.45% | −1.11% | −2.73% | −0.58% | 1/6 |

(The eight cards eliminated at Gate A or L are in `run.txt`; none of them would have reached a seat.)

**The three `B` variants are nearly indistinguishable here.** `B-momentum`, `B4-tight-stop` and
`B2-hold-90` post identical medians and identical cells in five of six sub-periods — over this period
their different exits almost never bound. That is a finding about the period, not about the cards: six
months of one environment is not enough for a stop-loss or a holding cap to be tested.

**Every survivor's shape is the same.** Flat, three strong sub-periods, one sharp negative, a weak
finish. These are not six independent draws — see §4.

## 3. Gate C, the ranking, and distinctness

**Gate C** (positive `adjusted_excess` in ≥ 3 of 6) removes **`H-trend-diversified`** at 1/6. Six of
seven pass. The gate did something, which §6 of the plan required it to do or be called decorative —
but one elimination on this field is close to the line, and a reader should treat it as a weak filter
rather than a strong one.

**Ranking** is the live median, then the live hit rate, then Gate S′'s backtest rank range (lower
better), then Gate A's 10-year QQQ median:

| card | live median | hits | S′ range | 10y QQQ |
|---|---|---|---|---|
| `B3-concentrated` | +7.41% | 4/6 | 4 | +1.90% |
| `B-momentum` | +4.82% | 3/6 | **1** | +3.92% |
| `B4-tight-stop` | +4.82% | 3/6 | **1** | +3.51% |
| `B2-hold-90` | +4.82% | 3/6 | 6 | +4.60% |
| `A-rotation` | +3.47% | 4/6 | **9** | +0.63% |
| `C-trend` | +1.81% | 3/6 | **1** | +1.28% |

The full tie-break chain was needed and worked: the three `B` variants tie on median *and* hit rate;
the S′ range separates `B2-hold-90` (6) from the other two (1 each); and the 10-year QQQ median finally
separates `B-momentum` (+3.92%) from `B4-tight-stop` (+3.51%). **Gate S′ demoted from gate to
tie-break is doing real work in exactly the place a tie-break should** — between near-identical
variants of one card — and none in the place it used to do damage.

**Distinctness** seats `B3-concentrated` (momentum), then `A-rotation` (pairs-rotation), then
`C-trend` (trend). No fourth discipline reaches the ranking. **Three seats of four**, and under the
rule's no-floor seat count that is an answer rather than a shortfall.

---

## 4. What this evidence cannot do

- **Six contiguous sub-periods of one period are not six regime draws.** Every survivor's row has the
  same shape because they all lived through the same market. Gate C measures consistency *within* that
  environment and says nothing about any other. This is the central limitation of fix 4 and the split
  does not remove it; it only stops one outsized month masquerading as a record.
- **The backtests, now demoted, are where regime coverage lived.** The three matrices span a GFC, a
  COVID crash, 2018's Q4, two chop regimes, a decade of bull market and 27 horizon windows. Round 11
  weights six months of 2026 above all of it. That is the whole content of fix 4 and it is a trade:
  the live record is the only evidence nobody could have fitted a card to, and it is also the
  narrowest evidence in the programme.
- **`A-rotation`'s S′ range of 9 has not gone away.** It ranks 10th of fifteen on round 2's
  bear-weighted matrix and 1st on round 5's ladder arm. Under this rule that costs a tie-break rather
  than a seat, which is a deliberate choice, not a finding that the swing was noise. If the regime
  turns, that is the card to watch first.
- **Still one out-of-sample period, now cut six ways.** Cutting a single sample into six pieces gives
  six numbers, not six samples.

### And this round ran fix 4 at half the sample the programme itself specified

**Round 7 set the bar at ~250 out-of-sample sessions and deferred fix 4 until the desk reached it**
(`data/rounds/r7-2026-08/SELECTION.md`: *"This needs roughly 250 sessions... Deferred to the round
after the desk reaches ~250 sessions, around mid-2027"*). Round 8 repeated the figure. The desk has
**127**.

Round 11 ran it anyway, on request. That is a legitimate call — round 10 showed the cost of having no
live-evidence rule at all, and half a sample beats none — but it is a **departure from a standard this
programme set for itself**, and `ROUND-11-PLAN.md` §4 listed what fix 4 gives up without mentioning
it. That omission is mine and is recorded here rather than left for a later round to rediscover.

Concretely, what the missing half-sample means: mid-2027's version of this matrix will cover roughly
twelve sub-periods spanning conditions this one does not. **Any seat decided by a margin smaller than
the difference between two sub-periods should be treated as provisional** — which, in §3's table, is
the entire `B`-variant tie and arguably `C-trend`'s seat as well.

## 5. What fix 4 actually settled — it split the two overrides

The point of round 11 was to give the rule access to the evidence the owner had twice weighted and the
rule could not see. It did, and **it did not simply agree with the owner**:

| | the rule said | the owner said | the live record says |
|---|---|---|---|
| **round 8** | `B3-concentrated` | overrode → `B-momentum` | **`B3-concentrated`** (+7.41% vs +4.82%, 4/6 vs 3/6) |
| **round 10** | drop `A-rotation` | overrode → kept it | **keep it** (seated on the rule, +3.47%, 4/6) |

**Round 8's override is reversed and round 10's is vindicated, by the same evidence.** That is the
outcome most worth trusting here, precisely because it is not the flattering one for either party: a
live-first rule that had simply ratified every owner decision would be indistinguishable from a rule
fitted to them, which §5 of the plan said a reader was entitled to suspect.

`B-momentum` was the card seated by round 8's override, kept through round 9's rule, and named
explicitly as one to keep. It is not seated by *this ranking* — it loses to a variant of itself on the
live record. **That is the owner's call to make, and the rule's job was to make the trade-off visible
rather than to make the decision.**

**The owner has since made it: `B-momentum` is back on the desk as a fifth seat — §8, added after this
section.** The ranking above is unchanged and `B3-concentrated` keeps the ranked momentum seat; what
§8 overrides is distinctness, not the rank.

---

## 8. Owner override, 2026-08-22 — `B-momentum` returns as a fifth seat

**Added after sections 0–7 were written and their numbers produced. Nothing above is edited.** The
ranking is unchanged: `B3-concentrated` still leads the live matrix at +7.41% against `B-momentum`'s
+4.82%, and still holds the ranked momentum seat.

**The desk trades `B3-concentrated`, `A-rotation`, `C-trend`, `B-momentum` and `ladder-qld-schd`.**

### This override is a different shape from the previous two

Rounds 8 and 10 were overridden on **which card is better** — genuine disagreements about what the
evidence said. This one is not. Nobody disputes the rank order here; §5 of this document is the
evidence that reversed round 8's override, and it stands.

What is being overridden is **distinctness** — the rule that at most one card per base family may be
seated, which exists so the desk does not display one idea twice.

### The holdings say what that rule is actually costing

`B3-concentrated` and `B-momentum` share every entry rule, exit rule, stop-loss and holding cap. They
differ only in slot count and position size: four slots at 22% against six at 15%
(`strategy-program/VARIANT-DISCRIMINATION.md` §1). As of 2026-08-18:

| | holdings |
|---|---|
| `B3-concentrated` | MRVL, TSM, AMD, MSFT |
| `B-momentum` | MRVL, TSM, AMD, MSFT, **AMZN, NVDA** |

**A strict subset — 4 of 6 names, not a large coincidental overlap.** So the second panel is not a
redundant copy of the first. It is the same rules run at a wider slot count, and what a reader gets
by having both is precisely **which names survive the tighter one**. For a desk whose stated purpose
is "see what each signal is buying", that is a legible comparison rather than a duplicated signal.

This also means the distinctness rule was, in this specific pairing, protecting against the wrong
thing. It is written to stop two *ideas* being counted once each when they are really one idea. Here
there is one idea, and the second seat displays a property of it — breadth — that no other panel on
the desk shows.

### The cost, which is real

- **Two of five panels now agree almost entirely.** A reader skimming the desk sees five cards of
  equal visual weight, and that overstates how much independent evidence is on the page. Four of the
  five are momentum-or-semis-shaped.
- **It is the third override in four rounds.** Rounds 8, 10 and 11 each ended with the owner seating
  something the rule did not. That the third one overrides a *different* rule than the first two is
  what makes it a new data point rather than a pattern of ignoring the rule — but it is worth
  counting honestly.
- **The subset relationship is a fact about today, not a guarantee.** `B3-concentrated` holds a
  subset of `B-momentum`'s names because both are currently long the same leaders. In a rotation
  where the narrower book concentrates into a name the wider one has already exited, the two panels
  would diverge and the "wider version of the same signal" reading would stop holding. Worth
  re-checking rather than assuming.

### For round 12

**Distinctness needs re-specifying, and this is the second rule in three rounds to fail on the same
axis.** Gate S was mis-specified because it ranked globally while distinctness worked per discipline
(round 10 §2); distinctness itself is now mis-specified because it treats "same base family" as
"same information", which the holdings table above refutes for at least one pairing.

The candidate replacement is a rule stated over what a card *holds* rather than what family it
descends from — round 7 already used a holdings-overlap cap and round 8 retired it, so the history is
there and the reasons it was retired should be read before it is revived. Pre-register whichever way
it goes, before round 12's numbers exist.

**Done — `strategy-program/ROUND-12-PLAN.md`.** It replaces both proxies with one rule over holdings,
measured per session across the whole live window rather than on a snapshot, and asymmetric so that
"seat the wide card, then the narrow one adds nothing" becomes expressible. Round 8's retirement
reasoning is answered rather than ignored: the cap it dropped asked a portfolio-concentration
question, this one asks a display-redundancy question, and overlap here never chooses between cards —
the ranking runs first, so a card can never be dropped in favour of a worse one the way round 7's cap
dropped `A-rotation`.

One figure from that document's feasibility check belongs here too, because it is the strongest single
case for measuring holdings rather than lineage: **`B4-tight-stop` and `B-momentum` held identical
books on all 127 sessions**, mean daily Jaccard **100%**. Over six months the tighter stop never once
changed a holding. No proxy for "a different idea" could have seen that, and both cards sat in this
round's ranking as separate entries.

---

## For whoever runs round 12

1. **Do not treat fix 4 as finished.** The live matrix is one environment. It will become genuinely
   multi-regime only with time, and the honest thing to do until then is to keep reporting the backtest
   matrices beside it — which this round does, as floors and a tie-break, rather than discarding them.
2. **The `B`-variant tie is a real gap, not a quirk.** Three variants posted identical cells in five of
   six sub-periods because their differing exits never bound. If distinguishing them matters, they need
   a window where a stop-loss or a holding cap actually fires, which is a *window design* problem, not
   a scoring one.
3. **Gate C eliminated exactly one card and should be watched, not trusted.** A gate that removes 1 of
   7 on its first outing may be well-calibrated or may be nearly inert. One round is not enough to say.
4. **New candidates remain the binding constraint.** Eight cards clear Gate A and six of the eight are
   variants of two base cards. `strategy-program/ROTH-MOMENTUM.md` and
   `strategy-program/ROTH-VOLTARGET.md` still hold the only genuinely new ideas since round 5 and still
   have no execution path into the tournament.
5. **D5 is a class of error, not a one-off.** Any future matrix built by slicing a live period must
   preserve position continuity across the slices. The cumulative-and-difference approach in
   `round11.py` is the pattern; six independent runs is the trap.
