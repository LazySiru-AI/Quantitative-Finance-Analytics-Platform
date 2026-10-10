# c11-breakout -- Cross-Asset Breakout

## Mechanism

A confirmed swing-high breakout marks the point where a market has absorbed the supply that capped
it at the prior pivot. The resting sellers anchored to that old high have been cleared; the next
marginal buyer transacts at a new equilibrium with less overhead resistance above. The counterparty
giving up the trade is the anchoring seller who priced the old high as fair value and is now
underwater on that reference point -- they cover or step aside rather than average down into a level
that just failed to hold. Nothing about that story is specific to equities: it is a claim about
order-book supply and anchoring bias, and it should recur in any liquid, exchange-traded, trend-
capable market -- government bonds, gold, investment-grade credit, not only stock indices.

Round 1's breakout card tested this mechanism with nine US sector ETFs, later measured near **0.58
mean pairwise correlation** -- nine expressions of the same equity-beta trend, which is why its win
rate swung 0%-71% by *window* rather than by symbol within a window. This card tests the same
mechanism across four assets chosen because their return drivers actually differ, and reports the
measured correlation matrix below rather than asserting diversification.

`sma(200)` gates entries to an established uptrend, to avoid buying a breakout that is really a
dead-cat bounce inside a larger downtrend. That filter also means the strategy is structurally absent
during the worst of a fast crash -- that is arithmetic (the filter cannot fire below its own average),
not risk management, and I am declaring it rather than claiming skill for it, per BRIEF.md's finding
#3 about round 1's covid results.

## Universe, and why

**`SPY TLT GLD LQD`** -- 4 symbols, all with first-bar dates at or before 2004 (SPY 1993, TLT
2002-07-30, LQD 2002-07-30, GLD 2004-11-18), which is comfortably ahead of the earliest window
(`gfc`, starting 2007-10-09) once warmup (`sma(200)` = 200 bars, `swing` = `2*lookback` = 40 bars) plus
the guard's 40 post-warmup causality bars are accounted for -- GLD alone has roughly 750 trading days
of history before `gfc` starts. **All eight main windows are eligible on history grounds**, confirmed
by the guard command in "Definition of done" below raising nothing.

Each symbol represents a different macro driver by design:
- `SPY` -- broad US equity risk premium.
- `TLT` -- long-duration Treasury / rates, flight-to-quality demand.
- `GLD` -- gold, monetary/inflation hedge, safe-haven demand distinct from Treasuries.
- `LQD` -- investment-grade corporate credit (duration + credit spread, not a pure equity or pure
  rates bet).

I set `max_positions = 4 = len(universe)`. This is a deliberate structural choice, not an oversight:
BRIEF.md §3 documents up to a 53.9-point swing (sigma 21.2) from the arbitrary tie-break that fires
when more symbols qualify than there are slots, because fills go in `universe` array order. With slots
equal to the whole universe, every qualifying signal is always filled (subject only to cash), so that
tie-break can never bind on this card. Order in the JSON array is therefore genuinely inert here, not
merely "not tuned."

### Universe candidates tried and abandoned

I measured correlation to `SPY` for a wider candidate set before settling on the above (full code and
output in `.scratch/c11-breakout/corr_study.py` and `corr_study2.py`). Rejected for being too
equity-correlated to add real diversification:
- `EFA` (developed intl equity): **0.880** vs SPY -- higher than most single US sectors.
- `EEM` (emerging markets): **0.819** vs SPY.
- `XLE` (energy sector): **0.729** vs SPY -- "commodity-linked equity" still trades like equity.
- `DVY` (dividend equity): **0.870** vs SPY.
- `XLU` (utilities): **0.651** vs SPY -- the classic "bond proxy" reputation does not show up as low
  correlation to equity in the data.
- `DBC` (broad commodities): 0.404 vs SPY, a real reduction, but its first bar (2006-02-06) leaves
  `gfc` eligible "only at the margin" per WINDOWS.md's own tiering, so it was dropped to keep the
  card's 8-window eligibility unambiguous rather than warmup-marginal.
- `DX-Y.NYB` (dollar index): the single lowest correlation measured (-0.061 vs SPY, -0.418 vs GLD)
  but it is a spot index, not a tradable ETF an investor can actually hold long -- excluded on
  realism grounds, not on correlation grounds.
- `IEF` (7-10y Treasury): **0.911** correlated with `TLT` itself -- redundant with `TLT`, so only one
  duration instrument was kept. I chose `TLT` over `IEF` for the higher volatility (14.4% vs 6.9%
  annualised), which produces cleaner, more decisive swing pivots for a breakout rule; `IEF`'s pivots
  are noisier relative to its own range.
- `AGG` / `SHY` / `TIP`: all measured near-zero-to-negative vs SPY (`AGG` -0.007, `SHY` -0.215, `TIP`
  -0.104) but their annualised volatility is very low (5.3%, 1.6%, 6.3%) -- too little range for a
  swing-high/swing-low breakout rule to generate meaningful, non-noise pivots. `LQD` (8.5% vol) was
  kept instead as the credit-market representative for that reason.

## Measured correlation matrix (through 2026-02-13 cutoff)

Daily close-to-close returns, pairwise-complete history (each pair using its full overlapping
sample; code in `.scratch/c11-breakout/corr_study.py`):

|      | SPY    | TLT    | GLD    | LQD    |
|------|--------|--------|--------|--------|
| SPY  | 1.000  | -0.310 | 0.054  | 0.159  |
| TLT  | -0.310 | 1.000  | 0.155  | 0.572  |
| GLD  | 0.054  | 0.155  | 1.000  | 0.146  |
| LQD  | 0.159  | 0.572  | 0.146  | 1.000  |

Mean of the 6 off-diagonal pairs: **+0.129** (mean of raw values) / **0.233** (mean of absolute
values) -- against round 1's breakout card at ~0.58 mean pairwise. The weakest link is `TLT`-`LQD` at
0.572, which is real and expected (both carry interest-rate duration) but is still well below any
`SPY`-vs-sector pair round 1 held, and the other five pairs are all under 0.16 in magnitude.

I also checked the caution passed down from an earlier analyst: `IEF` vs `SPY` at -0.110 and `GLD` vs
`SPY` at 0.042. My own measurement over full history gives `TLT` vs `SPY` at -0.310 (I did not carry
`IEF` into the final universe, but measured it too: -0.302, a similar sign and larger magnitude than
the -0.110 cited) and `GLD` vs `SPY` at 0.054 (close to the cited 0.042). Same sign, same rough
magnitude for gold; the bond number differs enough from the citation that it looks like it was
measured over a different sub-window or ticker than mine -- consistent with the brief's own warning
not to trust an inherited number without re-measuring it, which is what this table is.

I also checked the volatility caution: an earlier analyst cited GLD's annualised vol at 17.0% over one
window and 24.9% over another. My own measurement (code in `.scratch/c11-breakout/sensitivity.py`):

| window | GLD ann. vol |
|---|---|
| full history (2004-2026) | 17.95% |
| 2008 GFC (2007-10-09 to 2009-03-09) | 30.93% |
| 2011-2013 taper era | 19.28% |
| covid (2020-02-19 to 2020-06-30) | 23.55% |
| last 3y to cutoff | 18.57% |
| chop-2015 | 15.19% |
| chop-2011 | 21.51% |

Both cited figures (17.0%, 24.9%) sit inside this range -- confirmed, not just plausible. Gold's vol
roughly doubles in the GFC window versus its calmest chop window, which matters directly for this
card: `stop_loss_pct` is one fixed number for every symbol, and it will bind on GLD hardest exactly in
the regime (crisis) where GLD is supposed to be earning its keep as a diversifier.

## Parameters (budget: 10)

| # | parameter | value | justification |
|---|---|---|---|
| 1 | `swing_high` lookback (entry) | 20 | Conventional "one trading month" pivot window; the original Turtle system's 20-day breakout is the textbook convention here, not a search result. |
| 2 | `sma` period (entry) | 200 | The single most widely-watched trend filter in the field; chosen for being conventional, not fitted. |
| 3 | `swing_low` lookback (exit) | 20 | Symmetric with the entry pivot -- exit on a confirmed breakdown of the same-scale structure that defined entry, not an arbitrarily different number. |
| 4 | `stop_loss_pct` | 0.10 | Conventional round-number stop. BRIEF.md reports a 10% nominal stop realising -22.81% in round 1 because stops fill against the prior close, not the intraday low -- I am not pretending this caps risk at 10%; `position_pct` (below) is sized with that gap already priced in. |
| 5 | `max_hold_days` | 120 | Roughly two calendar quarters (about half of 252 trading days) -- a backstop against a position drifting with neither a fresh high nor a confirmed breakdown, not a return-optimised number. |
| 6 | `max_positions` | 4 | Equals `len(universe)` exactly, which is the structural choice discussed above (eliminates fill-order sensitivity entirely). |
| 7 | `position_pct` | 0.25 | `0.25 * 4 = 1.00 <= 1.001`, using the full book only when every slot is filled simultaneously. This stays at the real 25% single-name cap, so the card does **not** rely on the persona cap being relaxed to 100% -- it would run identically under `--honour-persona-cap`. |

**Count: 7 of 10.** `take_profit_pct` is deliberately unset -- a trend-following breakout thesis wants
to let a winning trend run to its own reversal (the `swing_low` exit), not cap it at a fixed target,
and the model validator does not require one once `exit` is non-empty.

## Sensitivity check

I varied the two entry parameters over a 3x3 grid (`lookback` in {15, 20, 25}, `sma period` in {150,
200, 250}) and counted raw entry-signal crossings per symbol over full history (code and full table in
`.scratch/c11-breakout/sensitivity.py`; this counts signal *frequency*, not backtested P&L -- I did
not grid-search for a return-maximising cell, which BRIEF.md §2 rules out):

```
symbol lb15/sma150 lb15/sma200 lb15/sma250 lb20/sma150 lb20/sma200 lb20/sma250 lb25/sma150 lb25/sma200 lb25/sma250
SPY           169         166         161         154         149         144         147         142         136
TLT            71          65          55          76          72          61          82          77          67
GLD            93          87          82          83          77          73          80          73          70
LQD            96          89          84          82          75          72          72          65          64
```

Every symbol's signal count moves smoothly and monotonically (or near-monotonically) across the grid
-- no cliff where a one-step change collapses the count to near zero or doubles it, which is the
knife-edge failure mode BRIEF.md §2 names (`rsi(14) > 55` working and `> 52` breaking). `(20, 200)` is
an interior, unremarkable cell of that grid, not a boundary the count is sensitive to. The rule
survived this check; I did not go further and backtest each cell's return, which would be exactly the
grid search the brief prohibits.

## The trade-off, named in advance

Diversification here is bought at a real cost, not a free lunch. In a window where equity beta is
simply the right trade -- `bull-2024`, `recent` -- three of the four assets (`TLT`, `GLD`, `LQD`) are
not that trade and will either sit out or generate smaller, choppier signals of their own, diluting
the book's participation in a move that a concentrated equity-only card would have captured with more
of its capital. I expect this card's median return in strong, single-direction bull windows to trail
a concentrated equity breakout book. What I am buying with that cost is a book whose four positions
can genuinely diverge rather than move as one lever -- which should show up as a shallower worst
window and a steadier hit rate across the regime types that punished round 1's card, at the price of a
lower per-trade and per-window expectancy in the windows where concentration would have won outright.

## Named window I expect to lose in

**`chop-2011`.** Both `chop-2015` and `chop-2011` are structurally hard for any breakout-plus-trend-
filter rule -- WINDOWS.md is explicit that "a stop-based rule will be tested on how often it is
whipsawed out" in a sideways market, and `sma(200)` does not prevent chop: price can sit on either
side of its 200-day average for months in a directionless market, so the filter does not suppress
false breakouts the way it suppresses buying into an established downtrend. I expect `chop-2011` to be
worse than `chop-2015` specifically because it carries higher realised volatility at the same
near-zero drift (22.9% vs 16.6% annualised per WINDOWS.md) -- more whipsaw at the same net destination
means more stop-outs and more `swing_low` breakdown exits with nothing captured in between. I do not
expect this to be arithmetic absence the way `gfc` might be (the trend filter does not obviously keep
the book out of a range-bound market the way it keeps it out of a falling one) -- I expect it to be
the rule actively trading and actively losing to whipsaw, which is the honest way to lose this window.

## Weakest assumption

That four assets picked for differing *macro drivers* actually diverge in *when their breakout
signals fire*, not just in their raw return correlation. Correlation of daily returns is what I
measured and reported above; I did not verify that entry/exit trade timing itself is uncorrelated
across the four symbols (the DSL provides no way to test that without running the actual backtest,
which is the harness's job, not mine). It is possible that broad risk-on/risk-off regime shifts
synchronise breakout signals across all four assets even though their unconditional return
correlation is low -- e.g., a Fed-driven regime change could push `SPY`, `TLT` and `LQD` breakouts to
cluster around the same macro turning point even though their day-to-day returns rarely move
together. If that happens, the book's *realised* trade-level diversification would be worse than the
static correlation matrix above implies.

## Guard output (verbatim)

```
card OK: c11-breakout | planned RRR: None | slots: 4
guard: all symbols checked
```

No `GUARD` lines were printed for any symbol/expression combination -- both `entry` and `exit` pass
the lookahead-causality check for `SPY`, `TLT`, `GLD`, `LQD`.
