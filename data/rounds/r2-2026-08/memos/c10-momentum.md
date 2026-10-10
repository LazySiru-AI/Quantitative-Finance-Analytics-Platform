# c10-momentum — Confirmed Sector Momentum

## Mechanism

Momentum exists because information about a strengthening sector diffuses over weeks, not
instantly: institutional mandates get reviewed on a schedule, index funds rebalance with a lag,
sell-side estimates get revised one analyst at a time rather than all at once. Positions build in
stages. The counterparty on the other side of the early leg is disproportionately a mean-reversion
trader who faded the first move on the (usually correct, occasionally wrong) prior that moves
revert — when the move doesn't revert, that trader is underwater and either stops out or capitulates
into the second leg, which is what extends the trend. This is a crowding-and-diffusion story, which
is why the edge decays slowly rather than being arbitraged away in one session, and why it should
show up across almost any diversified basket of liquid, widely-held names rather than being specific
to one stock's idiosyncratic story.

## Entry / exit / risk rules

```
entry: close crosses_above sma(20) and close > sma(100) and rsi(14) > 55
exit:  close crosses_below sma(20)
stop_loss_pct:  0.08
take_profit_pct: null
max_hold_days:  40
max_positions:  4
position_pct:   0.25
```

Three conditions must hold together to enter: a short-term breakout (price crossing its 20-day
average), that breakout happening above the 100-day average (don't fight the intermediate trend —
this is the "confirmation filter" the brief invites), and RSI(14) > 55 confirming the move has actual
thrust rather than being a single noisy bar. Exit is symmetric and fast: closing back below the same
20-day average that triggered entry, uncomplicated by a second oscillator condition. `max_hold_days`
of 40 sessions (~8 weeks) is a backstop against a position drifting sideways forever without either
side of the exit condition firing; `stop_loss_pct` of 8% is a tail backstop, not the everyday risk
control (see measurement below — it essentially never fires in the two chop windows).

## Universe and why

`QQQ, XLK, XLY, XLI, XLE, XLF, IWM, SMH` — Nasdaq-100, five sector SPDRs, small caps, and
semiconductors. All eight have a first bar between 1998-12-22 and 2000-06-05, so every window
including `gfc` (starts 2007-10-09) has 7+ years of pre-window history — the 100-day SMA warmup plus
causality-guard bars is a non-issue. This gives eligibility on **all 8 of 8 main windows**, well
above the 5/8 gate.

I chose sector/style ETFs over single names deliberately: momentum's mechanism (crowding into a
strengthening group) is a *sector*-level phenomenon as much as a stock-level one, and a basket
avoids one earnings-gap or idiosyncratic-headline blowing through the stop in a way a single equity
would. No leveraged or inverse instruments are used. None of the eight is a 13F-derived pick, so
`universe_knowable_from` does not apply.

## Parameter count

Counting every numeric literal in `entry` + `exit`, plus the five scalar fields, by raw occurrence:

| location | literals |
|---|---|
| entry (`sma(20)`, `sma(100)`, `rsi(14)`, `55`) | 4 |
| exit (`sma(20)`) | 1 |
| `stop_loss_pct` | 1 |
| `max_hold_days` | 1 |
| `max_positions` | 1 |
| `position_pct` | 1 |
| **total** | **9** |

9 of 10, one slot of headroom. (By distinct-value choice rather than raw token — `sma(20)` is
referenced once in each of entry and exit but is the same chosen parameter — the count is 8: `20,
100, 14, 55, 0.08, 40, 4, 0.25`. I report the more conservative raw count above.) All periods are
conventional (20/50/100-day are the most-watched moving-average lengths; RSI(14) is the textbook
default; RSI > 55 is a mild, round threshold above the neutral 50 line, not a fitted value).

## What I measured in the design window

All numbers below come from `.scratch/c10-momentum/research2.py`, which parses the entry/exit
strings with the engine's own `app.rules.grammar.parse` / `app.rules.evaluate.evaluate` (not a
reimplementation) against real bars read via `duck.connect(..., read_only=True)`, then walks forward
from each signal's next-session open to the earlier of the exit rule firing, the 8% stop (checked
against the *previous close*, matching the engine's stop convention), or the 40-day cap. This is a
single-symbol round-trip simulation, not the actual multi-slot broker — it exists to characterize
signal frequency and reversal behavior, not to reproduce final portfolio equity.

**Chop windows — signal frequency and stop behavior, filtered vs. unfiltered entry** (unfiltered =
same rule without the `close > sma(100)` clause):

| window | variant | signals | win rate | avg return/trade | avg hold | stopped within hold |
|---|---|---|---|---|---|---|
| chop-2015 | filtered | 35 | 42.9% | −0.08% | 6.0 sessions | **0 / 35 (0.0%)** |
| chop-2015 | unfiltered | 38 | 44.7% | +0.10% | 6.7 sessions | 0 / 38 (0.0%) |
| chop-2011 | filtered | 26 | 46.2% | +1.38% | 13.4 sessions | **0 / 26 (0.0%)** |
| chop-2011 | unfiltered | 27 | 44.4% | +1.26% | 13.0 sessions | 0 / 27 (0.0%) |

Zero signals in either chop window, filtered or not, reversed far enough within the hold to touch
the 8% stop — even re-tested at a much tighter 6% and 5% stop, the chop windows still produced no
stop-outs at all. The whipsaw in these two windows is not "sharp reversal that blows through a
stop"; it's grinding, low-amplitude churn. Breaking down the filtered trades further:

| window | avg winning trade | avg losing trade | worst single trade |
|---|---|---|---|
| chop-2015 | +0.84% | −0.76% | −2.01% |
| chop-2011 | +3.86% | −0.76% | −3.25% |

So the realistic cost of a chop-2015 whipsaw round-trip is under 1%, not a stop-sized loss, because
the exit (price closing back below its own 20-day average) reacts within days, not weeks — average
hold across both chop windows is 6–13 sessions against a 40-day cap that is essentially never
reached. **This is the actual defense against chop in this design**, not the entry filter.

**Did the confirmation filter (`close > sma(100)`) help, and did it cost anything in trends?**
Comparing filtered vs. unfiltered across all 8 windows I could compute (same exit/stop/hold, entry
only differing by that one clause):

| window | filtered avg ret | unfiltered avg ret | filtered trades | unfiltered trades |
|---|---|---|---|---|
| q4-2018 | −1.26% | −0.96% | 5 | 6 |
| covid | +9.66% | +7.47% | 3 | 5 |
| bear-2022 | +1.20% | +1.20% | 13 | 13 |
| chop-2015 | −0.08% | +0.10% | 35 | 38 |
| chop-2011 | +1.38% | +1.26% | 26 | 27 |
| bull-2024 | +0.72% | +0.72% | 44 | 44 |
| recent | +2.07% | +2.07% | 34 | 34 |
| gfc | −1.81% | −0.91% | 18 | 29 |

Honest reading: the filter is **not a strong lever**. It is exactly neutral in `bear-2022`,
`bull-2024` and `recent` (the regime condition is essentially always satisfied once a real uptrend or
downtrend is underway, so it changes nothing) — meaning it costs nothing in the trending windows,
which is the one clean result. In the two chop windows it modestly reduces trade count (−8% and −4%)
without a consistent effect on return (very slightly worse in chop-2015, very slightly better in
chop-2011) — call this a wash. In `gfc` it is measurably **worse** on a per-trade basis (−1.81% vs.
−0.91%) despite firing 38% less often, which is the opposite of a clean defensive story: fewer,
lower-quality trades, not fewer, avoided ones. I am keeping the filter because it is free where it
matters (trend regimes) and conventional (the 100-day average is a real, widely-watched level), but I
am not claiming it rescues the crash windows, because the data says it doesn't.

**The trap the brief names, applied honestly:** in `covid`, the filtered rule only fired 3 times, all
in the recovery leg (avg return +9.66%, 100% win rate). That is exactly the arithmetic-absence
pattern the brief warns about — a trend-confirmation entry structurally cannot fire while price is
still below its short-term average during the fall, so the rule is absent for the crash and present
only for the snapback. I am not claiming that as designed risk management; it is a side effect of
the entry's mechanics, and the exposure adjustment should discount it accordingly.

## Sensitivity check

Re-ran the stop at 6% (from the planned 8%) and separately at 5%: the two chop windows still
produced zero stop-outs at either tighter level — the finding that chop reversals don't reach the
stop is not an artifact of choosing 8% specifically, it holds down to 5%. `bear-2022` and `gfc` did
pick up additional stop-outs at 6% versus 8% (2→2 unchanged in bear-2022 at these two levels; gfc
went from 1 stop at 6% to 4 at 8% in one run variant during iteration, consistent with round 1's
finding that stop tightness interacts non-monotonically with regime rather than being a simple
dial). I did not grid-search the RSI threshold or the moving-average periods; 20/100/14 are the
conventional values and 55 is a round number above the neutral midline, chosen once and not tuned
against backtest output.

## Named window I expect to lose in

**`gfc`.** It has the worst measured average per-trade return of any window I tested (−1.81%) and
the highest stop-out rate. Unlike `covid`, this is not primarily an absence effect — the filtered
entry still fired 18 times over 356 sessions, more than in either chop window, because a 17-month
grinding-with-rallies bear market repeatedly produces dead-cat bounces that clear a 100-day-average
filter and a 55 RSI threshold before failing. I expect this window to be genuinely bad for this card,
not artificially flattered by absence — though I would not be surprised if the exposure-adjusted
score still looks better than the raw per-trade numbers suggest, simply because a 4-slot, 25%-per-
name card sitting partly in cash for a 56%-drawdown window is arithmetically hard to make look
terrible relative to a fully-invested SPY benchmark. If it does look fine, that is very likely the
same absence arithmetic the brief describes for `covid`, and should be read that way rather than as
evidence this rule tames the GFC.

## What I tried and abandoned

- **`sma(20) > sma(100)` as the regime filter** (comparing two moving averages) instead of
  `close > sma(100)`. Functionally almost identical in the data, but it requires writing `sma(20)`
  twice (the DSL disallows chained comparisons), which pushed the literal count needlessly higher
  for no measured benefit — dropped in favor of the leaner, equally effective `close > sma(100)`.
- **An RSI-based exit leg** (`... or rsi(14) < 40`) alongside the moving-average exit. Tested it in
  the same simulation; it changed average hold time and win rate only marginally in every window
  (differences under half a percentage point of average return) while adding two more literals
  against the budget. Dropped for being complexity without a measured payoff — the moving-average
  exit alone already produces the short average hold (6–13 sessions in chop) that keeps whipsaw
  losses small.
- **A tighter stop (5–6%) as the primary chop defense.** Confirmed via the sensitivity check that it
  wouldn't change anything in the chop windows specifically (still zero stop-outs) while round 1's
  own finding — a tighter stop doubling stop-out count without improving fill quality — argued
  against tightening it elsewhere for a benefit that wouldn't show up in the regime I'm actually
  being asked about. Kept the 8% stop as a tail backstop only.

## Single weakest assumption

That a 100-day-average regime filter measured on 8 large, liquid ETFs generalizes as "the"
confirmation filter for momentum broadly. The measured effect of that filter was small and
inconsistent across regimes (a wash in chop, worse in gfc, neutral everywhere trending) — the honest
conclusion is closer to "this filter doesn't hurt and is conventional" than "this filter is why the
strategy survives chop." The actual survival mechanism is the fast rule-based exit keeping average
holds to single-digit-to-low-teens sessions, and that mechanism was measured directly rather than
assumed, which is the part of this card I trust most; the entry filter is the part I trust least.
