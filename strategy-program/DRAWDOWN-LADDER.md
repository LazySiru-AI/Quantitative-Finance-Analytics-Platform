# The drawdown ladder: backtest, analysis, and the version worth running

**Not investment advice.** This is a specification tested against stored price history on a simulated
account. I am not a licensed financial adviser and none of this is a recommendation about real
capital.

The strategy as handed to me: hold SCHD; rotate into QLD at −10%, −20% and −30% drawdowns of the
S&P 500 from its all-time closing high; halve the QLD sleeve on a new high. Claimed result over
2016-08 to 2026-08 on $10,000: **$83,507, 23.7% CAGR, −41.1% max drawdown**.

**The headline finding: the strategy as specified reaches a −72.7% drawdown through 2008 — worse than
a static blend, and far worse than the index it triggers on.** It is not broken in a way tuning
fixes; it has no exit on continued decline. A three-sleeve version with a bounce condition keeps
almost all of the risk-adjusted return and cuts the drawdown by 15–18 points in every window tested.

Backtester: `strategy-program/tools/drawdown_ladder.py`.

---

## 1. Three things the specification leaves open

Each one decides whether the result is real, and each is closed in the implementation:

- **Arming.** A rung fires once per drawdown cycle and re-arms only on a full reset to the base
  state. Without it, an index oscillating around −10% round-trips the whole book repeatedly and the
  strategy is a slippage pump. April 2025 is exactly that shape.
- **Gap-through.** A close at −21% having never closed at −10% goes straight to the −20% weight in
  one trade. March 2020 came close enough to matter.
- **The ratchet.** "Halve on a new high" never reaches zero — 60% becomes 30%, then 15%, and leverage
  accumulates across cycles. A full exit condition is what actually closes the position.

## 2. One correction to the critique this arrived with

**The 0.95% QLD expense ratio is not an omitted cost.** An ETF's published NAV is already net of its
expense ratio, so a backtest running on real QLD closes has already paid it. Subtracting it again
double-counts. What is genuinely absent from the price is the cost of the rotations themselves, and
that is charged here at 5bp per dollar traded, one way.

## 3. The result, as specified

| window | CAGR | max drawdown | MAR |
|---|---|---|---|
| 2016-08 → 2026-08 (the claimed window) | +21.92% | −34.8% | 0.63 |
| 2011-11 → 2026-08 (all of SCHD's history) | +18.82% | −34.8% | 0.54 |
| **2006-06 → 2011-10 (the crisis)** | **+4.49%** | **−72.7%** | **0.06** |
| 2006-06 → 2026-08 (twenty years) | +16.69% | −72.7% | 0.23 |

My reproduction of the claimed window lands at 21.92% CAGR and −34.8% against the claimed 23.7% and
−41.1% — close enough that we are testing the same idea, with the difference attributable to the
three gaps above being closed differently.

**Against a static blend, over the claimed window, the ladder wins**: +21.92% and −34.8% against
static 60/40's +19.70% and −40.7%. The critique's prior — that most of the gap closes against static
rebalancing — is wrong *for that window*. Over the full SCHD history it is right: static 60/40 earns
more (+20.11%) and the ladder only wins on drawdown.

**Then 2008.** SCHD did not exist, so SPY stands in as the defensive sleeve; QLD is real, back to
2006-06.

| 2006-06 → 2011-10 | CAGR | max drawdown | MAR |
|---|---|---|---|
| ladder as specified | +4.49% | **−72.7%** | 0.06 |
| static 60/40 quarterly | +2.18% | −69.5% | 0.03 |
| QLD buy & hold | +3.59% | −84.0% | 0.04 |
| SPY buy & hold | −0.51% | −56.5% | −0.01 |

The ladder's drawdown is **worse than the static blend and 16 points worse than the index it
triggers on**. It ladders to 80% QLD as the market keeps falling — maximum leverage at the point of
maximum subsequent loss — and then has no rule that reduces it, because its only de-risking
condition is a new all-time high, which in 2008 was more than four years away.

The critique's suspicion was right and understated.

## 4. What fixes it, and what does not

Three candidate fixes, each tested across all three windows. **A fix that only helps one window is
not a fix**, and this programme has spent five rounds establishing that.

| variant | GFC MAR | modern MAR | full MAR |
|---|---|---|---|
| as specified | 0.06 | 0.54 | 0.23 |
| + bounce confirmation, 20-session | 0.14 | 0.49 | 0.25 |
| **+ bounce confirmation, 50-session** | **0.17** | 0.43 | **0.25** |
| + time stop, 120 sessions | **−0.05** | 0.46 | 0.17 |
| + time stop, 60 sessions | **−0.07** | 0.43 | 0.16 |
| + confirmation and time stop | 0.03 | 0.41 | 0.20 |

**Bounce confirmation works.** Requiring the index to close back above its own 50-session average
before a rung fires nearly triples crisis MAR and improves the full-period figure. The strategy stops
buying into a straight-line decline and waits for evidence that the decline has paused.

**Time stops actively hurt, and this was my own proposed fix.** Cutting leverage after N sessions
without a new high turns the crisis CAGR *negative*: it sells at the bottom and misses the recovery,
which is the classic whipsaw. Recorded because I expected it to help and the data said otherwise.

### The real defect: the defensive sleeve is not defensive

Even with confirmation, the full-period MAR is 0.25 against QLD's own 0.29. The improved ladder still
does not beat simply holding QLD on risk-adjusted terms, because **both sleeves fall together**. SCHD
fell 33% in 2022 and SPY fell 56% in 2008. There is no reserve — the strategy funds leverage by
selling something that is also down.

Adding a genuine reserve sleeve is what closes it. IEF (7–10 year Treasuries, history back to 2002)
as the funding source, drawn down before SCHD:

| reserve weight | GFC MAR | modern MAR | full MAR |
|---|---|---|---|
| none (two sleeves) | 0.17 | 0.43 | 0.25 |
| 30% IEF | 0.21 | **0.53** | 0.25 |
| 40% IEF | **0.25** | 0.53 | 0.25 |
| 50% IEF | **0.29** | 0.48 | 0.26 |

The surface is smooth across 30–50%, not a knife edge, which is the test the critique rightly asked
for. 40% is chosen as the midpoint; anywhere in that band is defensible and this data cannot
distinguish them.

**A reserve sleeve was in the original three-ticker sketch — QLD / SCHD / SGOV — and the written
specification dropped it.** It turns out to be the part that matters most. SGOV itself only has bars
from 2020-06, so IEF stands in for the backtest; SGOV or BIL is the shorter-duration equivalent for
live use, and the choice between them is a duration decision this test does not settle.

## 5. Sensitivity — is it overfit?

| trigger depths | GFC | modern | full |
|---|---|---|---|
| −7 / −15 / −22 | 0.07 | 0.45 | 0.20 |
| **−10 / −20 / −30** | **0.17** | 0.43 | **0.25** |
| −13 / −25 / −35 | 0.17 | 0.35 | 0.22 |
| −15 / −25 / −35 | 0.16 | 0.35 | 0.22 |

**The specification's own depths are the right ones** and the surface is flat (0.20–0.25 on the full
window). Triggering earlier at −7% is clearly worse in a crisis. This is not a knife edge.

| signal | GFC | modern | full |
|---|---|---|---|
| **SPX (SPY)** | **0.17** | 0.43 | **0.25** |
| NDX (QQQ) | 0.08 | 0.44 | 0.19 |

**Triggering on NDX is refuted.** The critique floated it on the reasoning that you are buying 2× NDX
so you should trigger on NDX; the data says the broad index is the better trigger in exactly the
window where it matters. The mismatch the critique identified is real, and resolving it the other way
is worse.

Larger tranches (25/75/100 instead of 20/60/80) score better on MAR in every window — **and are not
adopted.** That improvement is only "more QLD did better in a period where QLD did well", which is
the same trap as concluding the whole exercise should be replaced by holding QLD.

## 6. The final version

> Sleeves **60% SCHD / 40% IEF**, signal **SPY drawdown from all-time closing high**.
> Rungs **−10% → 20% QLD**, **−20% → 60%**, **−30% → 80%**, funded from IEF first, then SCHD.
> A rung fires **only when SPY closes above its own 50-session average**, once per cycle, with
> gap-through to a rung never touched.
> On a new all-time high, halve QLD. Exit fully at **+10% above the high the cycle began from**, or
> **60 sessions after the new high**, whichever comes first — then re-arm.
> No time stop.

| window | | CAGR | max drawdown | MAR | rotations |
|---|---|---|---|---|---|
| **2006-06 → 2011-10** | **final** | **+13.70%** | **−55.0%** | **0.25** | 2 |
| | as specified | +4.49% | −72.7% | 0.06 | 3 |
| **2011-11 → 2026-08** | **final** | +10.69% | **−20.2%** | 0.53 | 10 |
| | as specified | +18.82% | −34.8% | 0.54 | 22 |
| **2006-06 → 2026-08** | **final** | +13.95% | **−55.0%** | **0.25** | 14 |
| | as specified | +16.69% | −72.7% | 0.23 | 27 |
| **2016-08 → 2026-08** | **final** | +12.00% | **−20.2%** | 0.60 | 10 |
| | as specified | +21.92% | −34.8% | 0.63 | 19 |

**Essentially the same risk-adjusted return in every window, with the drawdown cut by 15 to 18
points, and the crisis case transformed** — MAR 0.06 → 0.25, drawdown −72.7% → −55.0%.

Turnover roughly halves as well: 14 rotations over twenty years against 27. That matters directly for
the tax point the specification raises, and it strengthens the case for holding this in a Roth: fewer
round trips, but every one of them still a short-term realisation on the leveraged leg.

## 7. What this is not

- **It does not beat QLD on return.** QLD compounds at 24.50% over the twenty-year window against the
  final version's 13.95%. The comment on the original post — that the conclusion is really "QLD is
  good" — is correct on return and remains correct here. What the ladder buys is a −55.0% worst
  drawdown instead of −84.0%. Whether 29 points of drawdown is worth 10 points of CAGR is a question
  about the holder, not about the data.
- **It does not beat QLD on MAR either** (0.25 against 0.29 over twenty years). It beats static 60/40
  (0.24), and it beats the specification it started from.
- **The sample is still small.** Two crises in twenty years. The 2006–2011 test uses SPY where SCHD
  would have been, because SCHD did not exist, and SCHD is not SPY.
- **Every window here is in-sample.** All of it predates 2026-02-13, and the specification was
  written with knowledge of these periods. Nothing here is a forward test.
- **Leverage decay is in the prices, not modelled separately.** QLD's real closes carry whatever
  path-dependency and financing cost it actually incurred. That is the right way to capture it and it
  means these results already include it.

## 8. Still worth running

- **Rolling five-year windows** rather than four fixed ones, to see dispersion rather than a point
  estimate. The critique asked for this and it is not done here.
- **A synthetic 2× NDX back to 2000** to include the dot-com collapse, where a Nasdaq-leveraged sleeve
  should behave far worse than it does in 2008. This is the single most likely source of a result
  that would change the conclusion.
- **SGOV or BIL in place of IEF** once enough history exists. IEF carries duration risk that a T-bill
  sleeve does not — and in 2022 that duration was itself a large drawdown, which flatters nothing
  here but would differ live.
