# Round 17 — does strategy *form* matter, holding everything else fixed?

Pre-registered 2026-08-29, before any card in this round has been run. Nothing below was written with
sight of a result.

Not investment advice. Every number this round will produce is a backtest on price-only bars with no
dividends, and the honest prior is stated in §6: the most likely outcome is that nothing separates.

---

## 1. The question, and why it has never been asked

**Does the *form* of an entry rule change what a strategy earns, once universe, parameters, sizing and
brackets are held identical?**

Sixteen rounds and a 1,935-generation autonomous search have never answered this, for two different
reasons:

- **Rounds 1–16 varied form together with everything else.** A round's field was a set of analyst
  cards, each with its own universe, its own periods, its own brackets and its own thesis. When one
  won, no part of that result could be attributed to its rule shape rather than to the twelve names
  it happened to hold. `PROGRAMME-REPORT.md` §14 concedes the general version of this.
- **The evolution loop varied parameters *inside a single form*.** `app.evolution.proposer._rules_card`
  composed every candidate's entry from one hardcoded f-string until 2026-08-26. Joining the ledger to
  the genome files pins the split exactly: **generations 1–1915 (1,374 rules-shape rows, 1,098 genomes)
  ran the single `ma-crossover` template**, and generations 1917–1935 (10 generations, 100 rows, 88
  genomes — 7.3% of all rules-shape genomes ever scored) ran the eight-form vocabulary. **All 28
  promotions and all 25 outstanding seat requests come from the one-template regime. Nothing from the
  eight-form regime has cleared a gate.**

So the programme has an enormous amount of evidence about one strategy form and almost none comparing
forms. This round is the missing comparison, and it is deliberately the cheapest possible version of
it: no search, no breeding, no promotion — one pre-registered grid, run once.

## 2. The field — an 8 × 2 × 3 factorial, 48 cells

Authored by `strategy-program/tools/round17.py`, which generates the cards from
`app.evolution.ruleforms` rather than restating the vocabulary in JSON. The entry and exit text and
the `discipline` label are produced by the same `render`/`classify` functions the evolution loop uses,
so this round compares the eight forms **as the loop actually emits them**.

| factor | levels | why it is a factor |
|---|---|---|
| `rule_shape` | 8 — `ma-crossover`, `momentum-state`, `rsi-pullback`, `band-reversion`, `channel-breakout`, `band-breakout`, `macd-cross`, `vol-compression` | the variable this round exists to isolate |
| `regime` | 2 — filter on / off | all eight forms carry a `close > sma(200)` conjunct and no round has ever measured what it is worth |
| `brackets` | 3 — `none` / `stop` / `stop-tp` | `B-momentum`'s thesis claims a take-profit amputates this kind of edge; that claim came from one card's design study and has never been tested across forms |

**Held identical across all 48 cells:** universe, `fast`/`slow`/`regime_ma` = 10/30/200,
`max_positions` = 6, `position_pct` = 0.15, `designed_through` = 2026-02-13 (the programme's
`DESIGN_THROUGH`).

**Nothing in this field was tuned.** Every threshold inside a form — RSI 40/60, Bollinger 2σ, MACD's
9-bar signal, the 2%/5% ATR band — is the textbook constant frozen in `ruleforms.py` on 2026-08-26,
before this round was conceived. No parameter here was chosen by looking at an outcome.

### The universe, and why it is the sector ETFs

`XLK XLF XLE XLV XLI XLY XLP XLU XLB XLRE XLC` — the eleven GICS sector SPDRs.

`PROGRAMME-REPORT.md` §14 concedes that every long-horizon figure in this programme is an unmeasured
upper bound, because the survivorship gate catches mechanically index-derived universes but not
analyst-thesis-picked ones. The sector ETFs are mechanically defined, do not die, and were not
selected by looking at returns — which removes stock selection from the comparison completely. In a
round about *form*, a thesis-picked universe would be the single most obvious confound.

**Two of them are younger than the matrix**: `XLRE` starts 2015-10-07 and `XLC` 2018-06-18, so `gfc`
and `chop-2011` see nine names rather than eleven. This is identical for all 48 cards and therefore
cannot favour a form; it is recorded here so no reader has to rediscover it.

## 3. Windows and metric

The standard matrix, run serially by `strategy-program/tools/run_round.sh`: `q4-2018`, `covid`,
`bear-2022`, `chop-2015`, `chop-2011`, `bull-2024`, `recent`, `gfc`. The `13f-legal` window is
card-filtered to a card this round does not contain and will not run.

Ranked on `median_adjusted_excess`, `adjusted_excess = total_return − (exposure × benchmark_return)` —
`score.py`'s primary metric, chosen because a form that is simply invested more often should not be
credited for the market's return. `worst_adjusted_excess` and `hit_rate` are reported beside it, per
§4 of the protocol, because the programme has repeatedly found the median and the worst disagree.

Scored with `--pin-store`, so this round records the bar-store state it actually ran against rather
than quoting a row count from an older document (`DEFECTS.md` D6).

## 4. The decision rule, pre-registered

This is the part that matters most, and it is stated before any number exists.

**The noise floor is 21.2 percentage points.** One identical card re-run under twelve `universe`
orderings moved its three-year return across a 53.9-point spread, σ = 21.2 (`backend/app/paper/library/README.md`,
study at `docs/tournament/results/a07-order/`).

**A factor is declared to matter only if its marginal spread exceeds 21.2pp.** Marginals, not cells:
the eight form-means (each averaging six cells), the two regime-means (24 cells each), the three
bracket-means (16 cells each).

**The best single cell is not a finding.** Simulated at σ = 21.2pp, the expected max−min spread across
48 independent draws of pure noise is **94.8pp**, with a 95th percentile of **119.2pp**. Across eight
form-marginals it is **60.4pp** expected, 90.9pp at the 95th percentile. A single pre-specified
pairwise contrast needs **|diff| > 58.8pp** to clear 95%. Any spread below these is consistent with
having drawn 48 numbers from noise, and will be reported as such.

**One caveat that cuts the other way, stated so it cannot be used selectively later.** The 21.2pp
figure is the variance of *one card under different universe orderings*. In this round every cell
shares the same universe in the same order, so that particular noise source is held constant and does
not inflate *between-cell* comparisons the way the simulation above assumes. The simulation is
therefore the conservative reading, not the exact one. Both readings will be reported.

**And a direct empirical test of exactly that, pre-registered now:** after scoring, the top and bottom
cells will be **re-run under a shuffled universe ordering**. If the gap between them survives the
shuffle, ordering noise does not explain it. If it collapses, it did. This is cheap, it is the
question the σ figure only estimates, and no round has done it.

**Nothing will be promoted from this round.** It is a measurement study, like rounds 15 and 16. No
card here is a proposal to trade anything, and none will be seated.

## 5. Falsifiable predictions

Stated in advance so this document can be wrong.

1. **No form-marginal will beat the next-best by more than 21.2pp.** If one does, form matters more
   than parameter search does, and the loop's 1,915 single-template generations carried a real
   opportunity cost that can now be named.
2. **The regime filter will not move the marginal by more than 21.2pp.** Six of eight forms carry it
   on the strength of convention alone.
3. **`stop-tp` will underperform `stop` on the bracket marginal**, reproducing `B-momentum`'s claim.
   If it does not, that thesis was a property of one card's universe rather than of brackets.
4. **`vol-compression` will post the lowest exposure of the eight forms**, because it requires ATR
   under 2% of price, which is a rare state.
5. **At least one cell will fail eligibility** — fewer than `MIN_ELIGIBLE_MAIN_WINDOWS` = 5 main
   windows in which it took a trade — because some forms are too restrictive on eleven names.

## 6. The honest prior

The likeliest outcome is that **nothing separates beyond noise**. That is not a disappointing result
and it is not a null to be buried: it would put a number on what the evolution loop's narrowness
actually cost. If eight structurally different forms, run over the same names on the same days, land
inside 21.2 points of one another, then a searcher that could only emit one of them was not missing
much — and the programme's effort is better spent on the expressiveness gaps in §7 than on widening
the rule vocabulary further.

The result that would genuinely change the programme's direction is prediction 1 failing.

## 7. What this round cannot settle

Named here so the report cannot quietly overclaim:

- **It says nothing about the strategy classes the engine cannot express.** No cross-sectional
  ranking, no cross-symbol regime gate (an analyst's VIX-gating attempt was abandoned for this
  reason), no volatility-scaled sizing, no shorting, leverage or options, no mid-window universe
  rotation, no dividends. `TiltRule.shift_pct` is a fixed `Decimal`, so continuous vol-targeting and
  inverse-vol risk parity — `ALLOCATION-FAMILY.md`'s best risk-adjusted result — remain unrunnable.
- **It says nothing about non-price data.** The rules DSL's `PriceField` enum exposes only
  open/high/low/close/volume, so Fear & Greed, the FRED macro series and the event calendar cannot
  reach a card at all, however much of that data the application collects.
- **It is one universe.** A form that suits eleven sector ETFs may not suit twelve megacap names.
  This round trades breadth of universe for the ability to attribute a difference to form.
- **It is price-only and dividend-free**, like every other backtest in this programme. On an eleven
  sector-ETF universe over a `gfc` window, that omission is not small.
- **It cannot promote anything**, and two consecutive qualifying rounds on differing window sets would
  be required before any cell here could become a candidate.

---

## 8. Amendment 1 — the universe, after the first attempt returned nothing in three windows

**Recorded 2026-08-30, after the first run and before the second. The failed attempt is kept on disk
at `data/rounds/r17-2026-08/{cards,results}-11etf-INVALID/`, following this programme's rule that a
correction keeps the error visible beside it.**

§2 pre-registered the eleven GICS sector SPDRs and disclosed that `XLRE` (from 2015-10-07) and `XLC`
(from 2018-06-18) are younger than the matrix, asserting that this "is identical for all 48 cards and
therefore cannot favour a form."

**That was true and it was not the relevant risk.** A symbol with zero bars in a window does not
merely contribute nothing to that card — it fails the entire card. The lookahead guard cannot
demonstrate causality against a series with no post-warmup region, and it refuses rather than passing
on no evidence:

```
GuardFailed: entry expression 'close crosses_above bb_upper(30, 2)' failed the lookahead guard
against XLRE (failed): causality: bb_30_2: only 0 bars against a 29-bar warmup leaves no
post-warmup region to truncate, so causality could not be demonstrated -- this guard reports
that as a failure rather than passing on no evidence
```

The first attempt therefore produced:

| window | runs of 48 |
|---|---|
| q4-2018 | **21** — partial, because `XLC` had ~3 months of history against a 200-day warmup |
| covid, bear-2022, bull-2024, recent | 48 |
| chop-2015, chop-2011, gfc | **0** |

Five complete windows is exactly `MIN_ELIGIBLE_MAIN_WINDOWS` with no slack, and the three lost are
`gfc` — the deepest drawdown available — plus **both** sideways regimes. Scoring that remnant would
have meant ranking forms on a window mix with no flat regime and no crash, which is precisely the
error `PROGRAMME-REPORT.md` §5 records round 4 making ("Round 3's conclusions were properties of
round 3's windows"). The partial `q4-2018` is worse than the zeroes: the 21 survivors are not a random
subset but the shorter-warmup forms, so a comparison across that window would have been a comparison
of warmup lengths wearing a form's name.

**The amendment.** The universe becomes the **nine sector SPDRs with full history** — `XLK XLF XLE
XLV XLI XLY XLP XLU XLB`, all from 1998-12-21, which covers every window in the matrix including
`gfc`. `XLRE` and `XLC` are dropped.

**What this changes about the round's claims, stated plainly:**

- The universe remains mechanically defined, survivorship-free and not chosen by looking at returns.
  The exclusion is on a data-availability criterion applied before any result was seen, not on
  performance — real estate and communication services are dropped for having no 2007 history, not
  for how they did.
- It is now a nine-sector universe, so §7's "it is one universe" caveat is unchanged but the universe
  is slightly narrower than pre-registered.
- **No prediction in §5 is altered, and none is weakened.** They were stated over form-marginals, not
  over specific tickers.
- Nothing was learned from the failed attempt that could inform a prediction: it produced no scored
  result in any window it failed, and the five windows that did complete have not been scored.

**Why this is an amendment and not a fresh round.** Nothing about the question, the factors, the
metric or the decision rule changes. What changed is a data-availability fact about two tickers that
should have been checked against the *guard*, not merely against the *store*, before the field was
authored. That check now exists in this document for whoever writes round 18.
