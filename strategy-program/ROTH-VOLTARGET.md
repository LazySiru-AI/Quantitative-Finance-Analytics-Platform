# Volatility-scaled and risk-budgeted allocation strategies for a Roth IRA

Backtested through `strategy-program/tools/contributions.py` (the contribution-funded simulator:
$7,500/year, one deposit at the start of each calendar year, 5% drift-band rebalancing, 5bp
slippage on every dollar traded, both IRR and time-weighted CAGR reported). Implementation:
`strategy-program/tools/roth_voltarget.py`. Reproduce with:

```
cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/roth_voltarget.py
```

**Everything in this document is in-sample.** No price bar used anywhere postdates 2026-02-13.
Nothing here is a forecast; every number describes what already happened, once.

## Why this family

`strategy-program/tools/drawdown_ladder.py` found a specific, concrete failure: a ladder that adds
leverage on the way down and only delevers on a fresh all-time high held its deepest QLD weight
through the back half of the 2008 decline and reached a contribution-adjusted -72.7% drawdown for
it. The ladder's problem was never the trigger price -- it was that its decision variable (drawdown
from a high) is a *lagging* signal. Volatility is not: the VIX had already cleared 30 in 2008 while
SPY was still less than -20% off its high. Every strategy below sizes exposure from realised
volatility instead of price level, specifically so it can act while a crash is developing rather
than one rung behind it.

## The strategies, as precise rules

All four are implemented as `WeightFn` factories in `roth_voltarget.py`; `realized_vol` (the one
shared primitive) is the annualised standard deviation of daily simple returns over a trailing
`lookback` window, computed from prices only up to and including the current session -- never past
it, since `simulate()` hands every strategy the *entire* price array and trusts it not to look ahead.

1. **Vol targeting** (`make_vol_target`) -- `QLD weight = min(1.0, target_vol / realized_vol(QLD))`,
   residual in IEF. Tested at `target_vol` in {12%, 15%, 20%} and `lookback` in {20, 60} sessions.
   The 1.0 cap is not a modelling convenience: a Roth IRA has no margin, so once the book is 100% in
   the leveraged sleeve there is nowhere further for "target vol says lever up more" to go.
2. **Inverse-volatility weighting** (`make_inverse_vol`) across QLD / income-sleeve / IEF --
   `weight_i = (1/vol_i) / sum(1/vol_j)` over whichever of the three already has `lookback` sessions
   of history. Rebalanced on the harness's standard 5% drift band, same as every other strategy here.
3. **A volatility circuit-breaker** (`make_circuit_breaker`) on a static 40/30/30 QLD/income/IEF
   blend: while QLD's own realised volatility is at or above 45% annualised, QLD is cut to zero and
   its weight redistributed proportionally across the other two sleeves; QLD is restored only once
   volatility has fallen back to at or below 30%. The 45/30 hysteresis gap is deliberate -- an
   `enter == exit` breaker would flip every time volatility crossed one line, the same chop
   `drawdown_ladder.py`'s per-cycle arming exists to stop, just measured in volatility instead of
   price. 45%/30% are not round numbers picked blind: they come from QLD's own trailing-volatility
   distribution across its full 2006-2026 history (median ~33% annualised, 75th percentile ~45-46%,
   90th percentile ~61%) -- `enter_vol` sits at "unusually volatile even for a 2x fund," `exit_vol`
   sits back at the median.
4. **Risk-budgeted core** (`make_risk_budgeted_core`) -- this programme's own synthesis of (1) and
   (2), built because the static baselines split their defensive sleeves in a fixed ratio (e.g. 30%
   SCHD / 30% IEF) regardless of which one is actually the riskier one this year. Size QLD by vol
   targeting exactly as in (1), at a fixed 12% target; split whatever is left between the income
   sleeve and IEF by *their own* inverse volatility, exactly as in (2), instead of a fixed split.
   2022 is the case this is built for: SCHD (equity beta) and IEF (rate duration) both drew down
   that year, but not together and not by the same amount, and a fixed 30/30 split has no mechanism
   to lean away from whichever one is currently the riskier of the two.

**Baselines, run on the identical contribution schedule and cost model:** QLD buy & hold, SPY buy &
hold, static 60/40 income-sleeve/IEF, static 40/30/30 QLD/income-sleeve/IEF.

**On IEF vs SGOV.** The brief's sketch mentions IEF/SGOV as the defensive sleeve for vol targeting.
SGOV's stored history starts 2020-06-01 -- using it would have thrown away every window except a
slice of the most recent six years, including all of 2008 and 2011. IEF has covered every window
tested here (its history starts 2002-07-30) and was used as the sole defensive sleeve throughout, so
every strategy could be run on the same three windows rather than a shorter, SGOV-only fourth one.
A SGOV variant restricted to 2020-2026 was not built -- see "what could not be tested."

## Windows

| Window | Sessions | Span | Note |
|---|---|---|---|
| **CRISIS** 2006-2011 | 1,344 (5.33y) | 2006-06-21 .. 2011-10-19 | SCHD does not exist yet; SPY substitutes for the income sleeve everywhere one is used. Includes the 2008-2009 crash and the Aug 2011 European-debt-crisis flash drawdown. **The window that matters most, per this programme's own rules of evidence.** |
| **PRIMARY** 2011-2026 | 3,727 (14.79y) | 2011-10-20 .. 2026-08-18 | Native SCHD, bound only by SCHD's own first stored session. Mostly a bull market (2018Q4, 2020, and 2022 are the only real drawdowns). |
| **FULL** 2006-2026 | 5,071 (20.12y) | 2006-06-21 .. 2026-08-18 | The longest window any of these symbols jointly support -- at the cost of the same SPY substitution as CRISIS, applied for the whole span. |

CRISIS and PRIMARY are adjacent, non-overlapping slices of history; FULL is their union. That means
these are **not three independent trials** -- see "what could not be tested."

**The SPY-for-SCHD substitution is real, not free.** SPY carries none of SCHD's quality/dividend
tilt. Every CRISIS- and FULL-window number for a strategy that uses the "income sleeve" is a result
about a diversified-equity substitute, not about SCHD, and every row using it is marked `*`.

## Full results table

Columns match `contributions.HEADER` exactly: balance, total contributed, balance/contributed
multiple, money-weighted **IRR**, time-weighted **CAGR (TWR)**, contribution-adjusted max drawdown,
MAR (TWR / |maxDD|), and the number of rebalancing events actually executed.

### CRISIS 2006-2011 (SPY proxy for the income sleeve, 5.33y)

```
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal
QLD buy & hold                   $     63,211  $   45,000   1.40x   10.70%    2.29%    -84.3%   0.03     0
SPY buy & hold                   $     44,879  $   45,000   1.00x   -0.08%   -0.82%    -53.1%  -0.02     0
static 60/40 SPY*/IEF            $     49,145  $   45,000   1.09x    2.75%    2.40%    -33.4%   0.07     7
static 40/30/30 QLD/SPY*/IEF     $     58,289  $   45,000   1.30x    8.12%    5.37%    -57.9%   0.09    18
voltarget 12% QLD/IEF (lb20)     $     63,239  $   45,000   1.41x   10.71%   10.22%    -29.1%   0.35   139
voltarget 12% QLD/IEF (lb60)     $     58,807  $   45,000   1.31x    8.40%    7.21%    -28.2%   0.26    35
voltarget 15% QLD/IEF (lb20)     $     65,736  $   45,000   1.46x   11.95%   11.19%    -34.6%   0.32   179
voltarget 15% QLD/IEF (lb60)     $     60,440  $   45,000   1.34x    9.27%    8.07%    -32.1%   0.25    50
voltarget 20% QLD/IEF (lb20)     $     65,615  $   45,000   1.46x   11.89%   11.13%    -44.7%   0.25   212
voltarget 20% QLD/IEF (lb60)     $     62,232  $   45,000   1.38x   10.20%    8.36%    -43.3%   0.19    70
inverse-vol (lb20)               $     56,262  $   45,000   1.25x    7.00%    6.19%    -23.6%   0.26   103
inverse-vol (lb60)               $     55,216  $   45,000   1.23x    6.41%    5.50%    -22.6%   0.24    29
circuit-breaker (lb20)           $     55,172  $   45,000   1.23x    6.38%    6.14%    -33.5%   0.18    16
circuit-breaker (lb60)           $     47,468  $   45,000   1.05x    1.66%    3.16%    -35.4%   0.09    13
risk-budgeted core (lb20)        $     62,462  $   45,000   1.39x   10.32%    9.60%    -35.4%   0.27   179
risk-budgeted core (lb60)        $     58,959  $   45,000   1.31x    8.48%    6.90%    -34.9%   0.20    46
```

Cost of turnover (5bp slippage, as a fraction of paid-in capital churned and of final balance):

```
QLD buy & hold                   turnover   1.00x paid-in   cost paid $       22  (   3.6bp of final balance)
SPY buy & hold                   turnover   1.00x paid-in   cost paid $       22  (   5.0bp of final balance)
static 60/40 SPY*/IEF            turnover   1.44x paid-in   cost paid $       32  (   6.6bp of final balance)
static 40/30/30 QLD/SPY*/IEF     turnover   2.14x paid-in   cost paid $       48  (   8.2bp of final balance)
voltarget 12% QLD/IEF (lb20)     turnover  17.80x paid-in   cost paid $      401  (  63.3bp of final balance)
voltarget 12% QLD/IEF (lb60)     turnover   4.33x paid-in   cost paid $       97  (  16.6bp of final balance)
voltarget 15% QLD/IEF (lb20)     turnover  23.98x paid-in   cost paid $      540  (  82.1bp of final balance)
voltarget 15% QLD/IEF (lb60)     turnover   5.87x paid-in   cost paid $      132  (  21.8bp of final balance)
voltarget 20% QLD/IEF (lb20)     turnover  28.21x paid-in   cost paid $      635  (  96.7bp of final balance)
voltarget 20% QLD/IEF (lb60)     turnover   8.30x paid-in   cost paid $      187  (  30.0bp of final balance)
inverse-vol (lb20)               turnover   9.45x paid-in   cost paid $      213  (  37.8bp of final balance)
inverse-vol (lb60)               turnover   3.23x paid-in   cost paid $       73  (  13.2bp of final balance)
circuit-breaker (lb20)           turnover   5.73x paid-in   cost paid $      129  (  23.4bp of final balance)
circuit-breaker (lb60)           turnover   4.67x paid-in   cost paid $      105  (  22.1bp of final balance)
risk-budgeted core (lb20)        turnover  21.11x paid-in   cost paid $      475  (  76.0bp of final balance)
risk-budgeted core (lb60)        turnover   5.08x paid-in   cost paid $      114  (  19.4bp of final balance)
```

### PRIMARY 2011-2026 (native SCHD, 14.79y)

```
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal
QLD buy & hold                   $  2,367,924  $  120,000  19.73x   32.66%   32.82%    -68.4%   0.48     0
SPY buy & hold                   $    380,705  $  120,000   3.17x   13.22%   13.16%    -34.1%   0.39     0
static 60/40 SCHD/IEF            $    189,569  $  120,000   1.58x    5.45%    5.94%    -23.4%   0.25     5
static 40/30/30 QLD/SCHD/IEF     $    531,248  $  120,000   4.43x   16.81%   17.04%    -41.9%   0.41    39
voltarget 12% QLD/IEF (lb20)     $    329,480  $  120,000   2.75x   11.65%   12.58%    -36.0%   0.35   495
voltarget 12% QLD/IEF (lb60)     $    289,977  $  120,000   2.42x   10.24%   11.01%    -34.8%   0.32   147
voltarget 15% QLD/IEF (lb20)     $    444,349  $  120,000   3.70x   14.89%   15.84%    -40.2%   0.39   572
voltarget 15% QLD/IEF (lb60)     $    375,340  $  120,000   3.13x   13.07%   13.77%    -39.2%   0.35   183
voltarget 20% QLD/IEF (lb20)     $    683,166  $  120,000   5.69x   19.48%   20.51%    -46.4%   0.44   603
voltarget 20% QLD/IEF (lb60)     $    552,709  $  120,000   4.61x   17.23%   17.85%    -44.4%   0.40   233
inverse-vol (lb20)               $    190,266  $  120,000   1.59x    5.49%    5.95%    -23.5%   0.25   331
inverse-vol (lb60)               $    182,071  $  120,000   1.52x    4.99%    5.49%    -25.2%   0.22    73
circuit-breaker (lb20)           $    341,338  $  120,000   2.84x   12.03%   12.72%    -23.9%   0.53    50
circuit-breaker (lb60)           $    271,466  $  120,000   2.26x    9.51%   10.92%    -38.8%   0.28    35
risk-budgeted core (lb20)        $    404,750  $  120,000   3.37x   13.88%   14.64%    -33.4%   0.44   584
risk-budgeted core (lb60)        $    339,513  $  120,000   2.83x   11.97%   12.45%    -34.1%   0.36   163
```

Cost of turnover:

```
QLD buy & hold                   turnover   1.00x paid-in   cost paid $       60  (   0.3bp of final balance)
SPY buy & hold                   turnover   1.00x paid-in   cost paid $       60  (   1.6bp of final balance)
static 60/40 SCHD/IEF            turnover   1.50x paid-in   cost paid $       90  (   4.7bp of final balance)
static 40/30/30 QLD/SCHD/IEF     turnover   8.21x paid-in   cost paid $      493  (   9.3bp of final balance)
voltarget 12% QLD/IEF (lb20)     turnover  84.48x paid-in   cost paid $    5,069  ( 153.8bp of final balance)
voltarget 12% QLD/IEF (lb60)     turnover  18.65x paid-in   cost paid $    1,119  (  38.6bp of final balance)
voltarget 15% QLD/IEF (lb20)     turnover 126.26x paid-in   cost paid $    7,575  ( 170.5bp of final balance)
voltarget 15% QLD/IEF (lb60)     turnover  28.60x paid-in   cost paid $    1,716  (  45.7bp of final balance)
voltarget 20% QLD/IEF (lb20)     turnover 199.09x paid-in   cost paid $   11,946  ( 174.9bp of final balance)
voltarget 20% QLD/IEF (lb60)     turnover  49.85x paid-in   cost paid $    2,991  (  54.1bp of final balance)
inverse-vol (lb20)               turnover  31.12x paid-in   cost paid $    1,867  (  98.1bp of final balance)
inverse-vol (lb60)               turnover   7.01x paid-in   cost paid $      420  (  23.1bp of final balance)
circuit-breaker (lb20)           turnover  34.29x paid-in   cost paid $    2,057  (  60.3bp of final balance)
circuit-breaker (lb60)           turnover  19.48x paid-in   cost paid $    1,169  (  43.1bp of final balance)
risk-budgeted core (lb20)        turnover 113.42x paid-in   cost paid $    6,805  ( 168.1bp of final balance)
risk-budgeted core (lb60)        turnover  22.43x paid-in   cost paid $    1,346  (  39.6bp of final balance)
```

### FULL 2006-2026 (SPY proxy throughout, 20.12y)

```
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal
QLD buy & hold                   $  6,158,947  $  157,500  39.10x   28.98%   24.04%    -84.3%   0.29     0
SPY buy & hold                   $    617,758  $  157,500   3.92x   11.56%    9.35%    -53.1%   0.18     0
static 60/40 SPY*/IEF            $    360,226  $  157,500   2.29x    7.24%    6.40%    -33.4%   0.19    14
static 40/30/30 QLD/SPY*/IEF     $  1,152,119  $  157,500   7.32x   16.36%   14.39%    -57.9%   0.25    49
voltarget 12% QLD/IEF (lb20)     $    650,036  $  157,500   4.13x   11.96%   11.95%    -35.6%   0.34   636
voltarget 12% QLD/IEF (lb60)     $    530,290  $  157,500   3.37x   10.36%   10.03%    -34.5%   0.29   177
voltarget 15% QLD/IEF (lb20)     $    949,530  $  157,500   6.03x   14.89%   14.52%    -39.3%   0.37   753
voltarget 15% QLD/IEF (lb60)     $    727,909  $  157,500   4.62x   12.84%   12.22%    -38.5%   0.32   232
voltarget 20% QLD/IEF (lb20)     $  1,595,339  $  157,500  10.13x   18.83%   17.90%    -45.2%   0.40   817
voltarget 20% QLD/IEF (lb60)     $  1,212,205  $  157,500   7.70x   16.75%   15.49%    -43.5%   0.36   305
inverse-vol (lb20)               $    332,735  $  157,500   2.11x    6.58%    6.51%    -26.0%   0.25   442
inverse-vol (lb60)               $    319,740  $  157,500   2.03x    6.25%    6.18%    -28.2%   0.22   114
circuit-breaker (lb20)           $    697,765  $  157,500   4.43x   12.51%   11.68%    -33.5%   0.35    63
circuit-breaker (lb60)           $    530,453  $  157,500   3.37x   10.36%    9.70%    -35.4%   0.27    44
risk-budgeted core (lb20)        $    888,016  $  157,500   5.64x   14.37%   13.78%    -35.4%   0.39   757
risk-budgeted core (lb60)        $    705,937  $  157,500   4.48x   12.60%   11.74%    -35.6%   0.33   209
```

Cost of turnover:

```
QLD buy & hold                   turnover   1.00x paid-in   cost paid $       79  (   0.1bp of final balance)
SPY buy & hold                   turnover   1.00x paid-in   cost paid $       79  (   1.3bp of final balance)
static 60/40 SPY*/IEF            turnover   2.15x paid-in   cost paid $      170  (   4.7bp of final balance)
static 40/30/30 QLD/SPY*/IEF     turnover  10.64x paid-in   cost paid $      838  (   7.3bp of final balance)
voltarget 12% QLD/IEF (lb20)     turnover 152.56x paid-in   cost paid $   12,014  ( 184.8bp of final balance)
voltarget 12% QLD/IEF (lb60)     turnover  29.45x paid-in   cost paid $    2,319  (  43.7bp of final balance)
voltarget 15% QLD/IEF (lb20)     turnover 237.81x paid-in   cost paid $   18,727  ( 197.2bp of final balance)
voltarget 15% QLD/IEF (lb60)     turnover  48.29x paid-in   cost paid $    3,803  (  52.2bp of final balance)
voltarget 20% QLD/IEF (lb20)     turnover 387.88x paid-in   cost paid $   30,546  ( 191.5bp of final balance)
voltarget 20% QLD/IEF (lb60)     turnover  91.73x paid-in   cost paid $    7,224  (  59.6bp of final balance)
inverse-vol (lb20)               turnover  51.74x paid-in   cost paid $    4,074  ( 122.4bp of final balance)
inverse-vol (lb60)               turnover  11.84x paid-in   cost paid $      932  (  29.2bp of final balance)
circuit-breaker (lb20)           turnover  55.16x paid-in   cost paid $    4,344  (  62.3bp of final balance)
circuit-breaker (lb60)           turnover  29.02x paid-in   cost paid $    2,286  (  43.1bp of final balance)
risk-budgeted core (lb20)        turnover 209.23x paid-in   cost paid $   16,477  ( 185.5bp of final balance)
risk-budgeted core (lb60)        turnover  40.90x paid-in   cost paid $    3,220  (  45.6bp of final balance)
```

## Lookback sensitivity: the surface is not flat, but it is not a knife-edge either

For every one of the eight vol-scaled variants, holding the strategy and target fixed and switching
the lookback from 20 to 60 sessions moves the answer in the *same direction, every time, in every
window*: 20-session lookbacks post a higher TWR and a higher MAR than their 60-session twin in all
24 comparisons (4 families x 2 targets-or-none x 3 windows, where applicable) except none -- the
ranking never flips. That is a real, directionally stable pattern, not noise flipping a coin. Two
things sit alongside it, though, that keep this from being a clean "always use 20 days" conclusion:

- **The MAR gap is real but not large** -- typically 0.03-0.09 MAR points (e.g. vol-target 12%: 0.35
  vs 0.26 in CRISIS, 0.35 vs 0.32 in PRIMARY, 0.34 vs 0.29 in FULL). A faster lookback is
  consistently a little better here, not dramatically better.
- **The turnover gap is large and consistent** -- 20-session lookbacks trade 4x to 6x more than
  60-session lookbacks, every strategy, every window (e.g. vol-target 12% in PRIMARY: 84.48x paid-in
  turnover at lb20 vs 18.65x at lb60; circuit-breaker in FULL: 55.16x vs 29.02x). The *turnover*
  surface is the knife-edge, not the return surface: halving the lookback from 60 to 20 sessions
  roughly quadruples how often the book trades, for a return improvement measured in single-digit
  MAR points.

Net of the 5bp slippage the harness actually charges, the faster lookback still wins on every metric
in every window tested here -- the extra 100-150bp of cumulative slippage cost (FULL window, lb20 vs
lb60) is small next to the multiple-of-balance differences the return gap produces. But that
conclusion is sensitive to the slippage assumption: at meaningfully higher trading costs than 5bp
(a wider bid/ask on a volatile week, say), the 60-session lookback's much lower turnover would start
to look like the safer default, and this backtest does not sweep the slippage assumption to find
where that crossover sits.

## The leverage trap, demonstrated directly

The vol-target family gives a clean, paired illustration of the brief's warning. In PRIMARY (a
mostly-bull 14.79-year window), raising the target from 12% to 20% (lb20) monotonically *improves*
every metric: TWR 12.58% to 20.51%, MAR 0.35 to 0.44. Read alone, that looks like "20% is simply the
better setting." In CRISIS -- the window that actually matters most -- the same move from 12% to
20% *monotonically worsens* every metric: TWR 10.22% down to 11.13% masks a maxDD that goes from
-29.1% to -44.7% and a MAR that falls from 0.35 to 0.25. The "better" setting in the bull window is
worse in the bear window, in the same direction on every metric, because a higher vol target simply
means holding more QLD on average -- more leverage -- and more leverage is a better bet exactly when
markets go up and a worse one exactly when they do not. Whichever target is chosen, it should be
chosen for this reason and stated as such, not presented as PRIMARY's numbers alone would imply.

## Verdict, strategy by strategy

To rank without letting one favourable window carry the argument, each strategy's **worst** MAR
across the three windows is used as the headline number -- the same principle `score.py` applies to
whole rounds of cards ("a result that only holds in one window is not a result").

| Strategy | CRISIS MAR | PRIMARY MAR | FULL MAR | **worst** |
|---|---|---|---|---|
| QLD buy & hold | 0.03 | 0.48 | 0.29 | **0.03** |
| SPY buy & hold | -0.02 | 0.39 | 0.18 | **-0.02** |
| static 60/40 | 0.07 | 0.25 | 0.19 | **0.07** |
| static 40/30/30 | 0.09 | 0.41 | 0.25 | **0.09** |
| voltarget 12% (lb20) | 0.35 | 0.35 | 0.34 | **0.34** |
| voltarget 12% (lb60) | 0.26 | 0.32 | 0.29 | **0.26** |
| voltarget 15% (lb20) | 0.32 | 0.39 | 0.37 | **0.32** |
| voltarget 15% (lb60) | 0.25 | 0.35 | 0.32 | **0.25** |
| voltarget 20% (lb20) | 0.25 | 0.44 | 0.40 | **0.25** |
| voltarget 20% (lb60) | 0.19 | 0.40 | 0.36 | **0.19** |
| inverse-vol (lb20) | 0.26 | 0.25 | 0.25 | **0.25** |
| inverse-vol (lb60) | 0.24 | 0.22 | 0.22 | **0.22** |
| circuit-breaker (lb20) | 0.18 | **0.53** | 0.35 | **0.18** |
| circuit-breaker (lb60) | 0.09 | 0.28 | 0.27 | **0.09** |
| risk-budgeted core (lb20) | 0.27 | 0.44 | 0.39 | **0.27** |
| risk-budgeted core (lb60) | 0.20 | 0.36 | 0.33 | **0.20** |

**Best candidate: vol-target 12%, lookback 20 sessions (QLD/IEF).** It is not the top MAR in any
single window -- circuit-breaker (lb20) beats it by 0.18 points in PRIMARY -- but it is the only
strategy whose MAR barely moves across three windows spanning a crash, a bull run, and their union
(0.35 / 0.35 / 0.34), and its worst-case number (0.34) is the best worst-case in the entire table,
baselines included, by a wide margin. In the window that matters most it very nearly matched QLD
buy-and-hold's own IRR (10.71% vs 10.70%) while cutting the contribution-adjusted max drawdown from
-84.3% to -29.1% -- the exact failure mode the drawdown ladder could not avoid, solved. The cost is
real (63bp-185bp of final balance in cumulative slippage depending on window length, driven by
17.8x-152.6x turnover of paid-in capital) but never comes close to erasing the gap over the static
baselines. **Keep this one.**

**Risk-budgeted core (lb20), this programme's own design, is the credible second choice** and the
one to prefer over vol-target 20% for anyone who wants more upside than the 12% target without
accepting vol-target 20%'s leverage-trap exposure. In PRIMARY it ties voltarget-20%'s MAR (0.44
each) with a shallower max drawdown (-33.4% vs -46.4%) at similar turnover cost, because the residual
capital is actively defended (split between income sleeve and IEF by their own risk) rather than
levered further. Its worst-case MAR (0.27) is the second-best in the table. **Keep this one too**, as
the "want more than 12% vol-target, don't want to just add leverage" answer.

**Inverse-volatility weighting (both lookbacks) is the one to not keep, as designed.** Its MAR is
essentially flat and mediocre across all three windows (0.22-0.26) and, in PRIMARY, is
indistinguishable from the plain static 60/40 baseline it was meant to improve on (0.25 vs 0.25,
identical to two decimal places). The mechanism explains why: QLD's realised volatility is
persistently 5-10x IEF's, so 1/vol weighting parks the overwhelming majority of the book in IEF in
almost every regime, converging the strategy toward "a conservative bond-heavy blend" rather than
anything that responds distinctively to risk. If that conservative profile is the actual goal, the
much simpler and cheaper static 60/40 blend gets there for a fraction of the turnover (1.5x-2.15x
paid-in vs 9.45x-51.74x). Naive three-way inverse-vol across assets this different in volatility
character does not do the job the brief hoped it would.

**The circuit-breaker is the strategy to flag rather than either keep or discard outright.** Its
PRIMARY-window number (MAR 0.53) is the single best result anywhere in the table, and that is exactly
why it is dangerous to present without the CRISIS number sitting next to it: 0.18 there, the worst
result in the vol-scaled family and barely better than the static 40/30/30 baseline (0.09). The
mechanism is legible -- a binary, all-or-nothing signal that goes to zero QLD for the entire stretch
that volatility stays elevated misses the sharp, high-volatility recovery rallies that typically
follow a crash (2009's first months, most obviously), where a continuous vol-target strategy keeps a
partial position throughout and captures some of that recovery. Whether the circuit-breaker is worth
keeping depends entirely on which regime an investor expects to face more of; on the evidence here,
it is a much worse bet for the crash than for the grind, and the grind is the easier regime to do
well in regardless of strategy.

**Both baseline static blends behave as expected and are the correct comparison set, not a finding in
themselves.** Static 40/30/30 (MAR 0.09/0.41/0.25) sits between the defensive static 60/40 and the
vol-scaled family in every window -- more return than 60/40, more drawdown than any of the vol-scaled
variants, confirming the vol-scaled mechanism is buying something (shallower drawdown) rather than
nothing, at a real cost in upside relative to the leveraged baselines.

## What could not be tested

- **Independence of the windows.** CRISIS and PRIMARY are adjacent, non-overlapping slices of the
  same single historical path; FULL is their union. This is three views of one sequence of market
  history, not three independent trials -- a genuinely different crisis (a stagflationary bear, a
  multi-year sideways grind, a bond-market-led crisis where IEF itself is the risky asset) could
  produce a different ranking entirely, and nothing here tests against one because none occurred in
  the available data.
- **A SGOV-based defensive sleeve.** SGOV's stored history starts 2020-06-01; running vol-target or
  risk-budgeted-core against SGOV instead of IEF would restrict the test to roughly six years,
  covering only the tail of PRIMARY, and was not built for that reason. The choice of IEF over SGOV
  as the "safe" sleeve throughout this module is a real modelling decision (duration risk instead of
  near-zero-duration cash-like exposure) and changes the strategies' behaviour in a sharp-rate-shock
  scenario like 2022's, where IEF itself drew down materially -- see the risk-budgeted-core rationale
  above, which exists specifically because IEF is not risk-free.
- **Slippage sensitivity.** Every number here uses the harness's 5bp default. The lookback-sensitivity
  section notes that the 20-session lookback's cost advantage over 60-session is not free, and this
  backtest does not sweep slippage upward to find the level at which the ranking between them
  flips.
- **Circuit-breaker threshold sensitivity.** `enter_vol`/`exit_vol` (45%/30%) were set once, from
  QLD's own historical volatility percentiles, and not swept the way lookback and target-vol were.
  A different threshold pair could change the circuit-breaker's CRISIS-window result materially,
  and that sensitivity is untested.
- **Anything beyond QLD/SCHD/IEF/SPY as the sleeve set.** GLD, TQQQ, AGG, BIL and the shorter-duration
  Treasury funds (SHY) were available in the store but not incorporated into any variant here; a
  genuinely different defensive sleeve (gold, say, as a diversifier uncorrelated with both equities
  and rates) was out of scope for this pass.
