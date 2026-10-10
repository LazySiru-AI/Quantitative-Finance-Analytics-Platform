# Round 1 — twenty-two strategies against five regimes

**2026-08-20.** Six analysts designed one strategy each against data through 2026-02-13, under an
information quarantine on the previous tournament's results. Their six cards were frozen in git
before any backtest ran, then traded alongside sixteen inherited library cards across five market
regimes reaching back to 2007 — including a 56% bear market, a crash, and a grinding rate-driven
decline.

84 card-window runs completed. Every window reconciled exactly against the eligibility matrix
computed beforehand, and no card was lost to store contention.

| window | dates | sessions | SPY | cards run | barred |
|---|---|---|---|---|---|
| `gfc` | 2007-10-09 → 2009-03-09 | 356 | **−56.23%** | 5 | 17 |
| `covid` | 2020-02-19 → 2020-06-30 | 93 | −8.71% | 18 | 4 |
| `bear-2022` | 2022-01-03 → 2022-10-12 | 196 | −25.14% | 19 | 3 |
| `bull-2024` | 2024-08-21 → 2025-08-20 | 250 | +14.00% | 20 | 2 |
| `recent` | 2025-08-21 → 2026-08-18 | 249 | +20.62% | 21 | 1 |
| `13f-legal` | 2025-11-17 → 2026-08-18 | 188 | +14.60% | 1 | — |

All 54 barred runs were honest `GuardFailed` eligibility refusals. Zero were store contention.

---

## 1. The finding that arrived before any trade was simulated

**Not one inherited card could be tested against the Global Financial Crisis.**

Every A variant is blocked by AVGO, first listed 2009-08-06. Every B variant by NOW, 2012-06-29.
`C-trend` and the 13F card by META, `H-trend-diversified` by INDA. The entire field carried over from
the previous tournament was built on a semiconductor and AI universe that **did not exist in 2008**,
so the worst market in living memory is structurally unavailable to it.

Only the five newly-designed challengers reached that far back, and they did so because the brief
told them in advance that a narrow recent universe would cost them eligibility. Every one of them
spent that freedom on history rather than on recent winners: index and sector ETFs, Treasuries, gold.
Nothing younger than 2004 in five of the six books.

This is the eligibility gate working exactly as intended, and it produced a fact about the inherited
library that no amount of backtesting the old windows would have revealed.

`D-13f-newbuys` clears **no window at all**, including the 13F window built specifically for it: its
`sma(200)` needs roughly 239 bars of prior history and SNDK, first bar 2025-02-13, falls about ten
weeks short even there.

---

## 2. The ranking

Ranked on median exposure-adjusted excess across the **four windows every ranked card shares**
(`covid`, `bear-2022`, `bull-2024`, `recent`). The GFC is excluded from the ranking because no
incumbent could run it; it is reported separately in §3.

Both inputs are corrected — see §6. Returns are `ending_equity/starting_equity − 1`, not the runner's
defective `total_return`; exposure is capital-weighted from the trade log, not the runner's
session-presence figure.

| # | card | median adj. excess | worst | IQR | hit rate | trades | cap. exposure |
|---|---|---|---|---|---|---|---|
| 1 | `B2-hold-90` | **+17.83%** | −5.15% | 12.32 | 75% | 48 | 36.4% |
| 2 | `B3-concentrated` | +15.61% | −7.75% | 26.45 | 75% | 36 | 40.8% |
| 3 | `G-volatility` | +12.66% | −19.27% | 17.74 | 67% | 130 | 19.7% |
| 4 | `B-momentum` | +12.21% | −5.15% | 15.35 | 75% | 47 | 37.8% |
| 5 | `A2-cash-headroom` | +11.42% | −22.78% | 21.26 | 75% | 158 | 50.8% |
| 6 | `B4-tight-stop` | +11.12% | −4.05% | 13.77 | 75% | 49 | 36.7% |
| 7 | `A1-alpha-order` | +9.70% | −29.97% | 30.84 | 75% | 129 | 52.7% |
| 8 | `B1-with-target` | +8.28% | −5.15% | 24.03 | 50% | 52 | 28.9% |
| 9 | `C-trend` | +4.99% | −7.21% | 22.92 | 50% | 41 | 30.5% |
| 10 | `A-rotation` | +3.23% | −27.41% | 29.37 | 75% | 121 | 52.9% |
| 11 | `H-trend-diversified` | +3.10% | −8.75% | 8.85 | 75% | 36 | 25.6% |
| 12 | `A4-tight-stop` | +2.45% | −27.82% | 30.20 | 75% | 123 | 52.6% |
| 13 | `c01-meanrev` | +0.62% | −6.46% | 3.48 | 75% | 73 | 11.3% |
| 14 | `c05-trend` | −0.07% | −2.69% | 3.37 | 50% | 30 | 20.5% |
| 15 | `A3-no-target` | −0.79% | −27.41% | 47.38 | 50% | 83 | 49.4% |
| 16 | `c02-volatility` | −0.92% | −4.41% | 2.74 | 25% | 29 | 37.1% |
| 17 | `c04-riskmanaged` | −2.51% | −2.63% | 1.70 | 25% | 55 | 52.6% |
| 18 | `c03-breakout` | −5.40% | −8.25% | 3.29 | 25% | 40 | 40.2% |

**Unranked**: `E-asymmetric` (+21.21% on `recent` alone — one draw, not a result), `F-fastrev` (two
windows, 7.3% capital exposure — a satellite sleeve judged against a fully-invested benchmark, which
is the wrong comparison), `D-13f-newbuys` (no windows), and **`c06-13f-momentum`** — see §5: all four
windows it ran begin before the filings its universe was derived from.

> **A correction made while writing this report, and the tooling gap behind it.** `c06-13f-momentum`
> was initially listed in the table above at rank 15, on a median of −0.60% computed from `covid`,
> `bear-2022`, `bull-2024` and `recent` — every one of which begins before the 2025-11-14 filing date
> its universe came from. Those are not results. They are the same basket-lookahead error the
> previous tournament made and documented, reproduced here two sections after §5 warns against it.
>
> `scorecard-full.json` still marks the card `"ranked": true`, and that is a real limitation rather
> than a slip. `tools/windows.py` tests whether a card's *symbols* have enough price history, which
> is a question about data. Whether a card's *basket* was knowable is a question about provenance,
> and nothing in the toolchain models it — the `13f-legal` window exists only because a person knew
> to create it. Round 2 should carry a per-card `universe_knowable_from` date and refuse to score any
> window starting before it.

**The challengers lost.** Five of the six occupy places 13, 14, 16, 17 and 18 of 18. The inherited B
family took four of the top six. On the metric this round chose, that is the result, and it should
not be narrated away.

**But the B family's best window is an artifact, and it should not be read as risk management.**
Every B card scores +26.68% to +27.61% adjusted excess in `covid` — and **not one of them held a
single position before 2020-03-30**, after the bottom. Four of the five share that exact date as
their first trade. Their entry rule, `ema(20) crosses_above ema(50) and close > sma(200)`, physically
cannot fire during a crash. They scored well by being absent while the benchmark fell and arriving
for the recovery, which is the arithmetic of the metric rather than a decision the strategy made.
`covid` is one of only four windows in the ranking, so this materially lifts every B placement.

---

## 3. What the ranking hides

**The five challengers have the five lowest cross-window spreads in the field** — IQRs of 1.70 to
4.50 points, against 8.85 to 47.38 for every incumbent. Their worst windows run −2.63% to −8.25%;
the A family's worst run −22.78% to −29.97%.

The challengers are consistent and mediocre. The incumbents are volatile and higher-median. Those are
different bets, and the median alone does not distinguish them.

The GFC makes this concrete. Only challengers could run it:

| card | return | benchmark | adj. excess | capital exp. | session exp. | trades | max DD |
|---|---|---|---|---|---|---|---|
| `c04-riskmanaged` | **+1.38%** | −56.23% | **+26.03%** | 43.8% | 97.2% | 28 | −8.81% |
| `c05-trend` | −1.15% | −56.23% | +9.62% | 19.2% | 46.1% | 20 | −6.65% |
| `c01-meanrev` | +0.83% | −56.23% | +4.00% | 5.6% | 16.9% | 11 | −4.22% |
| `c03-breakout` | −13.90% | −56.23% | −1.71% | 21.7% | 48.6% | 11 | −14.29% |
| `c02-volatility` | −20.78% | −56.23% | −11.89% | 15.8% | 33.4% | 10 | −21.18% |

`c04-riskmanaged` finished a 56% bear market **up 1.38%**, with 43.8% of capital deployed across 28
trades — it rotated into the legs that were trending, Treasuries and gold, as equities broke down. It
did not abstain. `c01-meanrev` also finished positive, but on 5.6% capital exposure across 11 trades,
nine of them clustered before December 2007: that is absence, not defence, and the two should not be
read the same way.

**`c04` ranks 18th of 19.** Its per-window adjusted excess is +26.03% / +3.71% / −2.44% / −2.59% /
−2.63% — it costs roughly two and a half points in every ordinary window and pays twenty-six in a
catastrophe. That is the payoff profile of an insurance policy, and **ranking by median structurally
places insurance last.**

This is a real limitation of the metric, not a defence of the card. One crisis window is one draw,
and a single 26-point payoff is not proof of a repeatable hedge. But a program built to survive
volatility should not use a ranking that cannot see the difference between a card that is flat
because it is hedged and a card that is flat because it never traded. §8 records this as the first
amendment for round 2.

---

## 4. The variants answered almost nothing

Eight variants, each isolating exactly one decision against its base. **None separated from its base
by a margin that clears the noise floor.**

The floor is empirical: `A1-alpha-order` differs from `A-rotation` *only* in the order its universe
is written, so whatever gap it shows is pure ordering artifact. It shows **+6.47 points of median**.
A prior sensitivity study re-running one identical card under twelve orderings measured a 53.9-point
spread, σ = 21.2. Against either estimate, every variant margin in this round is noise:

| variant | vs base | margin | verdict |
|---|---|---|---|
| `A1-alpha-order` | +9.70 vs +3.23 | +6.47 | **the control — this gap is the artifact** |
| `A2-cash-headroom` | +11.42 vs +3.23 | +8.19 | inside the floor |
| `A4-tight-stop` | +2.45 vs +3.23 | −0.78 | inside |
| `A3-no-target` | −0.79 vs +3.23 | −4.02 | inside |
| `B2-hold-90` | +17.83 vs +12.21 | +5.62 | inside |
| `B3-concentrated` | +15.61 vs +12.21 | +3.40 | inside |
| `B4-tight-stop` | +11.12 vs +12.21 | −1.09 | inside |
| `B1-with-target` | +8.28 vs +12.21 | −3.93 | inside |

**The control variant produced a larger gap than five of the seven real variants.** That is the
cleanest available demonstration that this round cannot resolve the questions the variants were
written to ask on medians. `B2-hold-90` topping the ranking is not evidence that a 90-day cap beats
180.

**Two comparisons do clear the floor, and only at the window level.** Measured per window rather than
on medians, `A1`'s pure-ordering artifact ranges 0.59 to 12.48 points — tighter than the library's
σ = 21.2 estimate, and a better empirical floor. Against it, exactly two of twelve A-family
window-comparisons clear:

- **`A3-no-target` in `recent`: +69.24 points.** Almost entirely one trade — MRVL, held 83 bars,
  **+155.8%**, which the base card's 20% take-profit would have cut. That is a real demonstration of
  the mechanism B's author described, from a single observation. It is also why A3's median is
  *negative* and it ranks 15th: the same removed cap costs it in every other window.
- **`A2-cash-headroom` in `recent`: −22.16 points.** Dilution across four slots costs the variant in
  the strongest trend window — evidence pointing the opposite way from A2's better median.

**Three cards were bit-for-bit identical to their base, meaning the variant was not tested at all:**

- `A3-no-target` vs `A-rotation` in `bear-2022` — the same 22 trades at the same prices, the same
  $6,672.54 ending equity, and all 22 exits `rule` in both. The take-profit never fired.
- `A4-tight-stop` vs `A-rotation` in `bull-2024` — the same 39 trades and the same P&L. The tighter
  8% stop merely **relabelled 8 exits from `rule` to `stop` without changing a single fill.**

That last one is the most instructive result in the variant programme. Where A4's tighter stop did
bind, it was worse: on the identical AMD position in `covid` it realised **−17.00% against the looser
stop's −11.91%**, because a stop evaluated on the previous close and filled at the next open does not
cap a loss where it is set — it just leaves earlier and sometimes lower. `B4-tight-stop` shows the
same thing from the other side: its 8% stop **more than doubled stop-outs, 10 against 4**, without
improving fill quality, and its two worst previous-close overshoots are the largest in the B family.

**`B1-with-target` produced the round's most careful answer, and it is genuinely unresolved.** B's
author rejected take-profits on measured grounds, arguing a cap "amputates the winners that carry a
momentum book." Matching all 15 of B1's target exits against B-momentum's same-symbol, same-entry
positions splits cleanly in two:

- On the **4 positions both cards fully closed**, the target won all four, protecting roughly 26
  points on average that the uncapped version gave back before its eventual rule exit — including one
  that round-tripped into a **−1.24% loss** after B1 had locked in **+30.79%**.
- Against B-momentum's **still-open** positions the picture inverts, most sharply MRVL and AMD in
  `recent`, whose unrealised marks of **+130.65%** and **+107.78%** dwarf B1's locked-in +31.98% and
  +29.48%.

Closed trades favour the target; open trades favour letting it run. The author's claim is neither
confirmed nor refuted, and the difference rests on positions whose outcome is not yet known. That is
the honest answer, and it is worth more than a ranking that would have declared one of them a winner.

Variants are not the problem; four windows are. Resolving a 5-point effect against a 21-point noise
floor needs far more windows, and §8 addresses that.

---

## 5. The 13F track

`c06-13f-momentum` was built as you asked: institutional filings select the universe, a price rule
times the entry. It is **unranked by construction**, because a 13F-derived basket may only trade
windows beginning after the filing date it came from — 2025-11-14 — and the engine cannot rotate a
universe mid-window.

In its one legal window it returned **+17.79% against a +14.60% benchmark**: +3.19 points raw,
+11.03 adjusted, on 56 trades at 46.3% capital exposure, worst drawdown −12.49%.

A modest genuine beat, on one draw. Its numbers in `covid`, `bear-2022` and `bull-2024` are
**basket lookahead** — a portfolio chosen with knowledge of which names would work, run over windows
predating the documents — and are recorded as unmeasured, not as results. That is the same error the
previous tournament made and documented, and it is not repeated here.

**The structural finding matters more than the return.** Working from all 14 managers at
`as_of=2025-11-14`, the analyst found 3,237 new-and-increased position rows, of which 134 resolved to
a tradeable ticker through the ledger-scoped CUSIP bridge (~4.1%), of which 85 had bars. The
high-conviction survivors collapsed to **eight mega-cap technology and semiconductor names** — the
consensus trade nearly every growth-oriented filer already held.

So the honest reading is that this is a momentum card with a rigorously-derived but conventional
universe, and that the 13F step's contribution is not separately measurable here. That is not a
failed assignment; it is the fourth independent time this project has found 13F unusable as a signal
within this engine, and the first time the pipeline itself was built cleanly enough to say why.

---

## 6. Two defects in the engine, found mid-round

Both are recorded with reproductions in [`../../DEFECTS.md`](../../DEFECTS.md). Both are worked
around in the scorer, not patched in `backend/` — a round is a measurement, and changing the
instrument partway through invalidates it.

**D1 — `total_return` is rebased to the first session's close.** `metrics.compute` divides
`equity[-1]` by `equity[0]`; the runner divides its whole curve by `starting_equity` first, and that
constant cancels out of the ratio. Any card filling on session one has its first day silently
excluded — which the runner's own adjacent comment says must not happen. 14 card-window pairs
disagree by more than 0.05pp and **two change sign**: `A-rotation` in `covid` reports −0.652%
against a true +0.465%.

**D2 — `exposure` counts sessions holding anything, not capital at risk.** A four-slot card holding
one slot every session reports 1.0. Multiplying that by a benchmark return over-credits exactly the
cards that hold few slots, and worst in a falling window where the term is negative.

The corrections were not cosmetic:

| card | window | naive | corrected |
|---|---|---|---|
| `c04-riskmanaged` | gfc | +55.45% | **+25.45%** |
| `H-trend-diversified` | bear-2022 | +17.32% | **+0.71%** |
| `c03-breakout` | gfc | +13.43% | **−1.71%** (sign change) |

`H`'s apparent 82% exposure was one small DBC commodity position held a long time, not a filled book.
Had this shipped uncorrected, the round's headline would have been a card that appeared to survive a
56% bear market while nearly fully invested.

D2 was surfaced by a card's author having estimated 45% capital deployment where the runner reported
97.19% — a disagreement between a memo and a machine, noticed only because both were in the record.

---

## 7. Execution reality, quantified

Stops evaluate against the **previous close**, not the intraday low, because the decision-maker
cannot see the session's low. The cost is large and consistent:

- `c02-volatility` — XLF entered 2008-09-09, stopped 2008-09-16 at **−18.22% against a nominal 8%
  stop**. A 10.2-point gap, landing on the week Lehman Brothers filed.
- `G-volatility` — COIN entered 2022-07-21, realised **−22.81% against a nominal 10% stop**. The
  round's largest gap.

Any card sizing its risk on the assumption that a stop caps the loss at its nominal value is sizing
it wrong by a factor of two or more in a fast market.

---

## 8. What changes for round 2

Per `PROTOCOL.md` §6, promotion requires positive median in **two consecutive rounds**. One round is
one draw, so this round promotes nothing to `base/`. The concrete changes:

1. **Add windows, and add a sideways one specifically.** Four is too few to resolve a 5-point variant
   effect against a 21-point ordering floor. The store supports 2011, 2015–16, 2018Q4 and the 2020–21
   melt-up for the deep-history cards. More windows is the single highest-value change available.

   The matrix also has a hole worth naming: it holds two bears, one crash and two bulls, and **no
   choppy, directionless market at all.** Several analysts pre-registered whipsaw as the regime they
   feared most — `c04-riskmanaged` named it first — and not one of them could be tested on it. A
   pre-registration that the matrix cannot evaluate is a prediction nobody scored. 2015-05 → 2016-02
   and 2011 are the obvious candidates.
2. **Rank on more than the median.** The metric places insurance last by construction. Round 2 should
   report a dominance view — median, worst window, and spread together — rather than collapsing to
   one number, and should say up front which profile it is selecting for.
3. **Fix D1 and D2 in the engine**, between rounds, and re-run this round's cards to confirm the
   scorer's workaround and the fixed engine agree.

   **And add a third: teach the toolchain about provenance.** Every card should carry a
   `universe_knowable_from` date, and the scorer should refuse to score any window starting before
   it. Right now the eligibility check answers "do these symbols have enough price history," and the
   quite different question "was this basket knowable at the time" is enforced only by a person
   remembering to enforce it. This round shows that is not reliable — it was missed once in the
   ranking table above, by the same author who had written the warning against it.
4. **Retire `D-13f-newbuys`** or drop SNDK from it. A card that cannot run in any window is not a
   strategy. Its prior +56.93% against a +11.99% benchmark was this project's most genuinely
   out-of-sample result and is now unreproducible in this matrix, which is worth one attempt at a
   shorter moving average before retirement.
5. **Give the variants a fair test or drop them.** Eight variants that resolve nothing are eight
   backtests a round. Either the window count rises enough to resolve them, or the variant programme
   is not earning its compute.
6. **Challengers carry forward unchanged** into round 2, where `recent` becomes a genuinely
   out-of-sample record for them. That is the walk-forward, and it is the only part of this design
   that produces uncontaminated evidence over time.

---

## 9. What this round does not show

- **One draw per regime.** Five windows are five draws, not a distribution. Every ranking here is
  provisional and several are separated by less than their own noise.
- **The GFC comparison is between five cards, not twenty-two.** No incumbent could enter it. The
  challengers' crisis results are not evidence they beat the incumbents there — the incumbents were
  not present.
- **`bull-2024` and `recent` overlap the design period** for every card in the field. Those two
  windows measure fit. Only `gfc`, `covid` and `bear-2022` sit outside every author's design window,
  and even then the analysts knew crisis windows were in the matrix.
- **The single-name cap is raised to 100%**, so drawdowns are larger than the persona's real 25%
  mandate would permit.
- **No dividends anywhere**, which flatters every strategy against a real buy-and-hold investor by
  roughly two points a year.
- **The universes are still chosen by their authors**, and the challengers chose deep-history ETFs
  partly because the gate rewarded it. That is the incentive working, but it also means the field is
  not a random sample of strategies.
- **The prior tournament's ρ = 0.162 problem is not solved by this round**, only measured
  differently. It will take several rounds of walk-forward before this program can claim its rankings
  predict anything.

---

Per-card reports, each written from that card's own trade logs and checked against its author's
pre-registered failure prediction, are in [`reports/`](reports/). Window analyses are in
[`analysis/`](analysis/). The frozen cards are in [`cards/`](cards/) and the design memos, written
before any result existed, in [`memos/`](memos/).

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
