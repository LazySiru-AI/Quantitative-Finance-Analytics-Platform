# E-asymmetric -- Tight Stop, Distant Target -- round 2 report

Agent: `E-asymmetric` | Discipline: `momentum` | Eligible: 1/8 main windows -- **unranked**, far
below the round-2 five-of-eight gate (see `results/eligibility.json`)

## 1. What the card is, its claim, and why it can run in only one window

The design is organised around payoff shape, not signal: a deliberately low win rate traded for a
large reward-to-risk (`take_profit_pct / stop_loss_pct = 0.28 / 0.08 = 3.5`). Entry is `close >
bb_upper(20,2) and macd_hist(12,26,9) > 0 and close > sma(50)` -- a band breakout confirmed by
accelerating momentum inside an established uptrend. Universe: `MU PLTR COIN NBIS LITE CRDO BE OKLO
APLD IREN`, ten early-stage AI-infrastructure/power/compute names. The design memo's own simulation
(496 signals over each symbol's full history) put the base rates at 35.3% target-hit, 57.3%
stop-first, 7.5% timeout -- so the claim is explicitly that a minority of trades carries the result,
and the card "needs 10-20+ resolved trades before its win rate is more than noise."

**Eligible for `recent` only**: `eligibility.json` gives `NBIS first bar 2024-10-21` as the binding
constraint against every other window (`needs <= 2024-04-14` for `bull-2024`, and earlier still for
the rest). NBIS is a 2024 listing; the universe cannot, by construction, reach any older regime.

**Round 2 added no new window for this card.** `REPORT.md` §9: no calendar time passed between rounds
1 and 2, so the walk-forward window round 1's own report named as the fix never arrived. NBIS's first
bar has not moved, and the card's eligible set is `{recent}`, identical to round 1.

## 2. Versus SPY, its one eligible window

| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| recent | 249 | **+26.86%** | +20.62% | +6.24% | +21.18% | 27.5% | -10.98% |

There is no median, worst, IQR, or hit rate to report for one data point. **This figure is also not a
new measurement**: round 1 recorded +21.21% on the same window, same 69 trades; the 0.03pp difference
is the D2 capital-exposure engine fix noted in `REPORT.md` §6, not fresh evidence. `E-asymmetric` has
exactly one draw, unchanged since round 1.

## 3. What moved the number

69 trades, exit-reason distribution: `target` 20, `stop` 37, `rule` 9, `open_at_end` 3.

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| BE | 2026-04-14 | 2026-04-30 | 12 | target | +45.69% | +556 | +5.56% |
| BE | 2025-09-17 | 2025-10-14 | 19 | target | +45.72% | +540 | +5.40% |
| NBIS | 2026-05-07 | 2026-06-02 | 17 | target | +43.05% | +491 | +4.91% |
| IREN | 2025-08-25 | 2025-09-03 | 6 | target | +40.73% | +477 | +4.77% |
| APLD | 2026-04-15 | 2026-05-07 | 16 | target | +37.63% | +450 | +4.50% |
| BE | 2025-10-30 | 2025-11-14 | 11 | stop | -27.42% | -290 | -2.90% |
| OKLO | 2025-10-14 | 2025-10-22 | 6 | stop | -21.05% | -248 | -2.48% |
| IREN | 2026-01-20 | 2026-02-05 | 12 | stop | -22.48% | -247 | -2.47% |

BE supplies both the single best trade of the window (+45.72%) and, six weeks later, the single worst
(-27.42%, a stop) -- the same name riding a target-scale move and then giving back more than double
the nominal stop. More than half of all trades (37 of 69, 53.6%) resolved at the stop, close to the
memo's own predicted 57.3% stop-first base rate; only 20 (29.0%) reached the 28% target, slightly
below the 35.3% base rate -- both within the range the memo itself said to expect.

## 4. Concentration

Top-3 share of gross winning P&L is **20%**; without the three largest winners (BE +5.56%, BE +5.40%,
NBIS +4.91%) the card returns **+10.99%** instead of +26.86%. Unlike `G-volatility`'s breadth, this
card's edge is not spread thin across 69 trades -- one-fifth of the gross winning P&L sits in three
trades, consistent with its own "the edge lives in the few trades that become real trend
continuations" framing.

## 5. Realised versus marked

**-0.39%** of the +26.86% total sits in positions open at the window's close -- a small negative drag,
not a material reliance on unrealised marks. This result is almost entirely realised cash.

## 6. Verdict on the claim, and recommendation

**Do not present +21.18% as a validated result.** The card's own design memo predicted exactly this
situation: with a 57% base stop-first rate and a 35% target-hit rate, "a handful of trades will decide
the whole result" in any single window, and BE alone (best and worst trade both) illustrates that
directly. `recent` is one draw from one regime (a bull market), and this round supplies the *same*
draw a second time, recomputed rather than re-measured -- not a second data point in any sense that
would move a median.

**Not rankable, and round 2 changed nothing about that.** One eligible main window against a
five-of-eight gate that has widened since round 1's three-of-four. What would change this: the
universe drops NBIS (or any name whose history is shorter) for an equally early-stage but longer-lived
name, or -- more honestly, given the thesis is specifically about early-stage names that are young by
construction -- the walk-forward window arrives. `REPORT.md` §8.5 names this directly: "round 3
should wait for real elapsed time, or it will again be a re-measurement wearing a round's clothing."
When real time has passed, NBIS's history will be long enough relative to whatever new window opens,
giving this card a second data point without any change to the card itself. A third window after that
would clear the gate.

**Recommendation: retain as a candidate; do not promote, and do not penalise it for a universe-history
constraint it disclosed in its own memo.** `PROTOCOL.md` §6 has no path to `base/` without clearing
the regime gate and no path to retirement for a card that took trades and is simply young. Carry
`E-asymmetric` forward unchanged into round 3, and treat the walk-forward window, when it arrives, as
the priority second data point for this card specifically.
