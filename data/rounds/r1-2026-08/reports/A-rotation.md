# A-rotation — Semis Breadth-Capped Rotation

Rank: **10th of 18** on the round's ranking (median adjusted excess). Ranked and eligible in all four
windows it can legally trade. **Blocked from `gfc`**: the universe includes AVGO, whose first bar is
2009-08-06, later than the `gfc` window's design cutoff requires (`<= 2007-06-02`). This holds for
every card in the A family — none of the five could run `gfc` this round.

## 1. What the card is

The card applies one absolute condition — close above its own 50-day SMA with RSI(14) between 55 and
80, i.e. a confirmed, non-extreme uptrend — identically across a 9-name cyclical-semiconductor
universe (`NVDA AMD MU INTC MRVL AVGO TSM QCOM SOXX`), and caps concurrent holdings at 3 of 9. Exit
is trend break or momentum fade (`close < sma(50) or rsi(14) < 45`), backstopped by a 12% stop and a
20% take-profit, with a 120-day hold cap and 30% position sizing. The engine has no cross-sectional
comparison, so "rotation" here means only the 3-of-9 cap; when more than three names qualify on one
session, the broker fills in the order the universe array is written, which is not a strength
ranking.

The card's own author measured mean pairwise daily-return correlation of **0.589** across the nine
names (range 0.286 INTC/AVGO to 0.824 SOXX/TSM) over the trailing ~253 sessions through the design
cutoff, and stated plainly that this is "a concentrated sector bet dressed as a 3-of-9 rotation, not
a diversified basket." That self-assessment is the right frame for reading everything below: this
card does not diversify across nine names so much as take one levered bet on the semiconductor/AI-
capex cycle, sized in three tranches.

Four variants isolate one decision each against this card: `A1-alpha-order` reorders the universe
only (a pure control, reproducing the tournament-submitted card exactly); `A2-cash-headroom` trades
4 slots at 22% instead of 3 at 30%; `A3-no-target` removes the 20% take-profit; `A4-tight-stop` cuts
the stop to 8% from 12%. Their reports carry the head-to-head detail; this report gives the base
numbers and, since A1 changes nothing but order, uses it to measure how much of any variant's margin
is signal versus reshuffling artifact.

## 2. Results across the four windows

All figures use the corrected metrics from `DEFECTS.md`: `corrected_return = ending_equity /
starting_equity − 1` (not the runner's `total_return`, which is rebased to the first session's close
and is wrong for exactly this kind of card — see below), `capital_exposure = Σ(quantity ×
entry_price × bars_held) / (sessions × starting_equity)` (not the runner's `exposure`, which only
counts sessions holding *something*), and `adjusted_excess = corrected_return − capital_exposure ×
benchmark_return`.

| window | trades | corrected return | benchmark | excess | adjusted excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| covid | 13 | +0.46% | −8.71% | +9.17% | **+4.85%** | 50.38% | 73.12% | −17.85% | 30.00% |
| bear-2022 | 22 | −33.27% | −25.14% | −8.13% | **−27.41%** | 23.34% | 44.39% | −34.55% | 13.64% |
| bull-2024 | 39 | +10.74% | +14.00% | −3.26% | **+1.60%** | 65.29% | 88.40% | −22.88% | 27.78% |
| recent | 47 | +95.28% | +20.62% | +74.66% | **+80.32%** | 72.55% | 95.58% | −13.24% | 54.55% |

Median adjusted excess **+3.23%** (between covid and bull-2024), worst **−27.41%** (bear-2022), best
**+80.32%** (recent), IQR **29.37 points**, hit rate 3 of 4 windows positive. 121 trades total.
Capital exposure runs 21–24 points below session exposure in every window (e.g. bear-2022: 23.34%
capital vs 44.39% session) — the same D2 pattern the program's defect log documents elsewhere:
counting *any* session with an open lot overstates how much capital was actually at risk, here by a
consistent margin regardless of regime.

**D1 matters most for exactly this card.** The runner's raw `total_return` reports covid as
**−0.65%**; the true figure, `ending_equity / starting_equity − 1`, is **+0.46%** — a sign flip. This
card fills on session one about as often as any card in the round, because the design cutoff sits
right at the entry threshold for several universe names, so it is the family hit hardest by the
defect. Every number in the table above uses the corrected figure.

## 3. Anchor for the variant family — the ordering-noise floor

`A1-alpha-order` is byte-identical to this card except for the order symbols are listed in
(`AMD AVGO INTC MRVL MU NVDA QCOM SOXX TSM` vs. this card's relative-strength order
`MU INTC AMD TSM SOXX NVDA AVGO QCOM MRVL`). Since the broker only consults order when more than
three names qualify on the same session, whatever gap A1 shows against this card is pure reshuffling
artifact — nothing else differs. Per-window:

| window | A1 adj. excess | A-rotation adj. excess | gap |
|---|---:|---:|---:|
| covid | +5.45% | +4.85% | +0.59pp |
| bear-2022 | −29.97% | −27.41% | −2.57pp |
| bull-2024 | +13.96% | +1.60% | +12.35pp |
| recent | +67.84% | +80.32% | −12.48pp |

Across this round's four windows, reordering the same nine symbols alone moves adjusted excess by up
to **12.48 points**, with no consistent sign. That is inside, and materially tighter than, the
library's own pre-registered estimate of the noise band: twelve orderings of this identical card
re-run over three years produced a 53.9-point spread, σ = 21.2 points (`library/README.md`). Treat
**~20 points** as the operative floor for any A-family variant-vs-base comparison this round — it is
the conservative, pre-registered figure, and this round's own A1 gap (max 12.48 points) is consistent
with it rather than contradicting it.

Against that floor, of the twelve variant-vs-base comparisons across A2/A3/A4 and the four windows,
exactly **two** clear it: `A2-cash-headroom` in `recent` (−22.16 points, underperforms) and
`A3-no-target` in `recent` (+69.24 points, outperforms). Every other comparison — all of A4's, all of
A2's and A3's non-`recent` windows — sits inside the noise band and should be read as indistinguishable
from a relabeled universe. Detail and verdicts are in each variant's own report.

## 4. Trade-level detail

**Exit-reason distribution per window:**

| window | rule | stop | target | open_at_end |
|---|---:|---:|---:|---:|
| covid | 8 | 1 | 1 | 3 |
| bear-2022 | 22 | — | — | — |
| bull-2024 | 28 | — | 8 | 3 |
| recent | 20 | 5 | 19 | 3 |

Every `bear-2022` exit is a rule exit — the 12% stop and 20% target never fired in that window (see
A3's report for what this implies about the take-profit specifically).

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| covid | NVDA, 2020-04-07→2020-05-18, target, +26.22% | AMD, 2020-02-19→2020-02-25, stop, −11.91% |
| bear-2022 | QCOM, 2022-07-14→2022-08-23, rule, +5.19% | INTC, 2022-07-28→2022-07-29, rule, −11.30% |
| bull-2024 | MRVL, 2024-11-15→2024-12-05, target, +30.68% | MU, 2024-12-17→2024-12-19, rule, −18.01% |
| recent | INTC, 2026-04-09→2026-04-27, target, +43.12% | MU, 2025-11-11→2025-11-21, stop, −17.72% |

**Every stopped-out trade against the nominal 12% stop.** Stops evaluate against the previous close,
not the intraday low, so a realised loss worse than 12% means the fill gapped past the threshold
before the stop could act:

| window | symbol | entry → exit | realised loss | nominal | gap |
|---|---|---|---:|---:|---:|
| covid | AMD | 2020-02-19 → 2020-02-25 | −11.91% | −12.00% | +0.09pp |
| recent | MU | 2025-11-11 → 2025-11-21 | −17.72% | −12.00% | **−5.72pp** |
| recent | TSM | 2026-02-25 → 2026-03-09 | −14.09% | −12.00% | −2.09pp |
| recent | MRVL | 2026-06-08 → 2026-06-11 | −9.84% | −12.00% | +2.16pp |
| recent | INTC | 2026-06-22 → 2026-07-06 | −11.99% | −12.00% | +0.01pp |
| recent | MU | 2026-06-23 → 2026-07-08 | −16.51% | −12.00% | −4.51pp |

Six stop-outs total, three of them worse than nominal — MU in `recent` is the worst single instance
in the base card, filling 5.72 points past the 12% threshold on an 8-bar hold, consistent with a gap
opening below the stop level before the previous-close check could trigger. `bear-2022` and
`bull-2024` had no stop-outs at all in this card.

## 5. Fragility

IQR of 29.37 points across four windows, with the median (+3.23%) sitting almost exactly between the
covid and bull-2024 results and telling a reader almost nothing about `bear-2022` (−27.41%) or
`recent` (+80.32%). This is not incidental spread — it is the direct consequence of the 0.589 mean
pairwise correlation the author measured and flagged at design time: the card does not hold nine
independent bets, it holds close to one bet on whether the semiconductor/AI-capex cycle is running,
sized across three tranches of the same trade. When that cycle runs (`recent`), the card is the
best-performing result in this report; when it breaks (`bear-2022`), it is the worst, and by roughly
the same magnitude. A reader relying on this card should expect binary, cycle-level outcomes rather
than a diversified return stream, exactly as its own thesis warns.

## 6. Verdict

Positive median adjusted excess (+3.23%), a 3-of-4 hit rate, and eligibility that clears the regime
gate — this round's result does not trigger `PROTOCOL.md` §6's demotion condition (negative median in
two consecutive rounds). But one round is one draw, and this card's own dispersion (29.37-point IQR,
a 108-point spread between its best and worst window) is a specific warning against reading +3.23%
as a stable expectation rather than the midpoint of a wide, correlation-driven distribution.

**Recommendation: retain in `library/base/` pending round 2.** No variant has beaten this card on
median adjusted excess in two consecutive rounds (only one round exists), so none is eligible to
replace it yet under §6, regardless of how striking `A3-no-target`'s `recent`-window result looks.
The single most useful thing round 2 can do for this card is re-run it across a window set that
includes another full cycle turn, since every extreme result here — best and worst alike — is the
same concentrated-correlation mechanism expressing itself in opposite directions.
