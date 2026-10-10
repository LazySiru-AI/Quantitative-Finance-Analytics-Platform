# Round 43 — report: the bond-sleeve read is null, and the one point it does shallow the drawdown by is mostly 2022

Run 2026-09-09 through the bespoke harness `strategy-program/tools/round43_run.py` (there is no
`score.py` for `AllocationCard`s). Six cards, the 5y/10y rungs judged, the 3y rungs reported, six bear
supplements, `desk._mandate(SAVINGS)` at $100,000, no macro pin (the field is price-only).
Pre-registration: `strategy-program/ROUND-43-PLAN.md` (2026-09-09, frozen in commit `628b5e3` before
the run). Tables: `ANALYSIS.md`, mirrored in `analysis.json`; the raw harness output is `run.log`.

**Not investment advice.** Price-only bars; AGG/GLD/BIL distributions are unmodelled, so every CAGR is
understated and the drawdown column is the trustworthy half. Benchmark is the 30/70 SPY/AGG blend, not
SPY. The hypothesis came from the persona discussion (`strategy-program/PERSONA-DISCUSSION-2026-09-09.md`
§3: Creator D's bond-market-stress framing, Creator A's metals-in-stress destination, Creator B's bonds-avoided stance) — the corpus supplied the question, the programme supplies the null; no
influencer is endorsed, and none of them stated the thresholds this round used.

---

## 1. Result — null, on the judged rungs

Treatment minus control on the five judged rungs (h10y-1, h10y-2, h5y-1, h5y-2, h5y-3), median across
rungs where the condition fired (all five, for every card). Drawdown margin positive = shallower, the
mandate's axis:

| card | condition → move | fired rungs | dd margin | MAR margin | CAGR margin |
|---|---|---|---|---|---|
| **r43-agg-trend-bil** (primary) | AGG < sma(200) → AGG→BIL | 5/5 | **+1.34pp** | +0.008 | +0.01pp |
| r43-agg-trend-bil-sma100 | AGG < sma(100) → AGG→BIL | 5/5 | +0.96pp | +0.008 | −0.09pp |
| r43-agg-trend-gld | AGG < sma(200) → AGG→GLD | 5/5 | −0.04pp | +0.012 | +0.21pp |
| r43-gld-trend | GLD > sma(200) → AGG→GLD | 5/5 | −0.38pp | −0.004 | +0.28pp |
| r43-price-placebo-spy (r38's placebo) | SPY < sma(200) → SPY→BIL | 5/5 | +0.94pp | −0.003 | −0.30pp |

Every drawdown margin is between −0.4 and +1.3 points on a control whose judged-rung drawdowns run
−5.5% to −17.9%; every MAR margin is within ±0.012. **P1 holds: the null is the result.** Reading the
bond sleeve's own trend moves a 10-20 year savings book's drawdown by about a point, the same order of
magnitude as every savings tilt this programme has measured (round 38's best was +0.94pp; the
allocation family's largest was single digits).

## 2. The primary card beats round 38's placebo — by two-thirds of a point

Plan §5 P2 predicted the bond-sleeve read would **not** beat the equity-sleeve read. On the point
estimate it does: primary minus placebo, on the five rungs where both fired, is **+0.67pp** of drawdown
and **+0.025** of MAR (`analysis.json` → `primary_minus_placebo`). The harness labels this "P2
falsified"; the plan's own falsification clause is stricter — "by more than the noise floor" — and
0.67pp is a thirtieth of the 21.2pp figure and well inside any floor anyone would defend for this card
shape. So: **P2 is not falsified by its own definition**, and the honest reading is that reading AGG's
trend and reading SPY's trend produce indistinguishable de-risking effects on this book, with the
bond-sleeve read a hair ahead on drawdown and the equity-sleeve read a hair ahead on volatility
(placebo realised vol 5.4–6.3% vs primary 6.1–6.7% across the judged rungs).

## 3. Where the primary card's point actually comes from — the hindsight split

The plan pre-registered that `b6m-2` (2021-12-15 → 2022-06-16) and `b1y-1` (2021-12-28 → 2022-12-28)
are **in-sample to the hypothesis**: the bond-stress thesis in the corpus is voiced after 2022, with
2022 known. Drawdown margin of the primary card by window (from `analysis.json`):

| window | regime | primary dd margin |
|---|---|---|
| `b6m-2` | **2022, in-sample** | **+1.33pp** |
| `b1y-1` | **2022, in-sample** | **+1.78pp** |
| `b6m-1` | 2019-20 covid run-in | +0.46pp |
| `b6m-3` | 2018 H2 | −0.00pp |
| `b1y-2` | 2019-20 | +0.44pp |
| `b1y-3` | 2015-16 | +0.09pp |
| `h3y-3` | 2020-23 (contains 2022) | +2.36pp |
| `h3y-1` / `h3y-2` / `h3y-4` | 2014-17 / 2017-20 / 2023-26 | +0.23pp / −0.47pp / +0.43pp |

The two 2022 windows and the one 3-year rung that contains 2022 carry the only margins above a point.
Outside 2022 the card's effect is a few tenths of a point either way. That is exactly the shape the
plan said to discount: **a margin that appears mainly in the regime the claim was voiced after is the
claim's own hindsight, not evidence for it.** The judged 10-year rungs (+1.3pp and +2.5pp of drawdown
on h10y-1/h10y-2) both contain 2022 as well.

## 4. The other predictions

- **P3 (insensitivity) holds.** The `sma(100)` arm posts +0.96pp against the primary's +1.34pp, same
  sign, similar size, on different firing sessions (123/142 trades vs 94/126 on the two 10-year rungs).
  The rule is not fitted to a window length — but that cuts both ways: an insensitive null is still a
  null.
- **P4 (GLD is not a cash proxy) holds.** Routing the identical signal into GLD instead of BIL raises
  realised volatility on every judged rung (6.64/7.04/4.40/6.63/7.16% vs 6.09/6.55/4.12/6.43/6.66%),
  erases the drawdown benefit (−0.04pp vs +1.34pp) and adds a little CAGR (+0.21pp). GLD is a return
  bet, not a de-risking destination.
- **The GLD-trend arm is the only card that worsens drawdown on the judged rungs** (−0.38pp) while
  posting the largest CAGR margin (+0.28pp; +87.2% total return on h10y-2 against the control's
  +69.8%). On a lowest-drawdown mandate that is the wrong trade, and the plan's decision rule says so:
  CAGR is reported, never ranked.
- **Named failure regimes.** The taper-tantrum whipsaw shows up as trade count, not damage: the
  primary card trades 7–8× as often as the control (94 vs 13 on h10y-1) for a drawdown margin of a
  point. The 2019 bond-rally case shows as h3y-2's −0.47pp — the only judged-or-reported rung where
  the primary card deepens the drawdown.

## 5. Decision (plan §9)

P1 holds; P2 holds by its own definition (the primary beats the placebo by 0.67pp, inside any floor);
P3 and P4 hold. **Verdict: the expected one.** Reading the bond sleeve's own bars adds nothing a
savings book can use beyond what round 38's equity-sleeve placebo already showed, and what little it
adds is concentrated in the year the hypothesis was voiced after. **Nothing is promoted** — this was a
measurement round and its result argues against promotion anyway. **No follow-up round on this
line.** The savings book's seated cards are unchanged.

BH is moot: no margin here is a candidate for significance, and the harness reports medians, not
p-values, for allocation cards (the 21.2pp floor is inherited conservatism for this card shape, as
round 38 and this plan both state).

## 6. What this round cannot settle

- **It is one base allocation (30/50/10/10), one band (5%), one shift (10 points).** A different shift
  size or a duration-graded bond sleeve (TLT/IEF/SHY) is a different round.
- **Distributions are unmodelled.** AGG's coupon and BIL's yield are absent from every return; a
  duration tilt's real-world cost includes the coupon given up while in T-bills, which this harness
  cannot see. The drawdown column is trustworthy; the CAGR column is understated for every card.
- **Hindsight is unbounded and 2022 dominates.** §3 shows the point of effect this round did find sits
  in the windows the plan pre-declared contaminated. This round cannot separate "bond trends carry a
  little drawdown information" from "2022 happened once".
- **The personas did not state these thresholds.** `sma(200)`/`sma(100)` and the 10-point shift are
  the programme's round-number choices; Creator D explicitly declined to give a threshold and said his
  approach is "thesis-driven, not rule-driven". A null here refutes this mechanical translation, not
  his discretionary practice.
