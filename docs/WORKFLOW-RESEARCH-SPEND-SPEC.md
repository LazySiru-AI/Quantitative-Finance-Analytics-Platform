# Research-Spend Policy — Technical Build Specification

**Status: DESIGN ONLY, then BUILT.** This document specified what would be built to implement the
"Research-spend policy (the 'only when necessary' machinery)" line items in
`docs/WORKFLOW-DYNAMIC-UNIVERSE-ROUND-PLAN.md` §2 ("Necessity gates") and §4 ("Phase B:
necessity-gate chain + verdict cache..."); that build has since shipped.
**Build status (2026-09-01):** BUILT — commits d75792b (feature), be6b67b (hysteresis), 679272d
(book routing), e35c967 (screen_top_n), bc5f178/ce4006b (daily step), 865de91 (backfill), 106ba5f
(screen_entry_rule). Sections below are the pre-build design and are kept verbatim as the
pre-registration; where they say "not built"/"flagged, not built", see `docs/AGENT-DESK-CONTRACT.md`
for the current surface. The necessity-gate chain lives in `app.workflow.research_cache` +
`pipeline._apply_necessity_gates`; `CandidateObservation` carries `skip_reason`, `skip_detail`,
`avoided_cost_usd`, `universe_source`, and `GateDecision` carries `verdict_source`.

Every constant, signature, and file path below was read directly out of the repository at
`<repo>` on 2026-08-31. Line numbers are
omitted where the surrounding function name is unambiguous, since a spec document will
outlive any given line number.

---

## Recon corrections

The parent round-plan doc and my own brief were verified against the code; four
corrections and one architecture note came out of that pass:

1. **`study._research_cost_usd` does not exist.** The function is
   `app.workflow.study._research_call_summary(book, *, settings) -> CallCostSummary`. It
   returns token counts *and* cost, and its result feeds `ArmMetrics.research_cost_usd`
   inside `_score_arm`. Anywhere this spec says "the study bills an arm," it means this
   function.

2. **`AgentBudget.exhausted` and `.remaining_usd` are computed `@property`s, not stored
   fields**, on `app.agents.models.AgentBudget` (`cap_usd`, `spent_usd`, `calls` are the only
   real fields). Immaterial to this spec's design, but worth not miscasting in any later
   Pydantic model that mirrors the shape.

3. **The tax gate (`app.workflow.taxcheck.SwitchVerdict`) operates at card-switch
   granularity, computed once per run in `pipeline._choose_card`, not per candidate symbol.**
   The round-plan doc's gate 4 ("wash-sale-blocked ⇒ skip; churn-limiter-blocked ⇒ research
   allowed but cached") talks about it as if it were evaluated per symbol. It is not, in the
   code as it stands today: `evaluate_switch` decides whether the *whole run* may adopt a
   different card at all; if blocked (for any of its three reasons), the incumbent card keeps
   running and candidate scanning proceeds entirely on the incumbent's own universe — the
   target card's candidates are never scanned in that run. This spec treats gate 4 as
   consuming the *existing, once-per-run* `SwitchVerdict` (recorded on `ctx.switch`) and
   applying its outcome uniformly to every candidate researched under whichever card ends up
   selected. See §"Gate 4" below for the full mapping, including the third outcome
   (`blocked_near_long_term`) the brief did not name but `SwitchVerdict.outcome`'s `Literal`
   actually has.

4. **`SwitchOutcome` has four values, not three implied by the brief.** Verified in
   `taxcheck.py`: `Literal["allowed", "blocked_wash_sale", "blocked_near_long_term",
   "blocked_churn"]`. `blocked_near_long_term` (a soft, materiality-capped cost cap on
   realising a near-long-term gain) is mapped explicitly below; the brief only described
   `blocked_wash_sale` and `blocked_churn`.

5. **Architecture note — TA and Vibe research are separately budgeted children, not one
   bundled spend decision.** `pipeline._launch_ta` and `pipeline._launch_vibe` are each
   capped independently at `per_child_budget_usd` ($4 by default), in two separate stage
   loops (`_stage_research` then `_stage_vibe`), and `_stage_vibe`'s follow-up question
   (`_followup_question`) is built by interpolating `candidate.ta_rating` into its text. The
   brief's necessity-gate chain reads as if it gates *one* "paid child run" per candidate.
   Taken literally that would either (a) force TA and Vibe to always be fresh or always be
   cached together, which silently defeats Vibe's actual job — reading *current* news/price
   evidence to catch a fast-moving thesis flaw — every time TA happens to be cache-served, or
   (b) require re-deriving one combined verdict object the existing pipeline has no place to
   put. §"Cache design" below resolves this by keeping gates 1/3/4/5/6 as one shared,
   per-candidate admission precheck (computed once, ahead of both stage loops) and evaluating
   gate 2 (the cache) **separately for the TA cache and the Vibe cache**, with an explicit
   linked-invalidation rule tying the Vibe cache to the TA rating it was originally paired
   with. This is a design decision this spec is making, not a literal reading of the brief —
   flagged here so it can be argued with rather than silently adopted.

---

## 1. Gate-chain spec

### Overview and cost

All six gates plus the new weekly circuit breaker are **free** — no gate in the chain makes
a model call. Every one of them is either a pure read of already-computed state
(`ctx.regime`, `ctx.candidates`, `ctx.switch`), a deterministic disk read (a book, the
candidate log, the new cache log), or deterministic arithmetic over stored bar history
(`AsOfMarket`, `app.discovery.clusters.correlation_groups`). The only thing on the "research"
side of the ledger that costs money is `_launch_ta`/`_launch_vibe` themselves — everything
this spec adds sits strictly upstream of that call and is priced at $0 to evaluate.

### Where the chain runs

**Gate 0** (new, run-level) is checked once, at the very top of `_stage_research`, before the
per-candidate loop begins. **Gates 1, 3, 4, 5, 6** are evaluated once per candidate, in a new
function (call it `_admission_check(cand, ctx) -> AdmissionResult`) run once per candidate
*before* either `_launch_ta` or `_launch_vibe` is considered for that candidate — this is the
"shared precondition" from the recon note above. **Gate 2** (the cache) is evaluated twice
per admitted candidate: once against the TA cache before `_launch_ta`, once against the Vibe
cache before `_launch_vibe`, independently.

### Gate 0 — weekly circuit breaker (new, run-level, checked once)

- **Input:** the trailing 7 calendar days of `DeskRun.cost_usd` (== `budget.spent_usd`) across
  every stored workflow run, read via `RunStore(settings, "workflow").list_runs(limit=...)`
  filtered to `created_at >= now - 7 days`.
- **Pass/fail:** fail (block the *entire* run's research, not per-candidate) when the rolling
  sum plus this run's own `DEFAULT_BUDGET_USD` ceiling would exceed a new constant
  `WEEKLY_BUDGET_USD` (a value in the owner's stated $80–100 range; this spec proposes $90 as
  a round midpoint pending the owner's pick, expressed as its own module constant so it can be
  changed without touching gate logic).
- **On failure:** every `research_<SYM>`/`vibe_<SYM>` stage for this run is marked
  `"skipped"` with `error="weekly research budget exhausted (trailing 7d spend $X ≥
  $WEEKLY_BUDGET_USD cap)"`, and every candidate's `CandidateObservation.skip_reason` is set
  to `"weekly_budget_exhausted"` (see the taxonomy below). No candidate in this run reaches
  gate 1.
- **Independent of `DEFAULT_BUDGET_USD`:** the existing $20/run cap (gate 6) is unaffected and
  still applies underneath this — a run that clears the weekly breaker still has to clear its
  own per-run cap candidate by candidate.

### Gate 1 — entry rule fires

- **Input:** already computed. `_scan_signals` (in `_stage_candidate_scan`) has already
  filtered `card.universe` down to symbols whose entry rule fires as of `ctx.trade_date`, and
  `ctx.candidates` is already truncated to `max_research_symbols`. Every member of
  `ctx.candidates` has, by construction, already passed this gate before `_stage_research`
  ever sees it.
- **Pass/fail:** trivially true for every candidate the admission check is called on. Stated
  as its own gate (rather than silently assumed) only because the brief's ordering names it
  first and because a future caller that hands `_admission_check` a candidate list from
  somewhere other than `_stage_candidate_scan` (e.g. a screened universe per the round-plan's
  Phase B) must not skip re-verifying it.
- **Cost:** $0 (already paid for by the existing scan).

### Gate 2 — no still-valid cached verdict

See §"Cache design" for the full schema, TTL, and invalidation rules. Summarized here for
ordering purposes only:

- **Input:** a lookup by `(symbol, agent_card_id, child_kind)` into the new research-verdict
  cache (`app.workflow.research_cache`), `child_kind ∈ {"tradingagents", "vibedesk"}`.
- **Pass/fail (as an admission question, TA side):** a paid TA child launches only if no
  cache entry exists for `(symbol, agent_card_id, "tradingagents")`, or the one that exists
  has expired (TTL) or been early-invalidated (regime flip, ATR move, or absence gap).
  Otherwise the cached `ta_rating`/`ta_ok` are reused and no child launches.
- **Pass/fail (Vibe side):** identically, against `(symbol, agent_card_id, "vibedesk")`, with
  one additional rule: a Vibe cache entry is invalidated regardless of its own TTL/trigger
  state if the candidate's *effective* `ta_rating` for this cycle (whichever of fresh-or-cached
  it ends up being) differs from the `ta_rating_at_cache` the Vibe entry was originally paired
  with — because `_followup_question` embeds the TA rating into the text the cached verdict
  was answering, and a cached answer to a different question is not evidence for today's.
- **Cost:** $0 — one or two JSONL reads plus a handful of comparisons.

### Gate 3 — book capacity exists

- **Input:** `app.paper.mandate.default_mandate()` (`max_positions=8`,
  `max_single_name_weight=0.25`, `min_clip_notional=$500.00`) and the current `BookState` for
  every arm in `ctx.config.arms_enabled`, loaded via `book_mod.load_book` (already cheap, file
  reads only — no network, no model call).
- **Pass/fail:** research is admitted if **at least one** enabled arm currently has room for
  the candidate — i.e. for that arm's book, either the symbol is already held, or
  `len(open_symbols) < mandate.max_positions`, **and** `_notional_for(card)` (the equal-weight
  clip the card would size the position at) is `>= mandate.min_clip_notional`. If every
  enabled arm is simultaneously full on both counts, the candidate is refused — researching a
  name none of the arms could structurally buy spends money to inform a decision no book can
  act on.
- **Deliberately not a full replay of `PaperBroker._check_buy`'s weight-cap rule.** The
  `max_single_name_weight` check needs a live equity mark, which needs a priced
  `PaperBroker.mark()` call this pre-check does not want to pay for at candidate-admission
  time (it is cheap, but this gate's whole point is staying a static, no-network precheck).
  This gate is therefore a **heuristic admission filter**, not the authoritative accept/reject
  — `PaperBroker.submit` at fill time (`execute_pending`, the next session) remains the real,
  final check and can still reject an order this gate admitted, exactly as it does today. That
  asymmetry is intentional: a false-admit here costs at most one wasted research spend and a
  fill-time rejection; a false-reject here would silently starve a legitimate candidate of any
  research at all, which is the worse failure (see §6, failure mode 1).
- **Cost:** $0 — book loads are local file reads; `_notional_for` is arithmetic.

### Gate 4 — tax-switch gate

- **Input:** `ctx.switch` — the `SwitchVerdict` (or `None`, if no switch was even attempted
  this run because the incumbent card already matched the regime map's top pick) computed
  once in `_choose_card`, before candidate scanning.
- **Mapping, all four `SwitchOutcome` values, explicit:**

  | `SwitchVerdict.outcome` | Effect on this run's admission check |
  |---|---|
  | `"allowed"` (or `ctx.switch is None`, no switch attempted) | No block. Gate passes. |
  | `"blocked_wash_sale"` | **Hard skip, whole run.** Every candidate this run is refused with `skip_reason="tax_wash_sale_blocked"`. Rationale: an IRC §1091 disallowance is a guaranteed, quantified tax cost, not a soft estimate — the desk is stuck on a card it did not choose, and researching entry candidates under an undesired incumbent, when the target card's own candidates were never even scanned this run, spends money informing decisions under a strategy the switch logic itself flagged as currently untradeable-without-cost. |
  | `"blocked_near_long_term"` | **Soft block — research allowed.** This is a materiality-capped cost estimate (`SWITCH_TAX_COST_CAP_FRACTION = 1%` of position value), not a guaranteed IRS disallowance; the desk is still running its current (incumbent) card correctly, so researching its own candidates is ordinary business. Verdict is cached normally. |
  | `"blocked_churn"` | **Soft block — research allowed, per the brief.** `MIN_DAYS_BETWEEN_SWITCHES = 7`; the desk is temporarily held to its incumbent card by the churn limiter, not by a tax cost. Research proceeds and is cached so that when the 7-day window lifts and the target card can finally be adopted, a fresh-enough verdict is already on hand rather than starting from zero. |

- **A caveat this spec is stating plainly, not smoothing over:** because `evaluate_switch` is
  run-level, "research allowed" under `blocked_churn`/`blocked_near_long_term` still only ever
  researches the **incumbent** card's candidates (the target card was never scanned). The
  brief's phrase "research allowed and caches the verdict for when the block lifts" is
  therefore only fully realized for the incumbent's own universe, not for whatever new names
  the target card would have wanted to research the moment its switch is unblocked. Extending
  this to also scan (and necessity-gate) the target card's shortlist during a soft-blocked run
  is out of scope for this spec — it would need `_stage_candidate_scan` to run twice
  (incumbent + target) on a soft-blocked run, a real pipeline change this document is not
  authorizing.
- **Cost:** $0 — `ctx.switch` is already computed; this gate only reads it.

### Gate 5 — not a correlation-duplicate

- **Input:** `app.discovery.clusters.correlation_groups(symbols, as_of, settings=...,
  threshold=DEFAULT_THRESHOLD)` with `DEFAULT_THRESHOLD = 0.95` (verified in
  `clusters.py`), called once per admission pass over the union of: every symbol already held
  in any enabled arm's book, plus every candidate already admitted earlier in this same
  candidate loop (candidates are processed in `entry_rank` order, so "already researched this
  round" means "ranked ahead of this one and already cleared gate 5 itself").
- **Pass/fail:** a candidate is refused if `correlation_groups` places it in the same group
  (ρ ≥ 0.95, transitively via single-linkage) as an already-held or already-admitted symbol.
  `collapse_to_one_per_group` is the natural helper here, applied over the rank-ordered
  candidate list plus held symbols standing in as pre-admitted group members.
- **Cost:** $0 in dollars, but non-trivial CPU — `correlation_groups` is O(n²) pairwise
  Pearson correlations over trailing 252-day return series for every symbol in the combined
  set (held + candidates). At `max_research_symbols = 3` plus `max_positions = 8`, that is at
  most 11 symbols, ~55 pairs — negligible in practice, called out only because it is the one
  gate whose cost is not literally zero work, just zero *dollars*.

### Gate 6 — remaining budget funds one more child (existing backstop, unchanged, stays last)

- **Input:** `budget.cap_usd - budget.spent_usd` (the running `AgentBudget` threaded through
  `run_workflow`) vs `ctx.config.per_child_budget_usd`.
- **Pass/fail:** unchanged from today's code — `_stage_research` already does exactly this
  (`if remaining < per_child: skip with error=f"workflow budget exhausted ({remaining} <
  {per_child})"`). This spec keeps the check, keeps its position last in the chain (a backstop
  should be the last thing that can say no, after every cheaper reason has already had its
  chance to say no first — checking it earlier would waste none of this chain's free
  evaluations, but ordering it last matches "cheapest checks first, backstop last" from the
  brief and keeps the existing message format stable for any caller already parsing it).
- **Applies independently to the TA launch and the Vibe launch** (each is its own `$4`-capped
  child, so a candidate that clears every other gate can still have its TA child launch and
  its Vibe child refused on this same run, if the run's remaining budget runs out in between —
  this already happens in the current code's two separate stage loops and is preserved as-is).
- **Cost:** $0.

### Skip-reason taxonomy

Exactly these literal string values, used as `CandidateObservation.skip_reason`:

```
"weekly_budget_exhausted"   # Gate 0 — run-level, applies to every candidate this run
"no_book_capacity"          # Gate 3
"tax_wash_sale_blocked"     # Gate 4, outcome == "blocked_wash_sale"
"correlation_duplicate"     # Gate 5
"budget_exhausted"          # Gate 6 (existing backstop wording preserved in the stage error;
                             # this is the machine-parseable code for the same event)
```

`None` (the field's default) means the candidate was **not** hard-skipped — it was admitted
into research, whether the resulting research turned out fresh or cache-served (that
distinction lives on `GateDecision.verdict_source`, not here — see §2). Gate 4's
`blocked_near_long_term`/`blocked_churn` soft-block outcomes are *not* skip reasons, precisely
because they do not skip anything.

`"cache_hit"` is deliberately **not** in this list. A cache hit is not a refusal — the
candidate is fully admitted and gets a ruling, just from reused evidence instead of a fresh
child run. Collapsing "declined to research" and "answered from cache" into one taxonomy
would be exactly the kind of fact-collapsing the brief calls out by name ("cache hit (N
sessions remaining)" is a *success* case, not a skip); it is represented instead by
`GateDecision.verdict_source == "cached"` (§2) plus `CandidateObservation.avoided_cost_usd`
(§4).

---

## 2. Cache design

### Why not `app.tradingagents.memory`

`MemoryEntryModel` (in `backend/app/tradingagents/memory.py`) is the desk's own
outcome-resolution log: it exists to let the **portfolio manager** read back its own past
decisions and their realised returns (`lessons_for_prompt`), and its `resolve_pending` step
**spends a model call** (a `reflector` turn) the moment an entry ages past `_HOLDING_DAYS`.
Three concrete reasons it is not a fit for a "should we skip research" cache:

1. **It costs money to resolve.** A necessity-gate cache must be free to *check*; consulting
   `memory.py`'s log for "is this still fresh" would be fine (reads are free), but its own
   resolution step is a paid reflector call this feature has no reason to trigger just to
   answer "do we already know this."
2. **It is keyed by `symbol` alone, with no `agent_card_id`, no regime, no ATR reference, and
   no Vibe verdict at all.** A workflow candidate's cache key needs `(symbol, agent_card_id,
   child_kind)`, and the invalidation triggers need a regime label and an ATR reading captured
   *at decision time* — none of which `MemoryEntryModel` carries or should be extended to
   carry, since that module is shared by every direct (non-workflow) call to the TA desk too;
   bolting workflow-specific caching fields onto it would leak one caller's concerns into a
   file every other TA-desk caller also reads.
3. **Its own docstring is explicit about its job**: "the desk's own record of what it decided
   and what actually happened, read back by the portfolio manager alone." A necessity-gate
   cache is a different kind of record — "would a fresh call agree with what we already have"
   — read by the *workflow orchestrator*, not by any TA-desk stage's prompt.

**Recommendation: a new sibling module, `app.workflow.research_cache`**, following the exact
JSONL-append/atomic-rewrite convention `app.workflow.candidates` and
`app.tradingagents.memory` both already use (`_write_all` via a uuid-suffixed staging file
then `os.replace`), at `data/agentdesk/workflow/research_cache.jsonl` (nested under
`agentdesk_dir`, matching `book.py`'s own placement reasoning for the workflow feature's
footprint).

### Schema

```python
class ResearchVerdictCacheEntry(_Frozen):
    cache_id: str
    symbol: str
    agent_card_id: str
    child_kind: Literal["tradingagents", "vibedesk"]

    decision_date: dt.date
    """The trade_date this verdict was produced on. TTL is anchored here and is NEVER
    slid forward on a cache hit -- see 'TTL semantics' below."""

    regime_at_cache: str
    """RegimeLabel active when this verdict was cached -- invalidation trigger A."""

    price_at_cache: Decimal
    """Symbol's close on decision_date -- reference point for trigger B."""
    atr14_at_cache: Decimal
    """ATR(14) on decision_date, from app.indicators.volatility.atr (the same free,
    deterministic reading app.workflow.regime.classify already uses internally) --
    the volatility scale trigger B measures the adverse move against."""

    # -- tradingagents entries populate these --
    ta_rating: str = ""
    ta_run_id: str = ""

    # -- vibedesk entries populate these --
    vibe_verdict: Literal["SUPPORT", "REFUTE", "INCONCLUSIVE"] | None = None
    vibe_explicit: bool = True
    vibe_run_id: str = ""
    ta_rating_at_cache: str = ""
    """vibedesk entries only -- the TA rating this Vibe verdict's follow-up question
    was actually built against. See 'Linked invalidation' below."""

    research_cost_usd: Decimal = Decimal(0)
    """What the ORIGINAL fresh child run that produced this entry cost -- carried so a
    cache hit can report avoided_cost_usd without a second lookup."""

    created_at: dt.datetime
```

`extra="forbid"`, frozen, matching every other model in this package. Written append-only
(one JSON line per fresh verdict, never mutated in place) — a `(symbol, agent_card_id,
child_kind)` key can have multiple historical rows; a reader always takes the **most recent**
row for that key as "the current cache entry," which both matches the rest of the codebase's
append-and-take-latest style and leaves a free audit trail of every verdict ever cached.

### Key structure

`(symbol, agent_card_id, child_kind)` — three-part key, `child_kind` is what makes the TA and
Vibe caches independent stores living in the same file (simpler operationally than two
files, and consistent with `candidates.jsonl` already mixing gate kinds in one log).

### TTL semantics

`CACHE_TTL_DAYS = 21`, this module's own named constant. **Must equal**
`app.workflow.candidates.HOLDING_DAYS` **and** `app.tradingagents.memory._HOLDING_DAYS`
(both verified `= 21` in the code read for this spec) — a test asserts the three-way equality,
extending the pattern `candidates.py`'s own docstring already establishes for its two-way lock
against `memory.py`. A cache entry is valid through `decision_date + dt.timedelta(days=21)`
— **calendar** days, matching both existing constants' actual implementation
(`dt.timedelta(days=HOLDING_DAYS)` in both `candidates.resolve_pending` and
`memory.resolve_pending`), not "trading sessions" despite the round-plan doc's own prose
occasionally calling it "21 sessions." That looseness in the parent doc's language is worth
flagging: 21 *calendar* days is roughly 14–15 trading sessions, not 21 — a caller reasoning
about "how many workflow runs will this cache survive" needs the calendar-day number, not the
session count the prose suggests.

**TTL does not reset on a cache hit.** `decision_date` on a cache entry is fixed at the moment
the *fresh* verdict that produced it was recorded; every subsequent hit reads and reuses that
same entry without writing a new one (a hit is a read, not a re-cache). This is deliberate:
letting a hit refresh the clock would let one fresh research call, reused every session for
weeks, drift arbitrarily stale while still reporting "TTL fresh" on every check. Anchoring the
clock to the original decision date bounds worst-case staleness at exactly 21 calendar days
regardless of hit frequency.

### The two invalidation triggers, precise thresholds

Both checked at read time even when the entry is still inside its TTL window; both apply
identically to TA and Vibe cache entries (each keyed and checked independently per
`child_kind`):

- **Trigger A — regime flip.** Invalidate if `ctx.regime.label != entry.regime_at_cache`.
  `ctx.regime` is already computed once per run, free (`app.workflow.regime.classify`, fully
  deterministic, no model call, confirmed in `regime.py`).
- **Trigger B — adverse ATR move.** The workflow only ever stages `buy` orders
  (`OrderPlan.side="buy"` throughout `pipeline.py`), so "thesis direction" is always long.
  Invalidate if `entry.price_at_cache - current_close > 2 * entry.atr14_at_cache`, where
  `current_close` is read via the same `AsOfMarket` instance the pipeline already holds for
  `ctx.trade_date`. Strict `>`, not `>=` — a move of exactly `2×ATR14` stays cached; the
  threshold is where the move first *exceeds* two ATRs, per the brief's own "greater than"
  wording. `entry.atr14_at_cache` is frozen at the original cache time (not recomputed today),
  so the volatility scale a verdict is judged against is the one that was actually in force
  when the verdict was formed.
- **Re-entry after absence = invalidated by construction.** Implemented purely from the
  existing `candidates.jsonl` log, no new storage: on a cache lookup for `(symbol,
  agent_card_id)`, find every **distinct** `decision_date` in `read_observations(settings=...)`
  filtered to `agent_card_id` in the half-open window `(entry.decision_date, today)` — these
  are "runs that actually happened" for this card since the entry was cached. If any such date
  has no `CandidateObservation` row for this specific `symbol`, that means on that day the
  entry rule did not fire for it, or it fell outside `max_research_symbols` — a genuine
  absence from the shortlist — and the cache is invalidated regardless of TTL or the other two
  triggers. This works because `append_observations` already logs **every** scanned candidate
  unconditionally, every run, before any gate rules — the log itself is the continuity record.

### Linked invalidation (Vibe cache only)

A Vibe cache entry additionally carries `ta_rating_at_cache`. At read time, after Vibe's own
TTL/regime/ATR checks pass, one more check applies: if the candidate's **effective** TA
rating for this cycle — whichever it ends up being, fresh or itself cache-served — differs
from `entry.ta_rating_at_cache`, the Vibe cache entry is invalidated anyway. Reason restated
from the recon note: `_followup_question` embeds `candidate.ta_rating` into the literal text
`_launch_vibe` sends as its question; a cached answer to a differently-worded question is not
evidence for today's question, no matter how fresh the underlying evidence was when it was
answered.

### Representing fresh vs cached downstream — `GateDecision.verdict_source`

New field on `app.workflow.candidates.GateDecision`:

```python
verdict_source: Literal["fresh", "cached", "mixed"] = "fresh"
```

- For `gate="ta_gated"`: `"fresh"` if the TA child launched this cycle, `"cached"` if the TA
  cache was hit. `"mixed"` never applies to this gate (only one child backs it).
- For `gate="vibe_gated"`: identically, against the Vibe cache.
- For `gate="full_workflow"`: `"fresh"` only if **both** underlying children were fresh this
  cycle; `"cached"` only if **both** were cache-served; `"mixed"` if one was fresh and the
  other cached (e.g. TA cache hit, but the Vibe cache was invalidated by the linked-rating
  rule and had to run fresh).
- **Default `"fresh"` is not merely a safe placeholder — it is the historically correct
  backfill value.** Every `CandidateObservation` row written before this feature existed was,
  in fact, produced by fresh research every time (no cache existed yet), so a reader replaying
  old rows under the new field gets the true answer for free, not an approximation.

### Why this distinction matters for the discrimination test

`app.workflow.study._discrimination` currently pools every resolved observation's
`GateDecision.passed` against its `forward_return_pct`, per gate, into one `passed`/`refused`
binomial test. Once cache hits exist, a `"cached"` pass is a *replay* of a decision made up to
21 days earlier, not a fresh read of today's evidence — mixing it into the same bucket as a
`"fresh"` pass conflates two different questions: "does the gate's current judgement on
today's evidence predict forward return" versus "does a stale-but-not-yet-expired judgement,
reused without re-checking anything, still predict forward return." A gate that is mostly
cache hits could show apparent discrimination that is really just the underlying symbol's own
momentum autocorrelating from whenever the verdict was fresh, which is not what §4 of
`docs/WORKFLOW-STUDY-PLAN.md` set out to measure.

**Specified fix:** `_discrimination`'s primary result (the one whose `q_value` is read against
the pre-registered threshold) is restricted to observations where the relevant
`GateDecision.verdict_source == "fresh"`. A second, explicitly diagnostic table — same
computation, restricted to `verdict_source in ("cached", "mixed")` — is reported alongside it,
labelled as descriptive only (too few cached-only observations early in the round's life to
carry its own power, and its purpose is catching failure mode 2 in §6, not confirming
anything). This is a light change to `_discrimination`'s partitioning loop (filter before
building `per_gate`), not a new statistical method.

---

## 3. Budget envelopes

All three scenarios ground out in these real constants:

- `DEFAULT_BUDGET_USD = $20.00` per run (`pipeline.py`)
- `DEFAULT_PER_CHILD_BUDGET_USD = $4.00`, applied **independently** to each TA child and each
  Vibe child (`_launch_ta`/`_launch_vibe`, each called with `budget_usd=per_child`) — so a
  single fully-fresh candidate's ceiling is $8 (TA + Vibe), not $4
- `DEFAULT_MAX_RESEARCH_SYMBOLS = 3` — a hard ceiling on symbols funded per run (this spec
  keeps it a ceiling per the brief; the necessity gates are what should bring realized spend
  under it, not a raised number)
- `STARTING_CASH = $100,000` per book (`pipeline.py`)
- The round-plan doc's own anchor figures: **observed $12–20/day today** (no necessity gates,
  every fired top-3 candidate researched fresh every run), and its own **pre-registered
  estimate of $4–6/day** once the gate chain + TTL reuse are in place.
- `WORKFLOW-STUDY-PLAN.md`'s own study floor: **60 sessions** (also this round-plan doc's own
  floor, "60 sessions / 40 gated candidates").

**Assumption stated up front:** none of the three scenarios below claims new empirical
per-call token measurements — this document was not authorized to run the pipeline. Where a
number is not directly derivable from a repository constant, it is the round-plan doc's own
pre-registered anchor, cited as such, not a new estimate invented here.

### Thorough (today's behavior — no necessity gates, or gates all miss)

Every fired candidate among the top 3 gets a fresh TA child and a fresh Vibe child, every
run, no cache reuse.

- **$/day:** $12–20 (the round-plan doc's own observed anchor; consistent with the structural
  ceiling of `3 × ($4 TA + $4 Vibe) = $24/day`, itself self-limited by the $20/run cap — the
  observed range sitting under both ceilings is expected, since real TA/Vibe runs typically
  do not spend their full per-child cap).
- **$/60-session round:** $720–$1,200 (`$12–20 × 60`).
- **As an annualized drag on the $100k book:** `$12–20/day × 252 sessions/yr ≈ $3,024–$5,040/yr`,
  i.e. **3.0%–5.0%/yr** — brackets the round-plan doc's own cited "≈3.8%/yr" figure.

### Default (necessity gates + TTL reuse, the round-plan doc's own target scenario)

Mechanism producing the reduction: with `CACHE_TTL_DAYS = 21` and a low-churn selector or a
stable `card.universe`, most of a card's shortlist stops needing fresh research within the
first ~3 weeks of the round and stays cache-served (gate 2 hits) until either the TTL expires
or one of the two triggers fires. Steady state, most days have **0–1 genuinely new** (not
previously cached, or invalidated) candidate needing the full TA+Vibe chain out of the 3-wide
fan-out, occasionally 2 on a churnier day (a regime flip invalidates every open cache entry at
once, for instance).

- **$/day:** $4–6 (round-plan doc's own pre-registered estimate; structurally consistent with
  "roughly one fresh full-chain research per day on most days, up to the ~$8 ceiling per fresh
  candidate, averaging down because Vibe's 3-call chain is materially cheaper per call than
  TA's 9–22-call chain — see §4's `analysts`/`rounds` arithmetic for why").
- **$/60-session round:** $240–$360 — a **~65–75% reduction** vs. the thorough scenario.
- **Annualized:** `$4–6 × 252 ≈ $1,008–$1,512/yr`, i.e. **≈1.0%–1.5%/yr** — the drag the round
  is trying to buy down to.

### Frugal (necessity gates + the `analysts` knob pulled down + the weekly breaker binding)

Same cache mechanics as Default, plus: any fresh TA child this scenario does launch runs with
a reduced `analysts` tuple (see §4's exact call-count arithmetic — cutting from 4 analysts to
1 removes 3 of a default run's 12 calls, ≈25% fewer TA calls per fresh candidate), and the new
`WEEKLY_BUDGET_USD` (proposed $90) circuit breaker is the binding constraint in any week where
Default-scenario spend would otherwise run hot (e.g. several regime flips in one week
invalidating many cache entries at once).

- **Typical $/day:** ≈$2–3 (Default's $4–6 scaled down by the ~25% TA-call reduction applied
  to whatever fraction of daily spend is TA vs. the unchanged Vibe cost — a rough scaling, not
  a re-derivation, stated as an assumption).
- **Hard ceiling imposed by Gate 0:** `$90/week ÷ 7 ≈ $12.9/day` peak, i.e. even a very churny
  week cannot exceed the weekly breaker regardless of how many candidates the necessity chain
  would otherwise admit.
- **$/60-session round:** typical `60 × $2–3 ≈ $120–$180`; **hard maximum** under the weekly
  breaker, `(60/7) weeks × $90–100 ≈ $771–$857` (a ceiling this scenario should never actually
  approach if the cache mechanism is working — reaching it is itself the alarm described in
  §6, failure mode 1's mirror case: the breaker binding routinely, not just as an occasional
  backstop).

---

## 4. Accounting requirements

### What must be logged per arm for honest net-of-cost reporting

`app.workflow.study` already does the hard part correctly and needs **no structural change**
for the cache case to report honestly: `_research_call_summary` walks each book's orders back
to their `created_by_run_id`, resolves `config["child_runs"]` into the actual TA/Vibe
`DeskRun`s, and sums `AgentCall.cost_usd` off their stages. A cached (skipped) candidate
produces **zero new child runs and zero new `AgentCall` records** — so on a day with heavy
cache reuse, `research_cost_usd` for that day's runs correctly comes out near zero without
this spec touching `_research_call_summary` at all. That is a genuinely good property of the
existing design, worth stating rather than assuming.

What the existing machinery does **not** surface, and this spec adds:

- **`CandidateObservation.avoided_cost_usd: Decimal = Decimal(0)`** — when a cache hit occurs
  (either child), the reused `ResearchVerdictCacheEntry.research_cost_usd` (what the
  *original* fresh run actually cost) is added onto this field on the observation row written
  for the reusing candidate. Summed across a window, this answers "how much did the cache save
  this round" without a second join against `research_cache.jsonl`. Default `0` is correct for
  every pre-existing row (nothing was ever avoided before this feature existed).
- **`ArmMetrics`/`CandidateObservation` gain no other new cost fields** — `research_cost_usd`,
  `net_adjusted_excess`, and the four `research_*_tokens` fields on `ArmMetrics` are unchanged
  and remain accurate as-is.

### The price-table prerequisite (hard blocker, not a nice-to-have)

`app.agents.client._PRICE_TABLE_PER_MILLION` has exactly one row —
`DEFAULT_MODEL = "claude-opus-5"` (`$5.00`/`$25.00` per million input/output tokens) —
verified directly in `client.py`. `estimate_cost_usd` falls back to that same row for **any**
model string it does not recognize. Two concrete consequences, both already named in the
round-plan doc and confirmed here by reading the code:

1. **A cheaper model's real savings are invisible to every dollar figure this spec adds** —
   `research_cost_usd`, `avoided_cost_usd`, the weekly-breaker rolling sum, and the frugal
   scenario's arithmetic above would all price a cheaper-tier call as if it were opus-5,
   overstating its true cost.
2. **The budget caps themselves would trip on phantom spend** — `AgentBudget.spent_usd`
   accumulates the *overstated* figure, so `per_child_budget_usd`/`DEFAULT_BUDGET_USD`/the new
   weekly breaker would all refuse research earlier than the model's real API cost warrants.

**Prerequisite, stated as a build item:** before lever (2) in the priority order below (a
cheaper model tier) can be turned on for the workflow, `_PRICE_TABLE_PER_MILLION` needs a row
for that exact model string. This is a one-line addition in `client.py`, but it is a
**dependency**, not an optional follow-up — enabling the lever without it produces numbers
this spec's own accounting requirements would then be wrong to report.

### Cheaper-run levers, in priority order, with call-count arithmetic

**(1) Reduce `analysts`/`debate_rounds`/`risk_rounds` — already plumbed, honestly accounted
today.** Read from `app.tradingagents.pipeline.build_stage_plan` and
`app.tradingagents.service`'s defaults:

- Stage count = `len(analysts selected) + 2×debate_rounds + 2 (research_manager + trader) +
  3×risk_rounds + 1 (portfolio_manager)`.
- **Default config** (all 4 analysts, `debate_rounds=1`, `risk_rounds=1` —
  `_DEFAULT_DEBATE_ROUNDS`/`_DEFAULT_RISK_ROUNDS` both `= 1`, verified in
  `tradingagents/service.py`): `4 + 2×1 + 2 + 3×1 + 1 = 12` calls.
- **Important correction to the round-plan doc's framing:** `debate_rounds` and `risk_rounds`
  are **already at the pipeline's own floor by default** (`clamp_rounds`'s range is `1..3`,
  and the default is already `1`). The lever described as "reduce debate_rounds/risk_rounds"
  has **zero headroom below the current default** unless a caller had explicitly raised them
  above 1 in the first place. The only real headroom left in this lever, starting from
  default, is **analyst count**: dropping from 4 analysts to 1 removes 3 of the 12 default
  calls (`4 → 1 = -3`), a **25% reduction** in TA call count for that candidate's fresh
  research, at the cost of losing whichever of market/sentiment/news/fundamentals analysis is
  dropped.
- Range across the pipeline's full configurable space: **9 calls minimum**
  (1 analyst, `debate_rounds=1`, `risk_rounds=1`) to **22 calls maximum** (4 analysts,
  `debate_rounds=3`, `risk_rounds=3`).
- Vibe's chain is fixed at exactly **3 calls** (`supporting_analyst`, `skeptical_analyst`,
  `referee` — verified in `followup_review.json`) — no analyst/round knob applies to it; it is
  already the cheap side of a fresh full-chain research.

**(2) Cheaper model tier — blocked until its price-table row exists (see prerequisite
above).** Once unblocked, this lever swaps the `model` string on `WorkflowConfig`/
`PipelineConfig`, priced by whatever real $/M rate its new table row states, applied against
the same call counts lever (1) already reduces.

### `cost-per-decision-changed`, precise definition

```
cost_per_decision_changed(gate) =
    ArmMetrics(arm=gate).research_cost_usd  /  count of CandidateObservation rows,
    over the same window, whose GateDecision(gate=gate).passed == False
```

**Why "differed from what the raw arm did" collapses to "gate refused"**: `raw_signal` passes
every candidate unconditionally — `pipeline._passes_gate` returns `True` immediately for
`arm == "raw_signal"`, no gate logic runs at all. So for any of the other three gates, "this
gate's ruling differed from what the ungated raw arm did" is true exactly when the gate
refused (`passed == False`) — raw would have bought it regardless, so every refusal is a
changed decision and every pass is not.

**Exact fields it is computed from**, both already produced by existing study machinery:

- **Numerator** — `ArmMetrics.research_cost_usd`, for the arm whose name matches the gate
  (`"ta_gated"`, `"vibe_gated"`, `"full_workflow"` map 1:1 to arm names of the same string —
  `_GATES` in `study.py` is already exactly the three gated arm names minus `raw_signal`).
- **Denominator** — `GateDiscrimination.refused_n` for that same gate, which
  `study._discrimination` already computes as `len(refused)` while building its own
  `per_gate` partition. No new counting logic is needed; this metric reads a value
  `_discrimination` already has and divides it into a value `_score_arm` already has.
- **Guard:** `None` when `refused_n == 0`, matching this file's existing style for
  `excess_per_exposure` (`None` when its own denominator is zero) rather than raising or
  reporting an undefined division.

A gate that never refuses anyone is spending its whole research budget on agreement with the
raw arm — this metric is specifically the number that would say so (an undefined/`None`
result with `refused_n == 0` is itself the signal, not a bug to paper over).

---

## 5. Test plan

Proposed home: `tests/test_workflow_research_spend.py` (new file; does not exist yet — this
is a spec, not an implementation).

1. **`test_gate2_cache_hit_skips_research`** — fresh verdict cached at trade date T; candidate
   re-scanned at T+5 sessions, regime unchanged, price move under `2×ATR14` → gate 2 skips
   both children, `GateDecision.verdict_source == "cached"`, `cand.ta_rating`/`vibe_verdict`
   populated from the cache entry, `avoided_cost_usd` on the observation equals the cached
   entry's `research_cost_usd`.
2. **`test_gate2_ttl_expiry_forces_fresh_research`** — same setup, re-scanned at
   `T + 22` calendar days (past `CACHE_TTL_DAYS = 21`) → cache treated as expired,
   `verdict_source == "fresh"`, both children launch.
3. **`test_gate2_regime_flip_invalidates_cache`** — cached under `regime_at_cache =
   "risk_on_trend"`; re-scanned inside TTL but `ctx.regime.label == "risk_off"` → invalidated
   despite being inside the TTL window, fresh research launches.
4. **`test_gate2_atr_adverse_move_invalidates_cache`** — three sub-cases on the same fixture
   (`price_at_cache=$100`, `atr14_at_cache=$2`): current close `$95` (move `$5 > 2×$2=$4` →
   invalidated); current close exactly `$96` (move `$4 == 2×$2`, **not** `>` → stays cached,
   confirms strict inequality); current close `$97` (move `$3 < $4` → stays cached).
5. **`test_gate2_reentry_after_absence_invalidates`** — cached at T; the symbol is absent from
   `ctx.candidates` on an intervening run at `T+3` (confirmed via a gap in
   `candidates.jsonl`'s per-date rows for that symbol); re-fires at `T+7`, still inside TTL →
   cache treated as invalidated per the "invalidated by construction" rule, not by TTL or the
   other two triggers.
6. **`test_gate2_linked_invalidation_vibe_follows_ta`** — TA cache invalidated (any trigger)
   and produces a **different** fresh `ta_rating` than `ta_rating_at_cache` on file for the
   Vibe entry; Vibe's own TTL/regime/ATR checks would otherwise still pass → Vibe cache is
   invalidated anyway, fresh Vibe research launches, `full_workflow`'s
   `GateDecision.verdict_source == "mixed"` (TA fresh, but reused nothing; actually both
   fresh here since Vibe was forced fresh too — this case should also cover the companion
   where TA cache hit reproduces the *same* rating, confirming Vibe cache is **not**
   invalidated when the rating is unchanged).
7. **`test_gate3_book_capacity_blocks_research`** — every enabled arm's book already holds 8
   positions (`max_positions`), none of which is the candidate symbol → `skip_reason ==
   "no_book_capacity"`. Companion: at least one enabled arm has an open slot → gate 3 passes.
8. **`test_gate3_min_clip_blocks_research`** — capacity available under `max_positions` in
   every enabled arm, but `_notional_for(card)` computed against current book equity falls
   below `mandate.min_clip_notional = $500.00` in every enabled arm → `skip_reason ==
   "no_book_capacity"`.
9. **`test_gate4_wash_sale_blocks_whole_run`** — `ctx.switch.outcome == "blocked_wash_sale"` →
   every candidate this run refused with `skip_reason == "tax_wash_sale_blocked"`, zero
   children launched for any candidate.
10. **`test_gate4_churn_limiter_allows_research`** — `ctx.switch.outcome == "blocked_churn"` →
    candidates researched normally (fresh, first time), verdict cached, and a follow-up
    assertion that the cache entry written is later readable by a gate-2 lookup once the
    7-day churn window (`MIN_DAYS_BETWEEN_SWITCHES`) has passed.
11. **`test_gate4_near_long_term_allows_research`** — `ctx.switch.outcome ==
    "blocked_near_long_term"` → treated like `blocked_churn`, research proceeds (this is the
    third `SwitchOutcome` value the brief did not name; the test exists specifically because
    it would be silently mishandled by an implementation that only branches on the two the
    brief mentioned).
12. **`test_gate5_correlation_duplicate_skips`** — two synthetic candidates with fabricated
    return series correlated at `ρ ≥ 0.95`; the higher-`entry_rank` one is admitted, the lower
    one is refused with `skip_reason == "correlation_duplicate"`.
13. **`test_gate5_correlation_vs_held_position`** — a candidate correlated `≥ 0.95` with a
    symbol **already held** (not another candidate this round, an existing book position) is
    refused the same way.
14. **`test_gate6_budget_backstop_unchanged`** — regression test pinning today's existing
    behavior: `remaining < per_child` → `skip_reason == "budget_exhausted"`, stage `error`
    text format unchanged from the current `_stage_research` wording, so this feature does not
    silently change an externally-visible message.
15. **`test_gate0_weekly_circuit_breaker_blocks_whole_run`** — fixture seeds several prior
    stored workflow `DeskRun`s within the trailing 7 days whose summed `cost_usd` already sits
    at or above `WEEKLY_BUDGET_USD` → the run under test skips its entire research stage
    before gate 1 is ever reached for any candidate, `skip_reason ==
    "weekly_budget_exhausted"` on every observation.
16. **`test_price_table_prerequisite_lint`** — asserts `_PRICE_TABLE_PER_MILLION` contains an
    entry for `WorkflowConfig.model` whenever that model string is not `DEFAULT_MODEL` —
    fails loudly at test time if a caller ever points the workflow at a cheaper tier before
    its price row exists, rather than letting `estimate_cost_usd`'s silent opus-5 fallback
    produce wrong numbers in production.
17. **`test_end_to_end_gate_chain_through_real_pipeline`** — the one test this spec requires
    to run through the **real** `run_workflow`/`_stage_research`/`_stage_vibe` path rather
    than calling gate functions in isolation, per the standing lesson in this project's own
    memory that unit-testing a validator only against rules-in-isolation fixtures has
    previously missed real caller behavior (`grounding-gate-false-rejections.md`). Concretely:
    two consecutive simulated `run_workflow` calls on the same card/symbol/regime fixture,
    with `tradingagents_service.start_run`/`vibedesk_service.start_run` monkeypatched to
    stubbed, deterministic children (matching `pipeline.py`'s own stated design — "imported as
    modules so a test can monkeypatch `start_run` on each"). Run 1: no cache exists, both
    children launch fresh, a cache entry is written for each. Run 2 (same symbol, same card,
    unchanged regime and price, still inside TTL): asserts **zero** new child runs launch for
    that symbol, the resulting `CandidateObservation` carries `verdict_source == "cached"` on
    both gates, and — the part an isolated gate-function test cannot prove — `_stage_orders`
    still stages a real order for whichever arms the *cached* verdict passes, confirming a
    cache hit changes spend without silently also breaking the trade path that consumes
    `cand.ta_rating`/`cand.vibe_verdict` downstream.

---

## 6. Failure modes

### 1. The policy could silently save money by starving research entirely

**Mechanism:** any combination of gates 0/3/4/5/6 refusing every fired candidate for an
extended stretch would look, from the outside, exactly like the policy succeeding — spend
drops to near zero. Two sub-cases:

- **Legitimately zero spend** (not a failure): the book is genuinely full at `max_positions`
  with no exits, or the entry rule genuinely stops firing. Zero research is the *correct*
  answer here — nothing to buy, nothing worth spending on.
- **Actual starvation** (a failure): a mis-calibrated gate refuses candidates that *should*
  have been researched — e.g. gate 3's approximate capacity precheck (§1, deliberately not a
  full weight-cap replay) wrongly reads "no room" when a real fill-time check would have
  admitted the order, or gate 5's `ρ ≥ 0.95` threshold over-collapses genuinely distinct
  opportunities into one group.

**The metric that reveals it:** the skip-reason taxonomy exists specifically so this is
distinguishable after the fact. Track a rolling histogram of `skip_reason` (plus the
`"cache_hit"`/`"fresh"` split from `verdict_source`, which is not a skip but belongs in the
same picture) over a trailing window (e.g. 2 weeks). The alarm is **not** "spend is low" —
that is `cache_hit` doing its job, or `fired_count` genuinely dropping to zero. The alarm is:
`no_book_capacity` / `correlation_duplicate` / `budget_exhausted` /
`weekly_budget_exhausted` accounting for a rising share of skips **while `fired_count`
(candidates whose entry rule fired, pre-gate) stays meaningfully above zero** — that
combination specifically says candidates the strategy itself thinks are worth entering are
being refused a first look for a reason other than "we already know the answer" or "nothing
fired." This is exactly what §1's cost-per-decision-changed metric (§4) complements: a gate
that both refuses heavily *and* shows `cost_per_decision_changed == None` (zero refusals to
divide into) cannot happen simultaneously — a rising hard-skip share with a *low*
`cost-per-decision-changed` (lots of cheap refusals) is healthy; a rising hard-skip share with
research spend still climbing (the necessity gates are being cleared but budget still runs
out fast) is the `budget_exhausted`/`weekly_budget_exhausted` variant of this same failure
mode, and is visible directly as those two skip-reason counts growing on their own.

### 2. A stale cache could survive a real thesis change

**Mechanism:** both invalidation triggers are proxies for "the world changed enough that the
old verdict might be wrong" — they are not a re-read of the actual thesis. A genuine
company-specific event (a guidance cut, a rating downgrade, an acquisition rumor) can occur
**without** moving the market-wide regime label (`regime.classify` reads SPY/macro signals,
not single-name news) **and without** yet moving price by more than `2×ATR14` — a price
reaction can lag a news event by a session or two, especially if the desk's own scan cadence
does not line up with the news. In that gap, a stale `"SUPPORT"` (or `"REFUTE"`) verdict can
survive up to the full 21-calendar-day TTL, answering a question that is no longer the real
one.

**This is exactly the gap the parent round-plan doc already named as out of scope**: no
earnings-calendar or company-event data source exists anywhere in this codebase —
`app.agentdesk.evidence.events_evidence` was verified (read directly) to call
`registry.get_events`, which returns **prediction-market** probabilities and question text,
not a corporate events calendar. There is no automated trigger this spec can add for "this
symbol reports earnings tomorrow, invalidate regardless of ATR/regime" without new
infrastructure the brief explicitly scoped out.

**Mitigating factor already in this design:** decoupling the TA and Vibe caches (§1, recon
note 5 / §2) means the *Vibe* verdict — the side of the chain whose evidence sections
explicitly include `news` — is only as stale as its **own** cache, independently of TA's. A
symbol whose TA cache is still valid but whose Vibe cache has separately expired or been
invalidated still gets a fresh news-reading check on its own schedule, which is a real
(if partial) mitigation the bundled-single-cache alternative this spec rejected would not have
had. It does not close the gap — Vibe's own TTL is still 21 days, and a fast-moving story
inside that window is still a risk — but it keeps the cheaper, news-sensitive half of the
research chain from going stale purely because the more expensive half happened to still be
cached.

**What would close it fully** (explicitly out of scope for this spec, named for the record):
a real earnings/events-calendar data source, wired as a third invalidation trigger. Until one
exists, the owner should treat the 21-day TTL as the honest worst-case staleness bound for a
company-specific development, not a number this design can currently shrink.

> **Status 2026-09-01:** Still out of scope, with one nuance — `app.market.providers.nasdaq_earnings`
> (a Nasdaq date-indexed earnings-calendar provider) has since been added to the codebase, but for an
> unrelated feature; it is not imported by `app.workflow.research_cache` or `pipeline.py`, and no
> third invalidation trigger reads it. The gap this section names is unchanged: nothing in the
> research-spend cache today invalidates on an upcoming earnings date.
