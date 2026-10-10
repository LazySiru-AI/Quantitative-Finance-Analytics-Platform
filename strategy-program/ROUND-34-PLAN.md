# Round 34 — industry rotation, one level below the sector, off the taxable book

Pre-registered **2026-09-08**, before any card in this round has been run and before any measurement
in it exists. Nothing below was written with sight of a result. **The round has not been run** — the
recipe is in §9 and it has deliberately not been executed.

Not investment advice. Every number this round will produce is a backtest on price-only bars with no
dividends, and the honest prior is in §6: the most likely outcome is that nothing separates.

---

## 1. The question, and why round 17 is not the end of it

**Does round 17's form null replicate out of sample, on a disjoint universe one level below the
sector?**

Round 17 ran an 8-form × regime-on/off × 3-bracket factorial — 48 cells — on the nine full-history
GICS sector SPDRs and found every marginal inside this programme's 21.2 percentage point noise floor:
the form marginal spanned 7.56pp, the regime filter came in inside the floor, and the three bracket
policies differed by **0.14pp**, with many cells byte-identical between them because the rule's own
exit fires first almost every time. Round 18 then held the entry fixed and varied only the exit and
found the same thing.

**That is a null measured on one universe, and it is the smoother of the two available.** A sector
SPDR is a cap-weighted aggregate of many industries. `XLB` holds chemicals, metals & mining,
containers and construction materials together; `XLI` holds aerospace, railroads, machinery and
staffing together. The sector's own diversification averages a rule's signal over the dispersion the
sector contains **before the rule ever sees it**. If a strategy form has any purchase at all — if
`channel-breakout` genuinely differs from `band-reversion` in what it earns rather than only in what
it is called — it should show first where the underlying series actually move apart from each other.

So this round asks round 17's question again, on eight industry baskets that share **no ticker** with
round 17's universe and no ticker with the taxable book. It is framed as a **replication with a
pre-registered alternative**: §5 states in advance the exact result that would make "form matters on
industries" the reading, and the exact result that leaves the null standing.

**A second constraint, which is not scientific and is not negotiable.** The owner's instruction is
that these strategies must not intersect the taxable research. Every card here carries
`purpose = Purpose.ROTH` and every ticker is absent from every `savings`- or `trading`-purpose card in
the library. §3 is that constraint in full.

## 2. The field — an 8 × 2 factorial, 16 cells

Authored by `strategy-program/tools/round34.py`, which generates the cards from
`app.evolution.ruleforms` rather than restating the vocabulary in JSON. Entry and exit text come from
`ruleforms.render`, the discipline label from `ruleforms.classify` and the thesis clause from
`ruleforms.describe` — the same derivation the evolution loop uses and the same one round 17 used, so
the two rounds compare the eight forms on identical rendering.

| factor | levels | why it is a factor |
|---|---|---|
| `rule_shape` | 8 — `ma-crossover`, `momentum-state`, `rsi-pullback`, `band-reversion`, `channel-breakout`, `band-breakout`, `macd-cross`, `vol-compression` | the variable this round exists to isolate, exactly as in round 17 |
| `regime` | 2 — filter on / off | all eight forms carry a `close > sma(200)` conjunct; round 17 measured its marginal inside the floor on sectors and this asks whether that holds on industries |

8 × 2 = **16 cells**. Derived disciplines across the field, from `classify` rather than from a label:
4 momentum, 4 mean-reversion, 4 breakout, 2 trend, 2 volatility.

### 2a. Why the bracket factor is gone, and why that is legitimate

Round 17's third factor is dropped. `none`, `stop` and `stop-tp` differed by **0.14pp** across its
whole 48-cell field. Carrying that factor here would triple this round's runtime to re-measure a
contrast already **published** as empty, and would triple the Benjamini–Hochberg denominator every
surviving cell has to pay for under `PROTOCOL.md` §3 rule 8.

**This is a decision taken from a published result before any round-34 card exists, not a mid-round
narrowing** — the identical move `ROUND-18-PLAN.md` §2 made, from the same finding, for the same
reason. The surviving level is `stop`: a 12% stop, a 180-day hold cap, no target. That is round 17's
own middle level, chosen because it is the one `B-momentum`'s thesis argues for and the one round 17
found indistinguishable from `stop-tp`; picking round 17's *best* bracket level instead would be
selecting on an outcome.

### 2b. The universe, and why it is these eight names

```
XME  XRT  XHB  XSD  XOP  XBI  ITA  VNQ
```

SPDR's S&P Select Industry funds for metals & mining, retail, homebuilders, semiconductors and oil &
gas E&P; SPDR's biotech basket; iShares aerospace & defense; Vanguard's REIT fund. Each is defined by
the index it tracks — mechanically, not from a thesis, and not chosen by looking at returns, which is
the property round 17 §2 needed and this round needs for the same reason: in a round about *form*, a
thesis-picked universe is the single most obvious confound.

**`UNIVERSE` is pinned. Round 36 uses the identical tuple**, so the two rounds stay comparable name
for name.

**`IBB` was considered and deliberately excluded**, recorded here so the exclusion is pre-registered
rather than reconstructed: it is a second biotech basket duplicating `XBI`'s exposure. Two baskets of
the same industry inside an eight-name universe would give biotech a quarter of the roster and two of
the four slots, so a form that happened to suit biotech would be credited twice — and under §3 rule
8's correction a redundant name costs every other cell without buying independent evidence. This is
`c20-rotation`'s own argument ("building the same basket again under a different label would be one
hypothesis wearing two names, which is exactly the redundancy Benjamini–Hochberg correction penalizes
every other card for"), applied to a universe instead of to a card.

**Substantial-identity honesty, stated plainly rather than assumed.** `XSD` tracks the S&P
Semiconductor **Select Industry** index, which is equal-weighted — not `SOXX`'s PHLX SOX and not
`SMH`'s MVIS index. `XOP` is equal-weight oil & gas exploration and production, not `XLE`'s
cap-weighted energy sector. Those are real differences in what is held and in how it is weighted.
They are offered as description, **not as a legal opinion**: see §3.

**Every window is eligible, and that was checked rather than reasoned about.** First stored daily
bars: `VNQ` 2004-09-29, `XHB`/`XSD`/`XBI` 2006-02-06, `ITA` 2006-05-05, `XME`/`XRT`/`XOP` 2006-06-22.
The binding symbol is 2006-06-22 against the `gfc` window's deadline of **2006-10-26** for a 200-day
indicator (200 warmup bars + the lookahead guard's 40 causality bars, converted to calendar days by
`windows._bars_to_calendar_days`). So all sixteen cells clear all eight main windows, verified with
`strategy-program/tools/windows.py --cards data/rounds/r34-2026-09/cards` **before the field was
frozen**: 16 of 16 cards report `8/8 main_ok  PASS`. Round 17's Amendment 1 is why that verification
is run and not argued: there, two ETFs with zero bars in a window did not merely contribute nothing,
they failed the entire card, and the round lost `gfc` and both `chop` windows to it.

**Two windows outside the main matrix are ineligible, and neither is a problem.** `windows.py` also
prints the auxiliary matrices, and every cell fails `inv-2000` and `inv-2006` — the two investor-horizon
windows that begin before these funds existed (`XME` is the binding symbol at 2006-06-22 against
deadlines of 1998-12-20 and 2005-03-19). That is a fact about when SPDR launched the Select Industry
funds, it is identical for all sixteen cells so it cannot favour a form, and neither window counts
toward the five-of-eight gate. **No main window is affected**; every other auxiliary window
(`oil-2014`, `volmageddon-2018`, `taper-2013`, `recovery-2009`, `inflation-2021`, `banks-2023`, the
horizon rungs and the live matrix) is eligible for all sixteen.

### 2c. Held identical across all 16 cells, and the free-parameter count

| held fixed | value | note |
|---|---|---|
| universe | the eight above | identical in the same written order in every cell |
| `fast` / `slow` / `regime_ma` | 10 / 30 / 200 | round 17's periods, unchanged |
| brackets | `stop_loss_pct` 0.12, no target, `max_hold_days` 180 | §2a |
| `max_positions` | **4** | round 17 used 6 |
| `position_pct` | **0.20** | round 17 used 0.15 |
| `designed_through` | 2026-02-13 (`DESIGN_THROUGH`) | |
| `rank_by` | unset | as every card this programme has published |
| `purpose` | `roth` | §3 |

**The sizing changed from round 17 and the reason is a real trade-off, not a preference.** Maximum
commitment is 4 × 0.20 = **0.80** against round 17's 6 × 0.15 = 0.90, so the two rounds' books are of
comparable size — which matters, because `adjusted_excess`'s exposure term is not commensurable across
differently-sized books (`PROTOCOL.md` §4). What changes is how often the slot cap binds. Six slots
over eight names is 75% of the roster: the cap would almost never bind, every form would converge on
holding essentially the whole basket whenever it was invested, and **this round's null would be
confirmed by construction rather than by measurement**. That is the fairest possible criticism of a
null here and it is cheap to remove. Four of eight makes the entry rule select.

**The cost of that choice, stated so it is not discovered later:** a harder-binding cap means the
`universe` write order decides more ties, and `rank_by` is unset. So round 34 carries *more* ordering
exposure than round 17 did, not less. The 21.2pp floor is therefore **not** lowered on the strength of
round 17's ~1pp ordering replication, which was measured on a different universe under a softer cap.
It also means a between-round difference (round 34 vs round 17) is attributable to universe **and**
sizing jointly and cannot separate them; this round's primary comparison is **within-round**, across
its own 16 cells, where sizing is held identical and cannot contribute.

**Free numbers per card (`PROTOCOL.md` §3 rule 3, budget 10):** `fast` 10, `slow` 30, `regime_ma` 200,
`stop_loss_pct` 0.12, `max_hold_days` 180, `max_positions` 4, `position_pct` 0.20 = **7**. The
thresholds inside a form (RSI 40/55/60, Bollinger 2σ, MACD's 9-bar signal, the 2%/5% ATR band) are
structural constants of the hypothesis, frozen in `ruleforms.py` on 2026-08-26 before either round was
conceived, identical across every candidate of that shape and unreachable by any search step — that is
`ruleforms.py`'s own stated design and it is why the eight forms fit inside a ten-number budget at
all. Counting every literal anyway, the most constant-laden forms (`rsi-pullback` at 40/60,
`vol-compression` at 0.02/0.05) reach **9**. Both readings are inside the budget; both are reported so
a reader does not have to pick one for us.

**Nothing in this field was tuned and no grid was searched to arrive at it.**

## 3. The binding constraint — no intersection with the taxable research

Every card carries `purpose = Purpose.ROTH`, and the invariant that follows is
`app.tournament.purposes.find_disjointness_violations`: **no symbol traded by a `roth`-purpose card
may appear in the universe of any `savings`- or `trading`-purpose card.**

**Why it is this strict.** Rev. Rul. 2008-5 holds that a loss realised in a taxable account and
replaced inside an IRA within 30 days is **disallowed outright, with no basis adjustment anywhere** —
strictly worse than an ordinary wash sale, which merely defers the loss to the replacement lot.
`backend/app/tax/washsale.py` models both outcomes. The cheapest defence is never letting the two
books name the same ticker.

**How it is enforced here.** `round34.py` recomputes the taxable roster from the **live library at
build time** — `load_library()`'s four `StrategyCard` tiers *plus* the `allocation/` and `ladder/`
tiers, which `load_library` does not cover and which is where `AGG`, `BIL`, `QLD`, `SCHD`, `SGOV` and
`IEF` actually live — runs `find_disjointness_violations` over the library and this round's cards
together, and **refuses `--write` on any violation naming one of its own cards**. A violation between
two cards already on disk is printed as a pre-existing library finding and does not block this round,
because it is not this round's to fix. The roster is recomputed, never hardcoded: the library is
edited concurrently by other work in this programme, and a pinned list would pass this check against a
book that no longer exists.

At authoring time the check reported 61 purposed cards in the library, 84 distinct savings/trading
symbols, and **no overlap**. `tests/test_round34_field.py` pins the same invariant so it cannot rot.

**Ticker disjointness is necessary, not sufficient — and this document does not claim otherwise.**
IRC §1091's test is *substantially identical securities*, not identical symbols. The IRS has never
ruled on ETF pairs of this kind. `purposes.py` says exactly this and so does
`ROTH-DISJOINT-LADDER.md`; **no claim is made here that this roster is §1091-safe**, only that it
satisfies the necessary condition the programme can actually check. §2b describes the index
differences honestly and stops there.

**What these cards read.** The Parquet / DuckDB bar store, and nothing else. No card and no tool in
this round touches `data/accounts.toml`, `data/sectors.toml`, `data/store/ledger.sqlite`, or anything
under `app.tax`. The tax engine and the tax data are on the other side of a line this round does not
cross in either direction.

## 4. Windows and metric

The standard eight-window matrix, run serially by `strategy-program/tools/run_round.sh`: `q4-2018`,
`covid`, `bear-2022`, `chop-2015`, `chop-2011`, `bull-2024`, `recent`, `gfc`. The `13f-legal` window
is card-filtered to cards this round does not contain and will not run.

Ranked on `median_adjusted_excess`, where `adjusted_excess = total_return − (capital_exposure ×
benchmark_return)` — `score.py`'s primary metric, so a form that is simply invested more often is not
credited for the market's return. `worst_adjusted_excess`, `hit_rate` and the window IQR are reported
beside it per `PROTOCOL.md` §4, because this programme has repeatedly found the median and the worst
disagree. Scored with `--pin-store`, so the round records the bar-store state it actually ran against
rather than quoting a row count from an older document.

**The benchmark is SPY, in every window, for these cards too** — that is `purpose_spec(ROTH).benchmark`
and it is not a choice this round makes. It is a caveat and §7 names it.

## 5. The decision rule, pre-registered

Stated before any number exists.

**The noise floor is 21.2 percentage points.** One identical card re-run under twelve `universe`
orderings moved its three-year return across a 53.9-point spread, σ = 21.2
(`backend/app/paper/library/README.md`, study at `docs/tournament/results/a07-order/`).

**A factor is declared to matter only if its marginal spread exceeds 21.2pp.** Marginals, not cells:
the eight form-means (each averaging two cells) and the two regime-means (eight cells each).

**"Form matters on industries" requires both of the following, together:**

1. the eight form-marginals span **more than 21.2pp** max−min, **and**
2. the best-versus-worst form contrast **survives Benjamini–Hochberg at q < 0.10 with a denominator of
   every cell run in this round** — all 16, not the 8 form-marginals and not a surviving subgroup.
   `PROTOCOL.md` §3 rule 8 is explicit and this programme has made the subgroup error once already.

**Anything less is the null**, and will be reported as round 17's result replicating out of sample on
a higher-dispersion universe.

**The best single cell is not a finding.** For standard draws, E[max − min] ≈ 2.847σ over 8 and
≈ 3.532σ over 16. At σ = 21.2 that is **60.4pp** expected across eight form-marginals and **74.9pp**
across sixteen cells — both far above the 21.2pp bar the marginals must clear, which is the point: a
spread below these is consistent with having drawn the numbers from noise. If instead a form-marginal
is treated as the mean of two independent cells, σ falls to 21.2/√2 = 15.0 and the expected 8-draw
range falls to **42.7pp**. A single pre-specified pairwise form contrast needs
|diff| > 1.96 × 21.2 × √2 = **58.8pp** at the conservative σ, or **41.6pp** at the averaged one. All
three readings will be reported; none of them is below 21.2pp, so the floor is the binding constraint
either way and the decision rule above does not depend on which is chosen.

**The reproduction check, and the honest answer about it.** `ROUND-18-PLAN.md` §2 could regression-check
its instrument because two of its cells reproduced round-17 designs exactly. **This round has no such
cell: zero of the sixteen reproduce a round-17 design, because the universe is disjoint by
construction and every round-17 cell holds sector ETFs.** That is a real loss and it is not papered
over. The replacement, pre-registered here: **before scoring round 34, re-run the frozen card
`data/rounds/r17-2026-08/cards/r17-ma-crossover-on-stop.json` against the same store and check it
reproduces round 17's committed figures to the digit.** If it does not, the instrument moved between
the two rounds and every comparison in this document is suspect — the same check round 16 ran against
round 15. This is an external check on the tool, not a cell of the field, and the report must say
which it is.

**Nothing will be promoted from this round.** It is a measurement study, like rounds 15, 16, 17 and
18. No card here is a proposal to trade anything and none will be seated.

## 6. Falsifiable predictions

Fixed before any run, so this document can be wrong.

1. **The form marginal will span less than 21.2pp**, replicating round 17's null on industries. If it
   does not — and the contrast survives BH over all 16 cells — form matters on a higher-dispersion
   universe and round 17's null was a property of sector aggregation, which is a finding that changes
   what the evolution loop's single-template history cost.
2. **The regime-filter marginal will be less than 21.2pp**, replicating round 17. Six of the eight
   forms carry `close > sma(200)` on convention alone; if removing it moves nothing on industries
   either, that convention is unpaid-for on two independent universes.
3. **The 16-cell max−min spread will exceed round 17's 16-cell `stop`-bracket slice** (its 8 forms × 2
   regime arms at the same bracket level, the exactly-comparable subset). This is the "industries
   disperse more" premise stated as a number, and it is **descriptive only, explicitly excluded from
   §5's decision rule**, because it borrows round 17's published figures, which were themselves
   selected on. If it fails, the premise this round was built on was wrong at the strategy level even
   if it is true at the price level, and I will say so.
4. **`vol-compression` will take the fewest trades of the eight forms**, and is the single cell most
   likely to fail the regime gate. Its entry needs `atr(10)/close < 0.02`, and `XBI`, `XOP` and `XME`
   are materially more volatile than any sector SPDR, so that gate should open rarely on this
   universe. (Round 17 refuted the related claim that this form posts the *lowest exposure* — its exit
   waits for ATR above 5%, so it holds long once in. This prediction is about trade count, not
   exposure, and is the version round 17's refutation did not already settle.)
5. **The trend and momentum forms — `ma-crossover`, `momentum-state`, `macd-cross`, `vol-compression`
   — will post their worst adjusted excess in `chop-2011` or `chop-2015`.** This is the round's
   pre-registered failure regime under §3 rule 5; each card carries its own form-specific version in
   its `falsification` field, and the per-card reports print the prediction beside the outcome.
6. **All 16 cells will produce a scored result in 8 of 8 main windows.** Eligibility was already
   checked against the store before freezing (§2b, 16 of 16 at `8/8 PASS`), so this is the stronger
   claim that the runner also *completes* every one — the gap Round 17's first attempt fell into,
   where the store said a symbol existed and the lookahead guard still refused the card. A shortfall
   is to be reconciled against the runner's `FAILED` lines (§9) and recorded as an instrument
   surprise, never absorbed silently.

## 7. What this round cannot settle

Named here so the report cannot quietly overclaim.

- **Survivorship of the roster.** These eight are ETFs that exist *today*. An industry basket that
  launched and closed between 2006 and now is absent from the store and therefore from this universe,
  and nothing in this programme measures how many there were. The universe is mechanically defined and
  free of *stock*-level survivorship, which is what round 17 bought; it is not free of *fund*-level
  survivorship, and that distinction is not one round 17 had to make either.
- **Price-only, dividend-free bars.** This bites harder here than in round 17. `VNQ` is a REIT fund
  whose total return is substantially distributions; over an eighteen-year matrix its price-only
  series understates it by a large and unmeasured amount. `XOP` and `XME` carry meaningful yields too.
  Every cell holds the same names, so this cannot favour a form — but it means no absolute number in
  this round is a return anyone could have earned.
- **SPY as the benchmark for a Roth book of equal-weight industry baskets.** `purpose_spec(ROTH)`
  says SPY and this round does not relitigate it, but SPY is a cap-weighted large-cap blend index and
  every name here is an equal-weight industry basket. A common size/weighting factor is mixed into
  every cell's excess identically. It cannot favour a form; it does mean "excess over SPY" is not
  "excess over the thing these funds actually are".
- **The ordering-noise floor on *this* universe is unmeasured.** The 21.2pp figure comes from a
  different card on a different universe, and §2c explains why this field's harder-binding slot cap
  should carry *more* ordering exposure, not less. No shuffled-ordering replication is budgeted here;
  if one is wanted it is a separate study and must be pre-registered as one.
- **Everything in round 17 §7 still applies unchanged**: no cross-sectional ranking, no cross-symbol
  regime gate, no volatility-scaled sizing, no shorting, leverage or options, no mid-window rotation,
  and no non-price data — `PriceField` exposes only open/high/low/close/volume, so the macro series
  and the event calendar cannot reach a card at all.
- **It cannot promote anything**, and two consecutive qualifying rounds on differing window sets would
  be required before any cell here could become a candidate.
- **It settles nothing about tax.** §3's disjointness is a necessary condition, checked; it is not a
  §1091 opinion and this round produces no evidence about wash sales, basis, or the taxable book.

## 8. The honest prior

The likeliest outcome is that **nothing separates beyond noise**, again. That is not a disappointing
result and it is not a null to be buried: round 17's null on sectors could always be answered with
"you measured it on the smoothest universe available." A null here removes that answer, on a universe
picked in advance precisely because it was the one most likely to break it. Round 33's own record —
one positive edge in 9,480 cells, and a promoted branch that failed BH correction and out-of-sample —
is the prior this round is written against, and the accumulated record of rounds 1–33 is that no
durable edge has been found. A new round should have to argue against that record, not the reverse.

The result that would genuinely change the programme's direction is prediction 1 failing **together
with** §5's BH condition. Prediction 1 failing on its own is one more max-of-sixteen.

## 9. Determinism, scope and the run recipe

`build()` is deterministic: `RULE_SHAPES` is a fixed tuple, the regime arms are ordered, and nothing
in the tool reads a clock, a random source, the bar store or the filesystem. Two calls produce
identical model dumps, which `tests/test_round34_field.py` asserts.

**The round has NOT been run.** The bar store is single-writer, a full matrix takes hours, and another
session may hold it. The recipe, to be executed by whoever runs the round:

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round34.py --write
bash strategy-program/tools/run_round.sh data/rounds/r34-2026-09/cards data/rounds/r34-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py --results data/rounds/r34-2026-09/results --json data/rounds/r34-2026-09/scorecard.json
```

Before scoring, run §5's external reproduction check on `r17-ma-crossover-on-stop`, and reconcile the
run files against the runner's `FAILED` lines for every window per `PROTOCOL.md` §8 — the runner walks
past a failed card by design, so a shortfall is silent and a contended round produces a report that
looks complete.

**Files this round owns:** this document, `strategy-program/tools/round34.py`,
`data/rounds/r34-2026-09/cards/*.json` and `tests/test_round34_field.py`. Nothing else.
