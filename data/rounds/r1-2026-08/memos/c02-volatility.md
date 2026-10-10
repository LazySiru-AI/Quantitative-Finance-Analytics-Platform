# c02-volatility — design memo

## Mechanism, in my own words

The card is a **volatility-squeeze breakout**: buy a broad, heavily-optioned instrument the
session after it closes above its own 20-day Bollinger upper band, but only when its 14-day ATR
is still below its 50-day ATR — i.e., realized volatility has not yet caught up with the price
move.

Why that combination and not just a breakout: in names with large, liquid options markets (index
ETFs, major sector SPDRs), a period of range compression is not neutral — it is usually
accompanied by *net-short-gamma* positioning building up on the other side. Covered-call overlay
funds, options-income strategies, and dealer/market-maker hedging desks systematically sell
premium into calm markets. While the range holds, their hedging is stabilizing (buy dips, sell
rips), which is part of *why* the range holds. The mechanism I'm trying to catch is the moment
that stabilizing flow flips: price closes outside the band while ATR(14) is still compressed
relative to ATR(50), meaning the option-selling crowd has not yet repriced or covered. Their
hedging now works in the move's direction (a short-call writer who gets tested has to buy the
underlying or unwind the hedge into strength), which mechanically extends the initial breakout for
some period afterward. The participant forced to trade against their own book here is the
volatility seller who wrote premium assuming continued range-bound behavior.

This is a real mechanism (dealer/writer gamma hedging), not a restatement of the rule — the rule
is one operational way to catch the moment this flow is likely to be active; the mechanism is why
that moment should have positive expected drift attached to it, for a few weeks, more often than
chance.

**What I expect to go wrong**, pre-registered: this strategy is about the *first* burst of a
volatility regime change, not persistence, and it is long-only. In a grinding, low-realized-vol
bear market (rate-driven decline, not a shock) there may be few or no valid squeeze setups to
trade at all — realized vol stays elevated-but-not-compressed as the market grinds down, so the
entry condition rarely fires and the strategy sits mostly in cash, which will look like
underperformance against a benchmark that is itself declining slowly (the strategy won't lose much,
but it also won't do anything, and "did nothing" scores worse than "declined less" only if the
benchmark's decline was shallow — it will score fine on `adjusted_excess` if exposure is low, but
it will not distinguish itself). **I expect `bear-2022` to be the window I do worst in**, precisely
because it is the regime this rule is least built for: a slow bleed rather than a compression/
release. I also expect a full crash (COVID's opening days) to be missed on the way down by
construction — a gap-through move arrives with ATR already elevated, not compressed, so the squeeze
filter correctly refuses the entry and the strategy does not attempt to catch the initial plunge.
It should be positioned to catch the post-crash breakout recovery instead, if one occurs inside a
squeeze.

## Universe, and why

`SPY, QQQ, DIA, IWM, XLF, XLE` — six of the most liquid, most heavily optioned instruments in the
store, chosen because the mechanism (option-seller gamma hedging around a compressed range) is
strongest where options open interest is largest and market-maker hedging flow is a real,
structural presence, not a theoretical one. All six are broad index or sector proxies rather than
single names, so no idiosyncratic-earnings gap risk drives the signal.

All six have first bars at or before 1993–2000 (confirmed directly against the store: SPY
1993‑01‑29, DIA 1998‑01‑20, XLF/XLE 1998‑12‑22, QQQ 1999‑03‑10, IWM 2000‑05‑26) — all comfortably
inside WINDOWS.md's "reaches every window including the GFC" tier (first bar ≤ 2004). That makes
this card **eligible for all five windows**: `gfc`, `covid`, `bear-2022`, `bull-2024`, `recent`.
I did not have to trade off eligibility against the mechanism here — the most liquid, most
option-rich names also happen to be the oldest ones in the store, so the two considerations point
the same direction. Adding a newer high-momentum single name (e.g. from the 2015+ tiers) would not
have added anything to the mechanism and would have cost GFC/COVID eligibility for no reason, so I
didn't.

## Every parameter, and why it has that value

| # | parameter | value | why |
|---|---|---|---|
| 1 | `bb` period | 20 | Bollinger's own convention; the single most widely-watched band period. |
| 2 | `bb` stddev | 2.0 | Bollinger's own convention. |
| 3 | `atr` short period | 14 | Wilder's original ATR period; the market standard. |
| 4 | `atr` long period | 50 | A conventional medium-term baseline (~10 weeks, a common "quarter" lookback used across technical analysis for a slower-moving reference line, e.g. the 50-day moving average) rather than a tuned number — see sensitivity check below, which shows 40/50/60 are functionally interchangeable on this rule. |
| 5 | `stop_loss_pct` | 0.08 | A round 8% stop. Sized knowing the brief's warning that stops are checked against the *previous close*, not the intraday low, so realized losses will sometimes run past this — this is a nominal risk unit, not a guarantee. |
| 6 | `take_profit_pct` | 0.20 | A round 20% target, giving a 2.5:1 planned reward:risk, consistent with a strategy that expects a lower hit rate than a mean-reversion rule and needs asymmetric payoff to be worth trading. |
| 7 | `max_hold_days` | 60 | ~3 months. Enough time for a volatility-expansion move to play out without turning a swing trade into an unbounded buy-and-hold position; also the primary exit mechanism since `exit` is empty. |
| 8 | `max_positions` | 4 | Two-thirds of the 6-symbol universe; leaves room for more than one squeeze to be live at once without concentrating in a single name. |
| 9 | `position_pct` | 0.25 | `4 × 0.25 = 1.00`, uses the full book when fully invested. **This does not rely on the round's 100%-single-name-cap relaxation** — 0.25 is exactly the persona's normal real-world single-name cap, so the card would run identically if that relaxation were withdrawn. |

**Total: 9 of 10.** `exit` is deliberately empty (0 literals) — the position closes on
`stop_loss_pct`, `take_profit_pct`, or `max_hold_days`, all of which are already counted above, so
adding a discretionary exit expression would only spend budget without changing the exit logic much
(a squeeze-breakout thesis doesn't have an obvious independent exit signal beyond "the move ran out
of room or time"). I kept one parameter of headroom deliberately rather than spending it on a
tunable-looking addition.

## What I measured in the design window, and the code I ran

Script: `.scratch/c02-volatility/analysis.py` (read-only DuckDB connection, bounded to
`end=2026-02-13`, the design cutoff). For each universe symbol, it computes the entry condition
(`close crosses_above bb_upper(20,2.0) and atr(14) < atr(50)`) over the symbol's full available
history through the cutoff, counts how many times it fires, and looks at the raw forward 20-session
return after each firing (descriptive only — this is not a parameter search, and the 20-day window,
target, and stop are not tuned against these numbers).

Results (`n_signals` at `atr_long=50`, the value in the card):

| symbol | bars | n_signals | fwd 20d mean | fwd 20d median | hit rate (fwd>0) |
|---|---|---|---|---|---|
| SPY | 8,318 | 176 | +0.32% | +1.03% | 63.1% |
| QQQ | 6,776 | 140 | +0.62% | +1.29% | 65.0% |
| DIA | 7,062 | 124 | +0.09% | +0.60% | 58.1% |
| IWM | 6,468 | 108 | −0.11% | −0.23% | 49.1% |
| XLF | 6,828 | 137 | −0.16% | +0.33% | 54.7% |
| XLE | 6,828 | 126 | +0.10% | −0.21% | 48.4% |

Honest reading: SPY and QQQ show a small, consistent positive edge on this raw diagnostic. DIA is
weakly positive. IWM and XLE are flat to slightly negative on this particular 20-day-forward
measure. **I did not drop IWM/XLF/XLE for this** — doing so after seeing this table would be
exactly the kind of post-hoc, results-driven universe pruning the brief warns against for
parameters, and I don't think the distinction between "pruning a parameter" and "pruning a
universe member" based on a backtest number is a meaningful one. 108–140 signals per symbol over
20–30 years is also not a lot of evidence to declare the mechanism absent in three names and
present in three others; the option-selling/dealer-hedging flow this thesis relies on is
structurally present in all six. The honest statement is: the raw signal is stronger in the
broadest, most liquid index proxies (SPY, QQQ) than in the sector- or style-tilted ones (IWM, XLF,
XLE) in this diagnostic, and that may or may not hold up out of sample.

## Sensitivity check

I varied the long ATR baseline (the one number in the rule with any real "which value" judgment
behind it) across 40 / 50 / 60 sessions and re-ran the signal count on every symbol, without
touching anything else:

- SPY: 175 / 176 / 176 signals
- QQQ: 139 / 140 / 137 signals
- DIA: 126 / 124 / 125 signals
- IWM: 109 / 108 / 107 signals
- XLF: 135 / 137 / 139 signals
- XLE: 122 / 126 / 124 signals

Signal counts move by at most 2–5 out of 100+ across a 50%-wide range of the parameter (40 to 60),
and the forward-return means/medians move in the same small way (see script output). This is what
insensitivity looks like: the rule is not perched on a specific ATR-baseline value, and I would not
expect a materially different card if I had picked 40 or 60 instead of 50.

I also computed, at each ATR baseline, the raw breakout count with the squeeze filter removed
entirely (`close crosses_above bb_upper(20,2.0)` alone) as a sanity check: 258 (SPY), 202 (QQQ),
197 (DIA), 180 (IWM), 209 (XLF), 221 (XLE). The squeeze filter cuts roughly a third of raw
breakouts across every symbol, consistently — it is doing something, not degenerating to
"always true" or "never true."

## What I tried and abandoned

- **Gating a tradeable name's entry on `^VIX`.** The two discipline-specific notes for this round
  say `^VIX` and `^TNX` have full-history bars and the DSL can read `close` on them like any other
  symbol, but that holding `^VIX` is not realistic and that the engine evaluates entry/exit
  per-symbol against that symbol's own bars. I confirmed this against `app/rules/nodes.py` and
  `app/backtest/guards.py`: every `NumExpr`/`BoolExpr` node (`PriceRef`, `IndicatorRef`, `Arith`,
  `Comparison`, `Cross`, `Not`, `BoolOp`) resolves against a single bars frame passed to the
  evaluator for one symbol — there is no node that can join two different symbols' series into one
  expression. **What I could express:** a rule that trades `^VIX` itself using its own close (not
  useful, since it isn't a position you can actually hold). **What I could not express:** "buy SPY
  when `^VIX` is elevated" or any other cross-symbol regime gate as a single DSL rule — there is no
  mechanism in the grammar to reference a second symbol's bars from within one symbol's rule. I
  therefore abandoned VIX-gating entirely and used `atr(14)/close`-style intrinsic volatility
  instead (realized on the traded symbol's own bars), per the round notes' suggestion that this
  arithmetic is verified to pass the guard. In this card I use the raw `atr(14)` vs `atr(50)`
  comparison rather than dividing by `close`, because both sides of the comparison are ATR on the
  *same* symbol and the same units cancel — the `atr/close` normalization matters when comparing
  volatility *across* symbols (e.g. inside a `thesis` discussion), not when comparing a symbol's own
  short- and long-run ATR to each other.
- **Band-width contraction relative to its own history** (a literal Bollinger "squeeze": band width
  now vs. band width's own rolling average) — not expressible. `sma()`/`ema()` take an integer
  period argument, not an arbitrary sub-expression, so there is no way to compute a moving average
  of `bb_upper - bb_lower`. I used the `atr(14) < atr(50)` comparison as the closest expressible
  proxy for "volatility is currently compressed relative to its recent baseline."
  the same idea using two independent indicator calls instead of an indicator applied to a derived
  series.
- **A discretionary exit rule** (e.g. `close crosses_below bb_mid(20,2.0)`) instead of relying on
  the stop/target/time-cap trio. I decided against it — it would have cost 2 more parameters
  against the budget of 10 for a mean-reversion-flavored exit that sits awkwardly against a
  breakout-continuation thesis, and `max_hold_days` already bounds how long a failed breakout can be
  held.
- **A tighter stop (e.g. 5%) to raise the reward:risk ratio.** I decided against tuning this up —
  the brief's own worst-trade example (19.9% loss against a 12% stop, because stops are checked
  against the previous close, not the intraday low) argues for leaving room rather than shrinking
  the stop to make the planned RRR look better on paper.

## Weakest assumption

The single weakest assumption is that `atr(14) < atr(50)` at the moment of a band breakout is a
good enough proxy for "the options market has not yet repriced this move" — it is a price-only,
backward-looking measure of realized volatility with no direct link to implied volatility, open
interest, or dealer positioning, so the causal story (short-gamma hedging flow) is inferred from
price behavior alone and cannot be verified with what the DSL can read.
