# Round 35 — country rotation off the taxable book

**Pre-registered 2026-09-08, before any card in this round has been run. Nothing below was written
with sight of a result. As of this writing the round has NOT been run: no card in
`data/rounds/r35-2026-09/cards/` has produced a single run file, and there is no
`data/rounds/r35-2026-09/results/` and no scorecard.**

Not investment advice. Every number this round will produce is a backtest on price-only bars with no
dividends, measured against a US benchmark, on a universe that does not survive the honesty register
in §7 intact. The honest prior is in §6: the most likely outcome is that every rotation cell lands
inside the noise floor of its own passive control.

---

## 1. The question, and the two reasons it is worth one round

**Does the c20 / round-17 rotation shape — one absolute per-symbol trend filter applied identically
across a small ETF universe, with a binding slot cap doing the actual rotating — carry any
information when the rotation axis is *country* rather than *sector*?**

This engine has no cross-symbol operator. `entry` and `exit` are evaluated per instrument against
that instrument's own bars, so "rotation" in this programme has always been produced by the universe,
the slot cap and the fill order, never by a rule that compares one symbol to another.
`backend/app/paper/library/candidates/c20-rotation.json` says this about itself in its own first
sentence, and round 17 generalised the shape across eight rule forms. **Every version of it has been
pointed at sectors.**

Country dispersion is a different source. It is driven by currency, by local monetary policy, by
index composition (Korea is semiconductors; Latin America is commodities; Japan is exporters) and by
capital-flow cycles that are not the US sector rotation wearing different tickers. This programme has
never measured it — rounds 1–33 contain no non-US equity universe at all.

**The second reason is legal, and it is why the universe is what it is.** These cards carry
`purpose = Purpose.ROTH`, and §6 of `THREE-PURPOSES-PLAN.md` requires that no symbol traded by a
roth-purpose card appear in the universe of any `savings`- or `trading`-purpose card. That is not
tidiness: Rev. Rul. 2008-5 does not *defer* a wash-sale loss when the replacement is bought inside an
IRA, it **destroys** it outright. So the Roth book needs research universes the taxable book does not
touch, and single-country equity ETFs are one of the few liquid asset groups still fully unclaimed.
This round is both a measurement and an attempt to find one.

**The record this round argues against.** Rounds 1–33 found no durable edge — one positive cell in a
9,480-cell timeframe sweep, seven measured-null macro series, a round-33 promotion that fails its own
Benjamini-Hochberg correction and its own out-of-sample test. That is the prior, and this round is
designed so that a null here is *informative* rather than merely expected: §2's passive control is
what makes "the rotation earned nothing" separable from "the asset class earned nothing".

## 2. The universe, pinned before anything was measured

`EWJ EWG EWU EWC EWY ILF EFA VWO` — iShares Japan, Germany, UK, Canada, South Korea, iShares Latin
America 40, iShares MSCI EAFE, Vanguard FTSE Emerging Markets.

First stored daily bars: `EWJ`/`EWG`/`EWU`/`EWC` 1996-03-18, `EWY` 2000-05-12, `EFA` 2001-08-27,
`ILF` 2001-10-26, `VWO` 2005-03-10. `VWO` is the binding symbol and it clears `gfc` (2007-10-09) with
a 200-day indicator by more than two years — **verified**, not asserted: `windows.py --cards` reports
all nine cards eligible in **8 of 8** main windows (§8).

Selection criteria, both applied before any result existed and neither of them a return:

1. **Enough stored history to clear every main window**, `gfc` included. This is the eligibility gate
   of `WINDOWS.md`, and it is the reason `EWA`-style latecomers and every 2010s single-country launch
   are absent.
2. **Total absence from the taxable book.** `strategy-program/tools/round35.py` recomputes the
   claimed set from the live library on every run — `load_library`'s four `StrategyCard` tiers plus
   the `allocation/` and `ladder/` directories that function does not walk, which between them hold
   five taxable tickers (`AGG`, `BIL`, `QLD`, `SCHD`, `SGOV`) that a `load_library`-only check would
   miss. As of 2026-09-08 that set is **84 tickers across 39 savings/trading cards**, and the tool
   **refuses `--write`** if any of them intersects this universe or if
   `find_disjointness_violations` returns anything.

### 2a. Four names that belong here and are excluded anyway

`EEM`, `EWZ`, `FXI` and `INDA` are single-country/regional equity ETFs that belong in a
country-rotation universe on the merits. All four are claimed by the taxable book. They are out on
the disjointness invariant alone, and that is a cost this round pays knowingly: emerging Asia and
Brazil enter only through `VWO` and `ILF`, which is a weaker instrument for the same exposure.

### 2b. Substantial identity — what disjointness does and does not buy

**Ticker disjointness is necessary and not sufficient under IRC §1091**, and nothing in this round
should be read as a §1091-safety claim.

- `VWO` tracks FTSE Emerging Markets; the taxable book's `EEM` tracks MSCI Emerging Markets. They are
  different securities tracking different indices — and their economic exposure is close.
- `ILF` is roughly 60% Brazil. The taxable book holds `EWZ`, which is Brazil.

What the disjoint roster guarantees is that no *identical* security is ever repurchased across the
two books, which is the failure mode that is both mechanical and catastrophic. Whether a particular
pair is "substantially identical" is a question about holdings and a matter for a tax adviser, not
for this document. `app.tournament.purposes` draws exactly this boundary in its own docstring; this
section restates it rather than assuming a reader will go and find it.

### 2c. The universe is not eight independent bets

`EFA` (MSCI EAFE) contains `EWJ`, `EWG` and `EWU` among its largest country weights. `VWO` and `ILF`
overlap on Brazil. So the field is being run over a roster with substantial internal redundancy.

**How that is handled: it counts against the field and nothing is added to compensate.** Benjamini-
Hochberg correction runs over every cell this round runs (`PROTOCOL.md` §3 rule 8 — the denominator
is everything tried, never a subgroup), and correlated cells spend denominator while buying no extra
evidence. The wrong response would be to add cells or names to "cover" the redundancy; the field
stays at nine, and the redundancy is reported as a reason any surviving margin should be read
smaller than it looks.

## 3. The field — 2 forms × 2 slot caps × 2 fill orders, plus one control = 9 cells

Authored by `strategy-program/tools/round35.py`. No grid search: every number below is transplanted
from a card or a module frozen before this round was conceived.

| factor | levels | why it is a factor |
|---|---|---|
| entry form | 2 — `absolute`, `macross` | the two shapes with real records here: c20's absolute filter, and the one template that produced all 28 of the evolution loop's promotions |
| slot cap | 2 — 2 slots, 4 slots | the cap *is* the rotation mechanism in an engine with no cross-symbol operator; 8 names into 2 or 4 slots is the binding constraint c20 relies on |
| fill order | 2 — universe order, `close / sma(200)` | which qualifying name takes a scarce slot. Unset, it is the arbitrary tiebreak `PROTOCOL.md` §7 measures at σ = 21.2 points |

**`absolute`** — `c20-rotation`'s filter, character for character:

```
entry: close > sma(100) and rsi(14) > 50 and rsi(14) < 75
exit:  close < sma(100) or rsi(14) < 40
```

Transplanted rather than re-authored, because a re-tuned version would answer a different question
from the one being asked. `app.evolution.ruleforms.classify` reads this as `mean-reversion`, while
c20's own JSON carries `pairs-rotation`; the derived label is used here and the disagreement is
recorded rather than resolved.

**`macross`** — rendered by `app.evolution.ruleforms.render("ma-crossover", fast=10, slow=30,
regime_ma=200)`, so this round compares the form **as the loop actually emits it** rather than a
second copy typed into a tool:

```
entry: close > sma(200) and ema(10) crosses_above ema(30)
exit:  ema(10) crosses_below ema(30)
```

**Held identical across all eight rotation cells:** universe; `stop_loss_pct` 0.10; no take-profit;
`max_hold_days` 150 (both bracket numbers are c20's own — brackets belong to neither form's
definition, so holding them fixed is what lets a difference between forms be attributed to the form);
`designed_through = DESIGN_THROUGH` (2026-02-13); `purpose = Purpose.ROTH`.

**Sizing: every card in the field targets the same 88% maximum deployed capital.** 2 slots × 0.44,
4 slots × 0.22, control 8 × 0.11. This is a deliberate design choice and it is what makes the slot
cap a question about *concentration* rather than about how much money is in the market — and it keeps
every cell clear of `PROTOCOL.md` §4's 2× exposure-divergence flag by construction rather than by
luck.

### 3a. The passive control — `r35-passive-8-order`

```
entry: close > 0        (true on every bar)
exit:  close < 0        (true on none)
no stop, no target, no time stop, 8 slots × 0.11
```

Both expressions were run through `app.backtest.guards.check` against real `EWJ` bars before this
field was authored; **both pass**, as does the ranking key `close / sma(200)`. So the always-true
control is viable and the idea did not have to be dropped.

**Why eight slots and not the rotation cells' two or four.** §4's known confound is that the
benchmark is SPY. The quantity that would actually settle whether the rotation carries information is
its excess over an **equal-weight buy-and-hold of these same eight names** — and the scorecard cannot
compute that. This card *is* that baseline, run through the identical engine on the identical
sessions. A 4-slot passive card would instead hold whichever four names sit first in the universe
tuple (Japan, Germany, the UK, Canada — a developed-markets-only book) and would measure universe
ordering rather than the asset class. Same capital budget, all eight names, no ranking (with a slot
per name there is nothing to rank).

**It is a position, not a strategy.** `StrategyCard`'s own model docstring says a card with no exit,
no target and no time stop "can hold forever, which is a position, not a strategy" — that is exactly
what this card is, and it is in the field to be subtracted, never to be ranked or promoted. Its
`discipline` is a forced label: `ruleforms.classify` returns `None` for a rule containing no
indicator and the `Discipline` enum has no member meaning "passive", so `trend` is the least wrong of
seven wrong options and is not a claim about what the card does.

**It is a buy-and-hold proxy, not an index.** It never rebalances, so it drifts away from equal
weight across a long window, and it deploys 88% rather than 100%. Both differences are small relative
to the effect being measured and both are stated here so no reader has to infer them.

### 3b. Free-parameter budget (`PROTOCOL.md` §3 rule 3 — ten per card)

Counted as **distinct numeric values** across `entry`, `exit` and `rank_by`, plus one each for the
stop, the target, the hold cap, the slot count and the position size. `sma(100)` appearing in both
the entry and the exit is one number an author chose once; counting it twice would inflate the budget
with a fact about text rather than about the hypothesis.

| cell | free numbers |
|---|---|
| `r35-absolute-2-order`, `r35-absolute-4-order` | 9 |
| `r35-absolute-2-rank`, `r35-absolute-4-rank` | **10 — exactly at the budget** |
| `r35-macross-*` (all four) | 7 |
| `r35-passive-8-order` | 3 |

`tests/test_round35_field.py` pins the maximum at 10 and pins the ranked `absolute` cells at exactly
10, so any later edit that adds a number to them breaks the constitution rather than the margin.

## 4. Windows, metric, and the confound this round is built around

**Windows.** The standard eight-window matrix, run serially by `run_round.sh`: `q4-2018`, `covid`,
`bear-2022`, `chop-2015`, `chop-2011`, `bull-2024`, `recent`, `gfc`. The `13f-legal` window is
card-filtered to a card this round does not contain and will not run. All nine cards are eligible in
**8 of 8** — verified in §8, not predicted.

**Metric.** `PROTOCOL.md` §4's primary key: the median of `adjusted_excess = total_return −
capital_exposure × benchmark_return` across a card's eligible main windows, with `worst_adjusted_
excess`, `hit_rate` and the across-window IQR reported beside it.

### 4a. The known confound, pre-registered

**The benchmark is SPY, price-only, in USD.** A non-US universe measured against SPY over 2011–2026
inherits a decade of US outperformance and a decade of dollar strength that no rule inside this
engine can overcome. `adjusted_excess` partially controls for *exposure* — it asks whether the rules
beat being invested the same fraction of the time — but it does not control for the **asset-class
gap**, and nothing in this harness does.

Two further pieces of the same problem, both structural:

- **Price-only, no dividends.** Non-US equity indices carry structurally higher dividend yields than
  the S&P 500. Dropping dividends therefore penalises this universe *more* than it penalises the
  benchmark, and by an amount this round does not measure.
- **FX is embedded.** These are USD-listed ETFs, so each one's return is a local-currency equity
  return multiplied by a currency move, and this round cannot separate the two.

**How the result will be read, fixed now.** The headline `adjusted_excess vs SPY` figures are
expected to be negative and will be reported as **uninformative about the rotation**. The quantity
this round actually ranks on is **each rotation cell's median adjusted excess minus the passive
control's**, both measured on the identical windows, which is the closest thing to a
rotation-versus-buy-and-hold comparison this harness can produce. Any narrative built on the SPY
column alone — in either direction — is out of bounds under this pre-registration.

## 5. Falsifiable predictions, fixed before any run

1. **Every rotation cell posts a negative median adjusted excess against SPY.** This is a prediction
   about the asset-class gap in §4a, not about the rules. If a cell posts a positive median against
   SPY, either the gap is smaller than §4a asserts over this window mix, or something in that cell is
   worth a second look — and the second look is a separate round, not a promotion.
2. **No rotation cell beats the passive control by more than 21.2pp on median adjusted excess.**
   This is the round's real hypothesis test, and it is the one that would overturn the programme's
   rounds 1–33 record if it failed. A margin inside 21.2pp is a null whichever side of the control it
   lands on.
3. **Pre-registered failure regimes** (`PROTOCOL.md` §3 rule 5), named per form before the run:
   - `macross` — its worst two windows are **`chop-2011` and `chop-2015`**. A 10/30 EMA crossover is
     whipsawed by a market that moves constantly and arrives nowhere, and both chop windows were
     built precisely to expose that.
   - `absolute` — its worst window is **`covid`**. A 100-day filter plus an `rsi(14) < 75` ceiling
     cannot re-enter fast enough in a V-shaped snapback, and the RSI ceiling actively blocks the
     strongest part of the rebound.
   - The control's worst window is **`gfc`**, trivially and by construction.
4. **The two fill orders differ by less than 21.2pp**, both as a marginal (four `rank` cells against
   four `order` cells) and within each matched pair. The one existing measurement of relative-strength
   ordering against random orderings put it 9th of 10, inside the noise (`PROTOCOL.md` §7); this
   predicts that result reproduces on a country universe.
5. **The 2-slot cells post a wider across-window IQR than the 4-slot cells at the same 88% budget.**
   Concentration into two names doubles per-name weight, so the fragility should be visible in spread
   even if the medians are indistinguishable.
6. **Validity check, not a hypothesis:** the control holds all eight names on essentially every
   session of every window (session exposure at or near 1.0, eight trades per window). If it does not,
   it is not the baseline it is being used as, and **every comparison in this round is void**.

## 6. The honest prior

The likeliest outcome is prediction 2 holding: all eight rotation cells land inside 21.2pp of the
passive control, and the round reports that the c20 shape carries no measurable information on the
country axis either. That is the programme's rounds 1–33 record reproducing on a new dispersion
source, and it is worth one round precisely because the source is new and the roster is legally
usable by the Roth book.

The result that would change the programme's direction is **prediction 2 failing on the same side in
both forms** — that is, both `absolute` and `macross` beating the control by more than the floor. One
form doing it is one cell family out of a nine-cell field and dies to Benjamini-Hochberg.

## 7. Decision rule, and what this round can never settle

**Decision rule, pre-registered:**

- Rank on median adjusted excess across the eight main windows, with the **rotation-minus-control**
  difference as the reported quantity (§4a).
- **The noise floor is 21.2pp** (`PROTOCOL.md` §7). No margin inside it is a finding, in either
  direction.
- **Benjamini-Hochberg over all nine cells** — the denominator is every cell this round runs, never a
  surviving subgroup (`PROTOCOL.md` §3 rule 8). If any cell from this round is later compared
  alongside cells from another round, the denominator grows accordingly.
- **Nothing is promoted from this round.** It is a measurement study, like rounds 15, 16 and 17.
  `PROTOCOL.md` §6 requires two consecutive qualifying rounds on window sets that differ before any
  cell could become a candidate, and a single round cannot supply that by construction.

**What this round can never settle**, stated here so the report cannot quietly overclaim:

- **Roster survivorship.** These eight ETFs are the survivors of the country-ETF launch cohort. Funds
  that closed are not in the bar store, so a "country rotation" measured on the ones still trading in
  2026 is a kinder experiment than the one an investor faced in 2001. The bias is in the selection,
  not in the data, and it is not sized here.
- **Price-only bars, no dividends** — and §4a's point that this penalises a non-US universe harder
  than it penalises SPY.
- **FX.** Each ticker's return is a local equity move times a currency move and this round cannot
  separate them; a "country rotation" result here may be a dollar-cycle result wearing eight tickers.
- **SPY as the benchmark for a Roth book.** A tax-free long-horizon book measured against a US
  large-cap price index is a convention inherited from the harness, not a considered choice, and §4a
  is the whole reason the control exists.
- **The 21.2pp ordering-noise floor**, which bounds every margin this round can report.
- **Composite overlap** (§2c): `EFA` contains three of the seven other names, so this is not eight
  independent bets and no q-value here should be read as though it were.
- **Substantial identity** (§2b): ticker disjointness is necessary, not sufficient, under IRC §1091.
  This round establishes that no identical security is repurchased across the two books. It
  establishes nothing about whether `VWO`/`EEM` or `ILF`/`EWZ` are substantially identical, and it is
  not tax advice.
- **Nothing outside the bar store.** These cards read only the Parquet/DuckDB daily bars. Nothing in
  this round touches `data/accounts.toml`, `data/sectors.toml`, `data/store/ledger.sqlite` or
  `app.tax`, and no figure produced here has any bearing on a real tax lot.

## 8. Determinism, scope and the run recipe

**Determinism.** `round35.build()` reads no clock, no filesystem and no randomness; called twice it
returns field-identical cards, which `tests/test_round35_field.py::TestDeterminism` pins. The only
part of the tool that reads state is the disjointness check, which reads the live library on purpose
— a ticker list pasted into a constant is correct exactly until the next commit, and this repository
is edited by concurrent sessions.

**Scope.** This round owns `strategy-program/ROUND-35-PLAN.md`, `strategy-program/tools/round35.py`,
`data/rounds/r35-2026-09/cards/*.json` and `tests/test_round35_field.py`. It modifies no library
card, no shared tool and no other round.

**Eligibility, verified 2026-09-08** (`windows.py --cards data/rounds/r35-2026-09/cards`, main-matrix
columns only):

| card | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc | main_ok |
|---|---|---|---|---|---|---|---|---|---|
| `r35-absolute-2-order` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r35-absolute-2-rank` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r35-absolute-4-order` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r35-absolute-4-rank` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r35-macross-2-order` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r35-macross-2-rank` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r35-macross-4-order` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r35-macross-4-rank` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r35-passive-8-order` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |

The only window any card fails is `inv-2000` (round 22's curve matrix, not part of this round's
gate): `VWO`'s first bar is 2005-03-10 against a 1999 deadline.

**The run recipe.** Not executed as part of this pre-registration — the bar store is single-writer,
a full round takes hours, and another session may hold it (`run_round.sh` refuses to start if a
tournament process is already alive, and `WINDOWS.md`'s data-access rule is why).

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round35.py --write
bash strategy-program/tools/run_round.sh data/rounds/r35-2026-09/cards data/rounds/r35-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \
    --results data/rounds/r35-2026-09/results --json data/rounds/r35-2026-09/scorecard.json
```
