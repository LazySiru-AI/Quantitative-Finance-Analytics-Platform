# Round 32 — the dedicated inflation-level round: is the near-miss real, or the rate in disguise?

Pre-registered 2026-08-30, before any measurement in this round exists. **Not investment advice.**

Round 31 closed the macro line on a null but left one genuine near-miss: **core CPI year-over-year
inflation above its trailing 60-month mean precedes lower forward equity returns** — broad across
2000-2024, robust to bootstrap block length, orthogonal to price momentum, reaching an uncorrected
p=0.009 on SPY at the quarterly horizon, and missing q<0.10 only by the 24-cell multiple-testing tax.
This round tests that single hypothesis on its own. It is the follow-up round 31 §5 named.

---

## 1. The honesty this round is built around

**Re-running round 31's strongest cell without the /24 tax is not new evidence.** The cell was *selected*
from a 24-cell grid; removing the correction it was chosen under is arithmetic, not confirmation. A
dedicated round that only did that would be the "re-running a frozen card is not a new draw" trap. So the
tax-free single p-value (Test 0 below) is reported as a **baseline, explicitly excluded from the decision
rule.** The round's real content is three tests the grid never ran, each on evidence round 31 did not use:

- **regime breadth** — the same hypothesis on 56 years (1970-2026), containing five or six inflation
  regimes instead of the SPY era's one, with **1970-1992 as a genuine out-of-sample half** round 31's
  selection never touched;
- **the rate-level confound** — is it inflation, or just the high nominal rates and high cash yields that
  accompany it? Round 31 controlled only for price momentum, never for rates;
- **exploitability vs cash** — the effect is lower *positive* returns; is avoiding equities in hot
  inflation actually better than holding the yield that prevails then?

The hypothesis is fixed to round 31's headline: transform `level`, 60-month trailing mean, core CPI
(`CPILFESL`), quarterly horizon (h=63), release-date bound at the 45-day lag. **No grid, no alternative
window, no target search** — one hypothesis, decided before this file was written.

## 2. The measurement

### 2a. The out-of-sample equity series (the decisive new evidence)

Round 31's targets (SPY from 1993, QQQ from 1999) cannot see a pre-1993 inflation regime. This round
builds a **26-name equal-weight portfolio** from every store symbol with a continuous daily history
beginning **1970-01-01** — a mechanical, non-cherry-picked selection (all names with a 1970 first bar):

`AEP BA CAT CNP CVX DIS DTE ED GD GE HON HPQ IBM IP JNJ KO KR LMT MCD MMM MO MRK MSI PG RTX XOM`

They span utilities, industrials, energy, staples, tech, health, defense and materials; all 26 are
present across the whole window (a balanced panel, no survivorship-within-window gaps). Forward return at
a rebalance date is the equal-weight mean of the 26 names' `h`-session forward returns. **The 1970-1992
sub-sample is out-of-sample in the strongest sense available:** round 31 selected this hypothesis on
1993-2026 SPY data and never touched a pre-1993 bar.

### 2b. The three tests and the baseline

- **Test 0 — baseline (mechanical, NOT decision-relevant).** Re-run the exact cell: `CPILFESL` level,
  SPY, h=63, single block-bootstrap p, no BH tax. Reported only to state plainly that removing the tax
  is arithmetic.
- **Test 1 — regime breadth (decisive).** The hypothesis on the 26-name portfolio over the full
  1970-2026, and split **1970-1992 (OOS) vs 1993-2026**. Spread = `mean(fwd | hot) - mean(fwd | cool)`,
  block-bootstrap p, for each sub-sample and the whole. The OOS half is the single most important number
  in this round.
- **Test 2 — the rate-level confound.** Residualize the portfolio's forward return within **terciles of
  the contemporaneous DGS10 rate level** (release-lagged), then recompute the hot-vs-cool spread. If the
  inflation spread survives conditioning on the rate level, it is inflation-specific; if it collapses, it
  is the rate level in disguise — and round 30 already measured the rate level as null, which would make
  the near-miss a known non-signal, not a new one.
- **Test 3 — exploitability vs cash.** Compare hot-regime forward equity return to the contemporaneous
  DGS10 yield scaled to the horizon (an imperfect cash-floor proxy — DGS10 is the 10-year, not a T-bill,
  the only rate in the pin). If hot-regime equity still beats the floor, the effect is real but a weak
  defensive tilt; if it underperforms, there is an exploitable avoid-signal.

### 2c. Shared machinery

Block bootstrap and BH from round28; spread and the tercile-residualization from round30/31; release-lag
binding and YoY construction from round31. `SEED = 32`. Non-overlapping quarterly rebalance
(`cal[::63]`). No new statistical definition is introduced.

## 3. Predictions (falsifiable, fixed before the run)

1. **The 1970-1992 out-of-sample half is negative** (hot inflation -> lower forward equity), the same
   sign selected on 1993-2026. This is the test. *Refuted if* the OOS spread is non-negative.
2. **The spread survives the rate-level control, weakened but same sign.** Inflation and the rate level
   are entangled, so I expect attenuation, not disappearance. *Refuted if* it flips sign or falls inside
   noise after the control.
3. **Hot-regime forward equity still beats the DGS10 cash floor** — the effect is lower gains, not an
   avoidable loss, so it is real but weakly exploitable. *Refuted if* hot-regime equity underperforms the
   floor.
4. **The full 1970-2026 spread is negative with a larger effective sample than round 31** — more regimes,
   same sign. *Refuted if* the full-sample sign is non-negative.

## 4. Decision rule (pre-registered)

The near-miss becomes a **card candidate** — earning a further pre-registered *card* round, which would
need the round-23/25 substitution trick to express — **only if BOTH**: (a) the 1970-1992 OOS sign holds
(Test 1) **AND** (b) the spread survives the rate-level control (Test 2). Exploitability (Test 3) informs
card *design*, not whether the effect is real.

- **OOS half null** -> round 31's near-miss was the one modern regime after all; the inflation line
  closes, and with it the macro line entirely.
- **Rate control kills it** -> it was the rate level in disguise, which round 30 already measured as
  null; the near-miss dissolves the way round 29's survivor dissolved into the beta premium, and the
  macro line closes.
- **Both hold** -> the first macro effect in the programme to survive a genuine out-of-sample test and an
  economic confound; a card round is justified, stress-tested against Test 3's exploitability first.

**Test 0's tax-free p is not in this rule.** The decision rests only on evidence round 31 did not use.

## 5. Determinism and honesty about scope

- `SEED = 32`, fixed. Mechanical universe (all 1970-start names). Release lag 45 days; YoY and eligibility
  causal by construction; non-overlapping windows.
- **What this cannot settle:** the 26 names are survivors (survivorship inflates the return *level*;
  it should not bias the hot-vs-cool *spread* unless survival correlates with inflation-regime
  performance, which is not expected — but it is a caveat); the equal-weight portfolio tilts industrial
  and defensive, not the true market; DGS10 is a 10-year proxy for a cash rate the pin does not carry;
  the CPI **revision leak** is unchanged (YoY on a possibly-revised index is not strict point-in-time);
  and h=63 only, fixed, with no horizon robustness by design (that would reintroduce a grid).
- Return statistic only. **No card, no engine, no backtest, nothing promotable.**
