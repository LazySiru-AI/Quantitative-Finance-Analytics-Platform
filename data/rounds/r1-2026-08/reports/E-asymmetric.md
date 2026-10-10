# E-asymmetric — competition report

`E-asymmetric`, "E - Asymmetric: tight stop, distant target" (discipline: `momentum`), is **unranked**
under the three-window gate. It ran in exactly one main window (`recent`) and posted an adjusted
excess of **+21.21%** on 69 trades — the single best per-window number of any of the six candidate
cards in this report. That number should not be read as a validated result, and this report exists
mainly to explain why.

## 1. What the card is, its claim, and why it could run in only one window

The design is organised around payoff shape rather than signal: a deliberately low win rate traded
for a large reward-to-risk (`take_profit_pct / stop_loss_pct = 0.28 / 0.08 = 3.5`). Entry is
`close > bb_upper(20,2) and macd_hist(12,26,9) > 0 and close > sma(50)` — a band breakout confirmed by
accelerating momentum inside an established uptrend. Universe: `MU PLTR COIN NBIS LITE CRDO BE OKLO
APLD IREN`, ten early-stage AI-infrastructure/power/compute names chosen narrow enough that one fixed
8% stop is a defensible approximation across the book (trailing ATR/price ranged 6.3%–14.0% across
the ten names at design time).

**Eligible only for `recent`**: `eligibility.json` gives `NBIS first bar 2024-10-21, needs <=
2024-04-14` for `bull-2024`, and the same binding symbol blocks `gfc` (`needs <= 2007-06-02`),
`covid` (`needs <= 2019-10-13`) and `bear-2022` (`needs <= 2021-08-27`). NBIS is a 2024 name; the
card's universe cannot, by construction, reach back to any pre-2024 regime. This is not a data gap
that better luck would have avoided — it is the direct, stated cost of a universe assembled from names
young enough that the "early-stage AI-infrastructure" thesis applies to them at all.

## 2. Results across its one eligible window

| window | trades | corrected return | benchmark | excess | adj. excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| recent | 69 | +26.86% | +20.62% | +6.24% | **+21.21%** | 27.39% | 81.12% | −10.98% | 34.85% |

Corrected return and capital exposure use the DEFECTS.md D1/D2 workarounds throughout. There is no
median, worst-window, IQR, or hit-rate to report beyond the single value — those statistics require
at least two data points to describe a distribution, and this card has one.

## 3. Verdict on the claim

**Do not present +21.21% as a validated result.** The card's own thesis is explicit about why: with a
57% base stop-first rate (measured over 10–40 years of per-symbol history) and a 35% target-hit rate,
"a handful of trades will decide the whole result" in any single window, and the design memo warned
specifically that the realised reward:risk in a 127-session-scale window would likely fall well short
of the planned 3.5, tracking whatever the timeout-return distribution happened to produce instead.
`recent` is 249 sessions — roughly double that reference window — and it produced 69 trades, so the
sample is not as thin as the memo's worst case, but it is still exactly one draw from one regime (a
bull market, per WINDOWS.md's own classification of `recent`).

A single window is a single draw, full stop, and a card designed around asymmetric payoffs is the
shape of strategy that needs a long record most, precisely because its edge is concentrated in a
minority of trades rather than distributed evenly across all of them — one favourable or unfavourable
tail event in a 69-trade sample can move the aggregate substantially, and there is no second window
here to check whether this one was typical. The honest framing is: this round supplies one positive,
sizeable data point consistent with the thesis (a 3.5:1 payoff structure trading a 35%-win asymmetric
book), not evidence the strategy works. The claim remains open.

## 4. Trade-level detail

**Exit-reason distribution (`recent`, 69 trades):** `target` 20, `stop` 37, `rule` 9, `open_at_end` 3.
More than half of all trades (37 of 69, 53.6%) resolved at the stop — close to the memo's own
predicted 57.3% stop-first base rate — and only 20 (29.0%) reached the 28% target, slightly below the
35.3% base rate, both within the range the memo itself said to expect.

**Best and worst trades:**

| best | worst |
|---|---|
| BE, 2025-09-17→2025-10-14, +45.72% | BE, 2025-10-30→2025-11-14, −27.42% (stop) |

BE produced both the best and the single worst trade in the book — the same name, roughly six weeks
apart, first riding a target-scale move and then giving back more than double the nominal stop.

**All 37 stop-outs, nominal `stop_loss_pct = 0.08`:** mean realised loss **−11.92%**, a gap of **3.92
percentage points** beyond the nominal 8% level. The distribution is wide — from BE at −27.42% (2025-
10-30→2025-11-14, 11 bars held) and IREN at −22.48% (2026-01-20→2026-02-05, 12 bars) down to COIN at
−5.28% (2026-07-22→2026-07-27, 3 bars, close to the nominal level). The pattern matches WINDOWS.md's
stated mechanism: stops evaluate against the previous close, not the intraday low, so on names with
the higher end of this universe's daily-move distribution (IREN and OKLO's p90 daily moves ran
10.6%–12.4% at design time, per the card's own thesis, above the 8% stop itself) an ordinary session's
close-to-close move can carry the realised exit several points past the nominal 8%, and the worst
cases (BE −27.42%, IREN −22.48%, OKLO −21.05% on 2025-10-14→2025-10-22) show that gap compounding over
several bars before the stop confirms and fills.

## 5. Rankable, and what would make it so

**Not rankable.** One eligible main window against a three-window minimum. What would change this:
either the universe drops NBIS (or any name whose history is shorter) for an equally early-stage but
longer-lived alternative that clears at least `bull-2024`'s 2024-04-14 deadline, or — more honestly,
given the thesis is specifically about *early-stage* AI-infrastructure names, most of which are young
by construction — the card simply waits. Round 2's walk-forward (PROTOCOL.md §5) adds the elapsed
time since this round as a new window; if NBIS's history is long enough by then relative to that new
window's start, `E-asymmetric` gains a second data point without any change to the card at all. A
third window after that would clear the gate.

## 6. Recommendation

**Retain as a candidate; do not promote, and do not judge harshly.** PROTOCOL.md §6 has no path for a
card to move to `base/` without clearing the regime gate, and no path to retirement for a card that
took trades and is simply young. `E-asymmetric` posted a real, sizeable positive result on its only
available window and behaved close to its own pre-trade predictions (stop-first rate, target-hit
rate) — the correct action is to carry it forward unchanged and let the walk-forward window matrix
do the work of turning one data point into three, rather than either promoting on a single window or
penalising the card for a universe-history constraint it disclosed in its own memo.
