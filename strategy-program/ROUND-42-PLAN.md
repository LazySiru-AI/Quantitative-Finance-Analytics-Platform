# Round 42 -- level reclaim (wick rejection) and breakout quality (0.25-range confirmation)

Pre-registered 2026-09-09, before any card in this round has been run. Nothing below was written with
sight of a backtest result. The reachability figures in §3 are firing counts over price-only bars, not
returns; they were measured to range-check the field, not to select it.

Not investment advice. Price-only bars, no dividends. The round has **not** been run.

---

## 1. The question, and whose claim it tests

**Two independent families, each testing one untested claim from `PERSONA-DISCUSSION-2026-09-09.md`
§3, each contrasted against its OWN control.** Every comparison in this round is arm-minus-own-family-
control on median adjusted excess. Nothing is ever compared to SPY and nothing in family A is ever
compared to a cell in family B -- the two families answer two unrelated questions and share nothing but
the universe, the book and the fixed brackets.

**Family A -- "level reclaim"**, testing **Creator E** (`creator-e`), who -- forced off his
native intraday timeframe into this programme's daily-bar constraint -- offered:

> "wick rejection at prior support and resistance combined with full-body candle confirmation"

and pre-registered its own failure regime:

> "consolidation and range-bound sideways movement, where support and resistance blur"

(`PERSONA-DISCUSSION-2026-09-09.md` §3, "trading" answer). Every reversion and breakout form this
programme has tested (rounds 17, 18, 34, 40) enters on a **close** crossing a level; none has
conditioned on what happened **intrabar** at that level, or on the shape of the confirming candle. That
is the untested gap Creator E's claim points at, and `PERSONA-DISCUSSION-2026-09-09.md` §4's triage table
marks it "**Round 42, family A**".

**Family B -- "breakout quality"**, testing **Creator C** (`creator-c`), who offered:

> "Fibonacci 0.25 confirmation on range breakouts" ... "a real breakout should confirm through 0.25
> within days"

with a named failure regime:

> "gapping markets where 0.25 is crossed in a single overnight gap then reverses"

and

> "sideways choppy markets where 0.25 takes 8+ days to reach with low conviction"

(`PERSONA-DISCUSSION-2026-09-09.md` §3, "trading" answer). Round 34's `channel-breakout` form enters at
the level itself; nothing this programme has run has required the breakout to *travel* past the level
before counting. That is the untested gap, and §4's triage marks it "**Round 42, family B** (the
expressible half only)" -- his 1.0x-range profit target and "within 5 trading days" clock cannot be
expressed in this engine's DSL (there is no lookback-bounded target-reach condition), so this round
tests the confirmation-entry half of his claim and no other.

Both personas' corpora are model-summarised from partly Korean-language video transcripts
(`PERSONA-DISCUSSION-2026-09-09.md` §5); every note has `published = null`
(`PERSONA-HYPOTHESES.md` §7), so neither claim can be dated against the windows below -- see §6.

## 2. The field -- 2 families, 5 cards, each family's own control

Authored by `strategy-program/tools/round42.py`. `FAMILIES` is the one place every entry and exit
expression in the round is written down; `build()` reads it and nothing downstream retypes an
expression. `tests/test_round42_field.py` asserts the pinned literal text by construction.

**Universe (both families, identical, verbatim):** `NVDA TSM MU AMD QCOM MSFT GOOGL AMZN NFLX ORCL
INTC TXN` -- the 12-name `_TAXABLE_GROWTH` pool from `backend/app/evolution/universe.py`, taken exactly
as round 40 did. It is **mechanically defined by the pool, not chosen for this round** -- large-cap
tech/semiconductors, and therefore **not survivorship-free**, the identical limitation round 40 carried
on this same universe.

**Brackets, fixed on every one of the 5 cards** (no cell varies these): `stop_loss_pct = 0.12`,
`take_profit_pct = None`, `max_hold_days = 150`, `max_positions = 3`, `position_pct = 0.25`,
`rank_by = None`, `purpose = trading`, `designed_through = DESIGN_THROUGH` (2026-02-13).
`source_persona` is left `None` on every card -- that field is reserved for cards promoted from a
persona strategy-card draft, and this round's cards are hand-authored, not drafted by a persona; the
persona is instead named in each card's `thesis`.

### Family A -- "level reclaim" (`discipline = mean-reversion`)

**Exit, fixed across the family:** `close crosses_below swing_low(20)`.

| arm | agent_id | entry | kind |
|---|---|---|---|
| control | `r42-reclaim-control` | `close crosses_above swing_low(20)` | control |
| wick | `r42-reclaim-wick` | `low < swing_low(20) and close > swing_low(20)` | treatment |
| wick-body | `r42-reclaim-wick-body` | `low < swing_low(20) and close > swing_low(20) and (close - open) > 0.5 * (high - low)` | treatment |

The control is a plain close-to-close reclaim of the last confirmed swing low -- no intrabar structure
at all. `wick` adds the intrabar pierce-and-close-back-above condition (the wick rejection itself).
`wick-body` adds Creator E's second, stricter condition on top of `wick`: the candle that closes back above
the level must also be more than half body (`(close - open) > 0.5 * (high - low)`), his "full-body
candle confirmation". Each arm isolates exactly one additional structural term against the one before
it, satisfying `PROTOCOL.md` §7's one-decision-per-variant rule twice over within the family.

`swing_low(20)` (`backend/app/indicators/swing.py`) is the **last CONFIRMED pivot, held forward,
published 20 bars late** -- see §5 below for what that costs this specific test.

### Family B -- "breakout quality" (`discipline = breakout`)

**Exit, fixed across the family:** `close crosses_below ema(20)` -- Creator C's own stated
trend-loss exit.

| arm | agent_id | entry | kind |
|---|---|---|---|
| control | `r42-breakout-control` | `close crosses_above swing_high(20)` | control |
| q25 | `r42-breakout-q25` | `close crosses_above swing_high(20) + 0.25 * (swing_high(20) - swing_low(20))` | treatment |

The control is the breakout at the level itself -- the tested `channel-breakout` shape from round 34
minus its regime filter. `q25` requires the close to first cross a level a further 0.25x the prior
range's height above the breakout point before counting -- his confirmation threshold. **Not
expressible and not part of this test:** the "within 5 trading days" clock (no bounded-lookback
target-reach primitive in the DSL) and the 1.0x-range profit target (the exit is fixed to `ema(20)`
loss across the whole family, per the one-decision rule, so a second, target-based exit cannot be
added without changing two things at once).

### The parameter budget (`PROTOCOL.md` §3 rule 3 -- ten free numbers per card)

Counted by `round42.free_numbers`, the identical convention rounds 35/36/40 use (distinct numeric
values across the expressions, + one per present bracket, + two for slot count and position size), and
asserted by the test:

| card | entry numeric values (distinct) | + brackets (stop, hold) | + slots, pos | total |
|---|---|---|---|---|
| `r42-reclaim-control` | 20 | 2 | 2 | 5 |
| `r42-reclaim-wick` | 20 | 2 | 2 | 5 |
| `r42-reclaim-wick-body` | 20, 0.5 | 2 | 2 | 6 |
| `r42-breakout-control` | 20 | 2 | 2 | 5 |
| `r42-breakout-q25` | 20, 0.25 | 2 | 2 | 6 |

The 20-period window is shared across `swing_low`/`swing_high`/`ema` in every expression and each
family's entry and exit, so it counts once per card, not once per occurrence. Every cell is well under
the budget of ten.

## 3. The reachability gate

The gate this round inherits is round 40's motivating defect: a `close crosses_above bb_upper(4, 4)`
expression that could **structurally never fire** (`sqrt(n-1)` bounds the achievable z-score at n=4 to
`sqrt(3)` ~ 1.7321, so a 4-sigma threshold is unreachable) still passed every pre-flight check --
eligibility, pytest, ruff, a parameter-range check -- because none of them asks whether a rule can ever
be *true*, only whether its indicators can warm up.

**So `round42.py --write` measures every DISTINCT entry and exit** (5 entries + 2 exits = 7
expressions; family A's three entries share one exit, family B's two entries share a different one)
against the actual bar store, bounded to `DESIGN_THROUGH`, with `app.market.store.read_frame` (an
in-memory DuckDB connection -- no file lock, safe alongside other readers) and the real evaluator
(`app.rules.grammar.parse` + `app.rules.evaluate.evaluate`, so a "fire" is a session on which the
expression is True under the same DSL semantics the backtest evaluates). It **refuses to write** if any
expression fires 0 times, or if any **entry** fires on more than 300 of every 1000 symbol-sessions -- a
near-always-on entry that would test whether the market is open, not the persona's claim. Exits are
measured and printed but exempt from that ceiling (a high-firing exit is a short average hold, not a
broken gate).

**Measured 2026-09-09, bounded to `DESIGN_THROUGH` (2026-02-13), over the 12-name universe
(108,465 symbol-sessions), reproduced exactly by `round42.py`'s own run:**

| expression | kind | fires | per 1000 sessions |
|---|---|---|---|
| `close crosses_above swing_low(20)` (reclaim control) | control | 1,245 | 11.48 |
| `low < swing_low(20) and close > swing_low(20)` (wick) | treatment | 1,651 | 15.22 |
| `... and (close - open) > 0.5 * (high - low)` (wick-body) | treatment | 683 | 6.30 |
| `close crosses_below swing_low(20)` (family A exit) | exit | 1,237 | 11.40 |
| `close crosses_above swing_high(20)` (breakout control) | control | 1,830 | 16.87 |
| `close crosses_above swing_high(20) + 0.25 * (swing_high(20) - swing_low(20))` (q25) | treatment | 1,464 | 13.50 |
| `close crosses_below ema(20)` (family B exit) | exit | 6,929 | 63.88 |

Every expression fires; every entry sits well inside the 300/1000 ceiling (the highest, the breakout
control, is 16.87/1000, roughly 6% of the ceiling); the field is reachable and the gate passes. These
figures match the brief's measured numbers to the fire count, so no drift note is needed this round
(contrast round 40, which found two of its four figures had drifted from an earlier store snapshot).

`round42.py --write` also verified the taxable universe is disjoint from the live 21-ticker roth union
(`app.evolution.promotion._library_cards`) -- it is, by construction, since every roth card in the
library holds ETF/enterprise-software tickers, not the 12 semiconductor/mega-cap-tech names here.

## 4. Windows, metric, decision rule

**Windows:** the standard eight-window main matrix (`WINDOWS.md`): `q4-2018`, `covid`, `bear-2022`,
`chop-2015`, `chop-2011`, `bull-2024`, `recent`, `gfc`. All 12 universe names begin no later than 1998
(the identical eligibility footprint round 40 measured on this same pool), so 8-of-8 eligibility is
expected. `13f-legal` does not apply to this round and will not run.

**Metric:** median exposure-adjusted excess across a card's eligible main windows,
`adjusted_excess = strategy_return - capital_exposure x benchmark_return` (`score.py`'s primary key,
benchmark SPY). **Reported as arm-minus-OWN-control, never arm-vs-SPY and never arm-vs-the-other-
family's-control.** A confirmation term can only reduce firings relative to its own control, so a
treatment always takes fewer trades and carries lower exposure than its control; raw return would
credit the control merely for being invested more, which is exactly what `adjusted_excess` exists to
strip out. Scored with `--pin-store`.

**Decision rule, pre-registered.** An arm "earns" something only if its **arm-minus-own-control median
adjusted excess exceeds the 21.2pp noise floor** (`PROTOCOL.md` §7) **AND** survives **BH q < 0.10**
with the denominator = **every cell run in this round (m = 5)**, per `PROTOCOL.md` §3 rule 8. The
reference cell BH is computed against is arbitrary (there are two natural candidates, one per family's
control); `round42_report.py` reports BH against both and states that m stays 5 regardless of which is
named -- the per-family arm-minus-own-control contrast is what the decision rule actually reads.

**Nothing here is promotable.** `PROTOCOL.md`'s r21 amendment: §6's promotion rule does not apply to
the `trading` purpose, and no replacement gate was built (per-window sampling error at this book's
six-to-nine-month effective horizon is far too high relative to the ~26 non-overlapping windows the
common history supports). This round reports; it does not seat, and no cell here can move to
`candidates/` or `base/` on its own scorecard.

**Honest prior: the null.** Rounds 17, 18, 34, 38, 39 and 40 have put form, exit, rotation, style
tilts and a confirmation conjunct all inside the 21.2pp floor (minimum BH q 0.40 in round 34's family;
round 40's best cell +4.82pp, still inside the floor). Both families here add a confirmation term to an
existing entry, exactly round 40's pattern -- the likeliest outcome is the same finding restated on two
new expressions.

## 5. Falsifiable predictions

Each card carries these in its `falsification` field; `round42_report.py` prints prediction beside
outcome.

1. **No arm beats its own control by more than 21.2pp on median adjusted excess AND survives BH
   q<0.10.** If one does, a confirmation term pays for itself on this book for the first time -- the
   result that would change the programme's direction. *Failure regime, both families: a treatment
   clears the floor only in trending windows and the median is dragged under it by chop.*
2. **Family A trade-count ordering:** `wick-body` takes fewer trades than `wick`, which takes fewer
   than the `reclaim` control -- each added structural term (the intrabar pierce, then the full-body
   requirement) can only filter further, never loosen. The reachability figures already show this in
   the fire counts (1,245 -> 1,651 is the exception: the wick condition ADDS an intrabar requirement
   but is not a strict subset of the control's fires -- see the honesty note below).
3. **Family B trade count and timing:** `q25` takes fewer trades and enters later than the `breakout`
   control (1,464 vs 1,830 fires), giving back early upside in strong trends (`recent`, `bull-2024`)
   and avoiding false starts in chop (`chop-2015`, `chop-2011`) -- Creator C's own named failure
   regime for a *failed* breakout, read here as the control's failure mode that `q25` is meant to avoid.
4. **Creator E's named failure regime for family A:** any daily version of his rule loses in
   range-bound consolidation -- watch `chop-2015` and `chop-2011` specifically for the control and
   both treatments; his claim predicts the treatments underperform there too, just less than the
   control's false reclaims would.
5. **Creator C's named failure regime for family B:** gapping markets (a single overnight gap
   crossing 0.25 then reversing) and slow chop (0.25 taking 8+ days, arriving "too late"). This
   programme has no windows labelled by gap frequency; `chop-2015`/`chop-2011` stand in for the slow
   half of his prediction and no window isolates the gap half.
6. **Sign flips by regime; only the eight-window median is safe to read.** Any single-window
   arm-minus-control read is unsafe in either family.
7. **Degenerate-outcome guard.** Any arm at these fire rates (max 16.87/1000 sessions across 12 names)
   could still fail the 5-of-8 regime gate in a short or thin window and be unranked -- that is
   "switched off", not "the confirmation did not help", and the two must not be conflated in the
   report.

**An honesty note on prediction 2.** `wick`'s entry is `low < swing_low(20) and close > swing_low(20)`
-- it is **not** `reclaim-control`'s entry (`close crosses_above swing_low(20)`) plus a conjunct; it is
a *different* condition built on the same level (a level-cross vs. a pierce-and-close-back-above), so
its fire count is not guaranteed to be a subset of the control's, and indeed it is not: `wick` fires
*more* than the control (1,651 vs 1,245), because "closed back above a level already under it"
(`crosses_above`, which requires being below on the prior bar) is stricter in one direction than "the
low pierced the level and the close is above it" is in the other. Prediction 2 is therefore stated only
about the ordering **within** the treatments (`wick-body` < `wick`, both being `wick`'s condition plus
strictly more), not about either treatment against the control's raw count -- the reachability table
already shows the control is not the highest-firing cell in family A.

## 6. What this round cannot settle

- **Neither treatment's exact expression was stated by its persona in threshold form.** Creator E named
  "wick rejection... with full-body candle confirmation" but never wrote `low < swing_low(20)` or
  `0.5 * (high - low)`; those are this programme's translation of his prose into the DSL, exactly as
  round 40 noted for its own arms. Creator C did state "0.25" explicitly, so that threshold is his.
- **It is one universe, and not a survivorship-free one.** The same 12 large-cap tech/semiconductor
  names round 40 used, mechanically defined by the pool but selected long ago for what they *are*.
- **Both persona corpora are model-summarised from partly Korean-language transcripts**
  (`PERSONA-DISCUSSION-2026-09-09.md` §5), and every note has `published = null`
  (`PERSONA-HYPOTHESES.md` §7) -- hindsight is unbounded. A wick-rejection or breakout-quality claim
  voiced in 2026 is voiced with every window in this round's matrix already known to the persona. This
  round does not, and cannot, bound which windows were genuinely unseen to either speaker.
- **It cannot promote anything.** `PROTOCOL.md`'s r21 amendment: the `trading` purpose is exempt from
  §6 promotion, and this round is a measurement study regardless -- report only, per this round's own
  framing.
- **The inexpressible halves of both claims are untested by construction, not refuted.** Creator E's
  intraday execution discipline (5-minute/1-minute entries confirmed by daily-chart direction) cannot
  be expressed on daily bars at all -- he said as much declining the question outright before offering
  the daily-bar fallback tested here. Creator C's 1.0x-range profit target and "within 5 trading
  days" confirmation clock have no DSL primitive (no bounded-lookback target-reach condition exists in
  this engine); a null on `q25`'s entry says nothing about whether his exit and timing rules would have
  changed the outcome.
- **It is price-only and dividend-free**, like every backtest in this programme.
- **It tests one entry-side operationalisation per persona, not "wick rejection" or "breakout quality"
  in general.** A null here refutes *these* expressions on *this* book, not the claims in full
  generality.

## 7. Run recipe (to execute after freeze -- not run by this document)

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round42.py --write
bash strategy-program/tools/run_round.sh data/rounds/r42-2026-09/cards data/rounds/r42-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \
    --results data/rounds/r42-2026-09/results --json data/rounds/r42-2026-09/scorecard.json --pin-store
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round42_report.py
```
