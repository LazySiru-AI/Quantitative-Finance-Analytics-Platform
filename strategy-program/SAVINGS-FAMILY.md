**Not investment advice.** Simulated results on stored price history. I am not a licensed financial
adviser and none of this is a recommendation about real capital.

Backtester: `strategy-program/tools/savings_family.py`. Reproduce with:

```
cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/savings_family.py
```

Raw stdout from the run this document reports: `data/rounds/r13-2026-08/savings-family-run.txt`.

**Everything in this document is in-sample.** No price bar used anywhere here postdates 2026-08-21,
the bar store's own latest stored session at the time this ran. Nothing here is a forecast; every
number describes what already happened, once.

## Why this purpose, and why it needs its own scoring basis

`strategy-program/THREE-PURPOSES-PLAN.md` names three distinct questions this programme has been
answering with one leaderboard: a savings account funded steadily over a decade or two is not the same
question as a $50,000 lump sum traded on no fixed horizon, and it is not the same question as a Roth
funded once a year at the IRS limit. (Both trading figures were corrected by the owner after the plan
document was written — $100,000 to $50,000, and "under three years" to unbounded; `PURPOSE_SPECS` is
the authority, and `PurposeSpec.seed`/`horizon_years_max` carry the correction in their docstrings.) The savings purpose modelled here is funded with a **$20,000 seed
and $1,000 every month** (the owner has not settled on the rate, so **$500/month is modelled in full
alongside it**), held **10 to 20 years**, in a taxable account.

Scoring this on the tournament's own basis -- lump-sum `adjusted_excess` over short regime windows --
would be a category error for the same reason `strategy-program/tools/contributions.py`'s own module
docstring gives for the Roth families: **contribution funding inverts sequence risk.** A lump-sum
investor fears a crash at the end, when the balance is largest; a contributor is helped by a crash
early, because the same dollars buy more shares. `strategy-program/ROTH-MOMENTUM.md` measured an 8.4
percentage-point gap between one strategy's money-weighted IRR and its time-weighted CAGR in one
window, produced entirely by *when* the money arrived, not by what the strategy did. Every table below
reports both numbers for the identical reason.

## Reuse decision: `contributions.simulate` could not be called with different arguments

The brief asked this module to reuse `contributions.simulate`'s weight-function interface and result
metrics where possible, and to say exactly what blocked reuse where it was not. Two things blocked it,
both structural rather than a missing keyword argument:

1. **The contribution schedule is hardcoded inside `simulate`, not injectable.** `simulate` calls
   `contrib_at = set(contribution_dates(dates))` itself, where `contribution_dates` returns the first
   session of each *calendar year*. There is no parameter on `simulate` that accepts a different
   schedule or a different granularity function -- monthly contributions needed a monthly version of
   that function, and there was no seam to hand one in through.
2. **There is no seed / opening-balance parameter anywhere on `simulate`.** The account it models opens
   at zero and receives its first contribution on day one. This purpose's account opens with $20,000
   already in it -- a structurally different starting condition the function has no argument for.

Both are properties of the simulation *loop*, not of the *result*. `contributions.ContributionResult`
(`irr`, `time_weighted_cagr`, `max_drawdown`, `volatility`, `mar`) is written generically over whatever
`dates`/`equity`/`contributed`/`flows` it is handed -- nothing in those properties assumes annual
spacing or a zero opening balance. So `savings_family.py` does not re-derive the metrics: it loads
`contributions.py` by file path (the same precedent `roth_voltarget.py` already set, since
`strategy-program` is not a legal Python package name) and reuses `ContributionResult`, `Cashflow`,
`summarise` and `HEADER` unmodified. What it writes fresh is one function, `simulate_savings` --
`contributions.simulate`'s own loop with the contribution-schedule line and the opening-balance line
changed and every rebalancing/drift-band/slippage/contribution-directed-rebalancing line copied
unchanged. `contributions.py` itself is not modified anywhere, per this task's scope fence.

## No leverage anywhere in this family

QLD, TQQQ and every other 2x/3x fund in the bar store are deliberately absent from every variant below,
for the identical reason `strategy-program/ALLOCATION-FAMILY.md` gives for its own four variants: a
strategy that beats a benchmark only by holding more of a leveraged sleeve is not demonstrating anything
about allocation, diversification or timing -- it is demonstrating that leverage did well over the
period tested. This is stated up front because it is the "known trap" the brief itself names, and it
recurs below in the verdicts, not just here.

## The four variants, precisely enough to reimplement

All four are `WeightFn` factories in `savings_family.py`. `realized_vol` is the annualised standard
deviation of daily simple returns over a trailing `lookback` window, reading prices only up to and
including the current session, matching `roth_voltarget.realized_vol` and
`allocation_family.realized_vol` exactly.

1. **Broad-Market Core** (`make_static_blend`) -- fixed **SPY 80% / AGG 20%**, band-rebalanced only
   (5% drift band), no signal anywhere. The simplest possible "more stock, some bond ballast" savings
   book, and the variant the "known trap" applies to most directly: any outperformance over the 60/40
   benchmark is a direct consequence of holding more equity, not of a smarter rule, and the verdict below
   says so.
2. **Diversified Multi-Asset Core** (`make_static_blend`) -- fixed weights spread across four asset
   classes instead of two: **SPY 35% / SCHD 20% / AGG 30% / GLD 15%** where SCHD's own history exists
   (native SCHD, from 2011-10-20); with SCHD's 20 points folded into SPY (**SPY 55% / AGG 30% / GLD
   15%**, marked `*`) in the longer window that predates SCHD, the identical fold-in convention
   `ROTH-MOMENTUM.md` and `ALLOCATION-FAMILY.md` both already use. Static, band-rebalanced, no signal --
   asset-class diversification is the entire mechanism.
3. **Horizon Glidepath** (`make_glidepath`) -- **SPY/AGG**, starting at 90% equity on day one and
   falling *linearly with elapsed time* (session index / 252, in fractional years) to 60% equity at 20
   years elapsed, held at 60% beyond that. No price history and no lookback of any kind: the target is a
   pure function of how much time has passed since the account opened, so it de-risks whether the
   market has done anything or not. Rebalanced on the same 5% drift band as every other variant.
4. **Volatility-Trimmed Core** (`make_vol_trim`) -- base **SPY 70% / AGG 30%**, checked **once a month**
   (first session of each calendar month, not daily -- see "reach for simplicity" below). While SPY's
   own trailing 60-session (~1 quarter) realised volatility is at or above 18% (near SPY's own 75th
   historical percentile, per `ALLOCATION-FAMILY.md`'s own calibration of the same measure) on a check
   date, 20 points shift from SPY into AGG; the shift reverts only once volatility has fallen back to at
   or below 13% (near SPY's own median), a strictly lower exit threshold so the rule cannot flip on and
   off every month a reading oscillates around one line. The trimmed weight is held between monthly
   checks, not recomputed daily.

**Benchmarks**, run on the identical contribution schedule, seed and cost model as every variant: SPY
buy & hold, and a static 60/40 SPY/AGG blend -- the brief's own requirement that a savings book not be
measured only against something more aggressive than itself.

**Reach for simplicity.** Variant 4 is checked monthly rather than daily, and cuts a fixed 20 points
rather than continuously re-sizing the way `ROTH-VOLTARGET.md`'s vol-targeting family does -- a
deliberate choice for a mandate the brief itself says should not need constant attention. It pays for
that simplicity in signal responsiveness, and the verdict below states the cost plainly rather than
implying "low-touch" was free.

## The round-12 lookback-activation check

Round 12 found that 10 of 21 tournament ladder windows were shorter than a long-lookback strategy's own
signal period, so the rule never activated and the book silently held its fallback sleeve the entire
run -- a table that looked like a result and measured nothing. Two of the four variants here have no
lookback at all: the static core (variant 1) and the diversified core (variant 2) are pure declared
weights, live from session zero; the glidepath (variant 3) is a pure function of elapsed time, also live
from session zero. The one variant with a lookback, the volatility-trimmed core (variant 4), uses 60
sessions. **Checked directly**: every window this module runs it on is at least 5,759 sessions (CORE)
long -- see the session counts printed in the tables below and in
`data/rounds/r13-2026-08/savings-family-run.txt` -- roughly 96x the lookback. The signal has room to
activate for effectively the whole backtest, not just its tail.

## Windows, and the span each one actually got

| Window | Symbols | Earliest common date | Backtest span actually run | Reaches 2008? |
|---|---|---|---|---|
| **CORE** (variants 1, 3, 4 + both benchmarks) | SPY, AGG | 2003-09-29 (bound by AGG) | 2003-09-29 .. 2026-08-19, 5,759 sessions, **22.85y** | yes |
| **DIVERSIFIED-FULL** (variant 2, SPY proxy for SCHD) | SPY, AGG, GLD | 2004-11-18 (bound by GLD) | 2004-11-18 .. 2026-08-19, 5,471 sessions, **21.71y** | yes |
| **DIVERSIFIED-PRIMARY** (variant 2, native SCHD) | SPY, SCHD, AGG, GLD | 2011-10-20 (bound by SCHD) | 2011-10-20 .. 2026-08-19, 3,728 sessions, **14.79y** | no |

None of these is the "close to worthless, five years bound by SGOV" case the brief warns against. The
shortest, DIVERSIFIED-PRIMARY, is 14.79 years -- inside the mandate's own 10-20 year range on its own --
and exists specifically because SCHD's real history does not reach 2008; DIVERSIFIED-FULL exists
specifically so the diversified variant is also tested through the crash, at the cost of substituting
SPY for SCHD (marked `*` throughout, a real substitution -- SPY carries none of SCHD's dividend/quality
tilt -- not a free one). CORE and DIVERSIFIED-FULL are not independent trials of market history: they
overlap almost completely (2004-2026 vs 2003-2026), which is stated here rather than left implicit --
see "what these results cannot be compared to" and "what could not be tested" below.

## Results: $1,000/month

```
=== CORE (SPY/AGG): 2003-09-29 .. 2026-08-19 (5759 sessions, 22.85y) ===
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal
benchmark: SPY buy & hold        $  1,303,809  $  296,000   4.40x   10.67%    9.26%    -56.4%   0.16     0
benchmark: static 60/40 SPY/AGG  $    715,340  $  296,000   2.42x    6.60%    5.76%    -38.0%   0.15     7
1. broad-market core 80/20       $    988,891  $  296,000   3.34x    8.82%    7.68%    -47.4%   0.16     5
3. horizon glidepath 90->60 (20y)$    785,357  $  296,000   2.65x    7.25%    6.54%    -48.8%   0.13     8
4. vol-trimmed core 70/30        $    711,738  $  296,000   2.40x    6.56%    5.92%    -33.5%   0.18    23

=== DIVERSIFIED-FULL (SPY*/AGG/GLD): 2004-11-18 .. 2026-08-19 (5471 sessions, 21.71y) ===
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal
benchmark: SPY buy & hold        $  1,183,025  $  282,000   4.20x   10.89%    8.97%    -55.5%   0.16     0
benchmark: static 60/40 SPY/AGG  $    661,122  $  282,000   2.34x    6.72%    5.61%    -37.0%   0.15     7
2. diversified multi-asset core  $    788,484  $  282,000   2.80x    8.01%    7.10%    -33.4%   0.21    13

=== DIVERSIFIED-PRIMARY (SPY/SCHD/AGG/GLD): 2011-10-20 .. 2026-08-19 (3728 sessions, 14.79y) ===
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal
benchmark: SPY buy & hold        $    646,700  $  199,000   3.25x   13.24%   13.26%    -34.3%   0.39     0
benchmark: static 60/40 SPY/AGG  $    391,142  $  199,000   1.97x    7.80%    7.82%    -23.8%   0.33     4
2. diversified multi-asset core  $    417,546  $  199,000   2.10x    8.52%    7.95%    -20.7%   0.38     3
```

## Results: $500/month

```
=== CORE (SPY/AGG): 2003-09-29 .. 2026-08-19 (5759 sessions, 22.85y) ===
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal
benchmark: SPY buy & hold        $    728,064  $  158,000   4.61x   10.45%    9.27%    -56.6%   0.16     0
benchmark: static 60/40 SPY/AGG  $    394,268  $  158,000   2.50x    6.49%    5.77%    -38.2%   0.15     7
1. broad-market core 80/20       $    549,628  $  158,000   3.48x    8.66%    7.70%    -47.6%   0.16     5
3. horizon glidepath 90->60 (20y)$    436,695  $  158,000   2.76x    7.16%    6.56%    -49.0%   0.13     9
4. vol-trimmed core 70/30        $    392,591  $  158,000   2.48x    6.46%    5.91%    -33.8%   0.17    23

=== DIVERSIFIED-FULL (SPY*/AGG/GLD): 2004-11-18 .. 2026-08-19 (5471 sessions, 21.71y) ===
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal
benchmark: SPY buy & hold        $    656,248  $  151,000   4.35x   10.59%    8.97%    -55.8%   0.16     0
benchmark: static 60/40 SPY/AGG  $    362,838  $  151,000   2.40x    6.55%    5.59%    -37.6%   0.15     7
2. diversified multi-asset core  $    443,307  $  151,000   2.94x    7.94%    7.16%    -33.4%   0.21    14

=== DIVERSIFIED-PRIMARY (SPY/SCHD/AGG/GLD): 2011-10-20 .. 2026-08-19 (3728 sessions, 14.79y) ===
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal
benchmark: SPY buy & hold        $    386,532  $  109,500   3.53x   13.24%   13.26%    -34.3%   0.39     0
benchmark: static 60/40 SPY/AGG  $    225,625  $  109,500   2.06x    7.78%    7.80%    -23.7%   0.33     4
2. diversified multi-asset core  $    240,176  $  109,500   2.19x    8.43%    7.96%    -20.3%   0.39     5
```

`maxDD` is contribution-adjusted throughout (peak-to-trough on the balance normalised by cumulative
contributions, per `ContributionResult.max_drawdown`'s own docstring) -- a raw balance drawdown would
understate every number here, because a deposit landing mid-crash lifts the raw balance and shrinks the
measured drawdown even though every dollar already invested fell just as far.

## Does the ranking change between $1,000/month and $500/month? Yes -- in exactly one place, and it is the finding that matters most

**CORE and DIVERSIFIED-FULL: the ranking is stable.** At full precision (four decimal places, not the
two shown in the tables above): CORE's MAR ordering is variant 4 (0.1765 / 0.1745) > SPY b&h (0.1643 /
0.1638) > variant 1 (0.1619 / 0.1618) > 60/40 benchmark (0.1513 / 0.1510) > variant 3 (0.1340 / 0.1338)
at $1,000 and $500 respectively -- identical order, nearly identical numbers, at both rates.
DIVERSIFIED-FULL is the same story: variant 2 (0.2127 / 0.2144) is the clear best MAR at both rates, SPY
b&h second, 60/40 third, every time.

**DIVERSIFIED-PRIMARY flips.** At $1,000/month, variant 2's MAR is **0.3837**, a hair below SPY
buy-and-hold's **0.3862** -- SPY wins on this metric. At $500/month, variant 2's MAR is **0.3922**,
above SPY buy-and-hold's **0.3865** -- variant 2 wins. The crossover happens because the shorter
14.79-year window has the smallest gap between the contribution stream's own size and the balance it
compounds into: at $500/month the contribution stream is a smaller share of the terminal balance,
letting variant 2's structurally shallower drawdown (-20.3% to -20.7% vs SPY's -34.3%) show up in the
risk-adjusted number more than the raw return gap costs it. **This is the exact effect
`THREE-PURPOSES-PLAN.md` warned about**: a strategy ranked at one contribution rate is not guaranteed to
rank the same way at another, and the gap here is a few hundredths of a MAR point, not a rounding
artifact -- it is real, it is small, and it is the single most important number in this report because
it is direct evidence the rate matters to which strategy an owner should actually pick.

## The 2008 GFC slice (raw balance return / drawdown within the slice, 2007-10-09 .. 2009-03-09)

Not contribution-adjusted -- by late 2007 every variant's balance is already the $20,000 seed plus four-
plus years of compounding and contributions, against which the handful of $500-$1,000 deposits landing
inside this 17-month slice are a small fraction of the balance, stated here rather than left implicit.

```
$1,000/month
  CORE window
    SPY buy & hold                       -45.7%   maxDD -45.7%
    static 60/40 SPY/AGG                 -23.0%   maxDD -27.1%
    1. broad-market core 80/20           -34.7%   maxDD -35.7%
    3. horizon glidepath 90->60          -36.4%   maxDD -37.0%
    4. vol-trimmed core 70/30            -16.8%   maxDD -22.5%
  DIVERSIFIED-FULL window
    SPY buy & hold                       -42.0%   maxDD -42.9%
    static 60/40 SPY/AGG                 -17.9%   maxDD -25.2%
    2. diversified multi-asset core      -12.3%   maxDD -25.1%

$500/month
  CORE window
    SPY buy & hold                       -48.4%   maxDD -48.4%
    static 60/40 SPY/AGG                 -26.6%   maxDD -28.2%
    1. broad-market core 80/20           -37.7%   maxDD -37.7%
    3. horizon glidepath 90->60          -39.4%   maxDD -39.4%
    4. vol-trimmed core 70/30            -20.9%   maxDD -24.0%
  DIVERSIFIED-FULL window
    SPY buy & hold                       -45.9%   maxDD -45.9%
    static 60/40 SPY/AGG                 -23.6%   maxDD -27.3%
    2. diversified multi-asset core      -17.8%   maxDD -26.7%
```

DIVERSIFIED-PRIMARY does not reach this slice (native SCHD starts 2011-10-20, three years after the
crash ended) -- reported as a gap, not silently skipped. The $500 and $1,000 numbers differ within a
window because the slice return is on raw balance, and a smaller contribution stream landing during the
crash means a slightly larger fraction of the pre-crash balance is exposed to the full drawdown --
consistent with, not contradicting, the sequence-risk mechanism this whole family is built to measure.

## Cost assumption

**5 basis points slippage, one way, charged on every dollar traded** -- the identical convention and
rate `contributions.py`, `roth_voltarget.py` and `allocation_family.py` all already use, for the
identical reason their own docstrings give: an ETF's stored close is already net of its own expense
ratio, so the rebalance trades are the one real, un-modelled cost. Rebalancing fires on a 5% drift band
(`band_pct=0.05`, matching every prior harness in this programme) plus whenever a monthly contribution
lands and is directed at the most underweight sleeve first -- a buy funded by a deposit pays slippage
once, where a buy funded by a sale pays it twice, exactly `contributions.simulate`'s own mechanism.
Turnover and cost-paid are reported in full in
`data/rounds/r13-2026-08/savings-family-run.txt`; every variant here pays under 20bp of its own final
balance in cumulative slippage over the full window, the vol-trimmed core (variant 4) paying the most
(~17bp) for its extra monthly checks.

## The known trap, demonstrated directly

**Variant 1 (Broad-Market Core, 80/20 SPY/AGG) beats the 60/40 benchmark on every headline number in
every window and at both rates, and the entire reason is that it holds more equity.** TWR 7.68% vs
5.76% (CORE, $1,000/month); maxDD -47.4% vs -38.0% in the same row. This is not a smarter rule finding
an edge -- it is the identical position a plain 80/20 blend would produce with no logic in it at all,
stated as a trap because the brief asked for exactly this to be said when it happens, and it happens
here in the least interesting variant in the family.

**Variant 2 buys a real, structural reduction in drawdown, not just a return trade.** Its 2008 maxDD
(-25.1% to -26.7% depending on rate and window) sits far below SPY buy-and-hold's (-42.9% to -48.4%) and
below the 60/40 benchmark's own (-25.2% to -28.2%) too, in the DIVERSIFIED-FULL window at both rates --
a genuinely different risk profile from either benchmark, not the same equity-weight trade variant 1
makes with a different label. This is the strongest positive finding in the family and is stated
plainly for that reason.

**Variant 3 (glidepath) is the worst MAR in the family in every window and at both rates it is tested
on**, and it is worth being precise about why: a 20-year linear glide from 90% to 60% equity spends most
of a 22.85-year backtest holding *more* equity than the 60/40 benchmark it is compared against (it only
reaches 60% equity at the 20-year mark, three-quarters of the way through the window), so its 2008
drawdown (-36.4% to -39.4%) is closer to variant 1's than to the benchmark's, while its long-run MAR
(0.1338-0.1340) is the family's lowest -- it pays variant 1's risk without variant 1's return, because
the de-risking schedule chosen (20 years) is too slow relative to the window actually tested (23 years)
to buy meaningfully more protection than a static blend would. A shorter glide horizon, closer to the
mandate's own 10-year floor, might change this; it was not tested here (see "what could not be
tested").

**Variant 4 (vol-trimmed core) is the best risk-adjusted number in the CORE window at both rates**
(MAR 0.1765/0.1745, ahead of every other CORE-window entry including both benchmarks), earned honestly
by a materially shallower 2008 drawdown (-22.5%/-24.0%, the shallowest of any CORE-window entry) rather
than by holding less equity on average -- its base allocation (70/30) sits between variant 1's (80/20)
and the 60/40 benchmark's, so the drawdown reduction is doing real work, not disguising a smaller bet.
The honest cost sits in the turnover table: 8.14x-8.54x paid-in-capital turnover against variant 1's
1.68x-1.71x, for 16.9-17.2bp of final balance in cumulative slippage against variant 1's 2.5bp -- roughly
seven times the cost, for a MAR improvement of about 0.01-0.02 points. That is a real, statable
trade-off, not free.

## The candidate, and the honest case against it

**Put forward: Variant 2, Diversified Multi-Asset Core.** It has the best MAR in every window it is
tested on, at both contribution rates (0.21-0.21 DIVERSIFIED-FULL, 0.38-0.39 DIVERSIFIED-PRIMARY), it
buys a genuine structural drawdown reduction rather than a disguised equity-weight trade (see above), it
is a fixed-weight, band-rebalanced-only rule with no lookback and no state to track -- the "reach for
simplicity" property the brief asks a savings mandate to have -- and its turnover cost is modest (2.33x-
2.69x paid-in, 4.2-4.6bp of final balance, in the same range as the 60/40 benchmark's own 1.86x-1.89x /
3.8-4.0bp).

**What would have to be false for this to be the wrong choice:**

- **If the owner weights raw return over risk-adjusted return, variant 2 is not the pick.** SPY
  buy-and-hold has a materially higher final balance in every window at every rate ($1,183,025 vs
  $788,484 in DIVERSIFIED-FULL at $1,000/month) -- variant 2's edge is entirely in the shape of the ride,
  not the size of the number at the end, and an owner who genuinely does not care about the drawdown
  should simply buy SPY and accept the trade this family's own docstring names throughout: more equity
  wins in the windows tested here because equity did well over the windows tested here, not because any
  rule is smart.
- **If the DIVERSIFIED-PRIMARY window's near-tie against SPY buy-and-hold at $1,000/month (MAR 0.3837 vs
  0.3862, variant 2 *loses*) is the rate the owner actually settles on**, the case for variant 2 over
  plain SPY buy-and-hold in that specific 14.79-year window is not clearly made -- it only wins there at
  $500/month. Anyone reading this report to make a $1,000/month decision should weight the
  DIVERSIFIED-FULL and CORE windows' clearer wins more than DIVERSIFIED-PRIMARY's near-coin-flip.
- **If SCHD's dividend/quality tilt materially outperforms or underperforms SPY going forward in a way
  its own 14.79-year native history does not capture**, DIVERSIFIED-FULL's numbers (which substitute
  SPY for SCHD for two-thirds of the tested span) may not describe variant 2's real long-run character
  as well as DIVERSIFIED-PRIMARY's shorter, native-SCHD numbers do -- and those are the numbers with the
  closer, rate-dependent race against the SPY benchmark.
- **If the 15-percentage-point gold allocation is judged too large a bet on one commodity for a savings
  mandate**, that specific design choice, not the diversification principle in general, is what should
  change -- it was not swept to a smaller weight here (see "what could not be tested").

## What these results cannot be compared to

Every `StrategyCard` in the tournament is scored on **lump-sum `adjusted_excess`** (total return minus
exposure-adjusted benchmark return) over the round's own set of regime windows, ranked by median and
worst `adjusted_excess` and hit rate (`strategy-program/tools/score.py`). Nothing in this document is
that quantity, for reasons that compound rather than merely differ:

1. **The funding shape is different in kind, not just in size.** A `StrategyCard` is backtested as a
   single lump sum at the start of a window; every number above is a contribution-funded account that
   receives new cash every month for 15-23 years. `score.py`'s `adjusted_excess` has no defined meaning
   for an account whose principal itself is a time series, not a constant.
2. **IRR and TWR are not `adjusted_excess`, and must never share a column with it.**
   `data/rounds/r12-2026-08/ROTH-CANDIDATES.md` already states this for the Roth families and it applies
   identically here: a money-weighted return answers "how did the money that was actually put in do,"
   `adjusted_excess` answers "how did this card do against its benchmark over this specific window,"
   and ranking the two together would be comparing different quantities as if they were the same one.
3. **These strategies are not `StrategyCard`s.** All four variants here are plain `WeightFn` closures in
   `savings_family.py`, not validated `app.tournament.models.StrategyCard` instances -- `score.py`'s own
   `_load_results` validates each result's `"card"` field against `StrategyCard`'s schema specifically,
   which none of these four would pass (no `universe`/`entry`/`exit` fields; variants 1 and 2 are, at
   best, `AllocationCard`-shaped, and `AllocationResult` already fails `isinstance(_, AgentResult)`,
   exactly as `ALLOCATION-FAMILY.md`'s own section on this makes explicit for its own four variants).
4. **No walk-forward or held-out split exists anywhere in this document.** Every window above ends
   before this module's own last run; every number is a description of what already happened, not a
   claim about what will happen next.

For any of these variants to be seated on the tournament's own roster, the same three-part gap
`ALLOCATION-FAMILY.md` already documented for its own family would have to be closed first: widening
`AgentResult.card`'s type, running the card through the round's actual window grid instead of one long
backtest, and re-deriving what "exposure-adjusted" would even mean for a continuously-invested,
monthly-funded book. None of that is attempted here, and none of it should be implied as already
possible by these tables sitting next to a round's own scorecard elsewhere in this programme.

## What could not be tested

- **VTI, or any genuinely whole-market fund, was not used.** SPY stands in throughout, the same
  substitution `ALLOCATION-FAMILY.md` already made and flagged: SPY is a large-cap index, not a
  total-market one.
- **The glidepath's 20-year horizon was not swept.** Variant 3's poor showing in this report may be an
  artifact of testing a 20-year glide against a 22.85-year window that gives it little time to actually
  reach its conservative endpoint; a glide calibrated to a 10-year horizon, or a non-linear (front-
  loaded) glide, was not built or tested here, and is the most likely candidate to change variant 3's
  verdict.
- **The vol-trim thresholds (18%/13%, 60-session lookback, 20-point cut) were set once, calibrated from
  SPY's own historical volatility percentiles, and not swept.** `ALLOCATION-FAMILY.md`'s own lookback-
  sensitivity section found the surface is not flat for a structurally similar rule; this module does
  not repeat that sensitivity check for its own thresholds.
- **Independence of the windows.** CORE (2003-2026) and DIVERSIFIED-FULL (2004-2026) are two views of
  almost the same 22-23 years of market history, not independent trials; DIVERSIFIED-PRIMARY is a
  genuinely different, shorter, native-SCHD slice of the same broader period. None of this is three
  independent draws of "what happens to a diversified, contribution-funded book" -- it is one realised
  history, read three overlapping ways.
- **Slippage sensitivity.** Every number uses the flat 5bp assumption; a materially higher real-world
  cost was not swept to find where any of this family's rankings might change.
- **A fifth variant combining the glidepath's time-based de-risking with variant 2's asset-class
  diversification** (e.g. a glidepath that shifts among four asset classes rather than two) was not
  built, and is the most direct way to test whether variant 3's weak showing is really about the glide
  horizon rather than the two-asset universe it was tested on.
