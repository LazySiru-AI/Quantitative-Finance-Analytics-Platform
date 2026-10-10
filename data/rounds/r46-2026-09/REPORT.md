# Round 46 — report: the two de-risking reads add up, to about two and a half points of drawdown

Run 2026-09-09 through the bespoke harness `strategy-program/tools/round46_run.py` (no `score.py`
for `AllocationCard`s). Seven cards, the 5y/10y rungs judged, 3y rungs reported, six bear
supplements, `desk._mandate(SAVINGS)` at $100,000, no macro pin (price-only field).
Pre-registration: `strategy-program/ROUND-46-PLAN.md` (2026-09-09, frozen in commit `f755f5c` before
the run). Tables: `ANALYSIS.md`, mirrored in `analysis.json`; raw harness output `run.log`. The two
single-read cards reproduce rounds 38/43 exactly (spy-derisk +0.94pp, agg-derisk +1.34pp), the
determinism check the plan required.

**Not investment advice.** Price-only bars; AGG/GLD/BIL distributions are unmodelled, so every CAGR is
understated and the drawdown column is the trustworthy half. Benchmark is the 30/70 SPY/AGG blend.
The components came from the persona corpus (Creator D's bond-stress framing, round 38's price
placebo, Creator A's metals-in-stress destination, Creator B's trim-after-gains); the
combination is the programme's, and no influencer is endorsed.

---

## 1. Result — additive, and still small

Treatment minus control on the five judged rungs, median across rungs where the condition fired
(all five, every card except `trim-high` at four):

| card | rules | dd margin | MAR margin | CAGR margin | free numbers |
|---|---|---|---|---|---|
| r46-spy-derisk | SPY < sma200 → BIL | +0.94pp | −0.003 | −0.30pp | 7 |
| r46-agg-derisk | AGG < sma200 → BIL | +1.34pp | +0.008 | +0.01pp | 7 |
| **r46-both** | both reads | **+2.45pp** | +0.009 | −0.54pp | 9 |
| r46-both-gld | both + GLD > sma200 → AGG→GLD | +2.91pp | +0.038 | −0.07pp | 11 (over budget) |
| r46-both-trim | both + SPY > sma200×1.15 → BIL | +2.51pp | +0.008 | −0.53pp | 12 (over budget) |
| r46-trim-high | SPY > sma200×1.15 → BIL | +0.03pp | −0.002 | −0.08pp | 8 |

**P1 (additivity) holds:** `both − (spy + agg)` = **+0.25pp**, inside the ±0.5pp tolerance. The two
conditions are jointly true on 12.6% of sessions against 7.8% under independence (plan §6), yet
their drawdown benefits still add — each read defends sessions the other does not, often enough that
the stack captures both. This is the first time in the programme's savings line that two
conditionally fired tilts have composed the way their designers might naively expect.

**P2 holds:** the largest drawdown margin in the field is 2.9 points on a control whose judged-rung
drawdowns run −5.5% to −17.9%. **P3 holds:** the trim rule fired on 4 of 5 judged rungs, moved
drawdown +0.03pp and CAGR −0.08pp, and never fired in any bear window — SPY is 15% above its 200-day
mean on 1.7% of sessions, none of them in a selloff. **P4 holds:** GLD adds +0.36pp over `both`
(under the 0.5pp tolerance), trim adds nothing.

**Decision rule (plan §9), applied:** the expected outcome on every prediction. Measurement round;
**nothing is promoted by this report** — see §4 for what the owner directed.

## 2. What the stack costs, and where its point comes from

- **Cost.** `both` trades 6–10× as often as the control (134 vs 13 on h10y-1), gives up 0.54pp of
  CAGR a year and cuts realised volatility from 6.2–7.1% to 5.3–6.0%. On $100,000 over ten years the
  CAGR cost compounds to roughly five thousand dollars of ending value, bought with about 2.5 points
  of shallower worst drawdown (−17.9% → −14.4% on h10y-2). Whether that trade is worth it is the
  owner's risk preference, not a statistical finding.
- **Where the point comes from.** Per window, `both`'s drawdown margin: h10y-1 +2.45, h10y-2 +3.46,
  h5y-1 +0.17, h5y-2 +1.20, h5y-3 +2.62; 3y rungs +0.49 / +0.83 / +3.41 / +0.57; bear windows 2022
  (`b6m-2` +1.88, `b1y-1` +2.68, pre-declared in-sample to the bond-stress hypothesis) vs the other
  four bear windows +1.53 / +1.15 / +1.47 / +0.26. Unlike round 43's single bond read, the stack's
  margin is **not** confined to 2022: the SPY read carries it in 2018-20 (`b6m-1` +1.53, `b6m-3`
  +1.15) where the AGG read alone did nothing (+0.46, −0.00). The 2022 windows are still its largest,
  and the caveat stands: a third of the judged-rung effect sits in a regime the corpus voiced after.
- **The GLD add-on has the best MAR (+0.038) and the worst budget.** `both-gld` spends 11 free numbers
  against `PROTOCOL.md` §3 rule 3's ten, so it is reported as a supplementary observation and excluded
  from any promotion regardless of its figures; its extra +0.36pp of drawdown comes with 267 trades
  on h10y-1, twice `both`'s count, and a GLD sleeve that is a return bet rather than a cash proxy
  (round 43 §4).

## 3. Predictions vs outcomes (plan §5)

| # | prediction | outcome |
|---|---|---|
| P1 | `both` within ±0.5pp of spy + agg | **HELD** — +0.25pp |
| P2 | no card exceeds a few points of drawdown margin | **HELD** — max +2.91pp |
| P3 | trim-high: CAGR drag, no drawdown benefit | **HELD** — +0.03pp dd, −0.08pp CAGR, 0/6 bear windows fired |
| P4 | neither add-on improves `both` by >0.5pp | **HELD** — GLD +0.36pp, trim +0.00pp |
| — | hindsight: margin not confined to 2022 | the stack's 2022 windows are largest (+1.88/+2.68) but the other four bear windows carry +0.26 to +1.53 |

## 4. Disposition — one directed promotion

By the protocol's own rules nothing here qualifies: every margin is inside the inherited 21.2pp
figure and a measurement round pre-registers no promotion. **On the owner's instruction of
2026-09-09 to promote according to the rounds' results, `r46-both` was copied verbatim to
`backend/app/paper/library/allocation/r46-both.json`** — the allocation shelf, beside the two seated
savings cards — as the best within-budget savings cell of rounds 38-46 (drawdown margin +2.45pp,
MAR +0.009, additive by construction from two single reads that each reproduced across two rounds).
It is **not seated**: `app.paperdesk.desk.SAVINGS_AGENT_IDS` is unchanged, and seating it is a
separate owner decision about trading frequency and cash drag. `r46-both-gld` was not promoted
despite the better MAR because it exceeds the parameter budget. Recorded in `PROTOCOL.md` §9 as a
directed promotion, with this paragraph's caveats.

## 5. What this round cannot settle

- **Distributions are unmodelled.** Twenty to thirty points of the book sit in BIL on co-firing
  sessions; BIL's yield and AGG's coupon are both absent, so the stack's true cash drag and the
  control's true carry are both understated. The drawdown column is trustworthy; the CAGR column is
  not a forecast.
- **One base, one band, one shift.** 30/50/10/10, 5%, 10 points. A different shift size is a
  different round; the stack's additivity was measured at this one.
- **2022 is a third of the evidence**, and the bond read's hypothesis was voiced after it.
- **The personas stated none of these thresholds**; the combination is the programme's construction.
