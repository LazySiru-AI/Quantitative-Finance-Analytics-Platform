# What the search found

Source: the frozen snapshot at `scratchpad/freeze-20260826T0900Z/`, taken 2026-08-26 09:00Z. This is a
read-only statistical wrap-up: nothing here ran a backtest, started the loop, or touched `data/`,
`roster_overlay.json`, or any other live file. Every number below is either copied verbatim from a
snapshot file or derived by a plain, stated arithmetic operation (median, fraction, percentile, Jaccard
overlap, rank-sum) over rows another module already owns (`ledger.jsonl`, generation `OUTCOME.json`
standings and findings, `promotions.jsonl`, `pending_seats.json`). The exact figures, keyed, are in
`stats.json` alongside this document's source in the scratchpad, so a UI or a later document can cite
them without re-deriving anything.

The venv this analysis ran in has no `scipy`. Every test below is implemented on `numpy`/`pandas` alone:
Mann-Whitney U with a hand-rolled rank-sum and a normal approximation (tie-corrected), and every
confidence interval is a nonparametric bootstrap or permutation over the data itself. Where an
assumption a test needs is not met by this data, that is stated next to the number, not left implicit.

## Verdict

The search ran **231 scored generations**, not 233 and nowhere near the 1,877 headline figure, evaluating
**2,374 candidate-generations** across **1,887 distinct genomes** over a **35.7-hour** wall clock, of which
**77%** is the dead 1,644-generation gap. The benchmark itself is generous in a structural, not merely
noisy, way: every crash-family window (`gfc` +37.5pp median, the `covid`+`q4-2018` holdout pair +15.0pp,
`bear-2022` +12.4pp) rewards a partly-invested rules book against a fully-invested benchmark, while the one
genuinely bullish window (`bull-2024`) has a **negative** median (−8.4pp). Bred cards do measurably
outscore random ones on both selection and holdout medians — so the mechanism is not doing literally
nothing — but the entire measured gap (≈6–7pp selection, ≈2–3pp holdout) is smaller than this programme's
own 21.2pp noise floor, and the field showed **no trend** over its 202-generation contiguous run despite an
elitist breeding step that reliably propagates each generation's winner forward. Of the 28 promotions, 21
clear a gate requiring the holdout to beat the field's own holdout median rather than zero, and **every
one of the 28** earned its "two clearances on differing window sets" by re-using 4 of 5 windows unchanged
and rotating exactly one. Put together: a benchmark this generous, a margin this thin relative to the
measured noise floor, and a promotion gate this permissive about window reuse mean the 28 promotions are
evidence that the search ran to completion, not evidence that 28 strategies work.

---

## 1. Scale, honestly stated

**233 generation directories exist. 231 carry a scored, parseable `OUTCOME.json`.**

| status | count |
|---|---|
| `succeeded` | 229 |
| `cancelled` | 2 |
| unparseable / missing `OUTCOME.json` | 2 (`gen1673`, `gen1849`) |
| **total directories** | **233** |

`gen1673` is a genuine 0-byte `OUTCOME.json` with no `PLAN.md` at all — the first attempt after the gap,
apparently caught mid-write by the freeze. `gen1849` has a `PLAN.md` (a generation was proposed) but no
`OUTCOME.json` — proposed, never scored. Neither has a single row in `ledger.jsonl`. Both read as
in-flight at the instant of the freeze rather than as new evidence of corruption beyond the known gap.

**The gap, confirmed from the data rather than taken on claim:** generation directories jump from
`gen0028` straight to `gen1673` — **1,644 missing generation numbers**, with zero directories, zero ledger
rows, and zero PLAN/OUTCOME files anywhere in between. `gen0028` finished at `2026-08-25T04:43:30Z`;
`gen1674` (the first usable generation after the gap — `gen1673` itself is unusable) started at
`2026-08-26T08:16:28Z`. That is a **27.5-hour** gap inside a **35.7-hour** total wall-clock span (first
`started_at` to last `finished_at` across every usable `OUTCOME.json`) — **the gap accounts for 77.1% of
the programme's entire elapsed time.** Less than a quarter of the wall clock this search has consumed
produced any scored generation at all.

| figure | value |
|---|---|
| distinct genomes ever scored (ledger) | 1,887 |
| candidate-generation evaluations (ledger rows) | 2,374 |
| distinct generation numbers with ≥1 ledger row | 229 |
| wall-clock span (first started → last finished) | 35.72 hours |
| gap span | 27.55 hours (77.1% of total span) |

**One more thing the ledger shows and `PLAN.md` alone would not:** generation numbers `1`–`13` (and
`1840`) were each run under **more than one distinct `round_id`** — the loop restarted from a low
generation number more than once before its long unbroken run began, almost certainly during the same
startup period that produced the `OSError` gap. Because `generations/gen{N}/PLAN.md` is overwritten by
whichever run under that number ran last, the ledger — append-only — retains **46 rows (38 distinct
genome_ids)** whose origin can no longer be recovered from any file on disk. Those 46 rows are excluded,
and only from, the origin-labelled comparison in section 2; they are included in every ledger-wide figure
elsewhere in this document.

**What this does not show.** It does not show *why* the gap happened beyond what the repo's own commit
already states (a read-only library-path `OSError`, since fixed) — this analysis did not read application
code or logs, only the snapshot's own generation records. It does not show what, if anything, ran during
the gap and left no trace; absence of a directory is not proof nothing was attempted, only proof nothing
was recorded.

## 2. The benchmark is broken, quantified

Reproduced from all **2,374** rows in `ledger.jsonl`:

| metric | n | value |
|---|---|---|
| selection-window median-of-medians | 2,374 | **+5.65pp**, positive in **82.0%** of rows |
| holdout median (`covid`+`q4-2018` combined) | 2,364 (10 rows have a null holdout and are excluded, not zeroed) | **+15.02pp**, positive in **94.33%** of rows |

Both match the figures already on record for this programme to four significant figures.

**Random vs. bred.** Every ledger row was labelled by the origin its genome was created with in
`PLAN.md` (`random`, `mutation`, `crossover`, or `news`; 46 rows unrecoverable, see section 1). `mutation`
and `crossover` are pooled as "bred":

| group | n rows | n distinct genomes | selection median | holdout median |
|---|---|---|---|---|
| random | 701 | ~606 (genome-level dedup) | +2.57pp (row) / +2.40pp (genome-level) | +13.01pp (row) / +13.32pp (genome-level) |
| bred | 1,592 | ~1,227 (genome-level dedup) | +9.31pp (row) / +8.43pp (genome-level) | +15.82pp (row) / +15.72pp (genome-level) |
| news | 35 | — | +7.36pp | +16.55pp |

Bred cards score higher than random cards on every one of these four comparisons. A Mann-Whitney U test
(rank-sum, normal approximation, tie-corrected — no `scipy` in this venv) rejects the null of no
difference at every cut, row-level and genome-level, selection and holdout (all p ≈ 0 to the precision
this approximation can report; |rank-biserial| effect sizes 0.44–0.46 for selection, 0.24–0.28 for
holdout — moderate). A bootstrap on the median difference (20,000 resamples) gives:

| comparison | observed gap | 95% CI |
|---|---|---|
| selection median, bred − random (row-level) | +6.75pp | [+5.84pp, +7.52pp] |
| holdout median, bred − random (row-level) | +2.81pp | [+2.02pp, +5.04pp] |

**So bred cards do beat random cards — the search is not producing literally nothing.** But two
assumptions of the Mann-Whitney test are violated by this data and are not fixable by switching tests:
(1) the same genome can appear more than once in the ledger, re-scored in a later generation (row-level
test only), and (2) bred rows are not independent draws — they share parents and grandparents within a
lane's lineage, which the genome-level dedup does not fix either. Both tests are reported because both
point the same direction regardless, but neither p-value should be read as a classical significance level
given (2).

**The number that matters more than the p-value: the observed gap (≈6–7pp on selection, ≈2–3pp on
holdout) is smaller than this programme's own 21.2pp noise floor** — the spread this same repo measured
from re-running one identical card under twelve `universe` orderings (`PROTOCOL.md` §7). A gap can be
statistically distinguishable from zero, because n runs into the hundreds, and still be smaller than the
programme's own stated floor for how much one card's score moves from ordering noise alone. Both are true
here at once, and the second is the one that should govern whether any individual promoted card is
trusted.

**What this does not show.** It does not show that breeding is *worthless* — a 6–7pp gap with a tight
bootstrap CI is a real, nonzero effect, not noise dressed up as one. It does not show which specific trait
or lineage drives the gap; that would need a different design (holding traits fixed one at a time), which
this ledger does not record per-row.

## 3. Selection vs. holdout, per window

The finest grain the snapshot supports for selection windows is a **per-generation field median** (median
across that generation's candidates), taken from each `OUTCOME.json`'s `regime` finding and pooled across
every succeeded generation that ran the window:

| window | n generations | median field excess | mean field excess | % of generations positive |
|---|---|---|---|---|
| `gfc` | 193 | **+37.47pp** | +31.09pp | 98.4% |
| `bear-2022` | 185 | +12.42pp | +11.36pp | 88.6% |
| `recent` | 193 | +11.00pp | +10.54pp | 71.0% |
| `chop-2011` | 193 | +4.05pp | +3.46pp | 74.1% |
| `chop-2015` | 193 | +1.00pp | +4.93pp | 77.7% |
| `bull-2024` | 188 | **−8.41pp** | −7.80pp | 23.4% |
| `covid`+`q4-2018` (holdout, **combined**) | n=2,364 candidate rows, not generations | **+15.02pp** | +13.17pp | 94.3% |

**`gfc` is by a wide margin the most generous window in the entire matrix, and `bull-2024` is the only
window that is actually hard.** The combined holdout pair sits above every selection window except `gfc`,
and its positive rate (94.3%) is second only to `gfc`'s (98.4%). This is not a coincidence of which
windows happen to be in each set: `covid`, `q4-2018`, and `gfc` are all sharp, fast drawdowns, and
`adjusted_excess = strategy_return − capital_exposure × benchmark_return` mechanically rewards a book that
is *not* fully invested (stop-losses, a regime filter that sits in cash) against a benchmark assumed fully
invested — exactly the bias `PROTOCOL.md` §4 already documents (capital exposure correlated with GFC
adjusted excess at Pearson r=+0.797 in the hand-run tournament). **The holdout pair is not adversarial in
the way a holdout is supposed to be; it is drawn from the same regime family that already inflates the
best-scoring selection window.** This is the single most consequential finding for a next architecture: a
gate that requires "a positive holdout median" is close to requiring "at least one of two crash windows
didn't get worse," which nearly every card that survives to be gated has already shown it can do on the
selection side via `gfc`.

**What this does not show — stated plainly because the task asked for it directly.** No file in this
snapshot separates `covid` from `q4-2018`; only their combined median-of-the-pair is recorded per
candidate. Whether `covid` alone or `q4-2018` alone is the more generous window, and by how much, **cannot
be answered from this data.** Answering it would require the per-window holdout run files, which the
snapshot does not include and which this task is not permitted to regenerate by running a backtest. This
is a real gap, not a rounding of the question — a next architecture that wants to know this should record
per-window holdout figures going forward, the same way `by_window` already exists for selection.

## 4. Did the search improve over time?

Field median excess by generation, for the 202 of 205 generations in the `gen1673`–`gen1877` range that
actually produced a scored, succeeded `OUTCOME.json` (excluded: `gen1673` and `gen1849`, both unparseable
per section 1; `gen1877`, `status=cancelled`, no candidates completed):

- OLS slope of field median on sequential generation order: **+0.0036pp per generation**, bootstrap 95% CI
  **[−0.0135pp, +0.0208pp]** (20,000 resamples). The interval straddles zero.
- Spearman rank correlation between generation order and field median: **ρ ≈ 0.045** — indistinguishable
  from no relationship.

**The field median did not rise over 202 generations of continuous running.** This is a clean null result
and it should be stated as one, not softened into "roughly flat with a slight upward drift" — the CI does
not support a drift claim in either direction.

**Elite survival vs. random resampling.** A generation's rank-1 card reappears in a *later* generation's
ledger rows (i.e. was carried forward and re-scored) **93.6% of the time (n=202 winners)**, against
**10.7% for every other rank (n=1,810)** — an 82.8pp gap. A permutation test (20,000 shuffles of the
winner/non-winner label) puts this nowhere near what random resampling of the field would produce
(one-sided p ≈ 0.00005). **This confirms the breeding mechanism does what it is designed to do — carry the
top-ranked card forward — not that carried-forward cards are actually improving anything.** Read next to
the flat trend above: the loop reliably propagates its own winner every single generation, and the field's
median score does not move as a result. Elitism operating correctly and a field failing to improve are not
in tension; the second is what makes the first, on its own, unpersuasive as evidence of progress.

**What this does not show.** It does not test any particular *lane* (roth vs. trading) separately, nor
does it control for the amendments the owner made mid-run (see `amendments.jsonl`: population, elite
count, and `rank_by` were all changed by hand across generations 1845–1848) — those changes are folded
into the same 202-generation series rather than isolated, because isolating them would need a
before/after comparison this task's scope does not include.

## 5. The promoted 28 — what distinguishes them from the field

| figure | value |
|---|---|
| promotions | 28 (21 `roth`, 7 `trading`, 0 `savings`) |
| distinct genomes | 28 |
| `q_value ≤ 0.05` | 26 of 28 |
| `q_value > 0.05` | 2 of 28 (`g1755-60b22dc5f630` q=0.072, `g1859-fd7c2c196f35` q=0.069) |
| median selection percentile within own purpose | 96.1 |
| median holdout percentile within own purpose | 82.0 |

Every one of the 28 sits in roughly the top 5–10% of its own purpose's ledger distribution on selection
median — expected, since clearing the 21.2pp gate twice already implies a high rank against a distribution
whose own median-of-medians is +5.65pp. The holdout percentile is looser (median 82.0), consistent with
section 3's finding that the holdout pair does not discriminate much once a card has already cleared
selection.

**The gate the owner most needs an answer to:** how many of the 28 would survive a gate requiring the
holdout to beat the field's own holdout median rather than zero?

- Against the **all-time, any-purpose field holdout median (+15.02pp, n=2,364)** — the single number this
  programme already reports as its headline holdout figure — **21 of 28 survive.**
- Against the **same-purpose field holdout median** (`roth`: +12.88pp; `trading`: +17.88pp) — a more
  lenient, purpose-matched cut — **27 of 28 survive**; only `g1679-944a6f327542` (holdout +11.56pp against
  a +12.88pp roth-purpose bar) falls short.

**21 of 28 is the number to carry forward**, because it uses the field figure this whole document (and the
repo's own commit history) already treats as the reference point, rather than a bar re-cut per purpose
after the fact.

**What this does not show.** It does not evaluate any of the 28 on trade count, worst-window depth,
universe overlap with the existing shelf, or the repeated-discipline-label pattern documented in the
companion `docs/research/loop/02-the-twenty-five.md` — those are covered there, for the 25 of these 28
still awaiting a stage-1 decision, and are out of this document's scope.

## 6. Repeated-measure contamination in the promotion gate

`PROTOCOL.md` §6(a) and `EVOLUTION-LOOP.md` §4 both establish that re-scoring a frozen card on an
already-seen window recomputes the identical number rather than sampling anything new. The promotion gate
requires two clearances "on differing window sets." For all **28 of 28** promotions, checked directly
against `promotions.jsonl`'s own `window_sets` field:

| figure | value |
|---|---|
| mean / median Jaccard overlap between the two window sets | **0.667 / 0.667** — identical for every promotion |
| minimum / maximum Jaccard overlap observed | 0.667 / 0.667 (zero variance) |
| promotions where exactly 1 of 5 windows differs | **28 of 28** |

Every promotion's two window sets share **4 of the 5 selection windows** and rotate exactly one. The
window that rotates is always one of two fixed swaps: `{chop-2011 ↔ chop-2015}` or
`{bull-2024 ↔ chop-2011}` — never anything else, across all 28. "Two clearances on differing window sets"
is formally satisfied in every single case, and is, in the measurement that actually matters, **one
genuinely new window of evidence layered on four re-used ones.** That is a much weaker claim than "two
independent five-window measurements," and every one of the 28 promotions rests on it identically — this
is not a defect in a handful of cards, it is how the gate operates by construction given the rotating
window-set design each generation draws from.

**What this does not show.** It does not show whether the *holdout* windows were also re-used between a
card's two clearances — the holdout set (`covid`, `q4-2018`) is fixed by `LoopConfig` and is not part of
the "differing window sets" check at all, so this question does not apply to it; the check is specific to
the 5 selection windows.

## 7. Concentration

**Tickers.** The field used **39 distinct tickers across 1,875 genomes with a recoverable universe** —
exactly the 39-ticker set `EVOLUTION-LOOP.md` §3 declares eligible across both the taxable and Roth pools:
full coverage, and no leakage beyond what was authorized. Concentration shows up in frequency, not in
scope:

| ticker | appears in (of 1,875 field genomes) |
|---|---|
| IGV | 510 |
| SOXX | 500 |
| SSO | 479 |
| QLD | 462 |
| VUG | 454 |
| AMAT | 427 |
| CSCO | 426 |

The 25 seat requests concentrate harder still — the top eight tickers (`LRCX`, `CSCO`, `AMAT`, `KLAC`,
`INTU`, `AAPL`, `CRM`, `ADBE`) each appear in 17–20 of the 25 cards, and 613 distinct exact-ticker-set
combinations were used across those 1,875 field genomes (roughly one distinct universe per 3 genomes).

**Discipline mix.** Among rules-shape genomes (934 of 1,875; the other 941 are allocation-shape, which
carries no `discipline` trait): `pairs-rotation` accounts for **348 of 934 (37%)**, more than double the
next most common (`breakout`, 136). Among the 25 seat requests specifically, `pairs-rotation` is **13 of
25 (52%)** — the search's most common discipline is over-represented in what actually reaches a human
decision relative to its already-large share of the field.

**Purpose coverage.** `savings` is one of three purposes the ticker partition and mandate declare, and it
was **never run**: zero of 2,374 ledger rows, zero of 233 generations, zero of 25 seat requests carry
`purpose=savings`. Two of three declared purposes account for 100% of everything this search has produced
in 233 generations.

**What this does not show.** It does not explain *why* `savings` was never selected as a lane — that is a
configuration or scheduling question this snapshot's data cannot answer, only observe. It does not compute
correlation between ticker concentration and score; a search drawing repeatedly from a small, high-scoring
pool of names is not distinguishable, from ledger data alone, from a search that has correctly identified
which names are easiest to show excess on inside this benchmark's known biases (section 3).

---

## What this means for the next architecture

0. **The search never searched strategy form — fix that before anything else on this list.**
   *Added after this document's first draft, from a source read rather than from the ledger; it
   subsumes several of the points below.* `app.evolution.proposer._rules_card` composes every
   candidate's rule from a hardcoded f-string:

   ```python
   entry     = f"close > sma({regime_ma}) and ema({fast}) crosses_above ema({slow})"
   exit_rule = f"ema({fast}) crosses_below ema({slow})"
   ```

   All 2,374 evaluations therefore explored **one** strategy form, varying `fast`, `slow`,
   `regime_ma`, `stop_loss_pct`, `take_profit_pct`, `max_hold_days`, `max_positions`, `position_pct`,
   `rank_key` and the ticker universe. Confirmed downstream: masking the numeric parameters out of
   every one of the 25 outstanding seat requests yields exactly **one** distinct entry/exit template.
   No amount of window-matrix or gate tuning changes what a search that cannot emit a second rule
   shape is able to find.

   `discipline` compounds it. It is drawn with `rng.choice(list(Discipline))` in
   `app.evolution.genome`, is a **mutable trait** a mutation can flip on its own, and reaches only
   `StrategyCard(discipline=...)` for display. Measured consequences: 26 of 673 single-parent
   mutations (3.9%) produced a card behaviourally identical to its parent, 15 of them differing only
   in that label; and the 25 seat requests are only **23** distinct strategies, because
   `g1815-d05786e4c611`("breakout") ≡ `g1823-e2a3d5060b09`("mean-reversion") and
   `g1763-b3154a945165`("pairs-rotation") ≡ `g1767-775be2277569`("mean-reversion") are byte-identical
   in universe, entry, exit, stop, hold, position count and sizing.

   Two changes follow, and point 5's "flat field median despite elitism working" is at least partly
   explained by the first: make the rule *shape* an evolvable part of the genome, validated by the
   `grammar.parse()` call `_rules_card` already performs (`app.rules.grammar` expresses far more than
   this one template); and either derive `discipline` from the emitted rule or remove it, because a
   randomly-drawn label presented as a description is worse than no label.

   **Both were implemented on 2026-08-26**, after this document was written and because of it. The
   rule form is now a `rule_shape` trait drawn from eight structurally different templates
   (`app.evolution.models.RULE_SHAPES`, rendered by `app.evolution.ruleforms`), and `discipline` is no
   longer a trait at all: `app.evolution.ruleforms.classify` parses the emitted rule and reads the
   label off its AST, so two identical rules can no longer carry two labels. The tenth budget slot
   `discipline` occupied is what `rule_shape` was paid for with, so the ten-free-parameter budget is
   unchanged. `strategy-program/EVOLUTION-LOOP.md` §3 is the authoritative description of the widened
   space. **Nothing in this document has been re-measured against it** -- every figure here still
   describes the completed 231-generation run, which explored the single template, and none of the
   numbers above should be read as characterising what the search does now.


1. **Treat the holdout pair as a second selection window, not a check.** Section 3 shows `covid`+`q4-2018`
   behaves like the most generous end of the selection matrix (`gfc`), not like an adversarial regime.
   Either add a holdout window from the `bull-2024` family (the one regime this benchmark actually
   penalizes) or stop presenting a positive holdout median as evidence of anything beyond "this card also
   didn't do badly in a crash," which 94.3% of everything ever run already does.

2. **Raise the promotion margin, or change what "differing window sets" means, or both.** Section 2's
   bred-vs-random gap (≈6–7pp) is smaller than the 21.2pp noise floor this same programme measured. Section
   6 shows the 21.2pp gate is being cleared twice on window sets that share 80% of their windows by
   construction, not by accident in a few cases — every promotion. A gate that wants two genuinely
   different measurements needs either a smaller shared-window ceiling (e.g. require ≤2 of 5 windows
   shared) or a bigger, rotating window pool so a full swap is possible.

   **Half-answered 2026-08-29, and the half that is not is the arithmetic.** The overlap is now
   computed and written into every promotion's `reason` and every `PendingSeat`, so the 4-of-5 figure
   this point had to reconstruct from the ledger is stated where an approver reads it.
   `LoopConfig.promotion_max_shared_windows` will enforce a ceiling — but with eight main windows, a
   two-window holdout and a five-window eligibility floor, two distinct selection sets **always**
   share four, so the "≤2 of 5" suggested above is unreachable and `start_loop` refuses it with a
   `400` naming the achievable floor rather than accepting a gate nothing can clear. The remaining
   work is therefore the second half of this point's own recommendation, and it is a `WINDOWS.md`
   change, not a gate change: **the pool has to grow before the ceiling can bite.** The margin was
   left at 21.2 — it is a measured noise floor (`PROTOCOL.md` §7), and raising it to compensate for a
   window-overlap problem would be tuning the wrong knob.

3. **Report the field's own holdout median next to every card's, not just its own number.** Section 5's
   most load-bearing number — 21 of 28 promotions beat the all-time field holdout median, not 28 of 28 — is
   invisible if a UI only shows a card's own holdout figure. The dossier contract already being built in
   this same effort (`context.field_holdout_median_same_purpose` / `_all_purposes`, split so a card is compared against its own book as well as against every book) is the right fix; this document is the
   evidence for why it is load-bearing rather than decorative.

4. **Stop counting generations that never produced output, and record what actually happened during a
   gap.** Section 1's 233-vs-231 distinction and the 1,644-generation dead stretch are both invisible
   unless something reads `status` and `started_at`/`finished_at` rather than counting directories. A
   supervisor that logs *why* a generation is missing (crashed, cancelled, still running) as it happens
   would make this kind of after-the-fact archaeology unnecessary.

5. **A flat field median across 202 generations, with elitism working as designed, is itself a finding
   the next design should react to.** Section 4 shows the mechanism is not stuck for lack of trying — it
   reliably keeps its own best card in the breeding pool — and still does not compound. That points at the
   search operators (mutation step size, crossover, or the correlated-ticker-pool effect the owner's own
   amendments in `amendments.jsonl` already flagged for generations 1845–1848) rather than at the selection
   or promotion machinery, which is doing what it was told to.

6. **Decide, explicitly, whether `savings` belongs in this search at all.** Section 7's zero-coverage
   finding is either a scheduling bug worth fixing or a deliberate scope decision nobody wrote down; either
   answer is better than the current silence, which reads as an oversight from the data alone.

   **Answered 2026-08-29: it was neither, and the reason is worse than both.** `LoopConfig.purposes`
   has always defaulted to `(trading, roth)` — a deliberate scope decision — but the start form's
   `buildLoopConfigFromDraft` did not carry the field at all, so **every run ever started from the
   Competition page took that default no matter what the person wanted**, and `savings` was not
   reachable from the UI by any route. That is what `gen1873`/`gen1877`'s
   `purposes=['trading', 'roth', 'saving']`, typed into the *goal* box, was trying to say. Zero
   coverage was not a scheduler skipping a lane; it was a form with no control.

   The form now has a "Books to breed for" checkbox group, `purposes` is sent in a fixed order rather
   than in click order (it is the order `_lanes_for` cycles lanes through, so click order would make
   two runs with the same selection work their lanes differently), and the last remaining book cannot
   be unticked. That last rule is a defect this pass also fixed at the model: `purposes=()` was
   accepted, `_lanes_for` returned no lanes, and `_run` then indexed `lanes[(n - 1) % 0]` — so an
   empty selection produced a loop that reported `"failed"` with a modulo error instead of a rejected
   request. `LoopConfig.purposes` is now `min_length=1`.

   **The default is deliberately unchanged.** Savings stays out of it: those cards are the least
   developed of the three families (`strategy-program/SAVINGS-FAMILY.md`), and adding a purpose to the
   default silently lengthens every lane cycle for everyone already using the button. What was missing
   was the ability to choose, not the choice.
