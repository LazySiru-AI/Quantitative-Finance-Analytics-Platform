# Candle timeframe effect, per strategy

Companion to [07-sweep-findings.md](07-sweep-findings.md), which measured individual
*rules*. This measures composed *strategies*: entry + exit + stop + max-hold, the unit
the paper desk actually trades.

Three runs, all kept:

| run | cells | unit | what each card was tested on |
|---|---:|---|---|
| 1 | 3,885 | symbol | a fixed 15-symbol list, regardless of the card's own universe |
| 2 | 2,231 | symbol | each card's own universe, after a 340-pair intraday backfill |
| **3** | **540** | **portfolio** | **the whole card through `run_card`** — max_positions, ranking, sizing, cash |

`data/research/timeframes/strategy_cells{,_v2}.csv` and `portfolio_cells.csv` — gitignored,
regenerable. **Run 2 is the result. Run 1 is retained because the difference between
them is itself a finding** (§5).

---

## 1. Strategies are not rules, and the difference is the whole problem

A rule is a boolean over one bar. A strategy has *state*: it enters, holds for a
duration, exits. That duration is written in bars but reasoned in calendar time, so
re-pointing a card at a finer candle silently rewrites it.

51 cards live in `backend/app/paper/library/{base,variants,candidates,retired}`. Median
lookback 99 bars, median `max_hold_days` 102 bars. What those same numbers *mean*:

| interval | median lookback | median max hold | `sma(200)` | `max_hold=180` |
|---|---|---|---|---|
| 5m | 1.3d | 1.3d | 2.6d | 2.3d |
| 15m | 3.8d | 3.9d | 7.7d | 6.9d |
| 30m | 7.6d | 7.8d | 15.4d | 13.8d |
| 1h | 15.2d | 15.7d | 1.5mo | 1.3mo |
| 4h | 2.9mo | 3.0mo | 5.9mo | 5.3mo |
| **1d** | **4.7mo** | **4.9mo** | **9.5mo** | **8.6mo** |
| 1w | 23.6mo | 24.3mo | 47.6mo | 42.9mo |

A ~110x horizon compression from `1d` to `5m`. `B-momentum`'s thesis argues for
"multi-week waves" with a "180-day backstop"; at 5m that backstop is 2.3 days. The card
still runs — 51/51 clear the bar-count requirement at almost every interval, only 30m is
tight — but it is no longer the strategy its author described.

**So this measures the literal question**: what happens when you point an existing card
at a different candle. Not the harder counterfactual of a card *redesigned* for that
candle. Calendar-equivalent rescaling is impossible at the short end anyway — `sma(200)`
daily needs 15,600 5m bars against a 4,680-bar retention ceiling.

---

## 2. Two baselines had to be discarded first

**Raw return is uncomparable across intervals.** NVDA at `1d` covers 20+ years
(buy-and-hold 4811x); at `5m`, 60 days (1.01x). Comparing `total_return` across
intervals measures window length, not skill.

**Buy-and-hold is also wrong.** Median exposure is 0.26-0.36. A strategy in the market a
third of the time, benchmarked against a permanently-long position through a bull
market, loses by construction.

Measured naively the numbers produce a clean, entirely spurious gradient — share of runs
beating buy-and-hold falling 30% -> 41% -> 27% -> 6% -> 3% -> 2% -> 0% from 5m to 1w,
which reads as "finer candles win" and is an artifact of both problems above.

**The metric used here**, per run:

    excess = log(1 + strategy_return) - exposure * log(1 + buyhold_return)

"Did this beat simply being in the market for the same fraction of the same window?"
Log space handles compounding scale; the `exposure` weight handles the mismatch. Gated
at **>= 10 closed trades** — a strategy consumes far more data per observation than a
rule does.

---

## 3. No interval has a positive median, but daily reaches parity

Run 2, 1,667 gated runs (run 1 in brackets):

| interval | n | median excess | % beating | med capture | med exposure |
|---|---:|---:|---:|---:|---:|
| 5m | 306 | -0.0601 *(-0.0503)* | 18% *(22%)* | -0.201 | 0.26 |
| 15m | 225 | -0.0503 *(-0.0176)* | 30% *(39%)* | 0.142 | 0.29 |
| 30m | 50 | -0.0248 *(-0.0193)* | 28% *(35%)* | 0.047 | 0.30 |
| 1h | 317 | -0.0585 *(-0.0552)* | 38% *(40%)* | 0.247 | 0.30 |
| 4h | 183 | -0.0676 *(-0.1158)* | 37% *(23%)* | 0.254 | 0.36 |
| **1d** | 319 | **-0.0144** *(-0.1916)* | **49%** *(43%)* | 0.319 | 0.33 |
| 1w | 267 | -0.0516 *(-0.1135)* | 46% *(43%)* | 0.264 | 0.28 |

Every interval is still negative at the median, so the headline holds: **no candle size
beats simply holding for the same fraction of the window.** But `1d` is now essentially
at parity — -0.0144 median, 49% of runs beating — where run 1 had it worst of all seven.

`capture` sits **below** `exposure` at every interval except a near-tie at `1d`
(0.319 vs 0.33). These strategies do not merely hold less; the windows they hold in are
worse than average. At 5m capture is outright negative — the strategy loses while the
market gains.

---

## 4. The per-strategy effect is real, and it points at daily

Best interval per strategy, run 2 (n=37 strategies with enough coverage):

    5m=1   15m=4   30m=0   1h=5   4h=2   1d=14   1w=11

Split-half replication on held-out symbols, 200 random splits:

    run 2:  1860/5099 = 36.5%     (chance 14.3%)
    run 1:  1952/7400 = 26.4%

**2.6x chance, up from 1.8x.** A strategy's preferred candle is a real property, not
noise — but it still fails to replicate 63% of the time, so it remains unsafe to act on
for any individual card.

The sharper result:

    strategies preferring 1d or 1w -- their design interval
      run 2:  25/37 = 68%      (chance 29%)
      run 1:  13/37 = 35%

**68% against a 29% chance rate.** Tested on the universes they were actually written
for, these cards prefer the candle they were authored on. 29 of 37 have a best interval
that clears the matched baseline (8 do not).

---

## 5. What changed between the runs, and why it matters

Run 1 tested every card against the same fixed 15 symbols — so `B-momentum`, whose
thesis is about AI/semiconductor flows, was partly scored on KO and WMT. A 340-pair
backfill (68 symbols x 5 intraday intervals, 631,508 bars, 0 failures) raised intraday
coverage from 18 to 88-90 symbols, and run 2 tests each card only on its own universe.

Three numbers moved, all in the same direction:

| | run 1 | run 2 |
|---|---:|---:|
| best-interval replication | 26.4% | **36.5%** |
| prefer design interval (1d/1w) | 35% | **68%** |
| `1d` median excess | -0.1916 | **-0.0144** |

Run 1's "the per-strategy effect is weak and daily looks bad" was **substantially an
artifact of testing cards off-thesis**. Diluting a card's universe with symbols it was
never designed for suppressed a real signal and made daily look far worse than it is.
That is worth recording as a methodological result in its own right: universe fidelity
mattered more here than any modelling choice made downstream of it.

Coverage asymmetry turned out not to bite — run 2 has 85 distinct symbols and near-equal
n per interval (306-319 at 5m/1h/1d), because card universes are ~10-12 names and are
now almost fully covered intraday.

---

## 6. What this still does not show

- ~~**No portfolio construction.**~~ **Resolved in run 3** (section 6b).
  `tournament/runner.py` is now interval-parametric, so cards run whole — `max_positions`,
  `position_pct`, cross-sectional ranking, cash and settlement — at any candle. Runs 1 and 2
  below still describe per-symbol `StrategySpec` results and should be read as such; the
  daily-preference finding did survive full portfolio simulation, at 28/32 paired.
- **One regime intraday.** 5m/15m/30m see ~60 days; the backfill confirmed every symbol
  starts 2026-06-29 at those intervals. That is a provider ceiling, not something a
  backfill can extend — it only accrues from here. `1h`/`4h` reach 2024-08-28.
- **No significance testing.** §3's medians are descriptive. §4 uses replication rather
  than a p-value because there is no clean null for backtest excess — a weaker instrument
  than the FDR correction the rule study used, and not equivalent to it.
- **Survivorship.** The symbols are large, liquid, mostly-winning US names; buy-and-hold
  is a strong baseline in that sample specifically.
- **Costs unanalysed.** `cost_drag` is recorded per run but not yet examined. At 5m it
  will matter more than at `1d`.
- **The interesting question is untouched**: whether a card *redesigned* for a finer
  candle can do what its daily version does. Re-pointing cannot answer it.

---

## 6b. Through the portfolio path (run 3)

`tournament/runner.py` became interval-parametric, so cards can now be run whole —
`max_positions`, cross-sectional ranking, position sizing, cash and settlement — at any
candle, rather than as bare entry/exit pairs one symbol at a time. Raw cells:
`data/research/timeframes/portfolio_cells.csv` (540 runs, 393 completing; the 147 failures
are legitimate `GuardFailed`, cards whose expressions cannot clear the lookahead guard at a
given interval).

Two experiments, deliberately overlapping so they could contradict each other:

| | window | intervals |
|---|---|---|
| A | 2026-07-13 to 2026-08-25 (~6 weeks) | 5m, 15m, 30m, 1h, 4h, 1d |
| B | 2024-10-01 to 2026-08-25 (~2 years) | 1h, 4h, 1d, 1w |

They disagreed, and the disagreement is the useful part.

| | 5m | 15m | 30m | 1h | 4h | 1d | 1w |
|---|---:|---:|---:|---:|---:|---:|---:|
| A, % beating benchmark | 15% | 28% | 22% | **63%** | 37% | **7%** | |
| B, % beating benchmark | | | | 22% | 0% | **77%** | 59% |

### A is invalid, and the reason generalises

Over six weeks `1h` looks best and daily looks worst. Over two years the ranking inverts
completely. The cause:

    Experiment A, 1d:  median 4 trades per card; only 4 of 54 cards reach 10 trades
    median card max_hold = 110 bars, against the 32 sessions A grants a daily run

A daily card cannot open and close a position inside six weeks. **Experiment A therefore
measures which candle can complete a trade in the window, not which candle is better**, and
it is biased toward fine candles by construction, because they turn over faster per unit of
calendar time.

Worth stating plainly, because holding the window fixed was introduced *as* the fix for run
2's window-length confound (section 2). It removes that confound and installs a new one: any
common window short enough for 5m's 60-day retention is far too short for a strategy whose
median hold is 110 bars. **Those two constraints cannot both be satisfied with this card
library.** That is a limit on what a short-interval comparison can establish here, not a
parameter to tune.

### The paired comparison, which is valid

Beta is the other trap. `benchmark_return` is SPY, and these cards hold NVDA, AMD and AVGO
through a period when those far outran the index, so B's "77% of daily runs beat the
benchmark" is mostly that rather than timing skill. It is **not** reported here as evidence
of skill.

A *paired* design removes it. Same cards, same universe, same window, same names held —
only the candle differs, so beta sits in both arms and cancels:

    cards runnable at both 1h and 1d over the identical 2-year window:  32
      median (1d total_return - 1h total_return):                   +0.2794
      cards where 1d beat 1h:                                          28/32

**Daily beat hourly for 28 of 32 cards, by a median 27.9 percentage points, on identical
holdings over an identical period.** This is the cleanest candle-choice result in the study:
it survives the window confound (both arms share a window), the exposure confound (both arms
hold the same names) and the beta confound (both arms carry the same beta).

`5m`/`15m`/`30m` cannot enter this comparison at all. Their 60-day retention is shorter than
one median hold period, so no window exists in which both they and a daily card can complete
a trade.

### What run 3 changes

It strengthens the conclusion and narrows its scope. Run 2 found daily preferred on a weak
symbol-split signal (36.5% replication). Run 3 finds the same direction under full portfolio
simulation, in a paired design where the main confounds cancel, at 28/32.

It also establishes that the intraday half of the original question is not answerable with
this card library — not because intraday lost, but because these strategies hold for longer
than intraday history exists.

---

## 7. Bottom line

Daily — what the desk already trades — is the right default, and run 3 makes that a
positive result rather than an absence of evidence: under full portfolio simulation, on
identical holdings over an identical two-year window, **daily beat hourly for 28 of 32 cards
by a median 27.9pp**. Window length, exposure and beta all cancel in that design.

No intraday candle earns a switch. Across all three runs 5m is worst on every measure, and
its per-symbol capture is negative — it loses while the market gains.

The per-strategy effect is real (2.6x chance) but too unreliable (fails 63% of the time) to
justify re-timing any individual card.

**The intraday half of the question is not answerable with this card library.** These
strategies hold a median 110 bars; 5m/15m/30m retain 60 days. No window exists in which both
a daily card and a 5m card can complete a trade, so there is no fair comparison to run.
Answering it needs strategies designed for intraday horizons, not existing ones re-pointed
— the open question section 6 has flagged since run 1.
