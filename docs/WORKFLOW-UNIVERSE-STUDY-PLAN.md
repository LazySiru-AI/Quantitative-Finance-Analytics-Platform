# Agent Workflow universe study — does dynamic selection change what the gate is worth?

**Build status (2026-09-01):** BUILT — commits d75792b (feature), be6b67b (hysteresis), 679272d
(book routing), e35c967 (screen_top_n), bc5f178/ce4006b (daily step), 865de91 (backfill), 106ba5f
(screen_entry_rule). Sections below are the pre-build design and are kept verbatim as the
pre-registration; where they say "not built"/"flagged, not built", see `docs/AGENT-DESK-CONTRACT.md`
for the current surface. `universe_select` exists and both screened books have staged orders — see
`docs/reports/EVERYTHING-INVESTIGATED-2026-09-01.md` §4-5 for the first measurement.

Pre-registered 2026-08-31, before `universe_select` exists, before either screened book has staged an
order, and before any measurement in this study exists. **Not investment advice.**

This is Phase B of `docs/WORKFLOW-DYNAMIC-UNIVERSE-ROUND-PLAN.md`, frozen. It is a sibling of
`docs/WORKFLOW-STUDY-PLAN.md`, not a replacement for it: that study asks whether research-gating a
strategy card's own static universe is worth its cost; this one asks a narrower, orthogonal question
— whether *which tickers get research spent on them* changes the answer, once a selector has been
promoted out of Phase A. Read `WORKFLOW-STUDY-PLAN.md` first. Every convention it establishes
(exposure correction, the discrimination test, the treatment of annualised statistics, the tax and
fill-realism caveats) is inherited here by reference, not restated, except where this document says
otherwise.

---

## 0. Recon corrections

Claims in the round-plan draft and this brief that the current code contradicts, or that the code
confirms only as *not yet built*. Verified 2026-08-31 by reading the modules named in the brief.

1. **`WorkflowArm` is a closed 4-value `Literal`, and book identity is keyed on it alone —
   confirmed, and it is a harder constraint than the round-plan draft's "contract caution" implies.**
   `book_models.py:57` — `WorkflowArm = Literal["raw_signal", "ta_gated", "vibe_gated",
   "full_workflow"]`. `book.py:103` — `book_path(settings, arm) -> data/agentdesk/workflow/book/
   <arm>.json`, a **one-argument** function. `book.load_book`/`save_book`/`stage_orders` (`book.py:
   129, 180, 198`) all take `arm` and no second axis. `BookState.arm` (`book_models.py:240`) is typed
   `WorkflowArm`, nothing else. **This means the two new screened books cannot be written today
   without colliding with the existing static-universe `raw_signal.json` and `full_workflow.json`.**
   §1.1 below states the layout this document assumes; it is a recommendation for the manager to
   confirm with the build-spec workers, not a decision this document is authorized to make.

   > **Status 2026-09-01:** Built exactly as recommended. `book_path` (`book.py:105`) now takes a
   > `universe_source: Literal["card", "screen"] = "card"` keyword; `"screen"` routes to
   > `data/agentdesk/workflow/book/screen/<arm>.json`, a separate file per arm, never colliding
   > with the card-mode books. `load_book`/`save_book` thread the same keyword through.
2. **`ArmMetrics.arm` (`study.py:95`) is likewise typed `WorkflowArm`, and `build_study` has no
   universe-axis parameter.** The same collision applies one level up: scoring a screened book through
   the existing `build_study` would report it under the same `arm` value as its static-universe
   namesake. §4 below states what this document assumes the Phase B scoring path does; again, a
   recommendation, not a decision.

   > **Status 2026-09-01:** Built exactly as recommended. `ArmMetrics.universe_source`
   > (`study.py:98`) and the paired-comparison row's own `universe_source` (`study.py:146`) are
   > both committed fields, set uniformly across every row in one `build_study` response; `GET
   > /study?universe_source=screen` scores the screen-mode books through this axis.
3. **`CandidateObservation` has no `universe_source` field today.** `candidates.py`'s
   `CandidateObservation` model (lines 106–141) carries `symbol`, `decision_date`, `entry_rank`,
   `gates`, and the resolved-return fields — no provenance field. The round-plan draft's "gains
   provenance (`universe_source: "card" | "screen"`)" is prospective, listed under its own "Build
   inventory," and this is consistent with the brief, not a contradiction — flagged here only so
   nothing below reads as describing code that exists yet.

   > **Status 2026-09-01:** Built exactly as recommended. `CandidateObservation.universe_source`
   > (`candidates.py:181`) is a committed field, default `"card"`, written by `app.workflow.pipeline`
   > on every scanned candidate; `GET /candidates?universe_source=` filters the log by it.
4. **Every workflow run logs all three `GateDecision`s for every candidate, regardless of which arms
   are enabled.** `pipeline.py:890–898` (`_stage_orders`) unconditionally computes and appends
   `ta_gated`, `vibe_gated`, and `full_workflow` decisions to the observation log for every scanned
   candidate — not gated on `ctx.config.arms_enabled`. This is what makes §3's cost-per-decision-
   changed definition computable straight from the log without needing to diff order books (see §3).
5. **`benjamini_hochberg`'s `m` is mechanically `len(p_values)`, the caller's list length —
   confirmed.** `scan.py:154`, `m = len(p_values)`. The parent study's `_GATES` tuple has three
   entries (`study.py:76`), which is why its BH denominator is 3. Nothing in `benjamini_hochberg`
   itself imposes 3; a caller that passes a one-element list gets `m = 1`. §1.2 restates this as a
   pre-registered choice, not an inherited one.
6. **`stationary_bootstrap_p` (`discovery/stats.py:172`) needs at least 3 common dates or returns
   `None`; `block` and `seed` are caller-supplied.** Same function, same floor, as the parent study's
   `_paired_comparison` (`study.py:504–515`, `block=3.0, seed=0`). This document uses identical
   arguments for identical reasons — no new floor invented.
7. **PROTOCOL.md §6 and the r21 amendment read as the brief describes.** §6 (line 169) is a mechanical
   promotion rule keyed to `StrategyCard` file moves; r21 (`PROTOCOL.md:287`) suspends it for the
   `trading` purpose specifically because a shorter horizon has less discriminating power (~20× the
   per-window sampling error against ~2.5× the sample-count gain) and a gate known in advance to lack
   power would launder noise into the library. §3 rule 8 (line 72) requires any multiple-comparison
   correction to use "a denominator of every card run in the comparison, never a subgroup." §7's
   argument in this document (below) extends r21's reasoning to a selector search rather than
   reproducing it verbatim — see §7.3.

None of the above blocks writing this pre-registration: a pre-registration fixes the *measurement*
before the *infrastructure* exists, which is the same order `WORKFLOW-STUDY-PLAN.md` itself was
written in relative to its own four books. It does mean §1.1 and §4's layout choices are load-bearing
for whoever builds `universe_select`, the necessity-gate chain, and the study extension, and must be
settled once, not independently guessed by three different workers (see the report to the manager).

---

## 1. The question, stated so it can fail

**Does routing research spend to a dynamically-selected shortlist, instead of a strategy card's
hand-authored static universe, change what the gate's research is worth?**

Two new books, both trading the same regime call and the same mandate as the in-flight study, both
seeded from the **single selector Phase A promotes** (per the round-plan's pragmatic gate) instead of
`card.universe`:

| Book | Gate |
|---|---|
| `raw_signal` / screened | none — every candidate the selector's shortlist produces (that also clears the card's own entry rule) is staged |
| `full_workflow` / screened | the whole chain — Trading Agents rating **and** Vibe verdict **and** entry-plan sizing — exactly `_passes_gate`'s existing `full_workflow` branch (`pipeline.py:404–408`), unchanged |

`raw_signal` / screened is the null, for the same reason `WORKFLOW-STUDY-PLAN.md` §1 gives for the
static `raw_signal`: the honest question is never "did the gated arm make money," it is "did it make
more than the same strategy, on the same shortlist, without the gate."

### 1.1 Why two books, not four, and what that implies for book identity

The owner's locked decision: no `ta_gated`/`vibe_gated` screened books. The static-universe 4-arm
study already isolates each individual gate's discrimination on the card's own universe; running
`ta_gated`/`vibe_gated` again under a screened universe would re-test *the gate question*, which is
already answered elsewhere, at double the research spend, and would buy no new information about
*selection* — the only new variable this round introduces. `full_workflow` is kept because it is the
one gate configuration anyone would actually route live spend through, and `raw_signal` because it is
the null every comparison needs.

**Contract axis, restated precisely.** Per the round-plan's leaning (confirmed, not re-opened): a
screened book is identified by the **pair** `(arm, universe_source)` with `universe_source ∈ {"card",
"screen"}`, not by adding `full_workflow_screened` or similar to `WorkflowArm`. `WorkflowArm` stays
the closed 4-value union pinned in `AGENT-DESK-CONTRACT.md` and mirrored in the frontend TS union —
see `closed-unions-over-server-data-kill-pages`; a throwing exhaustiveness switch over a fifth
server-supplied string is exactly the failure mode that lesson exists to prevent.

Recon item 1 (§0) established that today's `book_path(settings, arm)` has nowhere to put a second
axis. This document assumes, and asks the manager to confirm across every build-spec worker touching
`app.workflow.book`, `app.workflow.study`, and `app.workflow.pipeline`, the following layout:

- `book_path(settings, arm, *, universe_source: Literal["card", "screen"] = "card")`.
- `universe_source="card"` (the default) resolves to **exactly today's path**,
  `data/agentdesk/workflow/book/<arm>.json` — byte-for-byte unchanged, so the in-flight 4-arm study's
  books, the paths its tests assert on, and every existing caller that does not pass the new keyword
  are untouched. This is not a style preference; it is what "the static-universe study keeps running
  untouched" (§6 below, and the round-plan's own guardrail) requires at the file-layout level, not
  only at the reporting level.
- `universe_source="screen"` resolves to `data/agentdesk/workflow/book/screen/<arm>.json` — a
  subdirectory, not a filename suffix, so the two universes are trivially distinguishable by a
  directory listing and neither can be loaded by the wrong caller through a typo'd suffix.
- `BookState` gains its own `universe_source: Literal["card", "screen"] = "card"` field, so a loaded
  file states which universe produced it independent of the path it happened to be read from — defence
  against a future refactor that gets a path wrong silently loading the other universe's ledger.
- `ArmMetrics`, `PairedComparison`, and `GateDiscrimination` (`study.py`) each gain the same
  `universe_source` field, defaulted `"card"`, following the precedent the module's own docstring
  already sets for `excess_per_exposure`/`research_cost_usd`/`net_adjusted_excess`: fields the pinned
  `AGENT-DESK-CONTRACT.md` shape does not name, added alongside it, read by a caller that wants this
  study's full output rather than only the contract's. `build_study` gains a `universe_source` keyword
  (default `"card"`) threaded to `book_mod.load_book` and to the observation-log filter in §3.

**Whoever builds Phase B's book/study plumbing must implement this exact layout, not a compatible-
looking alternative** — a suffix scheme, a separate top-level directory, or a `universe_source` value
that isn't `"card"`/`"screen"` would silently break comparability between what this document
pre-registers and what the code actually measures.

### 1.2 BH denominator, restated not inherited

The parent study's discrimination test (§4 there) evaluates three gates and therefore uses `m = 3` —
mechanically, `len(_GATES)` passed to `benjamini_hochberg` (recon item 5, §0). This study evaluates
**one** gate — `full_workflow`, the only gate configuration either screened book runs — so its
discrimination test passes a **one-element** list to `benjamini_hochberg` and gets **`m = 1`**. This
is not an oversight to reconcile against the parent study's `m = 3`; it is what testing one hypothesis
instead of three mechanically requires, per `benjamini_hochberg`'s own "denominator is how many
hypotheses were tested" contract and PROTOCOL.md §3 rule 8 ("denominator of everything tried in *this*
comparison"). A `q_value` computed with `m = 3` here would be borrowing statistical power this study
did not spend three hypotheses to earn.

---

## 2. The trap this study is built around

Identical to `WORKFLOW-STUDY-PLAN.md` §2, restated because it applies unchanged: `full_workflow` /
screened is a subset of `raw_signal` / screened, so in a rising market it will show lower total return
and lower volatility purely from being invested less, and that is not evidence of a better gate. The
same two guards apply — `adjusted_excess` (never read without `excess_per_exposure` beside it) and the
discrimination test as the actually-powered instrument (§1.2 here is that test's BH configuration).

**A second, new source of the same trap.** The selector itself is not deterministic-with-respect-to-
Phase-A-in-the-same-sense the card's static universe is: it is a frozen, deterministic *function*
(no model call, §1 of the round-plan), but its shortlist changes day to day by construction, which
means `raw_signal` / screened is not one fixed universe over the study window the way the static
`raw_signal` book trades one fixed 12-ticker list — it is a moving one. A screened arm trading *more
different names* than its static sibling is not thereby exploring more skillfully; it is doing what
the selector was built to do. Nothing in §4's decision rule credits shortlist churn as evidence of
anything by itself — see §3's divergence-rate metric, reported descriptively, never as a win condition.

---

## 3. Metrics

### 3.1 Primary — decision rule

**Paired bootstrap, p ≤ 0.10, on daily-return differences, `full_workflow` / screened vs `raw_signal`
/ screened.** Exactly `WORKFLOW-STUDY-PLAN.md` §7(a)'s test, `stationary_bootstrap_p(diffs, block=3.0,
seed=0)` over the two screened books' common priced dates — recon item 6 confirms this needs no new
floor or parameterisation.

**Plus the discrimination test on the one gate in play**, restricted to observations whose
`universe_source == "screen"` (once that field exists — recon item 3): does `full_workflow`'s
pass/fail predict the screened candidate's realised forward return, using `binomial_p_value` against
the refused set's own observed hit rate exactly as `study._discrimination` does today, with `m = 1`
per §1.2, not `m = 3`.

**Both, for the same reason `WORKFLOW-STUDY-PLAN.md` §7 gives**: a positive paired-bootstrap result
alone is consistent with the selector's shortlist happening to cut exposure into a falling day by
luck; a positive discrimination result alone is consistent with a real signal too small to survive
costs. Neither alone settles whether *dynamic selection specifically* changed the gate's worth.

### 3.2 Secondary

- **`net_adjusted_excess`** — unchanged machinery (`study._score_arm`, `research_cost_usd` charged per
  arm via `_research_call_summary`). No new cost model; a screened book's orders carry
  `created_by_run_id` exactly as a static book's do, so the existing child-run walk applies verbatim
  once `book_mod.load_book` is called with `universe_source="screen"`.

- **Cost-per-decision-changed**, defined precisely because the brief asks for precision: for every
  `CandidateObservation` with `universe_source == "screen"`, `raw_signal` / screened stages the
  candidate **whenever the observation exists at all** — `_passes_gate("raw_signal", …)` is
  unconditionally `True` (`pipeline.py:397–398`), so the screened `raw_signal` book's staged set is,
  by construction, exactly the screened observation set. `full_workflow`'s ruling on that same
  candidate is the observation's own `GateDecision` where `gate == "full_workflow"` (recon item 4:
  this is logged for every candidate regardless of which books are enabled, so no order-book diff is
  needed). A ruling **differs from raw** exactly when that `GateDecision.passed` is `False` — the gate
  refused a name `raw_signal` would have bought. `passed == True` is agreement (both arms would trade
  it), not a decision changed.

  `cost_per_decision_changed = full_workflow_screened.research_cost_usd / count(obs in screen universe
  where full_workflow gate decision is False)`. `None`, reported as such, when that count is zero — a
  gate that never refuses anything is not merely expensive per flip, it has made no flips to divide
  by, and reporting a manufactured zero-cost-per-flip would read backwards.

  **Reading it.** A gate whose cost-per-decision-changed is high relative to its own average research
  cost per candidate is a gate that mostly agrees with the raw signal and is being paid for that
  agreement, not for changing anything — this is the number that makes that fact legible, which no
  figure in the parent study currently reports.

- **Selector-vs-static shortlist divergence rate** — the round's own exposure variable, reported
  descriptively: for every decision date the selector ran, the fraction of that day's shortlist that
  is *not* in `card.universe`, and separately the fraction of `card.universe` the shortlist dropped.
  Not a pass/fail metric on its own; it exists to let a reader check that the selector is actually
  doing something (a divergence rate near zero would mean the whole round measured almost nothing) and
  to contextualise §4's null if it holds.

### 3.3 What is not reported here

Everything `WORKFLOW-STUDY-PLAN.md` §3 already excludes — annualised CAGR/Sharpe/Sortino/vol under a
year of data, per `metrics.compute`'s own contract — is excluded here for the identical reason and is
not re-argued.

---

## 4. Minimum data

**60 trading sessions and 40 gated candidates**, restricted to the `universe_source == "screen"`
observation set — the same floor `WORKFLOW-STUDY-PLAN.md` §7 sets, reused rather than re-derived,
because nothing about routing research spend to a different shortlist changes how many independent
draws a paired-bootstrap or a binomial discrimination test needs to say anything. **If the floor is
not reached, the decision rule (§5) is not evaluated at all** — any figure quoted from a
below-floor window is monitoring, labelled as such, not evidence, exactly as the parent study's §7
final paragraph states, and this document adopts that sentence rather than paraphrasing it into
something weaker.

---

## 5. Explicit pre-registered nulls

Consistent with the programme's own record — 18+ consolidated rounds finding no durable edge, the
discovery momentum selector's measured IC of −0.0073 (p = 0.892), a 21.2pp ordering-noise floor
(`PROTOCOL.md` §7) — nothing about *which universe the research is spent on* changes the prior on
whether research-gating a signal helps at all:

1. **`full_workflow` / screened's `adjusted_excess` does not differ from `raw_signal` / screened's**
   at the pre-registered threshold over the study window. *Refuted if* §6's decision rule clears.
2. **The discrimination test does not clear `q ≤ 0.10`** — a candidate's forward return is not
   predicted by whether the gate passed it, whether the candidate came from the card's static list or
   the selector's shortlist.
3. **`net_adjusted_excess` is negative for `full_workflow` / screened** once research cost is charged,
   even if gross `adjusted_excess` is positive — mirroring `WORKFLOW-STUDY-PLAN.md` §6 prediction 4.

These are stated as predictions about **the mechanism**, not about the universe: the prior this
document is testing is whether *routing the same gate at different names* changes anything, and the
programme's record gives no reason to expect it does. A positive result here would be evidence the
selection question is not orthogonal to the gate question after all — worth knowing, but not the
expected outcome.

---

## 6. Decision rule (pre-registered)

Mirroring `WORKFLOW-STUDY-PLAN.md` §7's structure exactly, restated for this study's own arms and BH
denominator:

`full_workflow` / screened is judged **worth its research spend on a dynamic universe**, and earns a
further pre-registered round, only if **BOTH**:

(a) `full_workflow` / screened's `adjusted_excess` exceeds `raw_signal` / screened's, paired bootstrap
`p ≤ 0.10` on daily-return differences (§3.1), **and**
(b) the discrimination test (§3.1, `m = 1` per §1.2) clears `q ≤ 0.10`.

- **Neither holds** → dynamic selection did not change what the gate is worth; the mechanism finding
  from the static-universe study stands unmodified by universe choice.
- **(b) but not (a)** → the gate discriminates on screened names but the screened book is not
  capturing it net of cost or exposure — an execution finding about the screened path specifically,
  not a selection finding.
- **(a) but not (b)** → most likely exposure luck on a moving shortlist, which §2's second trap
  specifically warns is easier to manufacture here than on a fixed universe; re-run on a fresh window
  before crediting it.

Reading either arm before the §4 floor is reached is monitoring, not evidence, per §4.

---

## 7. Guardrails

1. **Phase B is a new run cohort.** Both screened books start flat at `STARTING_CASH` on Phase B's
   first live day. They are never blended into the in-flight 4-arm study's figures, its equity curves,
   or its `net_adjusted_excess` totals — a clean break, not a fifth and sixth arm of that study.
2. **The static-universe 4-arm study keeps running untouched and is secondary here, explicitly
   under-powered, descriptive only.** It answers a different question (does the gate help on the
   card's own list) and is reported alongside this study's results only as context, never averaged or
   pooled with them. It is secondary for a structural reason, not a convenience one: it started
   earlier, so its static arms may be carrying positions opened before this round began, while the
   screened books start flat — the two cohorts are not comparable session-for-session, and treating a
   staggered-start comparison as primary would misattribute a starting-inventory difference to
   universe choice.
3. **Freeze discipline.** The selector promoted out of Phase A, its parameters, and this document's
   thresholds are fixed before Phase B's first live session. A selector edited after seeing Phase B's
   early results is a memory of Phase B, not a selector being tested by it — the same
   `rerunning-a-frozen-card-is-not-a-new-draw` lesson the parent study's §2 cites for the raw arm
   applies here to the selector itself.
4. **What counts as one measurement.** One Phase B run, on one frozen selector, over one study window,
   evaluated once against §6's decision rule, is one measurement — not one per day it happens to be
   re-read, and not one per re-run of a deterministic replay over the same stored decisions
   (`app.workflow.replay.run_decision_log` is deterministic given a fixed decision log, exactly as the
   parent study's engine-honesty control assumes).
5. **PROTOCOL.md §6 promotion does not mechanically apply, and the r21 analogy needs its own argument,
   not a borrowed one.** A selector is not a `StrategyCard`; §6's file-move rule (`base/` /
   `candidates/` / `retired/`, two-consecutive-rounds, new-windows) has no object here to move. Under
   r21's posture (Gate L + Gate C as floors, adoption an owner judgement, nothing promoted
   mechanically), the analogous stance for Phase B is: **the owner decides whether to adopt the
   selector into the live default, informed by §6's decision rule, not bound by it.**

   The argument for why this is *more* warranted here than for a single card, not merely equally
   warranted: r21 suspended §6 because a shorter mandate horizon has less discriminating power per
   window (~20×) than the sample-count gain from more windows buys back (~2.5×), and because the
   multiple-comparison denominator rises sharply once the comparison set grows (PROTOCOL.md §3 rule
   8). Phase A already ran that exact trade in a worse direction: **8 entrants** (6 selectors + 2
   controls), graded at **daily cadence** over roughly 500 decision dates, on a **12-ticker-scale**
   candidate pool — a search across more hypotheses, at higher frequency, over a narrower cross-
   section than a single `StrategyCard`'s multi-year multi-window backtest ever was. A search shaped
   like that is *more* prone to finding a spurious winner than the single-card case r21 was written
   about, not less. A mechanical promotion rule applied to Phase B's outcome — "if §6's decision rule
   clears, adopt the selector live" — would launder exactly the kind of noise r21 already refused to
   let §6 launder, through a search that is structurally more exposed to it. §6's own text ("a rule
   that promotes on a margin the same document calls meaningless is a rule that launders noise into
   the library") applies here with the margin risk raised, not lowered, by the search's shape.

---

## 8. Free add-on: shadow-logging the non-promoted entrants

At zero incremental LLM cost — `app.discovery.selector`/`candidates` calls are deterministic and
price-only, no model in the loop (round-plan §1's honesty anchor) — every one of Phase A's
**non-promoted** entrants (the 5 losing selectors plus whichever control did not become the frozen
baseline) computes its own daily shortlist against the same candidate pool, for the same decision
dates Phase B actually runs on, and that shortlist is logged (not staged, not researched, not traded)
alongside the observation log.

**What gets logged, per entrant per decision date:** the entrant's own shortlist symbols and ranks,
the regime label in effect that day, and — for shortlist symbols that overlap the promoted selector's
own shortlist or `card.universe` — whether the candidate that day's real `CandidateObservation` exists
for that symbol (so a later round can look up the real forward return without re-pricing anything).
No child research run, no gate ruling, no order — this is a counterfactual shortlist record, not a
counterfactual trade record, seeded now so the next round's Phase A rerun (should there be one) has a
real live-period comparison for entrants that never got their own money.

---

## 9. Explicitly rejected design: interleaving selectors across days or weeks

Considered and rejected — recorded so it is not re-proposed, per the round-plan's own instruction.

**Why it looks appealing:** running multiple selectors within one Phase B window, alternating by day
or week, looks like it buys more coverage per unit of calendar time.

**Why it does not work:**

1. **Deterministic selectors gain no sample variance from alternation.** A selector is a fixed function
   of stored data as of a date — the same selector re-run on the same day always returns the same
   shortlist. Alternating which selector is "live" on which day does not average over draws of
   anything; there is no draw. It only decides, day by day, whose deterministic answer gets tested that
   day.
2. **It partitions the calendar by regime, not by selector quality.** Whichever selector happens to be
   "on" during the bull days of the window wins on total return regardless of anything about how it
   selects — this is exactly the mechanical exposure trap §2 already warns about, applied across
   selectors instead of across gates.
3. **It churns the tax/wash-sale and switch logic daily**, contaminating the one metric (§3.2's
   divergence rate, and any churn accounting Phase A's own report already computes) that is supposed
   to describe how much a selector moves the shortlist around on its own. A shortlist that changes
   because the *selector in charge* changed every few days looks identical, in the churn log, to a
   shortlist that changes because the selector itself is unstable — the two causes become
   unattributable exactly where attribution is the point.

One selector, frozen for the whole Phase B window, is the design that keeps the comparison in §6
interpretable.

---

## 10. What this study cannot settle

Inherited from `WORKFLOW-STUDY-PLAN.md` §8 without change, plus one addition specific to this study:

- **Power**, **one model draw per decision**, **tax realism**, **fill-realism drift with uptime**, and
  **regime thresholds as judgements** — identical caveats, identical reasoning, not restated.
- **One card at a time, and now one selector at a time.** The registry serialises workflow runs; this
  measures one strategy's chain on one frozen selector's shortlist, not the roster's, and not the
  selector catalogue's.
- **New to this study: the selector's own quality is Phase A's question, not this one's.** A null
  result here (§5) says the *gate* is not worth more on a dynamic universe than a static one; it does
  not re-litigate whether the promoted selector itself has skill — Phase A already pre-registered that
  question separately, under its own IC-based null, and this document does not re-test it.

Nothing in this study is promotable to a live default on its own — see §7.5. A positive result buys a
further pre-registered round on a fresh window and an owner decision informed by, not bound by, this
one.
