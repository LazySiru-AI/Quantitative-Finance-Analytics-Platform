# Agent Workflow — Dynamic Universe Build Specification

**Status: SPEC ONLY, then BUILT.** This document specified what Phase B would build; that build has
since shipped.
**Build status (2026-09-01):** BUILT — commits d75792b (feature), be6b67b (hysteresis), 679272d
(book routing), e35c967 (screen_top_n), bc5f178/ce4006b (daily step), 865de91 (backfill), 106ba5f
(screen_entry_rule). Sections below are the pre-build design and are kept verbatim as the
pre-registration; where they say "not built"/"flagged, not built", see `docs/AGENT-DESK-CONTRACT.md`
for the current surface.

Scope: the `universe_select` stage, the `app.workflow.universe` module, the config/schema/contract
deltas that plumb `universe_mode` through the pipeline, and the backward-compatibility and test plan
for all of it. This document does **not** re-specify the Phase B "research-spend policy" (necessity
gates, TTL cache, correlation-dedup, tax-gate interaction with research) — that is a separate worker's
document against the same pipeline; the seam between the two is called out explicitly in §7 and §9.

Every signature and line number below was read from the tree at
`<repo>` on 2026-08-31, not assumed from the
round plan.

---

## 0. Recon corrections

Corrections to the brief that follow from actually reading the code, in the order they matter to an
implementer:

1. **`select_universe`'s signature as guessed by the round plan and the brief creates a circular
   import; it must change.** The brief's sketch is
   `select_universe(card, regime, *, settings, as_of, config) -> tuple[str, ...]` where `config` reads
   naturally as `WorkflowConfig` (`backend/app/workflow/pipeline.py:107-119`). But `pipeline.py`
   imports `app.workflow.universe` as a module (the same pattern it already uses for `book_mod`,
   `candidates_mod`, `regime_mod`, `taxcheck_mod`, `verdict_mod` — see `pipeline.py:51-59`), so
   `universe.py` importing `WorkflowConfig` back from `pipeline.py` at module scope is
   `pipeline -> universe -> pipeline`, a real cycle. `app.workflow.taxcheck` already establishes the
   fix for exactly this shape — its own module docstring (`taxcheck.py:41-45`): *"`app.workflow.book`,
   `book_models.py` and `regime.py` are being written concurrently and their exact shapes are not
   final... `PositionLot`, `RecentSale` and `TargetCardSpec` below are this module's own minimal,
   frozen input types; the orchestrator is responsible for projecting whatever the real ledger... into
   these shapes."* §2 below defines `universe.UniverseSelectConfig`, a small frozen type owned by
   `universe.py` itself, and has `pipeline.py` project three `WorkflowConfig` fields into it at the
   call site. This is not a stylistic choice, it is what makes the module importable at all.

2. **The round plan's own two documents disagree on the literal string: `"screened"` (config field,
   round plan line ~105) vs `"screen"` (candidate provenance, round plan line ~110, and the task brief
   verbatim: `universe_mode: Literal["card","screen"] = "card"`).** This spec standardizes on
   `"screen"` everywhere — `WorkflowRunRequest.universe_mode`, `WorkflowConfig.universe_mode`,
   `CandidateObservation.universe_source` — per the brief's explicit instruction, and because `"screen"`
   is what the round plan itself uses for the field that actually persists (`CandidateObservation`).
   Whoever authorizes Phase B should fix the round-plan doc's prose to match before it is used as a
   pre-registration record.

3. **The taxcheck question (brief's open question 3 / recon item, "should a switch evaluation consider
   the screened universe") is not actually open — the pipeline's own stage order forces the answer.**
   `_choose_card` (`pipeline.py:642-679`), which calls `taxcheck_mod.evaluate_switch` with
   `TargetCardSpec(universe=frozenset(target_card.universe))`, runs inside `_stage_strategy_select`
   (`pipeline.py:578-602`) — **before** the new `universe_select` stage would run. The screened universe
   for whichever card the regime map picks does not exist yet at the moment the switch is evaluated.
   Even setting sequencing aside, using a screened universe here would be wrong: `evaluate_switch`
   decides which currently-held symbols the *new card* no longer wants, and that judgment has to be
   stable day over day for the same card or the tax gate's own churn limiter
   (`MIN_DAYS_BETWEEN_SWITCHES`, `taxcheck.py:113-118`) is fighting a universe that renarrows on its own
   schedule. §6 states this as a hard "no" with both reasons, not a recommendation.

4. **Test file location.** The brief says `backend/tests/`; the actual suite is at
   `Investing dashboard\tests\` (repo-root `tests/`, imported as the `tests` package — see
   `pytest.ini:29-34`, which puts both `.` and `backend` on `pythonpath` for exactly this reason). All
   test-plan paths in §8 are corrected to the real location.

5. **`GateName` (`app.workflow.candidates.GateName`) is not touched by this design**, despite the round
   plan's language about "a screened name the rule rejects is logged, not traded" reading as if it
   implies a new gate. §5 explains why entry-rule-rejected screened names are recorded in the
   `universe_select`/`candidate_scan` stage `output_md`, never as a `CandidateObservation` row — adding
   a fourth `GateName` member would be the same closed-union hazard the brief already warns about for
   `WorkflowArm` (`docs/design/closed-unions-kill-pages` lesson, cited in the brief itself), just on a
   different Literal.

6. **`CandidateObservation.universe_source` needs no migration and no read-side special-casing.**
   `CandidateObservation` is a frozen Pydantic model with `extra="forbid"` (`candidates.py:84-85`).
   `extra="forbid"` rejects *unknown* keys present in the JSON; it does not require every model field to
   be present. A field added with a default (`universe_source: Literal["card", "screen"] = "card"`)
   is filled from its default on every pre-existing JSONL row the moment `model_validate_json` parses
   it (`candidates.py:158`, inside `_read_all`). This is exactly how `entry_rank: int = 0` already
   behaves for older rows. No JSONL rewrite, no version field, nothing to backfill.

7. **`BookState.universe_source` (the book-layout question) also needs no schema bump**, for the
   identical Pydantic-default reason, and because — see §4 — the plumbing this document owns writes
   *new* files at a *new* path for screened books; it never rewrites the four existing
   `data/agentdesk/workflow/book/<arm>.json` files. `BOOK_SCHEMA_VERSION` (`book_models.py:78`) stays
   `1`.

8. **`StrategyCard.universe` is capped at 12 symbols** (`Field(min_length=1, max_length=12)`,
   `backend/app/tournament/models.py:201`). This design never constructs a new `StrategyCard`, so the
   cap is irrelevant to it — the screened shortlist is a plain `tuple[str, ...]` threaded through
   `_scan_signals`, never assigned back onto `card.universe`. Noted only because an implementer who
   reaches for "just build a card with the screened universe" will hit that validator immediately.

9. **An existing test's monkeypatch breaks under the new `_scan_signals` signature and must be updated,
   not just extended.** `tests/test_workflow_pipeline.py`'s `stub_desk` fixture
   (line 86) does
   `monkeypatch.setattr(pipeline, "_scan_signals", lambda card, *, settings, as_of: list(ctl.firing))`.
   §3's new `_scan_signals(card, *, settings, as_of, universe=None)` call site in
   `_stage_candidate_scan` passes `universe=ctx.universe` unconditionally. The existing lambda has no
   `universe` parameter and would raise `TypeError` on every test that runs through `stub_desk` the
   moment this stage change lands. §8 lists the exact one-line fix.

---

## 1. Data flow after the change

Nine run-level stages (was eight); `universe_select` is new. Per-symbol `research_<SYM>` and
`vibe_<SYM>` stages still splice in after the scan, unchanged in shape.

```
regime_call (L0)
  -> strategy_select (L1)          [card keeps entry/exit/stop/sizing rules; taxcheck runs HERE,
                                     against the card's static universe -- see recon #3]
  -> universe_select (L2)          [NEW. card mode: ctx.universe = card.universe, unchanged.
                                     screen mode: ctx.universe = discovery-selector shortlist]
  -> candidate_scan (L3)           [_scan_signals(card, universe=ctx.universe) -- entry rule is a
                                     hard filter over whichever universe was selected]
  -> research_{SYM} (L4)           [spliced per candidate; unchanged]
  -> followup_questions (L5)
  -> vibe_{SYM} (L6)               [spliced per candidate; unchanged]
  -> entry_plan (L7)
  -> stage_orders (L8)             [writes CandidateObservation with universe_source=config.universe_mode;
                                     books written to card-path or screen-path per arm]
```

Every layer number from `strategy_select` onward shifts by +1 versus today's table
(`docs/AGENT-DESK-CONTRACT.md` lines 284-293: `candidate_scan`=2, `followup_questions`=4,
`vibe_{SYM}`=5, `entry_plan`=6, `stage_orders`=7). Nothing in the codebase hardcodes a layer number
outside `pipeline.py` itself — `frontend/src/pages/AgentWorkflow.tsx`'s `groupByLayer`
(lines 115-126) sorts whatever layer values it is handed, and no test asserts a specific integer
(`tests/test_workflow_pipeline.py` asserts stage-id *sets*, never layers) — so the renumbering is safe
but must be applied consistently in `_FIXED_STAGES` and `_splice_symbol_stages`.

```
depends_on chain:
  universe_select   depends_on=("strategy_select",)
  candidate_scan    depends_on=("universe_select",)     [was ("strategy_select",)]
  research_{SYM}    depends_on=("candidate_scan",)       [unchanged]
```

---

## 2. Module: `app.workflow.universe` (new file, `backend/app/workflow/universe.py`)

```python
"""Dynamic ticker selection for the Agent Workflow desk -- wraps app.discovery.candidates and
app.discovery.selector verbatim; does not reimplement either. See recon #1 for why this module owns
its own config type instead of importing WorkflowConfig from app.workflow.pipeline."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.discovery.candidates import sector_candidates, theme_candidates
from app.discovery.selector import RANK_KEYS, select
from app.tournament.models import StrategyCard
from app.workflow.regime import RegimeCall

__all__ = ["CANDIDATE_POOLS", "UniverseSelectConfig", "select_universe"]

logger = logging.getLogger(__name__)

CandidatePool = Literal["sector-etf", "theme-etf"]

#: The only two pools this round supports -- both from app.discovery.candidates, both ETF rosters.
#: Single-stock pools are out of scope: the bar store holds no delisted names (see that module's own
#: docstring, StoredETFCandidates), so a single-stock CandidateSet would be survivor-biased by
#: construction until a point-in-time constituent feed exists.
CANDIDATE_POOLS: tuple[CandidatePool, ...] = ("sector-etf", "theme-etf")


class UniverseSelectConfig(BaseModel):
    """This module's own minimal input shape -- see recon #1. `app.workflow.pipeline` projects three
    WorkflowConfig fields into this at the universe_select stage's call site; nothing here imports
    WorkflowConfig."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_pool: CandidatePool
    rank_key: str
    """Must be a key of app.discovery.selector.RANK_KEYS. Validated at request time by
    app.workflow.service (422 on submission), not re-validated here -- see select_universe's error
    behaviour below for what happens if it is invalid anyway."""
    screen_top_n: int


def select_universe(
    card: StrategyCard,
    regime: RegimeCall,
    *,
    settings: Settings,
    as_of: dt.date,
    config: UniverseSelectConfig,
) -> tuple[str, ...]:
    """The screened shortlist for `card` at `as_of`, ranked best-first.

    Deterministic and as-of-gated: every number comes through `app.discovery.selector.select`, which
    itself never reads past `as_of` (via `AsOfMarket`). No model call -- the orchestrator-is-
    deterministic invariant (`pipeline.py`'s own module docstring) holds through this stage exactly
    like every other stage before the fan-out.

    `regime` is accepted now, for a future regime-conditioned selector (round-plan Phase A's
    bake-off, not yet run), but is NOT consulted by this round's implementation -- see §2's "regime
    conditioning" note below for why that mapping is deliberately deferred rather than stubbed in.
    `card` is accepted for the same forward-compatible reason (a future selector keyed on the card's
    own thesis/rank_by is conceivable) and is likewise not consulted today; `card.universe` plays no
    role in screen mode.

    Never raises. `rank_key` is validated at request submission (`app.workflow.service`), so a bad key
    reaching here would be a defect elsewhere in the call chain, not a normal runtime condition -- but
    this function still catches `KeyError` from `select()` (the one error `select` raises, per its own
    docstring) and degrades to an empty tuple with a logged warning, matching `_scan_signals`'s own
    "never raise on a symbol/config it cannot use" convention (`pipeline.py:270-273`). An `as_of` too
    early for any pool member to have `min_bars` history (`StoredETFCandidates.symbols_as_of`) is not
    an error either -- `select()` already returns an empty `Selection.picks` for that case, exactly as
    a real request against 1999 data should.
    """
    pool = sector_candidates(settings) if config.candidate_pool == "sector-etf" else theme_candidates(settings)
    try:
        selection = select(
            as_of,
            candidates=pool,
            settings=settings,
            top_n=config.screen_top_n,
            rank_key=config.rank_key,
            collapse=True,
        )
    except KeyError as exc:
        logger.warning("universe_select: %s; falling back to an empty shortlist", exc)
        return ()
    return selection.picks
```

**Design notes an implementer needs, not obvious from the signature:**

- `collapse=True` is hardcoded, not a fourth config field. `select()`'s own docstring and
  `app.discovery.clusters`' docstring are explicit that an uncollapsed top-N can spend two of three
  slots on one correlated pair (SMH/SOXX at ρ≈0.97). The brief's locked config additions name exactly
  three new `WorkflowRunRequest` fields (`candidate_pool`, `rank_key`, `screen_top_n`); adding a fourth
  wire knob for something that should just be the safe default is scope creep this document declines.
  If a future round wants uncollapsed screening for a specific bake-off entrant, that is a parameter on
  the *selector catalogue* (Phase A), not on this stage's wire contract.
> **Status 2026-09-01:** Partially superseded. The *primary* screen-mode path shipped as
> `selector_id` (`app.discovery.workflow_selectors.select_for_workflow`, dispatched from
> `app.workflow.universe.resolve_universe`), and that path IS regime-conditioned: each of the
> eight frozen Round-33 selectors picks its own per-regime `top_n` internally, keyed on
> `regime_label`. The recommendation below — keep `resolve_universe`'s raw `candidate_pool`/
> `rank_key` fallback path regime-blind, no `universe_regime_map.json` file — was followed
> exactly as written: that fallback path (used only when `selector_id` is omitted) still calls
> `app.discovery.selector.select`, which takes no regime input. So: regime conditioning is
> built for the primary path, still absent (by design, per this section) for the raw fallback.
- **Regime conditioning is deliberately NOT built this round.** The brief asks for a recommendation
  between extending `regime_map.json` and a new file. Recommendation: **neither, yet — keep it out of
  a file entirely until Phase A's bake-off actually names a selector worth conditioning by regime.**
  Reasoning: `regime_map.json` is validated by `load_regime_map` (`regime.py:616-664`), which raises
  `RegimeMapError` naming a missing `agent_id` — a validation shape entirely about resolving strategy
  cards. A selector-config map (`regime -> {pool, rank_key, top_n}`) validates a completely different
  vocabulary (`RANK_KEYS` membership, pool names), and conflating the two files means a `RegimeMapError`
  raised at server startup could be reporting either kind of problem, which is exactly the kind of
  ambiguous failure this codebase's other module docstrings go out of their way to avoid. A dedicated
  new file (`universe_regime_map.json`) is the right *eventual* shape (independently testable, its own
  loader, its own error type) but building it now means guessing at a mapping the bake-off hasn't
  produced yet. This round ships `select_universe` regime-blind (config is the same regardless of
  `regime.label`), takes `regime` as a parameter so the call site never has to change again once Phase
  A lands, and defers the file.

---

## 3. Changes to `backend/app/workflow/pipeline.py`

### 3.1 `_Ctx` (line 225-235)

Add one field:

```python
@dataclass
class _Ctx:
    ...
    universe: tuple[str, ...] = field(default_factory=tuple)
```

### 3.2 `_scan_signals` (line 258-285)

New signature, additive parameter, default preserves today's behaviour exactly:

```python
def _scan_signals(
    card: StrategyCard, *, settings: Settings, as_of: dt.date, universe: Sequence[str] | None = None
) -> list[str]:
    """... `universe`, when given, replaces `card.universe` as the symbols scanned -- the entry rule
    still gates every one of them, so passing a screened shortlist here is what makes the entry rule a
    hard filter over the screened set rather than a separate check. `None` (the default) scans
    `card.universe` unchanged, which is what keeps `universe_mode="card"` byte-for-byte identical to
    today."""
    ...
    scan_universe = universe if universe is not None else card.universe
    for symbol in scan_universe:
        ...
```

Only the loop's iterable changes (`for symbol in card.universe:` → `for symbol in scan_universe:`);
every line inside the loop body is untouched.

### 3.3 New stage function `_stage_universe_select`

Inserted between `_stage_strategy_select` and `_stage_candidate_scan`, same shape as its neighbours
(`with_stage` transitions, `store.save` after each):

```python
def _stage_universe_select(
    run: DeskRun, store: RunStore, ctx: _Ctx, cancel: threading.Event
) -> DeskRun:
    if cancel.is_set():
        idx = next(i for i, s in enumerate(run.stages) if s.stage_id == "universe_select")
        return _cancel_remaining(run, idx, budget=run.budget)
    run = with_stage(run, "universe_select", state="running", started_at=dt.datetime.now(dt.UTC))
    store.save(run)
    assert ctx.card is not None and ctx.regime is not None

    if ctx.config.universe_mode == "card":
        ctx.universe = tuple(ctx.card.universe)
        out = [f"# Universe: card ({ctx.card.agent_id})", "",
               f"Using the card's own universe unchanged: {', '.join(ctx.universe)}"]
        summary = f"Card universe: {len(ctx.universe)} symbol(s)."
    else:
        cfg = universe_mod.UniverseSelectConfig(
            candidate_pool=ctx.config.candidate_pool,  # validated non-None by service.py
            rank_key=ctx.config.rank_key,
            screen_top_n=ctx.config.screen_top_n,
        )
        ctx.universe = universe_mod.select_universe(
            ctx.card, ctx.regime, settings=ctx.settings, as_of=ctx.trade_date, config=cfg
        )
        out = [f"# Universe: screened ({cfg.candidate_pool}, {cfg.rank_key}, top {cfg.screen_top_n})",
               "", f"Shortlist: {', '.join(ctx.universe) if ctx.universe else '(none)'}"]
        summary = f"Screened universe: {len(ctx.universe)} symbol(s) from {cfg.candidate_pool}."

    run = with_stage(
        run, "universe_select", state="succeeded", completed_at=dt.datetime.now(dt.UTC),
        output_md="\n".join(out), summary=summary,
    )
    store.save(run)
    return run
```

Add `from app.workflow import universe as universe_mod` to the child-desk-style module imports
(`pipeline.py:51-59` already imports every workflow submodule this way).

### 3.4 `_FIXED_STAGES` (line 130-137)

```python
_FIXED_STAGES: tuple[tuple[str, AgentRole, str, int], ...] = (
    ("regime_call", "market_analyst", "Regime Call", 0),
    ("strategy_select", "research_manager", "Strategy Selection", 1),
    ("universe_select", "trader", "Universe Selection", 2),       # NEW
    ("candidate_scan", "trader", "Candidate Scan", 3),             # was layer 2
    ("followup_questions", "research_manager", "Follow-up Questions", 5),  # was layer 4
    ("entry_plan", "portfolio_manager", "Entry Plan", 7),          # was layer 6
    ("stage_orders", "portfolio_manager", "Stage Orders", 8),      # was layer 7
)
```

`role="trader"` for `universe_select`: reuses an existing `AgentRole` (the contract requires no new
roles — `docs/AGENT-DESK-CONTRACT.md` line 295), and `trader` is the role already attached to
`candidate_scan`, the stage `universe_select` most directly feeds.

### 3.5 `_splice_symbol_stages` (line 163-204)

`research` stages move from layer 3 to layer 4; `vibe` stages move from layer 5 to layer 6. No other
change — the `scan_idx`/`followup_idx` lookup logic is unaffected since it locates stages by
`stage_id`, not by layer number.

### 3.6 `_stage_candidate_scan` (line 682-709)

One-line change to the `_scan_signals` call:

```python
firing = _scan_signals(ctx.card, settings=ctx.settings, as_of=ctx.trade_date, universe=ctx.universe)
```

(`ctx.universe` is always populated by this point — `_stage_universe_select` runs immediately before
and sets it unconditionally in both branches.)

### 3.7 `run_workflow` (line 457-540)

Insert the new stage call between the existing two:

```python
run = _stage_strategy_select(run, store, ctx, cancel)
if _cancelled(run):
    return
run = _stage_universe_select(run, store, ctx, cancel)     # NEW
if _cancelled(run):
    return
run, proceed = _stage_candidate_scan(run, store, ctx, cancel)
```

### 3.8 `_stage_orders` (line 873-941)

Two changes:

1. `CandidateObservation` construction (line 882-901) gains
   `universe_source=ctx.config.universe_mode`.
2. The per-arm book load/save loop (line 905-930) needs a `universe_source` kwarg threaded through
   to `book_mod.load_book`/`book_mod.save_book` — see §4. `_stage_orders` reads
   `ctx.config.universe_mode` once and passes it to both calls unchanged for every arm in the loop; it
   does not vary per arm.

### 3.9 `WorkflowConfig` (line 106-119)

```python
@dataclass(frozen=True)
class WorkflowConfig:
    ...
    universe_mode: Literal["card", "screen"] = "card"
    candidate_pool: str | None = None
    rank_key: str | None = None
    screen_top_n: int | None = None
```

Defaults preserve every existing call site that constructs `WorkflowConfig` positionally-or-by-keyword
without these four names — in particular every `WorkflowConfig(...)` call in
`tests/test_workflow_pipeline.py` (`_run`, line 104-117) keeps working unmodified, since dataclass
fields with defaults never break an existing keyword-only construction that omits them.

### 3.10 `ALL_ARMS` / new `SCREENED_ARMS` constant

```python
ALL_ARMS: tuple[WorkflowArm, ...] = ("raw_signal", "ta_gated", "vibe_gated", "full_workflow")  # unchanged

#: The two arms Phase B runs under universe_mode="screen" -- see the round plan's own reasoning
#: (WORKFLOW-DYNAMIC-UNIVERSE-ROUND-PLAN.md §2, "Arms/books"): ta_gated/vibe_gated re-test the gate
#: question the static 4-arm study already isolates, at 2x cost, with no new information about
#: *selection*. Exported so app.workflow.service, app.workflow.book and app.workflow.study (owned by
#: the spend-policy worker's document, not this one) can share one definition of "which arms screen
#: mode is allowed to enable" rather than three.
SCREENED_ARMS: tuple[WorkflowArm, ...] = ("raw_signal", "full_workflow")
```

Add `"SCREENED_ARMS"` to `pipeline.py`'s `__all__` (line 63-72).

---

## 4. Book layout: `backend/app/workflow/book.py` / `book_models.py`

### 4.1 `book_path` (`book.py:103-111`)

```python
def book_path(settings: Settings, arm: WorkflowArm, *, universe_source: Literal["card", "screen"] = "card") -> Path:
    """`data/agentdesk/workflow/book/<arm>.json` for universe_source="card" (unchanged, every existing
    reader keeps working against the same path with no argument change required at any call site that
    does not opt in). `data/agentdesk/workflow/book/screen/<arm>.json` for universe_source="screen" --
    a new subdirectory, never colliding with a card-mode file, so no existing book is ever at risk of
    being read or overwritten by a screen-mode call."""
    base = agentdesk_dir(settings) / "workflow" / "book"
    if universe_source == "screen":
        return base / "screen" / f"{arm}.json"
    return base / f"{arm}.json"
```

### 4.2 `load_book` / `save_book` / `stage_orders` / `execute_pending` (`book.py:129-401`)

Each gains the same optional keyword, default `"card"`, threaded straight into its own `book_path`
call — no other line in any of the four functions changes. `held_lots` and `tax_summary` need no
change; they operate on an already-loaded `BookState` and are universe-source-agnostic.

### 4.3 `BookState` (`book_models.py:229-269`)

```python
class BookState(_Frozen):
    schema_version: int = BOOK_SCHEMA_VERSION   # stays 1 -- see recon #7
    arm: WorkflowArm
    universe_source: Literal["card", "screen"] = "card"   # NEW, self-describing
    ...
```

A book loaded from an existing file (no `universe_source` key at all) gets the default `"card"`,
identical reasoning to `CandidateObservation.universe_source` (recon #6). `load_book` itself does not
need to set this field explicitly on the fresh-seed path (§ `load_book`'s "no file yet" branch,
`book.py:151-162`) beyond passing it through as a constructor argument alongside `arm`, mirroring how
`arm` itself is already threaded there.

### 4.4 Call-site impact of the new keyword (backward compatibility)

Every existing caller of `book_path`/`load_book`/`save_book`/`stage_orders`/`execute_pending` omits
the new keyword and is therefore unaffected:

| Caller | File:line | Effect of this change |
|---|---|---|
| `_stage_strategy_select` → `book_mod.load_book` | `pipeline.py:586-588` | None — loads the `full_workflow` incumbent book for tax-switch purposes; always card-sourced, since it is checking the *live* book, not a hypothetical screen-mode one. |
| `_stage_orders`'s per-arm loop | `pipeline.py:906-930` | **Must** pass `universe_source=ctx.config.universe_mode` — the one call site this design changes on purpose (§3.8). |
| `GET /book` | `backend/app/api/workflow.py:164-170` | **Status 2026-09-01: built.** `GET /book` now takes an optional `?universe_source=` query param (`app/api/workflow.py:185-232`): omitted renders the four card-mode books plus any screen books that exist on disk (today's behaviour, extended); `"card"` renders only the four card books; `"screen"` renders only screen books that exist, never seeding one just by asking. See `docs/AGENT-DESK-CONTRACT.md`. |
| `POST /book/execute` | `backend/app/api/workflow.py:190-195` | Same as `GET /book` — untouched by this document, flagged for the other worker. |
| `app.workflow.loop.run_once` | `loop.py:175` (`for arm in ALL_ARMS`) | None as written — the daily autopilot only fills card-mode books until the other worker's document extends it. |
| `app.workflow.study.build_study` | `study.py:652-653` | None as written — scores only card-mode books (`arms: tuple[WorkflowArm, ...] = ALL_ARMS`, no `universe_source` param). Extending it to score screen-mode books separately (per the round plan's "screen-sourced candidates scored separately") is the other worker's document, not this one — §7 states the exact seam. |

No existing test that loads or saves a book (`tests/test_workflow_book.py`,
`tests/test_workflow_pipeline.py`'s book assertions) passes the new keyword, so none of them observe
any behaviour change.

---

## 5. `CandidateObservation` (`backend/app/workflow/candidates.py:106-141`)

```python
class CandidateObservation(_Frozen):
    ...
    universe_source: Literal["card", "screen"] = "card"   # NEW
```

Add to `candidates.py`'s module-level type alias block, next to `GateName` (line 79):

```python
UniverseSource = Literal["card", "screen"]
```

and use `UniverseSource` as the field's annotation (kept as its own name rather than importing
`Literal["card","screen"]` from `app.workflow.book_models` or `app.workflow.universe`, matching this
package's existing convention of each module owning its own Literal rather than importing one across a
boundary — see `book_models.py:72-76`'s own note on why `PriceSource` is restated rather than imported
from `app.paper.paperbroker.Fill`).

**Where the "screened-but-rule-rejected" names are recorded (recon #5):** they are never
`CandidateObservation` rows. `_scan_signals`, in screen mode, is handed `ctx.universe` (the screened
shortlist) and returns only the symbols whose entry rule fired — exactly as it does today for
`card.universe`. A shortlist member whose entry rule did not fire never becomes a `_Candidate`
(`pipeline.py:694`, `chosen = firing[:max_research_symbols]`) and therefore never reaches the
`CandidateObservation` construction in `_stage_orders`. This is a difference from the round plan's
loose language ("a screened name the rule rejects is logged") — it is recorded, but in the
`universe_select`/`candidate_scan` stages' own `output_md` (§3.3, §3.6 already print the full shortlist
and the full fired set respectively; a reader can already diff the two lists to see what the shortlist
offered and what the rule declined), not as a queryable, resolved-forward-return observation. Adding a
fourth `GateName` so entry-rule rejections could be logged and priced the same way ta_gated/vibe_gated
rejections are is a real, defensible extension — but it changes a second closed union
(`GateName`, consumed by `study.py`'s `_GATES` tuple and `_discrimination`'s BH-adjusted p-value loop,
`study.py:76, 518-571`) for a benefit (pricing the forward return of rule-rejected screened names) that
belongs to the *selector bake-off*'s own grading (Phase A already does this, for free, via
`app.discovery.exam` against the pool's own equal weight), not to this stage's plumbing. Out of scope
here; flagged for whoever eventually specs Phase A's exam extension.

---

## 6. `WorkflowRunRequest` / `WorkflowConfig` / `service.py` validation

### 6.1 `WorkflowRunRequest` (`backend/app/workflow/schemas.py:61-100`)

```python
class WorkflowRunRequest(_FrozenWire):
    ...
    universe_mode: Literal["card", "screen"] | None = None
    """`None`/omitted defaults to `"card"` -- byte-for-byte today's behaviour, so the in-flight 4-arm
    study's existing callers (and every stored run's replay) are untouched. `"screen"` runs the new
    discovery-selector shortlist through `universe_select` instead of the card's own universe."""

    candidate_pool: str | None = None
    """Required (validated, not just accepted) when `universe_mode == "screen"`; ignored otherwise.
    One of `app.workflow.universe.CANDIDATE_POOLS` (`"sector-etf"` | `"theme-etf"`)."""

    rank_key: str | None = None
    """Required when `universe_mode == "screen"`; ignored otherwise. One of
    `app.discovery.selector.RANK_KEYS` (`"mom12_1"` | `"mom6"` | `"trend"`)."""

    screen_top_n: int | None = None
    """Required (or defaulted) when `universe_mode == "screen"`; ignored otherwise. Positive int, the
    shortlist size handed to `app.discovery.selector.select`'s own `top_n`."""
```

`Literal["card", "screen"] | None` rather than a plain `str | None`: `_FrozenWire`'s `extra="forbid"`
already rejects unknown top-level keys, but nothing before this stopped an unknown *value* for a field
that names its own closed vocabulary — matching `arms_enabled: list[str]` (unchecked at the Pydantic
layer, validated in `service.py`) would defer the check to the same place, but `universe_mode` is a
genuine two-value enum unlike `arms_enabled`'s open list, so pinning it as a `Literal` gives the 422
for a typo'd value for free, before `service.py` is even reached — cheaper and more precise than the
hand-rolled check `_validate_arms` needs for an open list.

### 6.2 `WorkflowConfig` — see §3.9.

### 6.3 `service.py` validation (`backend/app/workflow/service.py`)

New constants, next to `ALL_ARMS`/`DEFAULT_*` imports (line 28-34):

```python
from app.discovery.selector import RANK_KEYS
from app.workflow.pipeline import SCREENED_ARMS
from app.workflow.universe import CANDIDATE_POOLS

DEFAULT_UNIVERSE_MODE: Literal["card", "screen"] = "card"
DEFAULT_CANDIDATE_POOL = "sector-etf"
DEFAULT_RANK_KEY = "mom12_1"
DEFAULT_SCREEN_TOP_N = 3
```

New function, same shape as `_parse_positive_decimal`/`_validate_arms` (`service.py:95-116`):

```python
def _resolve_universe(req: WorkflowRunRequest) -> tuple[str, str | None, str | None, int | None]:
    """(universe_mode, candidate_pool, rank_key, screen_top_n) -- the four WorkflowConfig fields,
    validated together because screen mode's three sub-fields are only meaningful as a group."""
    mode = req.universe_mode or DEFAULT_UNIVERSE_MODE
    if mode == "card":
        return "card", None, None, None

    pool = req.candidate_pool or DEFAULT_CANDIDATE_POOL
    if pool not in CANDIDATE_POOLS:
        raise InvalidRequest(f"unknown candidate_pool: {pool!r}; available: {', '.join(CANDIDATE_POOLS)}")

    rank_key = req.rank_key or DEFAULT_RANK_KEY
    if rank_key not in RANK_KEYS:
        raise InvalidRequest(f"unknown rank_key: {rank_key!r}; available: {', '.join(sorted(RANK_KEYS))}")

    top_n = req.screen_top_n if req.screen_top_n is not None else DEFAULT_SCREEN_TOP_N
    if top_n < 1:
        raise InvalidRequest(f"screen_top_n must be >= 1: {top_n}")

    return "screen", pool, rank_key, top_n
```

`_validate_arms` (`service.py:107-116`) gains a `mode` parameter and, when `mode == "screen"`, checks
membership against `SCREENED_ARMS` instead of `ALL_ARMS`, and defaults an omitted `arms_enabled` to
`SCREENED_ARMS` instead of `ALL_ARMS`:

```python
def _validate_arms(arms: list[str] | None, *, mode: Literal["card", "screen"]) -> tuple[str, ...]:
    universe = ALL_ARMS if mode == "card" else SCREENED_ARMS
    if arms is None:
        return universe
    if not arms:
        raise InvalidRequest("at least one arm must be enabled")
    unknown = sorted(set(arms) - set(universe))
    if unknown:
        raise InvalidRequest(
            f"unknown arm(s) for universe_mode={mode!r}: {', '.join(unknown)}; available: {', '.join(universe)}"
        )
    return tuple(arm for arm in universe if arm in arms)
```

Requesting `ta_gated`/`vibe_gated` with `universe_mode="screen"` is now a 422, not a silent no-op —
matches the round plan's explicit exclusion ("No `ta_gated`/`vibe_gated` here") as a hard validation
rule rather than a convention nothing enforces.

`start_workflow_run` (`service.py:119-189`) calls `_resolve_universe(req)` right after the existing
budget/symbol validation, passes `mode` into the corrected `_validate_arms` call, and adds all four
resolved values to both the `WorkflowConfig(...)` construction and the persisted `run.config` dict
(`service.py:142-153` and `161-173` respectively) — the same two places every other `WorkflowConfig`
field is already echoed.

### 6.4 `config_payload` (`service.py:65-92`)

Add to the returned dict, alongside the existing `default_*` keys:

```python
"universe_modes": ["card", "screen"],
"candidate_pools": list(universe_mod.CANDIDATE_POOLS),
"rank_keys": sorted(RANK_KEYS),
"default_universe_mode": DEFAULT_UNIVERSE_MODE,
"default_candidate_pool": DEFAULT_CANDIDATE_POOL,
"default_rank_key": DEFAULT_RANK_KEY,
"default_screen_top_n": DEFAULT_SCREEN_TOP_N,
```

---

## 7. Contract deltas: `docs/AGENT-DESK-CONTRACT.md`

This document is pinned; the amendment is additive text at the existing anchor points, not a rewrite.

### 7.1 `WorkflowConfig` / `WorkflowRunRequest` TS interfaces (contract lines 254-277)

```diff
 interface WorkflowConfig {
   arms: { key: WorkflowArm; label: string; blurb: string }[];
   default_budget_usd: DecimalString;
   default_per_child_budget_usd: DecimalString;
   default_max_research_symbols: number;
   default_model: string;
   agent_available: boolean;
   agent_reason: string;
   cards: { agent_id: string; label: string; purpose: string }[];
+  universe_modes: ("card" | "screen")[];        // always ["card", "screen"]
+  candidate_pools: string[];                    // "sector-etf" | "theme-etf"
+  rank_keys: string[];                          // "mom12_1" | "mom6" | "trend"
+  default_universe_mode: "card" | "screen";     // "card"
+  default_candidate_pool: string;               // "sector-etf"
+  default_rank_key: string;                     // "mom12_1"
+  default_screen_top_n: number;                 // 3
 }

 interface WorkflowRunRequest {
   agent_card_id?: string | null;
   trade_date?: string | null;
   budget_usd?: DecimalString;
   per_child_budget_usd?: DecimalString;
   max_research_symbols?: number;
   analysts?: string[];
   debate_rounds?: number;
   risk_rounds?: number;
   arms_enabled?: WorkflowArm[];
   model?: string;
+  universe_mode?: "card" | "screen";  // default "card" -- byte-for-byte today's behaviour
+  candidate_pool?: string;            // required (or defaulted) when universe_mode === "screen"
+  rank_key?: string;                  // required (or defaulted) when universe_mode === "screen"
+  screen_top_n?: number;              // required (or defaulted) when universe_mode === "screen"
 }
```

`WorkflowArm` itself (contract line 248) is **unchanged** — still exactly the four values. This is the
locked decision restated: books are keyed by `(arm, universe_source)`, not by a widened `WorkflowArm`.

### 7.2 Fixed stage table (contract lines 279-296)

```diff
 | `stage_id` | `role` | `label` | layer |
 |---|---|---|---|
 | `regime_call` | `market_analyst` | Regime Call | 0 |
 | `strategy_select` | `research_manager` | Strategy Selection | 1 |
-| `candidate_scan` | `trader` | Candidate Scan | 2 |
-| `research_{SYM}` | `research_manager` | Research · {SYM} | 3 |
-| `followup_questions` | `research_manager` | Follow-up Questions | 4 |
-| `vibe_{SYM}` | `risk_neutral` | Vibe Review · {SYM} | 5 |
-| `entry_plan` | `portfolio_manager` | Entry Plan | 6 |
-| `stage_orders` | `portfolio_manager` | Stage Orders | 7 |
+| `universe_select` | `trader` | Universe Selection | 2 |
+| `candidate_scan` | `trader` | Candidate Scan | 3 |
+| `research_{SYM}` | `research_manager` | Research · {SYM} | 4 |
+| `followup_questions` | `research_manager` | Follow-up Questions | 5 |
+| `vibe_{SYM}` | `risk_neutral` | Vibe Review · {SYM} | 6 |
+| `entry_plan` | `portfolio_manager` | Entry Plan | 7 |
+| `stage_orders` | `portfolio_manager` | Stage Orders | 8 |
```

Add a paragraph directly after this table, matching its existing prose style:

> `universe_select` is deterministic, exactly like every other stage before the fan-out — see
> `app.workflow.universe.select_universe`. In `universe_mode: "card"` it reproduces `card.universe`
> unchanged; the pipeline's behaviour, output, and every persisted artifact are byte-for-byte identical
> to a build without this stage. In `universe_mode: "screen"` its `output_md` names the candidate pool,
> rank key, top-n, and the resulting shortlist; `candidate_scan`'s own `output_md` then shows which
> shortlist members the card's entry rule accepted.

### 7.3 New subsection after "The paper book (per arm)" (contract lines 305-373)

> **Screened books (`universe_mode: "screen"`).** Exactly two additional books exist per the round
> plan, at `data/agentdesk/workflow/book/screen/raw_signal.json` and
> `data/agentdesk/workflow/book/screen/full_workflow.json` — never `ta_gated`/`vibe_gated`, and never
> at the same path as the four card-mode books. `WorkflowBook` gains one field:
> ```diff
>  interface WorkflowBook {
>    arm: WorkflowArm;
>    current_card_id: string;
>    ...
> +  universe_source: "card" | "screen";
>  }
> ```
> `GET /book` and `POST /book/execute`'s screened-book surface (a `universe_source` query parameter or
> an additional response section) is specified by the research-spend-policy build document, not here —
> this contract amendment only reserves the field and the path.

### 7.4 `CandidateObservation` is not on the wire

No contract change needed for `universe_source` on `CandidateObservation` — that type is never
serialized through `docs/AGENT-DESK-CONTRACT.md`'s TS interfaces (the candidate log has no HTTP
surface today; `study.py` reads it server-side only). Noted so nobody goes looking for it in the
contract doc.

---

## 8. Test plan

All paths corrected to the real location, `tests/` at the repo root (recon #4).

### 8.1 Existing files that need edits

| File | Change |
|---|---|
| `tests/test_workflow_pipeline.py` | `stub_desk`'s `_scan_signals` monkeypatch (line 86) must accept the new keyword: `lambda card, *, settings, as_of, universe=None: list(ctl.firing)`. Every existing test in this file continues to pass once this one line changes — none of them assert on layer numbers or the new stage, so the renumbering (§1, §3.4) is otherwise invisible to them. `_run`'s `WorkflowConfig(...)` call (line 104-117) needs no change (§3.9's new fields all default). |
| `tests/test_workflow_book.py` | No existing test breaks (§4.4) — `book_path`/`load_book`/`save_book` calls in this file all omit the new keyword and get `"card"`. |
| `tests/test_workflow_candidates.py` | No existing test breaks — `_observation()` (line 41-61) constructs `CandidateObservation` without `universe_source`, which defaults to `"card"`; none of the existing assertions touch the new field. |

### 8.2 New test cases

In `tests/test_workflow_pipeline.py` (extending `stub_desk`'s pattern):

- `test_universe_mode_card_is_byte_for_byte_unchanged` — **the load-bearing regression test.** Run the
  pipeline twice against the same `stub_desk` fixture and trade date: once with a `WorkflowConfig` that
  has no explicit `universe_mode` (picks up the dataclass default `"card"`), once with
  `universe_mode="card"` passed explicitly. Assert the two resulting `DeskRun`s are equal after
  stripping `run_id`/timestamps — specifically: same `stage_ids` set including the new
  `universe_select` stage, same `candidate_scan` `firing` list, same staged orders per arm (via
  `book_mod.load_book` for all four `ALL_ARMS`, as `test_each_arm_gates_the_same_candidate_set_differently`
  already does), same `CandidateObservation` rows via `candidates_mod.read_observations`. This is the
  test that proves the "default reproduces today's behaviour byte-for-byte" requirement is not just a
  docstring claim.
- `test_universe_select_stage_appears_between_strategy_select_and_candidate_scan` — assert `stage_ids`
  ordering (`run.stages` index of `"universe_select"` is between `"strategy_select"` and
  `"candidate_scan"`) and `depends_on` chain (§1).
- `test_screen_mode_scans_the_selector_shortlist_not_the_card_universe` — monkeypatch
  `pipeline.universe_mod.select_universe` to return a canned shortlist disjoint from the stub card's
  own `universe`, run with `universe_mode="screen"`, assert `_scan_signals`'s effective input (via the
  `candidate_scan` stage's `output_md` or a `_scan_signals` spy) is the canned shortlist, never
  `card.universe`.
- `test_screen_mode_entry_rule_still_hard_filters` — canned shortlist of 3 symbols, only one of which
  the stubbed entry rule fires on (reuse `stub_desk.firing` as the fired subset); assert
  `ctx.candidates`/staged orders contain only the fired symbol, and that the other two shortlist
  members appear nowhere in `candidates_mod.read_observations` (recon/§5 — they are logged in stage
  `output_md` only, this test pins that as the *absence* of a `CandidateObservation` row).
- `test_screen_mode_writes_universe_source_screen_on_every_observation` — assert every
  `CandidateObservation` written in a `universe_mode="screen"` run has `universe_source == "screen"`;
  a companion `test_card_mode_writes_universe_source_card` pins the default explicitly rather than
  relying on the field default alone.
- `test_screen_mode_rejects_ta_gated_and_vibe_gated_arms` (in the `service.py`-focused block, mirroring
  `test_service_rejects_unknown_arm_and_bad_budget`) — `WorkflowRunRequest(universe_mode="screen",
  arms_enabled=["ta_gated"])` raises `InvalidRequest`.
- `test_screen_mode_defaults_arms_to_screened_arms_not_all_arms` — `WorkflowRunRequest(
  universe_mode="screen")` with `arms_enabled` omitted resolves to exactly
  `pipeline.SCREENED_ARMS`, not `pipeline.ALL_ARMS`.
- `test_screen_mode_requires_valid_candidate_pool_and_rank_key` — bad `candidate_pool`/`rank_key`
  values each raise `InvalidRequest` with the offending value named, mirroring
  `test_service_rejects_unknown_arm_and_bad_budget`'s assertion style.
- `test_taxcheck_switch_evaluates_against_the_cards_static_universe_in_screen_mode_too` — the recon #3
  regression: run an auto-select `universe_mode="screen"` request through `_choose_card`'s switch path
  (same seeded-incumbent-book setup as
  `test_auto_select_feeds_the_incumbent_books_lots_into_the_tax_switch_check`, line 267-306), spy on
  `taxcheck_mod.evaluate_switch`'s `target_card` argument, and assert `target_card.universe ==
  frozenset(target_card_object.universe)` — i.e. the card's own static universe, never
  `ctx.universe`/the screened shortlist (which is not even computed yet at that point in the run).

In a new file `tests/test_workflow_universe.py` (mirrors `tests/test_workflow_candidates.py`'s
module-docstring style — one file per new module, matching the existing one-test-file-per-module
convention across this package):

- `test_select_universe_returns_the_selectors_top_n_picks` — real `sector_candidates`/`select` call
  (or a stubbed `AsOfMarket` history, matching `app.discovery`'s own test conventions) against a fixed
  `as_of`, asserting the returned tuple matches `select(...).picks` for the same parameters called
  directly.
- `test_select_universe_is_deterministic` — two calls with identical arguments return identical tuples
  (mirrors `RegimeCall`'s own determinism test referenced in `regime.py`'s docstring, same property,
  new module).
- `test_select_universe_degrades_to_empty_tuple_on_bad_rank_key` — construct a
  `UniverseSelectConfig(rank_key="not_a_real_key", ...)` directly (bypassing `service.py`'s validation
  on purpose, to test this function's own defensive floor) and assert `select_universe` returns `()`
  rather than raising.
- `test_select_universe_never_reads_past_as_of` — reuses the existing no-lookahead pattern from
  `tests/test_marketdata_cache.py` (cited by `paper/marketdata.py`'s own docstring) applied through
  `select_universe`: warm the process cache at a later `as_of`, construct `select_universe` at an
  earlier one, assert the shortlist a symbol whose price only turned favorable later would have
  produced is not selected early.

### 8.3 `docs/AGENT-DESK-CONTRACT.md`'s own test coverage

If a `tests/test_frontend_contract.py`-style drift check exists for this contract (the frontend
`api/workflow.ts`'s docstring, line 42-46, references exactly this kind of test for `DeskKind`), it
must be extended to assert `frontend/src/api/workflow.ts`'s `WorkflowRunRequest`/`WorkflowConfig`/
`WorkflowBook` TS interfaces carry the four/seven/one new fields named in §7.1/§7.3. (Confirm this
test's existence and exact assertion shape before implementing — not verified in this pass; flagged
rather than assumed, per the "verify every signature" instruction this document was written under.)

---

## 9. Blast radius and build order

| File | Change | Risk |
|---|---|---|
| `backend/app/workflow/universe.py` | New file | Low — new module, no existing caller, wraps `discovery.candidates`/`discovery.selector` which are already exam-tested. |
| `backend/app/workflow/pipeline.py` | New stage, new `_Ctx` field, `_scan_signals` signature, `_FIXED_STAGES`/`_splice_symbol_stages` layer renumbering, `WorkflowConfig` fields, `SCREENED_ARMS` constant, `_stage_orders` book-write kwarg | **Highest** — this is the file every other change routes through; the layer renumbering touches every stage's contract-pinned position, and a mistake in the `_stage_universe_select` insertion point breaks the whole run sequence, not just the new feature. |
| `backend/app/workflow/candidates.py` | One new field with a default | Low — additive, Pydantic-default-safe (recon #6). |
| `backend/app/workflow/book_models.py` | One new field with a default | Low — additive, same reasoning (recon #7). |
| `backend/app/workflow/book.py` | Optional kwarg on four functions | Low — every existing call site omits it and is unaffected (§4.4's table). |
| `backend/app/workflow/schemas.py` | Four new optional `WorkflowRunRequest` fields | Low — `extra="forbid"` on `_FrozenWire` means an old client sending none of these fields is unaffected; a `Literal["card","screen"] \| None` field with `None` default never rejects an old payload. |
| `backend/app/workflow/service.py` | New validation function, `_validate_arms` signature change, `config_payload` additions | **Medium** — `_validate_arms`'s signature change (`mode` parameter) is a breaking internal-API change if anything outside `service.py` calls it directly; confirmed nothing does (`Grep` for `_validate_arms` found only `service.py`'s own definition and call site). |
| `backend/app/api/workflow.py` | None required by this document (§4.4) | None — flagged for the spend-policy/study worker. |
| `backend/app/workflow/study.py` | None required by this document | None — flagged; `build_study` continues scoring only card-mode books until extended. |
| `backend/app/workflow/loop.py` | None required by this document | None — flagged; the daily autopilot continues filling only card-mode books. |
| `docs/AGENT-DESK-CONTRACT.md` | Additive TS interface fields, stage table renumbering, new subsection | Low as a doc, but the stage-table renumbering must land in lockstep with `pipeline.py`'s `_FIXED_STAGES` change (§9's build-order item 3) or the pinned contract goes stale on day one — the exact failure mode `docs/handoff-md-is-stale` in this repo's own memory warns about. |
| `frontend/src/api/workflow.ts` | Mirror §7.1/§7.3 TS interfaces exactly | Low in isolation, but must land in the same PR as the contract doc change per this codebase's own closed-union discipline — the brief's cited hazard (a throwing exhaustiveness check over a server-supplied string taking a page down) applies to `WorkflowArm` unchanged here, but a *drifted* `universe_source`/`universe_mode` string between backend and frontend is the same class of bug at a smaller blast radius (a form that can't submit a valid request, not a page that crashes). |
| `frontend/src/pages/AgentWorkflow.tsx` | New run-form controls: a card/screen mode toggle, and (when screen) `candidate_pool`/`rank_key`/`screen_top_n` selects populated from `config.candidate_pools`/`config.rank_keys` (§6.4); the progress board's `groupByLayer` (line 115-126) needs no change — it already sorts by whatever `layer` values a run has. | Low — additive UI, no existing control removed or renamed. |

**Build order** (each step should be its own commit, matching this repo's "Subagent + QA workflow per
phase" convention from project memory):

1. `app.workflow.universe` module + its own test file (§8.2's `test_workflow_universe.py` block) — no
   dependency on anything else in this list, can be built and tested in complete isolation.
2. `app.workflow.candidates` + `app.workflow.book_models`/`book.py` additive fields/kwargs, with their
   own backward-compat tests (§8.1's "no existing test breaks" claims turned into actual assertions,
   not just left implicit).
3. `app.workflow.pipeline` — the stage insertion, renumbering, `_scan_signals` signature, `_stage_orders`
   book-write change — **together with** the `docs/AGENT-DESK-CONTRACT.md` stage-table amendment in the
   same change, per the blast-radius note above. This is the step where
   `test_universe_mode_card_is_byte_for_byte_unchanged` must pass before anything else in this list is
   trusted.
4. `app.workflow.schemas` + `app.workflow.service` validation, with the `service.py`-focused new tests
   (§8.2).
5. Frontend: `api/workflow.ts` types, then `AgentWorkflow.tsx` form controls — after steps 3-4 are
   merged, since the frontend types must match the landed backend contract, not a moving target.

Rough sizing, reusing the round plan's own S/M/L scale (`WORKFLOW-DYNAMIC-UNIVERSE-ROUND-PLAN.md`
§4): step 1 is **S**, step 2 is **XS**, step 3 is **M** (the highest-risk step, per the table above,
warrants the QA-workflow's "prove defects" pass specifically on the renumbering and the
byte-for-byte test), step 4 is **S**, step 5 is **S**. No step in this document requires the
research-spend-policy machinery (necessity gates, TTL cache) to exist first — `universe_select` and
the hard entry-rule filter are fully functional and testable with the fan-out spending exactly as much
as it does today (every fired candidate still gets a full child run, gated only by the existing
whole-run budget cap). The spend-policy worker's document is what makes screen mode *cheaper* than
card mode; this document only makes it *different*.

---

## 10. Known hazards, applied concretely

- **Closed unions over server-supplied strings killing a page.** `WorkflowArm` stays a 4-value closed
  union on purpose (§7.1) — the orthogonal `universe_source` axis is exactly the fix this codebase
  already learned it needed. But `universe_mode`/`universe_source` are themselves new 2-value closed
  unions, on both sides of the wire (`Literal["card","screen"]` in `schemas.py`/`universe.py`, the TS
  `"card" | "screen"` in `api/workflow.ts`). Neither side should render an exhaustiveness switch that
  *throws* on an unrecognized value — `AgentWorkflow.tsx`'s existing `isRunActive` (`api/workflow.ts`
  line 294-309) is the model to copy: its `default` branch logs nothing fatal and returns a
  conservative value (`true`, "keep polling") rather than throwing. Any new frontend code that
  branches on `universe_source` (§7.3's book field) should follow that same pattern, not
  `stageStateLabel`'s pattern of an exhaustiveness check that assumes the union can never actually
  drift — `stageStateLabel` (`AgentWorkflow.tsx:88-110`) gets away with a `never` check today because
  `StageState` is fully enumerated and stable; a brand-new field arriving from a backend a frontend
  build hasn't been redeployed against yet is exactly the scenario that check would fail on if it were
  copied verbatim for a *new*, less-stable field.
- **A green test suite proving orchestration correctness, not that the app boots.** Every test in §8.2
  drives `run_workflow` in-thread against a stubbed model layer (`tests/test_workflow_pipeline.py`'s
  existing `stub_desk` pattern) — none of them start the FastAPI app or exercise
  `backend/app/main.py`'s router registration. §8.3 flags the one place this document's changes touch
  a wire contract without a corresponding app-boot check: if `docs/AGENT-DESK-CONTRACT.md`'s
  amendment (§7) is not mirrored into `frontend/src/api/workflow.ts` in the same change, every backend
  test in this document still goes green while the frontend silently cannot submit a screen-mode run —
  the same shape of gap `docs/test-suites-cannot-see-launch-config` in this repo's own memory warns
  about, one layer removed (frontend/backend drift instead of import-root drift).
- **API tests building their own app, so a missing `include_router` goes structurally untested.**
  Nothing in this document adds a new router or a new route — `app.api.workflow` is explicitly
  untouched by this document's required changes (§4.4, §9's blast-radius table). This hazard does not
  apply to this document's own scope, but it does apply to whichever document adds the screened-book
  `GET /book`/`POST /book/execute` surface next: that worker should confirm
  `backend/app/main.py` actually registers any new route the same way the existing
  `/api/workflow/runs/{run_id}/telemetry` route
  (`backend/app/api/workflow.py:88-97`) is registered, rather than relying on a test that constructs
  its own `FastAPI()` and mounts the router directly (per this codebase's own documented defect: a
  missing `include_router` in `main.py` passed all 13 tests of the suite that built its own app).
  Flagged here so it is not lost between the two documents.

---

## 11. Summary of literal names (for reconciliation with the spend-policy worker)

- **New stage id:** `universe_select` (layer 2, role `trader`, `depends_on=("strategy_select",)`).
- **New module:** `app.workflow.universe`, public surface `CANDIDATE_POOLS`, `UniverseSelectConfig`,
  `select_universe(card, regime, *, settings, as_of, config)`.
- **New `WorkflowConfig`/`WorkflowRunRequest` fields:** `universe_mode: Literal["card","screen"]`
  (default `"card"`), `candidate_pool: str | None`, `rank_key: str | None`, `screen_top_n: int | None`.
- **New `pipeline.py` constant:** `SCREENED_ARMS: tuple[WorkflowArm, ...] = ("raw_signal",
  "full_workflow")`.
- **New `CandidateObservation` field:** `universe_source: Literal["card","screen"]` (default `"card"`).
- **New `BookState` field:** `universe_source: Literal["card","screen"]` (default `"card"`).
- **New book path:** `data/agentdesk/workflow/book/screen/<arm>.json` for `arm in SCREENED_ARMS`,
  produced by `book_path(settings, arm, universe_source="screen")`; the four existing
  `data/agentdesk/workflow/book/<arm>.json` paths are untouched and remain the `universe_source="card"`
  (default) location.
- **Literal spelling standardized on `"screen"`**, not the round plan's `"screened"` (recon #2) — the
  spend-policy worker's document should use the same spelling for anything it adds (a
  necessity-gate skip reason, a study filter parameter) rather than reintroducing the round plan's
  inconsistency.
- **Taxcheck stays scoped to `card.universe`, never the screened shortlist** (recon #3) — if the
  spend-policy worker's document touches `_choose_card` or `evaluate_switch` at all, it must not
  attempt to pass a screened universe in; the shortlist does not exist yet at that point in the stage
  sequence.
- **Everything downstream of `_stage_orders` (necessity gates, TTL verdict cache, correlation-dedup,
  budget-capacity check, tax-gate-vs-research interaction) is explicitly out of this document's scope**
  — the seam is `ctx.candidates` immediately after `_stage_candidate_scan` returns (`pipeline.py:495`,
  `run, proceed = _stage_candidate_scan(...)`) and immediately before `_stage_research` is called
  (`pipeline.py:501`). A necessity-gate stage, if built as its own stage rather than folded into
  `_stage_research`'s existing per-candidate loop, would insert there, at a new layer between the
  current layers 3 (`candidate_scan`) and 4 (`research_{SYM}`) from §3.4's renumbered table — one more
  layer shift the spend-policy worker's document will need to account for if it adds a stage rather
  than a filter inside an existing one.
