# Round 47 — report: buying weakness and selling strength on a held basket changes exposure, not the answer

Run 2026-09-09, eight main windows, 12 cards (3 baskets × 4 arms), 96 runs, zero `FAILED` lines.
Pre-registration: `strategy-program/ROUND-47-PLAN.md` (2026-09-09, frozen in commit `5baac42` before
the run). Computed tables: `ANALYSIS.md`, from `strategy-program/tools/round47_report.py`, mirrored in
`analysis.json`. Scorecard: `scorecard.json` (`score.py --pin-store`). All cards `purpose = roth`;
`disjoint_field.py` 12/12, eligible 8/8. Run through the repaired `run_round.sh` guard (commit
`43dcc4f`). The `passive` and `trim` cells are byte-identical to round 44's and reproduce its numbers
exactly (power-passive +6.79pp, power-trim +9.16pp, control-passive −1.22pp), which is the
determinism check the plan required and nothing more — the same window set re-run is one measurement,
not two (`PROTOCOL.md` §6(a)).

**Not investment advice.** Price-only bars, no dividends (utilities and defense names are high payers),
SPY benchmark for a Roth book, a synthetic paper book. The arms translate two personas' disciplines —
Creator A's and Creator C's "accumulate on pullbacks inside an uptrend" and Creator B's
"trim after exceptional gains" — into one rule each and their combination; the personas named neither
these tickers nor these thresholds, and no influencer is endorsed.

---

## 1. Result — null on every arm

Arm minus its own basket's passive control, median adjusted excess:

| basket | dip | trim | dip-trim | six fair windows (dip / trim / dip-trim) | 2024-26 windows |
|---|---|---|---|---|---|
| power | −0.94pp | +2.36pp | −0.08pp | −0.23 / +4.69 / +1.78pp | −2.61 / +0.33 / −1.73pp |
| defense | −0.55pp | +0.76pp | +0.08pp | +0.48 / +0.83 / +1.62pp | +0.85 / +0.38 / −0.53pp |
| control | +0.12pp | +0.00pp | +0.58pp | +0.39 / +0.00 / +0.39pp | +1.40 / +0.81 / +2.80pp |

Largest margin in the field: power-trim +2.36pp, a ninth of the 21.2pp floor. BH over all 12 cells
against `r47-control-passive`: minimum q **0.17** (the four power cells, p 0.039–0.086), nothing under
0.10. **Decision rule (plan §4), applied:** no arm clears the floor, nothing survives BH. **The null is
the result.** Nothing is promoted.

## 2. What the numbers do say, short of a finding

1. **The dip entry is an exposure haircut, not a signal.** Every dip-entry cell sits out the start of
   each window until the first qualifying pullback — 0 to 85 sessions (`ANALYSIS.md`, days-to-first-
   entry) — and then holds. Mean exposure falls from 0.96–0.99 (passive) to 0.75–0.86 (dip), and the
   adjusted-excess change tracks that haircut: −0.94pp on power, where the missed early sessions were
   the strong ones (`q4-2018` +12.7pp vs passive's +22.5pp), +0.12pp on the control, where they were
   not. Waiting for a pullback bought nothing the benchmark-adjusted metric credits.
2. **The trim is the only arm with a consistent sign, and it is round 44's result again.** Power-trim
   beats power-passive in 6 of 8 windows (p 0.031), +4.7pp on the six fair windows, by stepping out of
   utilities when they are 15% above their 200-day mean and so carrying less of their drawdowns
   (`gfc` +18.4pp vs +14.4pp; worst drawdown −40.9% vs −44.6%). It is still a 2.4pp median margin on a
   low-beta basket, and the same reading round 44 gave it: the asset class's defensiveness, trimmed a
   little, not a rule that earns its keep against the floor.
3. **Combining the two does not add.** `dip-trim` lands below `max(dip, trim)` in power (−2.45pp) and
   defense (−0.68pp) and above it only in the control (+0.46pp): prediction 5 held in 2 of 3. What the
   combination does buy is the shallowest worst window of any power cell (−4.21pp) at the lowest
   exposure (0.69) — a narrower distribution, not a higher centre.
4. **Trim lost to passive in `bull-2024` in all three baskets (−0.35 to −1.17pp) and won in `recent`
   in all three (+1.37 to +1.97pp)** — the same split round 44 found, which is why this round
   pre-registered only the first half.
5. **Sign-flip p-values are coin-flip territory** except the power-trim and the two control-dip cells
   (0.031–0.078), all of which fall to q ≥ 0.17 once the twelve comparisons are counted.

## 3. Predictions vs outcomes (plan §5)

| # | prediction | outcome |
|---|---|---|
| 1 | No arm beats passive by >21.2pp with q<0.10 | **HELD** — max +2.36pp, min q 0.17 |
| 2 | Dip arms' exposure below passive in every basket; their gap tracks the entry delay | **HELD** — 0.75–0.86 vs 0.96–0.99; days-to-first-entry 0–85 |
| 3 | dip-trim has the lowest exposure of its basket's four arms, every basket | **HELD** — 0.693 / 0.680 / 0.856 are each basket's minimum (control by 0.004) |
| 4 | Trim loses to passive in `bull-2024` (`recent` not predicted) | **HELD** — −0.70 / −1.17 / −0.35pp; `recent` +1.37 / +1.94 / +1.97pp |
| 5 | dip-trim − max(dip, trim) ≤ 0 in at least two of three baskets | **HELD** — power −2.45, defense −0.68, control +0.46 |
| 6 | No arm clears the floor on the six fair windows either | **HELD** — best +4.69pp (power-trim) |
| 7 | Validity: passive arms hold every name on essentially every session | **HELD** — 0.956–0.990, byte-identical to round 44 |

Seven of seven held. A round whose every prediction was the null and whose every prediction held has
measured the null precisely; it has not found a strategy.

## 4. Disposition

- **Nothing promoted, nothing seated.** §6 applies to the Roth book, but a measurement round
  pre-registers no promotion, and no cell is within a factor of nine of the floor.
- Files: `cards/`, `results/<window>/runs/`, `scorecard.json`, `ANALYSIS.md`, `analysis.json`,
  `score.log`, `run.log`.

## 5. What this round cannot settle

- **One pullback definition and one trim threshold.** `close < sma(50) and close > sma(200)` and
  `1.15` are the programme's round numbers; the personas stated neither. The plan says so.
- **No dividends.** NEE/DUK/SO and LMT/NOC/GD/RTX are high-yield names; every arm's return is
  understated by the yield, and dip arms forgo it while out of the market.
- **Three baskets of four survivors.** Individual names chosen in 2026 among companies still carrying
  the theme; a result about these twelve tickers, not about "power" or "defense".
- **Hindsight is unbounded** (`published = null` on every note). The six-window split bounds the
  2024-26 contamination, not the personas' knowledge of 2007-2022.
- **The power basket's standing positive is beta.** Rounds 44 and 47 agree: regulated utilities fall
  less than SPY in selloffs and `adjusted_excess` credits a near-fully-invested low-beta book for it.
  That is an allocation fact, not a rule, and it is the same thing round 29 found as its only survivor.
