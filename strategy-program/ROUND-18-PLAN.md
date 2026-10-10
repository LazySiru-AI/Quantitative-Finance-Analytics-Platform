# Round 18 — does the *exit* decide the result?

Pre-registered 2026-08-30, before any card in this round has been run. Nothing below was written with
sight of a result.

Not investment advice. Price-only bars, no dividends.

---

## 1. Why this round exists, and why round 17 had to run first

Round 17 measured strategy *form* — eight entry/exit pairs, a regime filter and three bracket
policies — and found every marginal inside the 21.2pp noise floor. One of its three results is the
reason this round exists:

> **Brackets essentially never bind.** `none`, `stop` and `stop-tp` differed by **0.14pp** across the
> whole 48-cell field, and many cells were byte-identical between bracket policies. The rule's own
> exit fires first almost every time.

That is a finding about *exits*, arrived at sideways. If the exit is what closes nearly every
position, then the exit — not the stop, not the target, not the time backstop — is doing the work the
brackets were assumed to do. And round 17 could not separate it, because there each form's exit moved
together with its entry: they are one factor in that design.

**So this round holds the entry fixed and varies only the exit.** It is the mirror of round 17 and it
is only interpretable because round 17 ran first.

## 2. The field — 1 entry × 8 exits × 2 bracket policies, 16 cells

**The entry is fixed at `close > sma(200) and ema(10) crosses_above ema(30)`** — `ma-crossover` with
the regime filter on. That is not an arbitrary pick and it is not the round-17 winner: it is the
single hardcoded template the evolution loop emitted for generations 1–1915, so it is the
most-evidenced entry in this programme's history by an enormous margin, and the one whose behaviour a
reader is most likely to have intuitions about. Using round 17's best entry instead would be
selecting on an outcome.

The eight exits are the eight forms' own exit rules, taken from `app.evolution.ruleforms` unchanged:

| exit | rule |
|---|---|
| `ma-crossover` | `ema(10) crosses_below ema(30)` |
| `momentum-state` | `ema(10) < ema(30)` |
| `rsi-pullback` | `rsi(10) > 60` |
| `band-reversion` | `close crosses_above bb_mid(30, 2)` |
| `channel-breakout` | `close crosses_below swing_low(10)` |
| `band-breakout` | `close crosses_below bb_mid(30, 2)` |
| `macd-cross` | `macd_macd(10, 30, 9) crosses_below macd_signal(10, 30, 9)` |
| `vol-compression` | `atr(10) / close > 0.05 or close crosses_below sma(200)` |

**Brackets: `none` and `stop` only.** Round 17 showed `stop` and `stop-tp` were indistinguishable
(both marginals −1.96%), so carrying the third level would spend runtime on a contrast already
measured as empty. Dropping it is a decision made from round 17's *published* result, before any
round 18 card exists — not a mid-round narrowing.

**Held identical:** the nine full-history sector ETFs (`XLK XLF XLE XLV XLI XLY XLP XLU XLB`), the
same periods 10/30/200, `max_positions` 6, `position_pct` 0.15, `designed_through` 2026-02-13, and
the same eight-window matrix. Round 17's Amendment 1 is already applied — the two young ETFs that
made three windows unrunnable are excluded from the start.

Note the `ma-crossover` exit paired with the `ma-crossover` entry reproduces round 17's
`ma-crossover-on-none` and `ma-crossover-on-stop` cells exactly. **That is deliberate: it is a
built-in reproduction check.** If those two cells do not reproduce round 17's committed figures to the
digit, something moved in the instrument between the two rounds and every comparison here is
suspect — the same regression check round 16 ran against round 15.

## 3. Windows, metric, decision rule

Unchanged from round 17 §3–4: the eight-window matrix, ranked on `median_adjusted_excess`, scored with
`--pin-store`.

**The decision rule is unchanged and is the same 21.2pp floor.** With 16 cells the simulated
expected max−min spread under pure noise is **74.9pp** (95th percentile 103.0pp); across eight
exit-marginals it is **60.4pp**. An exit-marginal spread below 21.2pp is not a finding.

**The measured-ordering-noise result from round 17 does not lower this bar.** That replication found
~1pp of ordering noise on this universe, which makes the floor conservative — but ordering is one
noise source and window mix and sampling remain unmeasured. Round 17 declined to lower the bar after
seeing its data and this round inherits that decision rather than quietly revisiting it.

## 4. Falsifiable predictions

1. **The exit marginal will exceed round 17's form marginal of 7.56pp.** This is the round's central
   claim: if exits close nearly every position, varying them should move more than varying whole
   forms did. If the exit spread comes in at or below 7.56pp, round 17's brackets result was not
   evidence that exits dominate, and I will say so.
2. **The exit marginal will still be inside the 21.2pp floor**, so nothing will be promotable. Stated
   because I expect prediction 1 to hold and prediction 2 to hold simultaneously — "matters more than
   form did" and "matters enough to act on" are different claims.
3. **`momentum-state`'s exit (`ema(10) < ema(30)`, a state rather than a crossing) will hold
   positions for fewer days than `ma-crossover`'s crossing exit**, because a state test is true on
   every bar after the cross while a crossing test is true on one. Median hold and trade count are
   reported for every cell.
4. **`vol-compression`'s exit will produce the highest mean exposure of the eight**, reproducing the
   mechanism round 17 refuted prediction 4 with — it waits for ATR to expand past 5%, so it holds
   through volatility rather than avoiding it. Round 17 established this for the whole form; this
   isolates it to the exit.
5. **The bracket marginal will again be under 1pp**, reproducing round 17's 0.14pp on an independent
   field.

## 5. What this round cannot settle

- One entry. A different entry could plausibly reorder the exits, and this design trades that breadth
  for the ability to attribute a difference to the exit alone.
- Everything in round 17 §7 still applies unchanged: no cross-sectional or cross-symbol strategy, no
  vol-scaled sizing, no non-price data, price-only and dividend-free.
- Nothing will be promoted. This is a measurement study.
