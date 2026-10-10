# Round 7 — re-selection under the live-evidence gates

**Not investment advice.** Simulated books on a paper account, selected to be informative to watch.
I am not a licensed financial adviser and none of this is a recommendation about real capital.

> **Correction, 2026-08-22.** Everything below was computed on a 55-session window (2026-06-01 to
> 2026-08-18). The desk was subsequently backdated to 2026-01-01, which exposed that window as an
> unrepresentative slice of a much longer forward period. **Section 9 corrects the two claims that
> depended on it**, including the headline that the live evidence contradicted the backtests. It does
> not.

Round 7 applies the four fixes pre-registered in `data/rounds/r6-2026-08/SELECTION.md` §6.3, written
before this round had any data. Three could be applied; the fourth could not, and that is recorded
rather than fudged.

---

## The result

| seat | card | live 55 sessions | why |
|---|---|---|---|
| performance | **`B-momentum`** | −5.21% | best worst-rank across matrices (3/2/2); clears Gate A |
| performance | **`H-trend-diversified`** | −2.25% | **the only card in the field that can sit beside an equity book** |
| hedge | **`c20-rotation`** | −5.96% | +14.8-point bear swing, largest in the programme; ρ = −0.054 to the core |
| hedge | **`c11-breakout`** | −0.28% | clears every cap against all three seated |

**Dropped: `A-rotation`, `c07-chop`, `c14-riskmanaged-wide`** — all three seated by round 6, all
three removed by gates round 6 itself asked for.

**Single reference is still `B-momentum`.** Nothing in round 7 displaced it, and §5 of round 6's
document still applies unchanged, including that its honest expectation is roughly +4% a year over
QQQ rather than the +14.8% a 5-year SPY figure suggests.

---

## 1. Fix 1 — the liveness gate

*A desk card must be shown to have traded in the 60 sessions before selection.*

| card | live return | closed trades | holding now | liveness |
|---|---|---|---|---|
| `c18-meanrev` | **+2.44%** | 19 | CL, MMM | pass |
| `c09-convex` | +0.16% | 1 | GLD | pass |
| **`c07-chop`** | 0.00% | **0** | *nothing* | **FAIL** |
| **`c14-riskmanaged-wide`** | 0.00% | **0** | *nothing* | **FAIL** |
| `c19-volatility` | −0.14% | 1 | *nothing* | pass |
| `c11-breakout` | −0.28% | 0 | SPY | pass (open position) |
| `c21-uncorrelated` | −0.85% | 1 | DBC | pass |
| `H-trend-diversified` | −2.25% | 2 | DBC, NVDA, GDX | pass |
| `B-momentum` / `B2` / `B4` | −5.21% | 2 | MSFT, AMZN, NVDA, AVGO, TSM | pass |
| `c20-rotation` | −5.96% | 21 | XLV, XLP, DBC | pass |
| `B3-concentrated` | −6.94% | 2 | MSFT, AMZN, NVDA, AVGO | pass |
| `C-trend` | −7.24% | 2 | NVDA, AVGO, TSM, SOXX | pass |
| `A-rotation` | **−12.77%** | 10 | NVDA, AVGO, TSM (99%) | pass |

Two of round 6's four selections fail immediately. Both cleared round 6's exposure floor, which is
measured on historical windows and cannot see the regime the desk is about to run in. That was the
defect round 6 logged; this is it being paid.

## 2. Fix 2 — the holdings-overlap cap, and what it did to the field

*No two desk cards may share more than 25% of book weight in the same symbols.* Overlap is the sum,
over shared symbols, of the smaller of the two weights.

This is the round's real finding. **Every pair among the six equity books breaches it:**

| pair | ρ (annualized) | overlap |
|---|---|---|
| `B-momentum` / `B4-tight-stop` | +0.998 | **75%** |
| `B-momentum` / `B2-hold-90` | +0.909 | **75%** |
| `B-momentum` / `B3-concentrated` | +0.983 | **60%** |
| `B-momentum` / `C-trend` | +0.909 | **45%** |
| `B-momentum` / `A-rotation` | **+0.497** | **45%** |
| `C-trend` / `A-rotation` | **+0.411** | **55%** |
| `B3-concentrated` / `C-trend` | +0.847 | 37% |

The last two rows are the point. `B-momentum`/`A-rotation` and `C-trend`/`A-rotation` sit at ρ of
+0.497 and +0.411 — comfortably inside round 6's +0.70 cap, which is exactly why round 6 seated the
first pair. They share **45% and 55% of book weight**. Correlation of per-window *returns* never
looks at what a card holds, and two books can differ in entry timing across historical windows while
converging completely once both are fully invested in the same trade.

They all hold MSFT, AMZN, NVDA, AVGO, TSM and SOXX. **After the cap, `H-trend-diversified` is the
only card in the field that can sit beside any equity book at all** (16% overlap, one shared name in
NVDA), which caps the desk at **two performance seats** — not a design choice, a consequence.

## 3. Fix 3 — correlation on annualized figures only, which vindicates round 6's flag

Round 6 excluded `c20-rotation` — the strongest hedge signature in the programme — on a raw round-4
correlation of **+0.917** to `B-momentum`, and flagged the number as suspect because round 5 showed
raw correlation across windows of differing length mostly measures scale.

Measured the way fix 3 specifies:

| pair | round-6 rule (max incl. raw r4) | round-7 rule (annualized only) |
|---|---|---|
| `c20-rotation` / `B-momentum` | **+0.917** | **−0.054** |
| `c20-rotation` / `H-trend-diversified` | +0.464 | −0.051 |

`c20-rotation` goes from "the most correlated card in the field" to "essentially uncorrelated", on
the same two frozen cards. It takes the hedge seat, at 0% holdings overlap with `B-momentum` and 21
live trades.

**Round 6 was right to flag it and right not to exempt it.** The rule was applied as written and the
answer was corrected by the next round's pre-registered fix, which is the sequence the protocol is
supposed to produce.

## 4. Fix 4 — could not be applied

*Score the live desk as its own matrix, weighted above any backtest matrix.*

This needs roughly 250 sessions. The desk has **55**. Applying it now would give a single quarter's
rotation more weight than every backtest combined, which is the opposite of what the fix was for.

**Deferred to the round after the desk reaches ~250 sessions**, around mid-2027. Until then the live
data is used as a *gate* (fix 1) and as *disclosure* (§6), not as a ranking input.

## 5. Seat 4, and a collision worth recording

With `B-momentum`, `H-trend-diversified` and `c20-rotation` seated, seat 4 went to the best remaining
hedge clearing every cap against all three:

| candidate | swing | vs `c20-rotation` | verdict |
|---|---|---|---|
| `c18-meanrev` | +4.86 | **ρ = +0.745** | rejected — over cap |
| `c11-breakout` | **+4.38** | ρ = +0.425 | **selected** |
| `c21-uncorrelated` | +3.72 | ρ = +0.865 | rejected |
| `c09-convex` | +2.79 | ρ = −0.008 | eligible, lower swing |

`c18-meanrev` is **the only card that made money live** (+2.44%) and it was rejected, because it
collides with `c20-rotation` at ρ = +0.745. Seating it would have meant dropping the hedge with three
times its swing. Recorded because it is the most tempting override in this round and it was not
taken: one 55-session result is not grounds to unseat a card on 27 windows of evidence, and if it
were, fix 4 would already be in force.

`c11-breakout` holds an open SPY position and no closed trades. It passes liveness on the position —
it entered and has not exited — but it is the marginal case in this round and should be re-checked
next time.

## 6. The book

| matrix | round 7 worst | median | round 6 worst | opening worst | `B-momentum` alone worst |
|---|---|---|---|---|---|
| r2 (8 regime windows) | **−0.68%** | +2.32% | −5.14% | −3.66% | −5.15% |
| r4 (6 regime windows) | −10.97% | +0.35% | −4.85% | −6.59% | +0.04% |
| r5 ladder (21 windows) | **−3.42%** | +2.32% | −5.09% | −5.21% | −15.54% |
| r5 bear (6 windows) | **−1.53%** | **+6.90%** | −5.75% | −5.94% | −10.64% |

**Veto count: 1** (r4 only; the veto fires above 1). **The selection stands.**

Round 7's book has the best worst-window of all three rosters on three of four matrices, and the best
bear-arm median by a wide margin (+6.90% against +0.78% and +2.19%). It is worse on r4, and it gives
up median against holding `B-momentum` alone everywhere — which is what a four-card book costs.

**Live, over the 55 sessions already run:** round 7's four return **−3.42%** equal-weight, against
round 6's −4.50% and the opening three's −4.15%. SPY returned +1.17% and QQQ −3.40%. All three
rosters lost money; this one lost the least and roughly matched QQQ.

## 7. The screen

The paper-desk page changed with the roster:

- **Both benchmarks are shown.** SPY alone was the flattering half of the answer for this field
  (round 5 §3). Every benchmark is now priced the same way over the desk's own sessions — the engine
  measures over the sessions it traded and reads SPY at +1.60% where the store reads +1.17%, and
  putting one of each in a list a reader compares side by side is the defect round 5's report caught.
  The engine's own figure remains what the tournament scores against.
- **A desk that has never traded is marked.** `c07-chop` and `c14-riskmanaged-wide` sat at 100% cash
  with zero trades for 55 sessions and the page rendered that identically to a card that traded to
  roughly flat. The badge reads the same condition fix 1 does, and says plainly that a flat return
  there means the desk did not participate.

## 8. What this is not evidence of

- **Still not out-of-sample.** Every matrix ends on or before 2026-02-13. The desk is the forward
  test; it is 55 sessions old and negative.
- **The overlap cap is measured on today's holdings**, one snapshot. Two cards that overlap now may
  not in three months, and vice versa. It is a better instrument than return correlation for this
  purpose, not a precise one.
- **Round 5's ranking and the live ranking still disagree**, at Spearman −0.539 over ten cards. Round
  7 changes who is on the desk; it does not resolve that, and nothing will until fix 4 can run.


---

## 9. Correction — the 55-session window was not representative

The desk was backdated to **2026-01-01** after this round was scored, giving 157 sessions instead of
55 and, more importantly, a proper out-of-sample stretch. Two claims above do not survive it.

### 9.1 The backtests did *not* order the field backwards

Every card was re-run over the genuine out-of-sample period — **2026-02-17 to 2026-08-18**, 127
sessions, everything after the 2026-02-13 design cutoff:

| Spearman: round 5's ladder rank vs forward result | value |
|---|---|
| on the 55-session slice (§6, as reported) | **−0.539** |
| on the full 127-session out-of-sample period, raw return | **+0.625** |
| same, on adjusted excess | **+0.536** |

The sign flips. The claim in §6 — *"the backtests ordered this field roughly backwards over the only
period no analyst could have studied"* — was true of the slice I measured and **false of the period
it was meant to describe**. It is withdrawn.

What the out-of-sample period actually shows, against SPY +12.84% and QQQ +19.20%:

| card | return | adj. vs SPY | adj. vs QQQ | max DD | exposure | trades |
|---|---|---|---|---|---|---|
| `B3-concentrated` | **+51.63%** | +43.80% | +39.91% | −28.50% | 61.0% | 6 |
| `A-rotation` | **+37.36%** | +28.67% | +24.36% | −16.87% | 67.7% | 29 |
| `B-momentum` | **+31.97%** | +24.67% | +21.06% | −25.23% | 56.9% | 11 |
| `B4-tight-stop` | +31.97% | +24.67% | +21.06% | −25.23% | 56.9% | 11 |
| `B2-hold-90` | +29.89% | +22.84% | +19.34% | −21.01% | 54.9% | 12 |
| `c20-rotation` | +5.30% | +0.31% | −2.17% | −11.94% | 38.9% | 32 |
| `c18-meanrev` | +2.02% | −0.70% | −2.06% | −3.84% | 21.2% | 56 |
| `C-trend` | +1.87% | −3.37% | −5.97% | −17.39% | 40.8% | 10 |
| `c11-breakout` | +0.90% | −1.28% | −2.37% | −1.35% | 17.0% | 2 |
| `c07-chop` | +0.22% | −0.44% | −0.77% | −2.04% | 5.2% | 3 |
| `c09-convex` | +0.10% | −0.13% | −0.24% | −0.36% | 1.8% | 2 |
| `c14-riskmanaged-wide` | 0.00% | 0.00% | 0.00% | 0.00% | **0.0%** | **0** |
| `c19-volatility` | −0.14% | −0.44% | −0.59% | −1.37% | 2.3% | 1 |
| `H-trend-diversified` | −3.14% | −4.70% | −5.48% | −5.21% | 12.2% | 7 |
| `c21-uncorrelated` | −5.28% | −6.77% | −7.50% | −7.63% | 11.5% | 7 |

The five cards round 5's ladder ranked highest are the five that finished highest, and they beat both
benchmarks by wide margins after exposure correction. **This is the first positive forward evidence
the programme has produced**, and it arrived only because the window got longer.

### 9.2 Round 7's own selection underperformed out-of-sample

| roster | out-of-sample, equal-weight |
|---|---|
| `B-momentum` alone | **+31.97%** |
| round 6's four | **+17.39%** |
| SPY | +12.84% |
| the opening three | +11.28% |
| **round 7's four (this selection)** | **+8.76%** |

Round 7's holdings-overlap cap removed `A-rotation` (+37.36%) and seated `H-trend-diversified`
(−3.14%) and `c11-breakout` (+0.90%) in its place. Over this period the cap cost roughly nine points
against round 6's roster and four against simply holding SPY.

That is what a diversification constraint does in a strongly trending market, and it was the
foreseeable price of the cap rather than a defect in it — §2 said the cap capped the desk at two
performance seats, and two performance seats is what underperformed. But it should be recorded
plainly: **on the only out-of-sample evidence available, round 7's roster is the worst of the three,
and the constraint that produced it is why.**

### 9.3 What still stands

- **The liveness gate.** `c14-riskmanaged-wide` took **zero trades in 127 out-of-sample sessions**,
  not merely 55. `c07-chop` took three, at 5.2% exposure. Dropping both was right.
- **The holdings overlap itself.** The six equity books really do hold the same names; the cap
  measures something real. What §9.2 shows is its cost, not that it is measuring wrongly.
- **Fix 3.** `c20-rotation` at ρ = −0.054 rather than +0.917 remains the correct measurement, and it
  returned +5.30% out-of-sample against `B-momentum`'s +31.97% — genuinely different behaviour.

### 9.4 For round 8

1. **Re-open the overlap cap as a *sizing* rule rather than an exclusion.** Removing the second-best
   card outright to hold two names fewer is a poor trade; capping combined weight in shared symbols
   is the same protection at a fraction of the cost.
2. **Fix 4 is now much closer.** 127 out-of-sample sessions is halfway to the ~250 the live matrix
   needs, and on this evidence it will *support* the backtest ranking rather than contradict it.
3. **The methodological lesson is mine, not the programme's.** I computed a rank correlation on 55
   sessions and reported its sign as a finding. It was inside the noise of a single rotation. A
   forward window shorter than roughly one full cycle should be reported as an observation and never
   as a correlation.
