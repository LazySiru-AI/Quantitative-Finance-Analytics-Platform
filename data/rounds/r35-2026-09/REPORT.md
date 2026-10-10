# Round 35 — report: country rotation is the asset-class gap wearing eight tickers

Run 2026-09-09 01:36–01:39 (local), eight main windows, 9 cards, serial, zero `FAILED` lines in any
window log. Pre-registration: `strategy-program/ROUND-35-PLAN.md` (2026-09-08). Computed tables:
`ANALYSIS.md` in this directory, produced by `strategy-program/tools/round34_36_report.py --round 35`
and mirrored in `analysis.json`. Scorecard: `scorecard.json` (`score.py --pin-store`). The instrument
check for this family (`data/rounds/r34-2026-09/repro-r17/`) ran before round 34 and reproduced round 17
to the digit; round 35 ran on the same store minutes later.

**Not investment advice.** Price-only bars, no dividends, SPY benchmark in USD, a synthetic paper book.

---

## 1. The control is valid, so the comparison is

`r35-passive-8-order` — entry `close > 0`, exit `close < 0`, eight slots at 11% — held all eight names
on every session of every window: 8 trades per window, session exposure 1.000 in all eight windows,
mean capital exposure 0.862 (the 88% budget, less cash drag). Prediction 6 holds and the round's
comparisons stand.

## 2. Result — the rotation cells are the control, minus a little

| quantity | value | verdict |
|---|---|---|
| passive control, median adjusted excess vs SPY | **−2.28pp** | the asset-class gap, pre-registered in plan §4a |
| best rotation cell vs SPY (`r35-macross-4-rank`) | −2.21pp | negative, as predicted |
| worst rotation cell vs SPY (`r35-absolute-2-rank`) | −7.82pp | |
| best rotation-minus-control margin | **+0.08pp** (`macross-4-rank`) | inside 21.2pp floor by a factor of ~265 |
| worst rotation-minus-control margin | −5.54pp (`absolute-2-rank`) | inside the floor |
| fill-order marginal, `rank_by` vs written order | 0.50pp | inside |
| BH over all 9 cells against the control, minimum q | **0.70** | nothing survives |

**Decision rule (§7), applied:** rotation-minus-control is the reported quantity; no margin inside
21.2pp is a finding in either direction; BH over all nine cells. Every rotation cell lands within
−5.54pp to +0.08pp of simply holding the eight names, and nothing approaches the floor. **The null is
the result.** A country-rotation rule built from the programme's own two best-evidenced entry forms
adds nothing to owning the basket, and owning the basket trails SPY by about two points of median
adjusted excess over this window mix.

## 3. Predictions, beside their outcomes (§5)

| # | prediction | outcome |
|---|---|---|
| 1 | every rotation cell negative vs SPY | **held** — eight of eight, from −2.21pp to −7.82pp |
| 2 | no rotation cell beats the control by > 21.2pp | **held** — best margin +0.08pp |
| 3a | `macross` worst two windows are `chop-2011` and `chop-2015` | **half held** — `chop-2011` is in the worst two for all four `macross` cells, but the other is `bear-2022` (k=2) or `bull-2024` (k=4), never `chop-2015` |
| 3b | `absolute` worst window is `covid` | **refuted** — `chop-2011` for three of four cells, `gfc` for `absolute-2-rank`; in `covid` the absolute filter was flat (+0.04pp / +0.51pp) because it never re-qualified inside the window |
| 3c | control's worst window is `gfc` | **refuted** — `chop-2011` (−15.58pp); in `gfc` the exposure credit against a −56% benchmark leaves the control at −4.57pp. This is the exposure-scaling bias `PROTOCOL.md` §4 documents, showing up exactly where it should |
| 4 | fill orders differ by < 21.2pp | **held** — marginal 0.50pp; matched pairs −1.55, −1.13, 0.00, +0.65pp. Relative-strength ordering is inside the noise on a country universe too |
| 5 | 2-slot cells post wider IQR than 4-slot | **held** — mean IQR 8.80pp vs 7.14pp |
| 6 | control validity | **held** — see §1 |

## 4. What is worth more than the headline

1. **The `macross` cells never traded in `covid`** — +0.00pp in all four. `close > sma(200)` was false for
   every country ETF from the first session of that window to the last, so the 10/30 crossover never got
   permission to fire. On a non-US universe the regime filter converted the fastest crash-and-snapback
   on record into a window of pure cash. That is not a loss and not a gain; it is the filter doing what a
   200-day filter does, and it is why `macross` has the field's shallowest worst windows (−9.87pp at k=4).
2. **`chop-2011` is the failure regime for everything here, control included.** The 2011 window is the
   euro-area crisis: EWG, EWU and EFA fell hard while SPY went sideways, and every card — passive or
   rotating — paid for holding Europe. This is the FX-and-region confound in plan §7 made visible: the
   "chop" label describes SPY, not the universe these cards trade.
3. **`rank_by` did the one thing it should on a small universe: nothing much.** At k=4 on eight names
   the cap binds rarely, and the `rank`/`order` pairs differ by at most 1.55pp. `absolute-2-rank`'s
   `recent` window (+15.54pp against `-order`'s −6.40pp) is the single largest ordering effect in the
   family so far — and it is one window, offset by `gfc` (−17.83pp vs −6.15pp), netting to a −1.55pp
   median difference. Round 36 measures this directly.

## 5. What this round cannot settle (unchanged from the plan, §7)

Roster survivorship (eight survivors of the country-ETF launch cohort); price-only bars, which penalise
higher-yielding non-US indices harder than SPY; FX embedded in USD-listed ETFs — the −2.28pp control
gap is partly a dollar-cycle result; SPY as the benchmark for a Roth book; composite overlap (EFA
contains EWJ/EWG/EWU); and §1091 substantial identity for `VWO`/`EEM` and `ILF`/`EWZ`, which ticker
disjointness does not establish and this round does not claim.

## 6. Disposition

- **Nothing promoted** (plan §7: measurement study; every margin inside the floor; every rotation cell
  negative against SPY and at best level with its own passive control).
- What the round bought: the first measurement of a *country* rotation axis in this programme, and it
  reads exactly like the sector axis (rounds 17, 34) — the rules add nothing the basket does not already
  carry. The passive-control design worked and is worth reusing: it separated "the rules lost" from
  "the asset class lost" cleanly, and here it was entirely the latter.
- Files: `cards/`, `results/<window>/runs/`, `results/*.log`, `scorecard.json`, `ANALYSIS.md`,
  `analysis.json`.
