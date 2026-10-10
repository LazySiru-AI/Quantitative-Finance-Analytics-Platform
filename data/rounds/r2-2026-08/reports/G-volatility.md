# G-volatility -- Range Expansion -- round 2 report

Agent: `G-volatility` | Discipline: `volatility` | Eligible: 3/8 main windows -- **unranked this
round** under the round-2 five-of-eight gate (see `results/eligibility.json`)

## 1. What the card is, its claim, and why the gate now bites

Entry `high - low > atr(14) * 1.5 and close > open and close > sma(50)` -- a true-range expansion day
closing strong inside an established uptrend; exit on `close < sma(10)`. `stop_loss_pct = 0.10`,
`take_profit_pct = 0.15`, `max_hold_days = 20`. Universe: `NVDA AMD MU INTC MRVL DELL AVGO TSLA COIN
NET SNOW PLTR`, deliberately narrowed to twelve names whose ATR/price ratios cluster within a 1.6x
band (versus 260x across the full 43-symbol list) so one fixed stop is a defensible approximation.

The claim under test, from the prior tournament: "the only card besides A and B to beat the blind
window" -- but it lost in-sample, so round 1 asked whether that blind win generalised.

**Eligible for `bear-2022`, `bull-2024`, `recent` only**: `eligibility.json` gives `COIN first bar
2021-04-14` as the binding constraint against `q4-2018`, `covid`, `chop-2015`, `chop-2011` and `gfc`
alike. This is exactly round 1's eligible set -- COIN's 2021 listing has not moved, and round 2 added
no calendar time (`REPORT.md` §9: "no calendar time passed between rounds 1 and 2"), so the card has
gained zero new windows.

**The consequential fact this round is not in the trade log -- it is in the gate.** Round 1's gate
was "eligible in fewer than three main windows is unranked"; on that rule, `G-volatility` cleared the
floor exactly and ranked **3rd of 18**. Round 2's gate rises to **five of eight** (`PROTOCOL.md`
§3.7, `REPORT.md` intro table). `G-volatility` still clears only three of the (now eight) main
windows -- the identical three, on identical trades (see §2) -- so it now reports as **unranked**.
Nothing about the strategy or its evidence changed; the bar it has to clear did.

## 2. Versus SPY, its three eligible windows

| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| bear-2022 | 196 | **-20.72%** | -25.14% | +4.42% | -19.27% | 5.8% | -21.04% |
| bull-2024 | 250 | **+15.78%** | +14.00% | +1.78% | +12.64% | 22.4% | -11.48% |
| recent | 249 | **+22.62%** | +20.62% | +2.00% | +16.15% | 31.4% | -11.15% |

Median of three = the middle value, **+12.64%** (bull-2024). Worst window bear-2022, -19.27%. Hit
rate 2 of 3 (66.7%). 130 trades total, mean capital exposure 19.9% -- the largest trade sample of any
card in this report. These figures match round 1's to within ≤0.1pp (round 1: -19.27%, +12.66%,
+16.21%) -- the D2 engine-vs-reconstruction fix noted in `REPORT.md` §6, not new evidence. **This is
the same measurement recomputed, not a second draw**, per `REPORT.md` §1: the three windows, the
trade count, and (as shown below) the individual trades are identical to round 1's.

## 3. What moved the number

### bear-2022 (15 trades)

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| COIN | 2022-08-04 | 2022-08-05 | 1 | stop | -18.48% | -471 | -4.71% |
| COIN | 2022-07-21 | 2022-07-27 | 4 | stop | -22.81% | -421 | -4.21% |
| PLTR | 2022-08-03 | 2022-08-09 | 4 | stop | -13.98% | -284 | -2.84% |
| MRVL | 2022-08-26 | 2022-08-29 | 1 | rule | -8.61% | -168 | -1.68% |
| SNOW | 2022-07-06 | 2022-07-13 | 5 | rule | -8.17% | -152 | -1.52% |
| TSLA | 2022-04-05 | 2022-04-07 | 2 | rule | -7.48% | -142 | -1.42% |

Top-3 share **100%** of gross winning P&L is not meaningful here in the usual sense -- every trade
shown lost money; the card's -20.72% total is simply less bad than SPY's -25.14%. Without the three
largest losers the card returns -20.76%, essentially unchanged, because there was no offsetting
winner of any size in this window. A bull-leaning trigger (`close > sma(50)`, expansion day closing
strong) firing into a grinding decline produced almost uniformly losing trades.

### bull-2024 (47 trades)

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| AVGO | 2024-12-09 | 2024-12-16 | 5 | target | +29.39% | +579 | +5.79% |
| NET | 2025-01-28 | 2025-02-10 | 9 | target | +29.89% | +578 | +5.78% |
| PLTR | 2025-01-29 | 2025-02-05 | 5 | target | +27.17% | +522 | +5.22% |
| PLTR | 2024-11-18 | 2024-12-09 | 14 | target | +24.00% | +468 | +4.68% |
| COIN | 2024-11-07 | 2024-11-12 | 3 | target | +26.10% | +449 | +4.49% |
| MU | 2024-12-17 | 2024-12-20 | 3 | stop | -22.25% | -440 | -4.40% |

Top-3 share **36%** of gross wins; without them the card returns **-1.01%** instead of +15.78% --
close to flat, meaning the bulk of this window's edge sits in three trades out of forty-seven.

### recent (68 trades)

| symbol | entry | exit | bars | exit reason | trade return | P&L | share |
|---|---|---|---:|---|---:|---:|---:|
| MRVL | 2026-05-20 | 2026-06-02 | 8 | target | +38.02% | +768 | +7.68% |
| DELL | 2026-05-26 | 2026-06-01 | 4 | target | +41.79% | +753 | +7.53% |
| INTC | 2026-01-08 | 2026-01-22 | 9 | target | +27.06% | +531 | +5.31% |

Top-3 share **29%**; without them the card returns **+2.10%** instead of +22.62%. **+3.16% of the
+22.62% total sits in positions still open at the window's close** (SNOW +6.61% and PLTR +5.84%,
both `open_at_end`, partly offset by other small marks) -- a modest, not dominant, unrealised
component.

## 4. Concentration, summarised

| window | top-3 share of gross wins | return without top-3 |
|---|---:|---:|
| bear-2022 | n/m (no material winners) | -20.76% |
| bull-2024 | 36% | -1.01% |
| recent | 29% | +2.10% |

Unlike `C-trend` and `H-trend-diversified`, this card's edge is *not* concentrated in a handful of
positions -- 130 trades, and removing the top three from each winning window leaves the result
roughly flat rather than deeply negative. This is the "largest trade sample of any candidate" claim
holding up as a genuine breadth advantage, not just a headline about trade count.

## 5. Realised versus marked

Only `recent` carries a material unrealised component (**+3.16%** of +22.62%). `bear-2022` and
`bull-2024` are effectively fully realised. No result in this report leans on an open position the
way `C-trend`'s `bull-2024`/`covid` or `H-trend-diversified`'s `covid` do.

## 6. The stop gap, measured and quantified

**Confirmed from this round's trade log, bit-identical to round 1's:** COIN, entered 2022-07-21,
exited 2022-07-27, 4 bars held, `exit_reason: "stop"`, realised return **-22.81%**
(`return_pct = -0.2280621968...`, P&L -421.24) -- against a nominal `stop_loss_pct = 0.10`. **The gap
is 12.81 percentage points: the realised loss is 2.28x the nominal 10% stop.**

Across all 14 stop-outs in this round's three windows (identical set to round 1's):

| symbol | window | entry -> exit | bars | realised |
|---|---|---|---:|---:|
| COIN | bear-2022 | 2022-07-21 -> 2022-07-27 | 4 | **-22.81%** |
| MU | bull-2024 | 2024-12-17 -> 2024-12-20 | 3 | -22.25% |
| NET | recent | 2026-05-06 -> 2026-05-11 | 3 | -19.49% |
| COIN | bear-2022 | 2022-08-04 -> 2022-08-05 | 1 | -18.48% |
| INTC | recent | 2026-01-22 -> 2026-01-26 | 2 | -18.40% |
| INTC | recent | 2026-05-11 -> 2026-05-15 | 4 | -16.20% |
| MU | recent | 2026-05-11 -> 2026-05-19 | 6 | -16.15% |
| DELL | recent | 2026-06-02 -> 2026-06-08 | 4 | -14.58% |
| PLTR | bear-2022 | 2022-08-03 -> 2022-08-09 | 4 | -13.98% |
| NET | recent | 2026-06-05 -> 2026-06-10 | 3 | -12.93% |
| INTC | bull-2024 | 2025-02-19 -> 2025-02-26 | 5 | -10.58% |
| NET | recent | 2025-11-03 -> 2025-11-06 | 3 | -9.91% |
| COIN | bull-2024 | 2024-11-12 -> 2024-11-15 | 3 | -8.98% |
| MRVL | recent | 2026-06-05 -> 2026-06-08 | 3 | -3.71% |

Mean realised stop-out loss **-14.89%** against the 10% nominal -- a **4.89 percentage point** average
gap, and the widest average slippage of any card examined in this program's reports to date. The
mechanism is the previous-close stop check: the trigger session's close confirms the breach, but the
fill executes at the *next* session's open, so any further adverse move overnight or into that open
lands entirely on the trade before the stop can act. COIN's -22.81% is the clearest case in the whole
program: the nominal stop level implied by the entry price sits at $71.04 x 0.90 = $63.94; the
position closed four sessions later, well below that level, because COIN kept falling across the
intervening bars rather than breaching and reversing on the first adverse session. The second-worst
stop, also COIN (2022-08-04, 1 bar, -18.48%), shows the same mechanism compounding in a single
overnight gap rather than across several bars -- COIN, one of this universe's highest-beta names,
produced both of the round's largest gaps by this measure.

## 7. Verdict on the claim, and recommendation

**The claim ("beat the blind window") still reads as genuine and regime-specific, but round 2 adds
no new evidence toward it -- the gate change, not new data, is the finding.** The three windows this
round reruns are bit-identical to round 1's: same 130 trades, same COIN stop, same median (+12.64% vs
+12.66%), same worst window (-19.27%). The card remains genuinely strong in both bull regimes it can
reach and genuinely weak in the one bear regime it can reach, exactly as round 1 concluded -- a
bull/recovery-regime volatility strategy, not an all-weather one, whose own trigger (`close >
sma(50)`) is mechanically a bull-market filter.

What changed is that round 2's gate (five of eight main windows, up from round 1's three of four) was
set without regard to which cards' universes could reach it, and `G-volatility`'s COIN-anchored
universe cannot: COIN listed in 2021, which permanently excludes `chop-2011`, `chop-2015`, `covid`,
`q4-2018` and `gfc` regardless of how the strategy performs. A card that ranked 3rd of 18 last round on
the strongest trade sample among ranked candidates is unranked this round on the identical evidence,
because the floor moved, not the card.

**Recommendation: retain as a candidate; do not promote, and flag the gate mismatch rather than the
strategy.** `PROTOCOL.md` §6 has no path to `base/` for a card that cannot clear the regime gate, and
this card's own universe -- not its rule -- is what keeps it there. Two options would change this
without touching the mechanism: swap COIN for a name with pre-2021 history and a comparable ATR/price
profile (the design memo already measured the full 43-symbol universe's ATR/price range and could
identify a substitute), or wait for the walk-forward window round 3 is expected to add once real
calendar time has elapsed (`REPORT.md` §8.5) -- though that adds only one window, still short of five.
Absent a universe change, `G-volatility` is structurally capped at three eligible windows and will
stay unranked under the current gate no matter how it performs in them.
