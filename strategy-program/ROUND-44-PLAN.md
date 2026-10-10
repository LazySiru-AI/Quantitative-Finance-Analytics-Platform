# Round 44 — do the personas' thematic baskets beat a passive control, and does trimming the winner
# beat holding it?

**Pre-registered 2026-09-09, before any card in this round has been run. Nothing below was written
with sight of a result. As of this writing `data/rounds/r44-2026-09/cards/` holds no card, there is
no `data/rounds/r44-2026-09/results/` and no scorecard.**

**Not investment advice.** Every number this round will produce is a backtest on price-only bars with
no dividends, measured against SPY for a Roth book that holds neither SPY nor anything cap-weighted
large-cap-growth. No influencer named below is endorsed; these are tests of the *cheapest expressible
portfolio proxy* for something a persona said, not of the person or the claim as they intended it.

---

## 1. The question, and why it is not a re-run of anything

Two axes, one decision each, on the same ten-basket field so the multiple-comparison denominator is
shared and stated once:

1. **BASKET.** Do the personas' thematic baskets — power infrastructure, defense, semiconductor
   capex, and a rotation-flavoured "real assets" sleeve — held **passively**, beat a broad,
   style-neutral passive control?
2. **RULE.** Does Creator B's profit-trim — step out of a name when it is extended above its
   200-day mean, step back in when it is not — beat holding the same basket passively?

**Neither has been tested before.** Rounds 34, 35, 36 and 39 (`DISJOINT-SECTOR-FAMILY.md` §5a,
`ROUND-39-PLAN.md`) varied the **rotation mechanism** — rule form, slot cap, fill order, and the
value/growth/equal-weight/mid-cap style axis — always through some kind of *timing rule* applied to a
basket, and round 39 additionally measured a style tilt passively. **No round in this programme has
ever measured a *named thematic basket*, held passively, against a passive control.** Round 39 found
the timing rule loses to simply holding the slice in every one of its four slices (`ma − passive`:
value +0.93pp, growth −5.36pp, core −3.45pp, full −2.28pp — REPORT.md §2); that is the direct
argument for testing the basket construction itself rather than another rule wrapped around it, which
is exactly what axis 1 does. Axis 2 is new in a different way: every prior round's timing rule was a
regime *switch* (in the market or out, `close > sma(200)`); the trim rule tested here is a
*within-basket reallocation* — never fully out, only stepping between an extended name and cash on
that one name — which is a materially different mechanism from anything rounds 17, 18, 34–36 or 39
tested.

**Where the hypothesis comes from** (`PERSONA-DISCUSSION-2026-09-09.md` §3, §4; verbatim quotes,
≤15 words, attributed):

- Creator A, asked for a Roth basket: "power generation infrastructure as the bottleneck constraining
  AI expansion" and named defense capabilities acceleration and "semiconductor competition
  post-Stargate" as the other two candidate pillars.
- Creator D, roth: "memory semiconductor demand from large AI models" and "electricity infrastructure
  beneficiaries from data center migration" as the sector theses in her stated method.
- Creator C, roth: "The semiconductor super-cycle I track is structural" and, asked what a basket
  would hold, "semiconductors (SOXX), Korean equities (EWY), rare earths (UUUU)".
- Creator B (`creator-b`), trading: "trim on weakness to lock profits, exit immediately when thesis
  rationale breaks" — the only persona in the discussion to offer a *rule*, not just a basket.
  `PERSONA-HYPOTHESES.md` §3 independently records the same discipline from the ingested note corpus:
  "Trim after 'exceptional gains'" (mechanism: "Systematic profit-taking discipline after a large
  run-up in an overheated sector"). His roth answer names the destination assets: "EWZ (emerging
  markets), TSM (semiconductor supply-chain infrastructure), IYR... and an energy ETF" as the
  dollar-weakness/EM/energy/pension-support thesis's portfolio expression.
- `PERSONA-DISCUSSION-2026-09-09.md` §4's own triage row makes the disposition explicit: "as passive
  baskets, yes [expressible] ... no — r34/35/39 tested rotation *rules* and a style axis, never
  whether a named thematic basket held passively beats a broad passive control" → **Round 44
  baskets**; and "a price-extension trim is expressible: exit when `close > sma(200) * 1.15` ... no —
  r39 tested a regime *switch*, never a trim-the-winner exit on a held basket" → **Round 44 rule
  arm**.

**What this is not.** Creator A and Creator D both explicitly declined to state a mechanical rule
("That's not a 'rule' you can backtest against daily bars", Creator A; "I haven't documented those
with video citations", Creator D) and Creator C called his own thematic pillars "still a trading
thesis, not a 10-year conviction". None of the four baskets below is a literal transcription of any
one persona's named tickers — `creator-b`'s own roth answer named `EWZ`/`TSM`/`IYR`, not the
`realassets` basket's `XOP`/`XME`/`EWY`/`VWO`, because the literal names either fail the GFC
eligibility gate, are already claimed inside this round's own field or the disjoint family, or (`TSM`)
sit inside the semicap basket already. Every basket here is this programme's own construction, built
to the theme a persona named and to the eligibility and disjointness rules below — a proxy for the
theme, not a replica of any one person's portfolio, exactly as `ROUND-39-PLAN.md` §2a states of its
own value/growth proxy.

## 2. The universe, pinned before anything was measured

**Twenty names, five baskets of four.** First stored daily bars (`app.market.store.read_frame`, live
store, measured 2026-09-09) — every one clears the `gfc` window's 2007-10-09 start by more than a
year, most by decades:

| basket | names | first bars |
|---|---|---|
| `power` | `NEE DUK SO CCJ` | 1973-02-21, 1980-03-17, 1981-12-31, 1996-03-14 |
| `defense` | `LMT NOC GD RTX` | 1970-01-02, 1981-12-31, 1970-01-02, 1970-01-02 |
| `semicap` | `AMAT KLAC LRCX ASML` | 1980-03-17, 1980-10-08, 1984-05-04, 1995-03-15 |
| `realassets` | `XOP XME EWY VWO` | 2006-06-22, 2006-06-22, 2000-05-12, 2005-03-10 |
| `control` | `VTV SPYG RSP MDY` | 2004-01-30, 2000-10-02, 2003-05-01, 1995-05-04 |

`XOP`/`XME` (2006-06-22) are the binding pair — a little over a year before `gfc`'s 2007-10-09 start,
enough room for a 200-day indicator to warm inside the eligibility window the way `windows.py`
computes it. All twenty names are eligible in **8 of 8** main windows (verified in §8, not asserted
here).

**What each basket is, and what it is not.** `power` is Creator A's and Creator D's electricity/AI-
power-bottleneck thesis, expressed as two regulated utilities, one merchant/renewable utility and one
uranium miner — a proxy for "the grid and its fuel", not a literal transcription of either persona's
named tickers, neither of whom stated any. `defense` is Creator A's defense-spending pillar, the four
largest US pure-play defense primes. `semicap` is Creator C's and Creator D's semiconductor
super-cycle/memory-demand thesis, expressed as the three largest US semiconductor-capital-equipment
makers plus the sector's other most-cited super-cycle name (`ASML`) rather than `SOXX` itself, because
`SOXX` and `EWY` are already the literal instruments named in Creator C's own answer and both fail
elsewhere in this design: `SOXX` launched 2011 (fails `gfc`) and `EWY` is used instead as the
`realassets` basket's Korea sleeve, so putting it in `semicap` too would break basket disjointness.
`realassets` is `creator-b`'s and Creator C's EM/commodity/energy/Korea rotation thesis, expressed as
two energy-sector SPDRs, one Korea-country ETF and one broad emerging-markets ETF — again a proxy for
the *rotation destination*, not `creator-b`'s own named `EWZ`/`TSM`/`IYR`. `control` is round 39's own
`value`+`growth` pool collapsed to one four-name broad, style-neutral basket (Vanguard Value, the
S&P 500's growth half, the S&P 500 equal-weighted, and the S&P MidCap 400) — deliberately the same
instruments round 39 already measured as null against each other, so this round's control is not a
new object the field has to trust for the first time.

### 2a. Disjointness — the taxable book, and legal overlap with other roth cards

**Zero of the twenty names is claimed by any `savings`- or `trading`-purpose card.** Recomputed live
2026-09-09 through `app.evolution.promotion._library_cards` (all six library tiers, the same function
`round39.py`/`round40.py` use and the application itself uses at promotion time) against the current
84-ticker taxable set: `set(TRADED) & taxable == set()`.

**Five names are already claimed by *other roth-purpose cards* — legal, and disclosed rather than
hidden.** `AMAT`, `KLAC`, `LRCX` are held by roughly twenty of the evolution loop's own roth genome
cards (`g16xx`.../`g18xx`... agent ids); `XOP`, `XME` are held by `r34-ma-crossover-on`, the disjoint-
sector family's directed candidate. `app.tournament.purposes.find_disjointness_violations` only ever
compares a roth card against the *taxable* universe (`ROUND-39-PLAN.md` §2, confirmed again here) —
roth-to-roth overlap creates no wash-sale exposure under Rev. Rul. 2008-5, because nothing is ever
sold at a loss and repurchased *inside the taxable book*; two Roth accounts (or a Roth and the
evolution loop's own genome population, which trades nothing live) holding the same name is not the
failure mode §1091/Rev. Rul. 2008-5 addresses at all. Both checks — a direct set intersection against
the taxable-only ticker set, and `find_disjointness_violations` over the combined field — are run by
`round44.py` and by `disjoint_field.py` (§8), and both are expected to report zero taxable offenders
while the roth-roth overlap above is real and unflagged, because it is not a violation.

**Ticker disjointness is necessary, not sufficient, under IRC §1091** — restated exactly as
`ROUND-39-PLAN.md` and `disjoint_field.py`'s own docstring state it. This round establishes that no
name it trades is ever repurchased inside the taxable book; it says nothing about whether any of these
twenty names is *substantially identical* to something the taxable book already holds (none obviously
is — no leveraged/unleveraged pair, no share-class pair, no two funds on the same physical commodity
appear in this field), and that remains a question for a tax adviser, not this document.

## 3. The field — 5 baskets × 2 arms = 10 cells

**The two arms**, applied identically across every basket:

```
passive:  entry "close > 0"   exit "close < 0"    (round 39's control expressions, character for
                                                     character — both already passed
                                                     app.backtest.guards.check on real bars in round 35)
trim:     entry "close < sma(200) * 1.15"
          exit  "close > sma(200) * 1.15"
```

Both arms: `max_positions = 4`, `position_pct = 0.25` (100% of capital deployed when fully invested —
every basket is the same size, so unlike round 39 there is no fractional-budget normalisation to do),
`rank_by = None` (a slot for every name, so there is no slot contention and the §7 ordering artifact
cannot operate here), no stop, no target, no time stop on either arm. `discipline`: `passive` is
labelled `trend`, the same forced least-wrong label round 39's controls carry (`ruleforms.classify`
returns `None` for a rule with no indicator, and `Discipline` has no member meaning "passive"); `trim`
is labelled `risk-managed` — not forced, a genuine fit: the rule is a profit-taking/exposure-reduction
discipline applied to a held position, not a directional entry signal, which is exactly what
`Discipline.RISK_MANAGED`'s docstring describes.

**`1.15` is a round-number threshold, not an outcome read.** It was chosen so the rule is reachable
in every basket, and the choice is disclosed as a **support-of-regressor** read: the fraction of
sessions between each name's first bar and `DESIGN_THROUGH` on which `close > sma(200) * 1.15` is
true, measured 2026-09-09 and re-measured in the tool's own dry run (§3a) before any card was written.
`round44.py --write` **refuses to write** if any name's extended condition (`close > sma(200) * 1.15`)
fires zero times over its own history — the `bb_upper(4,4)` defect round 40 built its own reachability
gate around, so this round reuses that gate rather than re-inventing a weaker one.

**One rule, one basis-point-level threshold, applied uniformly.** No grid search: `1.15` is the only
threshold in the field, chosen once, before any figure below existed, and applied identically to
every basket regardless of that basket's own measured support — the RSI-pullback-style temptation to
tune the threshold per basket to hit a target retention was available and not taken.

### 3a. The support/reachability table — re-measured, printed by the tool, none fire zero times

Measured by `round44.py`'s dry run through `app.market.store.read_frame` (in-memory, no file lock) and
`app.rules.evaluate.evaluate` on `app.rules.grammar.parse("close > sma(200) * 1.15")` — the real DSL
evaluator, bounded to `DESIGN_THROUGH`, the identical method `round40.py`'s reachability probe uses:

| symbol | first bar | sessions | extended fires | support |
|---|---|---:|---:|---:|
| `NEE` | 1973-02-21 | 13,359 | 986 | 7.4% |
| `DUK` | 1980-03-17 | 11,573 | 530 | 4.6% |
| `SO` | 1981-12-31 | 11,120 | 426 | 3.8% |
| `CCJ` | 1996-03-14 | 7,529 | 2,149 | 28.5% |
| `LMT` | 1970-01-02 | 14,150 | 2,742 | 19.4% |
| `NOC` | 1981-12-31 | 11,120 | 2,082 | 18.7% |
| `GD` | 1970-01-02 | 14,151 | 3,180 | 22.5% |
| `RTX` | 1970-01-02 | 14,151 | 2,545 | 18.0% |
| `AMAT` | 1980-03-17 | 11,573 | 3,925 | 33.9% |
| `KLAC` | 1980-10-08 | 11,430 | 3,808 | 33.3% |
| `LRCX` | 1984-05-04 | 10,527 | 3,907 | 37.1% |
| `ASML` | 1995-03-15 | 7,782 | 2,667 | 34.3% |
| `XOP` | 2006-06-22 | 4,943 | 807 | 16.3% |
| `XME` | 2006-06-22 | 4,943 | 1,118 | 22.6% |
| `EWY` | 2000-05-12 | 6,478 | 1,274 | 19.7% |
| `VWO` | 2005-03-10 | 5,267 | 477 | 9.1% |
| `VTV` | 2004-01-30 | 5,546 | 157 | 2.8% |
| `SPYG` | 2000-10-02 | 6,380 | 329 | 5.2% |
| `RSP` | 2003-05-01 | 5,735 | 320 | 5.6% |
| `MDY` | 1995-05-04 | 7,747 | 519 | 6.7% |

Every value is within rounding of the brief's own pinned figures (NEE 7%, DUK 5%, SO 4%, CCJ 29%,
LMT 19%, NOC 19%, GD 22%, RTX 18%, AMAT 34%, KLAC 33%, LRCX 37%, ASML 34%, XOP 16%, XME 23%, EWY 20%,
VWO 9%, VTV 3%, SPYG 5%, RSP 6%, MDY 7%) — the small deltas are sessions-vs-trading-days rounding, not
a disagreement about the store. **Minimum support in the field is `SO` at 3.8% (426 sessions) — never
zero, so the round is not refused.** `SO`, `VTV` and `DUK` are the thinnest — power and control are the
two baskets where the trim arm will trade least, and `LRCX`/`semicap` the thickest, which is the basis
for the exposure prediction in §5.

### 3b. Free-parameter budget (`PROTOCOL.md` §3 rule 3 — ten per card)

Same derivation `round39.py`/`round40.py` use — distinct numeric values across `entry`/`exit`/
`rank_by`, plus one per present bracket, plus two for `max_positions`/`position_pct`:

| cell | free numbers |
|---|---|
| `r44-<basket>-passive` (5 cells) | **3** — `{0}` + slot count + position size |
| `r44-<basket>-trim` (5 cells) | **4** — `{200, 1.15}` + slot count + position size |

Maximum 4, well under the constitutional bound of 10.

## 4. Windows, metric, decision rule

**Windows.** The standard eight-window matrix: `q4-2018`, `covid`, `bear-2022`, `chop-2015`,
`chop-2011`, `bull-2024`, `recent`, `gfc`. All ten cards are eligible in 8 of 8 (verified in §8).

**Metric.** `PROTOCOL.md` §4's primary key, median `adjusted_excess` across a card's eligible main
windows, against the `roth` purpose's SPY benchmark. **The SPY confound is pre-registered exactly as
`ROUND-39-PLAN.md` §4a states it**: none of these five baskets is a US large-cap-growth book, so a raw
SPY-column reading is expected to be negative or noisy for every basket except possibly `control`
(which is itself only a partial match to SPY) and is not the round's decision quantity. The decision
quantities are the two **basket-vs-control** and **trim-vs-passive** contrasts below, which subtract
out the shared SPY confound the same way round 39's four passive controls did.

**Decision rule, pre-registered:**

- **Basket edge** only if `median(r44-<basket>-passive) − median(r44-control-passive) > 21.2` **AND**
  BH q < 0.10 over all 10 cells (`PROTOCOL.md` §3 rule 8 — the denominator is every cell this round
  runs).
- **Trim edge** only if `median(r44-<basket>-trim) − median(r44-<basket>-passive) > 21.2` **AND**
  BH q < 0.10 over the same 10-cell field.
- **The noise floor is 21.2pp** (`PROTOCOL.md` §7), not a per-round quantity and not relitigated here.
- **Pre-registered prediction: null on both axes.** Thirty-nine prior rounds (`PERSONA-HYPOTHESES.md`
  §5, `DISJOINT-SECTOR-FAMILY.md` §5a, `ROUND-39-PLAN.md` §6) have found every basket-composition and
  every timing-rule margin this programme has ever measured inside the floor; the honest prior for
  this round's ten cells is the same.
- **Promotion.** `PROTOCOL.md` §6 applies to `roth`. This is pre-registered as a measurement round:
  **nothing is promoted from it regardless of outcome.** Any later promotion of a cell measured here
  requires two consecutive qualifying rounds on window sets that differ, with margins outside the
  floor in both — the same bar `C-trend`, `r34-ma-crossover-on` and `r40-rsi-confirm-slots6` did *not*
  clear before being seated by direction, and this round does not ask for that exception.

## 5. Falsifiable predictions, fixed before any run

1. **No basket beats `control` (passive) by more than 21.2pp on median adjusted excess, and none
   survives BH q<0.10.** Predicted to hold in all four themed baskets.
2. **No trim arm beats its own basket's passive arm by more than 21.2pp, and none survives BH
   q<0.10.** Predicted to hold in all five baskets.
3. **Hindsight split — the central caveat, stated before any figure exists.** Every note in the
   persona corpus has `published = null` (`PERSONA-HYPOTHESES.md` §2, §7): the power/defense/semicap
   themes were voiced in 2025-26 with 2023-25 returns already known to the speaker. `bull-2024`
   (2024-08-21→2025-08-20) and `recent` (2025-08-21→2026-08-18) are therefore **in-sample to the
   hypothesis** and any positive basket margin confined to those two windows is hindsight, not a
   finding. **The fair test is the six windows ending by 2022-10** — `gfc`, `chop-2011`, `chop-2015`,
   `q4-2018`, `covid`, `bear-2022` — and `round44_report.py` computes and reports the basket-minus-
   control margin on those six separately from the full eight and from the two 2024-26 windows alone.
   Predicted: no basket clears the floor on the six-window fair subset either — the honest prior is
   the programme's null record, not a weaker one restricted to pre-2023 data.
4. **Exposure prediction, from §3a's support table.** Trim exposure falls **most in `semicap`**
   (mean support ≈34%, so the trim arm sits out roughly a third of sessions) and **least in `power`**
   (mean support ≈11%, driven down by `SO`'s 3.8% and `DUK`'s 4.6%) — the two baskets should bracket
   the field's range of trim-arm session exposure.
5. **In a strong trend, trim gives back upside.** `bull-2024` and `recent` are both sustained-uptrend
   windows; the trim rule steps a name to cash whenever it is more than 15% above its own 200-day
   mean, which a persistent uptrend does repeatedly, so the trim arm is predicted to **underperform
   its own passive control** in both of those windows, in every basket that trades at all.
6. **In `bear-2022` and `gfc`, trim may shallow the drawdown.** The trim rule's only way to help is by
   sidestepping a name after a run-up and ahead of a reversal; `bear-2022` (a post-2021-rally
   correction) and `gfc` are the two windows where that sequence is most plausible, so these are the
   trim arm's best chance to beat its control, not its worst.
7. **Validity check, not a hypothesis.** Every passive control holds all four of its basket's names on
   essentially every session of every eligible window (session exposure at or near 1.0). If any
   control does not, it is not the baseline it is being used as and every contrast drawn against it in
   this round is void — the same check round 39's plan §5 prediction 6 ran.

## 6. What this round cannot settle

- **The causal story behind any theme.** "Power is the binding constraint on AI expansion",
  "memory/AI demand sustains a semiconductor super-cycle", and the EM/energy/dollar-weakness
  narrative are none of them testable with OHLCV bars — this round tests whether *four survivor
  tickers, held passively or trimmed on one rule*, produced a return pattern, not whether the
  underlying mechanism is real. A null says nothing about the thesis; a positive says nothing about
  the mechanism either, only about these names over this window mix.
- **Survivorship.** All twenty names are today's survivors. A power/defense/semicap company that
  merged, delisted or was renamed between 1970 and 2026 is not in the bar store and not in this field.
- **The SPY-benchmark confound**, restated: none of these baskets is US large-cap growth, so the raw
  `adjusted_excess vs SPY` column is not the decision quantity for any basket (§4); only the
  basket-minus-control and trim-minus-passive contrasts are.
- **"The theme", as opposed to these four names.** A result about `power` is a result about
  `NEE DUK SO CCJ` specifically — a different four utilities/miners, or a different weighting among
  them, is a different basket this round does not measure.
- **Ticker disjointness is necessary, not sufficient, under IRC §1091** (§2a) — this establishes no
  identical security is repurchased across books; it is not a tax-safety finding.
- **Price-only bars.** No dividends. `power`'s two regulated utilities (`NEE`, `DUK`) and `defense`'s
  primes are all above-average-yield sectors; stripping dividends understates their total return more
  than it understates `semicap`'s, which is a real but unmeasured distortion in any cross-basket
  comparison.
- **Composite overlap inside `control`.** `RSP` and `SPYG` both hold S&P 500 constituents; round 39
  §2d already made this point about the same four tickers and it is unchanged here.

## 7. Determinism, scope and the run recipe

**Determinism.** `round44.build()` reads no clock, no filesystem and no randomness — called twice it
returns field-identical cards (`tests/test_round44_field.py::TestDeterminism`). Only the reachability
probe and the disjointness check read live state on purpose (the bar store and the library on disk,
respectively) — the same design `round39.py`/`round40.py` use, for the same reason: a pasted constant
is correct only until the next commit or bar-store refresh.

**Scope.** This round owns `strategy-program/ROUND-44-PLAN.md`, `strategy-program/tools/round44.py`,
`strategy-program/tools/round44_report.py`, `data/rounds/r44-2026-09/cards/*.json` and
`tests/test_round44_field.py`. It modifies no library card, no shared tool
(`strategy-program/tools/round34_36_report.py` is imported by file path, not edited), no other round
and no other document in this directory.

**The run recipe** (not executed as part of this pre-registration):

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round44.py --write
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/disjoint_field.py --cards data/rounds/r44-2026-09/cards
bash strategy-program/tools/run_round.sh data/rounds/r44-2026-09/cards data/rounds/r44-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \
    --results data/rounds/r44-2026-09/results --json data/rounds/r44-2026-09/scorecard.json --pin-store
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round44_report.py
```

**Not investment advice.** Every figure this round produces, once run, will be a backtest on
price-only bars against a benchmark this plan has already flagged as a poor fit for four of its five
baskets. Nothing here is a recommendation to buy, sell or hold `NEE`, `DUK`, `SO`, `CCJ`, `LMT`, `NOC`,
`GD`, `RTX`, `AMAT`, `KLAC`, `LRCX`, `ASML`, `XOP`, `XME`, `EWY`, `VWO`, `VTV`, `SPYG`, `RSP` or `MDY`.
