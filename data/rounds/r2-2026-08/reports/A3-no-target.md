# A3-no-target — No Take-Profit — round 2 report

Agent: `A3-no-target` | Discipline: `pairs-rotation` | Library status: `variants/` | Eligible: 7/8
main windows (same `gfc` block as the rest of the A family). Clears the regime gate.

## 1. What the card is, and the single decision it isolates

Identical to `A-rotation` except the 20% take-profit is removed entirely (`take_profit_pct: null`);
the 12% stop, 3-slot 30% sizing, universe, order and entry/exit rules are all unchanged.

**The question it was written to answer:** `B-momentum`'s author measured that take-profits amputate
the winners that carry a momentum book. `A-rotation` caps winners at 20%. Does that cap cost this card
more than it protects — is the base card's take-profit a net drag on a strategy whose entry logic is
built to ride a confirmed uptrend?

## 2. Versus SPY, every window

| window | sessions | card | SPY | excess | adj. excess | cap. exp | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| `q4-2018` | 65 | **-15.79%** | -20.05% | +4.26% | **-8.76%** | 35.0% | -17.23% |
| `covid` | 93 | **-2.37%** | -8.71% | +6.34% | **+1.36%** | 42.9% | -17.85% |
| `bear-2022` | 196 | **-33.27%** | -25.14% | -8.13% | **-27.41%** | 23.3% | -34.55% |
| `chop-2015` | 260 | **+3.68%** | -0.04% | +3.72% | **+3.70%** | 52.0% | -19.46% |
| `chop-2011` | 260 | **-16.90%** | -0.05% | -16.86% | **-16.88%** | 44.9% | -24.85% |
| `bull-2024` | 250 | **+5.32%** | +14.00% | -8.68% | **-2.91%** | 58.8% | -26.26% |
| `recent` | 249 | **+164.70%** | +20.62% | +144.08% | **+149.49%** | 73.8% | -16.25% |

Median adjusted excess **−2.91%** across all seven windows (sorted: −27.41, −16.88, −8.76, **−2.91**,
+1.36, +3.70, +149.49). Six-window common set (dropping `chop-2011`): **−0.79%**, matching
`scorecard-common6.json`. Worst window `bear-2022` at −27.41% — identical to `A-rotation`, and
verified so at the trade level below. Hit rate 3 of 7. **This is the largest single adjusted-excess
figure any card in the round posted, in any window (+149.49%, `recent`), sitting beside a negative
median** — the sharpest illustration in this family of a result that looks decisive in a ranking table
and is actually carried by a small number of trades.

## 3. What moved the number, and the take-profit's own price tag

**`bear-2022` — the take-profit never bound, verified exactly.** `A-rotation` and `A3-no-target` post
byte-identical results in this window: same 22 trades, same entries and exits, same P&L, same ending
equity. Every exit in both logs is `exit_reason: "rule"` — none is `"target"`. No position in this
window ever gained 20% before the trend-break exit fired first, so removing an exit condition that
never fires cannot change the result, and it did not. `chop-2011` shows the same mechanism at small
scale: `A-rotation`'s MU position (2011-12-23→2012-01-20, target, +20.64%/$627) becomes, in A3, the
same entry held to 2012-04-02 via the rule exit for +25.88%/$786 — a genuine but modest cost of
+5.24 points on that single trade, because the underlying move wasn't large enough for the cap to matter
much even when it does bind. `q4-2018` is identical between the two cards for the same structural
reason as `bear-2022` — every position in that window is a loss, so there is nothing for a take-profit
to cap.

**`recent` is where the take-profit actually binds hard, and this is the sharpest evidence the family
has produced.** `A-rotation`'s 20% cap fires on 19 of 47 exits in this window. Four of its capped
winners are precisely the trades this task set out to trace — same symbol, same entry date, held by
`A-rotation` only to the 20% target, held by `A3` all the way to the trend-break rule exit:

| symbol | entry | `A-rotation` exit (bars, reason, return, P&L, share) | `A3-no-target` exit (bars, reason, return, P&L, share) | take-profit cost |
|---|---|---|---|---:|
| MRVL | 2026-03-09 | 2026-04-02, 18, target, +16.23%, +$471, +4.71% | 2026-07-08, 83, rule, +155.82%, +$4,523, +45.23% | +139.59pp return / +$4,052 / +40.52pp share |
| INTC | 2026-04-02 | 2026-04-09, 4, target, +26.67%, +$762, +7.62% | 2026-06-08, 45, rule, +140.75%, +$4,021, +40.21% | +114.08pp return / +$3,259 / +32.59pp share |
| AMD | 2026-04-06 | 2026-04-17, 9, target, +28.02%, +$799, +7.99% | 2026-07-20, 72, rule, +135.53%, +$3,865, +38.65% | +107.51pp return / +$3,066 / +30.66pp share |
| MU | 2025-12-01 | 2025-12-26, 18, target, +25.07%, +$699, +6.99% | 2026-03-04, 63, rule, +69.28%, +$1,932, +19.32% | +44.21pp return / +$1,233 / +12.33pp share |

Across these four trades alone, removing the take-profit is worth **+116.10 points of card-return
share and +$11,610** on a $10,000 book — more than the entire window's net margin between the two
cards. That is not a contradiction: `A-rotation`'s early exits on these four positions free up slots
that it — but not `A3` — can redeploy into other trades. Netting the whole window, `A3` finishes
+$6,942 ahead of `A-rotation` (+69.42 raw excess points), meaning `A-rotation`'s redeployed capital
earned back roughly **$4,668** of the **$11,610** the cap gave up on these four names alone. **The
true net cost of the 20% cap in this window is the smaller, reconciled figure (~$6,942 / 69.4 points),
not the raw sum of what it visibly trimmed off the four biggest winners** — some of what it trims gets
recovered elsewhere, just not all of it.

The mechanism behind the size of the effect is straightforward: all four capped trades were still in a
confirmed uptrend (`close > sma(50)`, `55 < rsi(14) < 80`) well past the 20% mark, and the trend-break
exit did not fire until 45–83 bars in — 2 to 4.6× longer than the target-capped hold. MRVL alone rode
from $87.97 to $225.05 over 83 sessions, a move the take-profit could see only the first 18 sessions of.

**`covid`** shows a variant of the same mechanism with an important caveat: `A-rotation`'s NVDA position
(2020-04-07→2020-05-18, target, +26.22%/$813) is, in `A3`, the same entry still **open at the window's
close** (58 bars, +36.86%/$1,143) rather than closed via the rule exit. The +10.64-point, +$330
difference here is a **mark, not money taken** — see §5.

**`bull-2024`** inverts the story: this is the family's one window where the take-profit's absence
costs the card outright (adjusted excess −2.91% vs `A-rotation`'s +1.56%, a 4.47pp shortfall), and the
reason is visible directly in the trade log — see §5, because the loss is not realised at all.

## 4. Concentration

| window | top-3 share of gross winning P&L | return without top 3 |
|---|---:|---:|
| `bear-2022` | 100% | -35.16% |
| `q4-2018` | n/a — no material winners | — |
| `covid` | 100% | -15.07% |
| `chop-2015` | 75% | -15.57% |
| `chop-2011` | 100% | -29.70% |
| `bull-2024` | 97% | -29.70% |
| `recent` | 66% | +40.60% |

This is the most concentrated card in the entire A family. Four of seven windows have **100%** of
gross winning P&L in three trades or fewer, and even `recent` — the family's most broadly distributed
window for every other A-card — still carries 66% of its winning P&L in three positions here, because
removing the cap means the same handful of trades that would have been trimmed instead compound into
the whole story. Without those three trades, `recent` still returns +40.60%, comfortably positive, but
the round's headline +149.49% figure and the +116-point take-profit finding above rest on four trades
out of 26 — a card whose year rests on three or four positions, not ninety small edges. Only 10 trades
occurred in `covid`, 22 in `bear-2022`, 25 in `bull-2024`, 25 in `chop-2011` — removing the cap shrinks
trade count everywhere (capital tied up in unrimmed winners blocks new entries), which is the mechanical
reason concentration rises across the board, not just in `recent`.

## 5. Realised versus marked — two windows where this matters directly

**`bull-2024` is entirely a marks story, and the realised picture is materially worse than the headline.**
The window's total return is +5.32% ($532 on $10,000), but +23.36% of that return (+$2,336) sits in two
positions still open at the window's close — AVGO (2025-04-28→open, +52.74%, +$1,508) and TSM
(2025-05-02→open, +27.08%, +$828). **Strip those two marks and the window's realised trades net to
−18.04% (−$1,804)** — a solidly losing book propped entirely by two unrealised positions that happen to
be marked up at the window's last close. `A-rotation`, which would have taken both of these off the
table at 20%, shows no such gap.

**`covid` leans the same way, more mildly.** +12.51% of the window's −2.37% return sits in two open
positions (NVDA +36.86%/+$1,143 and TSM +3.71%/+$108). Realised trades alone return **−14.88%** —
noticeably worse than the already-negative headline.

**`chop-2015`** carries a smaller mark (+1.71%, one open TSM position); realised return is +1.97%,
close to the headline. **`recent`** carries a small negative mark (−3.50%, one losing open AVGO
position); realised return is actually **higher** than the headline (+168.20%), confirming the four
big winners in §3 are genuinely realised money, not projections. **`q4-2018`** carries a small negative
mark (−1.22%). `bear-2022` and `chop-2011` carry no open-at-end positions at all.

The takeaway: two of this card's seven windows (`bull-2024`, and to a lesser extent `covid`) would look
meaningfully worse, or would flip sign, if scored strictly on realised trades. This card's habit of
letting winners run means it also, mechanically, ends more windows holding open positions than
`A-rotation` does — the same structural feature that produced the recent-window take-profit finding
also means its interim marks matter more.

## 6. Verdict and promotion recommendation

Round 1 (four windows) gave this card a negative median of −0.79%, driven by the same mechanism visible
here: one outsized `recent`-window trade against three flat-to-negative windows. Round 2's full
seven-window median is **−2.91%**, still negative; the six-window common-set median is **−0.79%**,
identical to round 1's figure to two decimals (the underlying `recent` and `bear-2022` windows are the
same trades in both rounds, so this is not independent confirmation of the same number, per `REPORT.md`
§1). The three windows round 1 never had give a median of **−8.76%** (values −8.76%, +3.70%, −16.88%)
— negative, and numerically identical to `A-rotation`'s own new-window median by coincidence of which
value lands in the middle; the underlying `chop-2015` figures differ by +10.86 points (+3.70% for A3
against −7.16% for the base) but that single-window gap does not clear the ~20-point floor either.

**Not recommended for promotion to replace `A-rotation`.** The median has been negative in both rounds,
on both overlapping and non-overlapping window sets, and no margin against the base clears the noise
floor except the single `recent`-window result, which `PROTOCOL.md` §7 explicitly says a variant
comparison must not be judged on alone. The finding this round sharpens is not about promotion: **the
20% cap has a real, quantifiable, and in `recent`'s case enormous cost when a confirmed uptrend keeps
running past it — but the same absence of a cap converts two other windows into a mark-dependent,
occasionally realised-negative result** (`bull-2024` above all). This is a genuine trade-off, not a
free option; a reader should treat this card's median (−2.91% / −0.79%) as the honest summary and the
`recent` figure as the specific, well-understood exception to it, not the other way around.
**Recommendation: keep as a `variants/` line item and re-test unchanged in round 3**, specifically
because a single sustained-trend window (`recent`) is doing all of this card's promotional work, and
whether that generalises is exactly what a further, independent window can answer and this round cannot.
