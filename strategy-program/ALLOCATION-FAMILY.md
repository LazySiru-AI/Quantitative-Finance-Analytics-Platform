# A whole-market-core allocation family: four variants, backtested and argued honestly

**Not investment advice.** Simulated results on stored price history. I am not a licensed financial
adviser and none of this is a recommendation about real capital.

Backtester: `strategy-program/tools/allocation_family.py`. Reproduce with:

```
cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/allocation_family.py
```

**Everything in this document is in-sample.** No price bar used anywhere here postdates 2026-08-21,
the bar store's own latest stored session at the time this ran. Nothing here is a forecast; every
number describes what already happened, once.

## Why this family

Rounds 10, 11 and 12 all name the same binding constraint: eight cards clear the backtest floor and
six of the eight are variants of two base cards -- the QLD/SCHD/IEF drawdown ladder
(`strategy-program/DRAWDOWN-LADDER.md`) and the QLD/SCHD/SGOV buy-low/trim-high allocator
(`backend/app/paper/library/allocation/qld-schd-sgov.json`). Both trade a 2x-leveraged sleeve against
a defensive one; every variant of either is a parameter tweak on the same underlying bet. The desk
owner asked for a different question: **pick an ETF that covers the whole market as a core, distribute
between assets around it, and take account of volatility** -- no leverage anywhere in that sentence.

**No sleeve in this family is leveraged.** QLD, TQQQ and every other 2x/3x fund in the bar store are
deliberately absent from all four variants below. This is the single most direct way to avoid the
"leverage trap" this programme has already documented once (`ROTH-VOLTARGET.md`'s own section by that
name): a strategy that only outperforms because it holds more of a leveraged sleeve is not
demonstrating anything about allocation or volatility awareness, it is demonstrating that leverage did
well in the period tested. Every headline number below is smaller than the QLD-based families'
own -- that is the honest cost of the choice, not something to explain away.

**On the whole-market core.** No VTI bars are stored. SPY (S&P 500) stands in as "the whole-market
core" throughout, exactly the way `ROTH-VOLTARGET.md` used SPY as a proxy for SCHD before SCHD existed
-- a real, stated substitution, not a free one: SPY is a large-cap index, not a total-market fund, and
a genuinely whole-market card would need VTI or an equivalent once that history exists.

## The four variants, precisely enough to reimplement

All four are `WeightFn` factories in `strategy-program/tools/allocation_family.py`. `realized_vol` is
the annualised standard deviation of daily simple returns over a trailing `lookback` window;
`atr_pct` is a simple (equal-weight, not Wilder-smoothed) rolling mean of true range over `lookback`
sessions, as a fraction of that session's own close. Both read prices only up to and including the
current session, never past it.

1. **Static Core-Satellite** (`make_static_blend`, the control). Fixed weights, band-rebalanced only,
   no volatility awareness at all: **SPY 40% / SCHD 20% / AGG 20% / GLD 10% / BIL 10%** in the PRIMARY
   window (native SCHD); with SCHD's own 20 points folded into SPY (**SPY 60% / AGG 20% / GLD 10% /
   BIL 10%**) in the CRISIS window, where SCHD does not exist yet and SPY substitutes for it, marked
   `*` throughout.
2. **ATR-Tilt Core-Satellite** (`make_atr_tilt`, discrete and stateless). Identical base weights to
   variant 1. While SPY's own rolling-mean ATR(14), as a fraction of SPY's own close, is **above
   1.8%** (roughly SPY's own 80th historical percentile on this measure -- median ~1.17%, 75th
   ~1.67%), shift **5 points of the whole book from SPY into BIL**, and **5 points from SCHD into
   GLD** (in the CRISIS window, both 5-point shifts come out of SPY, since SCHD is folded into it).
   **Stateless by construction**: target weights are rebuilt from the declared base every single
   session, so the tilt reverts to the base allocation automatically the session ATR falls back at or
   below 1.8% -- there is no separate, lower exit threshold, because there is nothing to remember.
3. **Continuous Vol-Target Core** (`make_vol_target_core`, not AllocationCard-expressible -- see
   below). SPY's weight is `min(1.0, target_vol / realized_vol(SPY, lookback))`; the residual is split
   a **fixed 50/50 between IEF and GLD**. Tested at `target_vol` in **{12%, 16%, 20%}** and `lookback`
   in **{20, 60}** sessions -- calibrated from SPY's own realised-volatility distribution (20-session
   lookback: median ~13.1%, 75th percentile ~18.7%, 90th ~25.7%), the same "read the target off the
   instrument's own history, don't pick a round number" discipline `ROTH-VOLTARGET.md` used for QLD.
4. **Continuous Inverse-Volatility Risk Parity** (`make_inverse_vol`, not AllocationCard-expressible).
   `weight_i = (1/vol_i) / sum(1/vol_j)` across **SPY, IEF, GLD**, recomputed every session, among
   whichever of the three already has `lookback` sessions of history. No sleeve is privileged as "the
   core" -- every sleeve's share is set purely by its own realised risk relative to the other two.
   Tested at `lookback` in **{20, 60}**.

Every variant is band-rebalanced (5% drift band, matching `AllocationCard.band_pct`'s own purpose) and
costed at **5bp slippage, charged on every dollar traded, one way** -- the same convention and rate
`drawdown_ladder.py` and `roth_voltarget.py` use, for the identical reason their own docstrings give:
an ETF's stored close is already net of its own expense ratio, so the rebalance trades are the one real
cost not already in the price.

## Windows, and the earliest common date each variant actually got

| Window | Symbols | Earliest common date | Backtest span actually run |
|---|---|---|---|
| **PRIMARY** (variants 1-2, native SCHD) | SPY, SCHD, AGG, GLD, BIL | **2011-10-20** (bound by SCHD) | 2011-10-20 .. 2026-08-11, 3,722 sessions, 14.77y |
| **CRISIS** (variants 1-2, SPY proxy for SCHD*) | SPY, AGG, GLD, BIL | **2007-05-30** (bound by BIL) | 2007-05-30 .. 2011-10-19, 1,109 sessions, 4.40y |
| **FULL** (variants 3-4, no SCHD) | SPY, IEF, GLD | **2004-11-18** (bound by GLD) | 2004-11-18 .. 2026-08-18, 5,470 sessions, 21.71y |

None of these windows is the "close to worthless, five years bound by SGOV" case the brief warns
about -- the shortest, CRISIS, is 4.40 years and exists specifically to reach the 2008 crash; PRIMARY
is 14.77 years; FULL is 21.71 years and reaches 2008 natively (dropping SCHD, rather than substituting
for it, is what buys that extra reach). CRISIS and PRIMARY are adjacent, non-overlapping slices of the
same historical path for variants 1-2, and FULL is not their union -- it is a structurally different
symbol set (no SCHD anywhere), so it is a genuinely separate measurement, not a third view of the same
two.

## Results

### PRIMARY 2011-10-20 .. 2026-08-11 (14.77y, no leverage)

```
                                      final    total    CAGR    maxDD     vol    MAR  rebal
SPY buy & hold                   $  63,332    533.6%   13.32%   -34.1%    16.8%   0.39      1
QQQ buy & hold                   $ 126,952   1170.2%   18.78%   -35.6%    20.6%   0.53      1
1. static core-satellite         $  32,141    221.6%    8.23%   -21.5%     9.9%   0.38      7
2. ATR-tilt core-satellite       $  30,694    207.1%    7.89%   -19.9%     9.3%   0.40     44
```

### CRISIS 2007-05-30 .. 2011-10-19 (4.40y, SPY proxy for SCHD*)

```
                                      final    total    CAGR    maxDD     vol    MAR  rebal
SPY buy & hold                   $   7,887    -21.1%   -5.24%   -56.5%    27.6%  -0.09      1
QQQ buy & hold                   $  12,046     20.5%    4.33%   -53.6%    27.5%   0.08      1
1. static core-satellite         $  10,239      2.4%    0.55%   -36.3%    16.5%   0.02      8
2. ATR-tilt core-satellite       $  10,149      1.5%    0.35%   -32.6%    14.6%   0.01     44
```

### FULL 2004-11-18 .. 2026-08-18 (21.71y, SPY/IEF/GLD, no SCHD, no leverage)

```
                                      final    total    CAGR    maxDD     vol    MAR  rebal
SPY buy & hold                   $  64,628    546.6%    8.98%   -56.5%    18.9%   0.16      1
QQQ buy & hold                   $ 182,614   1727.1%   14.32%   -53.6%    21.6%   0.27      1
static 60/20/20 SPY/IEF/GLD      $  56,709    467.4%    8.33%   -33.7%    12.0%   0.25     22
3. voltarget 12% core (lb20)     $  66,700    567.3%    9.14%   -29.2%    12.1%   0.31    581
3. voltarget 12% core (lb60)     $  62,789    528.2%    8.83%   -26.2%    12.4%   0.34    258
3. voltarget 16% core (lb20)     $  70,229    602.6%    9.40%   -35.6%    13.7%   0.26    351
3. voltarget 16% core (lb60)     $  62,958    529.9%    8.85%   -34.8%    14.2%   0.25    150
3. voltarget 20% core (lb20)     $  74,664    647.0%    9.71%   -39.3%    14.9%   0.25    205
3. voltarget 20% core (lb60)     $  62,459    524.9%    8.81%   -39.4%    15.4%   0.22     96
4. inverse-vol parity (lb20)     $  29,041    190.6%    5.04%   -17.6%     6.5%   0.29    546
4. inverse-vol parity (lb60)     $  27,889    179.0%    4.84%   -18.2%     6.6%   0.27    132
```

## Severe drawdown periods (return / max drawdown *within the slice only*)

Peak reset at each slice's own first value, so this measures performance during the period rather than
how far underwater the run already was walking in.

### 2008 GFC (2007-10-09 .. 2009-03-09)

```
                                      return   maxDD (within slice)
SPY buy & hold                        -56.5%   -56.5%
QQQ buy & hold                        -51.8%   -53.6%
1. static core-satellite (CRISIS)     -36.1%   -36.3%
2. ATR-tilt core-satellite (CRISIS)   -32.4%   -32.6%
static 60/20/20 SPY/IEF/GLD (FULL)    -33.0%   -33.7%
3. voltarget 12% (lb20)               -26.4%   -29.2%
3. voltarget 12% (lb60)               -19.5%   -26.2%
3. voltarget 16% (lb20)               -35.5%   -35.6%
3. voltarget 16% (lb60)               -31.8%   -34.8%
3. voltarget 20% (lb20)               -39.3%   -39.3%
3. voltarget 20% (lb60)               -38.5%   -39.4%
4. inverse-vol (lb20)                  -2.2%   -13.6%
4. inverse-vol (lb60)                  -1.2%   -13.9%
```

### 2020 COVID crash (2020-02-19 .. 2020-03-23)

```
                                      return   maxDD (within slice)
SPY buy & hold                        -34.1%   -34.1%
QQQ buy & hold                        -28.1%   -28.6%
1. static core-satellite (PRIMARY)    -21.5%   -21.5%
2. ATR-tilt core-satellite (PRIMARY)  -19.8%   -19.9%
static 60/20/20 SPY/IEF/GLD (FULL)    -21.5%   -21.5%
3. voltarget 12% (lb20)               -13.8%   -16.2%
3. voltarget 12% (lb60)               -19.7%   -20.9%
3. voltarget 16% (lb20)               -17.7%   -19.4%
3. voltarget 16% (lb60)               -23.4%   -24.0%
3. voltarget 20% (lb20)               -19.9%   -21.1%
3. voltarget 20% (lb60)               -25.8%   -26.3%
4. inverse-vol (lb20)                  -3.1%    -8.2%
4. inverse-vol (lb60)                  -4.7%    -8.5%
```

### 2022 bear market (2022-01-03 .. 2022-10-13)

```
                                      return   maxDD (within slice)
SPY buy & hold                        -23.4%   -25.4%
QQQ buy & hold                        -33.1%   -34.6%
1. static core-satellite (PRIMARY)    -16.5%   -18.0%
2. ATR-tilt core-satellite (PRIMARY)  -15.6%   -16.8%
static 60/20/20 SPY/IEF/GLD (FULL)    -19.4%   -20.6%
3. voltarget 12% (lb20)               -20.5%   -21.3%
3. voltarget 12% (lb60)               -21.1%   -21.9%
3. voltarget 16% (lb20)               -22.6%   -23.9%
3. voltarget 20% (lb20)               -23.1%   -24.8%
4. inverse-vol (lb20)                 -15.4%   -17.1%
4. inverse-vol (lb60)                 -16.1%   -17.1%
```

## Cost of turnover (5bp slippage, as assumed throughout)

```
                                      turnover    cost paid   (bp of final balance)
PRIMARY
  1. static core-satellite            2.58x        $12.88          4.0bp
  2. ATR-tilt core-satellite         15.37x        $76.80         25.0bp
CRISIS
  1. static core-satellite            1.63x         $8.13          7.9bp
  2. ATR-tilt core-satellite          8.66x        $43.28         42.6bp
FULL
  static 60/20/20 SPY/IEF/GLD         5.84x        $29.19          5.1bp
  3. voltarget 12% (lb20)           263.13x     $1,314.98        197.2bp
  3. voltarget 12% (lb60)            95.28x       $476.14         75.8bp
  3. voltarget 20% (lb60)            33.58x       $167.80         26.9bp
  4. inverse-vol (lb20)             125.04x       $624.90        215.2bp
  4. inverse-vol (lb60)              26.76x       $133.73         48.0bp
```

## What the negatives actually are

**Variant 2's extra turnover barely buys anything, and once actively loses.** In PRIMARY, ATR-tilt
trades 15.4x its own starting capital against variant 1's 2.6x -- nearly six times the turnover -- for
a MAR improvement of 0.38 to 0.40 and a drawdown improvement of 21.5% to 19.9%, at a cost of 25.0bp of
final balance against variant 1's 4.0bp. In CRISIS, the tilt's MAR is **worse** than the static
baseline's (0.01 vs 0.02) despite a shallower max drawdown (-32.6% vs -36.3%) -- the extra trades cost
more, in CAGR terms, than the drawdown reduction was worth over that particular 4.4-year window. This
is not a strategy that clearly earns its complexity; it is closer to a coin flip that trades a lot more
than the thing it is a coin flip against.

**Vol-targeting at higher targets is the leverage trap, demonstrated directly, on an unlevered
sleeve.** Raising the target from 12% to 20% (lb20) monotonically improves every FULL-window headline
number -- CAGR 9.14% to 9.71%, MAR 0.31 to 0.25 (actually *falls*, see below) -- because a higher vol
target simply means holding more SPY on average. Read the FULL-window CAGR column alone and 20% looks
like "the better setting." **In the 2008 slice, the same move from 12% to 20% makes every metric
worse**: the 12%-target (lb20) loses 26.4% and draws down 29.2% in the crash; the 20%-target (lb20)
loses 39.3% and draws down 39.3% -- **worse than the plain, non-vol-aware static 60/20/20 blend
(-33.0%/-33.7%)**. A vol-target strategy that performs worse than a strategy with no volatility
awareness at all, in the exact regime volatility awareness is supposed to help with, is the sharpest
negative result in this whole family, and it happens because at a 20% target the strategy is, in
substance, "hold more SPY, all the time" -- the same trap a literal leverage multiplier sets, achieved
here with a volatility formula instead of a leverage multiplier, on an entirely unlevered instrument.
**12% is the only target of the three where vol-targeting actually beats the static baseline in the
crisis** (-29.2% max drawdown vs static's -33.7%), and even there the margin is real but not dramatic.

**The lookback sensitivity does not point one direction here, unlike `ROTH-VOLTARGET.md`'s own
finding.** That document found the faster (20-session) lookback beating the slower (60-session) one on
every metric, every strategy, every window, for QLD. Here the ranking flips by period: in the 2008
slice, the 12%-target's 60-session lookback (-19.5% return, -26.2% drawdown) clearly **beats** its own
20-session twin (-26.4%, -29.2%) -- the slower estimate reacted better to a slow-building crisis. In
the 2020 slice, the opposite holds: 20-session (-13.8%, -16.2%) clearly beats 60-session (-19.7%,
-20.9%) -- the faster estimate reacted better to a crash that happened in five weeks. **Neither
lookback is "the right one" independent of the shape of the crisis**, which is a genuinely different,
and less comfortable, finding than the prior module's own -- there, one lookback was simply better;
here, which one is better depends on a property of the future crash (slow-building vs sudden) that
cannot be known in advance.

**Inverse-volatility risk parity gives up most of the return to buy the drawdown reduction, the same
finding `ROTH-VOLTARGET.md` reported for its own three-asset inverse-vol variant.** FULL-window CAGR
is 4.84-5.04% against the static blend's 8.33% and SPY buy-and-hold's 8.98% -- roughly half the
market's own return, for a max drawdown of -17.6% to -18.2% against static's -33.7%. The 2008 numbers
are the most extreme in the whole family in either direction: -1.2% to -2.2% return, essentially flat
through the crash that took the static blend down 33%. Whether that trade is a good one depends
entirely on whether the return given up in every other year is worth the crash protection -- on a MAR
basis (0.27-0.29) it is a modest, not dramatic, improvement over static's 0.25, because it also gives
up return in the calm years the static blend was compounding through. And it is expensive to run: 125x
turnover of starting capital at the 20-session lookback, 215bp of final balance in cumulative slippage.

**No variant beats SPY or QQQ buy-and-hold on raw CAGR or MAR over the long windows.** Every table
above shows this plainly and it should not be read past: QQQ buy-and-hold's MAR is 0.53 in PRIMARY and
0.27 in FULL, both the best MAR in their respective tables. What every variant buys instead is a
shallower crash -- variant 1's PRIMARY MAR (0.38) is close to SPY's (0.39) at roughly a third of SPY's
volatility and drawdown, and the FULL-window vol-target-12%(lb60) reaches a genuinely better MAR (0.34)
than either buy-and-hold. But "beats buy-and-hold in a diversified, unlevered way" is a materially
smaller claim than the drawdown-ladder family's own headline numbers, and stating that plainly is the
point of putting these two families side by side.

## What AllocationCard could express, and what it could not

`app.tournament.allocation.AllocationCard` -- `Sleeve`/`TiltRule`, read in full before designing any of
this -- **can express variants 1 and 2 exactly**, and ~~**cannot express variants 3 or 4 at all.**~~

> **Amended 2026-08-30: variant 3 is now expressible; variant 4 is not, and this section named the
> wrong blocker for it.** The text below is left exactly as written -- it correctly predicted the
> engine change that landed -- and the amendment is at the end of the section.

**Variant 1 (Static Core-Satellite)** is the simplest possible `AllocationCard`: five sleeves at
declared weights summing to 1, `band_pct`, no rules. Nothing about it stresses the model.

**Variant 2 (ATR-Tilt Core-Satellite)** is directly, faithfully expressible as two `TiltRule`s --
`backend/app/paper/library/allocation/spy-schd-agg-gld-bil-atr-tilt.json` is the literal card, and it
validates against `AllocationCard.model_validate_json` (confirmed by loading it through that exact
model, not assumed). This worked *because* variant 2 was designed stateless from the start, to match
`_target_weights`'s own per-session recomputation (base weights plus whichever rules fire *this*
session, never anything carried over from the last) -- see this module's own docstring and the card's
own thesis for why that is not an implementation shortcut but a real property of what `TiltRule` can
express: a rule fires or does not fire on a boolean condition read off one symbol's own bars, and
there is no field anywhere on `TiltRule` or `AllocationCard` that remembers whether it fired last
session. `LadderCard.armed_depth` is the one place this repository already built that kind of memory,
and it exists in a third, separate card type for exactly this reason.

**Variants 3 and 4 cannot be expressed, and the gap is precise, not vague.** `TiltRule.shift_pct` is a
`Decimal` **declared once on the card** -- a fixed number of percentage points, the same amount whether
the triggering condition is barely true or wildly true. Variant 3's core weight is
`min(1.0, target_vol / realized_vol)` -- a continuous function of a real number that can be anywhere
from 0 to 1.0 depending on how far realised volatility sits from the target, and it changes by a
different amount on two different sessions where the underlying vol differs. Variant 4's weights are
`(1/vol_i) / sum(1/vol_j)` across every sleeve simultaneously -- not a shift *between* two named
sleeves at all, but a full re-derivation of every sleeve's weight from every other sleeve's current
risk, every session. Neither has any representation in a card whose only conditional mechanism is "if
this boolean is true, move this many percentage points from sleeve A to sleeve B." Building either
would need one of:

- **A new field type on `TiltRule`** -- a formula or a reference to a computed quantity (e.g.
  `weight = f(indicator_value)`) instead of a fixed `shift_pct` -- which is a materially larger change
  to a model this task was told to treat as read-only, not a small addition.
- **A fourth card type**, sized the way `LadderCard` was built as a third one when `AllocationCard`
  turned out not to fit a state-machine-driven strategy: a `VolTargetCard` or `RiskParityCard` with its
  own `run_*` engine, following the same "why a new module, not new fields" argument
  `allocation.py`'s and `ladder.py`'s own docstrings already make twice.

Neither is done here -- the task brief scoped this change to *designing and backtesting* the family and
*reporting* whether the target card type fits, not to extending it. This is reported as a finding, not
worked around.

### Amendment, 2026-08-30 -- the first bullet was built, and it resolved variant 3 only

`TiltRule.shift_expr` landed in **`8c033f1`**: a rule-DSL numeric expression, evaluated per session on
`on_symbol`'s own bars, that sets a tilt's *magnitude* in place of `shift_pct`'s fixed `Decimal`. That
is the first bullet above -- "a formula or a reference to a computed quantity ... instead of a fixed
`shift_pct`" -- built as described. It is parsed and guarded as a **ranking** key rather than a
condition, because a non-causal magnitude is lookahead in the *sizing* step, which is harder to catch
than lookahead in an entry: the condition beside it stays clean while the size is already wrong.

**Variant 3 is now expressible.** A continuous core weight is a `shift_expr` sized off realised
volatility, and the residual's fixed 50/50 split across the two satellites is two `TiltRule`s sharing
that one expression rather than a single shift.

**Variant 4 is not -- and the blocker is not the one this section named.** The text above attributes
both exclusions to `shift_pct` being fixed. For variant 4 that was only ever half the reason, and the
half that has now been removed. Parity weights each sleeve against every *other* sleeve's volatility,
and the engine has **no cross-symbol operator at all**: a rule reads one symbol's own bars and nothing
else. Variant 4 is therefore blocked by the same limitation that forecloses relative-strength, pairs
and dispersion strategies as a class (`docs/research/programme/00-EVERYTHING-TESTED.md` section 3a),
which no amount of `shift_expr` reaches. **The family's best risk-adjusted result stays measurable
only in this module's own harness**, for a reason this section did not identify.

**Neither variant has been run as a card, and expressible is not measured.** `shift_expr` has one
demonstration -- SPY/IEF over the GFC slice, a constant 15-point de-risk against a vol-proportional
one -- with a hand-picked threshold and multiplier, one window, and no null.
`00-EVERYTHING-TESTED.md`'s recommendation 2 records it as a wiring check and explicitly not a
finding; on this programme's own record that is the shape of number that does not survive correction.

## What this family cannot be compared to

Every `StrategyCard` in the tournament is scored on **lump-sum `adjusted_excess`** (total return minus
exposure-adjusted benchmark return) over the round's own set of regime windows -- six months to ten
years, dozens of windows per round -- ranked by median and worst `adjusted_excess` and hit rate
(`strategy-program/tools/score.py`). The backtests above are none of that: one long lump-sum run per
window, not dozens of short regime windows; CAGR/MAR/max-drawdown, not `adjusted_excess`; and, as
`app.tournament.allocation`'s own module docstring establishes at length, `AllocationResult` is **not**
`app.tournament.models.AgentResult` -- `isinstance(result, AgentResult)` is `False` for it, the same as
it is for `LadderResult`. `score.py`'s own `_load_results` calls
`AgentResult.model_validate_json(...)`, which validates the JSON's `"card"` object against
`StrategyCard`'s schema specifically; an `AllocationResult`'s `"card"` (`sleeves`/`band_pct`/`rules`,
none of `universe`/`entry`/`exit`) would fail that validation immediately.

For any of these four variants to be ranked in the same column as a `StrategyCard`, every one of the
following would have to be true, none of which is today:

1. **`AgentResult.card`'s type would have to widen** (e.g. to `StrategyCard | AllocationCard`) in
   `backend/app/tournament/models.py` -- explicitly out of scope for this change, per the task brief,
   and flagged here for the same reason `allocation.py`'s own docstring flags it rather than working
   around it.
2. **The card would have to be run through the round's actual regime windows**, not one long backtest
   -- `run_allocation` already takes arbitrary `start`/`end`, so this is mechanically available, but
   nothing here does it: every number above is one continuous run per symbol set, chosen to include a
   severe drawdown period as the brief requires, not the round's own six-month-to-ten-year window grid.
3. **`adjusted_excess`'s own exposure-adjustment convention would need re-deriving for a
   continuously-rebalanced book.** It is defined against `AgentResult.capital_exposure`
   (entry-notional-over-starting-equity, fixed at trade entry) -- and `AllocationResult.capital_exposure`
   is a structurally different quantity by design (invested-value-over-*current*-equity, averaged
   across sessions; see that field's own docstring for exactly why the two cannot share a denominator).
   An allocation card is *always* near-fully invested by construction (five sleeves summing to 1), so
   whatever "exposure-adjusted" would mean for it is a real design question, not a plug-in of the
   existing formula.
4. **A scoring bridge, not a scoring workaround**, would need to read `AllocationResult` and produce
   whatever `adjusted_excess`-equivalent point 3 settles on, without touching `score.py`'s existing
   `StrategyCard` path -- the same "new module for a new shape, not a branch in the old one" argument
   `allocation.py` and `ladder.py` already made twice in this repository.

None of this is done here, and none of it should be implied as already possible by the results tables
above sitting next to `StrategyCard` numbers elsewhere in this programme's documents. A CAGR/MAR number
in this document and a `median_adjusted_excess` number in a round's scorecard are not the same
measurement and are not on the same scale.

## The candidate, and the honest case against it

**Put forward: Variant 1, Static Core-Satellite.** Not variant 2 (barely earns its own turnover, and
loses on MAR in the crisis window despite the shallower drawdown), not variant 3 or 4 (cannot be built
as an `AllocationCard` at all without either a model change out of scope for this task or a fourth card
type nobody has built). Variant 1 is the one design in this family that is simultaneously: expressible
today, exactly as `backend/app/paper/library/allocation/spy-schd-agg-gld-bil-atr-tilt.json`'s own base
weights show (that card *is* variant 1 plus variant 2's rules layered on top -- strip the `rules` array
and it is variant 1 exactly); genuinely different in shape from every card already in the roster (no
leverage, five asset classes, not a QLD/SCHD variant); and its PRIMARY-window MAR (0.38) sits within two
points of SPY buy-and-hold's own (0.39) at roughly a third of the volatility and drawdown, which is a
real, statable trade rather than a strategy that only wins by holding more risk.

**What would have to be false for this to be the wrong choice:**

- **If the desk actually wants the drawdown reduction variant 2 or the vol-aware variants buy, plain
  static is the wrong pick.** Variant 1's PRIMARY drawdown (-21.5%) is close to but not as shallow as
  variant 2's (-19.9%), and neither reaches vol-target-12%(lb60)'s FULL-window MAR of 0.34 -- the best
  risk-adjusted number in this entire family, on the window that includes 2008. If risk-adjusted return
  is genuinely the criterion, not "is it expressible as a card today," vol-target 12% at a 60-session
  lookback is the stronger candidate on the numbers, and is disqualified only by the card-type gap
  documented above.
- **If SCHD's own 15-year window (PRIMARY) is judged too short a sample for a competition already
  criticised for over-narrow evidence,** the CRISIS-window numbers for variant 1 are weak on their own
  terms -- a 0.02 MAR, barely above break-even over 4.4 years including the entire GFC. The static
  blend does not lose money in that window, but it does not make a real case for itself either; its
  strongest argument is the PRIMARY window, and PRIMARY is the shorter, calmer 15 years, not the harder
  test.
- **If a future round widens `AgentResult.card` and builds the scoring bridge this document flags as
  missing** (section above), the calculus changes entirely, because the two continuous variants (3
  and 4) that cannot be submitted today would become live candidates, and variant 3 at a 12% target
  outperforms variant 1 on every metric in the FULL window's headline table and in the 2008 slice
  specifically. Variant 1 is the right choice **given today's card type**, not necessarily the right
  strategy in the abstract.

## Does the desk reproduce these numbers? Measured 2026-08-30

Every figure above comes from `allocation_family.simulate`. **That is not the code the paper desk
runs** -- the desk runs `app.tournament.allocation.run_allocation` -- and until this measurement the
two had never been compared on this card. They could not have been by accident, either: round 15
excluded `spy-schd-agg-gld-bil-atr-tilt` from its savings arm outright, because both its rules gate on
`atr(14)`, ATR needs high and low, and `contributions.simulate` passes closes only
(`data/rounds/r15-2026-08/SELECTION.md` section 4). So the number `ACCOUNT-DEPLOYMENT-PLAN.md` rests on
for the largest book was a harness number the desk had never once produced.

Reproduce with `strategy-program/tools/savings_gap.py`. Four arms, so the difference decomposes rather
than arriving as one unattributable lump:

| arm | CAGR | maxDD | vol | MAR | rebal | tilt fires | ending equity |
|---|---|---|---|---|---|---|---|
| **A** harness, simple-mean ATR *(this document)* | 7.93% | −19.9% | 9.3% | 0.40 | 44 | 505 | $309,170 |
| **B** harness, engine Wilder ATR | 7.84% | −19.8% | 9.3% | 0.40 | 36 | 474 | $305,334 |
| **C** engine, fractional shares | 7.78% | −19.6% | 9.1% | 0.40 | — | — | $303,309 |
| **D** engine, **live desk mandate** | 7.87% | −19.7% | 9.2% | 0.40 | — | — | $306,981 |

All four at $100,000, the savings book's own capital. Arm A also runs at this document's own $10,000
as a scale check and reproduces every ratio to within 1e-15, so what follows is the instrument and not
the capital. Arm A's CAGR reads 7.93% against the 7.89% in the table above because the bar store has
since extended from 2026-08-11 to 2026-08-21; SPY buy-and-hold moved 13.32% → 13.24% over the same
interval. Max drawdown and MAR did not move.

**The published figure survives the real execution path. A → D is −0.06pp of CAGR and +0.2pp of
drawdown, with MAR 0.40 in all four arms.** Arm D calls `app.paperdesk.desk._mandate(SAVINGS)` itself
rather than reconstructing it, so it is the live book's own constraints -- T+1 settlement, 5bp
slippage, whole shares, SEC/TAF fees, $500 minimum clip -- by construction.

**The decomposition is below its own resolution, and that is the part not to overread.** The
signal-definition term (A → B) and the instrument term (B → C) came out 0.1pp and 0.2pp of drawdown.
But arm D differs from arm C in *one* setting, whole-versus-fractional shares, which ought to be
nearly inert -- and it moves drawdown 0.2pp and CAGR 0.09pp, in the opposite direction. Configuration
noise is the same size as the terms being attributed. **The total gap is real; the split between
"signal" and "instrument" cannot be ranked in either direction**, and every number here sits far under
this programme's own 21.2pp noise floor.

**The ATR calibration concern is answered, and it was smaller than it looked.** `atr_pct`'s docstring
warned that a card author reproducing this rule against the engine would get Wilder smoothing rather
than this module's rolling mean, against a 1.8% threshold calibrated on the latter. The two fire on
505 and 474 of 3,730 sessions and **agree on only 75.1% of them** -- a quarter of firing sessions
genuinely differ -- yet the book's drawdown moves 0.1pp and its MAR not at all. The tilt earns its
drawdown reduction by being defensive across high-volatility stretches, not by precise entry timing,
so the result is not knife-edge on a threshold that was never re-fitted.

**Defect D8 is confirmed fixed on this card**, which had never been run through the path it broke.
All 19 (arm C) and 39 (arm D) rejections are settled-cash refusals -- T+1 residue on rebalances that
*were* funded. None is D8's signature of a band-breaching buy with nothing sold to pay for it, the
failure that silently stopped `qld-schd-sgov` rebalancing for weeks at a time. Rejections roughly
doubling from C to D is whole-share lumpiness, not a return of the defect.

**What this does not establish.** One window, in-sample, price-only, and the same missing dividends
that understate every return in this document -- AGG, SCHD and BIL all distribute. It says the
harness and the desk agree on this card in this window; it says nothing about the CRISIS or FULL
windows, nothing about the other variants (1 is untested against the engine, 3 and 4 remain
unexpressible-as-run), and nothing about whether the strategy is any good. It closes a
reproducibility gap, not an evidential one.

## What could not be tested

- **VTI, or any genuinely whole-market fund.** SPY stands in throughout, and SPY is a large-cap index,
  not a total-market one -- the substitution is real and not free, the same caveat this document states
  for the SPY-for-SCHD substitution in the CRISIS window.
- **A fifth, hybrid variant** combining variant 2's discrete tilt with variant 3's continuous core
  sizing (e.g. a card-expressible discrete approximation of vol-targeting, stepping through several
  fixed `TiltRule` thresholds instead of one continuous formula) was not built. It is the most direct
  way to close some of the AllocationCard gap without a model change, and is flagged here as unfinished
  work rather than attempted under this task's own time and scope.
- ~~**Recalibrating variant 2's ATR threshold against the engine's real, Wilder-smoothed `atr(14)`
  indicator.**~~ **Measured 2026-08-30 -- see "Does the desk reproduce these numbers?" below.** The
  concern was real and the effect is small: the two definitions disagree on a quarter of the sessions
  they fire on, and move the book's max drawdown by 0.1pp.
- **Slippage sensitivity.** Every number here uses the flat 5bp assumption. Variant 3 at a 12% target,
  20-session lookback pays 197bp of final balance in slippage over 21.71 years -- material enough that
  a materially higher real-world cost (a wider spread on GLD or IEF in a stressed week, say) could
  change which lookback or which target is actually the better choice, and this backtest does not sweep
  the assumption to find where that would happen.
- **Independence of the windows.** PRIMARY and CRISIS are adjacent, non-overlapping slices of one
  historical path for variants 1-2; FULL is a structurally different symbol set for variants 3-4, not a
  union of the other two. None of this is three independent trials of "what happens to a diversified
  book in a crisis" -- it is one realised history, read three ways.
