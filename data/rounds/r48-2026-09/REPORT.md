# Round 48 — report: 1%-risk sizing halves every seated card's tail and costs a third of its median; it is a risk dial, not an edge

Run 2026-09-09, eight main windows, 10 cards (5 seated roster cards × {base, risk1pct}). Run files:
8 per window except `chop-2011` (2) and `gfc` (0) — the known universe-history wall (META's 2012
first bar, AVGO's 2009 one; round 26 §1 documents the same), so the four eligible bases run 6 of 8
windows (7 for A-rotation) and clear the five-window gate; every `FAILED` line in `run.log` is a
lookahead-guard history refusal, none an `IOException`. `I-13f-duquesne-2026q2` ran only `recent` by
provenance (filing date 2026-08-14) and is UNRANKED as pre-registered. Pre-registration:
`strategy-program/ROUND-48-PLAN.md` (frozen in commit `01487ac` before the run). Tables:
`ANALYSIS.md` / `analysis.json` from `strategy-program/tools/round48_report.py`; scorecard
`scorecard.json` (`score.py --pin-store`). The four ranked bases reproduce rounds 24/26 exactly
(B3 +13.89pp, C-trend +5.03pp, A-rotation −7.16pp, B-momentum +12.16pp).

**Not investment advice.** Price-only bars, no dividends, SPY benchmark, a synthetic paper book.
This is the feedback-loop follow-up to round 45: Creator E's "never risk more than 1% of the
account per trade", rendered as `position_pct = 0.01 / stop_loss_pct` (0.083 on every seated card,
because every seated card carries a 0.12 stop), applied as a one-decision variant to the live
trading roster. Nothing on the `trading` purpose is promotable (`PROTOCOL.md` §9, r21).

---

## 1. Result — null on the median, consistent on the tail

| base | median: base → risk1pct | worst window: base → risk1pct | IQR: base → risk1pct | exposure: base → risk1pct | windows arm>base |
|---|---|---|---|---|---|
| B3-concentrated | +13.89 → +6.66pp | −7.75 → **−2.80pp** | 25.7 → **9.0pp** | 0.385 → 0.143 | 3/6 |
| B-momentum | +12.16 → +6.94pp | −5.15 → **−2.80pp** | 21.4 → **11.3pp** | 0.349 → 0.185 | 2/6 |
| C-trend | +5.03 → +2.35pp | −7.26 → **−2.71pp** | 19.2 → **8.9pp** | 0.281 → 0.126 | 3/6 |
| A-rotation | −7.16 → −1.59pp | −27.41 → **−7.92pp** | 16.1 → **7.1pp** | 0.488 → 0.149 | 5/7 |
| I-13f (1 window, unranked) | +34.40 → +21.87pp | — | — | 0.541 → 0.288 | 0/1 |

Marginal (mean of arm − base over the five bases): **−4.42pp**, inside the floor; every arm cell
q = 1.0 (m = 10). **Decision rule (plan §4), applied: null.** The resizing does not change what the
rules earn; it changes how much of the book is exposed to them.

## 2. What the numbers do say

1. **The tail shrinks on every ranked base, and by roughly the factor the book shrank.** Position
   size fell from 0.15–0.30 to 0.083 (by 45–72%) and the worst window fell by 46–71% (−7.75 →
   −2.80, −5.15 → −2.80, −7.26 → −2.71, −27.41 → −7.92). That proportionality is the point: `PROTOCOL.md`
   §4 says a smaller book structurally cannot have a deep worst window, and this round shows exactly
   that — the shape of every card's per-window record is unchanged (signs identical on every eligible
   window, 6/6, 7/7, 6/6, 6/6) while its amplitude is scaled down.
2. **In dollars, on a $60,000 book, the same fact reads plainly.** Worst-window realised P&L:
   A-rotation −$3,327 → −$991, B3 −$1,017 → −$369, B-momentum −$677 → −$369, C-trend −$224 → −$323
   (C-trend's worst window moves from `recent` to `bear-2022` on resizing). Total realised P&L over the
   eligible windows falls with it: B3 $8,620 → $3,375, B-momentum $7,933 → $4,360, C-trend $3,861 →
   $1,857, A-rotation $3,322 → $816. Half the pain, roughly half the gain.
3. **Adjusted excess per unit of exposure rose on every base** (+10.5pp on B3, +4.0 on A-rotation,
   +2.7 on B-momentum, +0.8 on C-trend), which refutes the plan's "within ±3pp" prediction on two
   bases. This is not alpha appearing from nowhere: `adjusted_excess` subtracts `capital_exposure ×
   benchmark`, so a card that deploys less capital in a window where the benchmark fell is credited
   relative to a smaller passive position, and the metric's own exposure bias (§4, measured at Pearson
   +0.80 in round 2) runs the other way in rising windows. Per-unit efficiency is the wrong lens for a
   sizing change; the dollar table is the right one.
4. **A-rotation is the one base where resizing lifts the median** (−7.16 → −1.59pp, 5 of 7 windows):
   its `bear-2022` −27.41pp and `chop-2011` −17.01pp were concentration losses on a three-slot, 30%
   book, and a 8.3% slot cannot lose that much. Still a negative median, still the roster's weakest
   card.
5. **Prediction 5 was mis-specified, not refuted in substance.** It asked for identical signs on "≥ 7
   of 8 windows" on bases that are eligible in only 6 or 7; signs were identical on every window that
   ran.

## 3. Predictions vs outcomes (plan §5)

| # | prediction | outcome |
|---|---|---|
| 1 | Null on the median marginal (|marginal| < 5pp) | **HELD** — −4.42pp |
| 2 | Worst window shallower on ≥ 4 of 5 bases | **HELD** — 4/5 (I-13f has one window) |
| 3 | IQR narrower on ≥ 4 of 5 | **HELD** — 4/5 |
| 4 | Mean exposure lower on 5/5 | **HELD** |
| 5 | Sign pattern identical on ≥ 7 of 8 windows per base | **mis-specified** — identical on every eligible window (6/6, 7/7, 6/6, 6/6, 1/1), but no base has 8 eligible windows |
| 6 | Excess per unit exposure within ±3pp of base | **REFUTED** on B3 (+10.5pp) and A-rotation (+4.0pp); see §2.3 |
| 7 | I-13f unranked by provenance | **HELD** — 1/8 windows, unranked |
| 8 | Dollar worst-window table printed | **done** — §2.2 |

## 4. Disposition — the dial, and who turns it

Nothing is promoted or seated by this report. What the round establishes for the owner is a
measured trade-off on the live roster: **moving every seated card to a 1%-risk slot (8.3%) would
have roughly halved the book's worst windows and its interquartile spread, and roughly halved its
realised P&L, without changing which windows each card wins or loses.** Whether to turn that dial is
a decision about how much of a $60,000 taxable book should ride five momentum rules at once, and it
belongs to the owner. `r45-kim-risk1pct` — the same resizing on the already-seated
`r40-rsi-confirm-slots6` — was placed on the `variants/` shelf by the owner's direction (§9), so the
variant mechanism of `PROTOCOL.md` §7 can track it against its base on future windows.

## 5. What this round cannot settle

- **One stop, one risk fraction.** Every seated card carries a 0.12 stop, so "1% risk" is one number
  (0.083) everywhere; a roster with mixed stops would size each card differently, and 1% is Straight
  Creator E's number, not a measured optimum.
- **Slot count was held fixed**, so the resized cards leave 50–75% of the book in cash at full
  deployment. A resizing that also raised slot count is a different card and a different question.
- **Two windows are missing for every base but one** (`gfc`, `chop-2011`) by universe history; the
  2008 drawdown — the one a tail-sizing rule exists for — is unmeasured on this roster.
- **Price-only, dividend-free, SPY-benchmarked**, like every backtest in this programme.
