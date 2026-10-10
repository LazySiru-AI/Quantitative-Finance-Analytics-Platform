# F-fastrev — competition report

`F-fastrev`, "F - Fast reversion: low-exposure satellite" (discipline: `mean-reversion`), is
**unranked** — eligible for only two of five main windows. Its defining number is not a return but an
exposure: **capital exposure of roughly 7.3%** across its two eligible windows, the lowest of any card
in the full round-1 field (`scorecard-full.json`: `mean_exposure = 0.0729`, against a next-lowest of
10.13% for `c01-meanrev`). That number is the report.

## 1. What the card is, and why it could run in only two windows

Entry is a short, sharp dislocation: `rsi(3) < 15 and close < bb_lower(10,2)`, exiting on the first
close back above `ema(5)`. `stop_loss_pct = 0.07`, `take_profit_pct = 0.05`, `max_hold_days = 8` — a
tight, fast-cycling design built on the measured finding (design-window sample, 306 dislocations) that
this kind of air-pocket resolves in a median of 4 sessions. Universe: `AMD MU AVGO QCOM MRVL CRDO NET
SOXX TSM NVDA`.

**Eligible for `bull-2024` and `recent` only**: `eligibility.json` gives `CRDO first bar 2022-01-27,
needs <= 2007-07-30` for `gfc`, `needs <= 2019-12-10` for `covid`, and `needs <= 2021-10-24` for
`bear-2022`. CRDO IPO'd in 2022, which structurally excludes every regime before it. This is the same
mechanism as `E-asymmetric`'s and `D-13f-newbuys`' exclusions: a young universe cannot reach an old
window, whatever the merits of the strategy trading it.

## 2. Results across its two eligible windows

| window | trades | corrected return | benchmark | excess | adj. excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| bull-2024 | 41 | −7.05% | +14.00% | −21.04% | **−8.05%** | 7.15% | 26.00% | −19.94% | 48.72% |
| recent | 48 | +36.45% | +20.62% | +15.83% | **+34.91%** | 7.43% | 30.92% | −4.58% | 89.58% |

Two windows, both run, both eligible — `n_windows_run = 2` against the gate's minimum of 3, so no
median, worst, IQR, or hit-rate beyond the pair itself.

## 3. Why the benchmark comparison is the wrong one, and what the right one looks like

The card's own framing — "judged as a market substitute it fails; judged as a satellite sleeve it may
not" — is borne out directly by these two windows. `excess` (return against the fully-invested
benchmark) swings from −21.04% to +15.83%; `adjusted_excess` (return against the benchmark scaled by
actual capital deployed) swings from −8.05% to +34.91%. Both corrections point the same direction:
raw excess punishes this card for **not** being invested 93% of the time, which is not a defect in the
strategy, it is the strategy. A book that holds roughly 7% of capital at risk on average and is
compared against a 100%-invested SPY benchmark is being scored on a question ("did you replace the
index?") the card never claimed to answer.

The comparison PROTOCOL.md's `adjusted_excess` metric already approximates — return against a
benchmark position sized to the same capital fraction actually deployed — is the right one, and it is
the one that flips the `bull-2024` read from a −21-point miss to an −8-point miss and turns `recent`'s
+15.83% excess into a +34.91% adjusted one. A cleaner version of the same idea, worth running
explicitly next round: hold the other ~93% of the book in cash or T-bills and compare the **blended**
portfolio return (7% strategy + 93% cash) against full SPY, which directly answers "is this satellite
sleeve worth the sliver of capital it asks for" without the exposure term doing that arithmetic
implicitly.

Read that way, this round is genuinely mixed rather than uniformly good: `bull-2024` cost the book
about 8 points of capital-adjusted return; `recent` earned nearly 35. Both are real outcomes of a
low-capital, high-turnover satellite sleeve, not artifacts of the comparison.

## 4. Trade-level detail

**Exit-reason distribution:**

| window | rule | stop | target | time |
|---|---:|---:|---:|---:|
| bull-2024 | 9 | 18 | 12 | 0 |
| recent | 21 | 3 | 23 | 1 |

The two windows have almost opposite profiles: `bull-2024` resolved mostly at the 7% stop (18 of 41,
43.9%); `recent` resolved mostly at the 5% target or the exit rule (21 rule + 23 target = 44 of 48,
91.7%, only 3 stops). An 89.58% win rate in `recent` against 48.72% in `bull-2024` is the same shift
in different terms.

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| bull-2024 | MRVL, 2025-04-07→2025-04-08, +14.17% | MRVL, 2025-03-28→2025-04-04, −18.56% (stop) |
| recent | CRDO, 2026-02-05→2026-02-09, +18.01% | CRDO, 2026-02-04→2026-02-05, −11.23% (stop) |

MRVL supplied both the best and worst trade of `bull-2024`, one day apart in the calendar (April
2025), on opposite sides of what appears to be the same volatile stretch. CRDO did the same in
`recent`, a single session apart — consistent with a fast-reversion book trading the same names
through consecutive dislocations in a choppy stretch.

**Stop-outs, 21 of 89 trades (23.6%), nominal `stop_loss_pct = 0.07`:** mean realised loss **−9.41%**,
a gap of **2.41 percentage points** beyond the nominal 7% level — the smallest such gap of any card in
this report, consistent with the short median hold (most stops resolve in 1–7 bars) giving less time
for a previous-close-based stop to be overtaken by further adverse movement. The worst individual case
was MRVL at −18.56% (2025-03-28→2025-04-04, 5 bars), more than 2.6x the nominal level; the tightest was
AMD at −4.48% (2025-04-04→2025-04-08, 2 bars), inside the nominal stop, which can happen when a
position is trimmed or the fill lands better than the triggering close implied.

## 5. Rankable, and what would make it so

**Not rankable.** Two of five main windows, against a three-window minimum. What would change this:
the same walk-forward mechanism as `E-asymmetric` — round 2 adds a new window measured from this
round's end, and if it falls after CRDO's 2022-01-27 first bar (which every window after `bear-2022`
does), it becomes this card's third eligible main window without any change to the card. `bear-2022`
itself would also become reachable if the universe dropped CRDO for a pre-2022 name with a similar
fast-reversion profile, though that changes the universe rather than merely waiting.

## 6. Recommendation

**Retain as a candidate; do not promote, and do not score it against the field's benchmark-relative
ranking.** It cannot be ranked this round, and even were it rankable, the median-adjusted-excess key
implicitly assumes the benchmark comparison is the right one for every card — which §3 above argues it
is not, for a card whose entire design point is minimal capital commitment. Carry it forward for a
third window next round, and consider adding the blended-portfolio comparison described in §3 as a
supplementary metric specifically for low-exposure satellite cards, since the existing scorecard
columns do not currently surface "return per dollar actually deployed" as its own number.
