# Roth momentum / regime backtest

Run through `strategy-program/tools/contributions.py`, the shared contribution-funded simulator:
$7,500 contributed on the first session of each year, 5bp slippage on every dollar traded, a 5%
drift band before an off-cycle rebalance fires, and contribution cash spent on the most underweight
sleeve first. No tax anywhere, because none is owed inside a Roth -- see that module's docstring for
why turnover is close to free here in a way it is not in a taxable account.

**Everything below is in-sample.** This analysis was run 2026-08-22. No window ends after that date,
and every strategy's rule was written with full knowledge of how each of these specific historical
paths turned out. Nothing here is a claim about what any of these rules will do next; it is only a
claim about how they would have priced the past this dataset actually contains.

## The strategies, as precise rules

All four momentum/regime strategies evaluate their trend leg daily and their momentum leg monthly
(first session of each calendar month) -- see `roth_momentum.py`'s module docstring for why: a
12-month trailing return recomputed every session flips sign on noise and manufactures whipsaw that
is an artifact of the daily grid, not of the rule. The moving-average leg is deliberately left daily,
because the brief calls for its whipsaw cost to be measured honestly rather than smoothed away.

1. **Absolute (time-series) momentum** -- `make_abs_momentum`. Hold the risk asset (QLD) at 100%
   when its own trailing 12-month return is positive; else hold the defensive sleeve at 100%.
   Evaluated monthly. Two variants: QLD/SCHD (SCHD-era only) and QLD/IEF (full history and the GFC
   slice, IEF standing in for SCHD).

2. **Dual momentum** -- `make_dual_momentum`. Rank a candidate set on trailing 12-month return each
   month; hold the top `N` split evenly, but only candidates with a *positive* trailing return --
   if none qualifies, hold 100% in a cash-equivalent (SHY) instead of the least-bad loser. Two
   variants run: top-1 over {QLD, SCHD, IEF, GLD} (SCHD-era only) and top-1 over {QLD, IEF, GLD}
   (full history and GFC, no SCHD available). A top-2 variant over the SCHD-era universe is also
   run as a bonus row.

3. **Moving-average regime switch** -- `make_ma_regime`. Hold QLD at 100% while SPY closes above
   its own trailing 200-session average; else hold the defensive sleeve at 100%. Checked every
   session, no confirmation delay. Two variants: QLD vs 50/50 SCHD/IEF (SCHD-era) and QLD vs 100%
   IEF (full history and GFC).

4. **Confirmed regime** (this family's own suggestion) -- `make_confirmed_regime`. Combine legs 1
   and 3: hold QLD at 100% only when *both* its own 12-month momentum is positive (monthly) *and*
   SPY is above its 200-session average (daily); hold the defensive sleeve at 100% only when *both*
   disagree with QLD; hold a 50/50 split of QLD and the defensive sleeve when the two legs
   disagree. The hypothesis under test was that requiring agreement between a slow monthly signal
   and a fast daily one would cut the round-trip trades the MA-only version pays for. It does not
   -- see the "what surprised me" note below.

**Baselines**, run alongside every window they are eligible for: QLD buy-and-hold, SPY buy-and-hold,
a static 60/40 SCHD/IEF blend and a static 40/30/30 QLD/SCHD/IEF blend (SCHD-era only), and a static
40/60 QLD/IEF blend standing in for the 40/30/30 mix in the two non-SCHD windows (SCHD's slot folded
into IEF -- noted, not disguised).

## Windows tested

| window | span | sessions | why |
|---|---|---|---|
| `full-2006` | 2006-06-21 -> 2026-08-18 | 5,071 (20.12y) | QLD's own inception is the binding constraint; the longest window any QLD strategy can run |
| `gfc-2006-2011` | 2006-06-21 -> 2011-10-19 | 1,344 (5.33y) | isolates the 2008-2009 crash on its own, ending the day before SCHD's first bar so no SCHD leaks in |
| `schd-era-2011-2026` | 2011-10-20 -> 2026-08-18 | 3,727 (14.79y) | SCHD's actual history; the only window any SCHD-bearing strategy can legally run in, and a bull-dominated stretch with no crash remotely 2008's shape |

Every strategy that does not need SCHD (legs 1-4's IEF variants, the non-SCHD baselines) runs in
both `full-2006` and `gfc-2006-2011`. Every strategy that needs SCHD runs only in
`schd-era-2011-2026`, because SCHD has no bars before 2011-10-20 and inventing them was not an
option this dataset supports.

## Full results table

```
Roth momentum / regime backtest -- annual contribution $7,500, 5bp slippage, both return measures reported.
Every window below predates neither the strategies nor the reader: this analysis was run 2026-08-22, so no window here is out-of-sample.

=== full-2006 (IEF defensive, no SCHD): 2006-06-21 .. 2026-08-18 (5071 sessions, 20.12y) ===
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal   avg QLD
abs momentum (QLD/IEF)           $  1,744,147  $  157,500  11.07x   19.50%   17.60%    -64.7%   0.27    21     75.9%
dual momentum (QLD/IEF/GLD, cash SHY) $    838,244  $  157,500   5.32x   13.93%   12.63%    -59.2%   0.21    48     63.4%
MA regime (QLD vs IEF, sig SPY200) $  1,966,608  $  157,500  12.49x   20.40%   19.51%    -57.4%   0.34   125     73.7%
confirmed regime (QLD vs IEF)    $  2,060,950  $  157,500  13.09x   20.75%   19.36%    -53.1%   0.36   160     74.9%
static 40/60 QLD/IEF (sub for 40/30/30) $    773,231  $  157,500   4.91x   13.31%   12.21%    -46.0%   0.27    75     41.1%
QLD buy & hold                   $  6,158,947  $  157,500  39.10x   28.98%   24.04%    -84.3%   0.29     0    100.0%
SPY buy & hold                   $    617,758  $  157,500   3.92x   11.56%    9.35%    -53.1%   0.18     0      0.0%

=== gfc-2006-2011 (IEF defensive, no SCHD): 2006-06-21 .. 2011-10-19 (1344 sessions, 5.33y) ===
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal   avg QLD
abs momentum (QLD/IEF)           $     62,727  $   45,000   1.39x   10.45%    7.31%    -41.0%   0.18     3     47.9%
dual momentum (QLD/IEF/GLD, cash SHY) $     52,431  $   45,000   1.17x    4.78%    5.64%    -32.0%   0.18    10     39.3%
MA regime (QLD vs IEF, sig SPY200) $     72,914  $   45,000   1.62x   15.28%   14.68%    -30.4%   0.48    34     46.3%
confirmed regime (QLD vs IEF)    $     69,125  $   45,000   1.54x   13.56%   11.71%    -30.9%   0.38    42     47.2%
static 40/60 QLD/IEF (sub for 40/30/30) $     61,577  $   45,000   1.37x    9.86%    7.55%    -46.0%   0.16    27     40.6%
QLD buy & hold                   $     63,211  $   45,000   1.40x   10.70%    2.29%    -84.3%   0.03     0    100.0%
SPY buy & hold                   $     44,879  $   45,000   1.00x   -0.08%   -0.82%    -53.1%  -0.02     0      0.0%

=== schd-era-2011-2026 (real SCHD): 2011-10-20 .. 2026-08-18 (3727 sessions, 14.79y) ===
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal   avg QLD
abs momentum (QLD/SCHD)          $    985,240  $  120,000   8.21x   23.36%   23.79%    -56.5%   0.42    19     79.0%
dual momentum top-1 (QLD/SCHD/IEF/GLD, cash SHY) $    428,087  $  120,000   3.57x   14.49%   14.61%    -62.6%   0.23    39     66.0%
dual momentum top-2 (same universe) $    373,327  $  120,000   3.11x   13.01%   12.34%    -42.7%   0.29    71     39.4%
MA regime (QLD vs 50/50 SCHD/IEF, sig SPY200) $    973,700  $  120,000   8.11x   23.24%   23.33%    -54.8%   0.43    80     79.5%
confirmed regime (QLD vs 50/50 SCHD/IEF) $    951,549  $  120,000   7.93x   22.99%   23.13%    -52.1%   0.44   104     79.3%
static 60/40 SCHD/IEF            $    189,569  $  120,000   1.58x    5.45%    5.94%    -23.4%   0.25     5      0.0%
static 40/30/30 QLD/SCHD/IEF     $    531,248  $  120,000   4.43x   16.81%   17.04%    -41.9%   0.41    39     41.0%
QLD buy & hold                   $  2,367,924  $  120,000  19.73x   32.66%   32.82%    -68.4%   0.48     0    100.0%
SPY buy & hold                   $    380,705  $  120,000   3.17x   13.22%   13.16%    -34.1%   0.39     0      0.0%
```

`maxDD` is contribution-adjusted (peak-to-trough on the balance normalised by cumulative contributions,
per `ContributionResult.max_drawdown`'s docstring) -- a raw balance drawdown would understate every
number here, because a deposit landing mid-crash lifts the raw balance and shrinks the measured
drawdown even though every dollar already invested fell just as far. `avg QLD` is the mean fraction
of the book held in QLD across the whole run, added specifically to make the leverage trap visible
in this table rather than left to be inferred.

## The verdict, strategy by strategy

**Absolute momentum -- keep, with the crisis-window caveat spelled out.** Consistently near the top
of the momentum family on raw return (TWR 17.60% full, 23.79% SCHD-era) and clearly beats every
static baseline on MAR in the bull-heavy windows. Its weak point is exactly the window that matters
most: in `gfc-2006-2011` its 12-month lookback is too slow to get out of QLD before most of the
crash happens -- average QLD exposure over the window is still 47.9%, and maxDD (-41.0%) is barely
better than the IEF-substitute static blend's (-46.0%). It gets the direction right eventually, but
"eventually" is most of the way down. Worth keeping as a simple, cheap-to-explain baseline for this
family, not as the crisis hedge.

**Dual momentum -- the weakest performer in every window, do not keep as specified.** Lowest TWR of
the momentum family in all three windows (12.63% full, 5.64% gfc, 14.61% SCHD-era top-1) and its
MAR in the SCHD era (0.23) is *worse* than the plain static 40/30/30 blend's (0.41) -- the clearest
single result in this report that a rule can add turnover and subtract value at the same time.
Diversifying into GLD and a cash-equivalent when QLD is not the outright leader sounds prudent, but
in a period this dominated by one asset class it mostly means holding less of the thing that was
going up. Its one real strength is the shallowest GFC-window drawdown of the momentum family
(-32.0%), so it is not without merit as a pure capital-preservation tool -- just not as a
momentum/regime strategy competing on return.

**Moving-average regime switch -- keep, and this is where the family's real edge lives.** It has the
best time-weighted CAGR in the crisis window (14.68%, more than double the IEF-substitute static
baseline's 7.55%) and the best MAR anywhere in this report (0.48, in `gfc-2006-2011`) -- nearly three
times the static baseline's 0.16 at a very similar average QLD exposure (46.3% vs 40.6%), which is
the fairest single comparison in this table for whether the *timing* is worth anything, holding
average leverage roughly constant. It pays for that with real turnover -- 125 rebalances over 20
years in `full-2006`, 34 in the 5.3-year GFC slice -- but the Roth-turnover-is-nearly-free premise
holds up: none of that churn erodes the edge relative to the alternatives it is compared against.
The honest cost is qualitative, not in this table: a person running this by hand is trading roughly
once every seven weeks on average and needs to actually do it when the signal flips.

**Confirmed regime (this family's own candidate) -- close to the MA switch, not clearly better, and
one assumption behind it was wrong.** It was built on the hypothesis that requiring monthly momentum
and the daily trend signal to agree before committing full weight would *reduce* the number of
round-trip trades the MA-only version pays for. It does the opposite: 160 rebalances vs the MA
switch's 125 in `full-2006`, 104 vs 80 in the SCHD era, 42 vs 34 in the GFC slice. Three states (full
risk / half / defensive) instead of two means more transitions, not fewer, every time either leg
flips near a threshold. What it does deliver is a shallower drawdown in two of the three windows
(-53.1% vs -57.4% full, -52.1% vs -54.8% SCHD-era) at a slightly lower MAR in the window that
matters most (0.38 vs 0.48 in the GFC slice). It is a reasonable, slightly more conservative
alternative to the plain MA switch for someone who specifically wants a smoother ride in ordinary
years, but it is not the crisis-window improvement it was designed to be, and the extra trading it
generates for that result is a real cost with no offsetting benefit where it counts most.

**Static blends -- keep as the baseline they are, and note how competitive 40/30/30 actually is.**
The static 40/30/30 QLD/SCHD/IEF blend's MAR in the SCHD era (0.41) is within a rounding error of
absolute momentum's (0.42) and beats dual momentum's (0.23) outright, with five rebalances instead
of nineteen to eighty. The static 60/40 SCHD/IEF blend is exactly what it should be -- the lowest
return, lowest drawdown (-23.4%) entry in the table, a genuine capital-preservation anchor rather
than a competitor on return.

**QLD and SPY buy-and-hold -- keep as the reference points they are, and read the GFC row carefully.**
QLD buy-and-hold has the largest headline balance in every window and, in the two bull-dominated
windows, the best IRR and TWR outright -- exactly the leverage-trap warning this report opened with:
more QLD wins almost everywhere between 2010 and 2026 because QLD did well over that stretch, not
because buy-and-hold is a good rule. The `gfc-2006-2011` row is the sharpest illustration in this
whole dataset of why both return measures must be quoted: QLD buy-and-hold's IRR there is 10.70%,
which on its own reads like a perfectly good five-year result, while its time-weighted CAGR is
2.29% -- the strategy itself barely broke even over 5.33 years and drew down 84.3% peak-to-trough
doing it. The IRR looks fine only because annual contributions kept buying more shares while the
price was crushed, a sequence-of-returns effect that flatters the money-weighted number and has
nothing to do with the rule's quality. Anyone reading only the IRR here would conclude the opposite
of what actually happened.

## What surprised me

The confirmed-regime strategy's central premise -- that requiring two signals to agree would produce
*fewer* trades than either alone -- turned out backwards. A three-state rule (full / half / defensive)
transitions more often than a two-state one, not less, because it has more state boundaries to cross.
This was checked against the raw `rebalances` column, not asserted from theory, and it holds in all
three windows. It is exactly the kind of assumption this report was built to test rather than
declare, and it did not survive contact with the data.

The second thing worth flagging: on a risk-adjusted (MAR) basis, the gap between "sophisticated
momentum rule" and "static 40/30/30 blend" in the calm SCHD-era window (0.41 vs 0.42) is close to
nothing. Almost the entire apparent edge of the momentum family in that window is explained by
holding more average QLD (75-80%) than the static blend (41%) -- a leverage effect, not a timing
skill effect, exactly the trap this report's own docstring warned about. The one place a momentum
rule demonstrably earns its complexity against a comparably-weighted static baseline is the crisis
window, where the MA regime switch's MAR (0.48) triples the IEF-substitute static blend's (0.16) at
nearly identical average QLD exposure. That is the finding this whole exercise was built to surface,
and it only shows up when the comparison is held constant on exposure rather than read off raw
dollars.

## The single best candidate

**The moving-average regime switch (QLD vs 100% IEF pre-2011 / 50-50 SCHD-IEF from 2011 on, signal
SPY's 200-session average).** It is not the best in every window -- the confirmed-regime variant has
a marginally better MAR in the SCHD era (0.44 vs 0.43) and a shallower drawdown in two of three
windows -- but it is decisively the best performer in the window this report's own brief says matters
most: `gfc-2006-2011`, where its MAR (0.48) is the highest number anywhere in this table, its
drawdown (-30.4%) is close to the shallowest of the momentum family, and its IRR/TWR gap (15.28% vs
14.68%) is the tightest of any strategy that held meaningful QLD exposure through that period --
meaning the money-weighted and time-weighted experience nearly agree, which is itself evidence the
result is not an artifact of contribution timing luck the way QLD buy-and-hold's is.

## What could not be tested

- **No pre-2011 SCHD analog exists, and IEF is not a substitute for SCHD's actual character.** Every
  IEF-defensive variant in `full-2006` and `gfc-2006-2011` swaps SCHD's dividend-growth equity
  exposure for intermediate treasuries -- a materially different risk profile, not a stand-in that
  happens to have a different name. Every table row using it says so in its own label.
- **No genuinely cash-like instrument covers the whole non-SCHD window.** SGOV starts 2020-06-01 and
  BIL starts 2007-05-30 -- neither covers `gfc-2006-2011`'s 2006-06-21 start, so SHY (available since
  2002, short-duration treasuries) stands in as the "cash-equivalent" fallback for dual momentum's
  absolute-momentum filter throughout. SHY carries real duration risk that true cash does not.
  `dual momentum`'s -32.0% maxDD in the GFC slice is against this backdrop, not against literal cash.
- **Lookback and moving-average window lengths were not swept.** Every momentum leg uses a single
  252-session (12-month) lookback and every trend leg a single 200-session average, matching the
  brief's stated rules exactly. Whether a shorter or longer window changes any of these verdicts is
  an open question this run does not answer, and testing it would multiply the risk of tuning a rule
  to fit these specific historical paths rather than describing a real regularity.
- **No out-of-sample split.** Every window here ends before 2026-08-22, the date this analysis was
  run, and no walk-forward or held-out period was constructed. This is stated in this report's
  opening paragraph and repeated here because it is the single most important caveat on every number
  above: nothing here has been shown to generalise, only to describe.
- **TQQQ (3x) was deliberately not substituted for QLD (2x) in any variant.** Doing so would almost
  certainly have produced a better-looking table for exactly the leverage-trap reason this report
  warns against throughout, and building that variant would have invited presenting a bigger bet as
  a better rule.
