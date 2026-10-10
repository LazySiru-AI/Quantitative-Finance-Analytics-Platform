# Inventory: the autonomous evolution loop

Read-only research. Nothing here ran a backtest, started the loop, or modified any source, data, or
overlay file. Figures below are either copied verbatim from the pre-registration
(`strategy-program/EVOLUTION-LOOP.md`), copied from the two prior analyses
(`docs/research/loop/01-what-the-search-found.md`, `docs/research/loop/02-the-twenty-five.md`), or
derived by a stated arithmetic operation over `data/loop/ledger.jsonl`, `data/loop/genomes/*.json`,
`data/loop/gen*/OUTCOME.json`, `data/loop/promotions.jsonl`, and `data/loop/pending_seats.json` — all
read fresh for this inventory via `./.venv/Scripts/python.exe` one-off scripts, not taken on the prior
documents' word where the live data could answer directly. Where this inventory's own re-measurement
differs from the two prior documents (both frozen at the 2026-08-26 09:00Z snapshot), the difference is
because roughly three more days and 58 more generations of loop activity have landed since — the prior
documents are not wrong, they are a snapshot, and this document says so at each point rather than
silently overwriting the earlier figure.

**As of this inventory (2026-08-29, ledger `recorded_at` through 2026-08-29T19:59:54Z — the loop is
presently at generation 1935 and still adding rows):**

---

## 1. Scale, honestly stated — then, and now

| figure | at the 2026-08-26 09:00Z freeze | now (this inventory) |
|---|---|---|
| generation directories on disk | 233 | **291** |
| generations with a valid, scored `OUTCOME.json` | 231 (229 succeeded, 2 cancelled) | **289** (286 succeeded, 3 cancelled) |
| unparseable/missing outcomes | 2 (`gen1673` 0-byte, `gen1849` no `OUTCOME.json`) | **still exactly those same 2** — no new corruption since |
| ledger rows (candidate-generation evaluations) | 2,374 | **2,944** |
| distinct genome ids ever scored | 1,887 | **2,371** |
| the one known gap | `gen0028` → `gen1673`, 1,644 missing numbers, 27.5h of a 35.7h span | **unchanged** — confirmed still the only gap; no second gap opened in the 58 new generations |

The gap statistic (77.1% of wall-clock elapsed with nothing scored) is a fact about the run's first ~36
hours and does not change by re-measuring later; it is quoted here from `01-what-the-search-found.md`
without re-deriving it, since nothing after the freeze can alter what happened before it.

**`purposes` coverage has changed materially since the freeze, and this is the clearest single
"snapshot vs. now" divergence.** `01-what-the-search-found.md` reported `savings` at *zero* coverage
across 233 generations and traced it to a form defect (`buildLoopConfigFromDraft` never sent the
`purposes` field, so every UI-started run silently took the `(trading, roth)` default). That defect is
now fixed (`LoopConfig.purposes` has a UI checkbox group; `min_length=1` blocks the empty-selection
crash that existed briefly during the fix). Measured now:

| purpose | ledger rows | distinct generations |
|---|---|---|
| `trading` | 1,398 | — |
| `roth` | 1,376 | — |
| `savings` | **170** (zero at the freeze) | **17** generation directories now carry `purpose=savings`, first appearing at generation 1878 |

Savings is no longer zero-coverage. It remains thin relative to the other two books (17 of 291
generations, 5.8%) and off by default in `LoopConfig.purposes` — a decision the loop's own docstring
now states explicitly is deliberate, not an oversight, because the savings card family is the least
developed of the three (`strategy-program/SAVINGS-FAMILY.md`).

**`JOURNAL.md` is stale relative to the ledger, and this is itself worth recording precisely rather
than glossed over.** `data/loop/JOURNAL.md` is rebuilt from every generation's `gen{N:04d}/DIGEST.md`
by `app.evolution.digest.rebuild_journal` (`backend/app/evolution/digest.py:1109`), but the file on
disk currently ends at **generation 1877** (233 `## Generation` headers, matching the freeze exactly).
Generations 1878–1935 each have their own `DIGEST.md` on disk (confirmed: `data/loop/gen1935/DIGEST.md`
exists and is current), so the underlying per-generation record is not missing — only the assembled,
human-facing `JOURNAL.md` has not been rebuilt since the freeze. A reader of `JOURNAL.md` alone would
believe the loop stopped at generation 1877 on 2026-08-26; it has run 58 more generations and 3 more
calendar days since.

---

## 2. What the search space allowed — the one-template vs. eight-form split, measured precisely

`docs/research/loop/01-what-the-search-found.md` and the code comments in
`backend/app/evolution/models.py`/`ruleforms.py` state that the entry/exit rule was a single hardcoded
f-string until 2026-08-26, and that `rule_shape` (eight forms) replaced it. Joining every ledger row to
its genome file (`data/loop/genomes/*.json`) pins the boundary exactly, rather than repeating the prose
date:

| regime | generation range | rules-shape ledger rows | distinct rules-shape genomes | rule_shape values used |
|---|---|---|---|---|
| **legacy — one template** (`rule_shape` key absent; read as `ma-crossover` per `LEGACY_RULE_SHAPE`) | generation 1 – **1915** | 1,374 | 1,098 | 1 (`ma-crossover` only, i.e. `close > sma(R) and ema(F) crosses_above ema(S)`) |
| **eight-form regime** (`rule_shape` trait present) | generation **1917** – 1935 (present-day) | 100 | 88 | all 8: `channel-breakout` (20 rows/16 genomes), `ma-crossover` (19/16), `momentum-state` (13/11), `macd-cross` (13/12), `vol-compression` (11/10), `rsi-pullback` (9/9), `band-reversion` (9/9), `band-breakout` (6/5) |

No generation straddles both regimes — the genome-file join finds zero overlap. (Generation 1916 has no
rules-shape genomes at all; it was an allocation-shape lane.)

**What this means stated plainly.** Of the loop's 291 total generations and 2,371 distinct genomes ever
scored, only **10 generations** (1917, 1919, 1921, …, 1935 — odd numbers only, because generations
alternate lanes and only the rules-shape lane in that stretch carries `rule_shape`) and **88 genomes**
(7.3% of the 1,206 rules-shape genomes ever scored) have run under the widened search space. Every
promoted card, every one of the 25 outstanding seat requests, and 1,098 of the 1,206 rules-shape
genomes ever tested (91%) were drawn from a search that could express exactly one entry/exit template.
The eight-form regime is real, shipped, and producing genuinely varied candidates (all eight shapes
appear, none dominates), but it has so far run for roughly 4% of the loop's total generation count and
has **not yet promoted anything** — every one of the 28 `promotions.jsonl` rows and all 25
`pending_seats.json` requests have `max(generations) ≤ 1863`, entirely inside the legacy regime (the
newest promoted-card file on disk in `backend/app/paper/library/candidates/` is dated 2026-08-26 08:42,
before the eight-form regime's first generation at 20:24 that same day).

`discipline`, the trait `rule_shape` replaced, is confirmed removed from genome traits going forward:
0 of the 88 eight-form genomes carry a `discipline` key (all 1,118 legacy-regime genomes with no
`rule_shape` do carry one, as expected for genomes written before the change).

---

## 3. What it promoted

| figure | value |
|---|---|
| `promotions.jsonl` rows | **28** (21 `roth`, 7 `trading`, 0 `savings`) — unchanged since the freeze; nothing has promoted in the 58 generations since |
| distinct genomes promoted / distinct genomes ever scored | 28 / 2,371 = **1.18%** |
| seated on the paper desk right now (`roster_overlay.json`, via an approved `PendingSeat`) | **0** |
| `pending_seats.json` requests | **25** total — **22 `shelved`**, **3 still `pending`** (`g1859-fd7c2c196f35`, `g1855-4a8d06c30426`, `g1855-2ff5b8e319dd`), **0 `seated`**, **0 `rejected`**, **0 `retired`** |
| files in `backend/app/paper/library/candidates/` from the loop (`g*.json`) | **28** (matches the 28 promotions; all dated 2026-08-26, all pre-eight-form-regime) |

The 22 `shelved` rows are not "reviewed and kept" in the ordinary sense — `02-the-twenty-five.md`
documents that all 22 were originally auto-seated onto the simulated paper desk at 09:00:49 on
2026-08-26 with no human decision, a defect the two-stage `SeatStatus` pipeline
(`pending → shelved → seated`/`retired`, or `pending → rejected`) was built specifically to stop from
recurring; a migration script pulled them back to the review shelf and the desk's overlay is currently
empty of loop-sourced cards. Every one of the 25 outstanding requests carries the same rule/universe
concentration `02-the-twenty-five.md` documents: 25 of 25 run the identical one-template rule, 145 of
300 possible pairs among them are close relatives (parent-sharing or ≥60% ticker overlap), 93 of those
145 trade the *identical* universe, and 20 of the 25 `roth` requests trace through one unbroken breeding
chain to a single ancestor pair at generation 1679. `02-the-twenty-five.md`'s own recommendation rule
(deterministic, stated in full in that document) assigns **shelve** to 23 of the 25 and **decline** to
the remaining 2 (margin-over-noise-floor under 1.0pp); it assigns **seat** to none of them, because none
is a clear outlier against the other 24 — a fact that, per that document, is close to true by
construction given how related the 25 are.

---

## 4. The five falsifiable predictions (§5), evaluated against the live ledger

### Prediction 1 — "Most candidates will fail the gate"

**Borne out in aggregate; breached on the stated per-generation criterion in a nontrivial minority of
generations.** Overall, 256 of 2,944 ledger rows (8.70%) clear the 21.2pp selection-median margin at
all, and only 28 of 2,371 distinct genomes (1.18%) were ever promoted — "most candidates fail" is true
by a wide margin in aggregate. But the prediction's own stated falsification bar is stricter and
per-generation: *"If more than a third of proposed candidates clear a 21.2-point margin **in any
generation**..."* Checked directly: **35 of 286 generations with ledger rows (12.2%) had more than a
third of their candidates clear the margin.** By the letter of the pre-registration this is a partial
breach of the stated bar — it happened 35 separate times, not never — though the aggregate 8.70%
clear-rate is consistent with the spirit of "most fail." No document flags these 35 generations as
requiring the "re-examined before any promotion from that generation is trusted" review the prediction
calls for.

### Prediction 2 — "Selection medians will exceed holdout medians on average"

**Refuted under the original holdout pair, then the holdout was changed specifically because of that
refutation, and the new pairing now bears the prediction out — both states are on the record, at
different times, and neither is optional to report.**

`LoopConfig.holdout_windows` changed from `(covid, q4-2018)` to `(q4-2018, bull-2024)` at exactly
generation 1878 (confirmed by reading every `gen{N}/PLAN.md`'s "Holdout windows" line from 1877 to
1917: 1877 is the last `covid, q4-2018` generation, 1878 is the first `q4-2018, bull-2024` one — this
lands exactly where `JOURNAL.md` stops being rebuilt, which is presumably why the swap is not narrated
there).

| holdout config | generation range | ledger rows | selection median | holdout median | selection > holdout, row-by-row |
|---|---|---|---|---|---|
| `(covid, q4-2018)` — original | 1 – 1877 | 2,374 | +5.65pp | **+15.02pp** | **22.0%** of rows |
| `(q4-2018, bull-2024)` — current | 1878 – 1935 | 570 | +7.80pp | **+1.07pp** | **81.1%** of rows |

Under the original pair the loop's own docs already state this plainly (`models.py`'s
`holdout_windows` docstring: "the exact reverse of ... section 5's prediction 2"), and both all-drawdown
holdout windows were measurably *easier* than the mixed selection set — `covid`/`q4-2018` sit above
every selection window except `gfc` on positive rate. The fix (swap `covid` back into selection, add
`bull-2024`, the one window this benchmark actually penalises, to the holdout) is exactly the remedy
`01-what-the-search-found.md` §"What this means for the next architecture" point 1 recommended, and it
was applied. Under the new pair the prediction now holds cleanly: selection exceeds holdout in 81.1% of
rows and the holdout's own positive-rate dropped from 94.3% to 59.5% — a genuinely more adversarial
holdout. **Both figures matter**: the first shows the original design failed its own falsification test
and was corrected in response; the second shows the correction worked, on 570 rows and 19 generations
of evidence so far — thinner evidence than the 2,374-row original figure, and worth re-checking again
once more generations accumulate under the new pair.

### Prediction 3 — "Allocation candidates will beat rules candidates on the drawdown windows and lose on the trend windows"

**Refuted on the drawdown half; a wash on the trend half — not the predicted pattern on either axis.**
Aggregated per-generation field-median `by_window` figures (`OUTCOME.json`'s `regime` finding) across
all 286 succeeded/cancelled generations, joined to each generation's shape via its standings' genome
files (143 rules-lane generations, 143 allocation-lane generations, evenly split):

| axis (windows pooled) | rules-shape median | allocation-shape median |
|---|---|---|
| drawdown (`gfc`, `bear-2022`, `covid`, `q4-2018`) | **+25.14pp** | **+7.45pp** |
| trend (`bull-2024`, `recent`) | −2.23pp | −1.91pp |

Rules-shape candidates beat allocation-shape candidates on the drawdown windows by a wide margin — the
opposite of the prediction — and on the trend windows the two are close to indistinguishable (both
negative; allocation is marginally less negative, which is at best a weak echo of the predicted
direction, not a clean confirmation). Per `EVOLUTION-LOOP.md` §5's own instruction, this is the trigger
to re-derive the satellite weighting range in §3: "the stability sleeves are not doing what the blend
was designed to do." **One caveat that has to travel with this number**: it uses uncorrected
`median_excess` (`strategy_return − benchmark_return`), which `app.evolution.models.Standing`'s own
docstring documents as biased toward *low capital exposure* in a falling window (Pearson r = −0.978
between a window's benchmark and its excess across 749 measured runs) — rules-shape cards more readily
sit in cash (a regime filter or stop-loss taking them out) than allocation-shape cards, which hold
continuous drift-banded weights and stay closer to fully invested. Some or all of the rules-over-
allocation gap on drawdown windows may therefore be the same benchmark artefact the programme has
already documented elsewhere, rather than a clean statement that rules-shape cards handle a real
drawdown better. A rerun on `median_adjusted_excess` (exposure-corrected) would separate the two and
was not done here — flagged as **not established** at the exposure-corrected level, only at the raw
level reported above.

### Prediction 4 — "News-biased candidates will be indistinguishable from pool-drawn candidates"

**Not established with confidence — the raw numbers are suggestive rather than conclusive, and no
significance test was run.** Joining ledger rows to each genome's `origin`:

| origin | n rows | selection median | holdout median |
|---|---|---|---|
| `news` | 61 | +7.21pp | +9.35pp |
| `random` | 960 | +3.43pp | +6.98pp |
| `mutation`+`crossover` (bred) | 1,923 | +9.34pp | +14.79pp |

News-origin candidates sit between random and bred on selection (closer to bred) but *below both* on
holdout — not the flat "indistinguishable from pool-drawn" pattern the prediction anticipates, but also
not a clean edge or a clean null given `news` is only 61 of 2,944 rows (2.1%) and no rank-sum or
bootstrap test was run against this specific split (unlike §2 of `01-what-the-search-found.md`, which
did run one for random-vs-bred). `LoopConfig.use_news` remains `True` by default and `news_fraction`
at 0.25; `AGENTS-INTEGRATION-PLAN.md` Phase D — "measure before believing" — is still not complete, so
this prediction should be read as **not yet properly tested**, not as confirmed or refuted.

### Prediction 5 — "Q-values will degrade monotonically as the loop runs"

**Refuted by the prediction's own stated falsification bar, on 103 documented instances.** Reading
every generation's `standings[].q_value` across all 289 parseable `OUTCOME.json` files and tracking each
genome_id's q-value across its consecutive re-appearances: of 512 consecutive-appearance pairs with a
q-value recorded both times, **103 (20.1%)** show the q-value *improving* (getting smaller / more
significant) between two appearances of the **same genome carrying byte-identical `median_excess`** —
i.e. re-ranked against a larger ledger without a new run, exactly the case the prediction names as
disqualifying ("If a candidate's q-value ever improves without new runs, the ledger's denominator is
wrong"). Examples: `g009-30c484221799` moved from q=0.00012 (generation 9) to q=0.0000491 (generation
13) with an unchanged median_excess of +30.51%; `g1676-7498faae2320` moved from q=0.879 to q=0.118
between generations 1684 and 1688 with an unchanged excess of +0.15%. **One caveat that matters and is
stated rather than left implicit**: this is not necessarily a computation bug. A Benjamini-Hochberg
q-value at a fixed p-value is `p × n / rank`, and both `n` (ledger size) and `rank` (that p-value's
position in the full sorted distribution) change as more candidates are added — it is mathematically
possible, not merely an error, for a fixed p-value's q to move either direction as the surrounding
distribution shifts. So this finding should be read as: the prediction's stated falsification condition
did occur, repeatedly, and nothing in this programme's artifacts currently reconciles that against the
"monotonic degradation" framing the pre-registration promised — which is itself the finding worth
carrying forward, whether the ultimate explanation is a computational property of BH under a growing,
shifting distribution (benign) or an implementation defect (not benign). This inventory did not audit
`app.evolution.ledger`'s BH implementation to distinguish the two, and says so rather than guessing.

---

## 5. Structural blind spots — what 1,935 generations still never tried, and why

1. **The rule form was one template for 91% of everything ever run, and still is for every promoted
   card.** Section 2 above. This is the highest-value blind spot: every one of the 28 promotions and
   all 25 outstanding seat requests are variations on
   `close > sma(R) and ema(F) crosses_above ema(S)` with different numbers and a different ticker
   universe — not evidence that mean-reversion, breakout, or volatility-compression trading fails in
   this codebase's backtests, because the loop was structurally incapable of proposing them until
   generation 1917, ten generations ago as of this writing, and none of those ten generations' output
   has cleared a gate yet.

2. **`pairs-rotation` and `risk-managed` are permanently unreachable from this search, not merely
   unexplored.** `ruleforms.py`'s own docstring states this as a fact about the grammar, not a scope
   choice: `entry` is evaluated per symbol against that symbol's own bars, so the DSL has no way to
   express a spread or a pair-relative condition, and `risk-managed` is a statement about brackets and
   hold cap rather than about the entry rule this module reads. `pairs-rotation` was nonetheless the
   *single most common label* on the legacy-regime run — 348 of 934 rules genomes carried it (measured
   at the freeze; the label existed only as a random, disconnected-from-the-rule trait at that time) and
   13 of the 25 outstanding seat requests still carry it. No card in this programme's history has ever
   actually executed a pairs trade; the label was decorative until `classify()` replaced it, and even
   under `classify()` this discipline can never be assigned to a loop-proposed card again, because the
   grammar cannot write one.

3. **`savings` remains structurally under-searched relative to the other two books, by design, not
   defect.** Section 1: 17 of 291 generations (5.8%), 170 of 2,944 ledger rows (5.8%), and zero of the
   28 promotions or 25 seat requests. Unlike the freeze-time zero (a form bug), this is now a stated,
   deliberate default — `savings` cards are the least developed family and adding it to
   `LoopConfig.purposes`'s default would lengthen every existing user's lane cycle. It is reachable, and
   has been reached 17 times, but the search has not spent meaningful time there and nothing in this
   programme's record suggests it will unless a person opts it in explicitly per run.

4. **Ladder cards cannot be proposed at all**, by an explicit design decision recorded in
   `EVOLUTION-LOOP.md` §3: "mutating a rung schedule under a search that never stops is the most direct
   route to an overfit available in this codebase." This is a permanent structural exclusion, not a
   coverage gap that more generations would close.

5. **Every threshold inside a rule shape (RSI 40/60, Bollinger 2 deviations, MACD's 9-bar signal, the
   2%/5% ATR band) is fixed and untunable by design** — `EVOLUTION-LOOP.md` §3 and `ruleforms.py` both
   state this is deliberate, not an oversight: a form whose canonical textbook setting fails is treated
   as a finding about the form, not an invitation to grid-search a threshold. This means the search space
   is genuinely eight distinct *hypotheses*, not eight-shapes-times-however-many-threshold-settings; a
   shape that would work at RSI 35 rather than 40 is invisible to this loop by construction, forever,
   unless a person edits `ruleforms.py` and that edit is itself pre-registered per `EVOLUTION-LOOP.md`
   §1's own rule ("a generation that would need a wider space ... is a change to this file, reviewed and
   committed before the loop runs again").

6. **The promotion gate's "differing window sets" requirement is satisfied by rotating one window in
   five, and this is arithmetically forced, not incidental.** `EVOLUTION-LOOP.md` §4's 2026-08-29
   amendment (confirmed shipped in `backend/app/evolution/promotion.py` and `loop.py` —
   `achievable_shared_windows`, `UnreachablePromotionCeiling`) states the achievable floor is 4-of-5
   shared windows given the current 8-window main pool and 2-window holdout; a genuinely stricter
   ceiling (≤2 shared) is refused with a `400` before the loop starts, because the current window pool
   cannot produce it. `01-what-the-search-found.md` measured this at 28/28 promotions sharing exactly
   4 of 5 windows (Jaccard 0.667, zero variance) — every promotion this programme has ever made rests
   on one genuinely new window of evidence layered on four re-used ones. The remedy is stated as a
   `WINDOWS.md` change (more eligible main windows), not yet made.

7. **News bias steers which universes get tested, never how a candidate is scored, and Phase D's
   predictive-value question for news attention is still open.** `AGENTS-INTEGRATION-PLAN.md` Phase D
   ("measure before believing") is not complete; §4 above shows the loop's own ledger data on this
   question is thin (61 rows, no significance test run) and inconclusive rather than supportive of
   either "news helps" or "news is neutral."

8. **Ticker concentration is a product of the *pool*, not of the search failing to explore it.** The
   39-ticker pool declared in `EVOLUTION-LOOP.md` §3 is used in full (39 of 39 tickers appear across
   1,875 field genomes measured at the freeze — no leakage beyond what is authorized), but frequency is
   very uneven: `IGV` appears in 510 of 1,875 genomes, `SOXX` in 500, and the 25 outstanding seat
   requests concentrate harder still (`LRCX`/`CSCO`/`AMAT`/`KLAC`/`INTU`/`AAPL`/`CRM`/`ADBE` each in
   17–20 of 25). Ledger data alone cannot separate "the search correctly identified the easiest names to
   show excess on inside this benchmark's known biases" from "a small pool got lucky and kept breeding
   itself" — `01-what-the-search-found.md` states this explicitly as unresolved, and this inventory did
   not attempt to resolve it either.

---

## Summary

- **In the ledger right now**: 291 generation directories (289 scored — 286 succeeded, 3 cancelled; 2
  unparseable, unchanged since the freeze), 2,944 candidate-generation evaluations, 2,371 distinct
  genomes, spanning generation 1 to **1935** (still running as of 2026-08-29T19:59:54Z). This is up from
  233 generations / 2,374 evaluations / 1,887 genomes at the 2026-08-26 09:00Z freeze the two prior
  documents describe — roughly 58 more generations and 570 more evaluations have landed since, entirely
  attributable to continued live running, not a second gap or a re-count.
- **One-template vs. eight-form split**: generations **1–1915** (1,374 rules-shape ledger rows, 1,098
  distinct genomes) ran under the single hardcoded `ma-crossover` f-string. Generations **1917–1935**
  (10 generations, 100 rules-shape ledger rows, 88 distinct genomes — 7.3% of all rules-shape genomes
  ever scored) run under the eight-form `rule_shape` vocabulary, with all eight shapes represented and
  none dominant. **Every one of the 28 promotions and all 25 outstanding seat requests comes from the
  one-template regime; nothing from the eight-form regime has cleared a gate yet.**
- **The five predictions**: (1) *partially borne out* — 91.3% aggregate fail-rate, but 35 of 286
  generations (12.2%) breached the prediction's own stricter "more than a third in any generation"
  falsification bar. (2) *refuted, then fixed* — the original `(covid, q4-2018)` holdout had selection
  exceed holdout in only 22.0% of rows (the reverse of the prediction); the holdout was swapped to
  `(q4-2018, bull-2024)` at generation 1878 specifically because of this, and under the new pair
  selection now exceeds holdout in 81.1% of rows (570 rows, 19 generations of evidence so far). (3)
  *refuted on the drawdown half, a wash on the trend half* — rules-shape cards beat allocation-shape
  cards on drawdown windows (+25.14pp vs +7.45pp median), not the reverse; caveat: measured on
  uncorrected excess, which this programme's own docs document as biased toward low capital exposure in
  falling windows, so some of this gap may be that artefact rather than a clean shape comparison. (4)
  *not established* — news-origin candidates (n=61) sit between random and bred on selection but below
  both on holdout; no significance test run, sample thin. (5) *refuted by the prediction's own stated
  bar* — 103 of 512 consecutive same-run re-appearances (20.1%) show a genome's q-value improving with
  no new run, which the pre-registration itself names as the condition meaning "the ledger's denominator
  is wrong"; whether the cause is a benign property of Benjamini-Hochberg under a growing, shifting
  distribution or an implementation defect was not determined here.
- **Three most significant structural blind spots**: (a) the rule form was — and for every promoted card
  still is — a single entry/exit template; the eight-form widening is real but has produced no promoted
  evidence yet. (b) `pairs-rotation`, the single most common discipline label in the whole legacy run
  (348 of 934 rules genomes, 13 of the 25 outstanding seat requests), can never actually be expressed by
  this grammar — the label was decorative, and remains permanently unreachable now that labels are
  derived from rules rather than drawn at random. (c) the promotion gate's "two clearances on differing
  window sets" is, for every one of the 28 promotions made so far, one new window of evidence on top of
  four re-used ones (Jaccard 0.667, zero variance across all 28) — an arithmetically forced consequence
  of the current 8-window main pool that a documented 2026-08-29 amendment now reports honestly but has
  not yet been able to tighten, because the window pool itself would need to grow first.
