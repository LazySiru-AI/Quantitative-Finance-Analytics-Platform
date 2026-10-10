# Round 45 -- persona method cards x cross-persona enhancements

Pre-registered 2026-09-09, before any card in this round has been run. Nothing below was written with
sight of a backtest result. The reachability and drift figures in section 3 are measured over
price-only bars and against on-disk source files, not returns -- they range-check the field, they do
not select it.

Not investment advice. Price-only bars, no dividends. The round has **not** been run.

---

## 1. The question, and whose claim each cell tests

**Three bases, each ANOTHER persona's own method rendered as a rule, each crossed with four
enhancements borrowed from a THIRD persona's stated method.** This is round 45 of
`strategy-program/MIX-AND-MATCH-PLAN.md` (section 3 pins this round's field verbatim; this document
is the pre-registration section 3 promises). No comparison in this round is against SPY directly and
none is arm-vs-arm across bases -- every reported contrast is one arm against its own base.

- **`kim`** -- Creator E's (`creator-e`) confirmation-conjunct entry, already MEASURED and
  seated on the trading paper book by direction: `close crosses_above bb_mid(20, 2) and rsi(14) >
  rsi_at_swing_high(14, 10)`, exit `close crosses_below bb_mid(20, 2)`, stop 0.12, no take-profit,
  150-day hold, 6 slots at 0.125 each. Round 45's `check_drift()` asserts this equals
  `backend/app/paper/library/candidates/r40-rsi-confirm-slots6.json` field for field and refuses to
  write on any mismatch.
- **`bee`** -- Creator C's (`creator-c`) vault-drafted `ma-crossover` card
  (`data/vault/influencers/creator-c/strategy/1.json`, saved 2026-09-09 via
  `app.personas.strategy.draft_strategy_card`): `close > sma(100) and ema(12) crosses_above ema(50)`,
  exit `ema(12) crosses_below ema(50)`, stop 0.08, take-profit 0.16, 30-day hold, 5 slots at 0.15
  each. The draft's own rationale, quoted verbatim (<=15 words): *"A 12/50 EMA crossover inside a
  100-day regime filter directly represents this approach."* Fidelity 0.38 (5 of 13 described
  techniques represented). `check_drift()` asserts entry/exit/brackets/slots equal the draft.
- **`creator-b`** -- Creator B's (`creator-b`) vault-drafted `band-reversion` card
  (`data/vault/influencers/creator-b/strategy/1.json`, same run): `close > sma(200) and close <
  bb_lower(26, 2)`, exit `close crosses_above bb_mid(26, 2)`, stop 0.12, no take-profit, 4 slots at
  0.20 each. The draft's own rationale, quoted verbatim (<=15 words): *"Band-reversion is chosen as
  the structural proxy: buying names undervalued by P/E."* Fidelity **0.0** -- his actual methodology
  is fundamentals and valuation, and the draft says so outright (0 of 5 techniques represented; the
  card is a forced structural translation, not a technical rule he described). **Hold cap: the draft
  says 252; this round pins 150.** 252 sessions is roughly a trading year, which exceeds the `trading`
  purpose's horizon ceiling (`app.tournament.purposes.PurposeSpec.horizon_months_max = 9`); 150 is the
  identical backstop `kim`'s base already uses, comfortably under that ceiling. `check_drift()`
  therefore asserts entry/exit/stop/slots equal the draft and deliberately EXCLUDES `max_hold_days`
  from that check -- the deviation is disclosed here and in every affected card's `thesis`, not
  silently matched.

**Both vault drafts carry the identical caveat, quoted (<=15 words):** *"Inspired by this persona's
described methodology, not a faithful reproduction of what they actually trade."* Every note behind
both drafts has `published = null` (`PERSONA-HYPOTHESES.md` section 7) -- see section 6.

**The four enhancements, one decision each against its base, each borrowed from a persona OTHER than
the one who owns the base it is tested on:**

| arm | change vs base | whose component |
|---|---|---|
| `base` | none | -- |
| `trend100` | entry `+ " and close > sma(100)"` (SKIPPED for `bee`, whose base entry already carries it) | Creator C |
| `rr5` | `take_profit_pct = 5 x stop_loss_pct` | Creator B |
| `risk1pct` | `position_pct = Decimal("0.01") / stop_loss_pct`, quantised to 3dp (slots unchanged) | Creator E |
| `trim115` | exit `+ " or close > sma(200) * 1.15"` | Creator B |

Fourteen cells: 5 on `kim`, 4 on `bee` (no `trend100`), 5 on `creator-b`.

## 2. The field -- 3 bases, 14 cells, one decision per arm

Authored by `strategy-program/tools/round45.py`. `BASES` is the one place every base's entry, exit
and brackets are written down; `entry_for`/`exit_for`/`take_profit_for`/`position_pct_for` derive
every arm from it by exactly the one substitution its row above names, and `build()` reads those
functions -- nothing downstream retypes an expression or a bracket value.
`tests/test_round45_field.py` asserts every arm's construction against its base by re-deriving the
same substitution, rather than trusting the pinned literal text.

**Universe (all three bases and every arm, identical):** `NVDA TSM MU AMD QCOM MSFT GOOGL AMZN NFLX
ORCL INTC TXN` -- the 12-name `_TAXABLE_GROWTH` pool from `backend/app/evolution/universe.py`, taken
exactly as rounds 40 and 42 did. **This is NOT any of the three vault drafts' own universes.** The
drafts' universes are today's bullish tickers -- `bee`'s draft holds AMAT, AMD, APLD, ARM, BA, CCME,
CRCL, CRDO, CRML, DDOG, DELL; `creator-b`'s holds AAL, AMZN, AVGO, AXP, BA, BE, BIDU, CLSK, COPX, CORZ --
several 2022-25 listings that fail window eligibility everywhere
(`MIX-AND-MATCH-PLAN.md` section 2). Every round-45 cell runs on the programme's mechanically-defined
12-name pool instead; this is what makes the three bases comparable on their enhancements, and it is
disclosed as a substitution, not a faithful reproduction of either draft's actual bullish list.

### Per-base fixed fields (identical across all of a base's arms except the one substitution named)

| base | entry | exit | stop | take-profit | hold | slots x pos | discipline |
|---|---|---|---|---|---|---|---|
| `kim` | `close crosses_above bb_mid(20, 2) and rsi(14) > rsi_at_swing_high(14, 10)` | `close crosses_below bb_mid(20, 2)` | 0.12 | None | 150 | 6 x 0.125 | momentum |
| `bee` | `close > sma(100) and ema(12) crosses_above ema(50)` | `ema(12) crosses_below ema(50)` | 0.08 | 0.16 | 30 | 5 x 0.15 | trend |
| `creator-b` | `close > sma(200) and close < bb_lower(26, 2)` | `close crosses_above bb_mid(26, 2)` | 0.12 | None | 150 (draft 252, capped) | 4 x 0.20 | mean-reversion |

`rank_by = None`, `purpose = trading`, `designed_through = DESIGN_THROUGH` (2026-02-13) on every cell.
`source_persona` is left `None` on every card, as rounds 40/42 do -- that field is reserved for cards
promoted directly from a persona draft by `app.personas.strategy`, and these are hand-authored cells
that merely reuse a draft's or a seated card's field; each card's `thesis` names the persona instead.

### The `rr5` take-profit and `risk1pct` position size, by base

| base | stop | `rr5` take-profit (5 x stop) | `risk1pct` position_pct (0.01 / stop, 3dp) |
|---|---|---|---|
| `kim` | 0.12 | 0.60 | 0.083 |
| `bee` | 0.08 | 0.40 | 0.125 |
| `creator-b` | 0.12 | 0.60 | 0.083 |

### The parameter budget (`PROTOCOL.md` section 3 rule 3 -- ten free numbers per card)

Counted by `round45.free_numbers`, the identical convention rounds 35/36/40/42 use (distinct numeric
values across `entry`/`exit`/`rank_by`, + one per present bracket, + two for slot count and position
size), and asserted by the test. **Measured 2026-09-09, matches the tool's own printed table
exactly:**

| card | free numbers | card | free numbers | card | free numbers |
|---|---|---|---|---|---|
| `r45-kim-base` | 8 | `r45-bee-base` | 8 | `r45-wsaj-base` | 7 |
| `r45-kim-trend100` | 9 | -- (skipped) | -- | `r45-wsaj-trend100` | 8 |
| `r45-kim-rr5` | 9 | `r45-bee-rr5` | 8 | `r45-wsaj-rr5` | 8 |
| `r45-kim-risk1pct` | 8 | `r45-bee-risk1pct` | 8 | `r45-wsaj-risk1pct` | 7 |
| `r45-kim-trim115` | 10 | `r45-bee-trim115` | 10 | `r45-wsaj-trim115` | 8 |

The two `trim115` maxima (`r45-kim-trim115`, `r45-bee-trim115`) land exactly at the budget ceiling of
ten (the trim clause's `200` and `1.15` are both new numeric values not already present in the base's
entry or exit); every other cell is under it. No card exceeds the budget.

## 3. The reachability gate, and the drift asserts

**The reachability gate** is round 40's motivating defect, inherited by every mix-and-match round
since: a `close crosses_above bb_upper(4, 4)` expression that could structurally never fire
(`sqrt(n-1)` bounds the achievable z-score at n=4 to `sqrt(3)` ~ 1.7321) passed every other pre-flight
check because none of them asks whether a rule can ever be *true*. `round45.py --write` measures
every DISTINCT entry and exit (11 expressions: 4 for `kim`, 3 for `bee`, 4 for `creator-b` -- `rr5` and
`risk1pct` never change entry or exit, so they add nothing new to this table) against the actual bar
store, bounded to `DESIGN_THROUGH`, with `app.market.store.read_frame` (in-memory, no file lock) and
the real evaluator (`app.rules.grammar.parse` + `app.rules.evaluate.evaluate`). It **refuses to
write** if any expression fires 0 times, if any ENTRY fires on more than 300 of every 1000
symbol-sessions, or if a `trend100` entry retains less than 2% or more than 98% of its own base's
firings.

**Measured 2026-09-09, bounded to `DESIGN_THROUGH` (2026-02-13), over the 12-name universe (108,465
symbol-sessions), reproduced exactly by `round45.py`'s own run:**

| expression | kind | fires | per 1000 | retention of base |
|---|---|---|---|---|
| `kim-base` entry (`... bb_mid(20,2) and rsi(14) > rsi_at_swing_high(14,10)`) | entry | 881 | 8.12 | -- |
| `kim-trend100` entry (`kim-base and close > sma(100)`) | entry | 384 | 3.54 | 43.59% |
| `kim-base` exit (`close crosses_below bb_mid(20, 2)`) | exit | 6,304 | 58.12 | -- |
| `kim-trim115` exit (`kim-base-exit or close > sma(200) * 1.15`) | exit | 39,544 | 364.58 | -- |
| `bee-base` entry (`close > sma(100) and ema(12) crosses_above ema(50)`) | entry | 959 | 8.84 | -- |
| `bee-base` exit (`ema(12) crosses_below ema(50)`) | exit | 1,265 | 11.66 | -- |
| `bee-trim115` exit (`bee-base-exit or close > sma(200) * 1.15`) | exit | 36,212 | 333.86 | -- |
| `wsaj-base` entry (`close > sma(200) and close < bb_lower(26, 2)`) | entry | 1,851 | 17.07 | -- |
| `wsaj-trend100` entry (`wsaj-base and close > sma(100)`) | entry | 907 | 8.36 | 49.00% |
| `wsaj-base` exit (`close crosses_above bb_mid(26, 2)`) | exit | 5,404 | 49.82 | -- |
| `wsaj-trim115` exit (`wsaj-base-exit or close > sma(200) * 1.15`) | exit | 38,908 | 358.71 | -- |

Every expression fires; every entry sits well inside the 300/1000 ceiling (the highest, `wsaj-base`,
is 17.07/1000, roughly 6% of the ceiling); both `trend100` retentions (43.59% for `kim`, 49.00% for
`creator-b`) sit comfortably inside `[2%, 98%]` -- the filter cuts roughly half the base's firings on
either base, not a no-op and not a near-off-switch. The field is reachable and the gate passes.

**The trim exits fire far more often than their bases** (`kim`: 364.58 vs 58.12 per 1000; `bee`:
333.86 vs 11.66; `creator-b`: 358.71 vs 49.82) because `close > sma(200) * 1.15` is a *level* condition,
true on every session price sits 15% above its 200-day average, not an edge-triggered cross -- once a
name is running, the added clause is true on most of the sessions it holds through. That is expected
and is exempt from the reachability ceiling (which binds entries only); it is also exactly why
`trim115` is predicted to shorten holds and lower exposure, per section 4's predictions.

**The drift asserts.** `round45.py::check_drift()` reads `r40-rsi-confirm-slots6.json` and both vault
draft JSONs from disk and compares every pinned field above to them. **Measured 2026-09-09: clean --
no mismatch on any of `kim`'s seven fields, `bee`'s seven fields, or `creator-b`'s five checked fields**
(entry, exit, stop, slots, position size; `max_hold_days` is deliberately excluded from `creator-b`'s
check, see section 1). `--write` refuses if any of these has moved since this round was pinned --
concurrent sessions may edit the vault or the library, and a stale pasted constant would silently
retest a different card than the one this document describes.

`round45.py --write` also verified the taxable universe is disjoint from the live 21-ticker roth union
(`app.evolution.promotion._library_cards`) -- it is, by construction, identical to rounds 40 and 42's
own verified result on this same pool.

## 4. Windows, metric, decision rule

**Windows:** the standard eight-window main matrix (`WINDOWS.md`): `q4-2018`, `covid`, `bear-2022`,
`chop-2015`, `chop-2011`, `bull-2024`, `recent`, `gfc`. All 12 universe names begin no later than
1998 (the identical eligibility footprint rounds 40/42 measured on this same pool), so 8-of-8
eligibility is expected. `13f-legal` does not apply and will not run.

**Metric:** median exposure-adjusted excess across a card's eligible main windows,
`adjusted_excess = strategy_return - capital_exposure x benchmark_return` (`score.py`'s primary key,
benchmark SPY). Scored with `--pin-store`.

**Decision rule, pre-registered, pinned identically in `MIX-AND-MATCH-PLAN.md` section 3:**

> An enhancement earns something only if its **marginal** -- the mean over its bases of (arm median
> adjusted excess minus base median) -- exceeds the **21.2pp noise floor** (`PROTOCOL.md` section 7)
> **AND** its arm cells survive **BH q < 0.10** with the denominator **m = 14** (every cell this
> round runs), where **each arm cell is contrasted with its own base**, not a shared reference, and
> **base cells carry p = None but still occupy a seat in m**.

`trend100`'s marginal is the mean over 2 bases (`kim`, `creator-b` -- `bee` does not carry this arm); the
other three enhancements' marginals are the mean over all 3 bases. `strategy-program/tools/
round45_report.py::bh_m14` builds the 14-entry p-value list in this shape (three `None`s for the
bases, eleven per-base contrast p-values for the arms) and calls
`app.backtest.scan.benjamini_hochberg` on it directly, so `m` is exactly 14 regardless of which base
an arm belongs to -- this is NOT `round34_36_report.bh_against_reference`, which assumes one shared
reference cell for every contrast; round 45 has three.

**An enhancement's verdict requires BOTH halves**: `round45_report.py` reports a cell "EARNS
SOMETHING" only when its marginal clears the floor AND every one of its arm cells (2 for `trend100`,
3 for the other three) has BH q < 0.10 in the m=14 pass. A conservative reading -- one qualifying arm
out of three is not the enhancement paying for itself on the book as a whole.

**Nothing here is promotable.** `PROTOCOL.md`'s r21 amendment: section 6's promotion rule does not
apply to the `trading` purpose, and no replacement gate was built (per-window sampling error at this
book's six-to-nine-month effective horizon is far too high relative to the ~26 non-overlapping windows
the common history supports). This round reports; it does not seat, and no cell here can move to
`candidates/` or `base/` on its own scorecard.

**Honest prior: the null.** Rounds 17, 18, 34, 38, 39, 40 and 42 have put form, exit, rotation, style
tilts and confirmation conjuncts all inside the 21.2pp floor (minimum BH q 0.40 in round 34's family;
round 40's best cell +4.82pp, still inside the floor; round 42's every family-vs-own-control margin
between -5.87pp and +1.00pp). Round 45 crosses three already-measured-or-drafted bases with four
enhancements each borrowed from a component this programme has separately measured or never measured
in this exact combination -- the likeliest outcome is a fourth null restated on twelve new cells.

## 5. Falsifiable predictions

Each card carries these in its `falsification` field; `round45_report.py` prints prediction beside
outcome.

1. **Null for all four enhancements** -- no enhancement clears the 21.2pp marginal floor AND survives
   BH q<0.10 over all of its arm cells. *Failure regime: an enhancement clears the floor on one base
   but not the others, which the marginal (a mean, not a max) is built to catch rather than reward.*
2. **`trend100` cuts trades vs base on both bases it applies to** (`kim`, `creator-b`) -- an added
   structural filter can only reduce firings, never increase them; the reachability table already
   shows retention well under 100% on both (43.59%, 49.00%).
3. **`rr5` cells are nearly identical to their base** -- the 5:1 bracket rarely binds (rounds 17/18
   measured 0.14pp on a similar asymmetric bracket). `round45_report.py::rr5_target_exit_counts`
   counts, from the run files' trade logs across the eight main windows, what fraction of each
   `rr5` cell's exits are actually the take-profit target; this plan pre-registers that **fewer than
   10%** of exits will be targets on every one of the three `rr5` cells.
4. **`risk1pct` lowers mean exposure and raises adjusted excess per unit exposure, without changing
   the per-window sign pattern** -- resizing to a flat 1% risk per trade cuts the largest position
   sizes (`kim` 0.125 -> 0.083, `creator-b` 0.20 -> 0.083) while leaving `bee`'s position size essentially
   unchanged (0.15 -> 0.125), so the effect should be visible on `kim` and `creator-b` and muted on `bee`.
5. **`trim115` lowers exposure and loses to base specifically in `bull-2024` and `recent`** -- the
   identical shape round 44's trim arm showed (+0.4 to +2.4pp, null): giving back upside in strong
   trends is the trim's cost, and the reachability table already shows the trim exit firing at
   roughly 6x (`kim`), 7x (`creator-b`) and 29x (`bee`) its own base exit's rate once a name is running.
6. **Sign flips by regime; only the eight-window median is safe to read.** Any single-window
   arm-minus-base read is unsafe for any of the fourteen cells.
7. **Degenerate-outcome guard.** An arm at low trade counts (`bee`'s cells run at 5 slots and a
   30-day hold, the shortest horizon of the three bases) could fail the 5-of-8 regime gate in a short
   or thin window and be unranked -- that is "switched off", not "the enhancement did not help", and
   the two must not be conflated in the report.

## 6. What this round cannot settle

- **Two of the three bases are vault drafts, not the personas' own stated rules.** `bee`'s draft has
  fidelity 0.38 (5 of 13 described techniques represented); `creator-b`'s has fidelity **0.0** -- his
  method is fundamentals and valuation, and `band-reversion` is a forced structural proxy the draft's
  own rationale says represents none of his actual defenses (financial statement analysis, relative
  valuation, macro positioning). A null on `creator-b`'s cells refutes this technical proxy, not his
  methodology.
- **Every vault draft's corpus has `published = null`** (`PERSONA-HYPOTHESES.md` section 7) --
  hindsight against this round's eight windows is unbounded for `bee` and `creator-b`. A claim voiced in
  2026 is voiced with every window in this round's matrix already known to the persona. `kim`'s base
  is a MEASURED card (round 40), not a corpus claim, and carries no equivalent caveat of its own.
- **It is one universe, and not a survivorship-free one.** The same 12-name large-cap
  tech/semiconductor pool rounds 40 and 42 used, mechanically defined by `_TAXABLE_GROWTH` but
  selected long ago for what the names *are*. None of the three bases runs on the universe its own
  persona (or draft) actually named.
- **The enhancement components were not necessarily stated as portable by their donor persona.**
  Creator B's 5:1 bracket and trim clause were measured (rounds 17/18/44) as HIS OWN card's
  brackets, not as a general-purpose addition to someone else's entry/exit; testing them here as
  drop-in modifiers is this programme's construction, not a claim either persona made about
  cross-application.
- **It cannot promote anything.** `PROTOCOL.md`'s r21 amendment: the `trading` purpose is exempt from
  section 6 promotion, and this round is a measurement study regardless -- report only.
- **It is price-only and dividend-free**, like every backtest in this programme.
- **A null here refutes these fourteen expressions on this book, not "mixing persona components" in
  general.** Eleven arm cells (four enhancements x three bases, minus one skip) plus three bases is
  not an exhaustive search of how these three methods could combine.

## 7. Run recipe (to execute after freeze -- NOT run by this document or by the agent that wrote it)

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round45.py --write
bash strategy-program/tools/run_round.sh data/rounds/r45-2026-09/cards data/rounds/r45-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \
    --results data/rounds/r45-2026-09/results --json data/rounds/r45-2026-09/scorecard.json --pin-store
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round45_report.py
```

The first line has been run to produce sections 3's measured tables and the 14 cards under
`data/rounds/r45-2026-09/cards/`. The remaining three lines -- the actual backtest, the scorecard and
the computed report -- have **not** been run as part of authoring this round; they are the next
session's or the owner's to execute.
