# Round 2 — eight regimes, a metric that can see insurance, and a promotion rule that cannot count

**2026-08-21.** Twenty-seven cards — round 1's twenty-two carried forward unchanged, plus five new
challengers — traded across eight market regimes reaching back to 2007, including for the first time
**two genuinely directionless markets**. The benchmark is SPY in every window, price-only, bought at
the window's first open and held to its last close.

**170 card-window runs completed. 47 guard refusals, all honest. Zero lost to contention.**

| window | sessions | SPY | ran | barred |
|---|---|---|---|---|
| `q4-2018` | 65 | −20.05% | 23 | 4 |
| `covid` | 93 | −8.71% | 23 | 4 |
| `bear-2022` | 196 | −25.14% | 24 | 3 |
| `chop-2015` | 260 | **−0.04%** | 23 | 4 |
| `chop-2011` | 260 | **−0.05%** | 15 | 12 |
| `bull-2024` | 250 | +14.00% | 25 | 2 |
| `recent` | 249 | +20.62% | 26 | 1 |
| `gfc` | 356 | −56.23% | **10** | 17 |
| `13f-legal` | 188 | +14.60% | 1 | — |

The GFC field doubled from five cards to ten: every challenger, old and new, reaches 2007. **Not one
inherited card does**, for the second round running.

---

## 1. The finding that undermines this program's own machinery

`PROTOCOL.md` §6 promotes a strategy on a **positive median in two consecutive rounds**, on the
reasoning that one round is one draw. Round 2 shows that reasoning does not survive contact with how
the rounds are actually run.

Cards are frozen. Windows are fixed date ranges. The engine is deterministic. So re-running a
round-1 card on a round-1 window in round 2 does not sample anything — it **recomputes the same
number**. Verified across every shared window:

| card | window | round 1 | round 2 | difference | trades |
|---|---|---|---|---|---|
| `A-rotation` | recent | +95.2786% | +95.2786% | 0.0000 | 47 / 47 |
| `B-momentum` | covid | +22.9291% | +22.9291% | 0.0000 | 6 / 6 |
| `c04-riskmanaged` | bear-2022 | −6.5828% | −6.5828% | 0.0000 | 18 / 18 |
| `H-trend-diversified` | bull-2024 | +11.1267% | +11.1267% | 0.0000 | 13 / 13 |

Bit-identical, on twenty of twenty pairs checked — same returns, same trade counts, same trades.

**One clarification, because a reader comparing the raw JSON will see differences.** The figures above
are `ending_equity / starting_equity`, the card's actual economics. The **`total_return` field** does
differ between rounds for any card that filled on session one — `A-rotation` in `covid` reads −0.6520%
in round 1 and +0.4647% in round 2; `c04-riskmanaged` in `gfc` reads +0.8030% then +1.3806%. That is
not new data. It is D1 being fixed between the rounds: round 1's field was wrong, round 2's is right,
and round 2's now equals `ending/starting` exactly. Cards that did not fill on session one — like
`B-momentum` and `c01-meanrev` — are identical in both fields.

So the economics did not move at all. Only a previously-defective reported number moved, and it moved
onto the truth.

**So `B-momentum`'s +12.21% in round 1 and +12.16% in round 2 are not two pieces of evidence.** They
are one piece of evidence, recomputed, differing only because the median was taken over six windows
instead of four. The two-round rule as written counts the same measurement twice and calls it
confirmation.

The only genuinely new evidence round 2 produced for an incumbent is its performance in the windows
round 1 did not have — `q4-2018`, `chop-2015`, `chop-2011` and, for the ten cards that can reach it,
`gfc`. Everything else is arithmetic on numbers that already existed.

This does not invalidate round 2. It invalidates the promotion rule, which is fixed in §8.

---

## 2. Did the dominance view earn its place?

Round 1's ranking placed a convex payoff **17th of 18** while it was the best card in the crisis by
seventeen points. The metric could not distinguish a card that is flat because it is hedged from one
that is flat because it never traded. Round 2 ranks on median, worst window and hit rate together,
reports a Borda composite, and publishes a **Pareto frontier**.

**The frontier, on the six windows every ranked card shares:**

| card | median | worst | hit rate | Borda |
|---|---|---|---|---|
| `B4-tight-stop` | +11.06% | −4.05% | 67% | 4.00 |
| `B2-hold-90` | +16.31% | −5.15% | 67% | 4.33 |
| **`c09-convex`** | **+0.64%** | **−3.31%** | **67%** | **5.67** |
| `c05-trend` | −0.80% | −2.69% | 33% | 11.83 |

`c09-convex` was commissioned specifically to test whether the change was worth making, and it
reaches the frontier at **4th of 22 by Borda** on a mean capital exposure of **6.80%** over these six
windows (7.5% across all eight — the frontier is computed on the common set, so the two figures
describe different window sets and both are quoted where they apply). Under round 1's median-only
rule it would have placed 11th. The change did what it was meant to do.

**But the more interesting result cuts against it.** Across all eight windows:

| card | GFC adjusted excess | median | worst | capital exposure |
|---|---|---|---|---|
| `c04-riskmanaged` | **+26.10%** | −1.49% | −3.96% | 45.3% |
| `c08-generalist` | **+19.20%** | −0.59% | −5.63% | 58.6% |
| `c11-breakout` | **+17.37%** | +2.01% | −4.70% | 28.5% |
| `c09-convex` | +6.66% | +1.15% | −3.31% | 7.5% |

**The card explicitly designed to be convex was markedly less convex than three cards that were not
trying to be.** Its own author predicted a crisis payoff of +1.4 to +6.9 points and delivered +6.66%
— an accurate forecast of a small effect.

**Decomposing the GFC result shows what the metric is actually doing**, and an earlier draft of this
report got the direction wrong. `adjusted_excess = total_return + capital_exposure × |benchmark|`, so
in a falling window the second term is a **credit proportional to exposure**. Across all ten cards
that ran the GFC, on a $10,000 book:

| card | return | P&L | capital exposure | credit | adjusted excess |
|---|---|---|---|---|---|
| `c04-riskmanaged` | +1.38% | **+$138** | 44.0% | +24.72% | +26.10% |
| `c08-generalist` | −4.25% | **−$426** | 41.7% | +23.45% | +19.20% |
| `c11-breakout` | −4.92% | −$492 | 39.6% | +22.28% | +17.37% |
| `c05-trend` | −1.15% | −$115 | 19.3% | +10.88% | +9.72% |
| `c09-convex` | +1.03% | **+$103** | 10.0% | +5.63% | +6.66% |
| `c01-meanrev` | +0.83% | +$83 | 5.6% | +3.17% | +4.00% |
| `c07-chop` | −8.04% | −$804 | 20.6% | +11.56% | +3.52% |
| `c03-breakout` | −13.90% | −$1,390 | 21.7% | +12.19% | −1.71% |
| `c10-momentum` | −9.59% | −$959 | 5.1% | +2.88% | −6.71% |
| `c02-volatility` | −20.78% | −$2,078 | 15.8% | +8.89% | −11.89% |

**Capital exposure correlates with adjusted excess at Pearson r = +0.797 in this window.** The metric
rewards *more* exposure in a falling market, not less.

**Correction.** An earlier draft of this section claimed the adjustment "flatters any small book
against a large negative benchmark" and led with c08 losing $426 while scoring +19.20%. That framing
was wrong in both directions. c08's score is not an artifact: holding 41.7% of capital through a −56%
market and losing only 4.25% genuinely beats a passive position of the same size by 19.2 points, and
that is exactly what the metric was built to say. And c09's small book **suppressed** its score rather
than flattering it — at 10% exposure its credit is arithmetically capped near +5.6 in that window,
where a 44% book can reach +24.7.

**The real defects are two, and they pull in opposite directions.**

*The adjusted excess is not commensurable across exposure levels.* It is a correct per-card statement
measured against a passive position of that card's own size, but the resulting numbers have different
scales, and the ranking puts them on one axis anyway.

*The worst-window criterion favours small books.* A card holding 7.5% of capital structurally cannot
have a deep worst window. c09's −3.31% worst — the criterion it ranks 2nd on — is close to
unavoidable at that size, not evidence of defence.

So `c09-convex` reached the Pareto frontier mainly on the **consistency axes**, not on the exposure
credit. It is a real, cheap, well-behaved hedge sleeve whose author's cost and payoff forecasts were
both accurate. Both defects are fixed in §8.

**And measured per unit of capital deployed, the ordering in the crash reverses.** Dividing each
card's GFC adjusted excess by its capital exposure — the scale-free question — gives:

| card | adjusted excess | capital exposure | excess per unit of exposure |
|---|---|---|---|
| `c01-meanrev` | +4.00% | 5.6% | **71.0%** |
| `c09-convex` | +6.66% | 10.0% | **66.6%** |
| `c04-riskmanaged` | +26.10% | 44.0% | 59.4% |
| `c08-generalist` | +19.20% | 41.7% | 46.0% |
| `c11-breakout` | +17.37% | 39.6% | 43.8% |

**Per unit at risk, the small books were not worse in the crash — two of them were the best in the
field.** That is the opposite conclusion from the raw column beside it, and it is the sharper answer
to whether c09 earned its frontier place: at its own size, it defended better than the large books
did at theirs. What remains unsettled is whether that scales — a 7.5% book cannot show whether the
same mechanism holds at 30%, which is why §8 asks for exactly that test.

The aggregate ranking barely moves under this measure (Spearman ρ = 0.922 on the six-window set,
0.977 across all eight), because the median already suppresses any single window's influence. **The
bias is real but concentrated in single-window comparisons**, which is precisely where this round's
most-quoted numbers live.

---

## 3. The chop windows, and whether they were worth the compute

The headline: **the predictions can now be scored.** `c07-chop` was built for these windows and
delivered in both — **+6.00%** in `chop-2015` and **+1.93%** in `chop-2011`. It also named `covid` as
its expected worst window before trading, and `covid` was its worst at **−15.57%**. A correct
pre-registration, on a regime round 1 could not evaluate at all.

But the two windows disagree sharply for several cards, and that is itself the finding:

| card | chop-2015 | chop-2011 |
|---|---|---|
| `c10-momentum` | **−6.90%** | **+2.62%** |
| `c11-breakout` | −1.94% | **+6.75%** |
| `c08-generalist` | −5.63% | +2.72% |
| `c07-chop` | +6.00% | +1.93% |
| `c05-trend` | −2.46% | +4.46% |

Five of the six cards eligible for both did **better** in the higher-volatility chop window than in
the quieter one, several changing sign — 6 of the 15 cards that ran both flip sign between them.

**And the cross-window correlations say chop is largely not a distinct regime at all.** Ranking cards
by adjusted excess and correlating the windows against each other:

| pair | Spearman ρ |
|---|---|
| `chop-2011` vs `bear-2022` | **0.732** |
| `chop-2015` vs `covid` | **0.610** |
| `chop-2011` vs `chop-2015` | **0.461** |

**Each chop window resembles a window from the existing matrix more than it resembles its own
sibling.** And the single most redundant pair in the whole matrix is not a chop pair at all —
`q4-2018` and `bear-2022` correlate at **0.734**, higher than anything the chop windows produced. Set that beside `c07`'s design memo — written before any of this ran — which measured its
mean-reversion edge as *larger* in trending and grinding-bear windows than in either chop window, and
located the real failure at crash speed rather than directionlessness.

The honest conclusion is that the two chop windows mostly **re-measured variance the matrix already
carried** under `bear-2022` and `covid`, rather than opening a new axis. They were still worth adding
— they scored predictions that had gone unscored, and **7 of 8 explicit chop or whipsaw calls across
five memos were directionally correct**, an 88% hit rate on pre-registrations that round 1 could not
evaluate. But the case for keeping both in round 3 is weak, and §8 acts on that.

A dedicated analysis is in [`analysis/chop.md`](analysis/chop.md).

**The A family is where the chop windows bit hardest.** A concentrated semiconductor rotation book
went roughly **−7% to −9%** in `chop-2015` and **−8.5% to −11.6%** in `q4-2018`, against **+58% to
+150%** in `recent`. That is one strategy, measured across regimes, and the pair is the whole argument
for a matrix: on `recent` alone it is the best thing in the program, and across eight windows
`A-rotation` ranks 20th of 22.

---

## 4. The cleanest result of the round

`c11-breakout` was commissioned because round 1's breakout card built a nine-symbol book entirely
from US sector ETFs — later measured at ~0.58 mean pairwise correlation, nine positions expressing
close to one bet. c11 was told to build one whose diversification is real, chose `SPY TLT GLD LQD`,
and measured **0.13 mean off-diagonal correlation** before submitting.

Same discipline, same eight windows, two universe philosophies:

| card | median (8 windows) | worst | GFC | chop-2011 |
|---|---|---|---|---|
| `c11-breakout` (diversified) | **+2.01%** | **−4.70%** | **+17.37%** | **+6.75%** |
| `c03-breakout` (sector) | **−3.13%** | −8.32% | −1.71% | −1.35% |

A **5.1-point median gap**, a worst window half as deep, and 6 of 8 windows won head-to-head. This is
the most controlled comparison the program has produced, because the discipline and the rules are
close and the universe is the variable that changed.

**A correction to an earlier draft of this report, which claimed c11 had the best median of any
challenger.** It does not: `c07-chop` posts **+2.72%** against c11's +2.01%. What c11 has is the best
*worst window* — −4.70% against c07's −15.57%, three times shallower. The claim holds on robustness,
not on raw median, and the distinction is exactly the one §2 says the ranking exists to make.

Two caveats, both real. The margin is well inside the ordering noise floor discussed in §5, so it is
suggestive rather than decisive on its own.

And c11's own author flagged, before the run, that low *return* correlation does not guarantee
independent *trade timing*. Checking the trade logs: **34% of its 29 consecutive-entry gaps fall
within 20 days of each other**, clustering at macro turning points — the 2011 debt-ceiling crisis,
May 2015, the August 2024 rally open, October–November 2007. The remainder spread 21 to 199 days
apart. So the diversification is real but partly a shared macro read rather than four independent
bets, which is precisely what its author warned it might be.

Its pre-registration was wrong, though: it named `chop-2011` as its expected worst window, and that
was its **second-best** at +6.75%, on a TLT position that rode the 2011 flight to duration for
+25.32%. Its actual worst was `bull-2024`, never mentioned as a risk.

---

## 5. The variants, and a rule that would promote noise

`c08-generalist` was given the hardest mandate: positive adjusted excess in as many windows as
possible. It managed **1 of 6** on the common set and 3 of 8 overall. The mandate failed, plainly. Its
memo had already disclosed that perturbing its 50/200 periods moved its own hit-rate estimate from
3/8 to 5/8 — an instability in exactly the quantity it was optimising, disclosed before the run rather
than discovered after.

That failure matters beyond one card, because round 1 found the same shape: cards with a strong median
had enormous spread, cards with tight spread had a median near zero, and nobody had both. Round 2
adds twenty-two more observations and does not overturn it.

**And here the protocol contradicts itself.** §6 replaces a base strategy with a variant that beats it
on median in two consecutive rounds. Mechanically:

| variant | vs `B-momentum` r1 | vs r2 | margin |
|---|---|---|---|
| `B2-hold-90` | +17.83 vs +12.21 | +16.31 vs +12.16 | +5.62, +4.15 |
| `B3-concentrated` | +15.61 vs +12.21 | +13.89 vs +12.16 | +3.40, +1.73 |

Both clear the rule as written. Both margins are **far inside** the noise floor §7 of the same
document insists on — round 1 measured a pure-ordering artifact at up to 12.5 points in a single
window, against an earlier study's 53.9-point spread at σ = 21.2. And per §1, the two rounds are not
independent anyway.

**So the promotion rule would replace Strategy B with `B2-hold-90` on evidence the protocol elsewhere
says is meaningless.** No such promotion is made. The rule is amended in §8.

---

## 6. The engine fixes, verified on real data

D1 and D2 were found during round 1, worked around in the scorer, and fixed in the engine between
rounds — never during one. Both are now confirmed against all 170 round-2 runs:

- **D1:** `max |total_return − ending_equity/starting_equity| = 0.000000pp`. Exact, everywhere.
- **D2:** the engine's new `capital_exposure` and the scorer's independent trade-log reconstruction
  agree to within **1.21pp** at worst. The residual is an off-by-one in which sessions `bars_held`
  spans; the engine is right by construction, so the scorer now prefers the engine's figure and keeps
  the reconstruction as a cross-check and for round-1 files, which predate the field. Re-scoring moved
  no card by more than 0.1pp and changed no rank.

A regression test for D1 was written first and confirmed to fail against the unfixed code. Fixing D1
also introduced a denominator bug of its own — the alignment point entered `exposure`'s mean, turning
a card held on all 250 sessions into 250/251 — which is corrected and pinned by a test asserting
`exposure × sessions` is a whole number.

**A third defect recurred and cost the round's first attempt.** D3 (a concurrent reader surfacing as
an ordinary card failure) was triggered by my own error: a run launched detached, then killed by
killing `python.exe` rather than the bash loop driving it, so the loop spawned a replacement and
fought a second run for five windows — **135 card-runs, zero results**. It is invisible at a glance,
because `0 run files, 27 FAILED lines` is exactly what a legitimately ineligible field looks like and
the contention error is formatted like an honest guard refusal. `run_round.sh` now refuses to start
while another run is alive.

---

## 7. The 13F track

`c06-13f-momentum` remains **unranked by construction**, and this round the toolchain enforces that
rather than relying on a reader. With `universe_knowable_from: 2025-11-14` declared, all eight main
windows are refused with reasons naming the violation, and the six run files the engine produced
anyway are flagged as basket lookahead:

> `universe knowable only from 2025-11-14, window starts 2020-02-19` — this is basket lookahead, not
> an ordinary eligibility mismatch; `c06-13f-momentum` is reported as unranked.

In its one legal window it returned **+17.79% against +14.60%**: +3.19 raw, **+10.99 adjusted**, 56
trades at 46.6% capital exposure, worst drawdown −12.49%.

Note carefully that this is **the same number round 1 produced (+11.03)**, recomputed — same card,
same window, same data. It is not a second observation. Per §1, the 13F result stands at exactly one
draw, as it did before.

`D-13f-newbuys` clears **no window in either round**, including the 13F window built for it.

---

## 8. What changes for round 3

1. **Fix the promotion rule.** Promotion must require positive median **on windows the previous round
   did not use**, not on a re-scored superset. As written it counts one measurement twice. And every
   promotion comparison must carry a noise-floor condition: a margin inside the ordering artifact is
   not a result, whatever the rule says.
2. **Make the ranking commensurable across exposure levels, and test convexity directly.** §2 shows
   `adjusted_excess` scales with exposure — r = +0.797 against capital exposure in the GFC — so a 7.5%
   book is capped near +5.6 where a 44% book reaches +24.7, and the ranking compares them on one axis
   anyway. Meanwhile the worst-window criterion pushes the other way, handing a small book a shallow
   worst window for free.

   Three concrete changes: report **realised P&L** beside every adjusted figure so the decomposition
   is visible without recomputing it; add **excess per unit of capital deployed** as a reported column
   and a ranking option; and **flag any card whose exposure differs from the field median by more than
   2×**, because its adjusted excess is not on the same scale as the rows around it. The Pareto
   section should state that its worst-window axis favours low-exposure books.

   Then test convexity directly, which this round could not: the same mechanism at 3× the capital
   exposure. At 7.5% exposure `c09-convex` cannot demonstrate convexity or its absence.
3. **Drop `chop-2011`, and accept that windows cannot be pre-screened.** `tools/window_redundancy.py`
   now measures this properly, reproducing §3's figures within 0.001. Two results, and the second is
   the important one.

   The measured matrix says `chop-2011` is **the most entangled window in the matrix** — ρ = 0.731
   with `bear-2022` and 0.649 with `q4-2018`. Drop it. (The single most redundant *pair* is actually
   `q4-2018`/`bear-2022` at **0.734**, which no one predicted; a greedy solver would drop `bear-2022`
   as the vertex touching the most edges, but a canonical regime is worth keeping and `chop-2011`
   duplicates it anyway.) At the other end, `recent` has a maximum correlation of just **0.150** —
   by far the most distinctive window in the matrix, and the one carrying the most independent
   information.

   **The proxy for choosing new windows does not work, and that is worth more than the drop list.**
   Scoring windows by their SPY signature — return, volatility, drawdown, fraction above the 200-day
   average, path efficiency — agrees with measured redundancy on **1 of 8 windows**. The clearest
   failure is this round's own: by SPY shape the two chop windows are each other's nearest neighbour
   by a wide margin, looking like twins. Measured by how the field actually ranked in them they are
   the *weakest* of the three pairs quoted in §3. **A signature screen would have recommended keeping
   both — precisely the mistake round 2 made.**

   So there is no cheap way to know what a window measures before running it. The workable procedure
   is: use the signature only to rule candidates *in* for consideration, run a **small subset** of the
   field in a candidate window, measure its correlation against the existing set, and only then commit
   the full round's compute. A window's label predicts nothing; only the field's behaviour in it does.
4. **Retire `D-13f-newbuys`.** Zero trades in every window of two consecutive rounds is the
   protocol's own retirement condition, and it is now met.
5. **The walk-forward still has not started.** No calendar time passed between rounds 1 and 2, so no
   unseen data exists and the design cutoff could not advance. Round 3 should wait for real elapsed
   time, or it will again be a re-measurement wearing a round's clothing.

### Library changes made

Promotion to `candidates/` requires clearing the gate with a positive median, which these did on
genuinely new windows: **`c07-chop`, `c09-convex`, `c10-momentum`, `c11-breakout`** are promoted from
challenger to candidate. `c01-meanrev` was positive in both rounds but, per §1, on overlapping
evidence; it is promoted to `candidates/` on round 1's result and **held there**, not advanced to
`base/`.

No card is promoted to `base/` and none is demoted from it. `A3-no-target`, `c02-volatility`,
`c03-breakout`, `c04-riskmanaged` and `c05-trend` posted negative medians in both rounds, but §1
applies to them equally — that is one negative measurement counted twice, not two.

---

## 9. What actually produced the numbers

Every figure above is a return against a benchmark. None of them says whether the return came from
ninety small edges or from one position held through the right fortnight, and those are different
strategies wearing the same number. `tools/attribution.py` decomposes each result exactly — every
trade's `pnl / starting_equity` is its share of the card's return, and the shares sum to the return,
so nothing here is modelled or allocated. Full output in
[`analysis/attribution.md`](analysis/attribution.md); per-card detail in [`reports/`](reports/).

Four things it changes about how this round should be read.

**The round's largest number is four trades.** `A3-no-target`'s +149.56% in `recent` came from MRVL
+155.8% (45.2% of the card), INTC +140.7% (40.2%), AMD +135.5% (38.7%) and MU +69.3% (19.3%). A3 is
the variant that removes the base card's 20% take-profit, and matching those four against
`A-rotation`'s own log at the same entry dates gives the cap's cost directly:

| symbol | `A-rotation` (capped) | `A3` (uncapped) | difference |
|---|---|---|---|
| MRVL | +16.23%, 18 bars, `target` | **+155.82%**, 83 bars, `rule` | +$4,052 |
| INTC | +26.67%, 4 bars, `target` | **+140.75%**, 45 bars, `rule` | +$3,259 |
| AMD | +28.02%, 9 bars, `target` | **+135.53%**, 72 bars, `rule` | +$3,066 |
| MU | +25.07%, 18 bars, `target` | **+69.28%**, 63 bars, `rule` | +$1,233 |

Gross, the cap cost **$11,610**. But capping early freed slots that `A-rotation` redeployed into other
trades worth about **$4,668**, so the **net** cost was roughly **$6,942** — the naive reading
overstates it by 40%. This is the clearest measurement the variant programme has produced, and it
still sits beside A3's negative median across six windows.

**Several headline results are marks, not money.** A position open at the window's close carries an
unrealised `pnl`. `B3-concentrated`'s `recent` result is **+53.54% unrealised — more than its entire
return**, so its realised trades net negative; `B-momentum` and `B4-tight-stop` each carry +35.58%
unrealised in the same window, all on the same open MRVL and AMD positions. `B2-hold-90`, whose
90-day cap forced MRVL closed at **+119.39%** four weeks before the window ended, is the one B card
whose comparable gain is real. `A3`'s `bull-2024` result is the starkest case: **+23.36% from two open
positions against realised trades netting −18.04%.**

**Beating the benchmark is not the same as defending.** `c11-breakout` beat SPY by **23.89 points** in
`bear-2022` — on **one GLD trade**, at 11.9% capital exposure. That is absence, not defence, and only
attribution distinguishes them. The contrast is its own `gfc`, where it held 39.6% and still beat the
benchmark by 51 points. `c04-riskmanaged`'s `gfc` is the clearest case of genuine defence, and the
trade log confirms the mechanism rather than assuming it:

| leg | contribution | trades |
|---|---|---|
| GLD | **+3.15%** | 8 |
| TLT | **+1.93%** | 9 |
| SPY | −1.54% | 5 |
| EFA | −2.16% | 6 |

Equities lost money; Treasuries and gold more than paid for them.

**Stops behave systematically, and tighter is not safer.** Across the field, the two tight-stop
variants roughly **tripled** their stop-outs against their bases — `A4` fired 30 against `A-rotation`'s
9, `B4` fired 13 against `B-momentum`'s 4 — without improving fill quality. And the slippage is large
because a stop is evaluated on the previous close and filled at the next open: `G-volatility`'s COIN
stop realised **−22.81% against a nominal 10%**, a 12.81-point gap, with a **mean gap of 4.89 points**
across its 14 stops. Meanwhile four cards — `c04-riskmanaged`, `c05-trend`, `c09-convex` and
`c10-momentum` — **never fired a stop at all** across every window they ran.

One footnote that bears on §2's argument: `c09-convex`'s GFC result came from 13 trades, all closed by
rule, only four of them winners and the largest worth +2.05%. It is a steady drip of small TLT and GLD
round trips, not a few large flight-to-quality bets — which is a reason to be careful with the word
"insurance" for it, whatever its per-exposure score.

---

## 10. What this round does not show

- **It is not an out-of-sample round.** No calendar time elapsed, so the design cutoff stands at
  2026-02-13 and nothing here is data nobody had seen. Round 2 widened the regimes; it added no new
  information about the future.
- **Analysts knew the matrix.** Every round-2 card was designed knowing a crisis window, two chop
  windows and a selloff were coming. That is a mild but real form of fitting to the test.
- **`bull-2024` and `recent` overlap every card's design period** and measure fit, not generalisation.
- **The GFC comparison is still ten cards against nothing.** No incumbent can enter it, so the
  challengers' crisis results are not evidence they beat the incumbents there.
- **One draw per regime**, except chop, where the two draws disagreed.
- **The single-name cap is raised to 100%**, so drawdowns exceed what the persona's real 25% mandate
  would permit; **no dividends anywhere**; **cash earns nothing**, which understates the true cost of
  a defensive book — `c09-convex`'s author noted 85–90% of its book sits in zero-cost cash.
- **Round 1's ρ = 0.162 problem is still not addressed.** Two rounds have now measured the same cards
  against overlapping windows. Whether this program's rankings predict anything remains untested, and
  will stay untested until real time passes.

---

Per-card reports are in [`reports/`](reports/), the chop analysis in
[`analysis/chop.md`](analysis/chop.md), frozen cards in [`cards/`](cards/), and the design memos —
written before any result existed — in [`memos/`](memos/).

---

## Restated 2026-08-21 — `DEFECTS.md` D4

Every run file in this round was **re-run and overwritten** after `DEFECTS.md` D4 was fixed. Rule
evaluation previously read a 400-day trailing window, an undocumented default parameter value, which
left recursive indicators (`ema`, Wilder `rsi`) carrying a seed error of roughly 1.8e-5; it now reads
full history.

**Across all three rounds, 330 runs were restated and 3 results moved** — the same card in the same
window in each round, `C-trend` in `covid`, by **0.065 percentage points** of starting equity. One
signal flipped: `TSM` on 2020-05-14, where `ema(20)` and `ema(50)` were crossing and 1.8e-5 decided
which was above the other. `C-trend`'s covid excess moves from +24.5% to +24.6%.

**No ranking, promotion, frontier or conclusion in this report changes.** The figures below are the
restated ones. The scoring aggregates (`tournament*.json`) were regenerated at the same time so they
cannot describe the pre-restatement field.
