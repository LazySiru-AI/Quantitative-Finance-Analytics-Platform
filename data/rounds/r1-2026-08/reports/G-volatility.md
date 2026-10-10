# G-volatility — competition report

`G-volatility`, "G - Range expansion: beat the blind window" (discipline: `volatility`), ranked **3rd
of 18** ranked cards on median `adjusted_excess` (**+12.66%**) — the strongest result of the six
candidates in this report. It also carries the round's single largest stop-slippage event: a nominal
10% stop that realised a **−22.81%** loss.

## 1. What the card is, and why it could run in only three windows

Entry is `high - low > atr(14) * 1.5 and close > open and close > sma(50)` — a true-range expansion
day, closing strong, inside an established uptrend; exit on `close < sma(10)`. `stop_loss_pct = 0.10`,
`take_profit_pct = 0.15`, `max_hold_days = 20`. Universe: `NVDA AMD MU INTC MRVL DELL AVGO TSLA COIN
NET SNOW PLTR`, deliberately narrowed (per the card's own thesis) to twelve names whose trailing
ATR/price ratios cluster between 3.68% and 5.98% — a 1.6x spread, against a 260x spread across the
full 43-symbol universe — so that one fixed stop and one fixed size are a defensible approximation.

**Eligible for `bear-2022`, `bull-2024`, `recent` only**: `eligibility.json` gives `COIN first bar
2021-04-14, needs <= 2007-06-02` for `gfc` and `needs <= 2019-10-13` for `covid`. COIN's 2021 listing
blocks both pre-2022 regimes. It cleared `bear-2022` itself (`needs <= 2021-01-21`; COIN's 2021-04-14
first bar is late enough to still qualify, since that window's deadline is comfortably before COIN's
listing) plus both bull windows.

## 2. Results across its eligible windows

| window | trades | corrected return | benchmark | excess | adj. excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| bear-2022 | 15 | −20.72% | −25.14% | +4.42% | **−19.27%** | 5.77% | 22.45% | −21.04% | 13.33% |
| bull-2024 | 47 | +15.78% | +14.00% | +1.78% | **+12.66%** | 22.27% | 58.80% | −11.48% | 44.44% |
| recent | 68 | +22.62% | +20.62% | +2.00% | **+16.21%** | 31.09% | 76.71% | −11.15% | 35.94% |

**Median adjusted excess +12.66% (bull-2024, the middle value of three), IQR 17.88 points (span from
−19.27% to +16.21%), hit rate 66.7% (2 of 3 positive), 130 trades total** — the largest trade sample
of any of the six candidate cards ranked in this report (`C-trend` 41, `H-trend-diversified` 36), and
among the larger samples in the full 19-card ranked field.

## 3. Verdict on the claim

The card's own framing was "the only card besides A and B to beat the blind window" in the prior
tournament, with the caveat that it lost in-sample. This round's evidence is consistent with that
shape but sharper: `G-volatility` is genuinely strong in both bull regimes (+12.66%, +16.21%) and
genuinely weak in the one bear regime it could reach (−19.27%). That is not the profile of a card that
"beat the blind window" by chance — a true-range-expansion trigger confirmed by trend (`close >
sma(50)`) is mechanically a bull-regime signal: expansion days closing strong, inside an uptrend, are
by construction rarer and less reliable in a grinding decline, which is exactly what `bear-2022`
produced. The median across three windows is positive and the largest single trade sample of the
field's ranked candidates gives that median real statistical weight, but the −19.27% worst window is
not noise around an otherwise-flat mechanism — it is the same mechanism working in reverse under a
regime it was never built to handle. The claim holds with a caveat the card's own design predicts: this
is a bull/recovery-regime volatility strategy, not an all-weather one, and its one bear-window result
says so directly.

## 4. Trade-level detail

**Exit-reason distribution:**

| window | rule | stop | target | open_at_end |
|---|---:|---:|---:|---:|
| bear-2022 | 12 | 3 | 0 | 0 |
| bull-2024 | 33 | 3 | 9 | 2 |
| recent | 41 | 8 | 15 | 4 |

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| bear-2022 | INTC, 2022-01-25→2022-01-26, +0.11% | COIN, 2022-07-21→2022-07-27, −22.81% (stop) |
| bull-2024 | NET, 2025-01-28→2025-02-10, +29.89% | MU, 2024-12-17→2024-12-20, −22.25% (stop) |
| recent | DELL, 2026-05-26→2026-06-01, +41.79% | NET, 2026-05-06→2026-05-11, −19.49% (stop) |

In `bear-2022` the "best" trade barely broke even (+0.11%) — every other trade in that window lost
money, consistent with a bull-leaning trigger firing into a regime it was not built for.

**All 14 stop-outs, nominal `stop_loss_pct = 0.10`:** mean realised loss **−14.89%**, a gap of **4.89
percentage points** beyond the nominal 10% level — the widest average slippage of any card in this
report. **Confirmed: COIN, entered 2022-07-21 at $71.04, exited 2022-07-27 at $54.84 (4 bars held,
`exit_reason: "stop"`), realised return −22.81% (`return_pct = -0.2280621968...` in the trade log)** —
against a nominal 10% stop, more than double the intended loss and the single worst stop-out of any
card examined for this report. The nominal stop level implied by the entry price is $71.04 × 0.90 =
$63.94; the trade closed 4 sessions later at $54.84, roughly 14% below that level. This is the
previous-close mechanic (WINDOWS.md, "Execution") in its most extreme form in this round's data: the
stop is evaluated against the prior session's close, not the intraday low, so a name that gaps or
grinds down across several sessions before the close finally confirms the breach can carry the
position well past its nominal stop level before the exit executes — and COIN, one of this universe's
higher-beta names, produced the round's clearest example of that gap compounding over multiple bars
rather than resolving on the first adverse session.

The second-worst stop, also COIN (2022-08-04→2022-08-05, 1 bar, −18.48%), shows the same mechanism can
also produce a large gap in a single session — a wide overnight or single-day move past the stop level
confirmed at the very next close.

## 5. Rankable, and where it stands

Yes. Three of five main windows run, clearing the gate exactly at its minimum. Ranked 3rd of 18 —
behind only the `B2-hold-90` and `B3-concentrated` momentum variants, and ahead of every trend and
risk-managed card in the field, on the strength of a wide but genuinely two-sided distribution rather
than a single spectacular window.

## 6. Recommendation

**Retain as a candidate; a strong candidate for promotion pending a second positive round.**
PROTOCOL.md §6 requires two consecutive rounds with a positive median on differing window sets before
`candidates/` → `base/`. This round supplies the first: a positive median (+12.66%), the field's
third-best rank, and the largest trade sample among the round's ranked candidates. The −19.27%
`bear-2022` result and the −22.81% COIN stop-slippage are not reasons to hold the card back — they are
exactly the kind of worst-case evidence PROTOCOL.md §4 asks every report to carry beside the headline,
and they are consistent with what the card's own design predicts about its weak regime. If round 2's
walk-forward window and the existing three windows produce another positive median, `G-volatility`
should move to `base/` on schedule.
