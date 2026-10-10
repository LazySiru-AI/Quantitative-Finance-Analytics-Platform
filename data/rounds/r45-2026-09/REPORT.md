# Round 45 — report: no persona's enhancement improves another persona's method; the 5:1 bracket almost never fires

Run 2026-09-09, eight main windows, 14 cards (3 bases × up to 5 arms), 112 runs, zero `FAILED`
lines. Pre-registration: `strategy-program/ROUND-45-PLAN.md` (2026-09-09, frozen in commit `d400a4c`
before the run). Computed tables: `ANALYSIS.md`, from `strategy-program/tools/round45_report.py`,
mirrored in `analysis.json`. Scorecard: `scorecard.json` (`score.py --pin-store`). All cards
`purpose = trading` on the 12-name `_TAXABLE_GROWTH` pool; the `kim` base reproduces
`r40-rsi-confirm-slots6`'s round-40 figures exactly (+4.01pp median, −17.21pp worst, 8/8), the
determinism check the plan required.

**Not investment advice.** Price-only bars, no dividends, SPY benchmark, a synthetic paper book.
The three bases are three personas' methods as the vault renders them — Creator E's confirmation
conjunct (his best measured card), Creator C's vault draft (`ma-crossover`, fidelity 0.38) and
Creator B's vault draft (`band-reversion`, fidelity 0.0: his method is fundamentals and the
draft says so). The four enhancements are the other personas' stated disciplines translated into one
mechanical change each. Nothing is promotable on the `trading` purpose (`PROTOCOL.md` §9, r21).

---

## 1. Result — null on all four enhancements

Enhancement marginal = mean over its bases of (arm − own base), median adjusted excess:

| enhancement | whose component | bases | marginal | arm − base per base | BH q (m=14) |
|---|---|---|---|---|---|
| `trend100` (`and close > sma(100)`) | Creator C | kim, creator-b | **−1.37pp** | kim −3.97, creator-b +1.24 | 1.00 |
| `rr5` (take-profit = 5 × stop) | Creator B | kim, bee, creator-b | **+0.21pp** | kim +0.00, bee +0.63, creator-b +0.00 | 1.00 |
| `risk1pct` (size = 1% risk at the stop) | Creator E | kim, bee, creator-b | **−0.22pp** | kim −1.35, bee −0.59, creator-b +1.28 | 1.00 |
| `trim115` (exit `or close > sma(200) * 1.15`) | Creator B | kim, bee, creator-b | **+0.01pp** | kim −1.13, bee −0.29, creator-b +1.47 | 1.00 |

**Decision rule (plan §4), applied:** an enhancement earns something only if its marginal exceeds
21.2pp and its arm cells survive BH q<0.10. The largest marginal in either direction is −1.37pp,
a fifteenth of the floor; no arm cell has q below 1.0. **The null is the result: none of the four
persona disciplines, grafted onto another persona's method, moves that method by more than noise.**

## 2. What the numbers do say, short of a finding

1. **The 5:1 bracket is a no-op, as pre-registered.** The take-profit fired on 4 of 202 exits (2.0%)
   on `kim`, 4 of 160 (2.5%) on `bee`, and 0 of 114 on `creator-b`. Two of the three `rr5` cells are
   byte-identical to their base on every window but one or two; `bee-rr5`'s +0.63pp and its
   `recent` +14.70pp (vs +1.71pp) come from four target exits. Rounds 17/18 measured brackets at
   0.14pp; this round measures a deliberately asymmetric one at the same order of nothing.
2. **Creator E's 1%-risk sizing halves the tail without moving the centre.** On his own base,
   `risk1pct` cuts position size from 12.5% to 8.3%, exposure from 0.126 to 0.082, the worst window
   from −17.21pp to −11.41pp and the IQR from 8.3 to 5.7pp, at a cost of 1.35pp of median. Adjusted
   excess per unit of exposure rises (31.8 → 32.3pp) and the per-window sign pattern is unchanged
   8/8. On `creator-b` the same resizing lifts the median +1.28pp and halves the worst window (−13.66 →
   −5.69pp); on `bee`, where the resizing barely changes size (0.15 → 0.125), nothing happens
   (−0.59pp). Sizing is the one enhancement that behaved exactly as its persona describes it —
   survival, not edge — and §4 of the protocol is explicit that a smaller book's shallower worst
   window is a size effect, not a skill effect.
3. **Creator C's 20-week filter switches Creator E's method off.** `kim-trend100` keeps 31% of the
   base's trades (63 vs 202), drops exposure to 0.046 and the median to +0.04pp; its −3.94pp worst
   window is the shallowest in the family only because it is barely in the market. On `creator-b` the same
   filter adds +1.24pp. Neither is a finding; both are what a second regime filter on top of an
   existing one does.
4. **The trim exit costs upside in both strong-trend windows in every base** (prediction 5, 6 of 6):
   `kim` gives back 3.2pp in `bull-2024` and 10.2pp in `recent`; `bee` 0.8pp and 0.9pp; `creator-b` 1.2pp
   and 2.8pp. Where it helps (`kim` in `bear-2022` +2.1pp, `bee` in `gfc` +3.0pp) the help is a
   tenth of the floor.
5. **The three methods themselves, on one pool, rank as round 40 and round 39 would predict.** Creator E's
   conjunct +4.01pp (the only positive persona cell the programme has, still inside the floor and
   still carrying a −17.2pp `gfc`), Creator C's crossover +2.38pp, Creator B's
   band-reversion proxy −2.07pp — a proxy the draft itself scored at fidelity 0.0 for a method that is
   not technical. Nothing here is evidence about his actual fundamentals process.

## 3. Predictions vs outcomes (plan §5)

| # | prediction | outcome |
|---|---|---|
| 1 | Null for all four enhancements | **HELD** — max marginal −1.37pp, min q 1.0 |
| 2 | `trend100` cuts trades on both bases | **HELD** — kim 202→63, creator-b 114→71 |
| 3 | `rr5` target exits <10% on every cell | **HELD** — 2.0%, 2.5%, 0.0% |
| 4 | `risk1pct` lowers exposure and raises excess per unit exposure without flipping signs | **HELD on kim and creator-b** (8/8 and 7/8 signs); on `bee` exposure fell but excess per unit fell too (11.3→10.4pp) — the muted-on-`bee` half of the prediction held, the per-unit half did not |
| 5 | `trim115` lowers exposure and loses in `bull-2024` and `recent` | **HELD** — all three bases, both windows |
| 6 | Sign flips by regime; only the 8-window median is safe to read | **HELD** — e.g. `kim` spans −17.2 to +22.4pp |
| 7 | Degenerate-outcome guard (a thin cell unranked ≠ "did not help") | **N/A** — all 14 cells ranked 8/8 |

## 4. Disposition

- **Nothing promoted, nothing seated, nothing unseated.** `r40-rsi-confirm-slots6` stays where the
  owner directed it; this round neither strengthens nor weakens the case for that seat — it
  reproduces the card's numbers and shows that none of the four grafts improves them.
- Files: `cards/`, `results/<window>/runs/`, `scorecard.json`, `ANALYSIS.md`, `analysis.json`,
  `score.log`, `run.log`.

## 5. What this round cannot settle

- **The drafts are "inspired by", not the personas' methods.** `app.personas.strategy` maps prose onto
  one of eight rule shapes by a model call; Creator C's draft scored fidelity 0.38 and Creator B's 0.0. A null on `bee` or `creator-b` is a null on a rule shape the model chose, not on the channel.
- **One pool.** The drafts' own universes (2022-25 listings, one Roth-claimed name) could not run; the
  12-name taxable pool is a substitution, disclosed in the plan, and is not survivorship-free.
- **One translation per discipline.** "1% risk" as `0.01 / stop`, "5:1" as a fixed take-profit, "trim
  after exceptional gains" as 15% above the 200-day mean, "20-week filter" as `sma(100)` — each is one
  reasonable reading of prose the personas did not state as code.
- **Hindsight is unbounded** (`published = null` on every note in the corpus).
- **Price-only, dividend-free, SPY-benchmarked**, like every backtest in this programme.
