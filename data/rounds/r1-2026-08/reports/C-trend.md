# C-trend — competition report

`C-trend`, "C - Trend (r1): won in-sample and 3yr" (discipline: `trend`), ranked **9th of 18** ranked
cards on median `adjusted_excess` (**+4.99%**). It carries a specific question forward from the prior
tournament: it beat SPY in-sample (+90.10%) and over three years (+91.66%) there, but lost its blind
window (+1.87%). This round puts it through four independent regime draws to ask whether that blind
loss was the outlier or the truth.

## 1. What the card is

`close > sma(200) and ema(20) crosses_above ema(50)`, exiting on the reverse cross, `stop_loss_pct =
0.12`, `max_hold_days = 120`, five slots at 18% each. Universe: `NVDA AVGO TSM ORCL SOXX NFLX MU META
QCOM` — large, liquid AI/semi/software names, chosen (per the card's own thesis) after excluding
smaller, more speculative names (`IREN OKLO APLD BE KORU`) whose golden-cross entries showed negative
forward returns in the same measurement.

**Not eligible for `gfc`**: `META first bar 2012-05-18, needs <= 2006-10-27` (`eligibility.json`).
META's absence from the universe before 2012 blocks the deepest drawdown in the matrix outright, so
this card's record has no data point from the one regime its own thesis (institutional flow into a
confirmed uptrend) would be tested hardest against. It ran all four other main windows — `covid`,
`bear-2022`, `bull-2024`, `recent` — which is what clears the three-window gate.

## 2. Results across eligible windows

| window | trades | corrected return | benchmark | excess | adj. excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 7 | +15.83% | −8.71% | +24.55% | **+19.63%** | 43.61% | 69.89% | −4.88% | 50.00% |
| bear-2022 | 5 | −6.97% | −25.14% | +18.17% | **−5.82%** | 4.57% | 21.43% | −7.60% | 0.00% |
| bull-2024 | 15 | +22.75% | +14.00% | +8.76% | **+15.79%** | 49.71% | 80.00% | −13.33% | 40.00% |
| recent | 14 | −2.24% | +20.62% | −22.85% | **−7.21%** | 24.12% | 53.82% | −17.99% | 20.00% |

Corrected return is `ending_equity / starting_equity − 1` per DEFECTS.md D1; `capital_exposure` is
reconstructed from the trade log per D2 and used in `adjusted_excess`, with the runner's raw
session-presence `exposure` carried alongside for comparison. **Median adjusted excess +4.99%
(midpoint of +15.79% and −5.82%), negative in 2 of 4 windows, IQR 12.99 points, hit rate 50%, 41
trades total.**

## 3. Verdict on the claim

The blind loss was not the outlier. `recent` — the window that overlaps most directly with the prior
tournament's 2026-02-17→2026-08-18 blind period — is this round's *worst* window at −7.21% adjusted
excess, on a −2.24% corrected return against a +20.62% benchmark. `bear-2022`, the other grinding
non-crash regime, is also negative (−5.82%). The two windows where the card wins decisively are
`covid` (+19.63%, a V-shaped crash-and-snapback) and `bull-2024` (+15.79%, a trending bull run) —
exactly the regime shape (sustained, confirmed uptrends with a clean re-entry after a shock) the
card's `sma(200)` + `ema(20/50)` mechanism is built to catch.

So the honest reading is neither "the blind result was a fluke" nor "the in-sample/3yr wins were
noise": the card has a real, recurring regime dependency. It performs well when a market either
snaps back sharply or trends cleanly, and it performs poorly in a grind (`bear-2022`) or in whatever
regime produced the most recent twelve months (`recent`) — chop, late-cycle whipsaw, or a market
moving without the kind of clean multi-quarter re-rating the thesis describes. The prior tournament's
blind loss and this round's `recent` loss are two independent draws pointing the same direction. A
positive median across four windows says the card is not worthless; a worst-window of −7.21%
recurring in precisely the window most similar to the original blind test says the original result
was a real signal about this card's weak regime, not sampling noise.

## 4. Trade-level detail

**Exit-reason distribution:**

| window | rule | stop | open_at_end |
|---|---:|---:|---:|
| covid | 2 | 0 | 5 |
| bear-2022 | 3 | 2 | 0 |
| bull-2024 | 9 | 1 | 5 |
| recent | 9 | 1 | 4 |

**Best and worst realised trades per window** (`open_at_end` positions are unrealised mark-to-market,
noted separately):

| window | best | worst |
|---|---|---|
| covid | TSM, 2020-05-15→2020-05-18, +0.63% (rule) | TSM, 2020-05-08→2020-05-14, −4.28% (rule) |
| bear-2022 | AVGO, 2022-02-17→2022-02-18, −1.60% (rule) | MU, 2022-02-11→2022-03-08, −16.56% (stop) |
| bull-2024 | NFLX, 2025-04-22→2025-08-06, +14.62% (rule) | MU, 2024-10-17→2024-11-18, −13.38% (stop) |
| recent | SOXX, 2026-04-07→2026-07-30, +43.15% (rule) | META, 2026-07-15→2026-07-31, −18.17% (stop) |

Every realised trade in `bear-2022` lost money — the "best" is simply the smallest loss. Unrealised
positions at window end were larger winners in three of four windows (best: ORCL +45.60%, entered
2025-05-15, still open at the `bull-2024` boundary; NVDA +36.86% in `covid`), which is the trend
discipline's usual shape — the biggest wins are the ones still running when the window ends.

**Stop-outs, 4 of 41 trades (9.8%), all against `stop_loss_pct = 0.12`:**

| symbol | window | entry→exit | bars held | realised |
|---|---|---|---:|---:|
| MU | bear-2022 | 2022-02-11→2022-03-08 | 16 | −16.56% |
| NVDA | bear-2022 | 2022-03-29→2022-04-07 | 7 | −14.91% |
| MU | bull-2024 | 2024-10-17→2024-11-18 | 22 | −13.38% |
| META | recent | 2026-07-15→2026-07-31 | 12 | −18.17% |

Mean realised stop-out loss **−15.75%** against a nominal 12% stop — a gap of **3.75 percentage
points**, consistent with WINDOWS.md's mechanics: stops evaluate against the previous close, not the
intraday low, so a breach confirmed at one close fills at the next session's open, and any further
overnight or intraday move against the position lands entirely on the trade before the stop can act.
The MU (bear-2022) and META (recent) trades — both held well past the median hold time of a losing
trade the card's own thesis describes (16 and 12 bars, against a design-window median of 16 days for
losers) — show the widened 12% stop (chosen over 8% specifically to reduce noise stop-outs) still
lets a real breakdown run several points past its nominal level once confirmed.

## 5. Rankable, and where it stands

Yes. Four of five main windows run (only `gfc` is blocked, by META's history), clearing the
three-window gate with room to spare. Ranked 9th of 18 on median adjusted excess, squarely in the
middle of the ranked field — ahead of the A-family variants and the other `c`-family trend/breakout
cards, behind every `B`-family (momentum) variant and `G-volatility`.

## 6. Recommendation

**Retain as a candidate; do not promote to base.** PROTOCOL.md §6 requires a positive median
adjusted excess in **two consecutive rounds on window sets that differ** before a candidate moves to
`base/`. This round supplies one positive-median result (+4.99%) built on a genuine four-window
regime spread — a stronger basis than the two-window in-sample/blind comparison that motivated its
promotion into the library — but it is one round, and the recurring weakness in `bear-2022` and
`recent` is exactly the kind of pattern the two-consecutive-rounds rule exists to distinguish from
noise. Carry `C-trend` into round 2 unchanged; if it clears a positive median again on the round's
new window (per PROTOCOL.md §5's walk-forward), promote to `base/`. If `recent`-style regimes recur
and the median goes negative, that would be the second data point needed to demote.
