# Round 47 — do "accumulate on pullbacks, then hold" or "buy weakness, sell strength" beat holding
round 44's baskets passively?

**Pre-registered 2026-09-09, before any card in this round has been run.** As of this writing
`data/rounds/r47-2026-09/cards/` holds no card, there is no `data/rounds/r47-2026-09/results/` and no
scorecard. This is round 47 of `MIX-AND-MATCH-PLAN.md` section 3's three rounds (45, 46, 47), authored
alongside two other agents building rounds 45 and 46 concurrently — this plan, `round47.py`,
`round47_report.py`, `tests/test_round47_field.py` and `data/rounds/r47-2026-09/cards/*.json` are this
round's own scope and touch no file any other round's agent owns.

**Not investment advice.** Every number this round will produce is a backtest on price-only bars with
no dividends, measured against SPY for a Roth book that holds neither SPY nor anything cap-weighted
large-cap-growth. No influencer named below is endorsed; these are tests of the *cheapest expressible
portfolio proxy* for something a persona said, not of the person or the claim as they intended it.

---

## 1. The question, and why it is not a re-run of round 44

Round 44 measured, on five baskets including three of this round's four candidates — `control`,
`power`, `defense` (the other two, `semicap` and `realassets`, are out of scope here) — whether holding
the basket passively beats a broad control, and whether Creator B's profit-trim
(`close > sma(200) * 1.15` on both sides) beats holding the basket passively. Both were null. This
round reuses that field's `power`, `defense` and `control` baskets **verbatim**, and reuses the
`passive` and `trim` arms **verbatim** — nothing about the basket construction or those two rules is
re-decided here; both are asserted against round 44's on-disk cards and the tool refuses to write on
any drift (§7).

What is new is the *entry* side of two personas' stated methods, never tested as a held-basket entry
before (`MIX-AND-MATCH-PLAN.md` §2's inventory table, "accumulate on dips inside an uptrend" row:
"never as a held-basket entry"):

- Creator C's and Creator A's "accumulate on a pullback inside an uptrend, then hold" — expressed
  as `close < sma(50) and close > sma(200)`: below the 50-day mean (a pullback) but still above the
  200-day mean (still the uptrend that makes it a pullback rather than a trend break). Paired with
  round 44's structurally-never-true `close < 0` exit, so a filled slot stays filled — "then hold" is
  literal, not a description.
- The same entry paired with round 44's trim exit instead of never: "buy weakness, sell strength", Creator B's and Creator C's/Creator A's disciplines combined in one card.

Round 44's own field never tested an entry filter — both its arms enter unconditionally (`close > 0`)
and differ only on exit. This round is the first in the programme to gate entry into a *held* thematic
basket on a moving-average pullback condition, and the first to combine that gate with a trim exit.
Twelve cells: three baskets (reused) × four arms (`passive`, `dip`, `trim` — all reused or their exit
already measured — and `dip-trim`, entirely new).

## 2. The universe — round 44's, reused verbatim

**Twelve names, three baskets of four.** No re-derivation, no re-justification: `ROUND-44-PLAN.md`
§2 is the sourcing document for what each basket is and why (`power` = Creator A's/Creator D's
electricity-infrastructure thesis; `defense` = Creator A's defense-spending pillar; `control` = round
39's own value+growth pool, collapsed). This file only asserts the reuse is exact.

| basket | names |
|---|---|
| `power` | `NEE DUK SO CCJ` |
| `defense` | `LMT NOC GD RTX` |
| `control` | `VTV SPYG RSP MDY` |

**`semicap` (`AMAT KLAC LRCX ASML`) and `realassets` (`XOP XME EWY VWO`) are out of scope.** Round 44
found both baskets' positive figures were entirely a hindsight artefact of the two 2024-26 windows
(semicap: +0.39pp fair vs +68.68pp hindsight; realassets: −5.39pp fair vs +20.38pp hindsight), so this
round's pinned field does not extend the arm axis onto them — see `MIX-AND-MATCH-PLAN.md` §3's round 47
row, which names only `control`, `power`, `defense`.

### 2a. Disjointness — recomputed live, not re-quoted from round 44

Round 44's §2a established that none of these twelve names (a subset of its twenty) is claimed by any
`savings`- or `trading`-purpose card, and disclosed that none of `power`/`defense`/`control`'s eight
non-control-overlapping names are claimed by any *other* roth-purpose card either (unlike `semicap` and
`realassets`, whose overlap this round does not inherit because it does not trade those baskets). This
plan does not trust that as a standing fact: `round47.py` recomputes both checks live through
`app.evolution.promotion._library_cards` (all six tiers) and `app.tournament.purposes.
find_disjointness_violations`, exactly as round 44 did, because two other sessions are editing this
repository concurrently and a library snapshot is correct only until the next commit. Confirmed
2026-09-09: `set(TRADED) & taxable == set()`, twelve of twelve, zero violations.

## 3. The field — 3 baskets × 4 arms = 12 cells

**The four arms**, applied identically across every basket:

```
passive:   entry "close > 0"                              exit "close < 0"
                                                            (round 44's control expressions, verbatim)

dip:       entry "close < sma(50) and close > sma(200)"    exit "close < 0"
                                                            (new entry; round 44's never-true exit —
                                                             "accumulate, then hold" is the exit
                                                             choice, not a placeholder)

trim:      entry "close < sma(200) * 1.15"                 exit "close > sma(200) * 1.15"
                                                            (round 44's trim expressions, verbatim)

dip-trim:  entry "close < sma(50) and close > sma(200)"    exit "close > sma(200) * 1.15"
                                                            (the dip entry, round 44's trim exit)
```

Every card: `max_positions = 4`, `position_pct = 0.25` (100% of capital deployed when fully invested,
identical to every arm in round 44), `rank_by = None` (a slot for every name), no stop, no target, no
time stop on any arm — the same one-decision discipline `PROTOCOL.md` §7 requires and round 44 already
applied to `passive`/`trim`; extended here to `dip`/`dip-trim` so `dip − passive`, `trim − passive` and
`dip-trim − passive` are each an attribution to exactly one rule change.

**Disciplines.** `ruleforms.classify` reads the entry first and only consults the exit when the entry
names nothing (`classify`'s own docstring). Four findings, two reused and two new, all asserted at
import time in `round47.py` rather than merely stated here:

| arm | `classify()` result | label used | how it was decided |
|---|---|---|---|
| `passive` | `None` | `Discipline.TREND` | **Forced**, reused from round 44 — the same least-wrong label round 39's and round 44's passive controls carry (a rule with no indicator classifies as nothing). |
| `trim` | `None` | `Discipline.RISK_MANAGED` | **Forced-but-genuine**, reused from round 44 verbatim — not a `classify()` result either, but round 44's own judgement that the rule is a profit-taking/exposure-reduction discipline on a held position, exactly `Discipline.RISK_MANAGED`'s docstring, not a directional entry signal. |
| `dip` | `Discipline.TREND` | `Discipline.TREND` | **Genuine** — `classify()` actually returns `TREND` for `close < sma(50) and close > sma(200)`, not a forced default. Verified, not assumed. |
| `dip-trim` | `Discipline.TREND` | `Discipline.TREND` | **Genuine**, for the identical reason as `dip`: `dip-trim` shares `dip`'s entry verbatim, and `classify()` never reaches the exit once the entry already names something. |

So this round's choice, stated as the brief required: **`dip` and `dip-trim` reuse `TREND` — not
because it was copied from `passive`, but because `classify()` independently returns it for the new
entry expression both arms share.** `trim`'s `RISK_MANAGED` is reused unchanged from round 44 because
`trim`'s rule text is unchanged from round 44.

### 3a. Support / reachability probe — re-measured 2026-09-09, none fire zero times

Measured by `round47.py`'s dry run through `app.market.store.read_frame` (in-memory, no file lock) and
`app.rules.evaluate.evaluate` on `app.rules.grammar.parse(...)` for both the dip entry and the trim
exit — bounded to `DESIGN_THROUGH` (2026-02-13), the identical method round 40's and round 44's
reachability probes use:

| symbol | basket | first bar | sessions | dip entry fires | dip support | trim exit fires | trim support |
|---|---|---|---:|---:|---:|---:|---:|
| `NEE` | power | 1973-02-21 | 13,359 | 2,143 | 16.0% | 986 | 7.4% |
| `DUK` | power | 1980-03-17 | 11,573 | 1,906 | 16.5% | 530 | 4.6% |
| `SO` | power | 1981-12-31 | 11,120 | 1,833 | 16.5% | 426 | 3.8% |
| `CCJ` | power | 1996-03-14 | 7,529 | 956 | 12.7% | 2,149 | 28.5% |
| `LMT` | defense | 1970-01-02 | 14,150 | 2,348 | 16.6% | 2,742 | 19.4% |
| `NOC` | defense | 1981-12-31 | 11,120 | 1,832 | 16.5% | 2,082 | 18.7% |
| `GD` | defense | 1970-01-02 | 14,151 | 2,165 | 15.3% | 3,180 | 22.5% |
| `RTX` | defense | 1970-01-02 | 14,151 | 2,289 | 16.2% | 2,545 | 18.0% |
| `VTV` | control | 2004-01-30 | 5,546 | 864 | 15.6% | 157 | 2.8% |
| `SPYG` | control | 2000-10-02 | 6,380 | 864 | 13.5% | 329 | 5.2% |
| `RSP` | control | 2003-05-01 | 5,735 | 885 | 15.4% | 320 | 5.6% |
| `MDY` | control | 1995-05-04 | 7,747 | 1,292 | 16.7% | 519 | 6.7% |

The trim-exit column reproduces round 44's own §3a figures for these twelve names exactly (NEE 7.4%,
DUK 4.6%, SO 3.8%, CCJ 28.5%, LMT 19.4%, NOC 18.7%, GD 22.5%, RTX 18.0%, VTV 2.8%, SPYG 5.2%, RSP 5.6%,
MDY 6.7%) — expected, since `trim` is the same expression on the same bars. **Minimum dip-entry support
in the field is `CCJ` at 12.7% (956 fires); minimum trim-exit support is `VTV` at 2.8% (157 fires).
Neither condition fires zero times for any name, so the round is not refused.** Dip-entry support
clusters tightly (12.7%–16.7% across all twelve names, mean ≈15.6%) — a pullback-inside-an-uptrend
condition is a much more evenly-distributed regime than the trim's extension condition, which the
support table's own spread (2.8%–28.5%) already showed in round 44.

`round47.py --write` **refuses to write** if the dip entry or the trim exit fires zero times for any
name, and separately refuses on any drift between this round's `passive`/`trim` cards and the
corresponding cards on disk in `data/rounds/r44-2026-09/cards/` (§7) — reusing round 40's reachability
gate and adding a reuse gate round 44 did not need (round 44 had nothing to reuse from).

### 3b. Free-parameter budget (`PROTOCOL.md` §3 rule 3 — ten per card)

Same derivation `round39.py`/`round40.py`/`round44.py` use: distinct numeric values across
`entry`/`exit`/`rank_by`, plus one per present bracket, plus two for `max_positions`/`position_pct`:

| cell | free numbers |
|---|---|
| `r47-<basket>-passive` (3 cells) | **3** — `{0}` + slot count + position size |
| `r47-<basket>-trim` (3 cells) | **4** — `{200, 1.15}` + slot count + position size |
| `r47-<basket>-dip` (3 cells) | **5** — `{50, 200, 0}` + slot count + position size |
| `r47-<basket>-dip-trim` (3 cells) | **5** — `{50, 200, 1.15}` + slot count + position size |

Maximum 5, well under the constitutional bound of 10.

## 4. Windows, metric, decision rule

**Windows.** The standard eight-window matrix: `q4-2018`, `covid`, `bear-2022`, `chop-2015`,
`chop-2011`, `bull-2024`, `recent`, `gfc`. All twelve cards are eligible in 8 of 8 (`disjoint_field.py`
check 3, run after `--write`).

**Metric.** `PROTOCOL.md` §4's primary key, median `adjusted_excess` across a card's eligible main
windows, against the `roth` purpose's SPY benchmark. As round 44 §4 already established: neither
`power` nor `defense` is a US large-cap-growth book, so a raw SPY-column reading is not this round's
decision quantity for those two baskets. The decision quantity here is **arm-minus-passive within
basket**, which is unaffected by the SPY confound the same way round 44's basket-minus-control and
trim-minus-passive contrasts were.

**Decision rule, pre-registered:**

- **An arm edge** only if `median(r47-<basket>-<arm>) − median(r47-<basket>-passive) > 21.2` **AND**
  BH q < 0.10 over all 12 cells this round runs, correction against `r47-control-passive` (the same
  single-reference BH design round 44 used).
- **The noise floor is 21.2pp** (`PROTOCOL.md` §7), not a per-round quantity and not relitigated here.
- **Pre-registered prediction: null on every arm** (§5 #1). Forty-six prior rounds have found every
  basket-composition, timing-rule and now entry-filter margin this programme has ever measured inside
  the floor; the honest prior for this round's nine non-passive cells is the same.
- **Promotion.** `PROTOCOL.md` §6 applies to `roth`. This is pre-registered as a measurement round:
  **nothing is promoted from it regardless of outcome.** Any later promotion of a cell measured here
  requires two consecutive qualifying rounds on window sets that differ, with margins outside the floor
  in both — the same bar `r34-ma-crossover-on` and `r40-rsi-confirm-slots6` did *not* clear before
  being seated by direction, and this round does not ask for that exception.

## 5. Falsifiable predictions, fixed before any run

1. **Null on every arm.** No arm beats its own basket's passive control by more than 21.2pp on median
   adjusted excess with BH q<0.10, in any of the three baskets. Predicted to hold for all nine
   non-passive cells.
2. **The dip arms' gap from passive is mostly the entry delay, not the pullback condition.** `dip` and
   `dip-trim` sit out the start of every window until the first qualifying pullback (`close < sma(50)
   and close > sma(200)`), so their session exposure is predicted below the passive arm's in every
   basket and window, and their adjusted-excess difference from passive is predicted to track that
   entry lag rather than a distinct timing edge. `round47_report.py` prints days-to-first-entry — the
   first trade's `entry_date` minus the window's own start date — per window, for both dip-entry cells
   in every basket, computed from the run files (`results/<window>/runs/r1-<agent_id>.json`), not
   asserted from the scorecard alone.
3. **`dip-trim` has the lowest exposure of its basket's four arms, in every basket.** It carries both
   restrictions the other three arms carry only one or none of — an entry gate *and* an early exit — so
   its mean session exposure is predicted to be the minimum of `{passive, dip, trim, dip-trim}` in
   `power`, `defense` and `control` alike.
4. **Trim loses to passive in `bull-2024`; `recent` is not predicted.** Round 44 found the trim arm
   underperforms its own passive control in `bull-2024` in every basket, but *beats* it in `recent` for
   `power` (+1.37pp) and `defense` (+1.94pp) — a sustained-uptrend prediction that held in one 2024-26
   window and was refuted in the other. This round pre-registers `bull-2024` (predicted: trim loses,
   again) and `recent` (no directional prediction — round 44's own split result means either sign is
   consistent with the prior) as two separate, separately-reported quantities for the same three arms,
   rather than repeating round 44's since-refuted single prediction across both.
5. **The combination is not better than the better of its parts.** `dip-trim − max(dip, trim) ≤ 0` in
   at least two of the three baskets, on median adjusted excess. A card that both filters entry and
   trims exit carries two restrictions where each component carries one; predicted to not out-earn
   whichever single restriction performed better alone, in most of the field.
6. **Hindsight caveat, restated from round 44.** Every note in the persona corpus has `published =
   null` (`PERSONA-HYPOTHESES.md` §2, §7): the personas' methods were voiced in 2025-26 with 2023-25
   returns already known to the speaker. `bull-2024` (2024-08-21→2025-08-20) and `recent`
   (2025-08-21→2026-08-18) are therefore **in-sample to the hypothesis**, and `round47_report.py`
   computes and reports the arm-minus-passive margin on the six windows ending by 2022-10 (`gfc`,
   `chop-2011`, `chop-2015`, `q4-2018`, `covid`, `bear-2022`) separately from the full eight and from
   the two 2024-26 windows alone — the identical split `round44_report.py` computes, reused unchanged.
   Predicted: no arm clears the floor on the six-window fair subset either.
7. **Validity check, not a hypothesis.** The `passive` arm in every basket holds all four names on
   essentially every session of every eligible window (round 44 §5 prediction 7 already confirmed this
   for `power`, `defense`, `control` — exposure 0.956–0.990). If that is no longer true — it should not
   have changed, since the `passive` cards are asserted byte-identical to round 44's — every contrast
   in this round drawn against it is void.

## 6. What this round cannot settle

- **The causal story behind either persona's method.** "Accumulate on pullbacks inside an uptrend" and
  "trim on extension, then re-enter" are neither of them testable causal claims with OHLCV bars — this
  round tests whether four survivor tickers, entered and/or exited on these rules, produced a return
  pattern, not whether either discipline is sound trading practice in general.
- **Survivorship**, restated from round 44 unchanged: all twelve names are today's survivors.
- **The SPY-benchmark confound**, restated: neither `power` nor `defense` is US large-cap growth, so
  the raw `adjusted_excess vs SPY` column is not the decision quantity for either basket; only
  arm-minus-passive is.
- **"The theme", as opposed to these four names**, restated from round 44 unchanged.
- **Ticker disjointness is necessary, not sufficient, under IRC §1091** (§2a) — this establishes no
  identical security is repurchased across books; it is not a tax-safety finding.
- **Price-only bars. No dividends.** `power`'s two regulated utilities (`NEE`, `DUK`) and `defense`'s
  primes are all above-average-yield sectors — the same distortion round 44 §6 named, unchanged here
  because the same names and the same benchmark are in use.
- **A single dip threshold and a single trim threshold, each chosen once.** `50`/`200` for the dip
  filter and `1.15` for the trim are round-number choices disclosed as support-of-regressor reads
  (§3a), not outcome reads; this round does not claim either is insensitive to its exact value, only
  that neither is unreachable.
- **One round is one draw.** `PROTOCOL.md` §6(a): a positive result here, on these eight windows, is
  not evidence on windows this round did not run. Nothing is promoted from a measurement round
  regardless of outcome (§4).

## 7. Determinism, scope and the run recipe

**Determinism.** `round47.build()` reads no clock, no filesystem and no randomness, so calling it twice
returns field-identical cards (`tests/test_round47_field.py::TestDeterminism`). Only the reachability
probe, the drift check and the disjointness check read live state on purpose (the bar store, round 44's
on-disk cards, and the library on disk, respectively) — the same design `round39.py`/`round40.py`/
`round44.py` use, for the same reason: a pasted constant is correct only until the next commit or bar-
store refresh.

**Reuse, not re-derivation — asserted, not assumed.** `round47.check_r44_drift()` loads
`data/rounds/r44-2026-09/cards/r44-<basket>-passive.json` and `r44-<basket>-trim.json` for `power`,
`defense`, `control` and compares `entry`, `exit`, `max_positions`, `position_pct` and `universe`
field-for-field against this round's own `passive`/`trim` cards. Any mismatch is a refusal to write,
printed alongside the reachability and disjointness refusals in the same list — this round does not
retype round 44's rules on trust.

**Scope.** This round owns `strategy-program/ROUND-47-PLAN.md`, `strategy-program/tools/round47.py`,
`strategy-program/tools/round47_report.py`, `data/rounds/r47-2026-09/cards/*.json` and
`tests/test_round47_field.py`. It modifies no library card, no shared tool
(`strategy-program/tools/round34_36_report.py` and `strategy-program/tools/windows.py` are imported by
file path, not edited), no round 44 file, no round 45/46 file (authored concurrently by other agents)
and no other document in this directory.

**The run recipe** (not executed as part of this pre-registration — this session's brief explicitly
excludes running `run_round.sh`/`score.py`/`app.tournament`):

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round47.py --write
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/disjoint_field.py --cards data/rounds/r47-2026-09/cards
bash strategy-program/tools/run_round.sh data/rounds/r47-2026-09/cards data/rounds/r47-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \
    --results data/rounds/r47-2026-09/results --json data/rounds/r47-2026-09/scorecard.json --pin-store
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round47_report.py
```

**Not investment advice.** Every figure this round produces, once run, will be a backtest on
price-only bars against a benchmark this plan has already flagged as a poor fit for two of its three
baskets. Nothing here is a recommendation to buy, sell or hold `NEE`, `DUK`, `SO`, `CCJ`, `LMT`, `NOC`,
`GD`, `RTX`, `VTV`, `SPYG`, `RSP` or `MDY`.
