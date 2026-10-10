# Round 48 -- does Creator E's 1%-risk sizing do to EVERY seated trading card what it did to his own?

Pre-registered 2026-09-09, before any card in this round has been run. Nothing below was written with
sight of a backtest result. The field tables in section 2 are measured against on-disk library files
and the real grammar, not against returns -- they read the field back, they do not select it.

Not investment advice. Price-only bars, no dividends. The round has **not** been run.

---

## 1. The question

Round 45 (`data/rounds/r45-2026-09/REPORT.md`, `ANALYSIS.md`, `ROUND-45-PLAN.md`) crossed three
persona-method bases with four cross-persona enhancements and found a null on every enhancement by
its own pre-registered decision rule -- except that one enhancement had a *shape* worth separating from
the others even inside the null: Creator E's `position_pct = 0.01 / stop_loss_pct` sizing (`risk1pct`)
cut his own card's mean exposure 0.126 -> 0.082, its worst window -17.21pp -> -11.41pp, and its IQR
8.3pp -> 5.7pp, at a cost of 1.35pp of median -- and it roughly halved the worst window on the `creator-b`
base too. Every other enhancement moved things around with no consistent direction.

**This is the feedback-loop follow-up.** Round 45 tested the sizing on cards that were themselves
either a MEASURED card (`r40-rsi-confirm-slots6`) or fidelity-scored vault drafts, not on the cards
actually carrying live capital. This round applies the identical resizing to every RULES card
currently seated on `app.paperdesk.desk.AGENT_IDS` (the live trading roster) except the one round 45
already measured, and asks the same question of the whole book at once: does the sizing shrink the
tail and the exposure everywhere it is applied, the way it did on the one card round 45 tested it on,
or was round 45's finding one card's story?

`AGENT_IDS` seats six cards: `B3-concentrated`, `A-rotation`, `C-trend`, `B-momentum`,
`I-13f-duquesne-2026q2`, `r40-rsi-confirm-slots6`. The sixth is round 45's own `kim` base -- already
measured under this exact resizing -- so this round covers the other five.

**Every comparison in this round is one arm against its own base, never arm-vs-arm across bases**,
matching round 45's own decision-rule shape.

## 2. The field -- 5 bases, 2 arms, 10 cells

Authored by `strategy-program/tools/round48.py`. Unlike round 45, there is **no pinned literal copy**
of any base's entry/exit/bracket text anywhere in this document or in the authoring tool: `build()`
reads each base's fields directly from its seated library JSON with `json.loads` at build time, merges
in only the round-card identifying fields a library card does not carry (`agent_id`, `display_name`,
`thesis`, `falsification`, `purpose`, `designed_through`), and constructs the `risk1pct` arm from the
resulting `base` `StrategyCard` with a single `model_copy(update={"position_pct": ...})` call --
`tests/test_round48_field.py` asserts every base cell against a *fresh* read of its own source file,
not against a second hand-typed table, and asserts every `risk1pct` cell differs from its base in
`position_pct` and nothing else. `round48.py` refuses to write if any of the five library files is
missing.

### Bases, read verbatim 2026-09-09 (identical to their current seated library JSON)

| slug | source | entry | exit | stop | tp | hold | slots x pos | discipline |
|---|---|---|---|---|---|---|---|---|
| `b3` | `variants/B3-concentrated.json` | `ema(20) crosses_above ema(50) and close > sma(200)` | `close crosses_below sma(200)` | 0.12 | -- | 180 | 4 x 0.22 | momentum |
| `arot` | `candidates/A-rotation.json` | `close > sma(50) and rsi(14) > 55 and rsi(14) < 80` | `close < sma(50) or rsi(14) < 45` | 0.12 | 0.20 | 120 | 3 x 0.30 | pairs-rotation |
| `ctrend` | `base/C-trend.json` | `close > sma(200) and ema(20) crosses_above ema(50)` | `ema(20) crosses_below ema(50)` | 0.12 | -- | 120 | 5 x 0.18 | trend |
| `bmom` | `base/B-momentum.json` | `ema(20) crosses_above ema(50) and close > sma(200)` | `close crosses_below sma(200)` | 0.12 | -- | 180 | 6 x 0.15 | momentum |
| `i13f` | `candidates/I-13f-duquesne-2026q2.json` | `close > sma(50) and close > sma(200) and rsi(14) > 50` | `close crosses_below sma(50)` | 0.12 | -- | 120 | 6 x 0.15 | momentum |

`b3` and `bmom` share a byte-identical thesis, entry, exit, stop and hold in the library -- they differ
only in `max_positions`/`position_pct` (4 x 0.22 vs 6 x 0.15), the concentration question that card's
own `falsification` field already names as unsettled. Round 48 carries both through unchanged, because
resizing is a different question from concentration and the round measures it on both.

**Universe, per base, read verbatim (not a shared pool this round chose):**

- `b3`/`bmom`: `NVDA AMD AVGO MU MRVL TSM META MSFT GOOGL NOW AMZN NFLX` (12 names, identical set)
- `arot`: `MU INTC AMD TSM SOXX NVDA AVGO QCOM MRVL` (9 names)
- `ctrend`: `NVDA AVGO TSM ORCL SOXX NFLX MU META QCOM` (9 names)
- `i13f`: `GOOGL AMD EQIX LLY RDDT IREN AMZN TSM` (8 names)

Every arm on a base runs on that base's own universe, unchanged -- this round does not move any card
onto a shared pool the way round 45 did for its three bases.

`rank_by = None` on every cell (none of the five library cards sets it). `purpose = trading`,
`designed_through = DESIGN_THROUGH` (2026-02-13) on every cell, stated explicitly rather than left to
default.

### The `risk1pct` arm -- `position_pct = 0.01 / stop_loss_pct`, quantised to 3dp

**Every one of the five seated bases carries `stop_loss_pct = 0.12`.** This round did not choose that
-- the library did -- and it means `risk1pct`'s pinned position size is the identical `0.083` on every
base:

| base | stop | base position_pct x slots | `risk1pct` position_pct (0.01 / stop, 3dp) | risk1pct x slots |
|---|---|---|---|---|
| `b3` | 0.12 | 0.22 x 4 = 0.88 | 0.083 | 0.083 x 4 = 0.332 |
| `arot` | 0.12 | 0.30 x 3 = 0.90 | 0.083 | 0.083 x 3 = 0.249 |
| `ctrend` | 0.12 | 0.18 x 5 = 0.90 | 0.083 | 0.083 x 5 = 0.415 |
| `bmom` | 0.12 | 0.15 x 6 = 0.90 | 0.083 | 0.083 x 6 = 0.498 |
| `i13f` | 0.12 | 0.15 x 6 = 0.90 | 0.083 | 0.083 x 6 = 0.498 |

Every product is comfortably under 1 (`round48.py::_risk1pct_card` asserts this before returning the
card, and `StrategyCard`'s own `_position_sizing_is_a_fraction_of_one` validator asserts it again at
construction). The resizing is a much larger relative cut on `arot` (0.30 -> 0.083, a 72% reduction)
than on `bmom`/`i13f` (0.15 -> 0.083, a 45% reduction) -- prediction 4 below is built to read that
gradient, not to expect one uniform effect.

### The parameter budget (`PROTOCOL.md` section 3 rule 3 -- ten free numbers per card)

Counted by `round48.free_numbers`, the identical convention rounds 35/36/40/42/45 use. **Measured
2026-09-09, matches the tool's own printed table exactly:**

| card | free numbers | card | free numbers |
|---|---|---|---|
| `r48-b3-base` / `r48-b3-risk1pct` | 7 | `r48-ctrend-base` / `r48-ctrend-risk1pct` | 7 |
| `r48-arot-base` / `r48-arot-risk1pct` | 10 | `r48-bmom-base` / `r48-bmom-risk1pct` | 7 |
| | | `r48-i13f-base` / `r48-i13f-risk1pct` | 7 |

`risk1pct` never changes an entry/exit literal, so its free-number count equals its base's exactly on
every card (`tests/test_round48_field.py::test_risk1pct_free_number_count_equals_its_base`).
`r48-arot-*` sits exactly at the budget ceiling of ten (`rsi(14)` reused twice plus `50`, `55`, `80`,
`45` are five distinct entry/exit values, two brackets present -- stop and take-profit -- plus the
hold cap is a third, plus the flat +2 for slots/position = 5 + 3 + 2 = 10); every other card is at 7,
well under it. No card exceeds the budget.

## 3. Reachability, drift and provenance

**Reachability is inherited, not re-measured.** Round 45's bar-store firing-rate probe exists to catch
a *newly written* expression that might be structurally unreachable -- the motivating defect was a
4-sigma Bollinger threshold that could never fire. That is not this round's risk: all five bases here
are cards that have already run in rounds 24 and 26 and trade live on the paper desk today. What
`round48.py --write` does instead: parses every entry/exit with the real grammar
(`app.rules.grammar.parse`) and recomputes the live roth union from disk
(`round48.roth_union`, identical helper to `round45.py`'s), refusing to write if the round's taxable
universes intersect it. **Measured 2026-09-09: every one of the 10 cells' entry and exit parses
cleanly, and the roth union (21 tickers, recomputed from `app.evolution.promotion._library_cards`)
intersects this round's universes in nothing.**

**There is no drift check, by construction.** Round 45 pinned each base's fields as a literal table and
then asserted that table against its source (`check_drift()`), because a stale pasted constant could
silently retest a different card than the one measured. Round 48 has no such table to go stale --
`build()` reads `json.loads` on the library file directly every time it runs, so what it writes is
*always* whatever the library currently says, not a snapshot. The cost of that: if a concurrent session
edits one of these five files between the plan being written and `--write` being run, the round would
silently measure the new version. `tests/test_round48_field.py::test_base_cell_matches_library_file_
verbatim` re-reads the library file itself at test time for the same reason -- it cannot go stale
either.

**`i13f`'s provenance is a special case, and its treatment is disclosed here rather than assumed away.**
`I-13f-duquesne-2026q2.json` carries `desk_only: true` and `designed_through: 2026-08-14` in the
library -- the mechanism `backend/app/tournament/models.py` currently uses to express "this basket
became knowable on 2026-08-14, after the tournament's design cutoff", not the
`universe_knowable_from` field `PROTOCOL.md` section 9's r2 amendment describes (that field does not
exist on the current `StrategyCard` model; `strategy-program/tools/windows.py::resolve_universe_
knowable_from` confirms this by checking for it via `getattr` and falling back to a sidecar file when
absent). **`StrategyCard.model_validate_json` accepts the library file exactly as it stands on disk**
(checked directly, 2026-09-09: `desk_only=True`, `purpose` defaults to `trading`, no other issue) --
but `desk_only=True` cannot enter a tournament round: `app.tournament.jobs._resolve_cards` refuses any
explicitly named `desk_only` card outright. A card refused from the round entirely is not the same
finding as a card that is unranked on early windows and ranked on late ones, and this round wants the
latter -- whether the resizing does anything on `i13f`'s own eligible windows is exactly the question
under test. So `round48.py` overrides `desk_only=False` and pins `designed_through=DESIGN_THROUGH`
like every other cell, and writes the filing date (2026-08-14) into
`data/rounds/r48-2026-09/cards/provenance.json` -- the sidecar `windows.py` already reads for a card
whose model carries no `universe_knowable_from` field. **This is the honest treatment**
(`PROTOCOL.md` section 5's provenance-by-code rule and section 9's r2 amendment): the basket's
point-in-time constraint is preserved and enforced by the scorer, not silently dropped by making the
card unable to run at all. Every one of `WINDOWS.md`'s eight main windows starts well before
2026-08-14, so **`i13f`'s two cells are expected `UNRANKED` on every main window in this round's
matrix** -- reported as a fact about provenance, not interpreted as a finding about the resizing
(prediction 7).

## 4. Windows, metric, decision rule

**Windows:** the standard eight-window main matrix (`WINDOWS.md`): `q4-2018`, `covid`, `bear-2022`,
`chop-2015`, `chop-2011`, `bull-2024`, `recent`, `gfc`. `b3`/`arot`/`ctrend`/`bmom` are expected 8-of-8
eligible (their universes are the same large-cap tech/semiconductor names rounds 24/26/40/42 already
ran on this history). `i13f` is expected unranked on all eight by provenance (section 3).

**Metric:** median exposure-adjusted excess across a card's eligible main windows, `adjusted_excess =
strategy_return - capital_exposure x benchmark_return` (`score.py`'s primary key, benchmark SPY).
Scored with `--pin-store`.

**Decision rule, pre-registered:**

> `risk1pct` earns something only if its **marginal** -- the mean over the five bases of (risk1pct
> median adjusted excess minus that base's own median) -- exceeds the **21.2pp noise floor**
> (`PROTOCOL.md` section 7) **AND** every one of its five arm cells survives **BH q < 0.10** with the
> denominator **m = 10** (base cells carry p = None but still occupy a seat in m), where each
> `risk1pct` cell is contrasted with its own base, never a shared reference.
> `strategy-program/tools/round48_report.py::bh_m10` builds that 10-entry p-value list (five `None`s
> for the bases, five per-base contrast p-values for the `risk1pct` cells) and calls
> `app.backtest.scan.benjamini_hochberg` directly, exactly as `round45_report.bh_m14` does for its own,
> differently-shaped field.

**Nothing here is promotable.** `PROTOCOL.md`'s r21 amendment: section 6's promotion rule does not
apply to the `trading` purpose, and no replacement gate was built. This round reports; it does not
seat, unseat, or resize anything on the live desk. **A decision to resize a seated card for real is
the owner's, about risk, not a scorecard's** -- this round measures what that decision would have
cost and bought on the same eight-window history the cards already trade against, it does not make the
decision.

**PROTOCOL.md section 4's caveat, applied in advance.** "The worst-window criterion favours small
books... frontier membership earned mainly on that axis must be read with the card's exposure in
view." Every `risk1pct` cell here runs a strictly smaller book than its base (section 2's table) except
where `position_pct x slots` was already close to 0.90 and stays close after the cut -- a shallower
worst window on `risk1pct` is therefore expected on size grounds alone, not necessarily evidence the
sizing changed anything about the *rule*. `round48_report.py::dollar_worst_window_table` prints each
cell's worst window's realised P&L **in dollars**, read from the run files' trade logs, beside the
scorecard's own `total_realised_pnl` for the full eight-window matrix, so this round's report makes the
size effect visible in currency rather than only in percentage points that already bake the correction
in.

## 5. Falsifiable predictions

Each card carries these in its `falsification` field; `round48_report.py` prints prediction beside
outcome.

1. **Null on the median marginal** (`|marginal| < 5pp`) -- round 45 measured the sizing at -1.35pp of
   median on the one card it ran it on; this round expects the same order of magnitude across five
   more, not a large positive or negative shift.
2. **Worst window shallower (less negative) on at least 4 of the 5 bases** -- the resizing cuts the
   largest single-position risk on every base (section 2's table), and round 45 measured this
   direction on both cards it tested (`kim` -17.21pp -> -11.41pp, `creator-b` roughly halved).
3. **IQR narrower on at least 4 of 5** -- the same mechanism (a smaller book has less to lose or gain
   in any one window) that round 45 measured on `kim` (8.3pp -> 5.7pp).
4. **Mean exposure lower on 5 of 5** -- `position_pct` falls on every base here (0.72x on `arot` to
   0.55x on `bmom`/`i13f`), and capital exposure is close to linear in position size for a card that is
   not already capped by how few names qualify each session.
5. **Per-window sign pattern identical on at least 7 of 8 windows for every base** -- resizing changes
   how much a card wins or loses by, not which windows it wins in for a rule that has not otherwise
   changed. Round 45 measured 8/8 on `kim`, 7/8 on `creator-b`.
6. **Adjusted excess per unit exposure within +/-3pp of the base on every base** -- sizing is not
   alpha; if the resizing moved the *scale-free* return meaningfully, that would be a different and
   much more surprising finding than "the book got smaller."
7. **`i13f` cells UNRANKED by provenance on the main windows** -- reported as a fact about the
   filing-date sidecar (section 3), not interpreted as a resizing finding one way or the other.
8. **PROTOCOL.md section 4's small-book caveat holds, and the dollar table makes it visible.** A
   shallower worst window in percentage points on `risk1pct` is expected to coincide with a smaller
   absolute-dollar worst-window loss too, but the two need not move by the same *proportion* --
   `round48_report.py`'s dollar table is descriptive, not a sixth pass/fail prediction with its own
   threshold.

**Degenerate-outcome guard**, carried from round 45's own prediction 7: a cell running at low slot
counts (`arot` at 3 slots) or a short universe (`i13f` at 8 names) could fail the 5-of-8 regime gate in
a thin window and be reported unranked for reasons unrelated to the resizing -- that is "switched off",
not "the resizing did not help", and `round48_report.py` must not conflate the two.

## 6. What this round cannot settle

- **It is five cards' own universes, not a shared pool** -- unlike round 45, this round does not
  standardise onto one universe to make bases comparable to each other, because no cross-base
  comparison is made; every contrast is arm-vs-own-base. That also means the five bases are not
  independent draws on the same history -- `b3`/`bmom` share a universe and an entry/exit, `arot`/
  `ctrend`/`i13f` overlap heavily in names (semiconductors and mega-cap tech).
- **`i13f`'s desk_only override is a round-only construction.** The seated library card stays
  `desk_only=True`, unedited; round 48's `r48-i13f-*` cells exist only under `data/rounds/r48-2026-09/
  cards/` with the override disclosed above, and nothing here changes what the live desk actually
  trades or how it is scored there.
- **It cannot promote or seat anything** -- `PROTOCOL.md`'s r21 amendment: the `trading` purpose is
  exempt from section 6 promotion, and this round is a measurement study regardless.
- **A resizing that "pays for itself" by this round's floor-and-BH rule is still not evidence the rule
  itself has edge** -- prediction 6 exists precisely because sizing and alpha are different claims, and
  a round that found sizing moved per-unit-exposure returns materially would need a harder look before
  being read as anything other than a measurement artifact.
- **It is price-only and dividend-free**, like every backtest in this programme.
- **A null here refutes this one resizing rule on these five books, not "1% risk sizing" in general** --
  a different quantisation, a different stop convention, or a rule that also resizes on realised
  volatility rather than the fixed stop could behave differently.

## 7. Run recipe (to execute after freeze -- NOT run by this document or by the agent that wrote it)

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round48.py --write
bash strategy-program/tools/run_round.sh data/rounds/r48-2026-09/cards data/rounds/r48-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \
    --results data/rounds/r48-2026-09/results --json data/rounds/r48-2026-09/scorecard.json --pin-store
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round48_report.py
```

The first line has been run to produce sections 2-3's measured tables and the 10 cards (plus
`provenance.json`) under `data/rounds/r48-2026-09/cards/`. The remaining three lines -- the actual
backtest, the scorecard and the computed report -- have **not** been run as part of authoring this
round; they are the next session's or the owner's to execute. This document does not run
`run_round.sh`, `app.tournament`, or `score.py`, and makes no commit.
