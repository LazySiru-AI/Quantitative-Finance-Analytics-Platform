# Round 38 — report: the real-yield tilt is null, and a price-only placebo does the same job better

Run 2026-09-09 through the bespoke harness `strategy-program/tools/round38_run.py` (there is no
`score.py` for `AllocationCard`s). Seven cards, the 5y/10y rungs judged, 3y reported, six bear
supplements, `desk._mandate(SAVINGS)` at $100,000, macro pin = round 21's frozen seven-series FRED pin.
Pre-registration: `strategy-program/ROUND-38-PLAN.md` (2026-09-09). Tables: `ANALYSIS.md`, mirrored in
`analysis.json`.

**Not investment advice.** Price-only bars; AGG/GLD/BIL distributions are unmodelled, so every CAGR is
understated and the drawdown column is the trustworthy half. Benchmark is the 30/70 SPY/AGG blend, not
SPY. From `creator-b`'s and `Creator D`'s rate theses — the corpus supplied the hypothesis, the programme
supplies the null; no influencer is endorsed.

---

## 1. Result — null, and the macro line stays closed

Treatment-minus-control on the judged rungs, in drawdown (positive = shallower, the mandate's axis) and
MAR:

| card | condition | fired rungs | dd margin | MAR margin | CAGR margin |
|---|---|---|---|---|---|
| **realyield-hi-1** (primary) | real yield > 1.0% → BIL | 4/5 | **+0.37pp** | +0.001 | −0.11pp |
| realyield-hi-2 | real yield > 2.0% → BIL | 2/5 | +0.00pp | −0.045 | −0.77pp |
| realyield-lo-1 | real yield < 1.0% → SPY | 5/5 | −1.72pp | +0.030 | +1.08pp |
| nominal-hi-4 | nominal 10y > 4.0% → BIL | 3/5 | +0.03pp | −0.037 | −0.67pp |
| breakeven-lo-2 | breakeven < 2.0% → BIL | 4/5 | +0.78pp | −0.032 | −0.76pp |
| **price-placebo** (no macro) | close < sma(200) → BIL | 5/5 | **+0.94pp** | −0.003 | −0.30pp |

Every margin is a fraction of a point of drawdown and near-zero MAR — far inside any floor. **The null
is the result**, and it matches rounds 30 and 32: no macro series, including this previously-untested
real-yield spread, carries drawdown-relevant information a savings book can use.

## 2. The placebo dominates — the sharpest reading

Plan §5 pre-registered prediction P3: if the price-only placebo matches the macro cards, no macro
result is attributable to the macro signal. It does not merely match — the placebo's drawdown
improvement (**+0.94pp**) is *larger* than the primary real-yield card's (+0.37pp). A plain
`close < sma(200)` de-risking rule shallows the drawdown more than the real-yield signal does. So the
small defensive benefit that exists belongs to going defensive on price weakness, not to the real
yield. The macro term adds nothing on top of price — the same verdict rounds 30 and 32 reached for
every other series.

## 3. The degenerate card behaved exactly as pre-declared

`realyield-hi-2` (real yield > 2.0%) fired in **0 of 6 bear windows** and only 2 of 5 judged rungs —
right at the `MIN_ELIGIBLE_R5_PER_HORIZON = 2` boundary. Plan §6 pre-declared it structurally
incapable of producing crisis evidence, and it was: its margins are ~0 because the condition rarely
fires. It is reported UNMEASURED-adjacent, never as a null about real yield. This is why 1.0%, not
2.0%, was the primary threshold — a feasibility screen on the regressor made before any outcome.

## 4. `realyield-lo-1` is a beta tilt, not an edge

Adding equity when the real yield is low returned +1.08pp of CAGR at −1.72pp of drawdown — more return
for more risk, MAR essentially flat (+0.030). That is the book taking more beta, not the signal
finding anything; the mandate's axis is drawdown, and it moved the wrong way.

## 5. Disposition

- **Nothing promoted.** Null by the rule; the macro term is dominated by a price placebo; nothing
  reaches the paper desk. The savings book is unchanged.
- The programme's **first macro-conditioned savings round** joins the closed macro line. What it adds:
  the real-yield spread `DGS10 − T10YIE`, the one construction rounds 30-32 never tested, is null too,
  and on the savings book specifically.
- Files: `cards/`, `scorecard.json` (empty — allocation cards are scored by the bespoke harness, not
  `score.py`), `ANALYSIS.md`, `analysis.json`, and the harness `strategy-program/tools/round38_run.py`.
