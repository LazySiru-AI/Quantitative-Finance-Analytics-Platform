# Round 21 — does a macro series available *at decision time* change a card's result?

Pre-registered 2026-08-29 as round 20; **renumbered to 21 on 2026-08-30**, when a concurrent
session committed a different round 20 (the D8 band-funding fix, `ROUND-20-PLAN.md`) over this
document. Nothing in the design below changed with the number -- the original is preserved at
commit `885f410` -- and the renumber is recorded rather than done silently, because a
pre-registration whose identity moves without explanation is not much of a record.

Before any card in this round has been run, before the engine change it
depends on has been written, and before any macro series has been pinned for it. Nothing below was
written with sight of a result, because no result can exist yet — the load-bearing work is the engine
change in §2, and this round is the test of whether that work bought anything.

**Not investment advice.** Price-only bars plus one macro scalar, no dividends.

---

## 1. The question, stated so it can be answered "no"

**Does a macro series that was actually knowable at the moment a card made its decision change that
card's result by more than this round's own pre-registered noise floor?**

A "no" is not a failed round. `docs/research/programme/00-EVERYTHING-TESTED.md` §1 records the honest
count going in — **~50 concepts, near-zero survivors** — and this round adds one more concept to that
ledger rather than starting a new one. It is worth running for a reason unrelated to the odds: **the
class has never been reachable.** §3b's table is blunt about the current state:

| data | status |
|---|---|
| FRED macro series (rates, curve, energy) | collected, displayed, **unreachable by any card** |
| Fear & Greed | collected, displayed, **unreachable** |
| Event calendar (FOMC, releases, earnings) | collected, displayed, **unreachable** |

and its recommendation #4 is this round's mandate:

> "Give the DSL one non-price field. A single market-regime input would open the cross-symbol regime
> class that an analyst abandoned. This is the highest-leverage expressiveness change after (2)."

`strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` §6 records the owner asking for exactly this.

---

## 2. The engine change — a new node, bound by release date

This is the round's real content. §3–§7 mean nothing if this section is built wrong, and getting it
wrong is a larger risk than finding nothing.

### 2a. Which series, and what was actually checked

Seven candidate series. **All seven were fetched live on 2026-08-29 and returned data** — this is a
direct check, not a recollection:

| series | latest observation | value | history |
|---|---|---|---|
| `DGS10` | 2026-08-27 | 4.67 | daily |
| `T10Y2Y` | 2026-08-28 | 0.39 | daily |
| `T10YIE` | 2026-08-28 | 2.31 | daily |
| `DCOILWTICO` | 2026-08-25 | 83.90 | daily |
| `PCEPI` | 2026-07-01 | 131.659 | 811 monthly obs from 1959-01-01 |
| `PCEPILFE` | 2026-07-01 | 130.658 | 811 monthly obs from 1959-01-01 |
| `CPILFESL` | 2026-07-01 | 336.789 | 834 monthly obs from 1957-01-01 |

**But only four have committed fixtures**, and the gap is this round's first task.
`tests/fixtures/macro/` holds `fred_dgs10.csv`, `fred_t10y2y.csv`, `fred_dcoilwtico.csv` and
`fred_dcoilbrenteu.csv` (plus JSON variants for DGS10). **There is no fixture for `PCEPI`,
`PCEPILFE`, `CPILFESL` or `T10YIE`.** A live check is evidence the endpoint answered today; a
committed fixture is evidence the parser handles that shape and will keep handling it. Capture the
four missing fixtures **before a single card is authored** — cheap, and it is the difference between
a guard resting on repo-recorded evidence and one resting on a changelog line.

### 2b. The node: `MacroRef`, alongside `PriceField`

`app.rules.nodes.PriceField` is the model to follow, including its reason for excluding `adj_close`:
a field whose whole history shifts under you is a field a rule silently changes meaning against. A
sibling enum, **closed at exactly the seven series above** so an eighth is a deliberate act:

```python
class MacroField(StrEnum):
    DGS10 = "DGS10"
    T10Y2Y = "T10Y2Y"
    T10YIE = "T10YIE"
    DCOILWTICO = "DCOILWTICO"
    PCEPI = "PCEPI"
    PCEPILFE = "PCEPILFE"
    CPILFESL = "CPILFESL"

@dataclass(frozen=True, slots=True)
class MacroRef:
    """A FRED series read as of the decision bar, release-date bound. Resolved against
    `app.market.macro_models.MacroSeries`, never against the bar frame `app.rules.evaluate`
    already carries -- a macro series has one row per FRED observation date, not one per
    trading session, and the two are joined explicitly, once, before evaluation."""
    field: MacroField
```

`MacroRef` joins `NumExpr`. `app.rules.grammar`'s `primary` production gains a `macro_field`
alternative beside `price_field` — `"macro" "(" MACRO_ID ")"` — so `macro(DGS10) > 4.5` and
`close < bb_lower(20,2)` are siblings in the grammar rather than a bolt-on. An unknown `MacroField`
is a parse error at load, exactly like an unknown indicator name.

**Deliberately out of scope: a macro value cannot be an argument to an indicator.**
`sma(macro(CPILFESL), 12)` — which is what a stationary transform of CPI actually requires — is not
expressible. The indicator registry operates on the OHLCV frame, and wiring a differently-sampled
external series into it is a second engine change. This round's field is a bare scalar, combinable by
`Arith`/`Comparison`/`Cross` with a `Literal` or a `PriceRef`, and nothing more. §6 records what that
costs.

### 2c. Binding by release date — the part that must not reuse existing code

The trap, precisely: **FRED serves the revised value against the reference date.** Reading
`CPILFESL`'s July observation at 2026-07-31 is lookahead of exactly the kind `CONSTRAINTS.md`
describes for 13F:

> "*Enforced by discipline. Not by code, and it cannot be.* The lookahead guard checks whether an
> indicator is causal on symbols already chosen; it has no way to know when the *basket* became
> knowable."

`PROTOCOL.md` §9 records what happened when that gap was left open: round 1 ranked a 13F card on four
windows predating its own filings, "caught by a reader, not a tool."

**This repository already has a mechanism that looks like the fix and is not one.** Verified
2026-08-29: `app.market.macro._nearest_on_or_before` selects on `point.date <= target` — **the
reference date.** That is correct for the dashboard (a reader asking what the 10-year printed through
June 1st wants the reference date) and is exactly the wrong join for a trading rule. **The evaluator
path for `MacroRef` must not call `_truncate_to_as_of` or `_nearest_on_or_before` as they exist
today.**

The binding:

1. Each `MacroPoint` gets an **eligibility date** = `point.date + lag(series)`, from a fixed,
   disclosed, per-series table:

   | series | lag | basis |
   |---|---|---|
   | `DGS10`, `T10Y2Y`, `T10YIE`, `DCOILWTICO` | 1 trading day | matches the engine's own convention — a signal known after the close is data for the next decision bar at the earliest, exactly like a price signal |
   | `PCEPI`, `PCEPILFE`, `CPILFESL` | **45 calendar days** | **a deliberately conservative placeholder, not a claimed BLS/BEA calendar fact.** Real CPI publishes ~2 weeks after month-end and PCE ~4 weeks; 45 days is chosen for symmetry with the 13F statute's own figure and because it errs toward excluding history, never toward including an unpublished value. Replacing it with the actual release calendars is §6 work this round does not do. |

2. For each bar date `t`, `MacroRef(field)` binds to the most recent `MacroPoint` whose **eligibility
   date** is `<= t` — an as-of join on the shifted date, computed once per card per field before
   evaluation, not per node.

3. **Determinism.** `PROTOCOL.md` §8 requires byte-identical reruns. A macro series is not static the
   way the bar store is: refetching can return revised values against the same reference dates, and
   the mechanism above still resolves those to the same *date*, not the same *value*. **Macro series
   must be pinned at freeze time** into a versioned local snapshot, the discipline `--pin-store`
   already applies to bars. This infrastructure does not exist and is part of the engine change.

### 2d. The guard — a new check, not an extension of the existing one

`app.backtest.guards`'s own docstring states the limit of what it proves:

> "An indicator is causal exactly when its value at bar `t` does not depend on any bar after `t`...
> What this does **not** prove: that the *bars* are point-in-time."

That is the whole problem restated for macro. `_causality_findings` recomputes an indicator on leading
slices of the **bar frame** — a proof about seeds and recursion, meaningless for a `MacroRef`, which is
not computed from bars at all but looked up. Folding `MacroRef` into `_ALLOWED_NODES` without a new
check would make the guard *report success on a node it has no evidence about*.

- `_ALLOWED_NODES` gains `MacroRef`; `MacroField` gets its own allowlist frozenset, mirrored against
  the enum's members by a test, as `_ALLOWED_PRICE_FIELDS` is today.
- A new `required_macro_refs()` walk, parallel to `required_indicator_refs()`.
- A new, independent check — **not** `_causality_findings` — asserting empirically, for every
  `MacroRef` a card actually uses: the eligibility date bound to every scored session is `<=` that
  session's date. This re-derives the guarantee §2c's join is supposed to provide and verifies it
  after the fact rather than trusting the join code.
- A **fail-closed lag-table check**, structurally identical to `_unlisted_node_types()`: a
  `MacroField` referenced without a lag-table entry is a guard failure, never a silent zero-lag
  default. Without it, a series added to the enum and forgotten in the table would bind by reference
  date, and the first sign would be an inflated result rather than an error.

**What this guard cannot enforce**, stated as plainly as `CONSTRAINTS.md` states the 13F version:

- **It cannot verify the lag table is right.** Only that the code respects whatever lag is configured.
  A too-short lag passes the guard and still leaks the future — enforced by discipline, not by code.
- **It cannot see revisions.** If core CPI for July was revised in the September release, the value
  bound to July's eligibility date is the September-revised number, not what printed in mid-August.
  This is a second, independent leak from the lag problem; closing it needs FRED's ALFRED vintage
  archive, which `FredProvider` does not speak. **The release-date check proves lag was respected and
  says nothing about revision — it must not be read as if it did.**
- **It cannot know about an irregular calendar.** A shutdown-delayed release is still treated as
  arriving on schedule. The lag table is a constant, not a calendar.

---

## 3. The design — forms × macro gate, in round 17's shape

**4 forms × 2 gate states = 8 ranked cells.**

| factor | levels | why |
|---|---|---|
| `rule_shape` | `ma-crossover`, `rsi-pullback`, `channel-breakout`, `vol-compression` | a **structurally** chosen subset of round 17's eight — one per entry mechanism the vocabulary contains: a crossing trend rule, a mean-reversion oscillator, a price-structure breakout, a volatility-regime entry. Excluded: `momentum-state`, because round 18 proved its exit **byte-identical** to `ma-crossover`'s, so it is not an independent level; `band-reversion`/`band-breakout` as Bollinger variants of two forms already present; `macd-cross` as an oscillator counterpart of `ma-crossover`. Selected from the taxonomy, **without reference to round 17/18's performance ordering**. |
| `macro_gate` | off / on | on appends `and macro(T10Y2Y) > 0` to the entry |

**Why `T10Y2Y` and not one of the other six.** It is the one candidate that is a *spread* rather than
a trending level. `PCEPI`, `PCEPILFE` and `CPILFESL` roughly triple in nominal terms across this
round's window matrix, and a fixed literal threshold on a non-stationary index is not a regime signal
without the YoY transform §2b puts out of scope. `T10Y2Y` is also the literal proxy for the class this
round exists to open: it applies identically to every symbol on a given date regardless of that
symbol's own price history, which is what makes it a **market-regime overlay** rather than a per-symbol
indicator — the direct descendant of the VIX-gating attempt §3a records as abandoned. `> 0` (curve not
inverted) is set from the concept, not from any return series: zero is the only value on this scale
that is not a parameter choice.

**Held identical across all 8 cells:** fast/slow/regime_ma = 10/30/200; `max_positions` = 6;
`position_pct` = 0.15; `designed_through` = 2026-02-13; bracket = **none**. Brackets are fixed rather
than swept because rounds 17 and 18 measured the marginal at 0.14pp and 0.15pp on independent fields —
the rule's own exit fires first almost every time. *This reuses a finding about brackets, not the
ordering-noise figure §4 declines to reuse.* The regime filter stays on in every cell, on round 17's
0.26pp marginal.

**Reproduction check, free.** The `ma-crossover`/gate-off cell is byte-identical in construction to
round 17's `ma-crossover-on-none` and round 18's reproduction of it. **If it does not match both to
the digit, the instrument moved and every comparison here is suspect** — the same check round 18 ran
against round 17.

**Parameter budget** (§3 rule 3, ten free numbers): fast=10, slow=30, regime_ma=200, threshold=0,
max_positions=6, position_pct=0.15 — **six of ten**, brackets and hold cap contributing zero.

**Universe: the nine full-history sector SPDRs** — XLK XLF XLE XLV XLI XLY XLP XLU XLB, all from
1998-12-21 — reused unchanged from round 17's Amendment 1 and round 18. Not re-derived: round 17's own
record is the standing warning that a zero-bar symbol fails the *whole card* at the guard, which cost
it 0 runs in three windows. Holding the universe constant across rounds 17, 18 and 20 also means any
deviation is attributable to the macro dimension rather than to a universe that moved.

**Windows: the eight `MAIN_WINDOWS`**, unchanged. Eligibility gate **5 of 8**
(`MIN_ELIGIBLE_MAIN_WINDOWS = 5`). *`PROTOCOL.md` §3 rule 7 read "fewer than three" until 2026-08-29 —
contradicting both its own r2 amendment and the code every round has run against. Found while writing
this document, which had to pick a number and discovered the constitution gave two; corrected there.*

**8 cells × 8 windows = 64 ranked runs**, plus §4c's 16 diagnostic runs, reported and excluded from
the ranking.

**Cell count against rule 8.** Eight ranked cells, deliberately small, for two reasons: this round
follows four higher-priority live-book re-specs and is not resourced to round 17's size; and a sweep
across all seven series would raise the correction bar for every series tested alongside it, including
three already disqualified on stationarity grounds. **A round whose job is proving the mechanism works
should not spend its correction budget on a multi-series search before the mechanism has cleared
once.** Any correction drawn from the ranked field uses a denominator of **8** — never a form-only or
gate-only subset. §4c's 2 cells carry their own denominator of 2, answering a different question.

---

## 4. The pre-registered null

**Explicitly not round 17's ~1pp ordering-noise figure.** That came from re-running one card under
shuffled *universe orderings* — a study about which qualifying name takes a scarce slot. This round's
factor is a macro gate, which does not touch universe order; the noise sources are unrelated, and
`00-EVERYTHING-TESTED.md` recommendation #5 is explicit that reusing it would be the retroactively
lowered bar it warns against.

**The null: circular-shift permutation of the gate mask.** `T10Y2Y > 0` is a boolean date-indexed
series with real autocorrelation — the curve does not flip sign day to day — so an i.i.d. reshuffle
would destroy the run-length structure and make the null artificially tight.

1. Take the actual gate mask over the full evaluated history, release-date bound per §2c.
2. Draw a circular shift by a uniformly random number of trading days, wrapping the full history. This
   preserves the mask's exact on/off proportion **and its exact run-length distribution**, randomising
   only its *phase* relative to price.
3. Re-run each form's gate-on cell against the shifted mask across all 8 windows.
4. Repeat for **200** shifts — a round number chosen for cost, not tuned to a result; cheap, since only
   the mask changes and no macro data is refetched.
5. This yields an empirical null for the gate marginal under *"some regime-shaped filter with the true
   curve's own statistics, but no informational relationship to price."*

**Decision rule: the `macro_gate` marginal matters only if it exceeds the 95th percentile of its own
circular-shift null.**

**A secondary, explicitly non-authoritative cross-check.** Round 17's 21.2pp floor is reported beside
the result for readers wanting the programme's numbers in one frame. It is **not** the decision rule,
and **if the two disagree the circular-shift null governs.** Stated here, before either number exists,
so it cannot be quietly swapped in later if it proves more convenient.

### 4c. The diagnostic side study — measuring the trap instead of arguing it

Unranked, excluded from §3's decision rule and from any correction over the ranked field.

- **Card:** `ma-crossover` — the most-evidenced entry in the programme — gated on `macro(CPILFESL)`,
  the most revision-prone, longest-lagged series in the set, **chosen because it is most likely to
  expose the trap, not most likely to look good.**
- **Run A — release-date bound**, 45-day lag per §2c.
- **Run B — reference-date bound (naive)**, `lag = 0`: the version that reads CPI at its own period
  date, exactly the 13F mistake. Never eligible for ranking, and named
  `*-NAIVE-DIAGNOSTIC-ONLY.json` so no later reader can mistake it for a submission.
- **Reported:** the count of sessions where the two bindings disagree about the gate's state, and the
  resulting difference in median adjusted excess, per window.

---

## 5. Pre-registered predictions

**The honest prior, stated once and meant literally: this most likely finds nothing.** ~50 concepts
across sixteen prior rounds and a 1,935-generation search, with near-zero survivors. Nothing about a
curve-inversion gate on nine sector ETFs is exempt from that base rate. The round is worth running
because the class was **unreachable**, not because it is expected to work.

1. **The gate marginal will not exceed its circular-shift null's 95th percentile.** The central
   prediction, and it predicts a null. If it fails — the real mask beats 200 phase-randomised versions
   of itself — that is the first evidence in this programme's history that macro data reachable at
   decision time changed a result, and it is the round's headline regardless of anything else.
2. **Gate-on will reduce trade count in all 32 cell-windows**, since the gate can only remove
   entry-eligible sessions. *Failure regime:* any cell-window where on trades **more** than off means
   the gate or its binding is backwards — a build defect, not a result.
3. **At least one of the 8 cells will fall short of the 5-of-8 eligibility gate.**
   `vol-compression` already requires ATR under 2% of price on top of a trend filter; stacking a
   non-inverted-curve requirement is exactly the restrictive intersection round 17 named.
4. **§4c's naive binding will produce a strictly more favourable result than release-date binding, on
   average**, because naive binding can only admit a value earlier than it should, never later. The
   direction is structural, so this is really a check that the diagnostic is wired correctly: if
   release-date binding is ever *more* favourable, that is a bug in the diagnostic, not a finding.
5. **The naive-vs-release gap in §4c will be smaller than the 21.2pp cross-check floor.** If it is
   **not** — if a 45-day lag on one series moves a result by more than the programme's established
   noise floor — that is a second possible headline, independent of prediction 1: it would mean the
   causality trap is a live source of overstated results here rather than a theoretical concern, and
   every future macro round would have to treat release-date binding as load-bearing.

---

## 6. What this round cannot answer

Round 17 §7 and round 18 §5 still apply in full. Specific to this round:

- **No stationary transform of a trending series.** `PCEPI`, `PCEPILFE`, `CPILFESL` are excluded from
  the ranked gate because a bare level comparison on a non-stationary index across a 19-year matrix is
  not a regime test, and §2b deliberately does not build the machinery that would make one possible.
  **Whether core inflation trend changes a result is still open after this round, not closed.**
- **One series in the ranked comparison.** `DGS10`, `T10YIE`, `DCOILWTICO` become engine-reachable but
  are not run here, to hold the denominator at 8.
- **No revision-vintage data.** §2d: the lag leak is closed, the revision leak is not.
- **The lag table is a placeholder, not a verified calendar**, most importantly the 45-day monthly
  figure.
- **Everything rounds 17/18 named still holds**: no cross-sectional ranking beyond `rank_by`'s single
  step; no volatility-scaled sizing (`TiltRule.shift_pct` is still a fixed `Decimal`); no dividends;
  a fixed universe for the whole run; long only; one stop and one position size for every symbol.
- **One universe.** The nine SPDRs remove stock selection from the comparison at the cost of saying
  nothing about a differently composed book.
- **Nothing will be promoted.** Like rounds 15–18 this is a measurement study. A cell clearing its null
  is evidence the class is worth developing, not a candidate — that still needs §6's ordinary path, on
  new windows, twice. **And note the r21 amendment in `PROTOCOL.md` §9: the promotion path no longer
  applies to the `trading` purpose at all.**

---

## 7. Amendment and disclosure discipline

`PROTOCOL.md` §2: *"A card edited after any result exists is not a strategy, it is a memory of one."*
If any run fails partway — a card rejected by the new guard mid-round, a window returning zero
eligible cells, a mid-round discovery that a threshold was checked against the wrong artifact — the
response is round 17's, not a quiet fix:

- The failed attempt's cards and partial results stay on disk, unmodified, at
  `data/rounds/r21-2026-08/{cards,results}-INVALID/`, as round 17's eleven-ETF attempt is preserved.
- The amendment is written into *this* document, dated, describing what was wrong, what changed, and —
  explicitly — whether any §5 prediction is altered or weakened. If none is, say so as plainly as round
  17 did.
- Nothing learned from a failed run informs a still-open design choice in the surviving version.

**Two failure modes specific to a macro round**, both needing a rule in advance rather than an
improvisation:

1. **A live FRED outage or a mid-round revision.** §2c's pinning exists so this cannot silently change
   inputs between freeze and run. If macro data is **not** pinned before phase 2 closes, that is itself
   a round-invalidating defect on discovery — affected results are marked `-INVALID`, never quietly
   re-scored against a refetch.
2. **A guard rejection at freeze time**, before any backtest runs — e.g. a `MacroField` with no
   lag-table entry, per §2d's fail-closed check. This is not an amendment; it is what phases 1 and 2
   are for, and the fix lands before the freeze commit.

The commit hash of the frozen cards is quoted in the round report, per §2, whichever of the above did
or did not happen.

---

## 8. Build note, 2026-08-30 — §2 is implemented; the round has not run

Appended rather than folded into §2, so this document stays a record of what was planned before the
code existed.

**§2a — done.** All seven series fetched live and pinned. The four that had no committed fixture
(`PCEPI`, `PCEPILFE`, `CPILFESL`, `T10YIE`) now have one each, with parsing tests.

**§2b — done.** `MacroField` and `MacroRef` in `app.rules.nodes`; `macro(T10Y2Y)` parses, renders and
round-trips through `app.rules.grammar`; `app.rules.evaluate` resolves it against a bound frame.

**§2c — done, and the pin exists.** `app.rules.macro_binding` shifts every observation to
`reference + RELEASE_LAG` and joins on that. `app.rules.macro_pin` writes an immutable, digest-verified
snapshot; the round's own pin is `data/rounds/r21-2026-08/macro-pin.json`, digest
`d83b5191832085b0eeceae8de939a39ced386a748970653ad2ac92d78a4d96c6`, seven series, 49,210 observations,
`DGS10` reaching back to 1962-01-02 so every window in the matrix is covered. `write_pin` refuses to
overwrite and `read_pin` refuses a file whose digest does not match its contents.

**§2d — done** (the empirical assertion was still outstanding when this note was first written on
2026-08-30; completed the same day). The node allowlist, the `MacroField` mirror and the
**fail-closed lag-table check** are in `app.backtest.guards`, each with a test that exercises the
refusal rather than assuming it.

**The empirical per-session assertion is now built**: `verify_release_binding` walks the *output* of
the join and asks, per bar, whether the value sitting there could have been known on that date. It is
deliberately built differently from the thing it checks — `bind_macro` carries a forward cursor
across bars, the verifier bisects an explicit eligibility list per bar — so a cursor bug cannot
reproduce identically in both and cancel out.

**And it is tested by constructing the bug it exists to catch.** One test builds the *naive
reference-date* binding — the join this whole module replaces — and requires the verifier to report
it; it flags exactly the two pre-release bars. Another catches a value bound a single day early, the
version that is invisible in a chart and shifts every signal forward one session. `guards.check` runs
it on any tree naming a macro series and **fails closed** when no pin is configured; a price-only rule
gets no macro finding at all, so the report a reader skims is unchanged for every card in the library
but the macro ones.

Verified on real data before any card exists: `close > sma(200) and macro(T10Y2Y) > 0` and
`... and macro(CPILFESL) > 300` both clear the guard over SPY's 5,196 sessions from 2006, with the
release binding re-derived for every one of them.

**Wired into the run path.** `app.backtest.strategy._fired` and `app.backtest.events._build_arm` bind
a macro frame when the tree needs one. A rule that names no macro series gets `None` and its call is
byte-identical to what it was before this existed — that is enforced by only passing the argument when
there is one, after forwarding `macro=None` unconditionally broke thirty tests whose `Evaluator`
doubles predate the parameter.

**An unpinned macro rule raises.** No live fetch is attempted anywhere in the run path. FRED serves
revised values against the same reference dates, so an unpinned run would reproduce its dates and not
its answers — reproducible-looking and wrong, which is worse than failing.

**Observed once, on real data, before any card exists.** `close > sma(200)` against
`close > sma(200) and macro(T10Y2Y) > 0` on SPY, 2006-01-02 to 2026-08-27: 3,864 firing sessions
against 3,329, the gate removing 535. Consistent with §5's prediction 2 (a gate can only remove) on
one symbol. **This is a wiring check, not a result** — one symbol, no window matrix, no null, nothing
scored. It is recorded because it is the first evidence the path runs end to end, and for no other
reason.

---

## 9. Amendment 1, 2026-08-30 — the gate is inert on this window matrix

**Recorded before any cell was scored**, and before the null was run. Discovered from a smoke run of
the GFC window in which all four gate-on cells came back byte-identical to their gate-off pairs.

### What was found

`macro(T10Y2Y) > 0` blocks **81 of 1,716 eligible sessions across the eight main windows**, and in
only two of them:

| window | sessions | gate true | **gate false** | T10Y2Y min .. max |
|---|---|---|---|---|
| q4-2018 | 63 | 63 | **0** | 0.11 .. 0.35 |
| covid | 93 | 93 | **0** | 0.12 .. 0.69 |
| bear-2022 | 194 | 123 | **71** | −0.51 .. 0.89 |
| chop-2015 | 258 | 258 | **0** | 0.95 .. 1.77 |
| chop-2011 | 259 | 259 | **0** | 1.22 .. 2.73 |
| bull-2024 | 249 | 239 | **10** | −0.17 .. 0.67 |
| recent | 248 | 248 | **0** | 0.27 .. 0.74 |
| gfc | 352 | 352 | **0** | 0.47 .. 2.60 |

**Six of eight windows produce identical gate-on and gate-off cells by construction.** The median
adjusted excess across eight windows — this round's ranking key — is therefore computed over six
identical pairs and two that differ, and a gate marginal of approximately zero would follow
arithmetically, whatever the macro data does or does not contain.

### Why the design did not anticipate it

The eight main windows were selected on **equity** regimes — a crash, two chops, a bull, a recent
slice, the GFC. Nothing in their selection considered the *curve*. The yield curve inverted in
2006–07, in 2019, and in 2022–24; the matrix samples the first only from 2007-10-09, **after** that
inversion had ended, misses 2019 entirely, and catches the third only in `bear-2022` and the tail of
`bull-2024`.

§3 argued for `T10Y2Y` on the grounds that it is a spread rather than a trending level, and that
reasoning still holds. What it did not check is whether the spread actually *crosses its threshold*
inside the windows the round would score it on. That check cost one query and was not made.

### The consequence, stated plainly

This is `DEFECTS.md` D5's shape, and round 12's: a rule that never activates measures its fallback,
not itself. Publishing a near-zero gate marginal from this field would invite exactly the wrong
reading — "a macro regime overlay does not change a result" — when the supported statement is
**"this window matrix cannot test a rates-based regime overlay."** Those are different claims and
only the second is evidence.

### What is done about it

1. **The ranked field is run anyway, and the identity is the result.** The 8 cells over 8 windows
   cost little and *document* the collapse: byte-identical pairs in six windows is the evidence for
   this amendment, not an inconvenience to it.
2. **The circular-shift null (§4) is not run.** A null distribution for a factor that varies on 81 of
   1,716 sessions would be a precise measurement of nothing, and 6,400 runs is a large price for it.
   This is a deviation from the pre-registration and is recorded as one rather than quietly skipped.
3. **No threshold, series or window is changed to make the gate fire.** Picking a different cut, or
   adding a window because the curve inverted in it, is selection on the outcome variable — the
   failure round 4 exists to document and round 5's Arm B is careful to isolate. A redesign belongs
   in a **new pre-registration**, written before its data is seen.
4. **Prediction 2 is not vindicated by this round.** "Gate-on reduces trade count in every
   cell-window" is technically unfalsified — the gate never *added* an entry — but six of eight
   windows tested it vacuously. It should be treated as untested, not as confirmed.

### What a successor round would need

A window matrix sampling **curve** regimes rather than equity ones: at minimum a window spanning
2006-01 → 2007-06 (sustained inversion), one spanning 2019-05 → 2019-10, and one spanning 2022-07 →
2024-08. All three are inside the nine sector SPDRs' history, which begins 1998-12-21, so the
universe does not have to change. That is a design for another document; it is named here so the next
reader does not have to re-derive it.
