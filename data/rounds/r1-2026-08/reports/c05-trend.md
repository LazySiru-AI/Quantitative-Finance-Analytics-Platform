# c05-trend — Cross-Asset 200dma Trend

Rank: **14th of 18** on the official scorecard (median adjusted excess across all five main
windows). Ranked and eligible in all five windows — the simplest card in the field, and the only
thing tested is a single convention (`sma(200)` crossing) applied independently to three
structurally different assets.

## 1. What the card was

The rule is trivial by design: go long a symbol on `close crosses_above sma(200)`, exit on
`close crosses_below sma(200)`, applied identically and independently to `SPY`, `TLT`, and `GLD` — no
cross-sectional comparison between the three (the engine has none to give). Five parameters against a
budget of ten. The thesis mechanism is that the 200-day average is one of the few technical levels a
large, identifiable population (CTAs, trend-following funds, technically-oriented traders) mechanically
watches and reacts to together, so a break triggers correlated follow-on flow rather than noise; the
counterparty is structurally slow money — scheduled index/401k flows and disposition-effect holders —
that cushions fills on the way down and lets a nascent trend build before it chases on the way up. The
cross-asset element is the second half of the thesis: `SPY` (equity beta), `TLT` (rate risk) and `GLD`
(a non-yielding hard asset) were chosen, per the memo's own correlation study, specifically because they
are the only categories the author measured with genuinely low or negative correlation to `SPY`
(`TLT` ≈ −0.30 full-history, `GLD` ≈ +0.05) — every equity-flavored alternative tested (`EFA`, `EEM`,
`FXI`, sector ETFs) ran 0.4–0.87 correlated, i.e. the same trade in a different costume.

## 2. Results across all five windows

All figures use the corrected metrics from `DEFECTS.md`: `corrected_return = ending_equity /
starting_equity − 1`, `capital_exposure = Σ(quantity × entry_price × bars_held) / (sessions ×
starting_equity)`, `adjusted_excess = corrected_return − capital_exposure × benchmark_return`.
`session_exposure` is the runner's raw (defective) exposure figure, shown for comparison. (The raw
`total_return` field happens to match `corrected_return` bit-for-bit in every window for this card —
no first-session fill artifact — so D1 does not move any number below, unlike some other cards in the
field.)

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gfc | 20 | −1.15% | −56.23% | +55.08% | **+9.62%** | 19.16% | 46.07% | −6.65% | 11.11% |
| covid | 6 | +2.51% | −8.71% | +11.22% | **+5.31%** | 32.18% | 76.34% | −2.80% | 50.00% |
| bear-2022 | 13 | −3.94% | −25.14% | +21.20% | **+0.84%** | 19.02% | 49.49% | −6.22% | 15.38% |
| bull-2024 | 6 | +0.30% | +14.00% | −13.70% | **−0.99%** | 9.21% | 31.60% | −2.65% | 0.00% |
| recent | 5 | +1.71% | +20.62% | −18.91% | **−2.70%** | 21.39% | 71.89% | −3.00% | 0.00% |

Median adjusted excess **+0.84%**, worst **−2.70%** (`recent`), best **+9.62%** (`gfc`), IQR **6.30
points**, hit rate 3 of 5 windows positive (60%), 50 trades total. The pattern is coherent rather than
random: positive adjusted excess in every window where the benchmark itself was negative (`gfc`,
`covid`, `bear-2022`), negative in both windows where the benchmark was strongly positive (`bull-2024`,
`recent`). This is exactly what a trend book with no short side should look like — it earns in crises
and bleeds in bull markets — and it is the intended trade-off, not a defect.

## 3. The pre-registered failure regime versus what happened

The memo's call, verbatim: *"COVID (`covid` window): fast crash-and-snapback... `close
crosses_below sma(200)` will confirm the crash only after most of the initial drop has already
happened, and `close crosses_above sma(200)` will confirm the recovery only after much of the snapback
has already happened. I expect this window to be this card's worst result."* The memo also
pre-registered the opposite call for `bear-2022`: *"the window I expect this design to defend best...
a slow decline gives a slow signal time to confirm and get out before most of the damage."*

**The `covid` prediction is contradicted by the result.** `covid` produced +5.31% adjusted excess —
the card's **second-best** window, not its worst. The trade log is consistent with the mechanism story
being directionally right about *speed* (the `SPY` entry on 2020-03-05 was cut the very next session at
−3.98% as the crash accelerated, and `GLD`'s late-March entry rode the recovery for +8.98% still open
at window end) but the net effect of "slow in, slow out" on three assets whose signals do not fire
together was still a positive outcome, because `TLT` and `GLD` did not crash on the same calendar days
`SPY` did. The actual worst window is `recent` (−2.70%), a **bull** window the memo did not name as a
risk at all — the card underperformed there for the ordinary reason a trend book underperforms a
strong, low-chop uptrend: few crossing events, small positions relative to the benchmark's move.

The `bear-2022` prediction fares better but is not exactly right either: the window is positive
(+0.84%) as predicted, but it ranks **third**, behind both `gfc` and `covid`, not first. Read together,
these two misses suggest the dominant driver of this card's window-to-window variance is simply the
**sign of the benchmark's move**, not the crash's speed the memo's mechanism story emphasizes — the
card does well whenever the benchmark falls and poorly whenever it rises strongly, regardless of
whether the decline was a V-shock or a grind.

## 4. Trade-level detail

**Exit-reason distribution per window** (no `stop`, `target`, or `time` exits occurred anywhere for
this card — every position closed via the rule itself or was still open at window end):

| window | rule | open_at_end |
|---|---:|---:|
| gfc | 18 | 2 |
| covid | 4 | 2 |
| bear-2022 | 13 | 0 |
| bull-2024 | 5 | 1 |
| recent | 4 | 1 |

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| gfc | TLT, 2008-11-05 → open at end, +9.17% (+$296.14) | GLD, 2008-10-09 → 2008-10-13, rule, −4.31% (−$135.45) |
| covid | GLD, 2020-03-24 → open at end, +8.98% (+$303.38) | SPY, 2020-03-05 → 2020-03-06, rule, −3.98% (−$121.38) |
| bear-2022 | GLD, 2022-02-07 → 2022-05-11, rule, +1.70% (+$54.82) | SPY, 2022-02-01 → 2022-02-14, rule, −2.49% (−$78.56) |
| bull-2024 | SPY, 2025-05-13 → open at end, +9.32% (+$272.05) | TLT, 2025-04-07 → 2025-04-08, rule, −2.93% (−$94.24) |
| recent | SPY, 2026-04-09 → open at end, +13.67% (+$369.08) | TLT, 2026-01-15 → 2026-01-20, rule, −2.36% (−$77.43) |

**Stop-outs against the nominal 12% stop: none.** `stop_loss_pct = 0.12` never bound in any of the 50
trades across all five windows. The worst single trade of the entire card, across every window, lost
4.31% (`GLD`, `gfc`) — less than half the stop's threshold. The 200dma crossing exit is consistently
faster than a 12% adverse move, which means the stop is decorative for this design as configured; it
would have to be tightened by roughly an order of magnitude before it would ever fire ahead of the
rule-based exit, and there is no evidence in these five windows of what that would cost.

## 5. Defended versus abstained

Capital exposure ranges from 9.21% (`bull-2024`, the lowest) to 32.18% (`covid`, the highest); trade
count ranges from 5 (`recent`) to 20 (`gfc`). The card is most active and most capitally committed in
the two crisis windows (`gfc`, `covid`), where the crossing rule fires more often as volatility rises,
and least committed in `bull-2024`, where a persistent uptrend with little chop produces few crossing
events at all. `recent` is a partial exception: only 5 trades and moderate capital exposure (21.39%),
but a high session exposure (71.89%) — a small number of large, long-held positions rather than
frequent turnover. Across all five windows, capital exposure never exceeds a third of the book; this
reads as genuine, moderate defense (positions taken and held through the move) in `gfc` and `covid`
rather than either full commitment or pure abstention.

## 6. Verdict

The card ranks below the field median (14th of 18) on a thin edge — +0.84% median adjusted excess,
positive in only 3 of 5 windows — but the edge is coherent and explainable rather than a fitted
artifact: it is the simplest card in the round (5 of 10 parameters), it earns exactly in the regimes
where its mechanism predicts it should (falling benchmarks), and it gives that back exactly in the
regimes it should (strongly rising benchmarks). The one clear miss is the pre-registration itself — the
author called `covid` as the worst window on a "slow signal, fast crash" argument, and the actual worst
window was a bull market the memo never named as a risk. That miss is informative on its own: it
suggests the card's real fault line is benchmark direction, not crash speed, which is a cleaner and
more useful characterization for anyone deciding whether to hold this alongside a directional card.

**Promote, conditionally.** Not as a standalone alpha card — a +0.84% median edge on 50 trades is not
distinguishable from noise by itself — but as a low-correlation, thesis-consistent hedge sleeve: it
loses less than the benchmark in every falling-market window measured and gives back a bounded,
explicable amount in strong bull markets. Its main value is what it does next to a more aggressive,
higher-beta card, not what it does alone.

**Most valuable variant to test next round:** the confirmation filter the memo considered and
abandoned — `close > sma(50) and sma(50) > sma(200)` — aimed specifically at the small, repeated
whipsaw losses that drag down `bear-2022` and `bull-2024` (win rates of 15.4% and 0.0% despite positive
or near-flat net results). Since the stop never binds for this design, tightening it would not change
behavior; the entry side is the only lever this card has left within its own logic, and the whipsaw
losses — not the tail risk the stop was sized against — are what a variant should target.
