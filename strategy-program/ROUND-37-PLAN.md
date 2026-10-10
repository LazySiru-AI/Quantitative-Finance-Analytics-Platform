# Round 37 — the double Bollinger band, a volatility-band entry family from the corpus

Pre-registered **2026-09-09**, before any card in this round has been run and before any measurement
in it exists. Nothing below was written with sight of a result. **The round has not been run** — the
recipe is in §9 and it has deliberately not been executed.

Not investment advice. Every number this round will produce is a backtest on price-only daily bars
with no dividends, and the honest prior is in §8: the most likely outcome is that nothing separates.
This document is also not an endorsement of the trader whose idea it borrows, and §7 is explicit that
the round cannot evaluate his actual claim at all.

---

## 1. The question, and where it comes from

**On daily bars, does a band-within-band entry structure earn anything a single band does not?**

### 1a. The hypothesis is from this programme's own persona corpus, not from the author

This programme ingests investing YouTubers into persona notes at
`data/vault/influencers/<slug>/notes/*.md`, read through `app.personas.service.list_notes`. The
persona `creator-e` — display name **"Creator E"**, channel `@creator-e`, **20
notes** — repeatedly describes a system he calls **"Double B"**: two Bollinger Bands running at once.

Three notes, cited by their note ids, with quotations kept short:

| note id | what it establishes |
|---|---|
| `VIDEOID002` — *"The 1 Minute Scalping Strategy That Made Me $660,000 (Step by Step)"* (en) | The structure and the parameters. Its summary describes a system that "applies two separate Bollinger Bands (lengths 20 and 4) to capture breakout momentum", strictly inside the first two hours after a session open, with stops moved to break-even. |
| `-VIDEOID001` (ko, model-summarised) | The exact configuration and the claim. Its summary gives "the first with period 4, standard deviation 4, source set to open, colored red; the second with period 20, standard deviation 2, colored white", and reports a backtest of 1000+ signals over three years. He says of the pair: *"There are the only indicators I've used for over 10 years."* On the comparison this round is built around: *"Using a single bore band, the win \[rate\] was around 55%."* |
| `VIDEOID003` (ko, model-summarised; tickers NQ, GC, BTC) | The higher-timeframe rule that makes the outer band a *bias* rather than a second trigger: *"The signal must come from the band that matches the higher time frame direction."* |

Two further notes corroborate the sizing discipline rather than the structure: `3pLtQ_82nSM`
(*"bet only 1%, until your win rate and risk to reward are stable"*) and `sYxJX3WlsIY`
(*"I kept Just two Bollinger Bands Two moving averages and two simple lower indicators."*).

**The quotations above are auto-transcribed and machine-summarised**, and two of the three notes are
Korean-language sources summarised into English by a model (`summary_source: model`). They are quoted
as *what the corpus records the persona claiming*, which is all this round needs from them; they are
not quoted as measurements, and §7 says why none of his numbers is testable here.

### 1b. What the programme has already measured, and why this form is not in it

Rounds 17, 18 and 34 measured the eight rule forms in `app.evolution.ruleforms.RULE_SHAPES` —
`ma-crossover`, `momentum-state`, `rsi-pullback`, `band-reversion`, `channel-breakout`,
`band-breakout`, `macd-cross`, `vol-compression` — and found every marginal inside this programme's
**21.2 percentage point** noise floor. Round 34's report is the most recent: form marginal **4.21pp**,
regime-filter marginal **0.88pp**, whole-field spread **6.40pp**, minimum Benjamini–Hochberg
**q = 0.81** across sixteen cells.

The nearest existing form to this round's hypothesis is `band-breakout`, and it is a **single** band:

```
entry:  close crosses_above bb_upper(30, 2) and close > sma(200)
exit:   close crosses_below bb_mid(30, 2)
```

A **two-band regime-plus-trigger structure is a form none of those rounds contained**, and it is one
the evolution loop's template vocabulary cannot emit — `RULE_SHAPES` has no shape that reads one band
as a bias filter and a second, faster band as the trigger inside it. So the question round 37 can
honestly ask on daily bars is not "does Creator E's system work" (it cannot ask that: §7) but:
**against the programme's own trend-form family, does adding the second band buy anything?**

## 2. The field — a 3 × 2 × 2 factorial, 12 cells

Authored by `strategy-program/tools/round37.py`. Unlike round 34, the cards are **not** generated
from `app.evolution.ruleforms`: this entry structure does not exist in that vocabulary, which is the
whole reason for running it, so there is nothing to import. The three entry strings and two exit
strings are literals in that module, and every one of them is passed through the real
`app.rules.grammar.parse` at import time (`_validated`) so a typo cannot reach a card.

| factor | levels | why it is a factor |
|---|---|---|
| **entry structure** | 3 — `double`, `outer`, `inner` | the variable this round exists to isolate |
| **exit** | 2 — `midcross`, `innerfail` | which band is allowed to end the trade; round 18 measured the exit marginal on a different entry family and this replicates it here |
| **regime filter** | 2 — `close > sma(200)` on / off | rounds 17 and 34 both measured it inside the floor; carried as this field's cheapest control and a third-universe replication |

3 × 2 × 2 = **12 cells**, at `PROTOCOL.md`'s ≤ 12 ceiling for this round.

### 2a. The three entry structures, verbatim

| level | entry (regime arm `off`) |
|---|---|
| `double` | `close > bb_mid(20, 2) and close crosses_above bb_upper(4, 4)` |
| `outer` | `close crosses_above bb_upper(20, 2)` |
| `inner` | `close crosses_above bb_upper(4, 4)` |

`double` is the persona's structure translated to daily bars: the **outer** 20-period 2σ band's
midline as the trend bias, the **inner** 4-period 4σ band's upper edge as the trigger inside it. That
mapping is the one his own notes state — `VIDEOID003`'s higher-timeframe rule is what makes the
slower band a bias rather than a second trigger — but it is a *translation*, and §7 records it as one.

`outer` and `inner` are the two halves on their own, and **they are the reason the round is
interpretable**. Without them a result for `double` would be a statement about Bollinger bands in
general, not about the band-within-band structure. `outer` is also the closest thing this field has to
the programme's existing `band-breakout` form, at a 20-period instead of a 30-period band.

The regime arm `on` prepends `close > sma(200) and ` to whichever entry above. It is composed, not
surgically removed the way `round34.strip_regime` had to remove it, so the `off` arm is the literal
and the `on` arm is literal-plus-prefix; string surgery cannot produce a rule that parses but no
longer means what the round says it means.

The two exits:

| level | exit |
|---|---|
| `midcross` | `close crosses_below bb_mid(20, 2)` — the outer-band regime is lost |
| `innerfail` | `close < bb_lower(4, 4)` — the fast band's own failure |

### 2b. The universe, and why it is these twelve names

```
NVDA  TSM  MU  AMD  QCOM  MSFT  GOOGL  AMZN  NFLX  ORCL  INTC  TXN
```

This is `app.evolution.universe._TAXABLE_GROWTH` **verbatim and in its own write order** — the
twelve-name taxable growth pool the evolution loop already searches for `trading`-purpose candidates.

**The author did not pick it, and that is the point.** In a round about *form*, a thesis-picked
universe is the single most obvious confound, and "twelve names that suit a band strategy" would be
exactly that. Using the loop's own pool makes this a form the loop **cannot emit**, tested on names
the loop **already trades**, so a difference is attributable to the structure rather than to a roster
chosen after looking at returns. `tests/test_round37_field.py` asserts the pinned tuple equals
`_TAXABLE_GROWTH` today, so if that pool is edited by other work the divergence is a loud test failure
rather than a silent drift; the tuple is *copied* rather than imported because a frozen field whose
universe can be rewritten by an edit elsewhere is not frozen (`PROTOCOL.md` §2).

**Every main window is eligible, and that was checked rather than reasoned about.** The binding symbol
is `GOOGL` at first bar **2004-08-19**, comfortably before every main window's deadline for a 200-day
indicator. Verified with `strategy-program/tools/windows.py --cards data/rounds/r37-2026-09/cards`
**before the field was frozen**: **12 of 12 cards report `8/8 main_ok PASS`**. Round 17's Amendment 1
is why that check is run and not argued: there, two young ETFs did not merely contribute nothing to a
window, they failed the whole card, and the round lost three windows to it.

**One auxiliary window is ineligible for all twelve cells, and it is not a problem.** Every cell fails
`inv-2000` (`GOOGL` first bar 2004-08-19 against a deadline of 1998-12-20 for the regime-on arm and
1999-09-07 for regime-off). `inv-2000` is an investor-horizon window outside the main matrix and
counts toward no gate; the failure is identical across all twelve cells so it cannot favour a level.
**`inv-2006` is eligible here**, unlike round 34's field. Every other auxiliary window (`oil-2014`,
`volmageddon-2018`, `taper-2013`, `recovery-2009`, `inflation-2021`, `banks-2023`, `13f-legal`, the
horizon rungs and the live matrix) is eligible for all twelve.

### 2c. Held identical across all 12 cells, and the free-parameter count

| held fixed | value | provenance — none of these was chosen by looking at an outcome |
|---|---|---|
| universe | the twelve above | `_TAXABLE_GROWTH`, identical order in every cell |
| outer band | 20 period, 2σ | the persona's own published number (`-VIDEOID001`) |
| inner band | 4 period, 4σ | the persona's own published number (`-VIDEOID001`) |
| regime period | 200 | rounds 17/18/34's regime period, unchanged so the marginal is comparable |
| `stop_loss_pct` | 0.12 | round 17's **middle** bracket level |
| `take_profit_pct` | none | §2d |
| `max_hold_days` | **150** | §2e — a mandate constraint, not a tuned parameter |
| `max_positions` | 4 | round 34's sizing |
| `position_pct` | 0.20 | round 34's sizing; 4 × 0.20 = 0.80 maximum commitment |
| `designed_through` | 2026-02-13 (`DESIGN_THROUGH`) | |
| `rank_by` | unset | as every card this programme has published |
| `discipline` | `breakout` | all three structures fire on price clearing an upper band edge |
| `purpose` | `trading` | §3 |

**Free numbers per card (`PROTOCOL.md` §3 rule 3, budget 10).** Counted as *choices*: outer period 20,
outer σ 2, inner period 4, inner σ 4, regime period 200, stop 0.12, hold cap 150, slots 4, position
0.20 = **9**. Counted as *distinct numeric literals* (the strict reading
`tests/test_round37_field.py::TestParameterBudget` enforces, in which the inner band's 4 and the slot
count's 4 are one token), the worst cell spends **7**. Both readings are inside the budget and both
are reported so a reader does not have to pick one for us.

**Nothing in this field was tuned and no grid was searched to arrive at it.** The two band
configurations are quoted from the corpus; 200, 0.12 and 4 × 0.20 are inherited from published rounds;
150 is a mandate ceiling. If the round returns a null it is not because a parameter was left at a bad
setting — it is because none of these settings was ever *chosen*, which is the property that makes the
result a measurement rather than a search result.

### 2d. Why there is no bracket factor

Round 17 measured `none`, `stop` and `stop-tp` as differing by **0.14pp** across its whole 48-cell
field, with many cells byte-identical between bracket policies because the rule's own exit fires
first almost every time. Carrying that factor here would spend three times the runtime on a contrast
already **published** as empty, and would triple the Benjamini–Hochberg denominator every surviving
cell has to pay for under `PROTOCOL.md` §3 rule 8.

This is a decision taken from a published result **before any round-37 card exists**, not a mid-round
narrowing — the identical move `ROUND-18-PLAN.md` §2 and `ROUND-34-PLAN.md` §2a both made, from the
same finding, for the same reason. The surviving level is `stop`, round 17's own middle level; picking
round 17's *best* bracket level would be selecting on an outcome.

### 2e. Why the hold cap is 150 and not round 17's 180

`StrategyCard.max_hold_days` counts **sessions** (`app.tournament.runner._decide_exit`), so 180
sessions is roughly **8.6 calendar months**. The `trading` mandate is bounded at **nine months**
(`PurposeSpec.horizon_months_max`) — and that bound has already been moved once *because* 180-session
cards breached it: round 24 found `B3-concentrated` and `B-momentum` could not honour the six-month
bound then in force, and the owner widened the bound rather than capping the cards. A new round should
not be the reason it moves again. **150 sessions is ~7.1 calendar months**, inside the mandate with
room rather than at its edge. `tests/test_round37_field.py::TestMandate` reads the bound off
`purpose_spec(TRADING)` rather than restating it, so the check cannot rot when the bound next moves.

## 3. Purpose, the mandate, and the disjointness constraint — which runs the *other* way here

Every card carries **`purpose = Purpose.TRADING`** (`$60,000` lump sum, taxable, benchmark SPY,
nine-month horizon bound). That has three consequences this document states rather than leaves to be
discovered.

**(a) Nothing is at stake.** `PROTOCOL.md` §9's **r21 amendment removes the `trading` purpose from
§6's promotion rule entirely**, and deliberately builds no replacement gate: at a horizon this short
the per-window sampling error is ~20× a ten-year window's, and a gate known in advance to lack
discriminating power would launder noise into the library. The medians this round produces are
**reported and never promoted on**, the same posture §4 already takes toward q-values. This is a
measurement study like rounds 15, 16, 17, 18 and 34. **No card here is a proposal to trade anything
and none will be seated.**

**(b) The disjointness check is the mirror image of round 34's, and copying round 34's would have been
vacuous.** `find_disjointness_violations` compares every `roth` card against every `savings`/`trading`
card, and reports the Roth card as `roth_agent_id` and the taxable card as `other_agent_id`. Round 34
authored **Roth** cards and filtered on `roth_agent_id`. These are **trading** cards: they can only
ever appear as `other_agent_id`, so round 34's filter transplanted here would match nothing and would
report a clean field however badly it collided. `round37.check_disjointness` filters on
`other_agent_id`, `round37.roth_symbols` computes the **Roth** roster (not the taxable one) from the
live library at build time across all six tiers, and `--write` refuses on any violation naming one of
its own cards. `tests/test_round37_field.py` plants a Roth ticker in a trading card to prove the guard
fires, **and** asserts that the wrong-direction filter would have been vacuous, so the bug cannot be
reintroduced by a copy-paste and go unnoticed.

At authoring time the check reported **62 purposed cards in the library, 21 distinct Roth symbols, and
no overlap**. The Roth roster it computed is `AAPL ADBE AMAT BND CRM CSCO IGV INTU ITA KLAC LRCX SSO
VIG VNQ VUG XBI XHB XME XOP XRT XSD`. It is recomputed on every run, never hardcoded: the library is
edited concurrently by other work in this programme and a pinned list would pass this check against a
book that no longer exists.

**Ticker disjointness is necessary, not sufficient**, and nothing here is a §1091 opinion. IRC §1091
turns on *substantially identical securities*, not on symbols. Rev. Rul. 2008-5 is why the direction
matters at all: a taxable loss replaced inside an IRA within 30 days is **disallowed outright**, with
no basis adjustment anywhere.

**(c) All twelve of this round's names are already traded by existing taxable cards, and that is
allowed but must be read correctly.** Measured at authoring time, every one of `NVDA TSM MU AMD QCOM
MSFT GOOGL AMZN NFLX ORCL INTC TXN` appears in the universe of at least one seated or archived
`savings`/`trading` card — `NVDA` in twenty-three of them, including `B-momentum` and `C-trend`, the
two cards the owner set as primaries. The disjointness invariant binds only between `roth` and the
taxable purposes, so this is not a violation of anything. What it does mean is that **round 37's cells
are not exploring new ground at the ticker level**; they are a new *rule form* over names the taxable
book already has heavy exposure to. Any reading of a positive cell as a diversifying addition would be
wrong, and §7 repeats it.

## 4. Windows and metric

The standard eight-window matrix, run serially by `strategy-program/tools/run_round.sh`: `q4-2018`,
`covid`, `bear-2022`, `chop-2015`, `chop-2011`, `bull-2024`, `recent`, `gfc`. The `13f-legal` window
is card-filtered to cards this round does not contain and will not run.

Ranked on `median_adjusted_excess`, where `adjusted_excess = total_return − (capital_exposure ×
benchmark_return)` — `score.py`'s primary metric, so a structure that is simply invested more often is
not credited for the market's return. That correction matters more here than in most rounds: the
`inner` entry is expected to be invested far more of the time than `outer` (§6, prediction 2), and raw
return would reward it for exactly that. `worst_adjusted_excess`, `hit_rate` and the window IQR are
reported beside the median per `PROTOCOL.md` §4, because this programme has repeatedly found the
median and the worst disagree. Scored with `--pin-store`.

**The benchmark is SPY, in every window** — `purpose_spec(TRADING).benchmark`, not a choice this round
makes. §7 names it as a caveat: twelve large-cap tech names against a cap-weighted large-cap blend
index is a comparison with a sector factor mixed into every cell identically.

## 5. The decision rule, pre-registered

Stated before any number exists.

**The noise floor is 21.2 percentage points.** One identical card re-run under twelve `universe`
orderings moved its three-year return across a 53.9-point spread, σ = 21.2
(`backend/app/paper/library/README.md`, study at `docs/tournament/results/a07-order/`).

### The primary contrast

**"The two-band structure matters" requires all three of the following, together:**

1. the `double` marginal exceeds the `outer` marginal by **more than 21.2pp** (marginals, not cells:
   each is the mean of its four cells across the exit and regime factors), **and**
2. the difference has the **same sign in at least five of the eight main windows** — the same
   five-of-eight proportion the regime gate uses, and the reason a single-window blowout cannot carry
   the contrast, **and**
3. the contrast **survives Benjamini–Hochberg at q < 0.10 with a denominator of every cell run in this
   round** — all **12**, not the three entry marginals and not a surviving subgroup. `PROTOCOL.md` §3
   rule 8 is explicit and this programme has made the subgroup error once already.

**Anything less is the null**, and will be reported as the band-within-band structure adding nothing
measurable at daily frequency — one more instance of the record rounds 17, 18 and 34 established.

### Why 21.2pp is the bar, and why it is generous to the alternative

Three readings of what pure noise would produce here, all reported, none of them cherry-picked after
the fact:

- **The 12-cell spread.** E[max − min] ≈ 3.336σ over 12 standard draws. At σ = 21.2 that is
  **70.7pp** — so a 12-cell max−min spread below 70.7pp is consistent with having drawn the numbers
  from noise, and the best single cell is therefore **not a finding** under any circumstances.
- **The three entry marginals, conservative σ.** E[max − min] ≈ 1.693σ over 3 draws → **35.9pp**.
- **The three entry marginals, credited for averaging four cells each** (σ → 21.2/√4 = 10.6):
  **17.9pp**, and a pre-specified pairwise contrast between two such marginals needs
  |diff| > 1.96 × 10.6 × √2 = **29.4pp**.

The bar in condition 1 is **21.2pp**, which is *below* two of those three readings and above only the
most averaging-credited one. That is deliberate and it is stated in advance: this programme's
accumulated record is a null, so the alternative is given the **most generous** of the defensible bars
rather than the strictest. If a form cannot clear even the easy bar, the null is a strong one. All
three readings will be reported beside the result.

### Secondary marginals, reported and not promoted on

The **exit** marginal (`midcross` vs `innerfail`, six cells each) and the **regime** marginal (on vs
off, six cells each) are reported against the same 21.2pp floor. Neither is this round's primary
question; both are replications of published findings (round 18's exit null, round 17/34's regime
null) on a third universe.

### The reproduction check, and the honest answer about it

`ROUND-18-PLAN.md` §2 could regression-check its instrument because two of its cells reproduced round
17 designs exactly. **This round has no such cell: zero of the twelve reproduce a frozen round-17,
round-18 or round-34 design.** The nearest, `outer` + `midcross` + regime-on, differs from
`r17-band-breakout-on-stop` in band period (20 vs 30), universe (twelve tech names vs nine sector
SPDRs) and sizing (4 × 0.20 vs 6 × 0.15). That is a real loss and it is not papered over;
`tests/test_round37_field.py::TestNoCellReproducesAFrozenDesign` checks the claim against the frozen
card files on disk rather than leaving it as prose.

**The replacement, pre-registered here: before scoring round 37, re-run the frozen card
`data/rounds/r17-2026-08/cards/r17-ma-crossover-on-stop.json` against the same store and check it
reproduces round 17's committed figures to the digit.** If it does not, the instrument moved and every
comparison in this document is suspect. Round 34 ran exactly this check and its output is in
`data/rounds/r34-2026-09/repro-r17/` — that is the tool and the precedent to reuse.

## 6. Falsifiable predictions

Fixed before any run, so this document can be wrong.

1. **The `double` − `outer` marginal will be inside 21.2pp**, and the null will stand. If it is not —
   and condition 3's BH correction also holds — a band-within-band structure earns something a single
   band does not, which would be the first form-level finding in this programme's history and would
   say the loop's `RULE_SHAPES` vocabulary is the binding constraint rather than the universe.
2. **`inner` will take the most trades of the three structures and post the worst hit rate.** A
   4-period band re-forms around price within a week, so an unfiltered break of its 4σ edge should
   fire far more often than a 20-period 2σ break; and firing more often on a noisier trigger should
   cost win rate. This is the prediction most likely to be refuted by the *opposite* mechanism: a 4σ
   band is very wide relative to a 4-bar standard deviation, so the trigger may prove rarer, not
   commoner, than the outer band's. Either outcome is informative and both are stated now.
3. **The regime filter will cut capital exposure by more than 10 percentage points while moving the
   median by less than 21.2pp** — round 34's finding ("the 200-day filter is a position sizer that
   happens to be spelled as an entry condition": `on` held 26% of capital, `off` 41%, for 0.88pp of
   median) replicating on a third universe. Both halves must hold; if exposure moves less than 10pp
   the mechanism this predicts is not the one operating.
4. **The failure regime splits by band speed.** The fast-trigger cells (`inner`, and `double` whose
   trigger is also the 4-period band) will post their worst adjusted excess in **`bull-2024`** — round
   34 §4 found seven of sixteen cells lost most in that window, a +14% year with a −19% air pocket in
   it, and named "V-shaped correction inside an up-year" as a failure regime the programme's
   vocabulary was missing. The slow-trigger cells (`outer`) will post their worst in **`chop-2011`** or
   **`chop-2015`**, the classic breakout-in-a-directionless-market failure. Each card carries its own
   form-specific version of this in its `falsification` field, per `PROTOCOL.md` §3 rule 5.
5. **The exit marginal will be inside 21.2pp**, replicating round 18's null. But `innerfail` will hold
   materially shorter than `midcross` — if the two exits do not differ in mean holding period, the
   exit factor measured nothing on daily bars and that must be reported as an instrument finding
   rather than as a null.
6. **All 12 cells will produce a scored result in 8 of 8 main windows.** Eligibility was already
   checked against the store before freezing (§2b, 12 of 12 at `8/8 PASS`), so this is the stronger
   claim that the runner also *completes* every one. A shortfall is to be reconciled against the
   runner's `FAILED` lines (§9) and recorded as an instrument surprise, never absorbed silently.

## 7. What this round cannot settle

Named here so the report cannot quietly overclaim. The first item is the largest and it is not a
technicality.

- **The persona's actual claim is intraday and this round does not test it.** His system runs on
  1-minute and 2-minute candles, inside the first two hours after the Asian, European or US session
  opens (`VIDEOID002`). This programme's engine has daily bars and nothing else. **A null here is not
  evidence against his system**, and a positive result here would not be evidence for it. What is
  tested is whether the *band-within-band structure* survives translation to a timeframe roughly 400×
  slower. That is a question worth asking about the structure; it is not his question.
- **His reported win rates cannot be checked and are not being checked.** `-VIDEOID001` reports 78%
  against 55% for a single band, from a private backtest of 1000+ signals. This round produces no
  evidence about that comparison at his timeframe, on his instruments (NQ, GC, BTC), with his sizing.
- **The 1%-risk sizing and the break-even stop are not modelled.** He sizes each trade to risk ~1% of
  the account and moves the stop to break-even once a trade works (`3pLtQ_82nSM`, `VIDEOID002`). This
  engine sizes a fixed 20% of starting equity per slot and carries a fixed 12% stop that never moves.
  Those are different strategies in the part he says matters most.
- **The inner band's `source = open` is not modelled.** His note specifies the fast band is computed on
  the *open*; `app.indicators.volatility.bollinger` builds all three bands on the close. `bb_upper(4,
  4)` here is therefore not exactly the band he draws even at his own timeframe.
- **His three execution scenarios collapse to one.** `VIDEOID002` describes initial breakout,
  re-breakout after a stop-out, and full trend reversal. Only the first has an expression in this DSL.
- **Price-only, dividend-free bars.** No absolute number in this round is a return anyone could have
  earned. Every cell holds the same names, so it cannot favour a level.
- **The universe is not survivorship-free, and this is a real weakness.** These are twelve large-cap
  technology names that exist and are large *today*; `_TAXABLE_GROWTH`'s own docstring records that
  two members were swapped out for having too little history. Whatever a rule earns on them is earned
  on the survivors of a two-decade selection this programme does not measure. Round 34's universe was
  free of *stock*-level survivorship (mechanically-defined ETFs); this one is not, and that is a step
  backwards on an axis round 34 was careful about. It is accepted here because the universe's
  provenance — the loop's own pool — is what makes the *form* comparison clean, and the form comparison
  is this round's question. Both facts are true at once and the report must carry both.
- **SPY as the benchmark for twelve large-cap tech names.** `purpose_spec(TRADING)` says SPY and this
  round does not relitigate it. A common sector/size factor is mixed into every cell's excess
  identically; it cannot favour a level, but "excess over SPY" is not "excess over the thing these
  names actually are".
- **These names are already heavily held by the taxable book** (§3c), so no cell here can be read as a
  diversifying addition even if it posted a positive median.
- **The ordering-noise floor on this universe is unmeasured**, and §2c's four-of-twelve slot cap binds
  harder than any previous round in this family while `rank_by` is unset — so this field carries *more*
  ordering exposure, not less. The 21.2pp floor is not lowered on the strength of round 17's ~1pp
  ordering replication, which was measured on a different universe under a softer cap.
- **It cannot promote anything.** §3a: the `trading` purpose has no promotion rule.
- **It settles nothing about tax.** §3b's disjointness is a necessary condition, checked; it is not a
  §1091 opinion and this round produces no evidence about wash sales, basis, or the taxable book.

## 8. The honest prior

The likeliest outcome is that **nothing separates beyond noise**. The accumulated record of rounds
1–34 is that no durable edge has been found: round 33 measured one positive edge in 9,480 cells and
its promoted branch then failed BH correction and out-of-sample; round 34's whole 16-cell field spanned
6.40pp with a minimum q of 0.81. A new round should have to argue against that record, not the reverse,
and this one does not expect to.

What makes it worth running anyway is that the record has a specific hole in it. Every form this
programme has measured came from one vocabulary — `app.evolution.ruleforms.RULE_SHAPES`, eight shapes
written on 2026-08-26 — and round 34's own conclusion was that **"the forms are the bottleneck, not the
universe"**. That conclusion is only as strong as the range of forms tested. A structure the vocabulary
cannot express, taken from outside the programme entirely and translated without tuning, is the
cheapest available test of whether the bottleneck is *forms* or is *that particular list of eight
forms*. A null here narrows the hole; the alternative, if it survived §5's three conditions, would be
the first form-level finding this programme has produced.

The result that would genuinely change direction is prediction 1 failing **together with** §5's
conditions 2 and 3. Prediction 1 failing on its own is one more max-of-twelve.

## 9. Determinism, scope and the run recipe

`build()` is deterministic: `ENTRIES`, `EXITS` and `REGIME_ARMS` are fixed and ordered, and nothing in
the tool reads a clock, a random source, the bar store or the filesystem. Two calls produce identical
model dumps, which `tests/test_round37_field.py::TestDeterminism` asserts.

**The round has NOT been run.** The bar store is single-writer, a full matrix takes hours, and another
session may hold it. The recipe, to be executed by whoever runs the round:

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round37.py --write
bash strategy-program/tools/run_round.sh data/rounds/r37-2026-09/cards data/rounds/r37-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \
    --results data/rounds/r37-2026-09/results --json data/rounds/r37-2026-09/scorecard.json
```

Before scoring, run §5's external reproduction check on `r17-ma-crossover-on-stop` (round 34's
`repro-r17/` is the worked precedent), and reconcile the run files against the runner's `FAILED` lines
for every window per `PROTOCOL.md` §8 — the runner walks past a failed card by design, so a shortfall
is silent and a contended round produces a report that looks complete.

**Note on `strategy-program/tools/disjoint_field.py`.** That tool is built for the *Roth* sector family
and will `FAIL` on this field's check 1 (`purpose='trading', expected 'roth'`), twelve times, by
design. Its check 2 has two halves and they are not equally meaningful here: the direct-intersection
half **skips non-Roth field cards entirely** (`check_taxable_overlap`), so its "0 offending lines" for
this field is structurally vacuous and must not be quoted as evidence; the
`find_disjointness_violations` half runs over library-plus-field including the library's Roth cards, so
its 0 **is** a valid independent confirmation of §3b. The authoritative check for this round is
`round37.py`'s own build-time refusal.

**Files this round owns:** this document, `strategy-program/tools/round37.py`,
`data/rounds/r37-2026-09/cards/*.json` and `tests/test_round37_field.py`. Nothing else.
